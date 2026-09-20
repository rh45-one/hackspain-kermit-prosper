"""People and routes as data, with the hand-written four still underneath.

The property that matters most here is not that the table works. It is that a
clinic which has configured **nothing** still has somebody to call, and calls
exactly the person it called before this table existed. An escalation that
resolves to nobody is discovered during a medical emergency, which is the one
time nobody is reading a panel.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.accounts import db as accounts_db
from agent.accounts import directory
from agent.accounts.store import Person, Route, Store, reset_store_cache, store
from agent.brain import deps
from agent.clinic import graph
from agent.config import Settings
from agent.ops import auth, console, live
from agent.ops import directory as ops_directory
from agent.orgs import DEFAULT_ORG_ID

TOKEN = "s3cret"
SERVICE = {"x-ops-token": TOKEN}
PASSWORD = "correcto-caballo-grapa-pila"
OTHER_ORG = "clinica-sagasta"


@pytest.fixture(autouse=True)
def _clean():
    reset_store_cache()
    directory.reset_defaults_cache()
    live._CACHE.clear()
    yield
    reset_store_cache()
    directory.reset_defaults_cache()
    live._CACHE.clear()


@pytest.fixture
def config(tmp_path, monkeypatch) -> Settings:
    made = Settings(
        _env_file=None, data_dir=str(tmp_path), ops_token=TOKEN, ops_secret_key="k" * 32
    )
    for module in (console, live, auth, ops_directory):
        monkeypatch.setattr(module, "settings", lambda made=made: made)
    return made


@pytest.fixture
def platform(config) -> Store:
    made = store(config)
    made.migrate()
    made.create_organization(OTHER_ORG, "Clínica Sagasta")
    return made


@pytest.fixture
def client():
    return TestClient(console.app)


def sign_in(client, platform, email: str, org_id: str, role: str):
    user = platform.get_user_by_email(email) or platform.create_user(email, PASSWORD)
    platform.add_membership(user.id, org_id, role)
    response = client.post(
        "/ops/login", data={"email": email, "password": PASSWORD}, follow_redirects=False
    )
    assert response.status_code == 303
    return user


# ---- nothing configured behaves exactly as today --------------------------
def test_the_defaults_are_read_from_the_graph_and_not_copied(config):
    """If this file restated the four roles they would drift the day somebody
    adds a fifth. They are read off `graph`'s own tables instead."""
    assert directory.escalation_targets(DEFAULT_ORG_ID) == list(graph._ROLES)


def test_resolving_the_defaults_never_calls_back_into_the_graph_builder(config, monkeypatch):
    """`graph.build` is about to call `escalation_targets`. If this module
    resolved its defaults through `build`, that would be a function calling
    the function that calls it. It reads the constants instead."""

    def explode(*_args, **_kwargs):
        raise AssertionError("graph.build must not be on this path")

    monkeypatch.setattr(graph, "build", explode)
    directory.reset_defaults_cache()
    assert len(directory.routes_for(DEFAULT_ORG_ID, config)) == 18
    assert directory.escalation_targets(DEFAULT_ORG_ID, config) == list(graph._ROLES)


def test_the_graph_may_publish_its_declared_tables_without_breaking_this(config, monkeypatch):
    """`DECLARED_ROLES` is read first so those names can become public."""
    monkeypatch.setattr(
        graph, "DECLARED_ROLES", (("triage", "Triaje", "Decide quién pasa."),), raising=False
    )
    directory.reset_defaults_cache()
    assert directory.escalation_targets(DEFAULT_ORG_ID, config) == [
        ("triage", "Triaje", "Decide quién pasa.")
    ]


def test_every_reason_routes_exactly_where_it_routed_before(config):
    """The eighteen endings, unchanged, for an organisation with no rows."""
    assert directory.escalation_routes(DEFAULT_ORG_ID) == graph._ESCALATION
    for reason in deps.CLOSED_REASONS:
        declared = graph.who_to_call(reason)
        route = directory.route_for(DEFAULT_ORG_ID, reason)
        assert route is not None, reason
        assert (route.person_slug, route.urgency, route.detail) == (
            declared.target,
            declared.urgency,
            declared.detail,
        )


def test_all_eighteen_reasons_have_somebody(config):
    assert len(directory.routes_for(DEFAULT_ORG_ID)) == len(deps.CLOSED_REASONS)
    assert directory.unreachable_routes(DEFAULT_ORG_ID) == []


def test_with_no_database_at_all_the_defaults_answer(tmp_path, monkeypatch):
    """The deployment as it stands: no file, and every escalation still lands."""
    made = Settings(_env_file=None, data_dir=str(tmp_path))
    assert not (tmp_path / "platform.db").exists()
    assert len(directory.routes_for(DEFAULT_ORG_ID, made)) == 18
    assert directory.escalation_targets(DEFAULT_ORG_ID, made) == list(graph._ROLES)
    assert not (tmp_path / "platform.db").exists()


def test_a_database_that_has_not_been_migrated_yet_still_answers(tmp_path):
    """The file on the Fly volume is at v1 until the next boot migrates it.

    Between the deploy and the migration the tables do not exist, and the
    answer to "who do I call about a medical emergency" must not be an
    exception.
    """
    import sqlite3

    path = tmp_path / "platform.db"
    sqlite3.connect(path).close()  # an empty file: no tables at all
    made = Settings(_env_file=None, data_dir=str(tmp_path))
    assert directory.route_for(DEFAULT_ORG_ID, "medical_emergency", made).person_slug == "emergency"
    assert len(directory.routes_for(DEFAULT_ORG_ID, made)) == 18


def test_the_migration_adds_the_tables_to_an_existing_database(tmp_path):
    """v1 was deployed with users in it. Upgrading may not lose them."""
    from agent.accounts.db import connect

    path = tmp_path / "platform.db"
    made = Store(path)
    made.migrate()
    user = made.create_user("ana@clinica.es", PASSWORD)
    with connect(path) as db:
        db.execute("DROP TABLE people")
        db.execute("DROP TABLE routes")
        db.execute("PRAGMA user_version = 1")
    assert Store(path).migrate() == accounts_db.SCHEMA_VERSION
    assert Store(path).get_user(user.id) is not None
    assert Store(path).list_people(DEFAULT_ORG_ID) == []


# ---- the overlay ----------------------------------------------------------
def test_a_configured_person_replaces_that_default_and_keeps_the_others(platform, config):
    platform.upsert_person(
        DEFAULT_ORG_ID,
        Person(slug="on_call", name="Dra. Ana Ruiz", role="on_call", languages=("es", "ca")),
    )
    people = {p.slug: p for p in directory.people_for(DEFAULT_ORG_ID, config)}
    assert people["on_call"].name == "Dra. Ana Ruiz"
    assert people["on_call"].source == "configured"
    # Configuring one role may not silently delete the other three.
    assert {"front_desk", "manager", "emergency"} <= set(people)
    assert people["front_desk"].source == "default"


def test_somebody_new_is_added_alongside_the_declared_roles(platform, config):
    platform.upsert_person(
        DEFAULT_ORG_ID, Person(slug="ana-ruiz", name="Dra. Ana Ruiz", role="provider")
    )
    slugs = [p.slug for p in directory.people_for(DEFAULT_ORG_ID, config)]
    assert slugs[:4] == [role[0] for role in graph._ROLES]
    assert "ana-ruiz" in slugs


def test_an_inactive_person_is_not_callable_and_does_not_restore_the_default(platform, config):
    platform.upsert_person(
        DEFAULT_ORG_ID, Person(slug="on_call", name="Dra. Ana Ruiz", role="on_call", active=False)
    )
    slugs = {p.slug for p in directory.people_for(DEFAULT_ORG_ID, config)}
    assert "on_call" not in slugs
    assert directory.person_for(DEFAULT_ORG_ID, "on_call", config) is None


def test_configuring_one_route_keeps_the_other_seventeen(platform, config):
    platform.upsert_person(DEFAULT_ORG_ID, Person(slug="ana-ruiz", name="Ana", role="manager"))
    platform.upsert_route(
        DEFAULT_ORG_ID,
        Route(reason="no_availability", person_slug="ana-ruiz", urgency="now", detail="Llámala."),
    )
    routes = {r.reason: r for r in directory.routes_for(DEFAULT_ORG_ID, config)}
    assert len(routes) == 18
    assert routes["no_availability"].person_slug == "ana-ruiz"
    assert routes["no_availability"].source == "configured"
    # Everything else is still the declared route.
    assert routes["medical_emergency"].person_slug == "emergency"
    assert routes["medical_emergency"].source == "default"


def test_deleting_a_route_restores_the_declared_one(platform, config):
    platform.upsert_person(DEFAULT_ORG_ID, Person(slug="ana-ruiz", name="Ana", role="manager"))
    platform.upsert_route(
        DEFAULT_ORG_ID, Route(reason="no_availability", person_slug="ana-ruiz", urgency="now")
    )
    platform.delete_route(DEFAULT_ORG_ID, "no_availability")
    route = directory.route_for(DEFAULT_ORG_ID, "no_availability", config)
    assert (route.person_slug, route.urgency, route.source) == ("manager", "today", "default")


def test_a_route_pointing_at_nobody_is_reported_and_never_hidden(platform, config):
    platform.upsert_person(DEFAULT_ORG_ID, Person(slug="ana-ruiz", name="Ana", role="manager"))
    platform.upsert_route(
        DEFAULT_ORG_ID, Route(reason="no_availability", person_slug="ana-ruiz", urgency="now")
    )
    platform.delete_person(DEFAULT_ORG_ID, "ana-ruiz")
    broken = directory.unreachable_routes(DEFAULT_ORG_ID, config)
    assert [r.reason for r in broken] == ["no_availability"]
    # And the reason still resolves to something rather than to nothing.
    assert directory.route_for(DEFAULT_ORG_ID, "no_availability", config) is not None


def test_two_organisations_keep_separate_directories(platform, config):
    platform.upsert_person(DEFAULT_ORG_ID, Person(slug="ana-ruiz", name="Ana", role="manager"))
    assert directory.person_for(OTHER_ORG, "ana-ruiz", config) is None
    assert directory.escalation_targets(OTHER_ORG, config) == list(graph._ROLES)


# ---- the call profile -----------------------------------------------------
def test_the_language_comes_from_the_person_when_they_are_not_in_the_catalogue(platform, config):
    """A receptionist is not a provider and had no answer before this."""
    platform.upsert_person(
        DEFAULT_ORG_ID,
        Person(slug="front_desk", name="Marta", role="front_desk", languages=("es", "en")),
    )
    brief = directory.cover_brief(DEFAULT_ORG_ID, "out_of_scope", config=config)
    assert brief["speaks"] == "español, inglés"
    assert brief["who"] == "Marta"


def test_a_doctor_with_nothing_written_down_still_resolves_off_the_catalogue(
    platform, config, monkeypatch
):
    """Exactly what `/ws/demo` did before: `PR01` -> ['ca','en','es']."""

    class FakeProvider:
        languages = ("ca", "en", "es")

    class FakeCache:
        def provider_by_id(self, ident):
            return FakeProvider() if ident == "PR01" else None

    monkeypatch.setattr(deps, "try_catalogue_cache", lambda org_id=None: FakeCache())
    platform.upsert_person(
        DEFAULT_ORG_ID, Person(slug="ana-ruiz", name="Dra. Ana", role="provider", provider_id="PR01")
    )
    person = directory.person_for(DEFAULT_ORG_ID, "ana-ruiz", config)
    assert directory.said(directory.languages_of(person, DEFAULT_ORG_ID, config)) == (
        "català, inglés, español"
    )


def test_what_is_written_down_wins_over_the_catalogue(platform, config, monkeypatch):
    class FakeCache:
        def provider_by_id(self, ident):
            raise AssertionError("the catalogue must not be consulted")

    monkeypatch.setattr(deps, "try_catalogue_cache", lambda org_id=None: FakeCache())
    platform.upsert_person(
        DEFAULT_ORG_ID,
        Person(slug="ana-ruiz", name="Dra. Ana", role="provider", provider_id="PR01",
               languages=("en",)),
    )
    person = directory.person_for(DEFAULT_ORG_ID, "ana-ruiz", config)
    assert directory.languages_of(person, DEFAULT_ORG_ID, config) == ("en",)


def test_the_brief_carries_the_per_person_call_profile(platform, config):
    """What Ginés asked for: the configuration travels with the person."""
    platform.upsert_person(
        DEFAULT_ORG_ID,
        Person(
            slug="on_call",
            name="Dra. Ana Ruiz",
            role="on_call",
            languages=("ca",),
            opening="Dile que es de la clínica y que es por una guardia.",
            may_ask=("si puede cubrir el hueco", "a qué hora le viene bien"),
            must_not_ask=("datos del paciente", "nada de su vida personal"),
        ),
    )
    # `provider_on_leave` reaches Coordinación by declaration, so point it at
    # her: the brief must describe the person the route actually lands on.
    platform.upsert_route(
        DEFAULT_ORG_ID,
        Route(reason="provider_on_leave", person_slug="on_call", urgency="now", detail="Guardia."),
    )
    brief = directory.cover_brief(DEFAULT_ORG_ID, "provider_on_leave", gap="jueves 10:00",
                                  config=config)
    assert brief["who"] == "Dra. Ana Ruiz"
    assert brief["speaks"] == "català"
    assert brief["gap"] == "jueves 10:00"
    assert "guardia" in brief["opening"]
    assert "si puede cubrir el hueco" in brief["may_ask"]
    assert "datos del paciente" in brief["must_not_ask"]


def test_two_people_on_the_same_reason_are_opened_differently(platform, config):
    """One configuration per person, not one per deployment."""
    for slug, name, opening, languages in (
        ("on_call", "Ana", "Directa: es una guardia.", ("ca",)),
        ("manager", "Berta", "Con contexto: decide ella.", ("en",)),
    ):
        platform.upsert_person(
            DEFAULT_ORG_ID,
            Person(slug=slug, name=name, role=slug, opening=opening, languages=languages),
        )
    ana = directory.cover_brief(DEFAULT_ORG_ID, "x", person_slug="on_call", config=config)
    berta = directory.cover_brief(DEFAULT_ORG_ID, "x", person_slug="manager", config=config)
    assert ana["opening"] != berta["opening"]
    assert ana["speaks"] == "català" and berta["speaks"] == "inglés"


def test_the_brief_never_carries_a_telephone_number_or_an_email(platform, config):
    """A phone number is how a human rings somebody. The model never needs it."""
    platform.upsert_person(
        DEFAULT_ORG_ID,
        Person(
            slug="on_call",
            name="Dra. Ana Ruiz",
            role="on_call",
            phone="600111222",
            email="ana@clinica.es",
        ),
    )
    brief = directory.cover_brief(DEFAULT_ORG_ID, "provider_on_leave", config=config)
    assert "600111222" not in str(brief)
    assert "ana@clinica.es" not in str(brief)


def test_an_explicit_argument_always_wins_over_the_route(platform, config):
    """The panel knows what it was looking at; this must not argue with it."""
    brief = directory.cover_brief(
        DEFAULT_ORG_ID, "no_availability", who="Quien sea", urgency="now", config=config
    )
    assert brief["who"] == "Quien sea"
    assert brief["urgency"] == "now"


# ---- over HTTP ------------------------------------------------------------
def test_a_member_reads_the_directory(platform, client):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "member")
    people = client.get(f"/ops/api/orgs/{DEFAULT_ORG_ID}/people")
    assert people.status_code == 200
    assert [p["slug"] for p in people.json()] == [role[0] for role in graph._ROLES]
    assert all(p["source"] == "default" for p in people.json())
    routes = client.get(f"/ops/api/orgs/{DEFAULT_ORG_ID}/routes")
    assert routes.status_code == 200
    assert len(routes.json()) == 18
    assert all(r["reachable"] for r in routes.json())


def test_a_member_may_not_write(platform, client):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "member")
    written = client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/people/ana-ruiz", json={"name": "Ana"}
    )
    assert written.status_code == 403


def test_an_admin_writes_a_person_and_a_route(platform, client, config):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "admin")
    written = client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/people/ana-ruiz",
        json={
            "name": "Dra. Ana Ruiz",
            "role": "on_call",
            "languages": ["ca", "es"],
            "opening": "Es por una guardia.",
            "may_ask": ["si puede cubrir"],
            "must_not_ask": ["datos del paciente"],
            "phone": "600111222",
        },
    )
    assert written.status_code == 200
    assert written.json()["source"] == "configured"

    routed = client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/routes/provider_on_leave",
        json={"person_slug": "ana-ruiz", "urgency": "now", "detail": "Cubre ella."},
    )
    assert routed.status_code == 200
    assert routed.json()["reachable"] is True
    assert directory.route_for(DEFAULT_ORG_ID, "provider_on_leave", config).person_slug == "ana-ruiz"


def test_a_route_to_somebody_who_does_not_exist_is_refused(platform, client):
    """Finding this out during a medical emergency is the failure to avoid."""
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "admin")
    refused = client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/routes/no_availability",
        json={"person_slug": "nadie", "urgency": "now"},
    )
    assert refused.status_code == 400
    assert "nadie" in refused.json()["detail"]


def test_a_reason_the_clinic_does_not_have_is_refused(platform, client):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "admin")
    assert (
        client.put(
            f"/ops/api/orgs/{DEFAULT_ORG_ID}/routes/inventada",
            json={"person_slug": "manager", "urgency": "now"},
        ).status_code
        == 400
    )


def test_an_urgency_the_graph_does_not_draw_is_refused(platform, client):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "admin")
    assert (
        client.put(
            f"/ops/api/orgs/{DEFAULT_ORG_ID}/routes/no_availability",
            json={"person_slug": "manager", "urgency": "inmediatamente"},
        ).status_code
        == 400
    )


def test_a_slug_that_could_be_a_path_is_refused(platform, client):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "admin")
    assert client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/people/..", json={"name": "Ana"}
    ).status_code in (400, 404)


def test_deleting_a_configured_role_restores_the_declared_one(platform, client):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "admin")
    client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/people/on_call", json={"name": "Dra. Ana", "role": "on_call"}
    )
    after = client.delete(f"/ops/api/orgs/{DEFAULT_ORG_ID}/people/on_call")
    assert after.status_code == 200
    restored = {p["slug"]: p for p in after.json()}["on_call"]
    assert restored["source"] == "default"
    assert restored["name"] == "Médico de guardia"


def test_one_organisation_cannot_read_or_write_anothers_directory(platform, client):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "owner")
    assert client.get(f"/ops/api/orgs/{OTHER_ORG}/people").status_code == 403
    assert client.get(f"/ops/api/orgs/{OTHER_ORG}/routes").status_code == 403
    assert (
        client.put(f"/ops/api/orgs/{OTHER_ORG}/people/x", json={"name": "X"}).status_code == 403
    )


def test_the_directory_is_behind_the_ops_door_as_well(platform, client):
    """Staff telephone numbers are here, so it is behind both checks."""
    assert client.get(f"/ops/api/orgs/{DEFAULT_ORG_ID}/people").status_code == 401
    # A service token passes the door and is still not a member of anything.
    assert (
        client.get(f"/ops/api/orgs/{DEFAULT_ORG_ID}/people", headers=SERVICE).status_code == 401
    )


def test_the_call_profile_screen_shows_what_the_call_would_open_with(platform, client, config):
    sign_in(client, platform, "ana@clinica.es", DEFAULT_ORG_ID, "admin")
    client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/people/on_call",
        json={
            "name": "Dra. Ana Ruiz",
            "role": "on_call",
            "languages": ["ca"],
            "opening": "Es por una guardia.",
            "phone": "600111222",
        },
    )
    client.put(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/routes/provider_on_leave",
        json={"person_slug": "on_call", "urgency": "now"},
    )
    shown = client.get(
        f"/ops/api/orgs/{DEFAULT_ORG_ID}/people/on_call/call-profile",
        params={"reason": "provider_on_leave", "gap": "jueves 10:00"},
    )
    assert shown.status_code == 200
    body = shown.json()
    # The same function the call itself uses, so the screen cannot drift.
    assert body["brief"] == directory.cover_brief(
        DEFAULT_ORG_ID, "provider_on_leave", gap="jueves 10:00", person_slug="on_call",
        config=config,
    )
    assert body["brief"]["speaks"] == "català"
    # The contact detail is on the person, for a human, and not in the brief.
    assert body["person"]["phone"] == "600111222"
    assert "600111222" not in str(body["brief"])


# ---- una voz por persona --------------------------------------------------
def test_each_person_can_have_their_own_voice(tmp_path):
    """Cuarenta y dos personas y una sola voz es un agente disfrazado de 42."""
    from agent.accounts import db
    from agent.accounts.store import Person, Store

    path = str(tmp_path / "platform.db")
    db.migrate(path)
    shop = Store(path)
    shop.upsert_person(
        DEFAULT_ORG_ID, Person(slug="hugo", name="Hugo", role="ORL", voice="Aoede")
    )

    assert shop.get_person(DEFAULT_ORG_ID, "hugo").voice == "Aoede"


def test_an_invented_voice_never_reaches_the_engine():
    """Un nombre inventado en una fila tiraría el socket al abrirlo.

    Y eso convierte un error de configuración en una llamada que no suena, que
    es el peor sitio donde puede aparecer.
    """
    from agent.voice.gemini_live import _gemini_voice_id

    class S:
        gemini_voice_id = "Charon"

    assert _gemini_voice_id(S(), "Aoede") == "Aoede"
    assert _gemini_voice_id(S(), "Pepito") == "Charon"
    assert _gemini_voice_id(S(), "") == "Charon"


def test_the_voice_travels_in_the_brief(tmp_path, monkeypatch):
    """El informe es lo que viaja de la ficha de una persona a la llamada."""
    from agent.accounts import db
    from agent.accounts import directory as accounts_directory
    from agent.accounts import store as accounts_store
    from agent.accounts.store import Person, Route, Store, _store_at

    path = str(tmp_path / "platform.db")
    db.migrate(path)
    monkeypatch.setattr(accounts_store, "store", lambda config=None: _store_at(path))
    monkeypatch.setattr(accounts_directory, "store", lambda config=None: _store_at(path))
    shop = Store(path)
    shop.upsert_person(
        DEFAULT_ORG_ID, Person(slug="hugo", name="Hugo", role="ORL", voice="Leda")
    )
    shop.upsert_route(
        DEFAULT_ORG_ID, Route(reason="provider_on_leave", person_slug="hugo", urgency="today")
    )

    assert accounts_directory.cover_brief(DEFAULT_ORG_ID, "provider_on_leave")["voice"] == "Leda"
