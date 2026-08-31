import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchCostDrivers, fetchCurrentCost } from '../api/endpoints'
import { useApi } from '../hooks/useApi'
import { useAppContext } from '../context/AppContext'
import { useCurrency } from '../context/CurrencyContext'
import { ResourceSelector } from '../components/ResourceSelector'
import { LoadingState, ErrorState, EmptyState } from '../components/StatusStates'
import { StatCard } from '../components/StatCard'

const COLORS = ['#2563eb', '#7c3aed', '#0891b2', '#16a34a', '#ea580c', '#db2777']

export function CostAnalysisPage() {
  const { provider, resourceId } = useAppContext()
  const { formatCurrency } = useCurrency()
  const [topN, setTopN] = useState(5)
  const hasResource = resourceId !== ''

  const current = useApi(() => fetchCurrentCost(provider, resourceId), [provider, resourceId], hasResource)
  const drivers = useApi(
    () => fetchCostDrivers(provider, { resourceId, source: 'current', topN }),
    [provider, resourceId, topN],
    hasResource,
  )

  const totalCost = current.data ? current.data.line_items.reduce((sum, li) => sum + li.cost, 0) : 0
  const bySku = current.data
    ? Object.values(
        current.data.line_items.reduce<Record<string, { sku: string; cost: number }>>((acc, li) => {
          acc[li.sku] = acc[li.sku] ?? { sku: li.sku, cost: 0 }
          acc[li.sku].cost += li.cost
          return acc
        }, {}),
      )
    : []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Cost Analysis</h1>
        <p className="text-sm text-slate-500">Cost breakdown by usage unit and top cost drivers.</p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div className="max-w-xs">
          <ResourceSelector />
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Top N drivers</span>
          <input
            type="number"
            min={1}
            max={20}
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value) || 5)}
            className="w-24 rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
      </div>

      {!hasResource && <EmptyState message="Select a resource to analyze its cost." />}

      {hasResource && (
        <>
          {current.loading && <LoadingState label="Loading cost breakdown…" />}
          {current.error && <ErrorState message={current.error} />}

          {current.data && (
            <>
              <StatCard label="Total cost (all-time)" value={formatCurrency(totalCost)} sublabel={`${current.data.line_items.length} priced line items`} />

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <h2 className="mb-3 text-sm font-semibold text-slate-900">Breakdown by usage unit (SKU)</h2>
                  {bySku.length === 0 ? (
                    <EmptyState message="No priced usage found." />
                  ) : (
                    <ResponsiveContainer width="100%" height={260}>
                      <PieChart>
                        <Pie data={bySku} dataKey="cost" nameKey="sku" outerRadius={90}>
                          {bySku.map((_, i) => (
                            <Cell key={i} fill={COLORS[i % COLORS.length]} />
                          ))}
                        </Pie>
                        <Legend />
                        <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                      </PieChart>
                    </ResponsiveContainer>
                  )}
                </div>

                <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <h2 className="mb-3 text-sm font-semibold text-slate-900">Top cost drivers</h2>
                  {drivers.loading && <LoadingState label="Ranking drivers…" />}
                  {drivers.error && <ErrorState message={drivers.error} />}
                  {drivers.data && drivers.data.drivers.length > 0 && (
                    <ResponsiveContainer width="100%" height={260}>
                      <BarChart data={drivers.data.drivers} layout="vertical" margin={{ left: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="label" tick={{ fontSize: 10 }} width={140} />
                        <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                        <Bar dataKey="cost" fill="#2563eb" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              {current.data.skipped.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700">
                  Skipped (no pricing/data): {current.data.skipped.join('; ')}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
