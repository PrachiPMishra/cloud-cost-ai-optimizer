import { useState } from 'react'
import { AGENT_STEPS, useAgentRun } from '../hooks/useAgentRun'
import { useAgentTraceStream } from '../hooks/useAgentTraceStream'
import { useAppContext } from '../context/AppContext'
import { useCurrency } from '../context/CurrencyContext'
import { ResourceSelector } from '../components/ResourceSelector'
import { ScenarioComparisonTable } from '../components/ScenarioComparisonTable'
import { ErrorState } from '../components/StatusStates'
import { buildScenarioSummaries } from '../lib/agentScenarios'
import type { Horizon } from '../api/types'

const HORIZONS: Horizon[] = ['day', 'week', 'month']

function StepProgress({ completedSteps, loading }: { completedSteps: string[]; loading: boolean }) {
  return (
    <ol className="flex flex-wrap gap-2">
      {AGENT_STEPS.map((step) => {
        const done = completedSteps.includes(step.key)
        const isCurrent = loading && !done && completedSteps.length === AGENT_STEPS.findIndex((s) => s.key === step.key)
        return (
          <li
            key={step.key}
            className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
              done
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : isCurrent
                  ? 'border-blue-200 bg-blue-50 text-blue-700'
                  : 'border-slate-200 bg-slate-50 text-slate-400'
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${done ? 'bg-emerald-500' : isCurrent ? 'animate-pulse bg-blue-500' : 'bg-slate-300'}`}
            />
            {step.label}
          </li>
        )
      })}
    </ol>
  )
}

function LiveToolLog({ sessionId }: { sessionId: string | null }) {
  const trace = useAgentTraceStream(sessionId)

  if (!sessionId || trace.events.length === 0) return null

  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
        Live tool calls
        <span className={`h-1.5 w-1.5 rounded-full ${trace.connected ? 'animate-pulse bg-emerald-500' : 'bg-slate-300'}`} />
      </div>
      <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto text-xs">
        {trace.events.map((e) => (
          <li key={e.id} className="flex items-center justify-between rounded bg-slate-50 px-2 py-1">
            <span>
              <span className="text-slate-500">{e.agent_name}</span>
              <span className="mx-1 text-slate-300">→</span>
              <span className="font-mono text-slate-700">{e.tool_name ?? e.event_type}</span>
            </span>
            <span className="flex items-center gap-2 text-slate-400">
              <span className={e.output?.status === 'success' ? 'text-emerald-600' : 'text-red-600'}>
                {e.output?.status ?? '…'}
              </span>
              <span>{e.latency_ms}ms</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function OptimizationPage() {
  const { provider, resourceId } = useAppContext()
  const { formatCurrency } = useCurrency()
  const { run, state, completedSteps, loading, error, sessionId } = useAgentRun()

  const [horizon, setHorizon] = useState<Horizon>('week')
  const [maxLatencyMs, setMaxLatencyMs] = useState(100)
  const [minAvailability, setMinAvailability] = useState(99.9)
  const [budget, setBudget] = useState(1000)

  function handleOptimize() {
    run({
      user_query: `Optimize cost for ${resourceId} within budget $${budget}, max latency ${maxLatencyMs}ms, min availability ${minAvailability}%.`,
      provider,
      resource_id: resourceId,
      usage_type: 'requests',
      horizon,
      max_latency_ms: maxLatencyMs,
      min_availability: minAvailability / 100,
      budget,
    })
  }

  const { scenarios, chosenId } = buildScenarioSummaries(state)
  const candidate = state?.optimization_data?.candidate
  const approved = state?.optimization_data?.approved
  // Compare against the "current" scenario's cost (same horizon as the
  // candidate) — not state.current_cost, which is an all-time historical
  // total from a different time window and would produce a bogus figure.
  const currentScenario = scenarios.find((s) => s.scenario_type === 'current')
  const savings = candidate && currentScenario ? currentScenario.predicted_cost - candidate.predicted_cost : null
  const done = Boolean(state?.final_report)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Optimization</h1>
        <p className="text-sm text-slate-500">
          Set your constraints, then run the full agent pipeline: forecast → cost analysis → scenario simulation →
          critic validation → report.
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
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Budget ($)</span>
            <input
              type="number"
              min={0}
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value) || 0)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Max latency (ms)</span>
            <input
              type="number"
              min={1}
              value={maxLatencyMs}
              onChange={(e) => setMaxLatencyMs(Number(e.target.value) || 1)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Min availability (%)</span>
            <input
              type="number"
              min={0}
              max={100}
              step={0.001}
              value={minAvailability}
              onChange={(e) => setMinAvailability(Number(e.target.value) || 0)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        </div>

        <div className="mt-4">
          <button
            onClick={handleOptimize}
            disabled={!resourceId || loading}
            className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Optimizing…' : 'Optimize'}
          </button>
        </div>
      </div>

      {error && <ErrorState message={error} />}

      {(loading || completedSteps.length > 0) && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-900">Live progress</h2>
          <StepProgress completedSteps={completedSteps} loading={loading} />
          {state?.optimization_attempt !== undefined && state.optimization_attempt > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              Optimization attempt {state.optimization_attempt} of 3
              {(state.rejected_scenario_types?.length ?? 0) > 0 &&
                ` — rejected: ${state.rejected_scenario_types!.join(', ')}`}
            </p>
          )}
          <LiveToolLog sessionId={sessionId} />
        </div>
      )}

      {done && candidate && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Plan</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{candidate.name}</div>
              <div className="mt-1 text-xs text-slate-500">
                {approved ? 'Approved by critic' : 'Not approved — see below'}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Cost / Savings</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{formatCurrency(candidate.predicted_cost)}</div>
              {savings !== null && (
                <div className={`text-xs ${savings > 0 ? 'text-emerald-600' : 'text-slate-500'}`}>
                  {savings >= 0 ? '+' : ''}
                  {formatCurrency(savings)} vs. current
                </div>
              )}
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Availability / Latency</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{(candidate.availability * 100).toFixed(3)}%</div>
              <div className="text-xs text-slate-500">{candidate.latency_ms.toFixed(1)} ms</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Confidence</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">
                {approved ? 'High' : 'Low — rejected'}
              </div>
              {state?.forecast_uncertainty_ratio !== undefined && (
                <div className="text-xs text-slate-500">forecast uncertainty {(state.forecast_uncertainty_ratio * 100).toFixed(0)}%</div>
              )}
            </div>
          </div>

          {!approved && state?.critic_verdict?.rejection_reason && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <strong>Not approved:</strong> {state.critic_verdict.rejection_reason}
            </div>
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-900">Why this recommendation</h2>
            <p className="whitespace-pre-wrap text-sm text-slate-700">{state?.optimization_narrative}</p>

            {(state?.optimization_data?.knowledge_sources.length ?? 0) > 0 && (
              <div className="mt-4 border-t border-slate-100 pt-3">
                <div className="mb-2 text-xs font-semibold uppercase text-slate-500">RAG sources cited</div>
                <ul className="flex flex-col gap-1 text-xs text-slate-600">
                  {state!.optimization_data!.knowledge_sources.map((k) => (
                    <li key={k.source}>
                      📄 <span className="font-medium">{k.source}</span> (relevance {k.score.toFixed(2)})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {scenarios.length > 0 && (
            <div>
              <h2 className="mb-3 text-sm font-semibold text-slate-900">Scenario comparison</h2>
              <ScenarioComparisonTable scenarios={scenarios} chosenScenarioId={chosenId} />
            </div>
          )}

          <details className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">Full report</summary>
            <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{state?.final_report}</p>
          </details>

          {sessionId && (
            <a href={`/agent-trace?session_id=${sessionId}`} className="text-xs text-blue-600 hover:underline">
              View full agent trace for this run →
            </a>
          )}
        </>
      )}
    </div>
  )
}
