import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchSettings } from '../api/endpoints'
import { formatMoney, type DisplayCurrency } from '../lib/currency'

const STORAGE_KEY = 'cloudpilot.displayCurrency'
const DEFAULT_CURRENCY: DisplayCurrency = 'INR'

function loadStoredCurrency(): DisplayCurrency {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'USD' || stored === 'INR' ? stored : DEFAULT_CURRENCY
  } catch {
    return DEFAULT_CURRENCY
  }
}

interface CurrencyContextValue {
  currency: DisplayCurrency
  setCurrency: (c: DisplayCurrency) => void
  toggleCurrency: () => void
  /** The backend's current USD->INR display rate. Fetched once on mount
   * from GET /api/settings — never refetched by the toggle itself. */
  usdToInrRate: number
  /** Reformats an already-fetched USD figure per the current toggle.
   * Client-side only; never re-queries the backend. */
  formatCurrency: (usdAmount: number) => string
}

const CurrencyContext = createContext<CurrencyContextValue | null>(null)

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [currency, setCurrencyState] = useState<DisplayCurrency>(loadStoredCurrency)
  const [usdToInrRate, setUsdToInrRate] = useState(83.0)

  useEffect(() => {
    let cancelled = false
    fetchSettings()
      .then((settings) => {
        if (!cancelled) setUsdToInrRate(settings.usd_to_inr_rate)
      })
      .catch(() => {
        // Keep the fallback rate — a failed settings fetch shouldn't break
        // currency display, it just won't reflect the configured rate yet.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const setCurrency = useCallback((c: DisplayCurrency) => {
    setCurrencyState(c)
    try {
      localStorage.setItem(STORAGE_KEY, c)
    } catch {
      // best-effort persistence only
    }
  }, [])

  const toggleCurrency = useCallback(() => {
    setCurrency(currency === 'USD' ? 'INR' : 'USD')
  }, [currency, setCurrency])

  const formatCurrency = useCallback(
    (usdAmount: number) => formatMoney(usdAmount, currency, usdToInrRate),
    [currency, usdToInrRate],
  )

  const value = useMemo(
    () => ({ currency, setCurrency, toggleCurrency, usdToInrRate, formatCurrency }),
    [currency, setCurrency, toggleCurrency, usdToInrRate, formatCurrency],
  )

  return <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>
}

export function useCurrency() {
  const ctx = useContext(CurrencyContext)
  if (!ctx) throw new Error('useCurrency must be used within CurrencyProvider')
  return ctx
}
