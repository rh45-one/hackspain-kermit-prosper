"""The ops door, now that a person can sign in and pick a clinic.

This app is published: `Dockerfile` runs `agent.serve` and `fly.toml` puts
port 8080 on the open internet, and what is behind the door is whole call
transcripts in which a patient dictates their national id and telephone
aloud. So the door is tested before anything else, and the properties are
stated as refusals:

* No session and no token is a refusal, from the internet and from loopback
  alike once a secret exists.
* A service token opens the API and is not a person: it gets the one clinic
  this process serves and no session.
* A session that expired, or a cookie that was never issued, is a refusal.
* A person reads their own clinic and nothing of anybody else's.
* A clinic's Prosper key goes in and does not come back out.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from agent.accounts.store import reset_store_cache, store
from agent.config import Settings
from agent.ops import auth, console, live
from agent.orgs import DEFAULT_ORG_ID

TOKEN = "s3cret"
SERVICE = {"x-ops-token": TOKEN}
SECRET = "a-configured-ops-secret-key"
PASSWORD = "correcto-caballo-grapa-pila"
API_KEY = "prosper_live_0123456789abcdef"

OTHER_ORG = "clinica-sagasta"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    live._CACHE.clear()
    reset_store_cache()
    yield
    live._CACHE.clear()
    reset_store_cache()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A throwaway DATA_DIR with its own database, wired into all three modules."""
    config = Settings(
        _env_file=None, data_dir=str(tmp_path), ops_token=TOKEN, ops_secret_key=SECRET
    )
    for module in (console, live, auth):
        monkeypatch.setattr(module, "settings", lambda config=config: config)
    monkeypatch.setattr(live, "_WARM_TRIED", set())
    platform = store(config)
    platform.migrate()
    platform.create_organization(OTHER_ORG, "Clínica Sagasta")
    Path(config.calls_dir_for(DEFAULT_ORG_ID)).mkdir(parents=True, exist_ok=True)
    Path(config.calls_dir_for(OTHER_ORG)).mkdir(parents=True, exist_ok=True)
    return config, platform


@pytest.fixture
def client():
    return TestClient(console.app)


def trace(config, org_id: str, call_id: str, text: str) -> None:
    path = Path(config.calls_dir_for(org_id)) / f"{call_id}.jsonl"
    path.write_text(
        json.dumps(
            {
                "ts": "2026-09-19T17:44:00.000+00:00",
                "event": "transcript",
                "data": {"role": "caller", "text": text},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def person(platform, email: str, orgs: list[tuple[str, str]]):
    user = platform.create_user(email, PASSWORD)
    for org_id, role in orgs:
        platform.add_membership(user.id, org_id, role)
    return user


def sign_in(client, email: str, password: str = PASSWORD):
    response = client.post(
        "/ops/login", data={"email": email, "password": password}, follow_redirects=False
    )
    return response


# ---- the door keeps closing ----------------------------------------------
def test_no_session_and_no_token_is_refused(env, client):
    """The property that matters most, restated after adding a second way in."""
    assert client.get("/ops/api/calls").status_code == 401
    assert client.get("/ops/api/live/calls").status_code == 401
    assert client.get("/ops/api/session").status_code == 401


def test_a_wrong_token_is_still_refused(env, client):
    assert client.get("/ops/api/calls", headers={"x-ops-token": "no"}).status_code == 401


def test_the_service_token_still_opens_the_api(env, client):
    """The Next panel proxies with this header and must keep working."""
    assert client.get("/ops/api/calls", headers=SERVICE).status_code == 200
    assert client.get("/ops/api/live/calls", headers=SERVICE).status_code == 200


def test_a_service_token_is_not_a_person(env, client):
    """It has no identity, so it has no session and no clinic to switch to."""
    assert client.get("/ops/api/session", headers=SERVICE).status_code == 401
    assert (
        client.post("/ops/api/session/org", headers=SERVICE, json={"org_id": OTHER_ORG}).status_code
        == 401
    )


def test_a_signed_in_person_needs_no_token(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    assert sign_in(client, "ana@clinica.es").status_code == 303
    assert client.get("/ops/api/calls").status_code == 200
    assert client.get("/ops/api/session").status_code == 200


def test_a_cookie_that_was_never_issued_is_refused(env, client):
    client.cookies.set(auth.COOKIE_NAME, "definitely-not-a-session-token")
    assert client.get("/ops/api/calls").status_code == 401


def test_a_tampered_cookie_is_refused(env, client):
    """One character off is a different token, and the stored value is a digest."""
    _, platform = env
    user = person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    token = platform.create_session(user.id, DEFAULT_ORG_ID)
    client.cookies.set(auth.COOKIE_NAME, token[:-1] + ("A" if token[-1] != "A" else "B"))
    assert client.get("/ops/api/calls").status_code == 401


def test_an_expired_session_is_refused(env, client):
    from datetime import timedelta

    _, platform = env
    user = person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    token = platform.create_session(user.id, DEFAULT_ORG_ID, ttl=timedelta(seconds=-1))
    client.cookies.set(auth.COOKIE_NAME, token)
    assert client.get("/ops/api/calls").status_code == 401


def test_a_disabled_account_stops_at_the_next_request(env, client):
    """Not at the next login: a session is checked against the user every time."""
    from agent.accounts.db import connect, now_iso

    _, platform = env
    user = person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@clinica.es")
    assert client.get("/ops/api/session").status_code == 200
    with connect(platform.path) as db:
        db.execute("UPDATE users SET disabled_at = ? WHERE id = ?", (now_iso(), user.id))
    assert client.get("/ops/api/session").status_code == 401
    # The gate itself, not just the routes that ask for a person: a live
    # session row belonging to a disabled account is not a way in.
    assert client.get("/ops/api/calls").status_code == 401
    assert client.get("/ops/api/live/calls").status_code == 401


def test_a_revoked_membership_stops_at_the_next_request(env, client):
    _, platform = env
    user = person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@clinica.es")
    platform.remove_membership(user.id, DEFAULT_ORG_ID)
    assert client.get("/ops/api/session").status_code == 401
    assert client.get("/ops/api/calls").status_code == 401


def test_logging_out_kills_the_session_on_both_sides(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@clinica.es")
    token = client.cookies.get(auth.COOKIE_NAME)
    assert client.post("/ops/logout", follow_redirects=False).status_code == 303
    # The row is gone, so replaying the stolen cookie is not a way back in.
    assert platform.load_session(token) is None
    client.cookies.set(auth.COOKIE_NAME, token)
    assert client.get("/ops/api/calls").status_code == 401


# ---- the state a new installation boots in --------------------------------
def test_a_fresh_installation_has_nobody_provisioned(env, client):
    """`people_are_provisioned()` is False, and that is what keeps today's
    deployment behaving exactly as it did: the URL token still opens the
    console because there is no login to send anybody to."""
    _, platform = env
    assert platform.user_count() == 0
    assert auth.people_are_provisioned() is False
    assert client.get(f"/ops/api/calls?token={TOKEN}").status_code == 200
    assert client.get("/ops", params={"token": TOKEN}).status_code == 200


def test_with_no_database_at_all_nobody_is_provisioned(tmp_path, monkeypatch):
    """The deployment that has been running all weekend. No file, no cost."""
    config = Settings(_env_file=None, data_dir=str(tmp_path), ops_token=TOKEN)
    monkeypatch.setattr(auth, "settings", lambda: config)
    assert not (tmp_path / "platform.db").exists()
    assert auth.people_are_provisioned() is False
    assert auth.session_of(object()) is None
    # Asking must not create the file: a read is never a write.
    assert not (tmp_path / "platform.db").exists()


def test_the_url_token_closes_the_moment_the_first_person_exists(env, client):
    """A token in a URL is a person's door, and people have their own now.

    The header keeps working, because that one is a service's door and the
    Next panel is a service.
    """
    _, platform = env
    assert client.get(f"/ops/api/calls?token={TOKEN}").status_code == 200
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    assert auth.people_are_provisioned() is True
    assert client.get(f"/ops/api/calls?token={TOKEN}").status_code == 401
    assert client.get("/ops/api/calls", headers=SERVICE).status_code == 200


def test_a_browser_with_no_session_is_sent_to_the_login_page(env, client):
    """Only the HTML page redirects. A poll that follows a redirect and gets
    a login form back is a failure that arrives looking like data."""
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    page = client.get("/ops", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/ops/login"
    assert client.get("/ops/api/calls", follow_redirects=False).status_code == 401


def test_the_login_page_says_when_there_is_nobody_to_sign_in_as(env, client):
    body = client.get("/ops/login").text
    assert "bootstrap" in body


# ---- signing in -----------------------------------------------------------
def test_a_wrong_password_does_not_open_a_session(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    response = sign_in(client, "ana@clinica.es", "not-the-password")
    assert response.status_code == 401
    assert auth.COOKIE_NAME not in response.cookies
    assert client.get("/ops/api/calls").status_code == 401


def test_an_unknown_account_gets_the_same_message_as_a_wrong_password(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    wrong = sign_in(client, "ana@clinica.es", "nope").text
    unknown = sign_in(client, "nadie@clinica.es", PASSWORD).text
    assert wrong == unknown


def test_a_person_in_no_organisation_cannot_sign_in(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [])
    assert sign_in(client, "ana@clinica.es").status_code == 403


def test_the_session_cookie_is_httponly(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    response = sign_in(client, "ana@clinica.es")
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite", "SameSite")


# ---- switching organisation ----------------------------------------------
def test_a_person_switches_between_their_own_clinics(env, client):
    """This is the whole of step 4's "cambiar de organización": everything
    downstream already takes org_id as an argument, so it is one column."""
    config, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner"), (OTHER_ORG, "member")])
    trace(config, DEFAULT_ORG_ID, "arenal-1", "hola Arenal")
    trace(config, OTHER_ORG, "sagasta-1", "hola Sagasta")
    sign_in(client, "ana@clinica.es")

    assert [c["call_id"] for c in client.get("/ops/api/live/calls").json()] == ["arenal-1"]
    switched = client.post("/ops/api/session/org", json={"org_id": OTHER_ORG})
    assert switched.status_code == 200
    assert switched.json()["org_id"] == OTHER_ORG
    assert switched.json()["role"] == "member"
    assert [c["call_id"] for c in client.get("/ops/api/live/calls").json()] == ["sagasta-1"]


def test_the_session_lists_only_the_clinics_the_person_belongs_to(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@clinica.es")
    body = client.get("/ops/api/session").json()
    assert [o["id"] for o in body["organizations"]] == [DEFAULT_ORG_ID]
    assert OTHER_ORG not in json.dumps(body)


def test_switching_to_a_clinic_you_are_not_in_is_refused(env, client):
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@clinica.es")
    assert client.post("/ops/api/session/org", json={"org_id": OTHER_ORG}).status_code == 403
    # And the session did not move.
    assert client.get("/ops/api/session").json()["org_id"] == DEFAULT_ORG_ID


def test_a_clinic_that_does_not_exist_is_refused_the_same_way(env, client):
    """"You are not in it" and "it is not there" are the same answer to
    somebody trying org ids."""
    _, platform = env
    person(platform, "ana@clinica.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@clinica.es")
    assert client.post("/ops/api/session/org", json={"org_id": "inventada"}).status_code == 403


def test_an_org_id_that_could_be_a_path_is_a_400_and_never_a_path(env, client):
    assert client.get("/ops/api/live/calls?org=../..", headers=SERVICE).status_code == 400


# ---- isolation between organisations --------------------------------------
def test_one_clinics_person_reads_nothing_of_anothers_calls(env, client):
    config, platform = env
    person(platform, "ana@arenal.es", [(DEFAULT_ORG_ID, "owner")])
    person(platform, "beto@sagasta.es", [(OTHER_ORG, "owner")])
    trace(config, DEFAULT_ORG_ID, "arenal-1", "hola Arenal")
    trace(config, OTHER_ORG, "sagasta-1", "hola Sagasta")

    sign_in(client, "ana@arenal.es")
    listed = client.get("/ops/api/live/calls")
    assert [c["call_id"] for c in listed.json()] == ["arenal-1"]
    assert "sagasta" not in listed.text
    # Naming the other clinic explicitly is a refusal, not a read.
    assert client.get(f"/ops/api/live/calls?org={OTHER_ORG}").status_code == 403
    assert client.get(f"/ops/api/live/calls/sagasta-1?org={OTHER_ORG}").status_code == 403
    # And the trace of the other clinic is not reachable through her own org.
    assert client.get("/ops/api/live/calls/sagasta-1").status_code == 404


def test_the_debug_console_is_scoped_to_the_session_too(env, client):
    config, platform = env
    person(platform, "beto@sagasta.es", [(OTHER_ORG, "owner")])
    trace(config, DEFAULT_ORG_ID, "arenal-1", "hola Arenal")
    trace(config, OTHER_ORG, "sagasta-1", "hola Sagasta")
    sign_in(client, "beto@sagasta.es")
    assert [c["call_id"] for c in client.get("/ops/api/calls").json()] == ["sagasta-1"]
    assert client.get("/ops/api/calls/arenal-1").status_code == 404


def test_one_clinics_person_cannot_read_or_write_anothers_credential(env, client):
    _, platform = env
    person(platform, "ana@arenal.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@arenal.es")
    assert client.get(f"/ops/api/orgs/{OTHER_ORG}/credential").status_code == 403
    assert (
        client.put(
            f"/ops/api/orgs/{OTHER_ORG}/credential", json={"prosper_api_key": API_KEY}
        ).status_code
        == 403
    )
    assert client.delete(f"/ops/api/orgs/{OTHER_ORG}/credential").status_code == 403
    assert platform.get_organization(OTHER_ORG).has_credential is False


def test_a_plain_member_may_not_write_a_credential(env, client):
    _, platform = env
    person(platform, "ana@arenal.es", [(DEFAULT_ORG_ID, "member")])
    sign_in(client, "ana@arenal.es")
    assert (
        client.put(
            f"/ops/api/orgs/{DEFAULT_ORG_ID}/credential", json={"prosper_api_key": API_KEY}
        ).status_code
        == 403
    )


# ---- a credential goes in and does not come out ---------------------------
def test_a_stored_credential_is_never_readable_over_http(env, client):
    """The rule the whole database exists for. There is no route that returns
    a clinic's key and no response model with a field that could hold one."""
    _, platform = env
    person(platform, "ana@arenal.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@arenal.es")

    written = client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/credential", json={"prosper_api_key": API_KEY}
    )
    assert written.status_code == 200
    assert API_KEY not in written.text
    assert written.json()["has_credential"] is True
    assert written.json()["credential_fingerprint"].startswith("sha256:")

    read_back = client.get(f"/ops/api/orgs/{DEFAULT_ORG_ID}/credential")
    assert read_back.status_code == 200
    assert API_KEY not in read_back.text
    assert read_back.json()["has_credential"] is True

    # Nor anywhere else a person can reach.
    assert API_KEY not in client.get("/ops/api/session").text
    assert API_KEY not in client.get("/ops").text
    # The process that places a call still gets it.
    assert platform.organization_api_key(DEFAULT_ORG_ID, SECRET) == API_KEY


def test_clearing_a_credential_takes_the_clinic_back_to_the_environment(env, client):
    _, platform = env
    person(platform, "ana@arenal.es", [(DEFAULT_ORG_ID, "owner")])
    sign_in(client, "ana@arenal.es")
    client.put(f"/ops/api/orgs/{DEFAULT_ORG_ID}/credential", json={"prosper_api_key": API_KEY})
    cleared = client.delete(f"/ops/api/orgs/{DEFAULT_ORG_ID}/credential")
    assert cleared.status_code == 200
    assert cleared.json()["has_credential"] is False
    assert platform.organization_api_key(DEFAULT_ORG_ID, SECRET) is None


def test_without_a_secret_key_the_backend_refuses_to_store_a_credential(tmp_path, monkeypatch):
    """Refusing is the safe failure: writing it in the clear onto the volume
    is how a backup becomes a breach."""
    config = Settings(_env_file=None, data_dir=str(tmp_path), ops_token=TOKEN, ops_secret_key="")
    for module in (console, live, auth):
        monkeypatch.setattr(module, "settings", lambda config=config: config)
    platform = store(config)
    platform.migrate()
    user = platform.create_user("ana@arenal.es", PASSWORD)
    platform.add_membership(user.id, DEFAULT_ORG_ID, "owner")
    client = TestClient(console.app)
    sign_in(client, "ana@arenal.es")
    response = client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/credential", json={"prosper_api_key": API_KEY}
    )
    assert response.status_code == 503
    assert API_KEY not in response.text
    assert platform.get_organization(DEFAULT_ORG_ID).has_credential is False


# ---- nothing secret reaches a log ----------------------------------------
def test_no_password_and_no_api_key_ever_reaches_a_log(env, client):
    """Signing in and writing a credential are the two paths that hold a
    secret in a local variable. Neither may print one."""
    _, platform = env
    person(platform, "ana@arenal.es", [(DEFAULT_ORG_ID, "owner")])
    written: list[str] = []
    sink = logger.add(written.append, level="TRACE")
    try:
        sign_in(client, "ana@arenal.es", "the-wrong-one")
        sign_in(client, "ana@arenal.es")
        client.put(
            f"/ops/api/orgs/{DEFAULT_ORG_ID}/credential", json={"prosper_api_key": API_KEY}
        )
        client.get("/ops/api/live/calls")
    finally:
        logger.remove(sink)
    logged = "".join(written)
    assert PASSWORD not in logged
    assert "the-wrong-one" not in logged
    assert API_KEY not in logged
    assert client.cookies.get(auth.COOKIE_NAME) not in logged
