import { useState, type FormEvent } from 'react'
import { ArrowRight, BriefcaseBusiness, Clock3, Luggage, Plane, RotateCcw, Sparkles } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'
import { conciergeService } from '../services/conciergeService'
import type { FlightOption, FlightSearchRequest } from '../types/travel'
import { formatMoney } from '../utils/format'
import { arrivalDayOffset, formatWallClock, todayDateOnly } from '../utils/dates'

const cityOptions = ['Bengaluru', 'Chennai', 'Delhi', 'Hyderabad', 'Kolkata', 'Mumbai', 'New Delhi', 'Jaipur', 'Lucknow', 'Udaipur', 'Colombo', 'Kathmandu', 'Bangkok', 'Singapore', 'Dubai']

export default function FlightSearchPage({ onSelectFlight }: { onSelectFlight: (flight: FlightOption) => void }) {
  const { language, t } = useLanguage()
  const [request, setRequest] = useState<FlightSearchRequest>({ originCity: '', destinationCity: '', departureDate: '2026-11-16', passengers: 2, cabinClass: 'economy', currency: 'INR' })
  const [results, setResults] = useState<FlightOption[]>([])
  const [otherDates, setOtherDates] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState('')

  const today = todayDateOnly()
  const datePast = !!request.departureDate && request.departureDate < today

  async function search(event?: FormEvent, override?: Partial<FlightSearchRequest>) {
    event?.preventDefault()
    const query = { ...request, ...override }
    if (override) setRequest(query)
    if (query.departureDate && query.departureDate < todayDateOnly()) return
    setLoading(true)
    setOtherDates([])
    setError('')
    setSearched(true)
    try {
      const found = await conciergeService.searchFlights(query, language.tag)
      setResults(found.flights)
      setOtherDates(found.otherDates)
    } catch (cause) {
      setResults([])
      setError(cause instanceof Error ? cause.message : t('flight.searchError'))
    } finally {
      setLoading(false)
    }
  }

  const update = <K extends keyof FlightSearchRequest>(key: K, value: FlightSearchRequest[K]) => setRequest((current) => ({ ...current, [key]: value }))

  return <section className="flight-search-section" id="flights" aria-labelledby="flight-title">
    <div className="flight-section-heading"><div><span className="eyebrow small-eyebrow"><span className="eyebrow-line" /> {t('flight.eyebrow')}</span><h2 id="flight-title">{t('flight.title')}</h2><p>{t('flight.intro')}</p></div><span className="flight-heading-mark"><Plane size={20} /></span></div>
    <form className="flight-search-form" onSubmit={search}>
      <label className="flight-input"><span>{t('flight.from')}</span><input required list="flight-cities" value={request.originCity} onChange={(event) => update('originCity', event.target.value)} placeholder={t('flight.fromPlaceholder')} /></label>
      <button className="flight-swap" type="button" aria-label={t('flight.swap')} title={t('flight.swap')} onClick={() => setRequest((current) => ({ ...current, originCity: current.destinationCity, destinationCity: current.originCity }))}><RotateCcw size={15} /></button>
      <label className="flight-input"><span>{t('flight.to')}</span><input required list="flight-cities" value={request.destinationCity} onChange={(event) => update('destinationCity', event.target.value)} placeholder={t('flight.toPlaceholder')} /></label>
      <datalist id="flight-cities">{cityOptions.map((city) => <option key={city} value={city} />)}</datalist>
      <label className="flight-input"><span>{t('flight.departure')}</span><input required type="date" min={today} aria-invalid={datePast} aria-describedby={datePast ? 'flight-date-error' : undefined} value={request.departureDate} onChange={(event) => update('departureDate', event.target.value)} /></label>
      <label className="flight-input"><span>{t('flight.passengers')}</span><select value={request.passengers} onChange={(event) => update('passengers', Number(event.target.value))}>{Array.from({ length: 9 }, (_, i) => i + 1).map((count) => <option key={count} value={count}>{count}</option>)}</select></label>
      <label className="flight-input"><span>{t('flight.cabin')}</span><select value={request.cabinClass} onChange={(event) => update('cabinClass', event.target.value as FlightSearchRequest['cabinClass'])}><option value="economy">{t('flight.economy')}</option><option value="business">{t('flight.business')}</option><option value="first">{t('flight.first')}</option></select></label>
      <button className="flight-search-button" type="submit" disabled={loading || datePast}>{loading ? <span className="spinner" /> : <><Plane size={16} /> {t('flight.search')}</>}</button>
      {datePast && <p id="flight-date-error" className="date-order-error" role="alert">{t('flight.datePast')}</p>}
    </form>
    {conciergeService.isMock && <p className="flight-preview-note"><Sparkles size={13} /> {t('flight.previewNote')}</p>}
    {error && <div className="flight-empty" role="alert">{error}</div>}
    {loading && <div className="flight-empty"><span className="spinner dark-spinner" /> {t('flight.loading')}</div>}
    {!loading && searched && !error && results.length === 0 && <div className="flight-empty"><Plane size={20} /><div><strong>{t('flight.emptyTitle')}</strong><span>{conciergeService.isMock ? t('flight.mockEmpty') : t('flight.emptyHelp')}</span>{!!otherDates.length && <div className="flight-other-dates"><span>{t('flight.otherDates')}</span>{otherDates.map((day) => <button key={day} type="button" onClick={() => search(undefined, { departureDate: day })}>{new Intl.DateTimeFormat(language.tag, { day: 'numeric', month: 'short' }).format(new Date(`${day}T00:00:00`))}</button>)}</div>}</div></div>}
    {!!results.length && <div className="flight-results" aria-live="polite">{results.map((flight) => <FlightCard key={flight.fareId} flight={flight} language={language.tag} onSelect={() => onSelectFlight(flight)} t={t} />)}</div>}
  </section>
}

function FlightCard({ flight, language, onSelect, t }: { flight: FlightOption; language: string; onSelect: () => void; t: (key: string) => string }) {
  // Each airport's local wall-clock time, read from the timestamp itself (never the browser's zone).
  const departs = flight.departsAtLocal ?? flight.departsAt
  const arrives = flight.arrivesAtLocal ?? flight.arrivesAt
  const nextDays = flight.arrivalDayOffset ?? arrivalDayOffset(departs, arrives)
  const duration = `${Math.floor(flight.durationMinutes / 60)}h ${flight.durationMinutes % 60}m`
  return <article className="flight-result-card">
    <div className="flight-airline"><span className="airline-logo"><Plane size={17} /></span><div><strong>{flight.airlineName}</strong><small>{flight.flightNumber} · {flight.fareClass}</small></div></div>
    <div className="flight-route"><div><strong>{formatWallClock(departs, language)}</strong><span>{flight.originCode}</span><small>{flight.originCity}</small></div><div className="flight-duration"><span>{duration}</span><i /><small>{flight.stops === 0 ? t('flight.nonstop') : t('flight.stops').replace('{count}', String(flight.stops))}</small></div><div><strong>{formatWallClock(arrives, language)}{nextDays > 0 && <sup className="flight-next-day" title={t('flight.nextDay')} aria-label={t('flight.nextDay')}>+{nextDays}</sup>}</strong><span>{flight.destinationCode}</span><small>{flight.destinationCity}</small></div></div>
    <div className="flight-fare"><div><strong>{formatMoney(flight.price, flight.currency)}</strong><small>{flight.seatsAvailable} {t('flight.seatsLeft')}</small>{flight.localPrice && flight.localCurrency && flight.localCurrency !== flight.currency && <small className="local-price">≈ {formatMoney(flight.localPrice, flight.localCurrency)} {t('price.local')}</small>}</div><button type="button" onClick={onSelect}>{t('flight.select')} <ArrowRight size={14} /></button></div>
    <div className="flight-perks"><span><Luggage size={13} /> {flight.baggageKg} kg {t('flight.checkedBag')}</span><span><BriefcaseBusiness size={13} /> {flight.cabinClass}</span><span><Clock3 size={13} /> {flight.refundable ? t('flight.refundable') : t('flight.nonRefundable')}</span></div>
  </article>
}
