"""The evaluator as a browser can read it.

Everything the evaluator has always produced lives in files: `cases.jsonl`,
`manifest.json`, `report.html`, the evidence WAVs. None of it was reachable from
a screen, which is why the dashboard ended up showing mock data next to real
numbers. This exposes the same files as JSON.

Three rules:

- **Read-only over runs.** Nothing here starts a run, edits a scenario or writes
  inside a results directory. A console that can rewrite its own benchmark is a
  console nobody can trust.
- **Local by default.** Binds to 127.0.0.1 with no auth, like the ops console: a
  tool for the machine it runs on, not a service.
- **No path escapes.** A run id is one directory name under the results root, and
  an evidence file must resolve inside that directory, whatever the request says.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from evaluator.api.chat import ChatSessionManager, create_chat_router
from evaluator.models import CaseResult
from evaluator.report.diff import diff_runs
from evaluator.report.metrics import summarize
from evaluator.report.side_by_side import load_cases, side_by_side


def _run_dir(root: Path, run_id: str) -> Path:
    """Resolve one run directory, refusing anything that is not a plain name."""
    if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
        raise HTTPException(400, "identificador de corrida inválido")
    directory = (root / run_id).resolve()
    if not directory.is_dir() or root.resolve() not in directory.parents:
        raise HTTPException(404, f"corrida desconocida: {run_id}")
    return directory


def _manifest(directory: Path) -> dict[str, Any]:
    path = directory / "manifest.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"note": "manifest.json ilegible"}


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
) -> FastAPI:
    root = Path(results_root)
    web = Path(web_dir) if web_dir else None
    sessions = ChatSessionManager(session_root or root / "_chat-sessions")
    app = FastAPI(title="Prosper evaluator - developer console", docs_url="/api/docs")
    app.include_router(create_chat_router(sessions))

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "results_root": str(root), "runs": len(_list_runs(root))}

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
            "metrics": summarize(cases),
            "side_by_side": side_by_side(directory).summary(),
        }

    @app.get("/api/runs/{run_id}/cases")
    def run_cases(run_id: str) -> list[dict[str, Any]]:
        directory = _run_dir(root, run_id)
        return [c.model_dump(mode="json") for c in _cases_or_empty(directory)]

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
    def diff(a: str, b: str) -> dict[str, Any]:
        result = diff_runs(_run_dir(root, a), _run_dir(root, b))
        return {"a": a, "b": b, "summary": result.summary()}

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
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

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
