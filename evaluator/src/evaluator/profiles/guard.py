"""The laboratory guard: this bench never touches production.

Port `7860` is not a port. It is the instance with the ngrok tunnel registered
in the Prosper panel, the one that answers *scored* calls, and it is running
right now on the machine this package was written on. Any profile whose
destination resolves to it — or to any other official host — is refused with a
message that says exactly that, before a socket is opened.

Three refusals, in the order they matter:

1. **Port 7860.** Never a destination for this bench, in either direction.
2. **Official/production hosts.** A URL that is not a local or private-network
   address is refused; `prosper`, `hackspain` and `ngrok` names are called out
   by name so the message reads as the reason, not as a parse failure.
3. **Occupied ports**, probed only when the lab would *start* something. Loading
   a profile for a live session talks to a process that must already be
   listening, so the occupancy check is opt-in (`probe_ports=True`) and used by
   the launcher path, never by the chat path.
"""
from __future__ import annotations

import hashlib
import socket
from urllib.parse import urlsplit

import httpx

from evaluator.profiles.schema import AgentProfile

# The scored instance. See README, "Nunca uses el 7860".
PRODUCTION_VOICE_PORT = 7860

# Hosts this machine can talk to without leaving the lab.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})

# Names that mean an official or published destination. Matched against the
# hostname, so `prosper-x.ngrok-free.app` is refused by either token.
OFFICIAL_HOST_MARKERS = ("prosper", "hackspain", "ngrok", "arena", ".run.app")

_SCHEME_DEFAULT_PORTS = {"ws": 80, "wss": 443, "http": 80, "https": 443}

_ENDPOINT_LABELS = (
    ("ws_url", "voice"),
    ("text_url", "text"),
    ("usage_url", "usage"),
)


class LaboratoryRefusal(ValueError):
    """A profile the laboratory refuses to use, with every reason listed."""

    def __init__(self, profile_id: str, problems: list[str]) -> None:
        self.profile_id = profile_id
        self.problems = list(problems)
        super().__init__(
            f"perfil '{profile_id}' rechazado por la guarda del laboratorio: "
            + "; ".join(self.problems)
        )


def _endpoint_urls(profile: AgentProfile) -> list[tuple[str, str]]:
    """Declared endpoints, as (field name, url) pairs, in contract order."""
    values = profile.endpoints.model_dump()
    return [(field, values[field]) for field, _ in _ENDPOINT_LABELS if values.get(field)] + [
        ("clinic_url", profile.laboratory.clinic_url)
    ]


def _is_private_host(host: str) -> bool:
    """True for the loopback range and RFC1918 literals, never for a name."""
    if host in LOOPBACK_HOSTS:
        return True
    if host.startswith("127."):
        return True
    octets = host.split(".")
    if len(octets) != 4 or not all(part.isdigit() for part in octets):
        return False
    first, second = int(octets[0]), int(octets[1])
    if first == 10:
        return True
    if first == 192 and second == 168:
        return True
    return first == 172 and 16 <= second <= 31


def _host_and_port(url: str) -> tuple[str | None, int | None]:
    parts = urlsplit(url if "://" in url else f"//{url}")
    host = (parts.hostname or "").lower() or None
    port = parts.port
    if port is None:
        port = _SCHEME_DEFAULT_PORTS.get(parts.scheme)
    return host, port


def destination_problems(profile: AgentProfile) -> list[str]:
    """Refusals about *where* a profile points. Empty means the lab may talk to it."""
    problems: list[str] = []
    for field, url in _endpoint_urls(profile):
        host, port = _host_and_port(url)
        label = f"endpoints.{field}"
        if port == PRODUCTION_VOICE_PORT:
            problems.append(
                f"destino oficial/producción: {label} usa el puerto {PRODUCTION_VOICE_PORT}, "
                "que atiende llamadas puntuadas (nunca es un destino del laboratorio)"
            )
            continue
        if not host:
            problems.append(f"{label}: no se pudo leer el host de {url!r}")
            continue
        if any(marker in host for marker in OFFICIAL_HOST_MARKERS):
            problems.append(
                f"destino oficial/producción: {label} apunta a {host!r}, que no es local"
            )
            continue
        if not _is_private_host(host):
            problems.append(
                f"destino remoto: {label} apunta a {host!r}; el laboratorio solo habla "
                "con 127.0.0.1 o la red privada"
            )
    return problems


def port_is_free(host: str, port: int) -> bool:
    """True when nothing is listening on `host:port` (bind probe, no traffic).

    Refuses to probe the production port at all: the guard answers about 7860
    from the constant, never by touching the socket.
    """
    if port == PRODUCTION_VOICE_PORT:
        return False
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    probe_host = "::1" if host in {"::1", "localhost"} else host
    probe_host = "127.0.0.1" if probe_host == "0.0.0.0" else probe_host
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((probe_host, port))
        except OSError:
            return False
    return True


def port_problems(profile: AgentProfile) -> list[str]:
    """Refusals about ports the lab would bind if it started this profile."""
    problems: list[str] = []
    _, port = _host_and_port(profile.endpoints.ws_url or "")
    port = port or profile.laboratory.voice_port
    if port == PRODUCTION_VOICE_PORT:
        problems.append(
            f"puerto {PRODUCTION_VOICE_PORT}: es la instancia de producción; el laboratorio "
            "no arranca nada ahí"
        )
    elif not port_is_free("127.0.0.1", port):
        problems.append(
            f"puerto {port} ya está ocupado: el laboratorio no arranca nada encima de "
            "otro proceso"
        )
    return problems


def laboratory_problems(profile: AgentProfile, *, probe_ports: bool = False) -> list[str]:
    """Every laboratory refusal for this profile, destination first."""
    problems = destination_problems(profile)
    if probe_ports and not problems:
        problems.extend(port_problems(profile))
    return problems


def assert_laboratory_profile(profile: AgentProfile, *, probe_ports: bool = False) -> None:
    """Raise `LaboratoryRefusal` when this profile must not be used."""
    problems = laboratory_problems(profile, probe_ports=probe_ports)
    if problems:
        raise LaboratoryRefusal(profile.id, problems)


async def inspect_profile(profile: AgentProfile) -> dict:
    assert_laboratory_profile(profile)
    if profile.engine not in {"cascade", "gemini_live"}:
        return {"ready": True, "verified": False, "reason": "El agente externo no declara identidad verificable."}
    parts = urlsplit(profile.endpoints.ws_url or profile.endpoints.text_url or "")
    scheme = "https" if parts.scheme in {"https", "wss"} else "http"
    url = f"{scheme}://{parts.netloc}/lab/identity"
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(url)
            response.raise_for_status()
            identity = response.json()
        if not isinstance(identity, dict):
            raise TypeError("identity")
    except (httpx.HTTPError, ValueError, TypeError):
        return {"ready": False, "verified": False,
                "reason": "No se pudo verificar el agente. Arranca o actualiza el perfil con TURNS_ADAPTER=1."}
    if identity.get("engine") != profile.engine:
        return {"ready": False, "verified": False,
                "reason": "El motor activo no coincide con el perfil seleccionado."}
    expected = hashlib.sha256(profile.laboratory.clinic_url.rstrip("/").encode()).hexdigest()
    if identity.get("clinic_fingerprint") != expected:
        return {"ready": False, "verified": False,
                "reason": "El agente no apunta a la clínica del perfil. No se ha iniciado ninguna llamada."}
    return {"ready": True, "verified": True,
            **{key: identity.get(key) for key in ("engine", "model", "text_model", "version", "config_hash")}}
