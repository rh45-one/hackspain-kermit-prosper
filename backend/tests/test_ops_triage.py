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
