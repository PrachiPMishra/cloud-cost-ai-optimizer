import type { AgentFinalState, ScenarioSummary } from '../api/types'

/** Reconstructs a ScenarioSummary[] (same shape the direct optimization API
 * returns) from the agent pipeline's streamed state — the agent path never
 * persists Scenario/OptimizationRun rows, so there's no real scenario_id;
 * we synthesize one from list position, which is all the comparison table
 * needs it for (a React key + highlighting the chosen row). */
export function buildScenarioSummaries(state: AgentFinalState | null): {
  scenarios: ScenarioSummary[]
  chosenId: number | undefined
} {
  if (!state?.optimization_ranked || !state.optimization_results_by_type) {
    return { scenarios: [], chosenId: undefined }
  }

  const checksByType = state.optimization_checks_by_type ?? {}
  const candidateType = state.optimization_data?.candidate?.scenario_type
  const approved = state.optimization_data?.approved ?? false

  const scenarios: ScenarioSummary[] = state.optimization_ranked.map((type, index) => {
    const result = state.optimization_results_by_type![type]
    const checks = checksByType[type] ?? []
    return {
      scenario_id: index + 1,
      scenario_type: result.scenario_type,
      name: result.name,
      description: result.description,
      configuration: result.configuration,
      predicted_demand_peak: result.predicted_demand_peak,
      capacity_provisioned: result.capacity_provisioned,
      predicted_cost: result.predicted_cost,
      latency_ms: result.latency_ms,
      availability: result.availability,
      solver_status: result.solver_status,
      constraints_satisfied: checks.length > 0 ? checks.every((c) => c.satisfied) : true,
      constraint_checks: checks,
    }
  })

  const chosen = scenarios.find((s) => s.scenario_type === candidateType && approved)
  return { scenarios, chosenId: chosen?.scenario_id }
}
