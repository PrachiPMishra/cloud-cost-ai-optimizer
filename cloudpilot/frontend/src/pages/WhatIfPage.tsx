import { useState } from 'react'
import { runOptimization } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { useCurrency } from '../context/CurrencyContext'
import { ResourceSelector } from '../components/ResourceSelector'
import { ScenarioComparisonTable } from '../components/ScenarioComparisonTable'
import { LoadingState, ErrorState, EmptyState } from '../components/StatusStates'
import type { Horizon, OptimizationRunSummary } from '../api/types'

const HORIZONS: Horizon[] = ['day', 'week', 'month']

export function WhatIfPage() {
  const { provider, resourceId } = useAppContext()
  const { formatCurrency } = useCurrency()
  const [horizon, setHorizon] = useState<Horizon>('week')
  const [budget, setBudget] = useState(1000)
  const [maxLatencyMs, setMaxLatencyMs] = useState(100)
  const [minAvailability, setMinAvailability] = useState(99.9)

  const [result, setResult] = useState<OptimizationRunSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSimulate() {
    setLoading(true)
    setError(null)
    try {
      const summary = await runOptimization(provider, resourceId, horizon, maxLatencyMs, minAvailability / 100, budget)
      setResult(summary)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Simulation failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">What-If Simulator</h1>
        <p className="text-sm text-slate-500">
          Adjust budget, latency, and availability targets to see how the 6 optimization scenarios — and which one
          wins — change. Each simulation re-runs the real solver and is stored as an optimization run.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <div className="col-span-2 lg:col-span-1">
            <ResourceSelector />
          </div>
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
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-slate-700">Budget: {formatCurrency(budget)}</span>
            <input type="range" min={1} max={5000} step={10} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
          </label>
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-slate-700">Max latency: {maxLatencyMs} ms</span>
            <input
              type="range"
              min={5}
              max={500}
              step={5}
              value={maxLatencyMs}
              onChange={(e) => setMaxLatencyMs(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium text-slate-700">Min availability: {minAvailability.toFixed(2)}%</span>
            <input
              type="range"
              min={90}
              max={99.999}
              step={0.001}
              value={minAvailability}
              onChange={(e) => setMinAvailability(Number(e.target.value))}
            />
          </label>
        </div>
        <div className="mt-4">
          <button
            onClick={handleSimulate}
            disabled={!resourceId || loading}
            className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Simulating…' : 'Simulate'}
          </button>
        </div>
      </div>

      {!resourceId && <EmptyState message="Select a resource to simulate." />}
      {loading && <LoadingState label="Running solver across 6 scenarios…" />}
      {error && <ErrorState message={error} />}

      {result && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Fully feasible?</div>
              <div className={`mt-1 text-lg font-semibold ${result.fully_feasible ? 'text-emerald-600' : 'text-red-600'}`}>
                {result.fully_feasible ? 'Yes' : 'No — best effort shown'}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Savings vs. current</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{formatCurrency(result.savings_vs_current)}</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Chosen plan</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">
                {result.scenarios.find((s) => s.scenario_id === result.chosen_scenario_id)?.name}
              </div>
            </div>
          </div>

          <ScenarioComparisonTable scenarios={result.scenarios} chosenScenarioId={result.chosen_scenario_id} />
        </>
      )}
    </div>
  )
}
