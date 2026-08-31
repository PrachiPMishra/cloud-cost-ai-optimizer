import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

interface UseApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

/** Runs `fetcher` whenever `deps` change; skips entirely if `enabled` is false. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[], enabled = true): UseApiState<T> & { reload: () => void } {
  const [state, setState] = useState<UseApiState<T>>({ data: null, loading: enabled, error: null })
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, loading: false, error: null })
      return
    }
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fetcherRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Request failed'
        setState({ data: null, loading: false, error: message })
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, reloadToken, ...deps])

  const reload = useCallback(() => setReloadToken((t) => t + 1), [])

  return { ...state, reload }
}
