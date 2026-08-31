interface StatCardProps {
  label: string
  value: string
  sublabel?: string
  tone?: 'default' | 'positive' | 'negative'
}

const toneClasses: Record<NonNullable<StatCardProps['tone']>, string> = {
  default: 'text-slate-900',
  positive: 'text-emerald-600',
  negative: 'text-red-600',
}

export function StatCard({ label, value, sublabel, tone = 'default' }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClasses[tone]}`}>{value}</div>
      {sublabel && <div className="mt-1 text-xs text-slate-400">{sublabel}</div>}
    </div>
  )
}
