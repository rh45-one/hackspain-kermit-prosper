"""The evaluator as a browser can read it.

Everything the evaluator has always produced lives in files: `cases.jsonl`,
`manifest.json`, `report.html`, the evidence WAVs. None of it was reachable from
a screen, which is why the dashboard ended up showing mock data next to real
numbers. This exposes the same files as JSON.

Four rules:

- **Read-only over runs.** Nothing here starts a run, edits a scenario or writes
  inside a results directory. A console that can rewrite its own benchmark is a
  console nobody can trust.
- **Local by default.** Binds to 127.0.0.1 with no auth, like the ops console: a
  tool for the machine it runs on, not a service.
- **No path escapes.** A run id is one directory name under the results root, and
  an evidence file must resolve inside that directory, whatever the request says.
- **No credential values.** Every response goes through `api/redact.py`: the run
  manifest carries the environment the runner started the agent with, and a
  provider key in that map must never reach a browser or an error string.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from evaluator.api.chat import ChatSessionManager, create_chat_router
from evaluator.api.redact import redact_secrets, redact_text
from evaluator.models import CaseResult
from evaluator.profiles import ProfileCatalog
from evaluator.report.diff import diff_runs
from evaluator.report.metrics import summarize
from evaluator.report.side_by_side import load_cases, side_by_side

# Free-text diagnostics of a case: the two places a rig could paste a value into.
_CASE_TEXT_FIELDS = ("errors", "notes")


def _run_dir(root: Path, run_id: str) -> Path:
    """Resolve one run directory, refusing anything that is not a plain name."""
    if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
        raise HTTPException(400, "identificador de corrida inválido")
    directory = (root / run_id).resolve()
    if not directory.is_dir() or root.resolve() not in directory.parents:
        raise HTTPException(404, f"corrida desconocida: {run_id}")
    return directory


def _manifest(directory: Path) -> dict[str, Any]:
    """The run manifest as a response may show it: every env value redacted.

    The file on disk keeps what the runner wrote. This is the only copy a
    client sees, and `candidates[].env` carries the environment the agent was
    started with, so nothing in it survives unmasked.
    """
    path = directory / "manifest.json"
    if not path.is_file():
        return {}
    try:
        return redact_secrets(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {"note": "manifest.json ilegible"}


def _candidate_versions(manifest: dict[str, Any]) -> dict[str, str]:
    """name -> declared version, to link a case back to what produced it."""
    versions: dict[str, str] = {}
    for candidate in manifest.get("candidates", []) or []:
        name, version = candidate.get("name"), candidate.get("version")
        if name and version and version != "unknown":
            versions[name] = str(version)
    return versions


def _case_payload(case: CaseResult, run_id: str, versions: dict[str, str]) -> dict[str, Any]:
    """One case as a response, with its run link filled in.

    `run_id` and `candidate_version` are read from the run on disk, so an
    artifact written before those fields existed still answers "which run and
    which version produced this?" without rewriting anybody's history.
    """
    payload = redact_secrets(case.model_dump(mode="json"))
    payload["run_id"] = payload.get("run_id") or run_id
    if not payload.get("candidate_version"):
        payload["candidate_version"] = versions.get(case.candidate)
    return _redact_diagnostics(payload)


def _redact_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    """Scrub credential shapes out of the rig-authored free text of a case.

    `errors` and `notes` are what the bench wrote about a case; a config value
    can end up quoted there. Transcripts and submitted payloads are evidence and
    are served as recorded - a leak of protected data is a finding the report has
    to show, not something to mask.
    """
    for field in _CASE_TEXT_FIELDS:
        values = payload.get(field)
        if isinstance(values, list):
            payload[field] = [redact_text(v) if isinstance(v, str) else v for v in values]
    return payload


def _redact_texts(value: Any) -> Any:
    """Apply `redact_text` to every string of a metrics-shaped structure."""
    if isinstance(value, dict):
        return {name: _redact_texts(item) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact_texts(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _case(cases: list[CaseResult], case_id: str) -> CaseResult:
    for candidate in cases:
        if candidate.case_id == case_id:
            return candidate
    raise HTTPException(404, f"caso desconocido: {case_id}")


def _run_row(directory: Path) -> dict[str, Any]:
    manifest = _manifest(directory)
    try:
        cases = load_cases(directory)
    except FileNotFoundError:
        cases = []
    return {
        "run_id": directory.name,
        "experiment": manifest.get("experiment", "—"),
        "started_at": manifest.get("started_at", "—"),
        "candidates": [c.get("name", "?") for c in manifest.get("candidates", [])]
        or sorted({c.candidate for c in cases}),
        "repetitions": manifest.get("repetitions"),
        "cases": len(cases),
        "passed": sum(1 for c in cases if c.verdict == "pass"),
        "failed": sum(1 for c in cases if c.verdict == "fail"),
        "invalid": sum(1 for c in cases if c.verdict == "invalid_evaluation"),
        "has_report": (directory / "report.html").is_file(),
    }


def create_app(
    results_root: Path | str,
    web_dir: Path | str | None = None,
    session_root: Path | str | None = None,
    profiles: ProfileCatalog | None = None,
) -> FastAPI:
    root = Path(results_root)
    web = Path(web_dir) if web_dir else None
    catalog = profiles or ProfileCatalog.builtin()
    sessions = ChatSessionManager(session_root or root / "_chat-sessions", catalog)
    app = FastAPI(title="Pronto evaluator - developer console", docs_url="/api/docs")
    app.include_router(create_chat_router(sessions))

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "results_root": str(root),
            "runs": len(_list_runs(root)),
            "profiles": catalog.ids(),
        }

    @app.get("/api/profiles")
    def profiles_list() -> list[dict[str, Any]]:
        """The profile catalog the server owns: ids, capabilities, guard verdict.

        A browser picks from this list; it never supplies a URL, a path or a
        command of its own.
        """
        return catalog.public_view()

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [_run_row(d) for d in _list_runs(root)]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        directory = _run_dir(root, run_id)
        cases = _cases_or_empty(directory)
        return {
            "run_id": run_id,
            "manifest": _manifest(directory),
            # The aggregates quote case diagnostics (`errors`), so they go
            # through the same text scrub as the case payloads.
            "metrics": _redact_texts(summarize(cases)),
            "side_by_side": side_by_side(directory).summary(),
        }

    @app.get("/api/runs/{run_id}/cases")
    def run_cases(run_id: str) -> list[dict[str, Any]]:
        directory = _run_dir(root, run_id)
        versions = _candidate_versions(_manifest(directory))
        return [
            _case_payload(case, run_id, versions) for case in _cases_or_empty(directory)
        ]

    @app.get("/api/runs/{run_id}/real-calls")
    def run_real_calls(run_id: str) -> list[dict[str, Any]]:
        """Observer runs only: every real backend call the run observed."""
        directory = _run_dir(root, run_id)
        path = directory / "real_calls.jsonl"
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    @app.get("/api/runs/{run_id}/compare")
    def run_compare(run_id: str) -> dict[str, Any]:
        directory = _run_dir(root, run_id)
        table = side_by_side(directory)
        return {
            "summary": table.summary(),
            "rows": [
                {
                    "scenario_id": row.scenario_id,
                    "problem_id": row.problem_id,
                    "repetition": row.repetition,
                    "disagrees": row.disagrees,
                    "cells": {name: row.cell_text(name) for name in table.candidates},
                }
                for row in table.rows
            ],
        }

    @app.get("/api/diff")
    def diff(a: str, b: str, candidate_a: str | None = None, candidate_b: str | None = None) -> dict[str, Any]:
        """Two runs, optionally pairing one candidate from each."""
        try:
            result = diff_runs(
                _run_dir(root, a), _run_dir(root, b), candidate_a=candidate_a, candidate_b=candidate_b
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"a": a, "b": b, "summary": result.summary(), "metrics": result.metrics}

    @app.get("/api/runs/{run_id}/report")
    def report(run_id: str) -> FileResponse:
        directory = _run_dir(root, run_id)
        path = directory / "report.html"
        if not path.is_file():
            raise HTTPException(404, f"la corrida {run_id} no tiene report.html")
        return FileResponse(path, media_type="text/html")

    @app.get("/api/runs/{run_id}/evidence/{stream}")
    def evidence(run_id: str, stream: str, case_id: str) -> FileResponse:
        # `case_id` is `candidate/scenario/rN`, so it travels as a query
        # parameter: a path segment cannot carry its slashes.
        directory = _run_dir(root, run_id)
        case = _case(_cases_or_empty(directory), case_id)
        path_value = case.audio.get(stream)
        if not path_value:
            raise HTTPException(404, f"el caso {case_id} no tiene audio de {stream}")
        path = Path(path_value).resolve()
        if not path.is_file() or directory.resolve() not in path.parents:
            raise HTTPException(404, "evidencia de audio no disponible")
        return FileResponse(path, media_type="audio/wav")

    @app.exception_handler(HTTPException)
    async def _error(_request: Any, exc: HTTPException) -> JSONResponse:
        # Public errors name the field at fault; they never repeat a value or a
        # credential shape that an internal exception may have carried along.
        return JSONResponse(
            {"detail": redact_text(str(exc.detail))}, status_code=exc.status_code
        )

    if web is not None and web.is_dir():
        _mount_console(app, web)

    return app


def _list_runs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (d for d in root.iterdir() if d.is_dir() and (d / "cases.jsonl").is_file()),
        key=lambda d: d.name,
        reverse=True,
    )


def _cases_or_empty(directory: Path) -> list[CaseResult]:
    try:
        return load_cases(directory)
    except FileNotFoundError:
        raise HTTPException(404, f"{directory.name} no tiene cases.jsonl") from None


def _mount_console(app: FastAPI, web: Path) -> None:
    """Serve the developer console itself, at the root."""
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=web), name="console-static")

    @app.get("/", response_class=HTMLResponse)
    def console() -> HTMLResponse:
        return HTMLResponse((web / "index.html").read_text(encoding="utf-8"))
