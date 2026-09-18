"""Structured logging with per-call context."""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        call_id = getattr(record, "call_id", None)
        if call_id:
            payload["call_id"] = call_id
        extra = getattr(record, "extra_data", None)
        if extra:
            payload["data"] = extra
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # httpx/httpcore INFO records include full request URLs. Directory lookups
    # carry phone numbers, national IDs, names, and dates of birth as query
    # parameters, so provider request logging must be suppressed by default.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str, call_id: str | None = None) -> logging.LoggerAdapter:
    return logging.LoggerAdapter(logging.getLogger(name), {"call_id": call_id})
