import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Ban, CalendarDays, Check, ChevronRight, Download, MapPin, Plus, Search, Users, Wallet, X } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'
import { formatMoney, formatShortDate } from '../utils/format'
import { destinationPhoto } from '../services/conciergeService'
import { apiData } from '../services/apiClient'
import { authService } from '../services/authService'
import { sessionService, type AuditEvent, type AuditVerification } from '../services/sessionService'
import AuditTimeline from './AuditTimeline'
import { historyFromEvents, type HistoryMessage } from '../services/historyFromEvents'
import { bookingService } from '../services/bookingService'
import TripPackModal from './TripPackModal'

export type Trip = {
  /** 'yatra' = planned with the trip agent (sessionId set); 'account' = a trip already on the user's account. */
  source: 'yatra' | 'account'; sessionId: string | null; bookingReference: string | null
  id: string; title: string; origin: string; destination: string; startDate: string; endDate: string
  partySize: number; adults: number; children: number; status: string; currency: string; budget: string
  itineraryCost: string | null; itineraryCurrency: string | null; itineraryItemCount: number; bookingCount: number
}
type TripFilter = 'all' | 'upcoming' | 'planning' | 'past'
const isoToday = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }

// Trips come from GET /api/v1/trips, scoped to the signed-in user: the trips they plan with
// Yatra plus trips already on their account. `refreshKey` changes whenever a Yatra session
// moves on (planned, awaiting approval, booked), so the page stays current.
export default function MyTripsPage({ onPlanNew, onResume, signedIn, refreshKey }: {
  onPlanNew: (city?: string) => void; onResume: (trip: Trip) => void; signedIn: boolean; refreshKey: string
}) {
  const { language, t } = useLanguage()
  const [trips, setTrips] = useState<Trip[]>([])
  const today = isoToday()
  const [selected, setSelected] = useState<Trip | null>(null)
  const [tripPackBookingId, setTripPackBookingId] = useState<string | null>(null)
  useEffect(() => {
    if (!signedIn) { setTrips([]); return }
    let alive = true
    apiData<{ trips: Trip[] }>('/api/v1/trips', { headers: authService.authHeaders() })
      .then((data) => { if (alive) setTrips(data.trips) })
      .catch(() => { if (alive) setTrips([]) })
    return () => { alive = false }
  }, [signedIn, refreshKey])
  const continuePlanning = (trip: Trip) => trip.sessionId ? onResume(trip) : onPlanNew(trip.destination)
  // The selected Yatra trip's stored conversation (from its audit trail).
  const [history, setHistory] = useState<HistoryMessage[] | null>(null)
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([])
  const [verified, setVerified] = useState<AuditVerification | null>(null)
  useEffect(() => {
    setHistory(null); setAuditEvents([]); setVerified(null)
    if (!selected?.sessionId) return
    let alive = true
    sessionService.audit(selected.sessionId)
      .then((events) => { if (alive) { setHistory(historyFromEvents(events, t)); setAuditEvents(events) } })
      .catch(() => { if (alive) setHistory([]) })
    return () => { alive = false }
  }, [selected?.sessionId, t])
  const [filter, setFilter] = useState<TripFilter>('all')
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => trips.filter((trip) => {
    const isPast = trip.endDate < today || trip.status === 'completed'
    const isPlanning = trip.status === 'draft' || trip.status === 'planning'
    const matchesFilter = filter === 'all' || (filter === 'upcoming' && !isPast && trip.status !== 'cancelled') || (filter === 'planning' && isPlanning) || (filter === 'past' && isPast)
    const query = search.trim().toLowerCase()
    return matchesFilter && (!query || `${trip.title} ${trip.destination} ${trip.origin}`.toLowerCase().includes(query))
  }), [filter, search, trips, today])

  const nextTrip = trips.filter((trip) => trip.endDate >= today && trip.status !== 'cancelled' && trip.status !== 'completed').sort((a, b) => a.startDate.localeCompare(b.startDate))[0]
  const counts: Record<TripFilter, number> = {
    all: trips.length,
    upcoming: trips.filter((trip) => trip.endDate >= today && trip.status !== 'cancelled' && trip.status !== 'completed').length,
    planning: trips.filter((trip) => trip.status === 'draft' || trip.status === 'planning').length,
    past: trips.filter((trip) => trip.endDate < today || trip.status === 'completed').length,
  }

  function tripStatus(status: string) {
    const labels: Record<string, string> = { draft: t('trip.status.draft'), planning: t('trip.status.planning'), confirmed: t('trip.status.confirmed'), in_progress: t('trip.status.inProgress'), completed: t('trip.status.completed'), cancelled: t('trip.status.cancelled') }
    return labels[status] ?? status
  }

  return <section className="my-trips-page" id="my-trips" aria-labelledby="my-trips-title">
    <div className="my-trips-hero">
      <div className="my-trips-copy"><div className="eyebrow"><span className="eyebrow-line" /> {t('trip.eyebrow')}</div><h1 id="my-trips-title">{t('trip.title1')}<br /><em>{t('trip.title2')}</em></h1><p>{t('trip.intro')}</p></div>
      <div className="trip-next-card">
        {nextTrip ? <><div className="trip-next-image"><img src={destinationPhoto(nextTrip.destination)} alt={`${nextTrip.destination} · ${t('trip.destinationPhoto')}`} /><span>{t('trip.upNext')}</span></div><div className="trip-next-copy"><span className="mini-label">{t('trip.nextJourney')}</span><h3>{nextTrip.destination}</h3><p><CalendarDays size={13} /> {formatShortDate(nextTrip.startDate, language.tag)} – {formatShortDate(nextTrip.endDate, language.tag)}</p><button onClick={() => setSelected(nextTrip)}>{t('trip.openTrip')} <ArrowRight size={14} /></button></div></> : <div className="trip-next-empty"><span className="mini-label">{t('trip.nextJourney')}</span><h3>{t('trip.noUpcoming')}</h3><button onClick={() => onPlanNew()}>{t('trip.planNew')} <ArrowRight size={14} /></button></div>}
      </div>
    </div>

    {!signedIn && <div className="trip-preview-note"><span className="trip-preview-dot" /><strong>{t('trip.previewLabel')}</strong><span>{t('trip.signInToSee')}</span></div>}

    <div className="trip-section-heading"><div><span className="mini-label">{t('trip.workspace')}</span><h2>{t('trip.allTitle')}</h2></div><button className="trip-new-button" onClick={() => onPlanNew()}><Plus size={15} /> {t('trip.planNew')}</button></div>

    <div className="trip-tools"><div className="trip-filters" role="tablist" aria-label={t('trip.filterLabel')}>
      {(['all', 'upcoming', 'planning', 'past'] as TripFilter[]).map((item) => <button key={item} role="tab" aria-selected={filter === item} className={filter === item ? 'selected' : ''} onClick={() => setFilter(item)}>{t(`trip.filter.${item}`)} <span>{counts[item]}</span></button>)}
    </div><label className="my-trips-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('trip.search')} aria-label={t('trip.search')} /></label></div>

    {filtered.length ? <div className="trip-card-grid">{filtered.map((trip) => {
      const planning = trip.status === 'draft' || trip.status === 'planning'
      return <article className="saved-trip-card" key={trip.id}>
        <button className="saved-trip-cover" onClick={() => setSelected(trip)} aria-label={`${t('trip.openTrip')} ${trip.destination}`}><img src={destinationPhoto(trip.destination)} alt={`${trip.destination} · ${t('trip.destinationPhoto')}`} loading="lazy" /><span className={`trip-status ${trip.status}`}>{tripStatus(trip.status)}</span><span className="saved-trip-city"><MapPin size={13} /> {trip.destination}</span></button>
        <div className="saved-trip-body"><div className="saved-trip-title"><div><span>{trip.title}</span><h3>{trip.origin ? <>{trip.origin}<ChevronRight size={15} /> {trip.destination}</> : trip.destination}</h3></div><button className="trip-more-button" onClick={() => setSelected(trip)} aria-label={t('trip.openTrip')}><ChevronRight size={17} /></button></div>
          <div className="saved-trip-meta"><span><CalendarDays size={13} /> {formatShortDate(trip.startDate, language.tag)} – {formatShortDate(trip.endDate, language.tag)}</span><span><Users size={13} /> {trip.partySize} {t('trip.travellers')}</span></div>
          <div className="saved-trip-foot"><div className="saved-trip-budget"><span><Wallet size={13} /> {t('trip.budget')}</span><strong>{formatMoney(trip.budget, trip.currency)}</strong></div><button onClick={() => planning ? continuePlanning(trip) : setSelected(trip)}>{planning ? t('trip.continuePlanning') : t('trip.viewDetails')} <ArrowRight size={14} /></button></div>
        </div>
      </article>
    })}</div> : <div className="trip-empty"><span className="trip-empty-icon"><MapPin size={19} /></span><h3>{t('trip.emptyTitle')}</h3><p>{t('trip.emptyHelp')}</p><button onClick={() => onPlanNew()}>{t('trip.planNew')} <ArrowRight size={14} /></button></div>}

    <p className="trip-page-footnote">{t('trip.dataFootnote')}</p>

    {selected && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null) }}><section className="trip-detail-modal" role="dialog" aria-modal="true" aria-labelledby="trip-detail-title">
      <button className="modal-close" aria-label={t('trip.close')} onClick={() => setSelected(null)}><X size={19} /></button><div className="trip-detail-image"><img src={destinationPhoto(selected.destination)} alt={`${selected.destination} · ${t('trip.destinationPhoto')}`} /><span className={`trip-status ${selected.status}`}>{tripStatus(selected.status)}</span></div>
      <div className="trip-detail-content"><span className="mini-label">{t('trip.details')}</span><h2 id="trip-detail-title">{selected.title}</h2><p className="trip-detail-route"><MapPin size={14} /> {selected.origin || t('trip.originUnknown')} <ArrowRight size={13} /> {selected.destination}</p>
        <div className="trip-detail-facts"><span><CalendarDays size={14} /> {formatShortDate(selected.startDate, language.tag)} – {formatShortDate(selected.endDate, language.tag)}</span><span><Users size={14} /> {selected.partySize} {t('trip.travellers')}</span><span><Wallet size={14} /> {t('trip.budget')}: {formatMoney(selected.budget, selected.currency)}</span><span><Check size={14} /> {selected.itineraryItemCount} {t('trip.itineraryItems')}</span></div>
        {selected.bookingReference && <p className="trip-detail-booking">{t('trip.bookingRef').replace('{reference}', selected.bookingReference)}</p>}
        {selected.source === 'yatra' && <p className="trip-detail-source">{t('trip.plannedWithYatra')}</p>}
        {selected.sessionId && <div className="trip-history"><strong>{t('trip.history')}</strong>
          {history === null ? <p className="trip-history-empty">{t('trip.historyLoading')}</p>
            : history.length ? <ol>{history.map((m, i) => <li key={i} className={`trip-history-${m.role}`}><span>{m.role === 'user' ? t('trip.historyYou') : 'Yatra Saathi'} · {new Intl.DateTimeFormat(language.tag, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(m.at))}</span><p>{m.content}</p></li>)}</ol>
              : <p className="trip-history-empty">{t('trip.historyEmpty')}</p>}
        </div>}
        {selected.sessionId && auditEvents.length > 0 && <div className="trip-audit"><strong>{t('audit.title')}</strong>
          <p className="trip-audit-note">{t('audit.note')}</p>
          <AuditTimeline events={auditEvents} currency={selected.currency} />
          <button type="button" className="text-button" onClick={() => void sessionService.verifyAudit(selected.sessionId!).then(setVerified).catch(() => undefined)}>{t('session.verify')}</button>
          {verified && <span className={verified.ok ? 'verified' : 'unverified'}>{verified.ok ? t('session.verified') : `${t('session.unverified')} ${verified.issues.join('; ')}`}</span>}
        </div>}
        <div className="trip-detail-itinerary"><strong>{t('trip.itineraryPreview')}</strong><p>{selected.itineraryCost && selected.itineraryCurrency ? `${t('trip.estimatedPlan')}: ${formatMoney(selected.itineraryCost, selected.itineraryCurrency)} · ` : ''}{selected.bookingCount} {t('trip.bookingRecords')}</p></div>
        {selected.bookingReference && (
          <div className="trip-booking-management-actions" style={{ display: 'flex', gap: '8px', margin: '14px 0', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="text-button"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 12px', border: '1px solid var(--border-color, #cbd5e1)', borderRadius: '6px' }}
              onClick={() => setTripPackBookingId(selected.id)}
            >
              <Download size={14} /> View Demo Trip Pack
            </button>
            {selected.status !== 'cancelled' && (
              <button
                type="button"
                className="text-button"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 12px', color: '#dc2626', border: '1px solid #fca5a5', borderRadius: '6px' }}
                onClick={async () => {
                  if (window.confirm('Cancel this demo reservation? This will safely release all inventory holds.')) {
                    try {
                      await bookingService.cancelBooking(selected.id, 'User cancelled from My Trips')
                      setSelected({ ...selected, status: 'cancelled' })
                      const res = await apiData<{ trips: Trip[] }>('/api/v1/trips', { headers: authService.authHeaders() })
                      setTrips(res.trips)
                    } catch (e: any) {
                      alert(e?.message || 'Cancellation failed')
                    }
                  }
                }}
              >
                <Ban size={14} /> Cancel Demo Reservation
              </button>
            )}
          </div>
        )}
        <button className="modal-primary" onClick={() => { setSelected(null); if (selected.status === 'draft' || selected.status === 'planning') continuePlanning(selected); else onPlanNew(selected.destination) }}>{selected.status === 'draft' || selected.status === 'planning' ? t('trip.continuePlanning') : t('trip.planAnother')} <ArrowRight size={15} /></button>
      </div>
    </section></div>}
    {tripPackBookingId && (
      <TripPackModal
        bookingId={tripPackBookingId}
        onClose={() => setTripPackBookingId(null)}
      />
    )}
  </section>
}
