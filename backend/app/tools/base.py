"""Shared logging/error-handling wrapper for every tool.

Every tool call — success or failure — writes exactly one row to
`agent_events` with the calling agent, tool name, typed input, typed
output, latency, and status. This is the audit trail behind "agents call
tools for all numbers, never invent numbers": any number an agent's
narrative references should be traceable to a logged tool call here.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.agent_event import AgentEvent

OutputT = TypeVar("OutputT", bound=BaseModel)


class ToolError(Exception):
    """Raised by a tool implementation for an expected, user-facing failure
    (bad input, no data found, upstream validation error, ...). Logged as
    status="error" rather than crashing the caller."""


def run_tool(
    db: Session,
    *,
    agent_name: str,
    session_id: str,
    tool_name: str,
    input_model: BaseModel,
    fn: Callable[[], OutputT],
) -> OutputT:
    started = time.perf_counter()

    try:
        result = fn()
        output_payload = {"status": "success", "result": result.model_dump(mode="json")}
        status = "success"
        error_message = None
    except ToolError as exc:
        result = None
        status = "error"
        error_message = str(exc)
        output_payload = {"status": "error", "error": error_message}
    except Exception as exc:  # unexpected — still logged, never swallowed silently
        result = None
        status = "error"
        error_message = f"{type(exc).__name__}: {exc}"
        output_payload = {"status": "error", "error": error_message}

    latency_ms = int((time.perf_counter() - started) * 1000)

    db.add(
        AgentEvent(
            session_id=session_id,
            agent_name=agent_name,
            event_type="tool_call",
            tool_name=tool_name,
            input=input_model.model_dump(mode="json"),
            output=output_payload,
            latency_ms=latency_ms,
        )
    )
    db.commit()

    if status == "error":
        raise ToolError(error_message)

    return result
