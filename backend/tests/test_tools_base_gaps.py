import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import delete

from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal
from app.tools.base import ToolError, run_tool


class _Input(BaseModel):
    value: int


class _Output(BaseModel):
    doubled: int


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_run_tool_wraps_unexpected_exception_as_tool_error_and_logs_it(db) -> None:
    session_id = str(uuid.uuid4())
    input_model = _Input(value=5)

    def _boom() -> _Output:
        raise ValueError("something unrelated broke")

    with pytest.raises(ToolError) as exc_info:
        run_tool(
            db,
            agent_name="test_agent",
            session_id=session_id,
            tool_name="test_tool",
            input_model=input_model,
            fn=_boom,
        )

    assert "ValueError" in str(exc_info.value)
    assert "something unrelated broke" in str(exc_info.value)

    event = (
        db.query(AgentEvent)
        .filter(AgentEvent.session_id == session_id, AgentEvent.tool_name == "test_tool")
        .one()
    )
    assert event.output["status"] == "error"
    assert "ValueError" in event.output["error"]
    assert event.input == {"value": 5}

    db.execute(delete(AgentEvent).where(AgentEvent.session_id == session_id))
    db.commit()
