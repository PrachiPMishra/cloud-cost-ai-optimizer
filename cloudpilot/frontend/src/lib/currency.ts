export type DisplayCurrency = 'USD' | 'INR'

/**
 * Formats an already-computed USD amount for display. This is the ONLY
 * place currency conversion happens anywhere in the frontend — every
 * number fetched from the backend is USD (see backend/app/services/
 * currency.py), and this function multiplies by the current rate purely
 * for presentation. It never feeds back into any calculation.
 */
export function formatMoney(usdAmount: number, currency: DisplayCurrency, usdToInrRate: number): string {
  if (currency === 'USD') {
    return usdAmount.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
  }
  const inrAmount = usdAmount * usdToInrRate
  return inrAmount.toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
}
