import { apiGet, apiPost, apiPostForm, API_BASE_URL } from './client'
import type {
  AgentEventsResponse,
  AgentSessionsResponse,
  CostDriverReport,
  CostPredictionSummary,
  ForecastAccuracyResponse,
  ForecastResponse,
  Horizon,
  IngestSummary,
  OptimizationRunSummary,
  PriceUsageResult,
  PricingModel,
  ResourceListResponse,
  SettingsResponse,
  UsageHistoryResponse,
} from './types'

export function fetchResources(provider?: string, service?: string) {
  return apiGet<ResourceListResponse>('/resources', { provider, service })
}

export function fetchUsageHistory(resourceId: string, usageType: string) {
  return apiGet<UsageHistoryResponse>('/usage/history', { resource_id: resourceId, usage_type: usageType })
}

export function createForecast(resourceId: string, usageType: string, horizon: Horizon) {
  return apiPost<ForecastResponse>('/forecast', { resource_id: resourceId, usage_type: usageType, horizon })
}

export function fetchForecast(id: number) {
  return apiGet<ForecastResponse>(`/forecast/${id}`)
}

export function fetchForecastAccuracy(resourceId?: string) {
  return apiGet<ForecastAccuracyResponse>('/forecast/accuracy', { resource_id: resourceId })
}

export function fetchCurrentCost(provider: string, resourceId?: string, service?: string) {
  return apiGet<PriceUsageResult>('/cost/current', { provider, resource_id: resourceId, service })
}

export function fetchCostDrivers(
  provider: string,
  opts: { resourceId?: string; service?: string; source?: 'current' | 'forecasted'; horizon?: Horizon; topN?: number },
) {
  return apiGet<CostDriverReport>('/cost/drivers', {
    provider,
    resource_id: opts.resourceId,
    service: opts.service,
    source: opts.source ?? 'current',
    horizon: opts.horizon,
    top_n: opts.topN ?? 5,
  })
}

export function predictCost(
  provider: string,
  horizon: Horizon,
  opts: { resourceId?: string; service?: string; pricingModel?: PricingModel; commitmentTermMonths?: number } = {},
) {
  return apiPost<CostPredictionSummary>('/cost/predict', {
    provider,
    horizon,
    resource_id: opts.resourceId,
    service: opts.service,
    pricing_model: opts.pricingModel ?? 'on_demand',
    commitment_term_months: opts.commitmentTermMonths,
  })
}

export function fetchCostBreakdown(forecastId?: number) {
  return apiGet<CostPredictionSummary>('/cost/breakdown', { forecast_id: forecastId })
}

export function runOptimization(
  provider: string,
  resourceId: string,
  horizon: Horizon,
  maxLatencyMs: number,
  minAvailability: number,
  budget: number,
) {
  return apiPost<OptimizationRunSummary>('/optimization/run', {
    provider,
    resource_id: resourceId,
    horizon,
    max_latency_ms: maxLatencyMs,
    min_availability: minAvailability,
    budget,
  })
}

export function fetchLatestOptimization(resourceId?: string) {
  return apiGet<OptimizationRunSummary>('/optimization/latest', { resource_id: resourceId })
}

export function fetchOptimization(id: number) {
  return apiGet<OptimizationRunSummary>(`/optimization/${id}`)
}

export function fetchSettings() {
  return apiGet<SettingsResponse>('/settings')
}

export function uploadUsageFile(file: File) {
  const form = new FormData()
  form.append('file', file)
  return apiPostForm<IngestSummary>('/data/upload', form)
}

export function fetchAgentEvents(sessionId: string) {
  return apiGet<AgentEventsResponse>('/agent/events', { session_id: sessionId })
}

export function fetchAgentSessions(limit = 20) {
  return apiGet<AgentSessionsResponse>('/agent/sessions', { limit })
}

export function agentRunStreamUrl() {
  return `${API_BASE_URL}/agent/run`
}

export function agentTraceStreamUrl(sessionId: string) {
  return `${API_BASE_URL}/agent-trace/${encodeURIComponent(sessionId)}`
}
