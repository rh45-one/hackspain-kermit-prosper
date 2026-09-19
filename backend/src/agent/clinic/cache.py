"""Catalogue cache: /clinic once at startup, indexed for fast, deterministic lookups.

The catalogue is generated once for the whole event and never changes, so it
is warmed exactly once and then treated as immutable. `warm()` builds every
index in local state and assigns it in one step, so a half-built cache is
never observable and concurrent readers always see a complete snapshot.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from agent.clinic.geo import haversine_km
from agent.clinic.models import (
    ClinicAppointmentType,
    ClinicCatalogue,
    ClinicLocation,
    ClinicPlan,
    ClinicProvider,
    ClinicSpecialty,
)

# Spoken language names → iso codes. Comparisons accept either form.
_LANGUAGE_CODES = {
    "español": "es",
    "espanol": "es",
    "spanish": "es",
    "castellano": "es",
    "catalán": "ca",
    "catalan": "ca",
    "català": "ca",
    "catala": "ca",
    "gallego": "gl",
    "galego": "gl",
    "galician": "gl",
    "euskera": "eu",
    "euskara": "eu",
    "basque": "eu",
    "inglés": "en",
    "ingles": "en",
    "english": "en",
}


# Spoken Spanish for each specialty, keyed by the catalogue's own id. The
# Prosper catalogue names specialties in English ("General Practice",
# "Dermatology") while every caller says "el médico de cabecera" or "el
# dermatólogo", so a perfectly ordinary Spanish ask reached find_availability
# as an unknown specialty and the agent stalled asking the caller to name it
# again. Only distinctive terms are listed: _lookup resolves a whole phrase
# through any single one of them, so indexing an ambiguous word ("médico",
# "doctor") would poison every phrase that contains it.
_SPECIALTY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "general_practice": (
        "medicina general",
        "medico de cabecera",
        "medica de cabecera",
        "medico de familia",
        "medicina de familia",
        "atencion primaria",
        "cabecera",
        "generalista",
        "familia",
        "primaria",
    ),
    "paediatrics": ("pediatria", "pediatra", "pediatrico", "pediatrica"),
    "dermatology": ("dermatologia", "dermatologo", "dermatologa"),
    "orthopaedics": (
        "traumatologia",
        "traumatologo",
        "traumatologa",
        "ortopedia",
        "ortopeda",
    ),
    "gynaecology": ("ginecologia", "ginecologo", "ginecologa", "matrona"),
    "physiotherapy": ("fisioterapia", "fisioterapeuta", "fisio", "rehabilitacion"),
}

# The catalogue's own specialty id, mapped onto the key above. Spellings vary
# between the live catalogue and the offline fixtures ("general_practice" vs
# "general"), and British and American forms both appear in the wild, so the
# synonyms attach by meaning rather than by exact id.
_SPECIALTY_ID_CANONICAL = {
    "general_practice": "general_practice",
    "general": "general_practice",
    "family_medicine": "general_practice",
    "primary_care": "general_practice",
    "paediatrics": "paediatrics",
    "pediatrics": "paediatrics",
    "dermatology": "dermatology",
    "orthopaedics": "orthopaedics",
    "orthopedics": "orthopaedics",
    "traumatology": "orthopaedics",
    "gynaecology": "gynaecology",
    "gynecology": "gynaecology",
    "physiotherapy": "physiotherapy",
    "physical_therapy": "physiotherapy",
}


def _specialty_synonyms(specialty_id: str) -> tuple[str, ...]:
    """Spoken Spanish for a catalogue specialty id, empty when unrecognised."""
    canonical = _SPECIALTY_ID_CANONICAL.get(_fold(specialty_id))
    return _SPECIALTY_SYNONYMS.get(canonical or "", ())


def _fold(text: str) -> str:
    """Accent- and case-insensitive key ('Sáez' -> 'saez'), the scorer's own rule."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold().strip()


# Words that appear in more than one plan name and so identify none of them.
_GENERIC_PLAN_WORDS = frozenset({"salud", "seguros", "seguro", "sanitaria", "sanitario"})

# What a Spanish caller says when they have no insurance at all. The catalogue
# calls it "Privado"; nobody on a telephone does.
_PLAN_SYNONYMS = {
    "particular": "privado",
    "particulares": "privado",
    "privada": "privado",
    "privado": "privado",
}


def _index_names(target: dict[str, Any], name: str, item: Any) -> None:
    """Index a record under its folded full name and each folded token.

    A caller says 'Sáez' or 'Dra. Ana Sáez'; both must find the same provider.
    The full name wins over tokens, and the first record keeps a contested
    token, so indexing stays deterministic in catalogue order.
    """
    target.setdefault(_fold(name), item)
    for token in _fold(name).replace(".", " ").split():
        if len(token) >= 3:
            target.setdefault(token, item)


def _one_edit_apart(a: str, b: str) -> bool:
    """True when two folded tokens differ by a single insert, delete or swap.

    This is how a spoken surname goes wrong: Sáez heard as Sáenz, Iglesia as
    Iglesias. Cheap because it never builds a matrix — the tokens differ by at
    most one character or the answer is no.
    """
    if a == b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    skipped = False
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
        elif skipped:
            return False
        else:
            skipped = True
        j += 1
    return True


def _language_keys(name: str) -> set[str]:
    """Comparable keys for a language name: its fold and its iso code."""
    low = _fold(name)
    keys = {low}
    if low in _LANGUAGE_CODES:
        keys.add(_LANGUAGE_CODES[low])
    if len(low) == 2:
        keys.add(low)
    return keys


class CatalogueCache:
    """Immutable after warm(); safe to share across concurrent calls."""

    def __init__(self) -> None:
        self._catalogue: ClinicCatalogue | None = None
        self.providers_by_id: dict[str, ClinicProvider] = {}
        self.providers_by_name: dict[str, ClinicProvider] = {}
        self.specialties_by_id: dict[str, ClinicSpecialty] = {}
        self.specialties_by_name: dict[str, ClinicSpecialty] = {}
        self.types_by_id: dict[str, ClinicAppointmentType] = {}
        self.types_by_name: dict[str, ClinicAppointmentType] = {}
        self.plans_by_id: dict[str, ClinicPlan] = {}
        self.plans_by_name: dict[str, ClinicPlan] = {}
        self.locations_by_id: dict[str, ClinicLocation] = {}
        self.locations_by_name: dict[str, ClinicLocation] = {}

    async def warm(self, client: Any) -> ClinicCatalogue:
        """Fetch /clinic once and publish the indexes atomically. Idempotent."""
        catalogue = await client.get_clinic()
        if not isinstance(catalogue, ClinicCatalogue):
            catalogue = ClinicCatalogue.model_validate(catalogue)

        providers_by_id: dict[str, ClinicProvider] = {}
        providers_by_name: dict[str, ClinicProvider] = {}
        for provider in catalogue.providers:
            providers_by_id[provider.id] = provider
            _index_names(providers_by_name, provider.name, provider)
        specialties_by_id: dict[str, ClinicSpecialty] = {}
        specialties_by_name: dict[str, ClinicSpecialty] = {}
        for specialty in catalogue.specialties:
            specialties_by_id[specialty.id] = specialty
            _index_names(specialties_by_name, specialty.name, specialty)
            # The id itself, so a model that passes "general_practice" through
            # instead of a spoken name resolves too.
            specialties_by_name.setdefault(_fold(specialty.id), specialty)
            for synonym in _specialty_synonyms(specialty.id):
                _index_names(specialties_by_name, synonym, specialty)
        types_by_id: dict[str, ClinicAppointmentType] = {}
        types_by_name: dict[str, ClinicAppointmentType] = {}
        for appt_type in catalogue.appointment_types:
            types_by_id[appt_type.id] = appt_type
            _index_names(types_by_name, appt_type.name, appt_type)
        plans_by_id: dict[str, ClinicPlan] = {}
        plans_by_name: dict[str, ClinicPlan] = {}
        for plan in catalogue.plans:
            plans_by_id[plan.id] = plan
            _index_names(plans_by_name, plan.name, plan)
        # "Salud" belongs to two plans and identifies neither; whichever came
        # first in the catalogue would otherwise answer to it on its own.
        for word in _GENERIC_PLAN_WORDS:
            plans_by_name.pop(word, None)
        locations_by_id: dict[str, ClinicLocation] = {}
        locations_by_name: dict[str, ClinicLocation] = {}
        for location in catalogue.locations:
            locations_by_id[location.id] = location
            _index_names(locations_by_name, location.name, location)

        # Single assignment point: readers never see a partial cache.
        self.providers_by_id = providers_by_id
        self.providers_by_name = providers_by_name
        self.specialties_by_id = specialties_by_id
        self.specialties_by_name = specialties_by_name
        self.types_by_id = types_by_id
        self.types_by_name = types_by_name
        self.plans_by_id = plans_by_id
        self.plans_by_name = plans_by_name
        self.locations_by_id = locations_by_id
        self.locations_by_name = locations_by_name
        self._catalogue = catalogue
        return catalogue

    @property
    def catalogue(self) -> ClinicCatalogue:
        if self._catalogue is None:
            raise RuntimeError("catalogue not warmed; call warm() at startup")
        return self._catalogue

    @property
    def warmed(self) -> bool:
        return self._catalogue is not None

    # ---- lookups (accent-insensitive) ------------------------------------
    @staticmethod
    def _lookup(index: dict[str, Any], name: str) -> Any | None:
        """Match a folded full name, a single token, or a set of tokens.

        'Álvaro Cid' matches via its tokens even though no indexed key equals
        it. Every token must resolve to the same record, so near-miss surnames
        ('Iglesia' vs 'Iglesias') can never collide.
        """
        key = _fold(name)
        if key in index:
            return index[key]
        tokens = [t for t in key.replace(".", " ").split() if len(t) >= 3]
        if not tokens:
            return None
        resolved: dict[int, Any] = {}
        for token in tokens:
            if token in index:
                resolved[id(index[token])] = index[token]
        if len(resolved) == 1:
            return next(iter(resolved.values()))
        return None

    def provider_by_name(self, name: str) -> ClinicProvider | None:
        return self._lookup(self.providers_by_name, name)

    def provider_by_id(self, provider_id: str) -> ClinicProvider | None:
        return self.providers_by_id.get(provider_id)

    def specialty_by_name(self, name: str) -> ClinicSpecialty | None:
        return self._lookup(self.specialties_by_name, name)

    def specialty_by_id(self, specialty_id: str) -> ClinicSpecialty | None:
        return self.specialties_by_id.get(specialty_id)

    def type_by_id(self, type_id: str) -> ClinicAppointmentType | None:
        return self.types_by_id.get(type_id)

    def type_by_name(self, name: str) -> ClinicAppointmentType | None:
        return self._lookup(self.types_by_name, name)

    def location_by_name(self, name: str) -> ClinicLocation | None:
        return self._lookup(self.locations_by_name, name)

    def location_by_id(self, location_id: str) -> ClinicLocation | None:
        return self.locations_by_id.get(location_id)

    def plan_by_name(self, name: str) -> ClinicPlan | None:
        """Resolve a plan from however the caller says it.

        Plans differ from providers here. Three of the ten carry a generic
        second word — Mapfre *Salud*, Caser *Salud*, Nueva Mutua *Sanitaria* —
        so "Sanitas Salud" resolves to two different records and the shared
        lookup rightly refuses it. There is no near-miss pair among ten plan
        names the way there is among surnames, so once the generic words are
        dropped a single remaining token is safe to trust.
        """
        exact = self._lookup(self.plans_by_name, name)
        if exact is not None:
            return exact
        folded = _fold(name)
        for word, plan_id in _PLAN_SYNONYMS.items():
            if word in folded.split():
                return self.plans_by_id.get(plan_id)
        distinctive = " ".join(t for t in folded.split() if t not in _GENERIC_PLAN_WORDS)
        if distinctive and distinctive != folded:
            return self._lookup(self.plans_by_name, distinctive)
        return None

    def plan_by_id(self, plan_id: str) -> ClinicPlan | None:
        return self.plans_by_id.get(plan_id)

    def plans_sounding_like(self, name: str) -> list[ClinicPlan]:
        """Plans whose name is a word away from what the caller seems to have said.

        A plan is one or two words over a telephone line and the line is the
        worst part of this system. "Mapfre Salud" arrived on a scored call as
        "ma phrase salue" — unsearchable, and the model invented a plan rather
        than ask. Every token of that noise is still one edit from `salud`,
        which is enough to put two real names in front of the caller.

        Deliberately does NOT resolve: "salue" is one edit from the `salud` in
        both Mapfre Salud and Caser Salud, and picking one of those would be
        the same guess in a smarter coat. It names the candidates so the agent
        can ask which. Derived from the catalogue, so a plan added tomorrow is
        offered too.
        """
        heard = [t for t in _fold(name).replace(".", " ").split() if len(t) >= 4]
        if not heard:
            return []
        found: dict[str, ClinicPlan] = {}
        for plan in self.plans_by_id.values():
            for word in _fold(plan.name).split():
                if len(word) < 4:
                    continue
                if any(word == t or _one_edit_apart(word, t) for t in heard):
                    found[plan.id] = plan
                    break
        return sorted(found.values(), key=lambda p: p.id)

    def providers_sounding_like(self, name: str) -> list[ClinicProvider]:
        """Providers whose surname is one edit from a token of ``name``.

        A spoken surname is the least reliable thing on a phone call, and this
        clinic has two pairs that differ by one letter and sit in different
        specialties — Sáez/Sáenz, Iglesia/Iglesias. Resolving one of those
        confidently is how an agent books the wrong doctor in the wrong field
        without ever noticing. Derived from the catalogue, so a pair added
        tomorrow is caught too; nothing here names anybody.
        """
        tokens = [t for t in _fold(name).replace(".", " ").split() if len(t) >= 4]
        if not tokens:
            return []
        found: dict[str, ClinicProvider] = {}
        for provider in self.providers_by_id.values():
            surnames = [t for t in _fold(provider.name).replace(".", " ").split() if len(t) >= 4]
            if any(_one_edit_apart(t, s) for t in tokens for s in surnames):
                found[provider.id] = provider
        return sorted(found.values(), key=lambda p: p.id)

    # ---- derived views ----------------------------------------------------
    def providers_for_specialty(self, specialty_id: str) -> list[ClinicProvider]:
        return [p for p in self.providers_by_id.values() if p.specialty_id == specialty_id]

    def providers_speaking(self, language: str) -> list[ClinicProvider]:
        """Providers whose language list matches the spoken name or its code."""
        wanted = _language_keys(language)
        if not wanted:
            return []
        matched = []
        for provider in self.providers_by_id.values():
            for spoken in provider.languages:
                if _language_keys(spoken) & wanted:
                    matched.append(provider)
                    break
        return matched

    def provider_ids_at_location(self, location_id: str) -> set[str]:
        """Providers who sit at a site, matched through the site's display name."""
        location = self.locations_by_id.get(location_id)
        if location is None:
            return set()
        wanted = _fold(location.name)
        return {
            p.id
            for p in self.providers_by_id.values()
            if any(_fold(name) == wanted for name in p.location_names)
        }

    def nearest_locations(self, lat: float, lng: float) -> list[tuple[ClinicLocation, float]]:
        """Locations ordered by straight-line distance from (lat, lng)."""
        scored = [
            (location, haversine_km(lat, lng, location.latitude, location.longitude))
            for location in self.locations_by_id.values()
        ]
        scored.sort(key=lambda pair: pair[1])
        return scored
