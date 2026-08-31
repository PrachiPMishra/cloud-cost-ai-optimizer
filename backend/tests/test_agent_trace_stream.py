import json
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.agent_trace import _agent_trace_event_stream
from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _insert_event(db, session_id: str, tool_name: str) -> AgentEvent:
    event = AgentEvent(
        session_id=session_id,
        agent_name="test_agent",
        event_type="tool_call",
        tool_name=tool_name,
        input={"x": 1},
        output={"status": "success", "result": {}},
        latency_ms=5,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _cleanup(db, session_id: str) -> None:
    db.execute(delete(AgentEvent).where(AgentEvent.session_id == session_id))
    db.commit()


def test_stream_drains_pre_existing_events_then_idles_out(db) -> None:
    session_id = f"test-trace-{uuid.uuid4()}"
    _insert_event(db, session_id, "tool_one")
    _insert_event(db, session_id, "tool_two")

    try:
        gen = _agent_trace_event_stream(session_id, poll_interval_seconds=0.02, max_idle_polls=5)
        chunks = [json.loads(line[len("data: "):]) for line in gen]

        meta_events = [c["_meta"]["event"] for c in chunks if "_meta" in c]
        tool_events = [c["event"]["tool_name"] for c in chunks if "event" in c]

        assert meta_events == ["connected", "idle_timeout"]
        assert tool_events == ["tool_one", "tool_two"]
    finally:
        _cleanup(db, session_id)


def test_stream_yields_events_inserted_after_connecting(db) -> None:
    session_id = f"test-trace-{uuid.uuid4()}"

    try:
        gen = _agent_trace_event_stream(session_id, poll_interval_seconds=0.02, max_idle_polls=100)

        # consume the initial "connected" meta event
        first = json.loads(next(gen)[len("data: "):])
        assert first["_meta"]["event"] == "connected"

        def _insert_later():
            time.sleep(0.15)
            writer_db = SessionLocal()
            try:
                _insert_event(writer_db, session_id, "late_tool")
            finally:
                writer_db.close()

        thread = threading.Thread(target=_insert_later)
        thread.start()

        received = None
        for _ in range(50):  # generous bound; each next() may block up to poll_interval
            chunk = json.loads(next(gen)[len("data: "):])
            if "event" in chunk:
                received = chunk["event"]
                break

        thread.join()
        assert received is not None
        assert received["tool_name"] == "late_tool"
        assert received["session_id"] == session_id
    finally:
        _cleanup(db, session_id)


def test_stream_with_no_events_ever_times_out_cleanly(db) -> None:
    session_id = f"test-trace-empty-{uuid.uuid4()}"
    gen = _agent_trace_event_stream(session_id, poll_interval_seconds=0.01, max_idle_polls=3)
    chunks = [json.loads(line[len("data: "):]) for line in gen]

    events = [c["_meta"]["event"] for c in chunks]
    assert events == ["connected", "idle_timeout"]


def test_http_endpoint_streams_pre_existing_events(client: TestClient, db) -> None:
    session_id = f"test-trace-http-{uuid.uuid4()}"
    _insert_event(db, session_id, "http_tool")

    try:
        with client.stream("GET", f"/api/agent-trace/{session_id}") as response:
            assert response.status_code == 200
            collected = []
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = json.loads(line[len("data: "):])
                collected.append(chunk)
                if "event" in chunk:
                    break  # got what we needed; close early rather than waiting for idle timeout

        assert any("event" in c and c["event"]["tool_name"] == "http_tool" for c in collected)
    finally:
        _cleanup(db, session_id)
