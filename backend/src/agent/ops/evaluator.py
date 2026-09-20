"""Authenticated, read-only export of completed call traces for the evaluator.

The evaluator runs outside the Fly volume, so it cannot inspect ``DATA_DIR``
directly.  This route exposes the original audit records server-to-server,
behind the existing ops access gate.  In-progress traces are deliberately
omitted: a call becomes benchmark evidence only after it records its end.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from agent.config import settings
from agent.ops.auth import request_org_id
from agent.ops.live import require_access

router = APIRouter(prefix="/ops/api/evaluator", dependencies=[Depends(require_access)])


def _records(path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return records
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


@router.get("/calls")
def completed_calls(
    request: Request,
    org: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    """Return completed raw audit traces, newest first and paginated."""
    org_id = request_org_id(request, org)
    completed: list[tuple[float, str, list[dict[str, Any]]]] = []
    for path in settings().call_trace_paths(org_id):
        records = _records(path)
        if not any(record.get("event") == "call_ended" for record in records):
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        completed.append((modified, path.stem, records))
    completed.sort(key=lambda item: (item[0], item[1]), reverse=True)
    start = (page - 1) * page_size
    selected = completed[start : start + page_size]
    return {
        "items": [{"call_id": call_id, "records": records} for _, call_id, records in selected],
        "page": page,
        "page_size": page_size,
        "total": len(completed),
        "next_page": page + 1 if start + page_size < len(completed) else None,
    }
