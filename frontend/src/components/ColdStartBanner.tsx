import { useEffect, useState } from 'react'
import { onWakingChange } from '../api/client'

/** Shown whenever the API client is retrying a request after an initial
 * timeout — the most likely cause on a deployed instance is Render's free
 * tier waking up from an idle sleep, which can take 30-50s. Mounted once in
 * Layout so it's visible regardless of which page triggered the request. */
export function ColdStartBanner() {
  const [waking, setWaking] = useState(false)

  useEffect(() => onWakingChange(setWaking), [])

  if (!waking) return null

  return (
    <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
      <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
      Waking up the server — this can take up to a minute on the free tier…
    </div>
  )
}
