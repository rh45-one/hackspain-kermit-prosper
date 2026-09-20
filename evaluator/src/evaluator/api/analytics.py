"""Descriptive statistics over observed calls; missing evidence is never a zero."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any


def number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) and value >= 0 else None
    return None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 1)


def seconds(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def call_metrics(row: dict[str, Any]) -> dict[str, Any]:
    # Transcript timestamps measure receipt of text, NOT audible response latency.
    gaps = []
    pending = None
    for event in row.get("transcript_events", []):
        ts = seconds(event.get("timestamp"))
        if ts is None:
            continue
        if event.get("role") == "caller":
            pending = ts
        elif event.get("role") in {"agent", "assistant"} and pending is not None:
            if ts >= pending:
                gaps.append(round((ts - pending) * 1000, 1))
            pending = None
    timeline = row.get("timeline", [])
    latencies = [v for x in row.get("turn_latencies_ms", []) if (v := number(x)) is not None]
    for event in timeline:
        if event.get("event") == "response_latency":
            value = number(event.get("data", {}).get("latency_ms"))
            if value is not None:
                latencies.append(value)
    interrupts = [e for e in timeline if e.get("event") == "barge_in_reset"]
    # Recovery requires explicit audio evidence. A text fragment is not proof of speech.
    # Correlate terminal outcomes by interruption id; legacy resets have no verdict.
    interruption_ids = {e.get("data", {}).get("interruption_id") for e in interrupts}
    interruption_ids.discard(None)
    recovered_ids = {e.get("data", {}).get("interruption_id") for e in timeline
                     if e.get("event") == "interruption_recovered"} & interruption_ids
    failed_ids = {e.get("data", {}).get("interruption_id") for e in timeline
                  if e.get("event") == "interruption_unrecovered"} & interruption_ids
    observed = recovered_ids | failed_ids
    first_audio = number(row.get("first_audio_ms"))
    stages = {e.get("data", {}).get("stage"): seconds(e.get("timestamp"))
              for e in timeline if e.get("event") == "pipeline_stage"}
    connected, emitted = stages.get("client_connected"), stages.get("assistant_audio_emitted")
    if first_audio is None and connected is not None and emitted is not None and emitted >= connected:
        first_audio = round((emitted - connected) * 1000, 1)
    return {
        "response_ms": latencies, "transcript_gap_ms": gaps,
        "first_audio_ms": first_audio,
        "interruptions": len(interruption_ids) + sum(not e.get("data", {}).get("interruption_id") for e in interrupts),
        "recovered": len(recovered_ids) if observed else None,
        "recovery_observed": len(observed),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [call_metrics(row) for row in rows]
    response = [v for m in metrics for v in m["response_ms"]]
    gaps = [v for m in metrics for v in m["transcript_gap_ms"]]
    first = [m["first_audio_ms"] for m in metrics if m["first_audio_ms"] is not None]
    judgments = [r["judgment"] for r in rows if r.get("judgment")]
    evaluated = [j for j in judgments if j.get("outcome") in {"pass", "fail"}]
    quality = [float(j["quality"]) for j in judgments if j.get("quality") is not None]
    recovered = [m for m in metrics if m["recovered"] is not None]
    duration = [v for r in rows if (v := number(r.get("duration_s"))) is not None]
    return {
        "calls": len(rows), "completed": sum(bool(r.get("ended")) for r in rows),
        "judged": len(judgments), "evaluated": len(evaluated),
        "passed": sum(j["outcome"] == "pass" for j in evaluated),
        "pass_rate": sum(j["outcome"] == "pass" for j in evaluated) / len(evaluated) if evaluated else None,
        "quality": round(sum(quality) / len(quality), 2) if quality else None,
        "quality_n": len(quality),
        "response_p50_ms": percentile(response, .5), "response_p95_ms": percentile(response, .95),
        "response_n": len(response), "response_calls": sum(bool(m["response_ms"]) for m in metrics),
        "transcript_gap_p50_ms": percentile(gaps, .5), "transcript_gap_n": len(gaps),
        "first_audio_p50_ms": percentile(first, .5), "first_audio_n": len(first),
        "duration_p50_s": percentile(duration, .5), "duration_n": len(duration),
        "interruptions": sum(m["interruptions"] for m in metrics),
        "recovered": sum(m["recovered"] for m in recovered) if recovered else None,
        "recovery_observed": sum(m["recovery_observed"] for m in recovered),
        "transcripts": sum(bool(r.get("transcript_events")) for r in rows),
        "response_distribution": [
            {"label": label, "count": sum(lo <= v < hi for v in response)}
            for label, lo, hi in [("< 0,5 s", 0, 500), ("0,5–1 s", 500, 1000),
                                  ("1–2 s", 1000, 2000), ("2–5 s", 2000, 5000),
                                  ("≥ 5 s", 5000, float("inf"))]
        ],
    }


def dashboard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    days: dict[str, list] = defaultdict(list)
    models: dict[tuple[str, str, str], list] = defaultdict(list)
    for row in rows:
        if seconds(row.get("started_at")) is not None:
            days[str(row["started_at"])[:10]].append(row)
        models[(row.get("candidate") or "desconocido", row.get("model") or "",
                row.get("candidate_version") or "")].append(row)
    return {
        "summary": aggregate(rows),
        "daily": [{"date": day, **aggregate(items)} for day, items in sorted(days.items())],
        "models": [{"engine": key[0], "model": key[1] or None, "version": key[2] or None,
                    **aggregate(items)} for key, items in sorted(models.items())],
        "comparison_note": "Muestras de llamadas distintas: comparación descriptiva, no experimento A/B controlado.",
        "undated": sum(seconds(r.get("started_at")) is None for r in rows),
    }
