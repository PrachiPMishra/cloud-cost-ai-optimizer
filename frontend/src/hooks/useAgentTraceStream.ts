import { useEffect, useState } from 'react'
import { agentTraceStreamUrl } from '../api/endpoints'
import type { AgentEventOut, AgentTraceStreamChunk } from '../api/types'

/** Tails GET /api/agent-trace/{sessionId} — real agent_events rows as
 * they're committed, not a re-derived approximation. Works identically
 * whether the session is still running (events keep arriving) or already
 * finished (existing events drain immediately, then the stream idles out
 * and closes on its own). */
export function useAgentTraceStream(sessionId: string | null) {
  const [events, setEvents] = useState<AgentEventOut[]>([])
  const [connected, setConnected] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // No session selected: nothing to subscribe to. The stale values from a
    // previous session (if any) are masked in the returned object below
    // rather than reset here — no need to touch state just to hide it.
    if (!sessionId) return

    const controller = new AbortController()

    async function run() {
      try {
        const response = await fetch(agentTraceStreamUrl(sessionId!), { signal: controller.signal })
        if (!response.ok || !response.body) {
          throw new Error(`Trace stream failed to start (HTTP ${response.status})`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        setConnected(true)

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { value, done: streamDone } = await reader.read()
          if (streamDone) break
          buffer += decoder.decode(value, { stream: true })

          const parts = buffer.split('\n\n')
          buffer = parts.pop() ?? ''

          for (const part of parts) {
            const line = part.trim()
            if (!line.startsWith('data:')) continue
            const jsonText = line.slice(5).trim()
            if (!jsonText) continue
            const chunk = JSON.parse(jsonText) as AgentTraceStreamChunk

            if ('_meta' in chunk) {
              if (chunk._meta.event === 'error') setError(chunk._meta.error ?? 'Trace stream error')
              continue
            }
            setEvents((prev) => [...prev, chunk.event])
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setError(err instanceof Error ? err.message : 'Trace stream failed')
        }
      } finally {
        setConnected(false)
        setDone(true)
      }
    }

    run()

    // Runs when this session's subscription is torn down — either because
    // sessionId is about to change (React always cleans up the previous
    // effect before running the next one, so this clears the old session's
    // data at the exact same point a reset-at-effect-start would have) or on
    // unmount.
    return () => {
      controller.abort()
      setEvents([])
      setDone(false)
      setError(null)
    }
  }, [sessionId])

  if (!sessionId) {
    return { events: [], connected: false, done: false, error: null }
  }
  return { events, connected, done, error }
}
