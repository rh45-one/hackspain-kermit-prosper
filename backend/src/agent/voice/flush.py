"""Submission flush: POST every accepted action inside the 30-second window.

Runs when the harness closes the socket. Uses the scheduling submitter when
worker B's module is present; otherwise logs loudly so nothing is silently
lost. 409 counts as accepted (idempotent retry per the call contract).
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger

from agent.voice.context import CallContext

ROUTES = {
    "register": "register",
    "book": "book",
    "reschedule": "reschedule",
    "cancel": "cancel",
    "no-action": "no-action",
    "escalate": "escalate",
}


async def flush_call(ctx: CallContext, settings: Any) -> None:
    """Submit queued actions for a finished call. Flushes exactly once."""
    if ctx.submitted:
        return
    ctx.submitted = True
    deadline = time.monotonic() + settings.submit_window_seconds
    actions_before_flush = len(ctx.queued_actions)
    fallback_action_added = actions_before_flush == 0
    if actions_before_flush:
        ctx.mark_pipeline_stage("action_queued")
    if fallback_action_added:
        # Silence is always wrong: force a record if the brain queued nothing.
        logger.error("call {} ended with NO queued actions - submitting no-action out_of_scope", ctx.call_id)
        ctx.queued_actions.append({"route": "no-action", "reason": "out_of_scope"})

    submitter: Submitter | None = None
    submissions_succeeded = 0
    submissions_failed = 0
    try:
        from agent.scheduling.submit import Submitter

        if settings.prosper_api_key:
            submitter = Submitter(settings.prosper_api_base_url, settings.prosper_api_key)
            ctx.mark_pipeline_stage("submission_attempted")
        else:
            logger.error("PROSPER_API_KEY not set; actions NOT submitted (offline mode)")
    except (ImportError, AttributeError) as exc:
        logger.error("scheduling submitter unavailable ({}); actions NOT submitted", exc)

    ctx.audit("flush_start", {"actions": len(ctx.queued_actions)})
    try:
        for action in ctx.queued_actions:
            route = ROUTES.get(action.get("route", ""))
            if route is None:
                logger.error("call {}: unknown action route {}", ctx.call_id, action)
                continue
            body = {k: v for k, v in action.items() if k != "route"}
            if submitter is None:
                # Submission bodies may contain identity and contact data.
                # Log only the route and field names, never caller values.
                logger.error(
                    "WOULD SUBMIT call={} route={} fields={}",
                    ctx.call_id,
                    route,
                    sorted(body),
                )
                continue
            try:
                # post_route retries transport errors internally and treats
                # 409 as accepted; the deadline keeps slow providers inside
                # the 30-second submission window.
                await submitter.post_route(action, ctx.call_id, deadline=deadline)
                ctx.audit("submitted", {"route": route})
                submissions_succeeded += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("call {}: submit {} failed: {}", ctx.call_id, route, exc)
                ctx.audit("submit_failed", {"route": route, "error": str(exc)})
                submissions_failed += 1
            if time.monotonic() > deadline:
                logger.error("call {}: submission window exhausted", ctx.call_id)
                break
    finally:
        if submitter is not None:
            await submitter.close()
    ctx.audit("flush_done", {})
    ctx.emit_outcome_summary(
        actions_before_flush=actions_before_flush,
        fallback_action_added=fallback_action_added,
        submissions_succeeded=submissions_succeeded,
        submissions_failed=submissions_failed,
        submission_configured=submitter is not None,
    )
