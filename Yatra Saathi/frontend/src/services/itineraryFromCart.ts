import type { ItineraryStop } from '../types/travel'
import type { Cart } from './sessionService'

// The trip agent's output is a cart of real flights and hotel nights, so the itinerary is
// built from it: departure and arrival times, check-in, each night, check-out, return flight.

export type ItineraryDay = { date: string; stops: ItineraryStop[] }
type T = (key: string) => string
const fill = (text: string, values: Record<string, string>) =>
  Object.entries(values).reduce((out, [name, value]) => out.replaceAll(`{${name}}`, value), text)

const addDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function itineraryFromCart(cart: Cart | null, t: T): ItineraryDay[] {
  if (!cart?.items.length) return []
  const byDate = new Map<string, ItineraryStop[]>()
  const add = (date: string, stop: ItineraryStop) => byDate.set(date, [...(byDate.get(date) ?? []), stop])

  const groups = new Map<string, typeof cart.items>()
  for (const item of cart.items) groups.set(item.itemGroupId, [...(groups.get(item.itemGroupId) ?? []), item])

  for (const [group, items] of groups) {
    const d = items[0].details
    if (d?.type === 'flight') {
      const day = d.departs_at.slice(0, 10)
      add(day, {
        id: `${group}-dep`, time: d.departs_at.slice(11, 16), category: 'flight',
        title: `${d.airline} ${d.flight_number}`,
        detail: `${fill(t('itinerary.flight'), { from: `${d.origin_city} (${d.origin_code})`, to: `${d.destination_city} (${d.destination_code})` })} · ${fill(t('itinerary.arrives'), { time: d.arrives_at.slice(11, 16) })}`,
      })
    } else if (d?.type === 'stay') {
      const nights = items.map((it) => it.forDate).sort()
      const first = nights[0]
      const checkout = addDays(nights[nights.length - 1], 1)
      add(first, { id: `${group}-in`, time: d.checkin_time ?? '', category: 'stay', title: fill(t('itinerary.checkIn'), { hotel: d.hotel }), detail: `${d.room} · ${d.city}` })
      for (const night of nights.slice(1)) add(night, { id: `${group}-${night}`, time: '', category: 'stay', title: fill(t('itinerary.stay'), { hotel: d.hotel }), detail: d.city })
      add(checkout, { id: `${group}-out`, time: d.checkout_time ?? '', category: 'stay', title: fill(t('itinerary.checkOut'), { hotel: d.hotel }), detail: d.address ?? d.city })
    }
  }
  // Timed stops first, in time order; untimed "night at" notes after them.
  return [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, stops]) => {
    const sorted = stops.sort((a, b) => (a.time || '99').localeCompare(b.time || '99'))
    // A flight leaving before the hotel's standard check-out time: check out first, before the flight.
    const out = sorted.find((s) => s.id.endsWith('-out'))
    const firstFlight = sorted.find((s) => s.category === 'flight')
    if (out && firstFlight && out.time && firstFlight.time && firstFlight.time < out.time) {
      const rest = sorted.filter((s) => s !== out)
      rest.splice(rest.indexOf(firstFlight), 0, { ...out, time: '', detail: `${t('itinerary.beforeFlight')} · ${out.detail}` })
      return { date, stops: rest }
    }
    return { date, stops: sorted }
  })
}
