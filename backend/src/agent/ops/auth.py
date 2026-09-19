"""Who is looking at the console, and which clinic they are looking at.

Before this module there was one shared secret and no idea who you were. A
token in a URL is not a person: it cannot belong to two clinics, it cannot be
revoked for one reader and kept for another, and it says nothing in an audit
line. So people now sign in and get a session, and the session carries the
`org_id` that the rest of the backend has been passing around since step 2.

Two doors, for two different kinds of caller, and deliberately not the same
door:

* **A person** signs in at `/ops/login` and rides a cookie. The session row
  names the user and the organisation they have selected, and switching
  clinic is an update to that row after a membership check.
* **A service** — the Next panel's server-side proxy — presents `OPS_TOKEN`
  in the `X-Ops-Token` header. It is a machine with one job and no identity
  to have.

The `?token=` query parameter was the *person's* version of the service door:
the one you use by pasting a URL into a browser. It closes the moment the
first person exists in the database, which is the whole of "no conviven dos
puertas" — before anyone is provisioned nothing changes, and after the first
person is, a person signs in.

Loopback with no `OPS_TOKEN` set is untouched. That is the local bench: the
evaluator drives `POST /turns` through this same gate from 127.0.0.1, and a
laptop that never had a secret still needs none.
"""
from __future__ import annotations

from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from agent.accounts.secrets import SecretsUnavailable
from agent.accounts.store import (
    CREDENTIAL_ROLES,
    SESSION_TTL,
    Session,
    Store,
    StoreError,
    store,
)
from agent.config import settings
from agent.orgs import DEFAULT_ORG_ID, InvalidOrgId, normalize_org_id

COOKIE_NAME = "ops_session"

router = APIRouter()


# ---- reaching the database without ever being the reason a page fails -----
def _store() -> Store | None:
    """The platform store, or None when there is no database on this host yet.

    A missing file is the normal state of the deployment this repository has
    been running all weekend, and it must cost nothing: no connection, no file
    creation, no exception.
    """
    try:
        platform = store(settings())
    except Exception:  # noqa: BLE001 - configuration problems are not a 500 here
        return None
    return platform if platform.exists else None


def people_are_provisioned() -> bool:
    """True once at least one person exists. False is "nothing has changed yet"."""
    platform = _store()
    if platform is None:
        return False
    try:
        return platform.user_count() > 0
    except Exception:  # noqa: BLE001
        return False


def session_of(request: Any) -> Session | None:
    """The live session behind this request's cookie, or None.

    Tolerant of a request object that is not a Starlette `Request`: the access
    gate is called from tests with a stand-in, and an attribute that is not
    there means "no cookie", never an error.
    """
    cookies = getattr(request, "cookies", None) or {}
    token = cookies.get(COOKIE_NAME) if hasattr(cookies, "get") else None
    if not token:
        return None
    platform = _store()
    if platform is None:
        return None
    try:
        return platform.load_session(token)
    except Exception:  # noqa: BLE001 - a broken database is not a valid session
        return None


class Principal(BaseModel):
    """Who is asking, once we know. Only ever built for a real session."""

    user_id: str
    email: str
    display_name: str
    org_id: str
    role: str


# One request asks "who is this" up to three times: the access gate, the org
# resolver and the route itself. The answer cannot change inside a request, so
# it is resolved once and kept on `request.state`.
_UNRESOLVED = object()


def principal_of(request: Any) -> Principal | None:
    """The signed-in person and their selected clinic, or None. Cached per request."""
    state = getattr(request, "state", None)
    if state is not None:
        cached = getattr(state, "ops_principal", _UNRESOLVED)
        if cached is not _UNRESOLVED:
            return cached  # type: ignore[return-value]
    person = _resolve_principal(request)
    if state is not None:
        # A request object that will not hold an attribute is not a reason to
        # fail: the cache is an optimisation, and the answer is already known.
        with suppress(Exception):
            state.ops_principal = person
    return person


def _resolve_principal(request: Any) -> Principal | None:
    """The database work behind `principal_of`."""
    session = session_of(request)
    if session is None:
        return None
    platform = _store()
    if platform is None:
        return None
    try:
        user = platform.get_user(session.user_id)
        role = platform.role_in(session.user_id, session.current_org_id)
    except Exception:  # noqa: BLE001
        return None
    if user is None or user.disabled or role is None:
        # A disabled account and a membership revoked mid-session both stop
        # working on the *next request*, not at the next login. This is why
        # the access gate asks for a principal and not merely for a session
        # row: a live row whose user no longer belongs anywhere is not a way
        # in, and must not quietly fall back to the default organisation.
        return None
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        org_id=session.current_org_id,
        role=role,
    )


def require_person(request: Request) -> Principal:
    """A signed-in person, or 401. For routes only a person may call."""
    person = principal_of(request)
    if person is None:
        raise HTTPException(401, "hace falta iniciar sesión")
    return person


def request_org_id(request: Any, asked: str | None = None) -> str:
    """Which organisation this request may read.

    * A signed-in person reads the clinic their session is pointed at, and may
      name another only if they are a member of it. Not being a member and the
      clinic not existing give the same 403, because they are the same answer
      to somebody trying org ids.
    * A service token or a loopback caller has no identity and therefore no
      membership, so it reads what it asks for and defaults to the one clinic
      this process serves — exactly what it read before sessions existed.
    """
    try:
        wanted = normalize_org_id(asked) if asked else None
    except InvalidOrgId as exc:
        raise HTTPException(400, "organización no válida") from exc

    person = principal_of(request)
    if person is None:
        return wanted or DEFAULT_ORG_ID
    if wanted is None or wanted == person.org_id:
        return person.org_id
    platform = _store()
    if platform is not None and platform.role_in(person.user_id, wanted) is not None:
        return wanted
    raise HTTPException(403, "no perteneces a esa organización")


# ---- the login page -------------------------------------------------------
_LOGIN_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Pronto — entrar</title><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
/* The panel's palette, not a second product's. This page and /equipo are the
   same thing to whoever is looking at them, and a dark blue form in front of a
   warm ivory panel says they were built by different people on different days. */
:root{
  --canvas:#fffefb; --fog:#f4f4f0; --ivory:#eee9df; --mist:#dcdfd9;
  --graphite:#1d211f; --steel:#4c534e; --quiet:#777e78; --ember:#e76432;
}
*{box-sizing:border-box}
body{
  margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
  background:var(--canvas); color:var(--graphite); padding:24px;
  font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-feature-settings:"cv05","ss01";
  /* A little warmth behind the card so it does not float on flat white. */
  background-image:radial-gradient(120% 90% at 50% -20%, var(--ivory) 0%, var(--canvas) 62%);
}
.card{width:100%; max-width:380px}
.mark{
  width:40px; height:40px; border-radius:11px; background:var(--graphite); color:var(--canvas);
  display:flex; align-items:center; justify-content:center;
  font-weight:600; font-size:19px; letter-spacing:-.04em; margin-bottom:22px;
}
h1{font-size:27px; line-height:1.15; letter-spacing:-.035em; margin:0 0 6px; font-weight:600}
.sub{color:var(--steel); font-size:14px; line-height:1.5; margin:0 0 28px}
form{
  background:var(--canvas); border:1px solid var(--mist); border-radius:18px;
  padding:24px; box-shadow:0 1px 2px rgba(29,33,31,.04), 0 12px 32px -18px rgba(29,33,31,.22);
}
label{
  display:block; font-size:11px; font-weight:500; color:var(--quiet);
  text-transform:uppercase; letter-spacing:.09em; margin:0 0 7px;
}
.field + .field{margin-top:18px}
input{
  width:100%; background:var(--fog); border:1px solid transparent; border-radius:11px;
  padding:11px 13px; font:inherit; font-size:15px; color:var(--graphite);
  transition:background .15s, border-color .15s, box-shadow .15s;
}
input::placeholder{color:var(--quiet)}
input:focus{
  outline:none; background:var(--canvas); border-color:var(--graphite);
  box-shadow:0 0 0 3px rgba(29,33,31,.08);
}
button{
  width:100%; margin-top:24px; background:var(--graphite); color:var(--canvas);
  border:0; border-radius:11px; padding:12px; font:inherit; font-size:15px; font-weight:500;
  cursor:pointer; transition:transform .08s, opacity .15s;
}
button:hover{opacity:.9}
button:active{transform:translateY(1px)}
.err{
  display:flex; gap:9px; align-items:flex-start;
  background:#fdf1ec; border:1px solid #f6d6c8; color:#8c3714;
  border-radius:11px; padding:11px 13px; font-size:13.5px; line-height:1.45; margin-bottom:20px;
}
.err b{color:var(--ember)}
.foot{margin-top:20px; font-size:12.5px; color:var(--quiet); line-height:1.5; text-align:center}
@media (prefers-color-scheme: dark){
  :root{
    --canvas:#14171a; --fog:#1b1f23; --ivory:#1b1f23; --mist:#2a2f35;
    --graphite:#eceee9; --steel:#a2aaa4; --quiet:#7d857f;
  }
  body{background-image:radial-gradient(120% 90% at 50% -20%, #1a1e22 0%, #14171a 62%)}
  button{background:var(--graphite); color:#14171a}
  .err{background:#2a1a14; border-color:#5a3020; color:#f0a884}
}
</style></head><body>
<div class="card">
  <div class="mark">P</div>
  <h1>Pronto</h1>
  <p class="sub">Consola de Clínica Arenal. Entra para ver las llamadas y gestionar el equipo.</p>
  <form method="post" action="/ops/login">
    __ERROR__
    <div class="field">
      <label for="email">Correo</label>
      <input id="email" name="email" type="email" autocomplete="username"
             placeholder="tu@clinica.es" required autofocus>
    </div>
    <div class="field">
      <label for="password">Contraseña</label>
      <input id="password" name="password" type="password"
             autocomplete="current-password" placeholder="••••••••" required>
    </div>
    <button type="submit">Entrar</button>
  </form>
  <p class="foot">Las cuentas las crea quien administra la clínica.</p>
</div>
</body></html>"""


def _login_page(error: str = "") -> str:
    block = f'<div class="err"><b>·</b><span>{error}</span></div>' if error else ""
    return _LOGIN_PAGE.replace("__ERROR__", block)


@router.get("/ops/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """The form. Already signed in? Straight to the console."""
    if principal_of(request) is not None:
        return RedirectResponse("/ops", status_code=303)
    if not people_are_provisioned():
        # Saying "there are no accounts" to a stranger tells them nothing they
        # could not learn by trying, and saves the one person who has to set
        # this up from guessing why their password does not work.
        return HTMLResponse(
            _login_page(
                "Todavía no hay ninguna cuenta. Créala con "
                "<code>python -m agent.accounts.bootstrap</code>."
            ),
            status_code=200,
        )
    return HTMLResponse(_login_page())


@router.post("/ops/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    """Check the password, open a session, set the cookie, go to the console.

    Deliberately `def` and not `async def`. scrypt costs about 40 ms, and this
    route is reachable without credentials by anyone who has the URL: on the
    event loop, a burst of attempts would be 40 ms of blocked loop each, on
    the single machine that is also carrying a three-minute scored call.
    Starlette runs a sync route in a threadpool, so the audio path never waits
    for somebody else's password check.

    There is no rate limit here yet. The threadpool bounds the damage to
    worker threads rather than to the loop, which is the part that would have
    been audible.
    """
    platform = _store()
    if platform is None:
        return HTMLResponse(_login_page("No hay base de datos en este host."), status_code=503)
    user = platform.authenticate(email, password)
    if user is None:
        # One message for "no such account", "wrong password" and "disabled".
        # Three messages is a way to enumerate who works here.
        return HTMLResponse(_login_page("Correo o contraseña incorrectos."), status_code=401)
    memberships = platform.memberships_of(user.id)
    if not memberships:
        return HTMLResponse(
            _login_page("Tu cuenta no pertenece a ninguna organización."), status_code=403
        )
    token = platform.create_session(user.id, memberships[0].org_id)
    response = RedirectResponse("/ops", status_code=303)
    _set_cookie(request, response, token)
    return response


@router.post("/ops/logout")
async def logout(request: Request, response: Response) -> Response:
    """Delete the row and clear the cookie. Both, so neither half survives."""
    cookies = getattr(request, "cookies", None) or {}
    token = cookies.get(COOKIE_NAME)
    platform = _store()
    if token and platform is not None:
        platform.delete_session(token)
    redirect = RedirectResponse("/ops/login", status_code=303)
    redirect.delete_cookie(COOKIE_NAME, path="/")
    return redirect


def _set_cookie(request: Request, response: Response, token: str) -> None:
    """HttpOnly always; Secure wherever the request arrived over TLS.

    `SameSite=Lax` is the CSRF control for every state-changing route here:
    a cross-site POST does not carry this cookie, so a form on another origin
    cannot switch somebody's organisation or write a credential.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )


# ---- the session, as the panel sees it ------------------------------------
class OrgView(BaseModel):
    """One clinic a person may switch to. No credential, ever — see below."""

    id: str
    name: str
    role: str
    # "Is a key loaded, and which one", never "what is the key". There is no
    # field on this model that could hold one, which is the point: a route
    # cannot leak what its response model cannot carry.
    has_credential: bool = False
    credential_fingerprint: str = ""
    credentials_updated_at: str | None = None


class SessionView(BaseModel):
    user_id: str
    email: str
    display_name: str
    org_id: str
    role: str
    organizations: list[OrgView] = Field(default_factory=list)


def _org_views(platform: Store, user_id: str) -> list[OrgView]:
    views: list[OrgView] = []
    for membership in platform.memberships_of(user_id):
        org = platform.get_organization(membership.org_id)
        views.append(
            OrgView(
                id=membership.org_id,
                name=membership.org_name,
                role=membership.role,
                has_credential=bool(org and org.has_credential),
                credential_fingerprint=(org.credential_fingerprint if org else ""),
                credentials_updated_at=(org.credentials_updated_at if org else None),
            )
        )
    return views


@router.get("/ops/api/session")
async def whoami(request: Request) -> SessionView:
    """Who I am and which clinics I can switch between. The panel's first call."""
    person = require_person(request)
    platform = _store()
    organizations = _org_views(platform, person.user_id) if platform else []
    return SessionView(
        user_id=person.user_id,
        email=person.email,
        display_name=person.display_name,
        org_id=person.org_id,
        role=person.role,
        organizations=organizations,
    )


class SwitchRequest(BaseModel):
    org_id: str


@router.post("/ops/api/session/org")
async def switch_org(request: Request, body: SwitchRequest) -> SessionView:
    """Point this session at another clinic. Membership is checked in the store.

    This is the whole of "cambiar de organización": everything downstream —
    the trace directory, the catalogue cache, the clinic credential — already
    takes `org_id` as an argument, so switching is one column.
    """
    person = require_person(request)
    platform = _store()
    if platform is None:
        raise HTTPException(503, "no hay base de datos en este host")
    cookies = getattr(request, "cookies", None) or {}
    try:
        wanted = normalize_org_id(body.org_id)
    except InvalidOrgId as exc:
        raise HTTPException(400, "organización no válida") from exc
    session = platform.switch_session_org(cookies.get(COOKIE_NAME, ""), wanted)
    if session is None:
        raise HTTPException(403, "no perteneces a esa organización")
    return SessionView(
        user_id=person.user_id,
        email=person.email,
        display_name=person.display_name,
        org_id=session.current_org_id,
        role=platform.role_in(person.user_id, session.current_org_id) or person.role,
        organizations=_org_views(platform, person.user_id),
    )


# ---- a clinic's credential: write-only over HTTP ---------------------------
class CredentialRequest(BaseModel):
    prosper_api_key: str = Field(min_length=8)


def require_member(request: Request, org_id: str) -> tuple[Store, str, Principal]:
    """A signed-in member of this organisation. Reads live behind this.

    Not being a member and the organisation not existing are the same 403,
    because they are the same answer to somebody trying org ids.
    """
    person = require_person(request)
    platform = _store()
    if platform is None:
        raise HTTPException(503, "no hay base de datos en este host")
    try:
        wanted = normalize_org_id(org_id)
    except InvalidOrgId as exc:
        raise HTTPException(400, "organización no válida") from exc
    if platform.role_in(person.user_id, wanted) is None:
        raise HTTPException(403, "no perteneces a esa organización")
    return platform, wanted, person


def require_admin(request: Request, org_id: str) -> tuple[Store, str, Principal]:
    """A member who may also write: owner or admin. Every write goes through here."""
    platform, wanted, person = require_member(request, org_id)
    if platform.role_in(person.user_id, wanted) not in CREDENTIAL_ROLES:
        raise HTTPException(403, "hace falta ser admin de la organización")
    return platform, wanted, person


def _require_credential_role(request: Request, org_id: str) -> tuple[Store, str, Principal]:
    return require_admin(request, org_id)


@router.get("/ops/api/orgs/{org_id}/credential")
async def credential_status(request: Request, org_id: str) -> OrgView:
    """Whether a key is loaded and which one — never what it is.

    There is no route that returns a clinic's Prosper key, and there is no
    model in this module with a field that could hold one. A key goes in and
    is only ever read again by the process that is about to call the clinic.
    """
    platform, wanted, person = _require_credential_role(request, org_id)
    org = platform.get_organization(wanted)
    if org is None:
        raise HTTPException(404, "organización no encontrada")
    return OrgView(
        id=org.id,
        name=org.name,
        role=platform.role_in(person.user_id, wanted) or "member",
        has_credential=org.has_credential,
        credential_fingerprint=org.credential_fingerprint,
        credentials_updated_at=org.credentials_updated_at,
    )


@router.put("/ops/api/orgs/{org_id}/credential")
async def set_credential(request: Request, org_id: str, body: CredentialRequest) -> OrgView:
    """Store this clinic's Prosper key, encrypted. The response is a fingerprint."""
    platform, wanted, person = _require_credential_role(request, org_id)
    try:
        org = platform.set_organization_credential(
            wanted, body.prosper_api_key, settings().ops_secret_key
        )
    except SecretsUnavailable as exc:
        # Refusing is the safe failure. Writing it in the clear onto the
        # volume is how a backup becomes a breach.
        raise HTTPException(503, "OPS_SECRET_KEY no está configurada en el backend") from exc
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return OrgView(
        id=org.id,
        name=org.name,
        role=platform.role_in(person.user_id, wanted) or "member",
        has_credential=org.has_credential,
        credential_fingerprint=org.credential_fingerprint,
        credentials_updated_at=org.credentials_updated_at,
    )


@router.delete("/ops/api/orgs/{org_id}/credential")
async def clear_credential(request: Request, org_id: str) -> OrgView:
    """Forget this clinic's key. The default clinic falls back to the environment."""
    platform, wanted, person = _require_credential_role(request, org_id)
    platform.clear_organization_credential(wanted)
    org = platform.get_organization(wanted)
    if org is None:
        raise HTTPException(404, "organización no encontrada")
    return OrgView(
        id=org.id,
        name=org.name,
        role=platform.role_in(person.user_id, wanted) or "member",
        has_credential=org.has_credential,
        credential_fingerprint=org.credential_fingerprint,
        credentials_updated_at=org.credentials_updated_at,
    )


__all__ = [
    "COOKIE_NAME",
    "Principal",
    "people_are_provisioned",
    "principal_of",
    "request_org_id",
    "require_admin",
    "require_member",
    "require_person",
    "router",
    "session_of",
]
