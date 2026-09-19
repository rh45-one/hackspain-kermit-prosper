"""The tables under the login: migrations, passwords, credentials, sessions.

Four properties this file exists to pin down, because every one of them is a
way a deployed console leaks something:

1. A password is never recoverable from what is stored.
2. A clinic's Prosper key is never readable from the database file alone.
3. A session token is never stored, so a stolen file is not a pile of live
   sessions.
4. With no database, or a database nobody has been provisioned in, a call
   resolves exactly the credential it resolved before this package existed.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from agent.accounts import secrets as crypto
from agent.accounts.credentials import clinic_credentials, prosper_api_key_for
from agent.accounts.db import SCHEMA_VERSION, connect, migrate
from agent.accounts.store import Store, StoreError, reset_store_cache
from agent.config import Settings
from agent.orgs import DEFAULT_ORG_ID

SECRET = "a-configured-ops-secret-key"
API_KEY = "prosper_live_0123456789abcdef"
PASSWORD = "correcto-caballo-grapa-pila"


@pytest.fixture(autouse=True)
def _isolated_store_cache():
    reset_store_cache()
    yield
    reset_store_cache()


@pytest.fixture
def platform(tmp_path) -> Store:
    store = Store(tmp_path / "platform.db")
    store.migrate()
    return store


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=str(tmp_path), **overrides)


# ---- migrations -----------------------------------------------------------
def test_migrations_run_on_an_empty_volume_and_are_idempotent(tmp_path):
    """Boot applies them with nobody watching, and a second boot is a no-op."""
    path = tmp_path / "platform.db"
    assert migrate(path) == SCHEMA_VERSION
    assert migrate(path) == SCHEMA_VERSION
    with connect(path) as db:
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"organizations", "users", "memberships", "sessions"} <= tables


def test_the_default_clinic_exists_after_the_first_boot_and_has_no_credential(platform):
    """A fresh install is one organisation with nothing in it.

    No credential on purpose: with the column NULL the environment's
    PROSPER_API_KEY is still what a call uses, which is the whole of "single
    organisation behaviour is unchanged".
    """
    org = platform.get_organization(DEFAULT_ORG_ID)
    assert org is not None
    assert org.has_credential is False
    assert platform.user_count() == 0


# ---- passwords ------------------------------------------------------------
def test_a_password_is_never_stored_in_the_clear(platform, tmp_path):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    raw = (tmp_path / "platform.db").read_bytes()
    assert PASSWORD.encode() not in raw
    with connect(platform.path) as db:
        stored = db.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()[0]
    assert stored.startswith("scrypt$")
    assert PASSWORD not in stored


def test_authenticate_accepts_the_password_and_nothing_else(platform):
    platform.create_user("ana@clinica.es", PASSWORD)
    assert platform.authenticate("ana@clinica.es", PASSWORD) is not None
    assert platform.authenticate("ana@clinica.es", PASSWORD + "x") is None
    assert platform.authenticate("ANA@clinica.es", PASSWORD) is not None  # email is not case
    assert platform.authenticate("nadie@clinica.es", PASSWORD) is None


def test_a_wrong_password_and_an_unknown_account_are_indistinguishable(platform):
    """Three different messages is a way to enumerate who works here."""
    platform.create_user("ana@clinica.es", PASSWORD)
    assert platform.authenticate("ana@clinica.es", "no") is None
    assert platform.authenticate("nadie@clinica.es", "no") is None


def test_verify_password_survives_junk_instead_of_raising():
    for stored in ("", "nonsense", "scrypt$x$y$z$q$r", "bcrypt$1$2$3$4$5"):
        assert crypto.verify_password("whatever", stored) is False


def test_changing_a_password_ends_every_session_it_opened(platform):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    platform.add_membership(user.id, DEFAULT_ORG_ID, "owner")
    token = platform.create_session(user.id, DEFAULT_ORG_ID)
    assert platform.load_session(token) is not None
    platform.set_password(user.id, "otra-contraseña-larga")
    assert platform.load_session(token) is None


# ---- a clinic's credential ------------------------------------------------
def test_the_api_key_is_encrypted_at_rest(platform, tmp_path):
    """The database file on its own is not enough to read a clinic's key."""
    platform.set_organization_credential(DEFAULT_ORG_ID, API_KEY, SECRET)
    raw = (tmp_path / "platform.db").read_bytes()
    assert API_KEY.encode() not in raw
    assert platform.organization_api_key(DEFAULT_ORG_ID, SECRET) == API_KEY


def test_the_fingerprint_identifies_a_key_without_being_one():
    assert crypto.fingerprint(API_KEY) == crypto.fingerprint(API_KEY)
    assert crypto.fingerprint(API_KEY) != crypto.fingerprint(API_KEY + "x")
    assert API_KEY not in crypto.fingerprint(API_KEY)
    assert len(crypto.fingerprint(API_KEY)) == len("sha256:") + 8


def test_a_credential_cannot_be_moved_between_organisations(platform):
    """The org id is authenticated data, so a copied row fails to open."""
    platform.create_organization("clinica-sagasta", "Clínica Sagasta")
    platform.set_organization_credential(DEFAULT_ORG_ID, API_KEY, SECRET)
    with connect(platform.path) as db:
        blob = db.execute(
            "SELECT prosper_api_key_encrypted FROM organizations WHERE id = ?", (DEFAULT_ORG_ID,)
        ).fetchone()[0]
        db.execute(
            "UPDATE organizations SET prosper_api_key_encrypted = ? WHERE id = ?",
            (blob, "clinica-sagasta"),
        )
    with pytest.raises(crypto.SecretsUnavailable):
        platform.organization_api_key("clinica-sagasta", SECRET)


def test_the_wrong_secret_key_refuses_rather_than_guesses(platform):
    platform.set_organization_credential(DEFAULT_ORG_ID, API_KEY, SECRET)
    with pytest.raises(crypto.SecretsUnavailable):
        platform.organization_api_key(DEFAULT_ORG_ID, "another-secret-entirely")


def test_storing_a_credential_without_a_secret_key_is_refused(platform):
    """Refusing is the safe failure. Writing it in the clear is how a backup
    becomes a breach."""
    with pytest.raises(crypto.SecretsUnavailable):
        platform.set_organization_credential(DEFAULT_ORG_ID, API_KEY, "")
    assert platform.get_organization(DEFAULT_ORG_ID).has_credential is False


# ---- which key a call actually uses ---------------------------------------
def test_with_no_database_the_default_clinic_uses_the_environment_key(tmp_path):
    """The deployment that has been running all weekend takes this branch."""
    config = _settings(tmp_path, prosper_api_key="env-key")
    assert not (tmp_path / "platform.db").exists()
    assert prosper_api_key_for(config, DEFAULT_ORG_ID) == "env-key"
    assert clinic_credentials(config, DEFAULT_ORG_ID).prosper_api_key == "env-key"


def test_a_provisioned_but_credential_less_clinic_still_uses_the_environment_key(tmp_path):
    config = _settings(tmp_path, prosper_api_key="env-key", ops_secret_key=SECRET)
    Store(tmp_path / "platform.db").migrate()
    assert prosper_api_key_for(config, DEFAULT_ORG_ID) == "env-key"


def test_a_clinics_own_key_wins_over_the_environment(tmp_path):
    config = _settings(tmp_path, prosper_api_key="env-key", ops_secret_key=SECRET)
    store = Store(tmp_path / "platform.db")
    store.migrate()
    store.set_organization_credential(DEFAULT_ORG_ID, API_KEY, SECRET)
    assert prosper_api_key_for(config, DEFAULT_ORG_ID) == API_KEY


def test_a_second_clinic_with_no_key_gets_nothing_not_somebody_elses(tmp_path):
    """The one failure mode that must never be convenient."""
    config = _settings(tmp_path, prosper_api_key="env-key", ops_secret_key=SECRET)
    store = Store(tmp_path / "platform.db")
    store.migrate()
    store.create_organization("clinica-sagasta", "Clínica Sagasta")
    assert prosper_api_key_for(config, "clinica-sagasta") == ""


def test_a_second_clinic_uses_its_own_key(tmp_path):
    config = _settings(tmp_path, prosper_api_key="env-key", ops_secret_key=SECRET)
    store = Store(tmp_path / "platform.db")
    store.migrate()
    store.create_organization("clinica-sagasta", "Clínica Sagasta")
    store.set_organization_credential("clinica-sagasta", "sagasta-key-abc", SECRET)
    assert prosper_api_key_for(config, "clinica-sagasta") == "sagasta-key-abc"
    assert prosper_api_key_for(config, DEFAULT_ORG_ID) == "env-key"


def test_an_unreadable_credential_falls_back_instead_of_dropping_the_call(tmp_path):
    """A credential lookup is never allowed to be the thing that fails a call."""
    config = _settings(tmp_path, prosper_api_key="env-key", ops_secret_key="wrong-secret")
    store = Store(tmp_path / "platform.db")
    store.migrate()
    store.set_organization_credential(DEFAULT_ORG_ID, API_KEY, SECRET)
    # The stored key cannot be opened with this process's secret. The default
    # clinic degrades to the environment rather than raising.
    assert prosper_api_key_for(config, DEFAULT_ORG_ID) == "env-key"


def test_the_credentials_view_never_prints_the_key(tmp_path):
    view = clinic_credentials(_settings(tmp_path, prosper_api_key=API_KEY), DEFAULT_ORG_ID)
    assert API_KEY not in repr(view)
    assert "<redacted>" in repr(view)


# ---- memberships and sessions ---------------------------------------------
def test_a_session_token_is_never_stored(platform, tmp_path):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    platform.add_membership(user.id, DEFAULT_ORG_ID, "owner")
    token = platform.create_session(user.id, DEFAULT_ORG_ID)
    assert token.encode() not in (tmp_path / "platform.db").read_bytes()


def test_a_session_cannot_be_opened_on_a_clinic_the_person_is_not_in(platform):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    with pytest.raises(StoreError):
        platform.create_session(user.id, DEFAULT_ORG_ID)


def test_an_expired_session_is_refused_and_deleted(platform):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    platform.add_membership(user.id, DEFAULT_ORG_ID, "owner")
    token = platform.create_session(user.id, DEFAULT_ORG_ID, ttl=timedelta(seconds=-1))
    assert platform.load_session(token) is None
    with connect(platform.path) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_a_token_that_was_never_issued_is_refused(platform):
    assert platform.load_session("not-a-token") is None
    assert platform.load_session("") is None


def test_switching_organisation_needs_a_membership(platform):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    platform.add_membership(user.id, DEFAULT_ORG_ID, "owner")
    platform.create_organization("clinica-sagasta", "Clínica Sagasta")
    token = platform.create_session(user.id, DEFAULT_ORG_ID)

    assert platform.switch_session_org(token, "clinica-sagasta") is None
    platform.add_membership(user.id, "clinica-sagasta", "member")
    switched = platform.switch_session_org(token, "clinica-sagasta")
    assert switched is not None
    assert switched.current_org_id == "clinica-sagasta"
    assert platform.load_session(token).current_org_id == "clinica-sagasta"


def test_a_person_belongs_to_several_clinics_and_the_roles_are_separate(platform):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    platform.create_organization("clinica-sagasta", "Clínica Sagasta")
    platform.add_membership(user.id, DEFAULT_ORG_ID, "owner")
    platform.add_membership(user.id, "clinica-sagasta", "member")
    assert platform.role_in(user.id, DEFAULT_ORG_ID) == "owner"
    assert platform.role_in(user.id, "clinica-sagasta") == "member"
    assert [m.org_id for m in platform.memberships_of(user.id)] == [
        DEFAULT_ORG_ID,
        "clinica-sagasta",
    ]


def test_a_revoked_membership_stops_working(platform):
    user = platform.create_user("ana@clinica.es", PASSWORD)
    platform.add_membership(user.id, DEFAULT_ORG_ID, "owner")
    platform.remove_membership(user.id, DEFAULT_ORG_ID)
    assert platform.role_in(user.id, DEFAULT_ORG_ID) is None


def test_duplicate_emails_and_unknown_roles_are_refused(platform):
    platform.create_user("ana@clinica.es", PASSWORD)
    with pytest.raises(StoreError):
        platform.create_user("ana@clinica.es", PASSWORD)
    user = platform.get_user_by_email("ana@clinica.es")
    with pytest.raises(StoreError):
        platform.add_membership(user.id, DEFAULT_ORG_ID, "superuser")


# ---- the bootstrap CLI ----------------------------------------------------
def test_the_bootstrap_creates_an_organisation_a_person_and_a_membership(tmp_path, monkeypatch):
    """There is no sign-up over HTTP: the first account is made with a shell."""
    from agent.accounts import bootstrap

    config = _settings(tmp_path, ops_secret_key=SECRET)
    monkeypatch.setattr(bootstrap, "settings", lambda: config)
    monkeypatch.setenv("OPS_BOOTSTRAP_PASSWORD", PASSWORD)

    assert bootstrap.main(
        ["--email", "ana@clinica.es", "--org", "clinica-sagasta", "--org-name", "Sagasta"]
    ) == 0

    platform = Store(tmp_path / "platform.db")
    user = platform.get_user_by_email("ana@clinica.es")
    assert user is not None
    assert platform.role_in(user.id, "clinica-sagasta") == "owner"
    assert platform.get_organization("clinica-sagasta").name == "Sagasta"


def test_the_bootstrap_stores_a_credential_by_name_and_prints_only_a_fingerprint(
    tmp_path, monkeypatch, capsys
):
    """Named, never pasted: a key on a command line is in the shell history."""
    from agent.accounts import bootstrap

    config = _settings(tmp_path, ops_secret_key=SECRET)
    monkeypatch.setattr(bootstrap, "settings", lambda: config)
    monkeypatch.setenv("PROSPER_KEY_SAGASTA", API_KEY)

    assert bootstrap.main(
        ["--org", "clinica-sagasta", "--credential-from-env", "PROSPER_KEY_SAGASTA"]
    ) == 0

    printed = capsys.readouterr().out
    assert API_KEY not in printed
    assert crypto.fingerprint(API_KEY) in printed
    assert Store(tmp_path / "platform.db").organization_api_key("clinica-sagasta", SECRET) == API_KEY


def test_the_bootstrap_refuses_to_store_a_credential_with_no_secret_key(tmp_path, monkeypatch):
    from agent.accounts import bootstrap

    config = _settings(tmp_path, ops_secret_key="")
    monkeypatch.setattr(bootstrap, "settings", lambda: config)
    monkeypatch.setenv("PROSPER_KEY_SAGASTA", API_KEY)
    assert bootstrap.main(["--credential-from-env", "PROSPER_KEY_SAGASTA"]) == 3
    assert Store(tmp_path / "platform.db").get_organization(DEFAULT_ORG_ID).has_credential is False


# ---- the scored-call path is untouched ------------------------------------
def test_the_clinic_client_a_call_builds_is_the_one_it_always_built(tmp_path, monkeypatch):
    """The whole point of the fallback. One organisation, no database: the
    client a ToolBox constructs carries the environment's key and the
    configured base url, exactly as before this package existed."""
    from agent.brain import deps

    config = _settings(
        tmp_path, prosper_api_key="env-key", prosper_api_base_url="https://clinic.example"
    )
    client = deps.try_clinic_client(config)
    assert client is not None
    assert client._api_key == "env-key"
    assert client._base_url == "https://clinic.example"


def test_a_second_clinics_client_carries_that_clinics_key(tmp_path):
    from agent.brain import deps

    config = _settings(tmp_path, prosper_api_key="env-key", ops_secret_key=SECRET)
    store = Store(tmp_path / "platform.db")
    store.migrate()
    store.create_organization("clinica-sagasta", "Clínica Sagasta")
    store.set_organization_credential("clinica-sagasta", "sagasta-key-abc", SECRET)
    assert deps.try_clinic_client(config, "clinica-sagasta")._api_key == "sagasta-key-abc"
    assert deps.try_clinic_client(config, DEFAULT_ORG_ID)._api_key == "env-key"


def test_broken_configuration_still_raises_out_of_the_client_builder(tmp_path):
    """`ensure_catalogue_warm` and `ops/live.py` both guard this call because
    it raises. It must keep raising rather than becoming a silent None."""
    from agent.brain import deps

    with pytest.raises(AttributeError):
        deps.try_clinic_client(object())
