"""Cost Analysis agent: calls calculate_current_cost, calculate_forecasted_
cost, and identify_cost_drivers (all logged tool calls), then asks Gemini
to narrate the already-computed breakdown.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.llm_client import LLMUnavailableError, generate_text
from app.forecasting.enums import ForecastHorizon
from app.pricing.aggregation import aggregate_total
from app.tools.base import ToolError
from app.tools.cost_analysis import IdentifyCostDriversInput, identify_cost_drivers
from app.tools.pricing import (
    CalculateCurrentCostInput,
    CalculateForecastedCostInput,
    calculate_current_cost,
    calculate_forecasted_cost,
)

AGENT_NAME = "cost_analysis_agent"

NARRATION_SYSTEM_INSTRUCTION = (
    "You are the cost analysis explanation module of a cloud cost assistant. "
    "You are given already-computed current cost, forecasted cost, and cost "
    "driver data as structured JSON. Write a short (4-6 sentence) explanation "
    "of the cost picture for a non-technical reader, highlighting the top "
    "cost drivers if given. Use ONLY the numbers given in the JSON — do not "
    "calculate, estimate, round differently, or invent any new number."
)


def run_cost_analysis_agent(
    db: Session, *, session_id: str, provider: str, resource_id: str, horizon: ForecastHorizon
) -> dict:
    current = None
    forecasted = None
    drivers = None

    try:
        current = calculate_current_cost(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=CalculateCurrentCostInput(provider=provider, resource_id=resource_id),
        )
    except ToolError:
        pass

    try:
        forecasted = calculate_forecasted_cost(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=CalculateForecastedCostInput(provider=provider, resource_id=resource_id, horizon=horizon),
        )
    except ToolError:
        pass

    try:
        drivers = identify_cost_drivers(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=IdentifyCostDriversInput(provider=provider, resource_id=resource_id, source="current"),
        )
    except ToolError:
        pass

    data = {
        "current_cost": current.model_dump(mode="json") if current else None,
        "forecasted_cost": forecasted.model_dump(mode="json") if forecasted else None,
        "cost_drivers": drivers.model_dump(mode="json") if drivers else None,
    }

    if not any(data.values()):
        return {**data, "error": "no cost data available", "narrative": "Cost analysis unavailable: no cost data could be computed for this resource."}

    prompt = f"Data (JSON): {data}"
    try:
        narrative = generate_text(prompt, system_instruction=NARRATION_SYSTEM_INSTRUCTION)
    except LLMUnavailableError:
        parts = ["[template fallback — Gemini unavailable]"]
        if current is not None:
            parts.append(f"current cost is ${aggregate_total(current.line_items):.2f}")
        if forecasted is not None:
            parts.append(f"forecasted cost for the period is ${forecasted.total_cost:.2f}")
        if drivers is not None and drivers.drivers:
            top = drivers.drivers[0]
            parts.append(f"the top cost driver is {top.label} at {top.pct_of_total:.1f}% of total cost")
        narrative = "; ".join(parts) + "."

    return {**data, "narrative": narrative}
