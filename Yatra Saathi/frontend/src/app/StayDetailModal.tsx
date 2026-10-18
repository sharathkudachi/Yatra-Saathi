import { useEffect, useState } from 'react'
import { ArrowRight, BedDouble, CalendarDays, Clock3, MapPin, Maximize2, Star, Users, X } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'
import { conciergeService } from '../services/conciergeService'
import type { HotelOption, StayDetails, StayRoom, TripRequest } from '../types/travel'
import { formatMoney, formatShortDate } from '../utils/format'

type T = (key: string) => string
const fill = (text: string, values: Record<string, string | number>) =>
  Object.entries(values).reduce((out, [name, value]) => out.replaceAll(`{${name}}`, String(value)), text)

// "Discover this stay": the hotel's details and every room for the brief's dates, straight
// from the catalog. Read-only -- booking still happens through Yatra and the Approve step.
export default function StayDetailModal({ hotel, request, onClose, onPlan }: {
  hotel: HotelOption; request: TripRequest; onClose: () => void; onPlan: () => void
}) {
  const { language, t } = useLanguage()
  const [stay, setStay] = useState<StayDetails | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setStay(null); setError('')
    conciergeService.getStay(hotel.hotelId, request)
      .then((details) => { if (alive) setStay(details) })
      .catch(() => { if (alive) setError(t('stay.loadError')) })
    return () => { alive = false }
  }, [hotel.hotelId, request.startDate, request.endDate, request.travellers, request.currency])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const info = stay?.hotel
  const bookableCount = stay?.rooms.filter((room) => room.bookable && room.fitsParty).length ?? 0
  const nightsLabel = (n: number) => `${n} ${n === 1 ? t('stay.night') : t('stay.nights')}`

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="stay-modal" role="dialog" aria-modal="true" aria-labelledby="stay-title">
      <button className="modal-close stay-close" aria-label={t('stay.close')} onClick={onClose}><X size={19} /></button>
      <div className="stay-hero">
        <img src={hotel.imageUrl} alt={fill(t('stay.photoAlt'), { city: hotel.city, hotel: hotel.name })} />
        <div className="stay-hero-copy">
          <span className="mini-label">{(info?.propertyType || hotel.tags[0] || '').toUpperCase()} · {hotel.city.toUpperCase()}</span>
          <h2 id="stay-title">{hotel.name}</h2>
          {info && <div className="stay-facts">
            {info.starRating ? <span><Star size={13} /> {fill(t('stay.star'), { count: info.starRating })}</span> : null}
            {info.guestScore != null && <span className="stay-score">{info.guestScore.toFixed(1)}<small>/10 · {fill(t('stay.reviews'), { count: info.reviewCount ?? 0 })}</small></span>}
            {info.address && <span><MapPin size={13} /> {info.address}{info.distanceToCentreKm != null ? ` · ${fill(t('stay.toCentre'), { km: info.distanceToCentreKm.toFixed(1) })}` : ''}</span>}
            {(info.checkinTime || info.checkoutTime) && <span><Clock3 size={13} /> {fill(t('stay.checkInOut'), { in: info.checkinTime ?? '—', out: info.checkoutTime ?? '—' })}</span>}
          </div>}
        </div>
      </div>

      <div className="stay-body">
        {info?.description && <p className="stay-description">{info.description}</p>}
        <div className="stay-dates"><CalendarDays size={14} /> {formatShortDate(request.startDate, language.tag)} – {formatShortDate(request.endDate, language.tag)}
          {stay && <> · {nightsLabel(stay.nights)}</>} · <Users size={14} /> {request.travellers} {request.travellers === 1 ? t('stay.guest') : t('stay.guests')}</div>

        {!stay && !error && <div className="stay-loading"><span className="spinner dark-spinner" /> {t('stay.loading')}</div>}
        {error && <div className="stay-error" role="alert">{error}</div>}
        {stay && <>
          <div className="stay-rooms-heading"><h3>{t('stay.rooms')}</h3><span>{fill(t('stay.roomsAvailable'), { count: bookableCount, total: stay.rooms.length })}</span></div>
          <div className="stay-rooms">{stay.rooms.map((room) => <RoomCard key={room.roomTypeId} room={room} nights={stay.nights} travellers={stay.travellers} language={language.tag} highlighted={room.roomTypeId === hotel.roomTypeId} t={t} nightsLabel={nightsLabel} />)}</div>
        </>}
      </div>

      <footer className="stay-footer">
        <p>{t('stay.footerNote')}{stay?.rooms.some((r) => r.localCurrency && r.localCurrency !== r.currency) ? ` ${t('price.ratesNote')}` : ''}</p>
        <button className="modal-primary" onClick={onPlan}>{t('stay.plan')} <ArrowRight size={16} /></button>
      </footer>
    </section>
  </div>
}

function unavailableText(room: StayRoom, language: string, t: T): string {
  const day = room.unavailableDetail && /^\d{4}-\d{2}-\d{2}$/.test(room.unavailableDetail) ? formatShortDate(room.unavailableDetail, language) : ''
  switch (room.unavailableCode) {
    case 'not_offered': return fill(t('stay.reason.notOffered'), { date: day })
    case 'sold_out': return fill(t('stay.reason.soldOut'), { date: day })
    case 'no_checkin': return fill(t('stay.reason.noCheckin'), { date: day })
    case 'min_stay': return fill(t('stay.reason.minStay'), { count: room.unavailableDetail ?? '' })
    case 'stay_length': return fill(t('stay.reason.stayLength'), { count: room.unavailableDetail ?? '' })
    default: return t('stay.notAvailable')
  }
}

function RoomCard({ room, nights, travellers, language, highlighted, t, nightsLabel }: {
  room: StayRoom; nights: number; travellers: number; language: string; highlighted: boolean; t: T; nightsLabel: (n: number) => string
}) {
  const status = !room.bookable ? { tone: 'off', text: unavailableText(room, language, t) }
    : !room.fitsParty ? { tone: 'warn', text: fill(t('stay.tooSmall'), { count: room.maxOccupancy, guests: travellers }) }
      : { tone: 'ok', text: fill(t('stay.left'), { count: room.availableUnits }) }
  const perNight = room.price && nights > 0 ? (Number(room.price) / nights).toFixed(2) : null
  return <article className={`stay-room ${room.bookable && room.fitsParty ? '' : 'stay-room-muted'} ${highlighted ? 'stay-room-highlight' : ''}`}>
    <div className="stay-room-main">
      <div className="stay-room-title">{highlighted && <span className="stay-room-pick">{t('stay.shownInResults')}</span>}<h4>{room.name}</h4></div>
      <div className="stay-room-specs">
        <span><Users size={13} /> {room.maxChildren
          ? `${fill(t('stay.sleeps'), { count: room.maxOccupancy })} ${fill(t('stay.sleepsDetail'), { adults: room.maxAdults, children: room.maxChildren })}`
          : fill(t('stay.sleepsAdults'), { count: room.maxOccupancy })}</span>
        {room.bedConfig && <span><BedDouble size={13} /> {fill(t('stay.bed'), { bed: room.bedConfig })}</span>}
        {room.sizeSqm ? <span><Maximize2 size={13} /> {room.sizeSqm} m²</span> : null}
        <span>{room.smokingAllowed ? t('stay.smoking') : t('stay.nonSmoking')}</span>
      </div>
      {room.nightly.length > 0 && <details className="stay-nightly"><summary>{t('stay.nightlyPrices')}</summary>
        <ul>{room.nightly.map((night) => <li key={night.date}><span>{formatShortDate(night.date, language)}</span><strong>{formatMoney(night.price, room.currency)}</strong></li>)}</ul>
      </details>}
    </div>
    <div className="stay-room-price">
      {room.price ? <><strong>{formatMoney(room.price, room.currency)}</strong>
        <small>{nightsLabel(nights)}{perNight ? ` · ${formatMoney(perNight, room.currency)}${t('stay.perNight')}` : ''}</small>
        {room.localPrice && room.localCurrency && room.localCurrency !== room.currency && <small className="local-price">≈ {formatMoney(room.localPrice, room.localCurrency)} {t('price.local')}</small>}
      </> : <strong className="stay-room-na">—</strong>}
      <span className={`stay-room-status ${status.tone}`}>{status.text}</span>
    </div>
  </article>
}
