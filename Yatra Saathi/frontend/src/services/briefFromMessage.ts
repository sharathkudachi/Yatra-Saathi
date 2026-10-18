import type { TripRequest } from '../types/travel'

// Live mode: a chat message that states a destination, dates, guests or budget updates the
// trip brief *before* it is sent. The brief's budget becomes the session's hard spend cap
// (the agent may only lower it), so without this "under ₹60,000" in chat would be silently
// capped by whatever the brief said. The rules mirror the agent's own extraction
// (ai/travel_agent/extraction.py) so both sides read a message the same way.

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const MONTH_RE = '(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?'
const NUMBER_WORDS: Record<string, number> = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9 }
const PEOPLE_RE = '(people|persons?|adults?|trav[a-z]*ers?|pax|guests?|of us)'
const ORIGIN_CUE = /\b(from|dep[a-z]*r[a-z]*|leaving|starting|origin|source)\b/g
const DEST_CUE = /\b(to|in|visit|dest[a-z]*|going to|trip to|headed to|heading to)\b/g
const ALIASES: Record<string, string> = { goa: 'Panaji', delhi: 'New Delhi', bangalore: 'Bengaluru', bombay: 'Mumbai' }

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function makeDate(year: number, month: number, day: number): Date | null {
  const d = new Date(year, month - 1, day)
  return d.getMonth() === month - 1 && d.getDate() === day ? d : null
}

function withYear(month: number, day: number, year: string | undefined, today: Date): Date | null {
  if (year) return makeDate(Number(year), month, day)
  const candidate = makeDate(today.getFullYear(), month, day)
  if (candidate && candidate >= new Date(today.getFullYear(), today.getMonth(), today.getDate())) return candidate
  return makeDate(today.getFullYear() + 1, month, day)
}

function findDates(text: string, today: Date): Date[] {
  const found: Array<[number, Date]> = []
  const push = (index: number, d: Date | null) => { if (d && found.every(([at]) => Math.abs(at - index) > 3)) found.push([index, d]) }
  for (const m of text.matchAll(/\b(20\d\d)-(\d{2})-(\d{2})\b/g)) push(m.index!, makeDate(+m[1], +m[2], +m[3]))
  for (const m of text.matchAll(/\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b/g)) push(m.index!, makeDate(+m[3], +m[2], +m[1]))
  for (const m of text.matchAll(new RegExp(`\\b(?:from\\s+)?(\\d{1,2})(?:st|nd|rd|th)?\\s+(?:to|through|until|till|[-–])\\s+(\\d{1,2})(?:st|nd|rd|th)?\\s+${MONTH_RE}(?:,?\\s+(20\\d\\d))?\\b`, 'gi'))) {
    const month = MONTHS.indexOf(m[3].toLowerCase().slice(0, 3)) + 1
    const end = withYear(month, +m[2], m[4], today)
    let start = end ? makeDate(end.getFullYear(), month, +m[1]) : null
    if (start && end && start > end && !m[4]) start = makeDate(end.getFullYear() - 1, month, +m[1])
    push(m.index!, start)
    push(m.index! + m[0].lastIndexOf(m[2]), end)
  }
  for (const m of text.matchAll(new RegExp(`\\b(\\d{1,2})(?:st|nd|rd|th)?\\s+${MONTH_RE}(?:,?\\s+(20\\d\\d))?`, 'gi')))
    push(m.index!, withYear(MONTHS.indexOf(m[2].toLowerCase().slice(0, 3)) + 1, +m[1], m[3], today))
  for (const m of text.matchAll(new RegExp(`\\b${MONTH_RE}\\s+(\\d{1,2})(?:st|nd|rd|th)?\\b(?:,?\\s+(20\\d\\d))?`, 'gi')))
    push(m.index!, withYear(MONTHS.indexOf(m[1].toLowerCase().slice(0, 3)) + 1, +m[2], m[3], today))
  return found.sort((a, b) => a[0] - b[0]).map(([, d]) => d)
}

function findNights(text: string): number | null {
  const m = text.match(/\b(\d{1,2})\s*-?\s*(days?|nights?)\b/i)
  if (m) return Number(m[1])
  return /\ba week\b/i.test(text) ? 7 : null
}

function findTravellers(text: string): number | null {
  const digits = text.match(new RegExp(`\\b(\\d{1,2})\\s+${PEOPLE_RE}\\b`, 'i'))
  if (digits) return Number(digits[1])
  const words = text.match(new RegExp(`\\b(${Object.keys(NUMBER_WORDS).join('|')})\\s+${PEOPLE_RE}\\b`, 'i'))
  if (words) return NUMBER_WORDS[words[1].toLowerCase()]
  if (/\b(solo|alone|just me|by myself)\b/i.test(text)) return 1
  if (/\b(a couple|couple)\b/i.test(text)) return 2
  return null
}

function amount(number: string, scale: string | undefined): string {
  const multiplier = ({ k: 1000, thousand: 1000, l: 100000, lakh: 100000, lakhs: 100000 } as Record<string, number>)[(scale ?? '').toLowerCase()] ?? 1
  const [whole, fraction = ''] = number.replace(/,/g, '').split('.')
  const cents = (Number(whole || '0') * 100 + Number((fraction + '00').slice(0, 2))) * multiplier
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, '0')}`
}

const SYMBOLS: Record<string, string> = { '₹': 'INR', rs: 'INR', 'rs.': 'INR', inr: 'INR', rupees: 'INR', '$': 'USD', '€': 'EUR', '£': 'GBP' }

/** The currency a stated budget is in: a symbol before it, or an ISO code right after it. */
function findBudgetCurrency(text: string, supported: string[]): string | null {
  const symbol = text.match(/(₹|\$|€|£|\brs\.?|\binr\b|\brupees\b)\s*\d/i)
  if (symbol) return SYMBOLS[symbol[1].toLowerCase()] ?? null
  for (const m of text.matchAll(/\d(?:[\d,]*(?:\.\d{1,2})?)\s*(?:k|thousand|lakhs?|l)?\s*([a-z]{3})\b/gi)) {
    if (supported.includes(m[1].toUpperCase())) return m[1].toUpperCase()
  }
  return null
}

function findBudget(text: string): string | null {
  const number = '(\\d[\\d,]*(?:\\.\\d{1,2})?)\\s*(k|thousand|lakhs?|l)?\\b(?!\\s*-?\\s*(?:days?|nights?|stars?|hours?|km|people|persons?|adults?|pax|guests?|trav[a-z]*ers?)\\b)'
  const keyword = '(?:under|below|within|budget(?:\\s+(?:of|is|=))?|max(?:imum)?(?:\\s+budget)?(?:\\s+(?:of|is|=))?|up\\s*to|less than|not more than|cap(?:\\s+(?:of|is|=))?)'
  const withKeyword = text.match(new RegExp(`${keyword}\\s*:?\\s*(?:₹|\\$|€|£|rs\\.?|inr|rupees)?\\s*${number}`, 'i'))
  if (withKeyword) return amount(withKeyword[1], withKeyword[2])
  const withMark = text.match(new RegExp(`(?:₹|\\$|€|£|rs\\.?|inr|rupees)\\s*${number}`, 'i'))
  return withMark ? amount(withMark[1], withMark[2]) : null
}

function lastIndex(re: RegExp, text: string): number {
  let at = -1
  for (const m of text.matchAll(new RegExp(re.source, 'gi'))) at = m.index!
  return at
}

function findDestination(text: string, cities: string[]): string | null {
  const lowered = text.toLowerCase()
  const names = [...cities.map((c) => [c.toLowerCase(), c] as const), ...Object.entries(ALIASES)]
    .sort((a, b) => b[0].length - a[0].length)
  const mentions: Array<[number, string]> = []
  const taken: Array<[number, number]> = []
  for (const [key, city] of names) {
    for (const m of lowered.matchAll(new RegExp(`(^|[^a-z])${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=[^a-z]|$)`, 'g'))) {
      const start = m.index! + m[1].length
      const end = start + key.length
      if (taken.some(([s, e]) => s < end && start < e)) continue
      taken.push([start, end]); mentions.push([start, city])
    }
  }
  mentions.sort((a, b) => a[0] - b[0])
  let previousEnd = 0
  let fallback: string | null = null
  for (const [pos, city] of mentions) {
    // Same rule as the agent: the cue nearest the city decides its role.
    const before = lowered.slice(Math.max(previousEnd, pos - 40), pos)
    previousEnd = pos + city.length
    const origin = lastIndex(ORIGIN_CUE, before)
    const dest = lastIndex(DEST_CUE, before)
    if (dest > origin) return city
    if (origin < 0 && dest < 0 && fallback === null) fallback = city
  }
  // A lone city with no cue ("Lucknow for 2 people") is the destination.
  return mentions.length === 1 ? fallback : null
}

export function findOrigin(text: string, cities: string[]): string | null {
  const lowered = text.toLowerCase()
  const names = [...cities.map((c) => [c.toLowerCase(), c] as const), ...Object.entries(ALIASES)]
    .sort((a, b) => b[0].length - a[0].length)
  const mentions: Array<[number, string]> = []
  const taken: Array<[number, number]> = []
  for (const [key, city] of names) {
    for (const m of lowered.matchAll(new RegExp(`(^|[^a-z])${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=[^a-z]|$)`, 'g'))) {
      const start = m.index! + m[1].length
      const end = start + key.length
      if (taken.some(([s, e]) => s < end && start < e)) continue
      taken.push([start, end]); mentions.push([start, city])
    }
  }
  mentions.sort((a, b) => a[0] - b[0])
  let previousEnd = 0
  for (const [pos, city] of mentions) {
    const rawBefore = lowered.slice(Math.max(previousEnd, pos - 40), pos)
    previousEnd = pos + city.length
    const before = rawBefore.replace(/\b(starting|origin|departing|leaving)\s+in\b/gi, '$1')
    const origin = lastIndex(ORIGIN_CUE, before)
    const dest = lastIndex(DEST_CUE, before)
    if (origin >= 0 && (dest < 0 || origin > dest)) return city
  }
  // Check for "Origin → Destination" or "Origin -> Destination"
  const arrowMatch = text.match(/(?:^|[^a-z])([A-Za-z\s]+?)\s*(?:→|->)\s*([A-Za-z\s]+?)(?:[^a-z]|$)/)
  if (arrowMatch) {
    const potential = arrowMatch[1].trim()
    const match = cities.find((c) => c.toLowerCase() === potential.toLowerCase())
    if (match) return match
  }
  return null
}

/** The brief with whatever the message states applied on top. Unmentioned fields are unchanged. */
export function briefFromMessage(message: string, current: TripRequest, cities: string[], currencies: string[] = [], today = new Date()): TripRequest {
  const next = { ...current }
  const destination = findDestination(message, cities)
  if (destination) next.destination = destination

  const dates = findDates(message, today)
  const nights = findNights(message)
  if (dates.length === 1 && /\b(return\w*|back|until|till|coming home|end date)\b/i.test(message)) {
    next.endDate = iso(dates[0])
  } else if (dates.length) {
    next.startDate = iso(dates[0])
    if (dates.length > 1) next.endDate = iso(dates[1])
    else if (nights) next.endDate = iso(new Date(dates[0].getFullYear(), dates[0].getMonth(), dates[0].getDate() + nights))
  }

  const travellers = findTravellers(message)
  if (travellers && travellers >= 1 && travellers <= 12) next.travellers = travellers

  const budget = findBudget(message)
  if (budget && budget !== '0.00') {
    next.budget = budget
    // "$1,200" or "5000 AED" also sets the trip currency (the backend converts local prices into it).
    const currency = findBudgetCurrency(message, currencies.length ? currencies : ['INR', 'USD', 'EUR', 'GBP'])
    if (currency) next.currency = currency
  }
  return next
}
