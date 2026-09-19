"""Persistent, rebuildable index over evaluator artifacts.

The index is a cache, never a second source of truth: deleting it and importing
again only reads ``cases.jsonl`` and ``real_calls.jsonl``.  This makes repeated
imports idempotent and keeps old runs readable without a migration.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evaluator.models import CaseResult
from evaluator.report.side_by_side import load_cases


def _availability(value: Any, *, unknown: bool = False) -> str:
    if unknown:
        return "unknown"
    return "present" if value else "absent"


def _record_id(origin: str, run_id: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{origin}\0{run_id}\0{source_id}".encode()).hexdigest()[:20]
    return f"{origin}-{digest}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


class HistoryStore:
    """Calls index stored below the results root and safe to recreate."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.path = self.root / "_history" / "calls-v1.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        calls = raw.get("calls", {}) if isinstance(raw, dict) else {}
        return calls if isinstance(calls, dict) else {}

    def _save(self, calls: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema_version": 1, "calls": calls}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def import_runs(self) -> dict[str, int]:
        calls = self._load()
        before = dict(calls)
        seen: set[str] = set()
        for directory in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            if not directory.is_dir() or not (directory / "cases.jsonl").is_file():
                continue
            manifest = _manifest(directory)
            versions = {
                str(item.get("name")): str(item.get("version"))
                for item in manifest.get("candidates", [])
                if isinstance(item, dict) and item.get("name") and item.get("version")
            }
            kinds = {
                str(item.get("name")): str(item.get("kind", "external"))
                for item in manifest.get("candidates", []) if isinstance(item, dict)
            }
            for case in _cases(directory):
                row = self._case_row(case, directory.name, versions, kinds, manifest)
                calls[row["id"]] = row
                seen.add(row["id"])
        for path in sorted((self.root / "_manual-calls").glob("*.json")) if (self.root / "_manual-calls").is_dir() else []:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict) or not raw.get("call_id"):
                continue
            row = self._manual_row(raw)
            calls[row["id"]] = row
            seen.add(row["id"])
            for raw in _read_jsonl(directory / "real_calls.jsonl"):
                row = self._real_row(raw, directory.name, manifest)
                calls[row["id"]] = row
                seen.add(row["id"])
        # Remove stale entries only when their source is an evaluator run that
        # has disappeared. This prevents an interrupted write from multiplying
        # a call, while preserving a current partial run on the next import.
        calls = {
            key: value for key, value in calls.items()
            if value.get("origin") == "manual" or value.get("run_id") in self._run_ids()
        }
        created = sum(1 for key in calls if key not in before)
        updated = sum(1 for key in calls if key in before and calls[key] != before[key])
        skipped = sum(1 for key in seen if key in before and calls.get(key) == before[key])
        self._save(calls)
        return {"indexed": len(calls), "created": created, "updated": updated, "skipped": skipped}

    def _run_ids(self) -> set[str]:
        if not self.root.is_dir():
            return set()
        return {p.name for p in self.root.iterdir() if p.is_dir() and (p / "cases.jsonl").is_file()}

    def _case_row(self, case: CaseResult, run_id: str, versions: dict[str, str], kinds: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
        rid = _record_id(case.origin, run_id, case.case_id)
        events = [event.model_dump(mode="json") for event in case.ordered_transcript]
        return {
            "id": rid, "call_id": case.call_id, "origin": case.origin,
            "run_id": run_id, "case_id": case.case_id, "candidate": case.candidate,
            "candidate_version": case.candidate_version or versions.get(case.candidate),
            "candidate_kind": kinds.get(case.candidate, "external"),
            "scenario_id": case.scenario_id, "problem_id": case.problem_id,
            "verdict": case.verdict, "evaluated": case.verdict != "invalid_evaluation",
            "started_at": case.started_at or manifest.get("started_at"), "ended_at": case.ended_at,
            "duration_s": case.duration_s, "cost": case.cost,
            "evidence": case.evidence.as_dict(), "transcript_events": events,
            "transcript_fragments": case.transcript if not events else [],
            "actions": case.submitted, "submit_attempts": case.submit_attempts,
            "audio": case.audio, "errors": case.errors, "notes": case.notes,
        }

    def _real_row(self, raw: dict[str, Any], run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        call_id = str(raw.get("call_id") or "unknown")
        transcript = raw.get("transcript") if isinstance(raw.get("transcript"), dict) else {}
        fragments = [
            {"role": role, "text": text, "fragment": True, "source": "observer"}
            for role, text in (("caller", transcript.get("caller")), ("agent", transcript.get("assistant")))
            if isinstance(text, str) and text.strip()
        ]
        verdict = raw.get("verdict") if raw.get("verdict") in {"pass", "fail", "invalid_evaluation"} else "unknown"
        return {
            "id": _record_id("real", run_id, call_id), "call_id": call_id, "origin": "real",
            "run_id": run_id, "case_id": None, "candidate": raw.get("engine") or "backend-real",
            "candidate_version": None, "candidate_kind": "external",
            "scenario_id": raw.get("tagged_scenario"), "problem_id": None, "verdict": verdict,
            "evaluated": verdict in {"pass", "fail"}, "started_at": raw.get("started_at") or manifest.get("started_at"),
            "ended_at": raw.get("last_event_at"), "duration_s": raw.get("elapsed_s"), "cost": None,
            "evidence": {"audio": "absent", "transcript": _availability(fragments), "cost": "unknown", "outcome": _availability(raw.get("tagged_scenario"))},
            "transcript_events": fragments, "transcript_fragments": [], "actions": raw.get("actions") or [],
            "submit_attempts": raw.get("submissions") or [], "audio": {}, "errors": raw.get("problems") or [], "notes": [],
        }

    def _manual_row(self, raw: dict[str, Any]) -> dict[str, Any]:
        call_id = str(raw["call_id"])
        scenario = raw.get("scenario") if isinstance(raw.get("scenario"), dict) else {}
        verdict = "unknown"
        if scenario:
            verdict = "pass" if scenario.get("passed") else "fail"
        return {
            "id": _record_id("manual", "manual", call_id), "call_id": call_id, "origin": "manual",
            "run_id": None, "case_id": None, "candidate": raw.get("profile_id") or "manual-agent",
            "candidate_version": None, "candidate_kind": "external", "scenario_id": scenario.get("id"),
            "problem_id": None, "verdict": verdict, "evaluated": bool(scenario),
            "started_at": raw.get("started_at"), "ended_at": raw.get("ended_at"), "duration_s": None,
            "cost": None, "evidence": raw.get("evidence") or {"audio": "unknown", "transcript": "unknown", "cost": "unknown", "outcome": "unknown"},
            "transcript_events": raw.get("turns") or [], "transcript_fragments": [],
            "actions": raw.get("submissions") or [], "submit_attempts": raw.get("rejected") or [],
            "audio": {}, "errors": [raw["transport_error"]] if raw.get("transport_error") else [], "notes": [],
        }

    def calls(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        rows = list(self._load().values())
        rows = [row for row in rows if _matches(row, filters)]
        return sorted(rows, key=lambda row: (row.get("started_at") or "", row["id"]), reverse=True)

    def call(self, record_id: str) -> dict[str, Any] | None:
        return self._load().get(record_id)


def _manifest(directory: Path) -> dict[str, Any]:
    try:
        value = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _cases(directory: Path) -> list[CaseResult]:
    try:
        return load_cases(directory)
    except (FileNotFoundError, ValueError):
        return []


def _matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    if not filters.get("include_doubles", False) and row.get("candidate_kind") == "double":
        return False
    for field in ("origin", "candidate", "candidate_version", "verdict", "scenario_id"):
        value = filters.get(field)
        if value is not None and value != "" and row.get(field) != value:
            return False
    started = row.get("started_at") or ""
    if filters.get("from") and started < filters["from"]:
        return False
    return not (filters.get("to") and started > filters["to"])


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [row for row in rows if row.get("evaluated")]
    passed = sum(1 for row in evaluated if row.get("verdict") == "pass")
    def coverage(name: str) -> dict[str, int]:
        return {"present": sum(1 for row in rows if row.get("evidence", {}).get(name) == "present"), "total": len(rows)}
    return {
        "population": len(rows), "evaluated": len(evaluated), "passed": passed,
        "pass_rate": None if not evaluated else passed / len(evaluated),
        "coverage": {name: coverage(name) for name in ("audio", "transcript", "cost", "outcome")},
        "origins": {origin: sum(1 for row in rows if row.get("origin") == origin) for origin in ("real", "simulated", "manual")},
    }
