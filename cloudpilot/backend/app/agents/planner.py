"""Planner agent: turns the user's natural-language request into a
structured plan of which downstream analysis steps to run. Gemini is used
purely for intent classification into a fixed, typed schema — the planner
never computes or invents any number, and the set of possible steps is
closed (forecast / cost analysis / optimization), not open-ended.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.agents.llm_client import LLMUnavailableError, generate_structured

AGENT_NAME = "planner_agent"

PLANNER_SYSTEM_INSTRUCTION = (
    "You are the planning module of a cloud cost optimization assistant. "
    "You decide which fixed analysis steps are relevant to a user's request: "
    "usage forecasting, cost analysis, and optimization recommendations. "
    "You never compute or state any numeric result yourself — only which "
    "steps should run and why."
)


class Plan(BaseModel):
    run_forecast: bool = True
    run_cost_analysis: bool = True
    run_optimization: bool = True
    reasoning: str = ""


DEFAULT_PLAN = Plan(reasoning="Default plan (LLM unavailable): run every analysis step.")


def plan_request(user_query: str) -> Plan:
    prompt = (
        f"User request: {user_query}\n\n"
        "Decide which analysis steps are relevant and respond with the "
        "requested JSON structure."
    )
    try:
        return generate_structured(prompt, Plan, system_instruction=PLANNER_SYSTEM_INSTRUCTION)
    except LLMUnavailableError:
        return DEFAULT_PLAN
