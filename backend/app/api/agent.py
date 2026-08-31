"""HTTP surface for the LangGraph agent pipeline (Phases 7-8).

POST /run streams genuine live step progress via Server-Sent Events,
using LangGraph's own `stream_mode="updates"` — each event is one
completed node's real output, not a simulated/fake progress indicator.
GET /events and /sessions expose the `agent_events` audit trail for the
Agent Trace view.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func

from app.agents.graph import stream_agent_session
from app.forecasting.enums import ForecastHorizon
from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal

router = APIRouter()


class AgentRunRequest(BaseModel):
    user_query: str
    provider: str
    resource_id: str
    usage_type: str
    horizon: ForecastHorizon
    max_latency_ms: float
    min_availability: float
    budget: float


@router.post("/run")
def run_agent_endpoint(request: AgentRunRequest) -> StreamingResponse:
    def event_stream():
        db = SessionLocal()
        try:
            for chunk in stream_agent_session(
                db,
                user_query=request.user_query,
                provider=request.provider,
                resource_id=request.resource_id,
                usage_type=request.usage_type,
                horizon=request.horizon,
                max_latency_ms=request.max_latency_ms,
                min_availability=request.min_availability,
                budget=request.budget,
            ):
                yield f"data: {json.dumps(chunk, default=str)}\n\n"
        except Exception as exc:  # surface a clean error event instead of a broken stream
            yield f"data: {json.dumps({'_meta': {'event': 'error', 'error': str(exc)}})}\n\n"
        finally:
            db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class AgentEventOut(BaseModel):
    id: int
    session_id: str
    agent_name: str
    event_type: str
    tool_name: str | None
    input: dict | None
    output: dict | None
    latency_ms: int | None
    created_at: datetime


class AgentEventsResponse(BaseModel):
    events: list[AgentEventOut]


@router.get("/events", response_model=AgentEventsResponse)
def list_agent_events_endpoint(session_id: str) -> AgentEventsResponse:
    db = SessionLocal()
    try:
        rows = (
            db.query(AgentEvent)
            .filter(AgentEvent.session_id == session_id)
            .order_by(AgentEvent.id.asc())
            .all()
        )
        return AgentEventsResponse(
            events=[
                AgentEventOut(
                    id=r.id,
                    session_id=r.session_id,
                    agent_name=r.agent_name,
                    event_type=r.event_type,
                    tool_name=r.tool_name,
                    input=r.input,
                    output=r.output,
                    latency_ms=r.latency_ms,
                    created_at=r.created_at,
                )
                for r in rows
            ]
        )
    finally:
        db.close()


class AgentSessionSummary(BaseModel):
    session_id: str
    event_count: int
    started_at: datetime
    ended_at: datetime


class AgentSessionsResponse(BaseModel):
    sessions: list[AgentSessionSummary]


@router.get("/sessions", response_model=AgentSessionsResponse)
def list_agent_sessions_endpoint(limit: int = Query(default=20, le=100)) -> AgentSessionsResponse:
    db = SessionLocal()
    try:
        rows = (
            db.query(
                AgentEvent.session_id,
                func.count(AgentEvent.id),
                func.min(AgentEvent.created_at),
                func.max(AgentEvent.created_at),
            )
            .group_by(AgentEvent.session_id)
            .order_by(func.max(AgentEvent.created_at).desc())
            .limit(limit)
            .all()
        )
        return AgentSessionsResponse(
            sessions=[
                AgentSessionSummary(session_id=row[0], event_count=row[1], started_at=row[2], ended_at=row[3])
                for row in rows
            ]
        )
    finally:
        db.close()
