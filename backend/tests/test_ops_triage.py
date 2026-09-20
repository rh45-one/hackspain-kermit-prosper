"""Lo que Jev lee de un paciente, y lo que nunca sale de aquí."""
from __future__ import annotations

from agent.ops.triage import _record_of


class _Patient:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_the_record_is_what_decides_and_nothing_else():
    record = _record_of(
        _Patient(
            given_name="María",
            first_surname="García",
            national_id="12345678Z",
            phone="+34600111222",
            date_of_birth="1958-04-02",
            sex="female",
            insurer="Sanitas",
            has_visited_before=True,
            referrals=["Cardiology"],
            note="Revisión anual de tensión.",
        )
    )

    # Lo que sirve para decidir una especialidad.
    assert "nacido en 1958" in record
    assert "plan Sanitas" in record
    assert "ya ha venido antes" in record
    assert "Cardiology" in record
    assert "Revisión anual" in record

    # Y lo que no hace falta para decidirla, no se manda. Lo que no sale de
    # aquí no se puede filtrar mal en el otro extremo.
    assert "12345678Z" not in record
    assert "600111222" not in record
    assert "María" not in record
    assert "García" not in record


def test_somebody_with_no_history_says_so():
    """Y por eso la respuesta normal para esa persona es abstenerse."""
    record = _record_of(_Patient(date_of_birth="1994-01-01", has_visited_before=False))

    assert "nunca ha venido" in record
    assert "volantes" not in record


# ---- la tabla que se llena sola -------------------------------------------
def test_a_lookup_leaves_the_patient_in_the_clinics_own_table(accounts_db):
    """Prosper no exporta pacientes, así que la tabla se construye con el uso."""
    from agent.accounts.store import Store
    from agent.brain.tools import ToolBox
    from agent.config import settings
    from agent.orgs import DEFAULT_ORG_ID
    from agent.voice.context import CallContext

    box = ToolBox(CallContext(org_id=DEFAULT_ORG_ID), settings())
    box._remember_them(
        [
            {
                "patient_id": "P1",
                "given_name": "María",
                "first_surname": "García",
                "insurer": "Sanitas",
                "national_id": "12345678Z",
                "phone": "+34600111222",
            }
        ]
    )

    rows = Store(accounts_db).list_patients(DEFAULT_ORG_ID)
    assert len(rows) == 1
    assert rows[0].name == "María García"
    assert rows[0].insurer == "Sanitas"
    # Y lo que esta base nunca guarda, porque acaba en una copia de seguridad.
    assert not hasattr(rows[0], "national_id")
    assert not hasattr(rows[0], "phone")


def test_seeing_somebody_twice_counts_and_never_empties_what_was_known(accounts_db):
    """Una búsqueda por documento devuelve menos campos que una por nombre."""
    from agent.accounts.store import PatientRow, Store
    from agent.orgs import DEFAULT_ORG_ID

    shop = Store(accounts_db)
    shop.remember_patient(
        DEFAULT_ORG_ID,
        PatientRow(patient_id="P1", given_name="María", first_surname="García", insurer="Sanitas"),
    )
    shop.remember_patient(DEFAULT_ORG_ID, PatientRow(patient_id="P1"))

    row = shop.list_patients(DEFAULT_ORG_ID)[0]
    assert row.times_seen == 2
    assert row.name == "María García"
    assert row.insurer == "Sanitas"


def test_the_table_filters(accounts_db):
    from agent.accounts.store import PatientRow, Store
    from agent.orgs import DEFAULT_ORG_ID

    shop = Store(accounts_db)
    shop.remember_patient(
        DEFAULT_ORG_ID,
        PatientRow(patient_id="P1", given_name="María", insurer="Sanitas",
                   likely_specialty="Cardiología"),
    )
    shop.remember_patient(
        DEFAULT_ORG_ID, PatientRow(patient_id="P2", given_name="Luis", insurer="Adeslas")
    )

    assert len(shop.list_patients(DEFAULT_ORG_ID, query="sanitas")) == 1
    assert len(shop.list_patients(DEFAULT_ORG_ID, query="cardio")) == 1
    assert len(shop.list_patients(DEFAULT_ORG_ID, query="luis")) == 1
    assert len(shop.list_patients(DEFAULT_ORG_ID, query="nadie")) == 0
