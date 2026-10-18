import { useEffect, useState } from 'react'
import { apiData } from './apiClient'

// The currencies a trip can be planned in, with the backend's indicative demo exchange rates
// (GET /api/v1/currencies). The backend prices, caps and books with these same rates, so any
// conversion shown in the UI matches what the cart will say. Rates are "INR per one unit".

export type CurrencyInfo = { code: string; name: string; symbol: string; inrPerUnit: string }
type CurrencyList = { currencies: CurrencyInfo[]; ratesAsOf: string; ratesNote: string }

// Used until the backend answers (and in preview mode): codes only, no conversion.
const FALLBACK: CurrencyList = {
  currencies: ['INR', 'USD', 'EUR', 'GBP', 'AED', 'THB', 'IDR', 'SGD', 'LKR', 'NPR'].map((code) => ({ code, name: code, symbol: '', inrPerUnit: '' })),
  ratesAsOf: '', ratesNote: '',
}

let cached: Promise<CurrencyList> | null = null

export function loadCurrencies(): Promise<CurrencyList> {
  cached ??= apiData<CurrencyList>('/api/v1/currencies').catch(() => { cached = null; return FALLBACK })
  return cached
}

export function useCurrencies(): CurrencyList {
  const [list, setList] = useState<CurrencyList>(FALLBACK)
  useEffect(() => { let alive = true; void loadCurrencies().then((next) => { if (alive) setList(next) }); return () => { alive = false } }, [])
  return list
}

/** Same rule as the backend (src/core/fx.py): amount x rate[from] / rate[to], half-up to 2 dp. */
export function convertAmount(amount: string, from: string, to: string, list: CurrencyList): string | null {
  if (from === to) return amount
  const rate = (code: string) => Number(list.currencies.find((c) => c.code === code)?.inrPerUnit || NaN)
  const value = Number(amount) * rate(from) / rate(to)
  if (!Number.isFinite(value)) return null
  return (Math.round((value + Number.EPSILON) * 100) / 100).toFixed(2)
}
