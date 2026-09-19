"""Post-hoc observer: turn the backend's real calls into evaluator evidence.

The backend appends one JSONL audit per call under `DATA_DIR/calls/`. That
file is evidence the evaluator can read without changing the backend, and it
carries everything the wire cannot show: full transcripts, the complete
payload of every queued action, the submission flush, and the identity steps.

Two rules, inherited from `agent_audit.py` and the rest of this package:

- The audit is evidence, not a contract. Corrupt, partial or unknown lines
  are skipped; a half-written file (the backend appends while the call is
  live) must still load.
- The evaluator owns the oracle. A real call is only *scored* when a
  human-authored map ties its call_id to a scenario; untagged calls are
  reported as informational (what was sent, what leaked) and never invent a
  verdict.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from evaluator.models import ROUTE_TO_VERB, Scenario, canonical_action


@dataclass
class BackendCall:
    """What one backend audit file says about one real call."""

    call_id: str
    path: Path
    engine: str | None = None
    from_number: str | None = None
    started_at: str | None = None
    last_event_at: str | None = None
    caller_text: str = ""
    assistant_text: str = ""
    # Canonical actions the backend queued (route → verb, fields kept flat).
    actions: list[dict[str, Any]] = field(default_factory=list)
    # Raw submission flush events: one per `submitted` line, backend truth.
    submissions: list[dict[str, Any]] = field(default_factory=list)
    identity_patient_id: str | None = None
    ended: bool = False
    elapsed_s: float | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def caller_chars(self) -> int:
        return len(self.caller_text.strip())

    @property
    def assistant_chars(self) -> int:
        return len(self.assistant_text.strip())


def _text(data: dict[str, Any]) -> str:
    value = data.get("text")
    return value if isinstance(value, str) else ""


def _queue_action(data: dict[str, Any], call: BackendCall) -> None:
    """Convert one `action_queued` payload into a canonical evaluator action."""
    route = data.get("route")
    verb = ROUTE_TO_VERB.get(str(route))
    if verb is None:
        call.problems.append(f"action_queued con ruta desconocida: {route!r}")
        return
    fields = {k: v for k, v in data.items() if k not in ("route", "ts")}
    call.actions.append(canonical_action({"action": verb, **fields}))


def load_backend_call(path: Path) -> BackendCall:
    """Read one `calls/<call_id>.jsonl`, tolerating corrupt or partial lines."""
    call = BackendCall(call_id=path.stem, path=path)
    caller_parts: list[str] = []
    assistant_parts: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        event = record.get("event")
        data = record.get("data")
        data = data if isinstance(data, dict) else {}
        ts = record.get("ts")
        if isinstance(ts, str):
            call.started_at = call.started_at or ts
            call.last_event_at = ts
        if event == "engine_selected":
            engine = data.get("engine")
            call.engine = engine if isinstance(engine, str) else None
        elif event == "call_context_created":
            number = data.get("from_number")
            call.from_number = number if isinstance(number, str) else None
        elif event == "transcript":
            text = _text(data)
            if not text:
                continue
            # The audit streams transcript fragments; the wire-level turn
            # boundaries are unreliable, so the leak check reads each side as
            # one continuous string (a conservative local approximation).
            if data.get("role") == "caller":
                caller_parts.append(text)
            elif data.get("role") == "assistant":
                assistant_parts.append(text)
        elif event == "action_queued":
            _queue_action(data, call)
        elif event == "submitted":
            route = data.get("route")
            call.submissions.append({"route": route, "ts": ts})
        elif event == "identity_confirmed":
            patient = data.get("patient_id")
            call.identity_patient_id = patient if isinstance(patient, str) else None
        elif event == "call_ended":
            call.ended = True
            elapsed = data.get("elapsed_s")
            call.elapsed_s = elapsed if isinstance(elapsed, (int, float)) else None
    call.caller_text = "".join(caller_parts)
    call.assistant_text = "".join(assistant_parts)
    return call


def load_backend_calls(calls_dir: Path | str) -> list[BackendCall]:
    """Load every `*.jsonl` in the agent's `calls/` dir (or the DATA_DIR itself)."""
    base = Path(calls_dir)
    if any(base.glob("*.jsonl")):
        directory = base
    elif (base / "calls").is_dir():
        directory = base / "calls"
    else:
        raise FileNotFoundError(f"no hay audit de llamadas en {base} ni en {base / 'calls'}")
    return [load_backend_call(p) for p in sorted(directory.glob("*.jsonl"))]


def _resolve_scenario_path(base: Path, scenario_path: str) -> Path:
    """Map entries may be relative to the map file or to the cwd (repo root)."""
    path = Path(scenario_path)
    if path.is_absolute():
        return path
    beside_map = base / path
    return beside_map if beside_map.is_file() else path


class OracleMap:
    """call_id → scenario, by exact id or unique prefix."""

    def __init__(self, map_path: Path | str) -> None:
        raw = yaml.safe_load(Path(map_path).read_text(encoding="utf-8")) or {}
        entries = raw.get("calls") or {}
        base = Path(map_path).parent
        self._exact: dict[str, Scenario] = {}
        self._prefixes: list[tuple[str, Scenario]] = []
        for key, scenario_path in entries.items():
            scenario = Scenario.load(str(_resolve_scenario_path(base, str(scenario_path))))
            self._exact[key] = scenario
            self._prefixes.append((key, scenario))

    def scenario_for(self, call_id: str) -> tuple[str, Scenario] | None:
        if call_id in self._exact:
            return call_id, self._exact[call_id]
        matches = [(key, s) for key, s in self._prefixes if call_id.startswith(key)]
        if len(matches) > 1:
            raise ValueError(
                f"el prefijo de {call_id} coincide con varias entradas del mapa: "
                f"{[m[0] for m in matches]}"
            )
        return matches[0] if matches else None
