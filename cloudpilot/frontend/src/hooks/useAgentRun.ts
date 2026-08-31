import { useCallback, useRef, useState } from 'react'
import { agentRunStreamUrl } from '../api/endpoints'
import type { AgentFinalState, AgentStreamChunk, Horizon } from '../api/types'

export interface AgentRunRequest {
  user_query: string
  provider: string
  resource_id: string
  usage_type: string
  horizon: Horizon
  max_latency_ms: number
  min_availability: number
  budget: number
}

export type StepStatus = 'pending' | 'running' | 'done'

export const AGENT_STEPS = [
  { key: 'planner', label: 'Planning' },
  { key: 'forecast', label: 'Forecasting usage' },
  { key: 'cost_analysis', label: 'Analyzing cost' },
  { key: 'optimization', label: 'Simulating scenarios' },
  { key: 'critic', label: 'Validating recommendation' },
  { key: 'finalize_optimization', label: 'Finalizing recommendation' },
  { key: 'report', label: 'Writing report' },
] as const

function isMeta(chunk: AgentStreamChunk): chunk is { _meta: { session_id?: string; event: 'started' | 'done' | 'error'; error?: string } } {
  return '_meta' in chunk
}

export function useAgentRun() {
  const [state, setState] = useState<AgentFinalState | null>(null)
  const [completedSteps, setCompletedSteps] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const run = useCallback(async (request: AgentRunRequest) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState(null)
    setCompletedSteps([])
    setError(null)
    setSessionId(null)
    setLoading(true)

    try {
      const response = await fetch(agentRunStreamUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal: controller.signal,
      })
      if (!response.ok || !response.body) {
        throw new Error(`Agent run failed to start (HTTP ${response.status})`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated: AgentFinalState = { session_id: '' }

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const jsonText = line.slice(5).trim()
          if (!jsonText) continue
          const chunk = JSON.parse(jsonText) as AgentStreamChunk

          if (isMeta(chunk)) {
            if (chunk._meta.session_id) {
              accumulated.session_id = chunk._meta.session_id
              setSessionId(chunk._meta.session_id)
            }
            if (chunk._meta.event === 'error') {
              setError(chunk._meta.error ?? 'Agent run failed')
            }
            continue
          }

          const [nodeName, partial] = Object.entries(chunk)[0]
          accumulated = { ...accumulated, ...partial }
          setState({ ...accumulated })
          setCompletedSteps((prev) => (prev.includes(nodeName) ? prev : [...prev, nodeName]))
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError(err instanceof Error ? err.message : 'Agent run failed')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    setLoading(false)
  }, [])

  return { run, cancel, state, completedSteps, loading, error, sessionId }
}
