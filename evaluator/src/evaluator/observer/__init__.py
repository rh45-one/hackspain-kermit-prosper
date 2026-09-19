"""Observer: score the backend's real calls without touching the backend.

Public API: `observe` (build a run from the backend audit) and the
`BackendCall`/`OracleMap` primitives behind it.
"""
from evaluator.observer.backend_calls import (
    BackendCall,
    OracleMap,
    load_backend_call,
    load_backend_calls,
)
from evaluator.observer.run import observe, score_call

__all__ = [
    "BackendCall",
    "OracleMap",
    "load_backend_call",
    "load_backend_calls",
    "observe",
    "score_call",
]
