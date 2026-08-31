"""Live agent_events trace stream (Phase 10).

`POST /api/agent/run` (Phase 7-8) streams per-LangGraph-node progress —
coarse, since a single node (e.g. "optimization") can make a dozen-plus
tool calls internally before it completes. This endpoint instead tails
the `agent_events` table itself for one session_id, so a client sees each
individual tool call the instant it's logged — real granularity, sourced
directly from the same rows `app.tools.base.run_tool` commits, not a
re-derived approximation.

Since this process has no message broker, "live" is implemented as short
-interval polling of the row a writer just committed — simple, correct
for a single-process app, and cheap at this event volume. The stream
naturally serves both cases with no separate code path: connecting to an
already-finished session immediately drains its existing rows, then goes
idle and closes; connecting to a session that's still running keeps
yielding new rows as they're committed.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.agent import AgentEventOut
from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal

router = APIRouter()

POLL_INTERVAL_SECONDS = 0.3
MAX_IDLE_POLLS = 100  # ~30s of no new rows before giving up


def _serialize(row: AgentEvent) -> dict:
    return AgentEventOut(
        id=row.id,
        session_id=row.session_id,
        agent_name=row.agent_name,
        event_type=row.event_type,
        tool_name=row.tool_name,
        input=row.input,
        output=row.output,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
    ).model_dump(mode="json")


def _agent_trace_event_stream(
    session_id: str,
    *,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    max_idle_polls: int = MAX_IDLE_POLLS,
):
    db = SessionLocal()
    last_id = 0
    idle_polls = 0
    try:
        yield f"data: {json.dumps({'_meta': {'event': 'connected', 'session_id': session_id}})}\n\n"

        while idle_polls < max_idle_polls:
            rows = (
                db.query(AgentEvent)
                .filter(AgentEvent.session_id == session_id, AgentEvent.id > last_id)
                .order_by(AgentEvent.id.asc())
                .all()
            )
            # Fresh transaction next iteration so newly committed rows from
            # the writer's connection are visible (no long-lived snapshot
            # holding us to a stale view).
            db.commit()

            if rows:
                idle_polls = 0
                for row in rows:
                    last_id = row.id
                    yield f"data: {json.dumps({'event': _serialize(row)})}\n\n"
            else:
                idle_polls += 1
                time.sleep(poll_interval_seconds)

        yield f"data: {json.dumps({'_meta': {'event': 'idle_timeout', 'session_id': session_id}})}\n\n"
    except Exception as exc:  # surface a clean error event instead of a broken stream
        yield f"data: {json.dumps({'_meta': {'event': 'error', 'error': str(exc)}})}\n\n"
    finally:
        db.close()


@router.get("/{session_id}")
def stream_agent_trace_endpoint(session_id: str) -> StreamingResponse:
    return StreamingResponse(_agent_trace_event_stream(session_id), media_type="text/event-stream")
