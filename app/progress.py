"""Best-effort, user-safe progress events for LangGraph tool execution."""

from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer


def emit_progress(stage: str, state: str, message: str, **details: Any) -> None:
    """Emit a factual progress event when called inside a streamed graph run."""
    try:
        writer = get_stream_writer()
    except (RuntimeError, KeyError):  # Direct calls lack the LangGraph runtime context.
        return
    writer({
        "type": "progress",
        "stage": stage,
        "state": state,
        "message": message,
        **details,
    })
