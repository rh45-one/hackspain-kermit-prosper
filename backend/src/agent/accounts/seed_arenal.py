"""The people of Clínica Arenal, and who covers whom.

Run: python -m agent.accounts.seed_arenal [--db PATH]

These are the team's own names and mobiles, put here deliberately so calls can
be tested against real handsets. Nothing here is a patient and nothing here
comes from the challenge API; it is the staff side, which the API has never
had.

The rota is the part a catalogue cannot express: the head of gynaecology being
off is only a problem until somebody works out that the junior can take the
morning. It lives in the routes — `provider_on_leave` reaches Germán — so when
a consultation loses its doctor the clinic already knows whose phone to ring,
and nobody has to work it out at seven in the morning.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent.accounts import db
from agent.accounts.store import Person, Route, Store
from agent.orgs import DEFAULT_ORG_ID

TEAM: tuple[dict[str, Any], ...] = (
    {
        "slug": "gines-martinez",
        "name": "Ginés Martínez Ruiz",
        "role": "Jefe de Ginecología",
        "detail": "Lleva el servicio y decide cuando ninguna regla decide.",
        "languages": ["es", "en"],
        "phone": "+34684360367",
        "opening": "Es el jefe de servicio: ve al grano, sabe cómo funciona esto.",
        "may_ask": "cualquier cosa del servicio de ginecología, y a quién asignar si falta alguien",
        "must_not_ask": "",
    },
    {
        "slug": "german-padua",
        "name": "Germán Padua",
        "role": "Ginecólogo Jr.",
        "detail": "Cubre el servicio cuando falta el jefe.",
        "languages": ["es", "en"],
        "phone": "+34627119059",
        "opening": "Trátale de tú. Si le llamas es porque falta el jefe de servicio.",
        "may_ask": "si puede cubrir una consulta de ginecología, y desde qué hora",
        "must_not_ask": "no le pidas que decida por el servicio: eso lo decide el jefe",
    },
    {
        "slug": "marina-vicens",
        "name": "Marina Vicens",
        "role": "Psiquiatra",
        "detail": "Salud mental. Fuera del circuito de ginecología.",
        "languages": ["es", "ca", "en"],
        "phone": "+34699510737",
        "opening": "Háblale en català si te contesta en català.",
        "may_ask": "si puede atender una urgencia de salud mental",
        "must_not_ask": "nunca le pases una consulta que no sea de lo suyo",
    },
    {
        "slug": "hugo-rodriguez",
        "name": "Hugo Rodríguez",
        "role": "Otorrinolaringólogo",
        "detail": "ORL.",
        "languages": ["es", "en"],
        "phone": "+34616645646",
        "opening": "",
        "may_ask": "si puede coger una consulta de ORL",
        "must_not_ask": "",
    },
    {
        "slug": "jose-antunez",
        "name": "Jose Antúnez",
        "role": "Podólogo",
        "detail": "Podología.",
        "languages": ["es"],
        "phone": "+34613000269",
        "opening": "",
        "may_ask": "si puede coger una consulta de podología",
        "must_not_ask": "",
    },
    # Two doctors the challenge catalogue does know, tied to it by
    # `provider_id` so a call about them resolves the same person either way,
    # plus the desk, which it has never heard of.
    {
        "slug": "carmen-ortiz",
        "name": "Dra. Carmen Ortiz Vidal",
        "role": "Medicina General",
        "detail": "Consulta en Arenal Centro. Habla català.",
        "languages": ["ca", "en", "es"],
        "phone": "",
        "provider_id": "PR01",
        "opening": "Lleva quince años aquí y prefiere que le hablen en català.",
        "may_ask": "si puede doblar una mañana de medicina general",
        "must_not_ask": "nada de guardias de noche: tiene una excedencia parcial",
    },
    {
        "slug": "pablo-requena",
        "name": "Dr. Pablo Requena",
        "role": "Medicina General",
        "detail": "Consulta en Arenal Norte.",
        "languages": ["en", "es"],
        "phone": "",
        "provider_id": "PR02",
        "opening": "",
        "may_ask": "si puede coger consultas de medicina general",
        "must_not_ask": "",
    },
    {
        "slug": "recepcion",
        "name": "Recepción",
        "role": "Mostrador",
        "detail": "Atiende y resuelve lo que no necesita un médico.",
        "languages": ["es", "en"],
        "phone": "",
        "opening": "",
        "may_ask": "cualquier cosa de agenda, coberturas o papeleo",
        "must_not_ask": "nada clínico",
    },
)

# Which of the eighteen endings reaches whom here. Anything not named keeps the
# declared default, so this replaces rather than empties.
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("provider_on_leave", "german-padua", "today"),
    ("no_availability", "gines-martinez", "today"),
    ("medical_emergency", "gines-martinez", "now"),
    ("caller_not_authorised", "gines-martinez", "today"),
    ("patient_history", "gines-martinez", "today"),
    ("referral_required", "recepcion", "today"),
    ("specialty_not_covered", "recepcion", "today"),
    ("location_not_covered", "recepcion", "today"),
    ("provider_not_in_network", "recepcion", "today"),
    ("insurer_referral_required", "recepcion", "today"),
    ("allowance_exhausted", "recepcion", "today"),
)


def seed(path: str, org_id: str = DEFAULT_ORG_ID) -> tuple[int, int]:
    """Write the team and the rota. Idempotent: run it twice, same result."""
    db.migrate(path)
    shop = Store(path)
    for person in TEAM:
        shop.upsert_person(
            org_id,
            Person(
                slug=person["slug"],
                name=person["name"],
                role=person["role"],
                detail=person.get("detail", ""),
                languages=tuple(person.get("languages", ())),
                provider_id=person.get("provider_id"),
                phone=person.get("phone", ""),
                opening=person.get("opening", ""),
                may_ask=tuple(x for x in [person.get("may_ask", "")] if x),
                must_not_ask=tuple(x for x in [person.get("must_not_ask", "")] if x),
            ),
        )
    for reason, slug, urgency in ROUTES:
        shop.upsert_route(org_id, Route(reason=reason, person_slug=slug, urgency=urgency))
    return len(TEAM), len(ROUTES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="path to platform.db")
    parser.add_argument("--org", default=DEFAULT_ORG_ID)
    args = parser.parse_args()

    from agent.config import settings

    path = args.db or str(Path(settings().data_dir) / "platform.db")
    people, routes = seed(path, args.org)
    print(f"seeded {people} people and {routes} routes into {path}")


if __name__ == "__main__":
    main()
