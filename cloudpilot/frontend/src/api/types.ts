// Mirrors backend Pydantic response models exactly (see cloudpilot/backend/app/api/*.py).

export type Horizon = 'day' | 'week' | 'month'
export type PricingModel = 'on_demand' | 'reserved'
export type ScenarioType =
  | 'current'
  | 'autoscaling'
  | 'reserved'
  | 'right_sizing'
  | 'storage_optimization'
  | 'combined'

export interface ResourceOut {
  resource_id: string
  service: string
  provider: string
  region: string
}
export interface ResourceListResponse {
  resources: ResourceOut[]
}

export interface UsagePoint {
  date: string
  quantity: number
}
export interface UsageHistoryResponse {
  resource_id: string
  usage_type: string
  points: UsagePoint[]
}

export interface ModelMetrics {
  mae: number
  rmse: number
  mape: number | null
}
export interface StoredForecastPoint {
  date: string
  predicted_usage: number | null
  lower_bound: number | null
  upper_bound: number | null
  actual_usage: number | null
}
export interface ForecastResponse {
  id: number
  resource_id: string
  service: string
  usage_type: string
  horizon_days: number
  model_name: string
  model_version: string
  status: string
  generated_at: string
  training_window_start: string
  training_window_end: string
  metrics: Record<string, ModelMetrics>
  points: StoredForecastPoint[]
}

export interface ForecastAccuracyResponse {
  sample_size: number
  mae: number
  rmse: number
  mape: number | null
}

export interface TierBreakdown {
  tier_min: number
  tier_max: number | null
  quantity: number
  rate: number
  subtotal: number
}
export interface CostCalculationResult {
  provider: string
  region: string
  service: string
  sku: string
  unit: string
  pricing_model: PricingModel
  commitment_term_months: number | null
  resource_id: string | null
  resolved_quantity: number
  cost: number
  currency: string
  effective_date: string
  tiers_applied: TierBreakdown[]
}
export interface PriceUsageResult {
  line_items: CostCalculationResult[]
  skipped: string[]
}

export interface CostDriver {
  label: string
  cost: number
  pct_of_total: number
}
export interface CostDriverReport {
  total_cost: number
  drivers: CostDriver[]
}

export interface LineItemBreakdown {
  resource_id: string
  service: string
  usage_type: string
  sku: string
  unit: string
  forecast_model: string
  predicted_quantity: number
  predicted_cost: number
  lower_bound_cost: number | null
  upper_bound_cost: number | null
}
export interface CostPredictionSummary {
  forecast_id: number
  provider: string
  pricing_model: PricingModel
  horizon_days: number
  period_start: string
  period_end: string
  generated_at: string
  total_cost: number
  total_lower_bound: number | null
  total_upper_bound: number | null
  by_service: Record<string, number>
  by_resource: Record<string, number>
  by_usage_unit: Record<string, number>
  line_items: LineItemBreakdown[]
  skipped: string[]
}

export interface ConstraintCheck {
  constraint_type: string
  threshold: number
  actual: number
  satisfied: boolean
  description: string
}
export interface ScenarioSummary {
  scenario_id: number
  scenario_type: ScenarioType
  name: string
  description: string
  configuration: Record<string, unknown>
  predicted_demand_peak: number
  capacity_provisioned: number
  predicted_cost: number
  latency_ms: number
  availability: number
  solver_status: string
  constraints_satisfied: boolean
  constraint_checks: ConstraintCheck[]
}
export interface OptimizationRunSummary {
  optimization_run_id: number
  resource_id: string
  service: string
  provider: string
  horizon_days: number
  max_latency_ms: number
  min_availability: number
  budget: number
  chosen_scenario_id: number
  fully_feasible: boolean
  savings_vs_current: number
  scenarios: ScenarioSummary[]
  generated_at: string
}

export interface SettingsResponse {
  app_name: string
  gemini_model: string
  gemini_configured: boolean
  database_connected: boolean
  /** Display-only USD->INR rate (backend/app/services/currency.py). Every
   * monetary figure in every other API response is USD; this rate is used
   * client-side to reformat those already-fetched figures for display. */
  usd_to_inr_rate: number
}

export interface IngestSummary {
  rows_received: number
  rows_valid: number
  rows_failed: number
  usage_records_inserted: number
  resources_created: number
  resources_updated: number
  errors: { row_index: number; error: string }[]
}

// ---- Agent pipeline (SSE + trace) ----

export interface Plan {
  run_forecast: boolean
  run_cost_analysis: boolean
  run_optimization: boolean
  reasoning: string
}

export interface KnowledgeSnippet {
  source: string
  content: string
  score: number
}

export interface CriticFinding {
  check: string
  passed: boolean
  detail: string
}
export interface CriticVerdict {
  approved: boolean
  findings: CriticFinding[]
  rejection_reason: string | null
}
export interface CriticHistoryEntry {
  scenario_type: string
  verdict: CriticVerdict
}

export interface OptimizationAgentData {
  candidate: ScenarioResultLike | null
  approved: boolean
  exhausted_without_approval: boolean
  rejection_history: CriticHistoryEntry[]
  knowledge_sources: KnowledgeSnippet[]
}

export interface ScenarioResultLike {
  scenario_type: ScenarioType
  name: string
  description: string
  configuration: Record<string, unknown>
  predicted_demand_peak: number
  capacity_provisioned: number
  predicted_cost: number
  latency_ms: number
  availability: number
  solver_status: string
}

export interface AgentFinalState {
  session_id: string
  plan?: Plan
  forecast_data?: Record<string, unknown>
  forecast_narrative?: string
  cost_data?: Record<string, unknown>
  cost_narrative?: string
  optimization_data?: OptimizationAgentData
  optimization_narrative?: string
  optimization_ranked?: ScenarioType[]
  optimization_results_by_type?: Record<string, ScenarioResultLike>
  optimization_checks_by_type?: Record<string, ConstraintCheck[]>
  current_candidate_type?: ScenarioType | null
  critic_verdict?: CriticVerdict
  critic_notes?: string
  critic_history?: CriticHistoryEntry[]
  optimization_attempt?: number
  rejected_scenario_types?: string[]
  forecast_uncertainty_ratio?: number
  current_cost?: number
  final_report?: string
}

export type AgentStreamChunk =
  | { _meta: { session_id?: string; event: 'started' | 'done' | 'error'; error?: string } }
  | Record<string, Partial<AgentFinalState>>

export interface AgentEventOut {
  id: number
  session_id: string
  agent_name: string
  event_type: string
  tool_name: string | null
  input: Record<string, unknown> | null
  output: { status: 'success' | 'error'; result?: unknown; error?: string } | null
  latency_ms: number | null
  created_at: string
}
export interface AgentEventsResponse {
  events: AgentEventOut[]
}

export interface AgentSessionSummary {
  session_id: string
  event_count: number
  started_at: string
  ended_at: string
}
export interface AgentSessionsResponse {
  sessions: AgentSessionSummary[]
}

// GET /api/agent-trace/{session_id} — live SSE tail of agent_events.
export type AgentTraceStreamChunk =
  | { _meta: { event: 'connected' | 'idle_timeout' | 'error'; session_id?: string; error?: string } }
  | { event: AgentEventOut }
