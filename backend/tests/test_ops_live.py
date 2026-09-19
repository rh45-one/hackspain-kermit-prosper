"""The product view reads the same traces as the console, for a different reader.

Two things it must never get wrong: it is behind the same access door as every
other ops route, and the caller's national id and telephone do not come out of
it. A patient dictates both aloud during a registration, so they sit verbatim
in the JSONL this module reads.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent.ops import console, live

TOKEN = "s3cret"
HEADERS = {"x-ops-token": TOKEN}


@pytest.fixture(autouse=True)
def _clean_cache():
    live._CACHE.clear()
    yield
    live._CACHE.clear()


@pytest.fixture
def calls_dir(tmp_path, monkeypatch):
    """Point both modules at a throwaway DATA_DIR and open the door with a token."""
    directory = tmp_path / "calls"
    directory.mkdir()
    monkeypatch.setattr(live, "settings", lambda: type("S", (), {"calls_dir": str(directory)})())
    monkeypatch.setattr(console, "settings", lambda: type("S", (), {"ops_token": TOKEN})())
    return directory


@pytest.fixture
def client():
    return TestClient(console.app)


def write_trace(directory, call_id: str, events: list[tuple[str, dict]]) -> None:
    with (directory / f"{call_id}.jsonl").open("w", encoding="utf-8") as handle:
        for index, (event, data) in enumerate(events):
            stamp = f"2026-09-19T17:44:{index:02d}.000+00:00"
            handle.write(json.dumps({"ts": stamp, "event": event, "data": data}) + "\n")


def say(role: str, text: str) -> tuple[str, dict]:
    return ("transcript", {"role": role, "text": text})


# ---- the door ------------------------------------------------------------
def test_the_live_routes_sit_behind_the_same_door(calls_dir, client):
    """A second check is how one ends up open; this must reuse console's."""
    write_trace(calls_dir, "c1", [say("caller", "hola")])
    assert client.get("/ops/api/live/calls").status_code == 401
    assert client.get("/ops/api/live/calls/c1").status_code == 401
    assert client.get("/ops/api/live/calls", headers=HEADERS).status_code == 200


# ---- redaction -----------------------------------------------------------
def test_the_national_id_and_phone_never_leave_the_reader(calls_dir, client):
    """Problem 14's protected fields, dictated aloud and sitting in the trace."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "Mi DNI es 31426012P, el teléfono 792919982 y sergio_m77@gmail.com")],
    )
    body = client.get("/ops/api/live/calls/c1", headers=HEADERS).text
    assert "31426012P" not in body
    assert "792919982" not in body
    assert "sergio_m77@gmail.com" not in body
    assert "[DNI]" in body and "[teléfono]" in body and "[email]" in body


def test_the_registration_shows_the_name_and_nothing_else(calls_dir, client):
    """The name is deliberately not protected — it is why the panel is useful."""
    write_trace(
        calls_dir,
        "c1",
        [
            say("caller", "quiero darme de alta"),
            (
                "action_queued",
                {
                    "route": "register",
                    "given_name": "Sergio",
                    "first_surname": "Martínez",
                    "second_surname": "Ramírez",
                    "national_id": "31426012P",
                    "date_of_birth": "2005-08-10",
                    "phone": "792919982",
                    "email": "sergio_m77@gmail.com",
                    "insurer": "adeslas",
                },
            ),
        ],
    )
    payload = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()
    body = json.dumps(payload, ensure_ascii=False)
    assert payload["patient"] == "Sergio Martínez Ramírez"
    assert "Sergio" in body
    for secret in ("31426012P", "792919982", "sergio_m77@gmail.com", "2005-08-10"):
        assert secret not in body, f"{secret} escapó al panel"


def test_a_field_added_upstream_is_not_published_by_accident(calls_dir, client):
    """The allow-list must fail closed on a key nobody has reviewed yet."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "hola"), ("action_queued", {"route": "cancel", "appointment_id": "A1",
                                                   "secret_new_field": "no debería salir"})],
    )
    body = client.get("/ops/api/live/calls/c1", headers=HEADERS).text
    assert "no debería salir" not in body


# ---- reading the trace ---------------------------------------------------
def test_streamed_fragments_join_without_extra_spaces(calls_dir, client):
    """Each fragment already carries its own spacing; joining on a space doubles it."""
    write_trace(
        calls_dir,
        "c1",
        [say("assistant", "Clínica Arenal, "), say("assistant", "buenos días."),
         say("caller", "Hola.")],
    )
    payload = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()
    assert payload["conversation"][0] == {"speaker": "agente", "text": "Clínica Arenal, buenos días."}
    assert payload["conversation"][1]["speaker"] == "paciente"


def test_the_decision_reads_as_a_sentence(calls_dir, client):
    write_trace(
        calls_dir,
        "c1",
        [
            say("caller", "quiero cita"),
            ("availability_query", {"asked": "el jueves que viene", "slots": 4}),
            ("action_queued", {"route": "no-action", "reason": "no_availability"}),
            ("submitted", {"route": "no-action"}),
        ],
    )
    payload = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()
    sentences = [item["text"] for item in payload["events"]]
    assert 'Buscó huecos para "el jueves que viene": 4 disponibles.' in sentences
    assert "No hizo ninguna gestión: no hay hueco." in sentences
    assert "Envió la decisión a la clínica correctamente." in sentences


def test_plumbing_events_are_not_shown_to_a_receptionist(calls_dir, client):
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "hola"), ("audio_bridge_metrics", {"underruns": 0}),
         ("barge_in_reset", {"resets": 3}), ("engine_selected", {"engine": "gemini_live"})],
    )
    payload = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()
    assert payload["events"] == []


def test_a_call_with_no_words_is_not_listed(calls_dir, client):
    """24 of the 164 traces on disk are sockets that never produced a word."""
    write_trace(calls_dir, "silent", [("client_connected", {}), ("socket_stop", {"elapsed_s": 1})])
    write_trace(calls_dir, "real", [say("caller", "buenos días")])
    listed = [row["call_id"] for row in client.get("/ops/api/live/calls", headers=HEADERS).json()]
    assert listed == ["real"]


def test_an_unfinished_trace_that_stopped_growing_is_not_called_live(calls_dir, client):
    """No close record and no recent write is a call that died, not one in progress."""
    write_trace(calls_dir, "c1", [say("caller", "hola")])
    import os

    old = 1_600_000_000
    os.utime(calls_dir / "c1.jsonl", (old, old))
    row = client.get("/ops/api/live/calls", headers=HEADERS).json()[0]
    assert row["status"] == "sin cierre"


def test_a_closed_call_reports_its_duration(calls_dir, client):
    write_trace(calls_dir, "c1", [say("caller", "hola"), ("call_ended", {"reason": "x", "elapsed_s": 42.4})])
    row = client.get("/ops/api/live/calls", headers=HEADERS).json()[0]
    assert row["status"] == "finalizada"
    assert row["duration_seconds"] == 42


# ---- safety and cost -----------------------------------------------------
def test_a_call_id_cannot_walk_out_of_the_data_directory(calls_dir, client):
    for bad in ("../../etc/passwd", "..", "a/b"):
        assert client.get(f"/ops/api/live/calls/{bad}", headers=HEADERS).status_code in (400, 404)


def test_an_unknown_call_is_not_found(calls_dir, client):
    assert client.get("/ops/api/live/calls/nope", headers=HEADERS).status_code == 404


def test_a_finished_call_is_parsed_once_however_often_the_panel_polls(calls_dir, client, monkeypatch):
    """The panel polls, and the process answering may be carrying a scored call."""
    write_trace(calls_dir, "c1", [say("caller", "hola"), ("call_ended", {"reason": "x", "elapsed_s": 5})])
    parses = []
    original = live._parse
    monkeypatch.setattr(live, "_parse", lambda path: parses.append(path) or original(path))
    for _ in range(5):
        client.get("/ops/api/live/calls", headers=HEADERS)
    assert len(parses) == 1


def test_a_reading_repeated_every_turn_is_said_once(calls_dir, client):
    """Jev re-emits the same reading while it holds; four lines read as a stutter."""
    same = ("jev_assessment", {"intent": "book_appointment", "confidence": 0.9})
    write_trace(calls_dir, "c1", [say("caller", "quiero cita"), same, same, same, same])
    payload = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()
    assert [e["text"] for e in payload["events"]] == ["Entendió la petición como «book_appointment»."]


def test_an_empty_reading_is_not_shown_at_all(calls_dir, client):
    """"other" with nothing attached is the model saying it has no reading yet."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "hola"), ("jev_assessment", {"intent": "other", "needs_clarification": True})],
    )
    assert client.get("/ops/api/live/calls/c1", headers=HEADERS).json()["events"] == []


def test_a_call_that_queued_nothing_still_reports_an_outcome(calls_dir, client):
    """flush.py refuses to end a call silently and submits a no-action itself."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "hola"), ("flush_start", {"actions": 1}), ("submitted", {"route": "no-action"})],
    )
    row = client.get("/ops/api/live/calls", headers=HEADERS).json()[0]
    assert row["headline"] == "No registró ninguna decisión; se envió un cierre automático."


def test_a_cold_catalogue_degrades_to_ids_instead_of_failing(calls_dir, client, monkeypatch):
    """No credentials is a normal state for this reader; it must still answer."""
    monkeypatch.setattr(live, "_WARM_TRIED", False)
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "hola"), ("action_queued", {"route": "book", "provider_id": "PR10",
                                                   "location_id": "norte",
                                                   "appointment_type_id": "first_visit"})],
    )
    row = client.get("/ops/api/live/calls", headers=HEADERS).json()[0]
    assert "PR10" in row["headline"]


def test_the_patient_is_named_once_identity_is_confirmed(calls_dir, client):
    """The id identifies a record; the name is what tells a person who called."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "soy Marta"),
         ("identity_confirmed", {"patient_id": "P01633", "given_name": "Marta"})],
    )
    payload = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()
    assert payload["events"][0]["text"] == "Confirmó la identidad de Marta."
    assert "P01633" not in json.dumps(payload)


def test_a_question_about_the_clinic_is_no_longer_invisible(calls_dir, client):
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "¿qué horario tienen?"),
         ("clinic_question", {"about": "horarios", "answered": ["sites", "doctors"]})],
    )
    payload = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()
    assert payload["events"][0]["text"] == (
        'Le preguntaron sobre "horarios" y respondió con las sedes y los médicos.'
    )


def test_the_nearest_site_says_why_it_was_not_the_nearest(calls_dir, client):
    """Problem 15: the closest site is not the answer when it cannot serve."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "estoy en Chamberí"),
         ("nearest_site", {"asked_from": "Chamberí", "specialty": "traumatología",
                           "chose": "centro", "km": 2.43, "closest_overall": "norte"})],
    )
    text = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()["events"][0]["text"]
    assert 'Buscó la sede más cercana a "Chamberí" y eligió centro, a 2,4 km.' in text
    assert "La más cercana era norte, pero no podía atender la petición" in text


def test_a_medical_emergency_is_visible_without_opening_the_call(calls_dir, client):
    """The only thing on this screen that may need a person to get up."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "me duele el pecho"),
         ("jev_assessment", {"intent": "triage", "medical_emergency": True})],
    )
    row = client.get("/ops/api/live/calls", headers=HEADERS).json()[0]
    assert row["medical_emergency"] is True


def test_an_ordinary_call_is_not_flagged_as_an_emergency(calls_dir, client):
    write_trace(calls_dir, "c1", [say("caller", "quiero cita"),
                                  ("jev_assessment", {"intent": "book_appointment"})])
    assert client.get("/ops/api/live/calls", headers=HEADERS).json()[0]["medical_emergency"] is False


def test_a_booking_names_the_caller_from_the_confirmed_identity(calls_dir, client):
    """Bookings carry only a patient_id, so rows used to read "unidentified"."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "quiero cita"),
         ("identity_confirmed", {"patient_id": "P01633", "given_name": "Marta"}),
         ("action_queued", {"route": "book", "provider_id": "PR10"})],
    )
    assert client.get("/ops/api/live/calls", headers=HEADERS).json()[0]["patient"] == "Marta"


def test_a_registration_still_wins_over_the_confirmed_name(calls_dir, client):
    """The registration body has the full name; the confirmation has one word."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "alta"),
         ("action_queued", {"route": "register", "given_name": "Sergio",
                            "first_surname": "Martínez", "second_surname": "Ramírez"}),
         ("identity_confirmed", {"patient_id": "P1", "given_name": "Sergio"})],
    )
    row = client.get("/ops/api/live/calls", headers=HEADERS).json()[0]
    assert row["patient"] == "Sergio Martínez Ramírez"


def test_a_broken_clinic_client_does_not_become_a_500(calls_dir, client, monkeypatch):
    """`deps.try_clinic_client` calls the constructor outside its own try, so
    bad configuration raises out of it. A reader whose job is to answer must
    degrade to ids instead of failing the request."""
    from agent.brain import deps

    monkeypatch.setattr(live, "_WARM_TRIED", False)
    monkeypatch.setattr(
        live, "settings",
        lambda: type("S", (), {"calls_dir": str(calls_dir), "prosper_api_key": "k"})(),
    )
    def explode(_config):
        raise RuntimeError("bad base url")
    monkeypatch.setattr(deps, "try_clinic_client", explode)

    write_trace(calls_dir, "c1", [say("caller", "hola"),
                                  ("action_queued", {"route": "book", "provider_id": "PR10"})])
    response = client.get("/ops/api/live/calls", headers=HEADERS)
    assert response.status_code == 200
    assert "PR10" in response.json()[0]["headline"]


def test_an_empty_search_says_which_rule_blocked_it(calls_dir, client):
    """"No hay hueco" and "your plan does not cover that site" are different
    answers, and only the second one a receptionist can act on."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "quiero cita en Norte"),
         ("availability_query", {"asked": "mañana", "slots": 0,
                                 "blocked": ["location_not_covered", "provider_on_leave"]})],
    )
    text = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()["events"][0]["text"]
    assert text == (
        'Buscó huecos para "mañana" y no había ninguno libre: '
        "el centro no está cubierto y el profesional está de baja."
    )


def test_a_search_with_slots_does_not_explain_itself(calls_dir, client):
    """The "why" only matters when the answer was no."""
    write_trace(
        calls_dir,
        "c1",
        [say("caller", "quiero cita"),
         ("availability_query", {"asked": "mañana", "slots": 3, "blocked": ["provider_on_leave"]})],
    )
    text = client.get("/ops/api/live/calls/c1", headers=HEADERS).json()["events"][0]["text"]
    assert text == 'Buscó huecos para "mañana": 3 disponibles.'
