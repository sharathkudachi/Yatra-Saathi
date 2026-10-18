// Trip dates are calendar days, exchanged with the backend as 'YYYY-MM-DD' strings.
// They are compared as strings and built from local date parts at noon -- never through
// toISOString() or Date.parse('YYYY-MM-DD'), which read the day in UTC and can move it by one.
// Flight timestamps carry their own offset ('2026-11-09T22:40:00+05:30'); their wall-clock time is
// read straight from the string, so it shows the airport's local time whatever the browser's zone.

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/

export function isDateOnly(value: string) {
  const match = DATE_ONLY.exec(value)
  if (!match) return false
  const [year, month, day] = match.slice(1).map(Number)
  const probe = new Date(year, month - 1, day, 12)
  return probe.getFullYear() === year && probe.getMonth() === month - 1 && probe.getDate() === day
}

export function toDateOnly(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

/** A date-only string as a local Date at noon (safe from DST and offset shifts). */
export function dateOnlyToLocal(value: string) {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day, 12)
}

export function todayDateOnly(now = new Date()) {
  return toDateOnly(now)
}

export function addDays(value: string, days: number) {
  const date = dateOnlyToLocal(value)
  date.setDate(date.getDate() + days)
  return toDateOnly(date)
}

export function laterDate(a: string, b: string) {
  return a > b ? a : b
}

export type TripDateIssue = 'past' | 'order' | null

/**
 * Start = hotel check-in / outbound flight date, end = check-out / return flight date.
 * The start may be today but not earlier, and the end must be at least one day (one night) later.
 */
export function tripDateIssue(start: string, end: string, today: string): TripDateIssue {
  if (start && isDateOnly(start) && start < today) return 'past'
  if (start && end && isDateOnly(start) && isDateOnly(end) && end <= start) return 'order'
  return null
}

export function formatDateOnly(value: string, locale: string, options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }) {
  return new Intl.DateTimeFormat(locale, options).format(dateOnlyToLocal(value))
}

/** '2026-11-10T00:55:00+05:30' -> { date: '2026-11-10', hours: 0, minutes: 55 } at that offset. */
export function wallClock(timestamp: string) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/.exec(timestamp)
  if (!match) return null
  return { date: match[1], hours: Number(match[2]), minutes: Number(match[3]) }
}

/** The airport-local time of a timestamp, in the app's locale ('00:55', '12:55 am', …). */
export function formatWallClock(timestamp: string, locale: string) {
  const clock = wallClock(timestamp)
  if (!clock) return timestamp
  // Format the wall time as if it were UTC, in UTC: no browser offset is ever applied.
  const instant = new Date(Date.UTC(2000, 0, 1, clock.hours, clock.minutes))
  return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(instant)
}

/** How many local calendar days after departure a flight lands (1 = after midnight). */
export function arrivalDayOffset(departsLocal: string, arrivesLocal: string) {
  const dep = wallClock(departsLocal), arr = wallClock(arrivesLocal)
  if (!dep || !arr) return 0
  return Math.round((dateOnlyToLocal(arr.date).getTime() - dateOnlyToLocal(dep.date).getTime()) / 86_400_000)
}
