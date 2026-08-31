import { useState } from 'react'
import { fetchCurrentCost, fetchForecastAccuracy, fetchLatestOptimization, predictCost } from '../api/endpoints'
import { useApi } from '../hooks/useApi'
import { useAppContext } from '../context/AppContext'
import { useCurrency } from '../context/CurrencyContext'
import { ResourceSelector } from '../components/ResourceSelector'
import { StatCard } from '../components/StatCard'
import { LoadingState, ErrorState, EmptyState } from '../components/StatusStates'
import type { CostPredictionSummary } from '../api/types'

export function DashboardPage() {
  const { provider, resourceId } = useAppContext()
  const { formatCurrency } = useCurrency()
  const hasResource = resourceId !== ''

  const current = useApi(() => fetchCurrentCost(provider, resourceId), [provider, resourceId], hasResource)
  const optimized = useApi(() => fetchLatestOptimization(resourceId), [resourceId], hasResource)
  const accuracy = useApi(() => fetchForecastAccuracy(resourceId), [resourceId], hasResource)

  const [predicted, setPredicted] = useState<CostPredictionSummary | null>(null)
  const [predictLoading, setPredictLoading] = useState(false)
  const [predictError, setPredictError] = useState<string | null>(null)

  async function handlePredict() {
    setPredictLoading(true)
    setPredictError(null)
    try {
      const result = await predictCost(provider, 'month', { resourceId })
      setPredicted(result)
    } catch (err) {
      setPredictError(err instanceof Error ? err.message : 'Prediction failed')
    } finally {
      setPredictLoading(false)
    }
  }

  const currentTotal = current.data ? current.data.line_items.reduce((sum, li) => sum + li.cost, 0) : null
  const optimizedScenario = optimized.data?.scenarios.find((s) => s.scenario_id === optimized.data?.chosen_scenario_id)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">Current, predicted, and optimized cost at a glance.</p>
      </div>

      <div className="max-w-xs">
        <ResourceSelector />
      </div>

      {!hasResource && <EmptyState message="Select a resource above to see its cost picture." />}

      {hasResource && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {current.loading && <LoadingState label="Loading current cost…" />}
            {current.error && <ErrorState message={current.error} />}
            {currentTotal !== null && (
              <StatCard label="Current cost (all-time)" value={formatCurrency(currentTotal)} sublabel="Sum of ingested usage, priced on-demand" />
            )}

            <StatCard
              label="Predicted cost (next month)"
              value={predicted ? formatCurrency(predicted.total_cost) : '—'}
              sublabel={
                predictLoading
                  ? 'Generating…'
                  : predicted
                    ? `${predicted.period_start} → ${predicted.period_end}`
                    : 'Click Generate to forecast'
              }
            />

            {optimized.loading && <LoadingState label="Loading optimization…" />}
            {optimized.error && (
              <StatCard label="Optimized cost" value="—" sublabel="No optimization run yet" />
            )}
            {optimizedScenario && (
              <StatCard label="Optimized cost" value={formatCurrency(optimizedScenario.predicted_cost)} sublabel={optimizedScenario.name} />
            )}

            {optimized.data && (
              <StatCard
                label="Savings vs. current"
                value={formatCurrency(optimized.data.savings_vs_current)}
                sublabel={
                  optimizedScenario
                    ? `${((optimized.data.savings_vs_current / (optimizedScenario.predicted_cost + optimized.data.savings_vs_current)) * 100).toFixed(1)}% reduction`
                    : undefined
                }
                tone={optimized.data.savings_vs_current > 0 ? 'positive' : 'default'}
              />
            )}
          </div>

          {!predicted && (
            <div>
              <button
                onClick={handlePredict}
                disabled={predictLoading}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
              >
                {predictLoading ? 'Generating prediction…' : 'Generate next-month prediction'}
              </button>
              {predictError && <div className="mt-2"><ErrorState message={predictError} /></div>}
            </div>
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-900">Forecast accuracy</h2>
            {accuracy.loading && <LoadingState label="Checking backfilled forecasts…" />}
            {accuracy.error && (
              <EmptyState message="No forecasts have accumulated enough elapsed time to be backfilled with real actuals yet — accuracy will appear here once they do." />
            )}
            {accuracy.data && (
              <div className="mt-3 grid grid-cols-3 gap-4">
                <StatCard label="Sample size" value={String(accuracy.data.sample_size)} sublabel="backfilled forecast points" />
                <StatCard label="MAE" value={accuracy.data.mae.toFixed(2)} sublabel="mean absolute error" />
                <StatCard label="MAPE" value={accuracy.data.mape !== null ? `${accuracy.data.mape.toFixed(1)}%` : 'n/a'} sublabel="mean absolute % error" />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
