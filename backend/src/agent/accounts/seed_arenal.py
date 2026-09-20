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
        "voice": "Fenrir",
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
        "voice": "Puck",
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
        "voice": "Aoede",
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
        "voice": "Orus",
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
        "voice": "Kore",
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
    # ---- the rest of the hospital -------------------------------------
    #
    # Invented, and built AROUND the five mobiles above rather than into them:
    # every one of these covers for somebody, never the other way round, so
    # the chains the team tests with still ring the handset they rang
    # yesterday. What this adds is the second line, and the specialties the
    # clinic had no name for at all.
    #
    # That gap was not cosmetic. Asked who covers a heart attack, the only
    # people on the list were a gynaecologist, a podiatrist, an ENT and a
    # psychiatrist — so a heart attack got a gynaecologist, which is exactly
    # what it looked like. A closed choice can only be as good as the set it
    # closes over.
    #
    # Compact on purpose: (slug, name, role, covers_for, detail). Everything
    # else these rows could carry is per-person copy, and a table of forty
    # people that nobody can read is a table nobody keeps true.
    *(
        {
            "slug": slug,
            "name": name,
            "role": role,
            "detail": detail,
            "languages": ["es", "en"],
            "covers_for": covers,
            "opening": "",
            "may_ask": f"si puede coger una consulta de {role.lower()}",
            "must_not_ask": "nada fuera de su especialidad",
        }
        for slug, name, role, covers, detail in (
            # Urgencias y corazón: lo que faltaba, y lo que más se nota faltando.
            ("urgencias", "Urgencias", "Urgencias", "", "Lo que no puede esperar a una consulta."),
            ("elena-bru", "Dra. Elena Bru", "Cardióloga", "urgencias", "Jefa de cardiología."),
            ("ruben-salas", "Dr. Rubén Salas", "Cardiólogo", "elena-bru", "Cardiología, segundo."),
            ("intensivos", "Medicina Intensiva", "Intensivos", "urgencias", "UCI."),
            # Ginecología: el jefe y su junior son reales; la tercera no.
            ("lucia-serrano", "Dra. Lucía Serrano", "Ginecóloga", "german-padua",
             "Tercera de ginecología. Entra cuando no están ni el jefe ni Germán."),
            # Las otras cuatro especialidades del equipo, con su segundo.
            ("andres-vila", "Dr. Andrés Vila", "Otorrinolaringólogo", "hugo-rodriguez",
             "ORL, segundo de Hugo."),
            ("nuria-cano", "Nuria Cano", "Psiquiatra", "marina-vicens",
             "Salud mental, segunda de Marina."),
            ("elena-prat", "Elena Prat", "Podóloga", "jose-antunez",
             "Podología, segunda de Jose."),
            # Y el resto del cuadro médico.
            ("traumatologia", "Dr. Iván Colom", "Traumatólogo", "urgencias", "Huesos y lesiones."),
            ("traumatologia-2", "Dra. Rosa Neira", "Traumatóloga", "traumatologia", "Traumatología, segunda."),
            ("pediatria", "Dra. Clara Bonet", "Pediatra", "urgencias", "Hasta los catorce años."),
            ("pediatria-2", "Dr. Tomás Gil", "Pediatra", "pediatria", "Pediatría, segundo."),
            ("neurologia", "Dr. Samuel Roig", "Neurólogo", "urgencias", "Cabeza y sistema nervioso."),
            ("dermatologia", "Dra. Paula Sanz", "Dermatóloga", "manager", "Piel."),
            ("oftalmologia", "Dr. Martín Cueto", "Oftalmólogo", "manager", "Ojos."),
            ("digestivo", "Dra. Irene Lamas", "Digestiva", "manager", "Aparato digestivo."),
            ("endocrino", "Dr. Álvaro Pons", "Endocrino", "manager", "Hormonas y metabolismo."),
            ("urologia", "Dr. Nacho Beltrán", "Urólogo", "manager", "Urología."),
            ("neumologia", "Dra. Sofía Arias", "Neumóloga", "urgencias", "Pulmón y respiración."),
            ("reumatologia", "Dr. Luis Ferrer", "Reumatólogo", "manager", "Articulaciones."),
            ("oncologia", "Dra. Teresa Almazán", "Oncóloga", "manager", "Oncología."),
            ("alergologia", "Dra. Noa Vidal", "Alergóloga", "urgencias", "Alergias."),
            ("rehabilitacion", "Carlos Iriarte", "Fisioterapeuta", "traumatologia", "Rehabilitación."),
            ("nutricion", "Marta Solís", "Nutricionista", "endocrino", "Nutrición."),
            ("matrona", "Rocío Vega", "Matrona", "german-padua", "Embarazo y parto."),
            ("enfermeria", "Enfermería", "Enfermería", "front_desk", "Curas, analíticas y vacunas."),
            ("analisis", "Laboratorio", "Análisis clínicos", "enfermeria", "Analíticas."),
            ("radiologia", "Dr. Jorge Mena", "Radiólogo", "urgencias", "Imagen."),
            ("anestesia", "Dra. Ana Cifuentes", "Anestesista", "intensivos", "Anestesia y quirófano."),
            ("farmacia", "Farmacia", "Farmacia", "manager", "Medicación y recetas."),
            ("trabajo-social", "Beatriz Moll", "Trabajo social", "manager", "Ayudas y gestiones."),
            ("administracion", "Administración", "Administración", "manager", "Facturación y seguros."),
        )
    ),
    # `manager` y `on_call`, no `sara-buendia` ni `medico-de-guardia`: la regla
    # es que una fila configurada reemplaza al valor declarado **con la misma
    # clave**. Con un slug nuevo aparece una Coordinación al lado de la
    # declarada en vez de en su lugar — que es exactamente lo que pasó, y se
    # veían dos Coordinaciones y dos Médicos de guardia en el grafo.
    {
        "slug": "manager",
        "name": "Sara Buendía",
        "role": "Coordinación",
        "detail": "Lleva las agendas y reparte lo que nadie ha cogido.",
        "languages": ["es", "en"],
        "covers_for": "",
        "opening": "Es quien reparte el trabajo: ve al grano.",
        "may_ask": "abrir agenda, mover consultas, buscar quién cubre",
        "must_not_ask": "nada clínico",
    },
    {
        "slug": "on_call",
        "name": "Médico de guardia",
        "role": "Guardia",
        "detail": "Fuera del horario de consulta, y el último eslabón de todas las cadenas.",
        "languages": ["es", "en"],
        "covers_for": "urgencias",
        "opening": "Está de guardia: sé breve, puede estar ocupado.",
        "may_ask": "si puede atender algo que no aguanta a mañana",
        "must_not_ask": "no le pidas cubrir agenda ordinaria",
    },
    {
        # `front_desk`, not `recepcion`: the rule is that a configured row
        # replaces the default with the SAME key. A new slug adds a second
        # Recepción beside the declared one instead of replacing it, which is
        # exactly what happened the first time this ran.
        "slug": "front_desk",
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
    # La baja de un médico llega a Germán. Ésta es la cadena con la que el
    # equipo prueba llamando de verdad, y no se toca.
    ("provider_on_leave", "german-padua", "today"),
    # `medical_emergency` NO está aquí, y su ausencia es la corrección.
    #
    # Lo estuvo: apuntaba a Ginés, jefe de ginecología. Con lo cual la clínica
    # contestaba a un infarto mandándolo a ginecología — que es exactamente lo
    # que se vio al probarlo. El valor declarado en `clinic/graph.py` siempre
    # fue el correcto ("Cuelga y llama al 112"), así que lo que había que
    # hacer no era escribir una regla mejor sino borrar la peor. Al no estar
    # en esta tabla, vuelve a mandar el declarado.
    ("no_availability", "manager", "today"),
    ("caller_not_authorised", "manager", "today"),
    ("patient_history", "gines-martinez", "today"),
    ("referral_required", "front_desk", "today"),
    ("specialty_not_covered", "manager", "today"),
    ("location_not_covered", "front_desk", "today"),
    ("provider_not_in_network", "administracion", "today"),
    ("insurer_referral_required", "administracion", "today"),
    ("allowance_exhausted", "administracion", "today"),
    ("not_eligible_age", "pediatria", "today"),
    ("type_not_offered", "manager", "queue"),
    ("clinic_closed", "on_call", "today"),
    ("location_hours", "front_desk", "queue"),
)



def seed(path: str, org_id: str = DEFAULT_ORG_ID, *, prune: bool = True) -> tuple[int, int, int]:
    """Write the team and the rota. Idempotent, and **authoritative**.

    `prune` is the part that took two production bugs to learn. An upsert-only
    seed adds and never removes, so a row this file used to declare survives
    forever in a database nobody looks at:

    * `sara-buendia` was renamed to `manager` and the old slug stayed, so the
      graph drew two Coordinaciones.
    * `medical_emergency -> gines-martinez` was deleted from `ROUTES` and the
      row stayed, so the clinic went on answering a heart attack with the head
      of **gynaecology** — after the fix, and on the deployed host, with every
      test green. The table said one thing and the volume said another.

    So anything this file no longer declares is removed. That is only safe
    because this seed owns this organisation end to end; pass `prune=False`
    for an organisation a human curates through the panel, where the seed is
    a starting point rather than the truth.

    Returns (people, routes, removed).
    """
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
                covers_for=person.get("covers_for", ""),
                voice=person.get("voice", ""),
                opening=person.get("opening", ""),
                may_ask=tuple(x for x in [person.get("may_ask", "")] if x),
                must_not_ask=tuple(x for x in [person.get("must_not_ask", "")] if x),
            ),
        )
    for reason, slug, urgency in ROUTES:
        shop.upsert_route(org_id, Route(reason=reason, person_slug=slug, urgency=urgency))

    removed = 0
    if prune:
        declared_people = {person["slug"] for person in TEAM}
        for existing in shop.list_people(org_id):
            if existing.slug not in declared_people and shop.delete_person(org_id, existing.slug):
                removed += 1
        declared_routes = {reason for reason, _slug, _urgency in ROUTES}
        for route in shop.list_routes(org_id):
            if route.reason not in declared_routes and shop.delete_route(org_id, route.reason):
                removed += 1
    return len(TEAM), len(ROUTES), removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="path to platform.db")
    parser.add_argument("--org", default=DEFAULT_ORG_ID)
    parser.add_argument(
        "--keep-undeclared",
        action="store_true",
        help="leave rows this file no longer declares (default: remove them)",
    )
    args = parser.parse_args()

    from agent.config import settings

    path = args.db or str(Path(settings().data_dir) / "platform.db")
    people, routes, removed = seed(path, args.org, prune=not args.keep_undeclared)
    note = f", removed {removed} no longer declared" if removed else ""
    print(f"seeded {people} people and {routes} routes into {path}{note}")


if __name__ == "__main__":
    main()
