import { Check, Hotel, Plane, Star } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'
import { formatMoney } from '../utils/format'

// The trip packages Yatra offers (sent as structured options on its CLARIFICATION_REQUESTED
// event). Choosing one simply sends "Option N" as the user's next message.

type Leg = { airline: string; flight_number: string; departs_at: string; arrives_at: string; stops: number
  duration_minutes: number | null; cabin_class: string | null; from: string | null; to: string | null; refundable: boolean }
export type TripOption = {
  index: number; key: string; label: string; currency: string; total: string; subtotal: string; tax: string
  outbound: Leg; return: Leg
  hotel: { name: string; room: string; stars: number | string | null; guest_score: string | number | null
    distance_km: string | number | null; nights: number; rooms: number; total: string }
}

const fill = (text: string, values: Record<string, string | number>) =>
  Object.entries(values).reduce((out, [k, v]) => out.replaceAll(`{${k}}`, String(v)), text)

export function isTripOptions(value: unknown): value is TripOption[] {
  return Array.isArray(value) && value.every((o) => o && typeof o === 'object' && 'index' in o && 'hotel' in o && 'outbound' in o)
}

export default function TripOptions({ options, active, onChoose }: { options: TripOption[]; active: boolean; onChoose: (index: number) => void }) {
  const { language, t } = useLanguage()
  const time = (iso: string) => iso.slice(11, 16)
  const day = (iso: string) => new Intl.DateTimeFormat(language.tag, { day: 'numeric', month: 'short' }).format(new Date(`${iso.slice(0, 10)}T12:00:00`))
  const leg = (label: string, l: Leg) => {
    const mins = l.duration_minutes ?? 0
    return <div className="trip-option-leg"><Plane size={13} /><div>
      <strong>{label} · {l.airline} {l.flight_number}</strong>
      <span>{day(l.departs_at)} {time(l.departs_at)} → {time(l.arrives_at)}{l.from && l.to ? ` · ${l.from}–${l.to}` : ''}</span>
      <small>{l.stops ? fill(t('options.stops'), { count: l.stops }) : t('options.nonstop')} · {Math.floor(mins / 60)}h {mins % 60}m{l.refundable ? ` · ${t('flight.refundable')}` : ''}</small>
    </div></div>
  }
  return <div className="trip-options">
    {options.map((o) => <article className={`trip-option trip-option-${o.key.split('-')[0]}`} key={o.index}>
      <header><span className="trip-option-num">{o.index}</span><strong>{o.label}</strong><em>{formatMoney(o.total, o.currency)}</em></header>
      <small className="trip-option-tax">{t('options.totalNote')}</small>
      {leg(t('options.out'), o.outbound)}
      {leg(t('options.back'), o.return)}
      <div className="trip-option-leg"><Hotel size={13} /><div>
        <strong>{o.hotel.name}</strong>
        <span>{o.hotel.room} · {fill(t('options.nights'), { count: o.hotel.nights })}</span>
        <small>{o.hotel.stars ? <><Star size={10} /> {o.hotel.stars} · </> : null}{o.hotel.guest_score != null ? `${fill(t('options.guestScore'), { score: o.hotel.guest_score })} · ` : ''}{o.hotel.distance_km != null ? fill(t('options.fromCentre'), { km: o.hotel.distance_km }) : ''}</small>
      </div></div>
      {active && <button type="button" className="trip-option-choose" onClick={() => onChoose(o.index)}><Check size={14} /> {t('options.choose')}</button>}
    </article>)}
  </div>
}
