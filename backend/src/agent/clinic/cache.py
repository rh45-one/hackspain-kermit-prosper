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


def _fold(text: str) -> str:
    """Accent- and case-insensitive key ('Sáez' -> 'saez'), the scorer's own rule."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold().strip()


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
        return self._lookup(self.plans_by_name, name)

    def plan_by_id(self, plan_id: str) -> ClinicPlan | None:
        return self.plans_by_id.get(plan_id)

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
