import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useAppContext } from '../context/AppContext'
import { useCurrency } from '../context/CurrencyContext'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/forecast', label: 'Forecast' },
  { to: '/cost-analysis', label: 'Cost Analysis' },
  { to: '/optimization', label: 'Optimization' },
  { to: '/what-if', label: 'What-If Simulator' },
  { to: '/agent-trace', label: 'Agent Trace' },
  { to: '/settings', label: 'Settings' },
]

export function Layout({ children }: { children: ReactNode }) {
  const { provider, setProvider } = useAppContext()
  const { currency, setCurrency } = useCurrency()

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-5">
          <div className="text-lg font-bold text-slate-900">CloudPilot</div>
          <div className="text-xs text-slate-500">FinOps dashboard</div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  isActive ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-100'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-slate-500">Provider</span>
            <input
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            />
          </label>
        </div>
        <div className="border-t border-slate-200 p-3">
          <span className="mb-1 block text-xs font-medium text-slate-500">Currency</span>
          <div className="flex overflow-hidden rounded-md border border-slate-300 text-xs font-medium">
            {(['USD', 'INR'] as const).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setCurrency(c)}
                aria-pressed={currency === c}
                className={`flex-1 px-2 py-1.5 transition-colors ${
                  currency === c ? 'bg-blue-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-100'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto p-8">{children}</main>
    </div>
  )
}
