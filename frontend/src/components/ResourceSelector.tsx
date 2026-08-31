import { fetchResources } from '../api/endpoints'
import { useApi } from '../hooks/useApi'
import { useAppContext } from '../context/AppContext'
import { LoadingState, ErrorState } from './StatusStates'

interface ResourceSelectorProps {
  service?: string
  label?: string
}

export function ResourceSelector({ service, label = 'Resource' }: ResourceSelectorProps) {
  const { provider, resourceId, setResourceId } = useAppContext()
  const { data, loading, error } = useApi(() => fetchResources(provider, service), [provider, service])

  if (loading) return <LoadingState label="Loading resources…" />
  if (error) return <ErrorState message={error} />

  const resources = data?.resources ?? []

  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <select
        className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none"
        value={resourceId}
        onChange={(e) => setResourceId(e.target.value)}
      >
        <option value="">Select a resource…</option>
        {resources.map((r) => (
          <option key={r.resource_id} value={r.resource_id}>
            {r.resource_id} — {r.service} ({r.region})
          </option>
        ))}
      </select>
    </label>
  )
}
