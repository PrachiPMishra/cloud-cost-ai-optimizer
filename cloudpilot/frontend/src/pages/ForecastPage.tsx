import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { createForecast, fetchUsageHistory } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { ResourceSelector } from '../components/ResourceSelector'
import { LoadingState, ErrorState, EmptyState } from '../components/StatusStates'
import type { ForecastResponse, Horizon, UsageHistoryResponse } from '../api/types'

const USAGE_TYPES = ['requests', 'hours_used', 'storage_gb', 'network_gb']
const HORIZONS: Horizon[] = ['day', 'week', 'month']

interface ChartRow {
  date: string
  historical?: number
  predicted?: number
  lower?: number
  upper?: number
  actual?: number
}

function mergeSeries(history: UsageHistoryResponse | null, forecast: ForecastResponse | null): ChartRow[] {
  const rows = new Map<string, ChartRow>()
  history?.points.forEach((p) => rows.set(p.date, { date: p.date, historical: p.quantity }))
  forecast?.points.forEach((p) => {
    const existing = rows.get(p.date) ?? { date: p.date }
    rows.set(p.date, {
      ...existing,
      predicted: p.predicted_usage ?? undefined,
      lower: p.lower_bound ?? undefined,
      upper: p.upper_bound ?? undefined,
      actual: p.actual_usage ?? undefined,
    })
  })
  return Array.from(rows.values()).sort((a, b) => a.date.localeCompare(b.date))
}

function MiniForecastCard({ resourceId, usageType }: { resourceId: string; usageType: string }) {
  // Keyed by (resourceId, usageType) so "loading" is derived at render time —
  // a result whose key doesn't match the current props is stale (from the
  // previous card) and treated the same as "not loaded yet", with no
  // separate loading flag to keep in sync by hand.
  const key = `${resourceId}:${usageType}`
  const [result, setResult] = useState<{ key: string; forecast: ForecastResponse | null; error: string | null } | null>(null)

  useEffect(() => {
    let cancelled = false
    createForecast(resourceId, usageType, 'week')
      .then((forecast) => {
        if (!cancelled) setResult({ key, forecast, error: null })
      })
      .catch((e) => {
        if (!cancelled) setResult({ key, forecast: null, error: e instanceof Error ? e.message : 'Failed' })
      })
    return () => {
      cancelled = true
    }
  }, [resourceId, usageType, key])

  const loading = result?.key !== key

  if (loading) return <LoadingState label={`Forecasting ${usageType}…`} />
  if (result.error) return null // not applicable for this resource — skip silently, no fake data
  if (!result.forecast) return null

  const data = result.forecast.points.map((p) => ({ date: p.date, predicted: p.predicted_usage }))

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{usageType}</div>
      <ResponsiveContainer width="100%" height={100}>
        <ComposedChart data={data}>
          <Line type="monotone" dataKey="predicted" stroke="#2563eb" strokeWidth={2} dot={false} />
          <XAxis dataKey="date" hide />
          <YAxis hide />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ForecastPage() {
  const { resourceId } = useAppContext()
  const [usageType, setUsageType] = useState('requests')
  const [horizon, setHorizon] = useState<Horizon>('week')

  const [history, setHistory] = useState<UsageHistoryResponse | null>(null)
  const [forecast, setForecast] = useState<ForecastResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    setForecast(null)
    try {
      const [historyResult, forecastResult] = await Promise.all([
        fetchUsageHistory(resourceId, usageType),
        createForecast(resourceId, usageType, horizon),
      ])
      setHistory(historyResult)
      setForecast(forecastResult)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate forecast')
    } finally {
      setLoading(false)
    }
  }

  const chartData = useMemo(() => mergeSeries(history, forecast), [history, forecast])
  const boundaryDate = history?.points.at(-1)?.date

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Forecast</h1>
        <p className="text-sm text-slate-500">Historical usage, forecast, and confidence interval.</p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div className="max-w-xs">
          <ResourceSelector />
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Usage type</span>
          <select
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            value={usageType}
            onChange={(e) => setUsageType(e.target.value)}
          >
            {USAGE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Horizon</span>
          <select
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            value={horizon}
            onChange={(e) => setHorizon(e.target.value as Horizon)}
          >
            {HORIZONS.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </label>
        <button
          onClick={handleGenerate}
          disabled={!resourceId || loading}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Generating…' : 'Generate forecast'}
        </button>
      </div>

      {!resourceId && <EmptyState message="Select a resource to forecast." />}
      {error && <ErrorState message={error} />}

      {forecast && (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">
                {usageType} — history + {horizon}-ahead forecast ({forecast.model_name})
              </h2>
              <span className="text-xs text-slate-500">
                MAE {forecast.metrics[forecast.model_name]?.mae.toFixed(2)} · RMSE{' '}
                {forecast.metrics[forecast.model_name]?.rmse.toFixed(2)}
              </span>
            </div>
            <ResponsiveContainer width="100%" height={340}>
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={30} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                {boundaryDate && <ReferenceLine x={boundaryDate} stroke="#94a3b8" strokeDasharray="4 4" label="today" />}
                <Line type="monotone" dataKey="historical" name="History" stroke="#64748b" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="predicted" name="Forecast" stroke="#2563eb" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="upper" name="Upper CI" stroke="#93c5fd" dot={false} strokeDasharray="4 4" />
                <Line type="monotone" dataKey="lower" name="Lower CI" stroke="#93c5fd" dot={false} strokeDasharray="4 4" />
                <Line type="monotone" dataKey="actual" name="Actual (backfilled)" stroke="#16a34a" strokeWidth={0} dot={{ r: 3 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          <div>
            <h2 className="mb-3 text-sm font-semibold text-slate-900">Per-metric forecasts for this resource</h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              {USAGE_TYPES.filter((t) => t !== usageType).map((t) => (
                <MiniForecastCard key={t} resourceId={resourceId} usageType={t} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
