"""generate_scenarios(): the fixed set of scenarios every optimization run
compares. The spec is service-agnostic — which axes actually apply to a
given service (e.g. Object Storage has no instance tier) is handled by
`app.optimization.simulator`, which no-ops an axis a service doesn't
support rather than fabricating a difference.
"""

from __future__ import annotations

from app.optimization.enums import ScenarioType
from app.optimization.schemas import ScenarioSpec


def generate_scenarios() -> list[ScenarioSpec]:
    return [
        ScenarioSpec(
            scenario_type=ScenarioType.CURRENT,
            name="Current",
            description="Today's configuration: baseline tier, on-demand pricing, "
            "peak-provisioned (no autoscaling), standard storage tier.",
            allow_tier_choice=False,
            allow_pricing_model_choice=False,
            allow_autoscaling=False,
            allow_storage_tier_choice=False,
        ),
        ScenarioSpec(
            scenario_type=ScenarioType.AUTOSCALING,
            name="Autoscaling",
            description="Baseline tier and pricing, but capacity tracks daily "
            "predicted demand instead of being sized to the period's peak.",
            allow_tier_choice=False,
            allow_pricing_model_choice=False,
            allow_autoscaling=True,
            allow_storage_tier_choice=False,
        ),
        ScenarioSpec(
            scenario_type=ScenarioType.RESERVED,
            name="Reserved",
            description="Baseline tier and provisioning, but choose the cheapest "
            "available pricing model (on-demand or a reserved commitment term).",
            allow_tier_choice=False,
            allow_pricing_model_choice=True,
            allow_autoscaling=False,
            allow_storage_tier_choice=False,
        ),
        ScenarioSpec(
            scenario_type=ScenarioType.RIGHT_SIZING,
            name="Right-sizing",
            description="On-demand, peak-provisioned, but choose the tier "
            "(instance size / serverless memory) that minimizes cost.",
            allow_tier_choice=True,
            allow_pricing_model_choice=False,
            allow_autoscaling=False,
            allow_storage_tier_choice=False,
        ),
        ScenarioSpec(
            scenario_type=ScenarioType.STORAGE_OPTIMIZATION,
            name="Storage optimization",
            description="Baseline compute configuration, but choose the "
            "cheapest storage tier that still meets latency/availability.",
            allow_tier_choice=False,
            allow_pricing_model_choice=False,
            allow_autoscaling=False,
            allow_storage_tier_choice=True,
        ),
        ScenarioSpec(
            scenario_type=ScenarioType.COMBINED,
            name="Combined",
            description="All optimizations applied together: best tier, best "
            "pricing model, autoscaling, and best storage tier.",
            allow_tier_choice=True,
            allow_pricing_model_choice=True,
            allow_autoscaling=True,
            allow_storage_tier_choice=True,
        ),
    ]
