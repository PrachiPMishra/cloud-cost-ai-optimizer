"""Forecast agent: calls get_usage_history and forecast_usage for the
resource in scope (both logged tool calls), then asks Gemini to narrate
the already-computed result — the prompt hands Gemini the structured
forecast JSON and explicitly forbids it from computing new numbers.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.llm_client import LLMUnavailableError, generate_text
from app.forecasting.enums import ForecastHorizon
from app.tools.base import ToolError
from app.tools.forecasting import ForecastUsageInput, forecast_usage
from app.tools.usage import GetUsageHistoryInput, get_usage_history

AGENT_NAME = "forecast_agent"

NARRATION_SYSTEM_INSTRUCTION = (
    "You are the forecasting explanation module of a cloud cost assistant. "
    "You are given an already-computed usage forecast as structured JSON. "
    "Write a short (3-5 sentence) explanation of the trend for a "
    "non-technical reader. Use ONLY the numbers given in the JSON — do not "
    "calculate, estimate, round differently, or invent any new number."
)


def run_forecast_agent(
    db: Session, *, session_id: str, resource_id: str, usage_type: str, horizon: ForecastHorizon
) -> dict:
    try:
        get_usage_history(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=GetUsageHistoryInput(resource_id=resource_id, usage_type=usage_type),
        )
    except ToolError:
        pass  # history is context only; forecast_usage below is what actually matters

    try:
        forecast = forecast_usage(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=ForecastUsageInput(resource_id=resource_id, usage_type=usage_type, horizon=horizon),
        )
    except ToolError as exc:
        return {"error": str(exc), "narrative": f"Forecasting unavailable: {exc}"}

    forecast_json = forecast.model_dump(mode="json")
    prompt = f"Forecast data (JSON): {forecast_json}"

    try:
        narrative = generate_text(prompt, system_instruction=NARRATION_SYSTEM_INSTRUCTION)
    except LLMUnavailableError:
        first, last = forecast.points[0], forecast.points[-1]
        narrative = (
            f"[template fallback — Gemini unavailable] Forecast for {resource_id}/{usage_type} "
            f"over the next {len(forecast.points)} day(s) using {forecast.chosen_model_name}: "
            f"starts at {first.predicted_usage:.2f} on {first.date} and ends at "
            f"{last.predicted_usage:.2f} on {last.date}."
        )

    return {"forecast": forecast_json, "narrative": narrative}
