"""Report agent: synthesizes the other agents' narratives into one final
report. Each input narrative is already grounded in tool-computed data —
the report agent recombines prose, it does not introduce new numbers.
"""

from __future__ import annotations

from app.agents.llm_client import LLMUnavailableError, generate_text

AGENT_NAME = "report_agent"

REPORT_SYSTEM_INSTRUCTION = (
    "You are the final report writer for a cloud cost optimization assistant. "
    "Combine the given section narratives (each already grounded in computed "
    "data) into one cohesive report with short headers: Forecast, Cost "
    "Analysis, Optimization Recommendation, and a closing Reviewer Note. Do "
    "not add any new numbers — only reorganize and connect what's given."
)


def run_report_agent(
    *, forecast_narrative: str, cost_narrative: str, optimization_narrative: str, critic_notes: str
) -> str:
    prompt = (
        f"Forecast section: {forecast_narrative}\n\n"
        f"Cost analysis section: {cost_narrative}\n\n"
        f"Optimization section: {optimization_narrative}\n\n"
        f"Reviewer note: {critic_notes}"
    )
    try:
        return generate_text(prompt, system_instruction=REPORT_SYSTEM_INSTRUCTION)
    except LLMUnavailableError:
        return (
            "# Cloud Cost Report (template fallback — Gemini unavailable)\n\n"
            f"## Forecast\n{forecast_narrative}\n\n"
            f"## Cost Analysis\n{cost_narrative}\n\n"
            f"## Optimization Recommendation\n{optimization_narrative}\n\n"
            f"## Reviewer Note\n{critic_notes}\n"
        )
