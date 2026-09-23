const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Render's free tier sleeps the backend after ~15 min idle; the first
// request after that can take 30-50s to wake it. FIRST_ATTEMPT_TIMEOUT_MS
// distinguishes "slow because asleep" from "genuinely broken" quickly, then
// RETRY_TIMEOUT_MS gives the retry enough room to outlast a real cold start.
const FIRST_ATTEMPT_TIMEOUT_MS = 12_000
const RETRY_TIMEOUT_MS = 55_000

type WakingListener = (waking: boolean) => void
const wakingListeners = new Set<WakingListener>()

function setWaking(waking: boolean) {
  for (const listener of wakingListeners) listener(waking)
}

/** Subscribe to "the API might be waking up from a cold start" state.
 * Returns an unsubscribe function. Used by <ColdStartBanner />. */
export function onWakingChange(listener: WakingListener): () => void {
  wakingListeners.add(listener)
  return () => wakingListeners.delete(listener)
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

function isTimeoutOrNetworkError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError' ? true : err instanceof TypeError
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`
  const fetchInit: RequestInit = {
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  }

  let response: Response
  try {
    response = await fetchWithTimeout(url, fetchInit, FIRST_ATTEMPT_TIMEOUT_MS)
  } catch (err) {
    if (!isTimeoutOrNetworkError(err)) throw err
    // Likely a sleeping free-tier instance rather than a real failure —
    // retry once with a much longer timeout, and tell the UI so it can
    // show a "waking up the server" state instead of a bare loading spinner.
    setWaking(true)
    try {
      response = await fetchWithTimeout(url, fetchInit, RETRY_TIMEOUT_MS)
    } finally {
      setWaking(false)
    }
  }

  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      // ignore — use statusText
    }
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  return response.json() as Promise<T>
}

export function apiGet<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const query = params
    ? '?' +
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : ''
  return request<T>(`${path}${query && query !== '?' ? query : ''}`)
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
}

export function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>(path, { method: 'POST', body: form })
}

export { API_BASE_URL }
