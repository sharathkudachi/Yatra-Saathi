import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Compass, MapPin, Search, Sparkles, X } from 'lucide-react'
import { conciergeService } from '../services/conciergeService'
import type { HotelOption, TripRequest } from '../types/travel'
import { formatMoney, formatShortDate } from '../utils/format'
import { useLanguage } from '../i18n/LanguageContext'
import { convertAmount, useCurrencies } from '../services/currencyService'

type Destination = Awaited<ReturnType<typeof conciergeService.exploreDestinations>>[number]

export default function ExplorePage({ request, onAskYatra, onPlanDestination }: { request: TripRequest; onAskYatra: (prompt: string) => void; onPlanDestination: (city: string) => void }) {
  const { language, t } = useLanguage()
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [loading, setLoading] = useState(false)
  const [region, setRegion] = useState<'all' | 'India' | 'International'>('all')
  const [currency, setCurrency] = useState('INR')
  const currencyList = useCurrencies()
  const currencies = currencyList.currencies.map((c) => c.code)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Destination | null>(null)
  const [stays, setStays] = useState<HotelOption[]>([])
  const [staysLoading, setStaysLoading] = useState(false)
  const [staysLoaded, setStaysLoaded] = useState(false)

  async function loadStays() {
    if (!selected || staysLoading || staysLoaded) return
    setStaysLoading(true)
    try {
      const items = await conciergeService.searchHotels({ ...request, destination: selected.name, currency: selected.currency, budget: '999999999999.99' }, language.tag)
      setStays(items.slice(0, 4))
    } catch {
      setStays([])
    } finally {
      setStaysLoaded(true)
      setStaysLoading(false)
    }
  }

  function openDestination(item: Destination) {
    setStays([])
    setStaysLoaded(false)
    setSelected(item)
  }

  useEffect(() => {
    let active = true
    setLoading(true)
    void conciergeService.exploreDestinations(request).then((items) => { if (active) setDestinations(items) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [request.startDate, request.endDate, request.travellers])

  const visible = useMemo(() => destinations.filter((item) => {
    const matchesRegion = region === 'all' || (region === 'India' ? item.countryCode === 'IN' : item.countryCode !== 'IN')
    return matchesRegion && item.name.toLowerCase().includes(search.trim().toLowerCase())
  }), [destinations, region, search])

  function displayPrice(item: Destination) {
    if (!item.fromPrice) return t('explore.noPrice')
    if (item.currency === currency) return `${t('explore.priceFrom')} ${formatMoney(item.fromPrice, currency)}`
    // Same indicative demo rates the backend prices trips with.
    const converted = convertAmount(item.fromPrice, item.currency, currency, currencyList)
    if (converted === null) return `${t('explore.priceAbout')} ${formatMoney(item.fromPrice, item.currency)}`
    return `${t('explore.priceAbout')} ${formatMoney(converted, currency)}`
  }

  return <section className="explore-page" id="explore" aria-labelledby="explore-title">
    <div className="explore-hero">
      <div><div className="eyebrow"><span className="eyebrow-line" /> {t('explore.eyebrow')}</div><h1 id="explore-title">{t('explore.title1')}<br /><em>{t('explore.title2')}</em></h1><p>{t('explore.intro')}</p></div>
      <div className="explore-prompt"><span className="explore-prompt-icon"><Sparkles size={18} /></span><strong>{t('explore.unsure')}</strong><p>{t('explore.unsureHelp')}</p><button onClick={() => onAskYatra(t('explore.recommendPrompt'))}>{t('explore.recommend')} <ArrowRight size={15} /></button></div>
    </div>
    <div className="explore-toolbar"><div className="explore-filters" role="group" aria-label={t('explore.filterLabel')}><button className={region === 'all' ? 'selected' : ''} onClick={() => setRegion('all')}>{t('explore.all')}</button><button className={region === 'India' ? 'selected' : ''} onClick={() => setRegion('India')}>{t('explore.india')}</button><button className={region === 'International' ? 'selected' : ''} onClick={() => setRegion('International')}>{t('explore.international')}</button></div><label className="explore-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('explore.findCity')} aria-label={t('explore.findCity')} /></label><label className="explore-currency">{t('explore.showPrices')} <select value={currency} onChange={(event) => setCurrency(event.target.value)} aria-label={t('explore.currencyLabel')}>{currencies.map((code) => <option key={code}>{code}</option>)}</select></label></div>
    <p className="explore-date-note"><Compass size={14} /> {t('explore.forDates')} {formatShortDate(request.startDate, language.tag)} – {formatShortDate(request.endDate, language.tag)} · {request.travellers} {t('search.travellers').toLowerCase()}</p>
    {currency !== 'INR' && <p className="fx-note">{t('explore.fxNote')}</p>}
    {loading ? <div className="explore-empty">{t('explore.loading')}</div> : visible.length ? <div className="destination-grid">{visible.map((item) => <article className="destination-card" key={item.name}>
      <button className="destination-photo" onClick={() => openDestination(item)} aria-label={`${t('explore.exploreStays')} ${item.name}`}><ExplorePhoto src={item.imageUrl} city={item.name} alt={`${item.name} · ${t('explore.destinationImage')}`} loading="lazy" /><span className="destination-photo-shade" /><span className="destination-place"><MapPin size={13} /> {item.name}{item.countryCode !== 'IN' && <small>{item.countryCode}</small>}</span><span className="destination-open"><ArrowRight size={16} /></span></button>
      <div className="destination-details"><div><strong>{displayPrice(item)}</strong><span>{item.hotelCount ? `${t('explore.availableStays')} · ${item.hotelCount} · ${item.currency}` : t('explore.noStays')}</span></div><button onClick={() => openDestination(item)}>{t('explore.exploreStays')} <ArrowRight size={14} /></button></div>
    </article>)}</div> : <div className="explore-empty">{t('explore.empty')}</div>}
    <div className="explore-bottom-cta"><span className="assistant-icon"><Sparkles size={18} /></span><div><strong>{t('explore.bottomTitle')}</strong><p>{t('explore.bottomHelp')}</p></div><button onClick={() => onAskYatra(t('explore.askPrompt'))}>{t('explore.ask')} <ArrowRight size={15} /></button></div>
    <p className="explore-disclaimer">{t('explore.photoNote')}</p>
    {selected && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null) }}><section className="destination-detail-modal" role="dialog" aria-modal="true" aria-labelledby="destination-detail-title">
      <button className="modal-close" aria-label={t('explore.close')} onClick={() => setSelected(null)}><X size={19} /></button>
      <div className="destination-detail-image"><ExplorePhoto src={selected.imageUrl} city={selected.name} alt={`${selected.name} · ${t('explore.destinationImage')}`} /><span>{selected.countryCode}</span></div>
      <div className="destination-detail-content"><span className="mini-label">{t('explore.cityGuide')}</span><h2 id="destination-detail-title">{selected.name}</h2><p>{selected.hotelCount ? `${t('explore.availableStays')} · ${selected.hotelCount}` : t('explore.noStays')}</p>
        <div className="destination-detail-price"><span>{t('explore.showPrices')} · {formatShortDate(request.startDate, language.tag)} – {formatShortDate(request.endDate, language.tag)}</span><strong>{displayPrice(selected)}</strong></div>
        <button className="destination-guide-ask" onClick={() => void loadStays()} disabled={staysLoading || staysLoaded}><MapPin size={15} /> {staysLoading ? t('explore.loading') : t('explore.viewStays')} <ArrowRight size={15} /></button>
        {staysLoading ? <p className="explore-stays-state">{t('explore.loading')}</p> : staysLoaded && stays.length ? <div className="explore-stay-list"><h3 className="explore-stays-heading">{t('explore.availableStays')}</h3>{stays.map((stay) => <article className="explore-stay-card" key={`${stay.hotelId}-${stay.roomTypeId}`}>
          {(stay.roomImages?.length || stay.surroundingsImages?.length) ? <div className="explore-stay-gallery">{stay.roomImages?.map((photo, i) => <ExplorePhoto key={`room-${i}`} src={photo} city={stay.roomName} alt={`${stay.roomName} · ${t('explore.roomPhoto')}`} />)}{stay.surroundingsImages?.map((photo, i) => <ExplorePhoto key={`area-${i}`} src={photo} city={selected.name} alt={`${selected.name} · ${t('explore.surroundingsPhoto')}`} />)}</div> : null}
          <div className="explore-stay-info"><div><strong>{stay.name}</strong><span>{stay.localizedRoomName ?? stay.roomName} · {(stay.localizedTags ?? stay.tags).join(' · ')}</span></div><b>{formatMoney(stay.price, stay.currency)}</b></div>
          <p className="explore-stay-description">{stay.localizedDescription ?? stay.description}</p>
          {(stay.localizedMenuItems ?? stay.menuItems)?.length ? <div className="explore-food"><strong>{t('explore.foodMenu')}</strong>{(stay.localizedMenuItems ?? stay.menuItems ?? []).map((food, i) => <span key={`${food.name}-${i}`}>{food.category ? `${food.category} · ` : ''}{food.name}{food.description ? ` — ${food.description}` : ''}{food.price && food.currency ? ` · ${formatMoney(food.price, food.currency)}` : ''}</span>)}</div> : null}
        </article>)}</div> : <p className="explore-stays-state">{t('explore.noStays')}</p>}
        <button className="destination-guide-ask" onClick={() => { setSelected(null); onAskYatra(`${t('explore.destinationPrompt')} ${selected.name}. ${t('explore.recommendPrompt')}`) }}><Sparkles size={16} /> {t('explore.askCity')} <ArrowRight size={15} /></button>
        {!staysLoaded && <p className="explore-stays-state">{t('explore.detailsOnRequest')}</p>}
        <button className="destination-guide-plan" onClick={() => { setSelected(null); onPlanDestination(selected.name) }}>{t('explore.planTo')} {selected.name} <ArrowRight size={14} /></button>
      </div>
    </section></div>}
  </section>
}

function ExplorePhoto({ src, city, alt, loading = 'eager' }: { src: string; city: string; alt: string; loading?: 'eager' | 'lazy' }) {
  const { t } = useLanguage()
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  return <div className={`explore-photo-frame ${state}`} aria-label={state === 'error' ? `${city} · ${t('explore.photoUnavailable')}` : undefined}>
    {state !== 'error' && <img src={src} alt={alt} loading={loading} onLoad={() => setState('ready')} onError={() => setState('error')} />}
    {state === 'loading' && <span className="explore-photo-skeleton" aria-hidden="true" />}
    {state === 'error' && <span className="explore-photo-fallback"><MapPin size={16} /><strong>{city}</strong><small>{t('explore.photoUnavailable')}</small></span>}
  </div>
}
