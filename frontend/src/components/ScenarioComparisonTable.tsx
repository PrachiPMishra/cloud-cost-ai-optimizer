import type { ScenarioSummary } from '../api/types'
import { useCurrency } from '../context/CurrencyContext'

export function ScenarioComparisonTable({
  scenarios,
  chosenScenarioId,
}: {
  scenarios: ScenarioSummary[]
  chosenScenarioId?: number
}) {
  const { formatCurrency } = useCurrency()
  const current = scenarios.find((s) => s.scenario_type === 'current')

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">Plan</th>
            <th className="px-4 py-3">Cost</th>
            <th className="px-4 py-3">Savings</th>
            <th className="px-4 py-3">Capacity</th>
            <th className="px-4 py-3">Latency</th>
            <th className="px-4 py-3">Availability</th>
            <th className="px-4 py-3">Risk</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {scenarios.map((s) => {
            const savings = current ? current.predicted_cost - s.predicted_cost : null
            const isChosen = s.scenario_id === chosenScenarioId
            const failedChecks = s.constraint_checks.filter((c) => !c.satisfied)

            return (
              <tr key={s.scenario_id} className={isChosen ? 'bg-blue-50/60' : undefined}>
                <td className="px-4 py-3 font-medium text-slate-900">
                  {s.name}
                  {isChosen && (
                    <span className="ml-2 rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-blue-700">
                      Recommended
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 tabular-nums">{formatCurrency(s.predicted_cost)}</td>
                <td
                  className={`px-4 py-3 tabular-nums ${
                    savings === null ? 'text-slate-400' : savings > 0 ? 'text-emerald-600' : savings < 0 ? 'text-red-600' : 'text-slate-500'
                  }`}
                >
                  {savings === null ? '—' : `${savings >= 0 ? '+' : ''}${formatCurrency(savings)}`}
                </td>
                <td className="px-4 py-3 tabular-nums">{s.capacity_provisioned.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                <td className="px-4 py-3 tabular-nums">{s.latency_ms.toFixed(1)} ms</td>
                <td className="px-4 py-3 tabular-nums">{(s.availability * 100).toFixed(3)}%</td>
                <td className="px-4 py-3">
                  {s.constraints_satisfied ? (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                      Low
                    </span>
                  ) : (
                    <span
                      className="cursor-help rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700"
                      title={failedChecks.map((c) => c.description).join('; ')}
                    >
                      High ({failedChecks.length})
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
