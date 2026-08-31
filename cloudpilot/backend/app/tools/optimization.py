from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.enums import ForecastHorizon
from app.models.resource import Resource
from app.optimization.comparison import ScenarioComparison
from app.optimization.comparison import compare_scenarios as _compare_scenarios
from app.optimization.constraints import check_constraints as _check_constraints
from app.optimization.enums import ScenarioType
from app.optimization.scenarios import generate_scenarios as _generate_scenarios
from app.optimization.schemas import ConstraintCheck, ScenarioResult, ScenarioSpec
from app.optimization.simulator import simulate_scenario as _simulate_scenario
from app.optimization.solver import OptimizationInfeasibleError
from app.pricing.enums import ServiceType
from app.services.optimization_service import InsufficientDemandDataError, build_context
from app.tools.base import ToolError, run_tool

TOOL_GENERATE_SCENARIOS = "generate_scenarios"
TOOL_SIMULATE_SCENARIO = "simulate_scenario"
TOOL_CHECK_CONSTRAINTS = "check_constraints"
TOOL_COMPARE_SCENARIOS = "compare_scenarios"


class GenerateScenariosInput(BaseModel):
    pass


class GenerateScenariosOutput(BaseModel):
    scenarios: list[ScenarioSpec]


def generate_scenarios(
    db: Session, *, agent_name: str, session_id: str, input: GenerateScenariosInput
) -> GenerateScenariosOutput:
    def _impl() -> GenerateScenariosOutput:
        return GenerateScenariosOutput(scenarios=_generate_scenarios())

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_GENERATE_SCENARIOS,
        input_model=input, fn=_impl,
    )


class SimulateScenarioInput(BaseModel):
    provider: str
    resource_id: str
    scenario_type: ScenarioType
    horizon: ForecastHorizon
    max_latency_ms: float
    min_availability: float
    budget: float


def simulate_scenario(
    db: Session, *, agent_name: str, session_id: str, input: SimulateScenarioInput
) -> ScenarioResult:
    def _impl() -> ScenarioResult:
        resource = db.query(Resource).filter(Resource.external_id == input.resource_id).first()
        if resource is None:
            raise ToolError(f"No resource with external_id={input.resource_id!r}")
        try:
            service = ServiceType(resource.resource_type)
        except ValueError as exc:
            raise ToolError(f"Unsupported resource_type {resource.resource_type!r}") from exc

        spec = next((s for s in _generate_scenarios() if s.scenario_type == input.scenario_type), None)
        if spec is None:
            raise ToolError(f"Unknown scenario_type {input.scenario_type!r}")

        try:
            ctx = build_context(
                db, input.provider, resource, service, input.horizon,
                input.max_latency_ms, input.min_availability, input.budget,
            )
            return _simulate_scenario(db, ctx, spec)
        except (InsufficientDemandDataError, OptimizationInfeasibleError) as exc:
            raise ToolError(str(exc)) from exc

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_SIMULATE_SCENARIO,
        input_model=input, fn=_impl,
    )


class CheckConstraintsInput(BaseModel):
    scenario_result: ScenarioResult
    max_latency_ms: float
    min_availability: float
    budget: float


class CheckConstraintsOutput(BaseModel):
    checks: list[ConstraintCheck]


def check_constraints(
    db: Session, *, agent_name: str, session_id: str, input: CheckConstraintsInput
) -> CheckConstraintsOutput:
    def _impl() -> CheckConstraintsOutput:
        checks = _check_constraints(
            input.scenario_result,
            max_latency_ms=input.max_latency_ms,
            min_availability=input.min_availability,
            budget=input.budget,
        )
        return CheckConstraintsOutput(checks=checks)

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_CHECK_CONSTRAINTS,
        input_model=input, fn=_impl,
    )


class CompareScenariosInput(BaseModel):
    scenario_results: list[ScenarioResult]
    max_latency_ms: float
    min_availability: float
    budget: float
    checks_by_scenario_type: dict[ScenarioType, list[ConstraintCheck]] | None = None


def compare_scenarios(
    db: Session, *, agent_name: str, session_id: str, input: CompareScenariosInput
) -> ScenarioComparison:
    def _impl() -> ScenarioComparison:
        if not input.scenario_results:
            raise ToolError("scenario_results must not be empty")
        return _compare_scenarios(
            input.scenario_results,
            max_latency_ms=input.max_latency_ms,
            min_availability=input.min_availability,
            budget=input.budget,
            checks_by_scenario_type=input.checks_by_scenario_type,
        )

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_COMPARE_SCENARIOS,
        input_model=input, fn=_impl,
    )
