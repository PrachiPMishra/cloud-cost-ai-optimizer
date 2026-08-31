import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchAgentSessions } from '../api/endpoints'
import { useApi } from '../hooks/useApi'
import { useAgentTraceStream } from '../hooks/useAgentTraceStream'
import { LoadingState, ErrorState, EmptyState } from '../components/StatusStates'

export function AgentTracePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const sessionIdFromUrl = searchParams.get('session_id') ?? ''
  const [selected, setSelected] = useState(sessionIdFromUrl)

  const sessions = useApi(() => fetchAgentSessions(20), [])
  const trace = useAgentTraceStream(selected !== '' ? selected : null)

  function select(id: string) {
    setSelected(id)
    setSearchParams({ session_id: id })
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Agent Trace</h1>
        <p className="text-sm text-slate-500">
          Every tool call an agent made — agent, tool, input, output, latency, status — streamed live from{' '}
          <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">agent_events</code> as it's committed. This is
          the audit trail behind "agents call tools for every number."
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Recent sessions</h2>
            <button onClick={() => sessions.reload()} className="text-xs text-blue-600 hover:underline">
              Refresh
            </button>
          </div>
          {sessions.loading && <LoadingState label="Loading sessions…" />}
          {sessions.error && <ErrorState message={sessions.error} />}
          {sessions.data && sessions.data.sessions.length === 0 && (
            <EmptyState message="No agent sessions yet — run an optimization first." />
          )}
          <ul className="flex flex-col gap-1">
            {sessions.data?.sessions.map((s) => (
              <li key={s.session_id}>
                <button
                  onClick={() => select(s.session_id)}
                  className={`w-full rounded-md px-3 py-2 text-left text-xs ${
                    selected === s.session_id ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  <div className="truncate font-mono">{s.session_id.slice(0, 8)}…</div>
                  <div className="text-slate-400">
                    {s.event_count} events · {new Date(s.started_at).toLocaleString()}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          {selected === '' && <EmptyState message="Select a session on the left to view its trace." />}

          {selected !== '' && (
            <div className="mb-3 flex items-center gap-2 text-xs">
              <span
                className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 font-medium ${
                  trace.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${trace.connected ? 'animate-pulse bg-emerald-500' : 'bg-slate-400'}`} />
                {trace.connected ? 'Live' : trace.done ? 'Stream closed' : 'Connecting…'}
              </span>
              <span className="text-slate-400">{trace.events.length} events so far</span>
            </div>
          )}

          {trace.error && <ErrorState message={trace.error} />}

          {selected !== '' && trace.events.length === 0 && !trace.done && (
            <LoadingState label="Waiting for the first tool call…" />
          )}

          {selected !== '' && trace.events.length === 0 && trace.done && !trace.error && (
            <EmptyState message="No tool calls were logged for this session." />
          )}

          <div className="flex flex-col gap-3">
            {trace.events.map((e) => (
              <details key={e.id} className="rounded-lg border border-slate-200 p-3">
                <summary className="flex cursor-pointer items-center justify-between text-sm">
                  <span>
                    <span className="font-semibold text-slate-900">{e.agent_name}</span>
                    <span className="mx-2 text-slate-400">→</span>
                    <span className="font-mono text-slate-700">{e.tool_name ?? e.event_type}</span>
                  </span>
                  <span className="flex items-center gap-3 text-xs text-slate-400">
                    <span
                      className={`rounded-full px-2 py-0.5 font-medium ${
                        e.output?.status === 'success' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                      }`}
                    >
                      {e.output?.status ?? 'unknown'}
                    </span>
                    <span>{e.latency_ms} ms</span>
                    <span>{new Date(e.created_at).toLocaleTimeString()}</span>
                  </span>
                </summary>
                <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Input</div>
                    <pre className="max-h-64 overflow-auto rounded-md bg-slate-50 p-2 text-xs">
                      {JSON.stringify(e.input, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Output</div>
                    <pre className="max-h-64 overflow-auto rounded-md bg-slate-50 p-2 text-xs">
                      {JSON.stringify(e.output, null, 2)}
                    </pre>
                  </div>
                </div>
              </details>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
