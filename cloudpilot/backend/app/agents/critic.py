"""Critic agent: real, deterministic validation of one candidate
optimization scenario, plus a short LLM (or template) reviewer note.

Every check here is pure Python over already-computed numbers — the
critic computes nothing new and calls no tools; it only judges whether
the Optimization agent's candidate is trustworthy enough to recommend.
A failing check produces a specific, machine-readable reason, not a vague
LLM impression, so the Optimization agent's retry logic can act on it and
the final report can quote it honestly if no candidate ever passes.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from app.agents.llm_client import LLMUnavailableError, generate_text
from app.optimization.schemas import ConstraintCheck, ScenarioResult

AGENT_NAME = "critic_agent"

# A forecast whose average (upper - lower) / predicted_usage across the
# horizon exceeds this is judged too uncertain to act on with confidence.
# This is a documented judgment call, not a statistically derived cutoff —
# consistent with the other heuristic thresholds in this project (e.g. the
# forecasting engine's confidence-interval z-score).
MAX_ACCEPTABLE_UNCERTAINTY_RATIO = 1.5

# A recommendation claiming to cut cost by more than this fraction is
# flagged for review rather than presented with confidence — see the
# reasoning where this is used.
MAX_PLAUSIBLE_COST_REDUCTION_FRACTION = 0.95

REVIEWER_SYSTEM_INSTRUCTION = (
    "You are a lightweight review module for a cloud cost assistant's optimization "
    "recommendation. You are given the outcome of a set of deterministic validation "
    "checks (already computed — do not recompute or second-guess the numbers). Write "
    "ONE short sentence summarizing the outcome for a non-technical reader. Do not add "
    "any numbers of your own beyond what's given."
)


class CriticFinding(BaseModel):
    check: str
    passed: bool
    detail: str


class CriticVerdict(BaseModel):
    approved: bool
    findings: list[CriticFinding]
    rejection_reason: str | None


def evaluate_scenario(
    scenario: ScenarioResult,
    checks: list[ConstraintCheck],
    *,
    current_cost: float | None,
    forecast_uncertainty_ratio: float | None,
) -> CriticVerdict:
    findings: list[CriticFinding] = []

    # 1) Re-verify the four basic constraints (defense in depth — these were
    # already checked by app.optimization.check_constraints, but the critic
    # is the last line of review before a recommendation goes out).
    for check in checks:
        findings.append(
            CriticFinding(
                check=f"constraint:{check.constraint_type}",
                passed=check.satisfied,
                detail=f"{check.description} (actual={check.actual:.4g}, threshold={check.threshold:.4g})",
            )
        )

    # 2) Cost must be a real, non-negative number.
    cost_ok = math.isfinite(scenario.predicted_cost) and scenario.predicted_cost >= 0
    findings.append(
        CriticFinding(
            check="unrealistic_assumptions:cost",
            passed=cost_ok,
            detail=f"predicted_cost={scenario.predicted_cost!r}",
        )
    )

    # 3) Availability must be a valid probability.
    availability_ok = math.isfinite(scenario.availability) and 0.0 <= scenario.availability <= 1.0
    findings.append(
        CriticFinding(
            check="unrealistic_assumptions:availability",
            passed=availability_ok,
            detail=f"availability={scenario.availability!r}",
        )
    )

    # 4) Latency must be a real, positive number.
    latency_ok = math.isfinite(scenario.latency_ms) and scenario.latency_ms > 0
    findings.append(
        CriticFinding(
            check="unrealistic_assumptions:latency",
            passed=latency_ok,
            detail=f"latency_ms={scenario.latency_ms!r}",
        )
    )

    # 5) Capacity must be provisioned to meet demand (redundant with the
    # "capacity" constraint check above, kept explicit since it's named in
    # the phase's own list of things the critic checks).
    capacity_ok = scenario.capacity_provisioned >= scenario.predicted_demand_peak
    findings.append(
        CriticFinding(
            check="capacity",
            passed=capacity_ok,
            detail=f"capacity_provisioned={scenario.capacity_provisioned:.4g} vs "
            f"predicted_demand_peak={scenario.predicted_demand_peak:.4g}",
        )
    )

    # 6) A near-total cost reduction is more likely a pricing/data bug (a
    # missing cost component, a unit mismatch) than a genuine optimization
    # win — flag it for a human to verify rather than reporting it as a
    # confident recommendation. (Savings exceeding current_cost outright is
    # already impossible whenever cost_ok holds, since predicted_cost >= 0.)
    if current_cost is not None and cost_ok and current_cost > 0:
        reduction_fraction = (current_cost - scenario.predicted_cost) / current_cost
        savings_ok = reduction_fraction <= MAX_PLAUSIBLE_COST_REDUCTION_FRACTION
        findings.append(
            CriticFinding(
                check="unrealistic_assumptions:savings",
                passed=savings_ok,
                detail=f"cost_reduction={reduction_fraction * 100:.1f}% "
                f"(predicted_cost={scenario.predicted_cost:.2f} vs current_cost={current_cost:.2f}, "
                f"limit={MAX_PLAUSIBLE_COST_REDUCTION_FRACTION * 100:.0f}%)",
            )
        )

    # 7) Forecast uncertainty: is the demand forecast this decision rests
    # on confident enough to act on?
    if forecast_uncertainty_ratio is not None:
        uncertainty_ok = forecast_uncertainty_ratio <= MAX_ACCEPTABLE_UNCERTAINTY_RATIO
        findings.append(
            CriticFinding(
                check="forecast_uncertainty",
                passed=uncertainty_ok,
                detail=f"relative_uncertainty={forecast_uncertainty_ratio:.2f} "
                f"(limit={MAX_ACCEPTABLE_UNCERTAINTY_RATIO})",
            )
        )

    approved = all(f.passed for f in findings)
    rejection_reason = (
        None if approved else "; ".join(f"{f.check}: {f.detail}" for f in findings if not f.passed)
    )

    return CriticVerdict(approved=approved, findings=findings, rejection_reason=rejection_reason)


def summarize_verdict(verdict: CriticVerdict) -> str:
    if verdict.approved:
        prompt = "All validation checks passed for the recommended scenario. Confirm this in one sentence."
    else:
        prompt = (
            f"The following checks failed: {verdict.rejection_reason}. "
            "State in one sentence that the recommendation was rejected and why, "
            "without inventing any numbers beyond what's given."
        )

    try:
        return generate_text(prompt, system_instruction=REVIEWER_SYSTEM_INSTRUCTION)
    except LLMUnavailableError:
        if verdict.approved:
            return "Critic (template fallback): all validation checks passed."
        return f"Critic (template fallback): rejected — {verdict.rejection_reason}"
