from pydantic import BaseModel

from app.optimization.enums import ScenarioType


class ScenarioSpec(BaseModel):
    """Which decision axes a scenario is allowed to change vs. the baseline."""

    scenario_type: ScenarioType
    name: str
    description: str
    allow_tier_choice: bool
    allow_pricing_model_choice: bool
    allow_autoscaling: bool
    allow_storage_tier_choice: bool


class ScenarioResult(BaseModel):
    scenario_type: ScenarioType
    name: str
    description: str
    configuration: dict
    predicted_demand_peak: float
    capacity_provisioned: float
    predicted_cost: float
    latency_ms: float
    availability: float
    solver_status: str


class ConstraintCheck(BaseModel):
    constraint_type: str
    threshold: float
    actual: float
    satisfied: bool
    description: str
