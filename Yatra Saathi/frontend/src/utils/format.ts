import { formatDateOnly } from './dates'

export function formatMoney(amount: string, currency: string) {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(amount)
  if (!match) return `${currency} ${amount}`
  const [, sign, whole, fraction = ''] = match
  const groupedWhole = new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 0 }).format(BigInt(whole))
  return `${sign}${groupedWhole}${fraction ? `.${fraction.padEnd(2, '0')}` : ''}`
}

export function subtractMoney(...amounts: string[]) {
  const paise = amounts.map(decimalToMinorUnits)
  const result = paise.slice(1).reduce((value, current) => value - current, paise[0] ?? 0n)
  const sign = result < 0n ? '-' : ''
  const absolute = result < 0n ? -result : result
  return `${sign}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`
}

export function sumMoney(amounts: string[]) {
  const total = amounts.map(decimalToMinorUnits).reduce((sum, value) => sum + value, 0n)
  return minorUnitsToDecimal(total)
}

export function decimalToMinorUnits(amount: string) {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(amount)
  if (!match) throw new Error(`Invalid decimal money value: ${amount}`)
  const [, sign, whole, fraction = ''] = match
  const value = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  return sign === '-' ? -value : value
}

export function minorUnitsToDecimal(value: bigint) {
  const sign = value < 0n ? '-' : ''
  const absolute = value < 0n ? -value : value
  return `${sign}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`
}

export function formatShortDate(date: string, locale = 'en-IN') {
  if (!date) return 'Choose dates'
  return formatDateOnly(date, locale)
}
