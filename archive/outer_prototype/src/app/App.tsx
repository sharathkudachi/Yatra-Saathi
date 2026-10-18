import { useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  ArrowRight, ArrowUpRight, CalendarDays, Check, ChevronDown, CircleHelp,
  Compass, LockKeyhole, Mail, MapPin, Menu, Minus, Moon, Plus, Send, ShieldCheck, Sparkles, Sun, UserRound, Users, Wallet, X,
} from 'lucide-react'
import { conciergeService, destinationPhoto } from '../services/conciergeService'
import ExplorePage from './ExplorePage'
import MyTripsPage from './MyTripsPage'
import { useLanguage } from '../i18n/LanguageContext'
import type { BudgetSummary, HotelOption, ItineraryStop, TripRequest } from '../types/travel'
import { decimalToMinorUnits, formatMoney, formatShortDate, subtractMoney } from '../utils/format'

const initialRequest: TripRequest = {
  destination: '', startDate: '2026-11-16', endDate: '2026-11-20', travellers: 2,
  budget: '25000.00', currency: 'INR', preferences: '',
}

type ChatMessage = { role: 'assistant' | 'user'; content: string }

export default function App() {
  const { language, options: languageOptions, setLanguage, t } = useLanguage()
  const [request, setRequest] = useState(initialRequest)
  const [hotels, setHotels] = useState<HotelOption[]>([])
  const [itinerary, setItinerary] = useState<ItineraryStop[]>([])
  const [budget, setBudget] = useState<BudgetSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedHotel, setSelectedHotel] = useState<HotelOption | null>(null)
  const [holdMessage, setHoldMessage] = useState('')
  const [holding, setHolding] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [chatDraft, setChatDraft] = useState('')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([{ role: 'assistant', content: t('agent.greeting') }])
  useEffect(() => {
    setChatMessages((messages) => messages.length === 1 && messages[0].role === 'assistant' ? [{ role: 'assistant', content: t('agent.greeting') }] : messages)
  }, [language.tag, t])
  const [agentSteps, setAgentSteps] = useState<string[]>([])
  const [agentLoading, setAgentLoading] = useState(false)
  const [signInOpen, setSignInOpen] = useState(false)
  const [signInMessage, setSignInMessage] = useState('')
  const [theme, setTheme] = useState<'light' | 'dark'>(() => localStorage.getItem('yatra-theme') === 'dark' ? 'dark' : 'light')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('yatra-theme', theme)
  }, [theme])
  const itinerarySampleDate = new Date(2026, 10, 17)

  async function refreshResults(nextRequest = request) {
    setLoading(true); setError(''); setNotice('')
    try {
      const [options, stops, currentBudget] = await Promise.all([
        conciergeService.searchHotels(nextRequest), conciergeService.getItinerary(nextRequest), conciergeService.getBudget(nextRequest),
      ])
      setHotels(options); setItinerary(stops); setBudget(currentBudget)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load trip suggestions. Please try again.')
    } finally { setLoading(false) }
  }

  useEffect(() => { void refreshResults() }, [])

  const remaining = useMemo(() => {
    if (!budget) return '0.00'
    return subtractMoney(budget.total, budget.committed, budget.planned)
  }, [budget])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    await refreshResults(request)
  }

  async function handleChatSubmit(event: FormEvent) {
    event.preventDefault()
    const message = chatDraft.trim()
    if (!message || agentLoading) return
    setChatMessages((current) => [...current, { role: 'user', content: message }])
    setChatDraft(''); setAgentLoading(true); setAgentSteps([]); setError(''); setHotels([]); setItinerary([]); setBudget(null)
    try {
      const turn = await conciergeService.sendAgentTurn(message, request, language.tag)
      setRequest(turn.tripRequest); setHotels(turn.hotels); setItinerary(turn.itinerary); setBudget(turn.budget)
      setAgentSteps(turn.toolSteps)
      setChatMessages((current) => [...current, { role: 'assistant', content: turn.assistantMessage }])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The trip planner could not complete that request.')
      setChatMessages((current) => [...current, { role: 'assistant', content: 'I hit a connection problem. Please try again, or adjust the trip details and search directly.' }])
    } finally { setAgentLoading(false) }
  }

  function handleSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    event.currentTarget.reset()
    setSignInMessage('Sign-in is not connected yet. Your credentials were not sent or saved.')
  }

  async function handleHold() {
    if (!selectedHotel) return
    setHolding(true); setHoldMessage('')
    try {
      const result = await conciergeService.createHold(selectedHotel.hotelId)
      setHoldMessage(result.message)
    } catch (cause) {
      setHoldMessage(cause instanceof Error ? cause.message : 'Could not request a hold.')
    } finally { setHolding(false) }
  }

  function update<K extends keyof TripRequest>(key: K, value: TripRequest[K]) {
    setRequest((current) => ({ ...current, [key]: value }))
  }

  function updateDestination(destination: string) {
    setRequest((current) => ({
      ...current,
      destination,
      currency: conciergeService.currencyForDestination(destination) ?? current.currency,
    }))
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="Yatra home"><span className="brand-mark"><Compass size={19} /></span><span>yatra<span className="brand-period">.</span></span></a>
        <nav className={`nav-links ${mobileOpen ? 'nav-open' : ''}`} aria-label="Main navigation">
          <a className="nav-link active" href="#plan" onClick={() => { setMobileOpen(false); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>{t('nav.plan')}</a>
          <button className="nav-link" onClick={() => { setMobileOpen(false); document.getElementById('my-trips')?.scrollIntoView({ behavior: 'smooth' }) }}>{t('nav.trips')}</button>
          <button className="nav-link" onClick={() => { setMobileOpen(false); document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth' }) }}>{t('nav.explore')}</button>
        </nav>
        <div className="topbar-actions">
          <label className="language-select-wrap" title="Choose interface language"><span className="language-dot" /><select className="language-select" value={language.tag} onChange={(event) => setLanguage(event.target.value)} aria-label="Interface language">{languageOptions.map((item) => <option key={item.tag} value={item.tag}>{item.nativeName}</option>)}</select><ChevronDown size={14} /></label>
          <button className="theme-toggle" onClick={() => setTheme((current) => current === 'light' ? 'dark' : 'light')} aria-label={t(theme === 'light' ? 'theme.switchDark' : 'theme.switchLight')} title={t(theme === 'light' ? 'theme.switchDark' : 'theme.switchLight')}>{theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}</button>
          <button className="sign-in-button" onClick={() => { setSignInMessage(''); setSignInOpen(true) }}><UserRound size={16} /> <span>{t('nav.signIn')}</span></button>
          <button className="mobile-menu icon-button" aria-label={mobileOpen ? 'Close menu' : 'Open menu'} onClick={() => setMobileOpen(!mobileOpen)}>{mobileOpen ? <X size={20} /> : <Menu size={20} />}</button>
        </div>
      </header>

      {notice && <div className="notice" role="status">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={15} /></button></div>}

      <main id="home" className="main-content">
        <section className="hero-row" id="plan">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-line" /> {t('hero.eyebrow')}</div>
            <h1>{t('hero.title1')}<br /><em>{t('hero.title2')}</em></h1>
            <p className="hero-intro">{t('hero.intro')}</p>
            <div className="trust-note"><span className="trust-icon"><ShieldCheck size={16} /></span>{t('hero.trust')}</div>
            <button className="agent-hero-cta" type="button" onClick={() => { document.getElementById('chat-input')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); window.setTimeout(() => document.getElementById('chat-input')?.focus(), 350) }}><span className="agent-cta-icon"><Sparkles size={17} /></span><span>{t('agent.askButton')}</span><ArrowRight size={16} /></button>
          </div>
          <div className="hero-art" role="img" aria-label="Travel inspiration photograph">
            <div className="hero-art-overlay" />
            <div className="hero-art-caption"><span>{t('hero.artLabel')}</span><strong>{request.destination || t('hero.artDefault')}</strong></div>
            <div className="hero-art-stamp"><Sparkles size={15} /> {t('hero.artStamp')}</div>
          </div>
        </section>

        <form className="trip-search" onSubmit={handleSubmit}>
          <div className="search-field destination-field"><label htmlFor="destination"><MapPin size={16} /> {t('search.destination')}</label><input id="destination" list="destination-options" value={request.destination} onChange={(e) => updateDestination(e.target.value)} placeholder={t('search.destinationPlaceholder')} /><datalist id="destination-options">{conciergeService.destinations.map((city) => <option key={city} value={city} />)}</datalist></div>
          <div className="search-field"><label htmlFor="start-date"><CalendarDays size={16} /> {t('search.checkIn')}</label><input id="start-date" type="date" value={request.startDate} onChange={(e) => update('startDate', e.target.value)} /></div>
          <div className="search-field"><label htmlFor="end-date"><CalendarDays size={16} /> {t('search.checkOut')}</label><input id="end-date" type="date" value={request.endDate} onChange={(e) => update('endDate', e.target.value)} /></div>
          <div className="search-field guests-field"><label htmlFor="travellers"><Users size={16} /> {t('search.travellers')}</label><div className="guest-stepper"><button type="button" aria-label="Remove traveller" onClick={() => update('travellers', Math.max(1, request.travellers - 1))}><Minus size={14} /></button><span>{request.travellers} {t('search.guests')}</span><button type="button" aria-label="Add traveller" onClick={() => update('travellers', Math.min(12, request.travellers + 1))}><Plus size={14} /></button></div></div>
          <div className="search-field budget-field"><label htmlFor="budget"><Wallet size={15} /> {t('search.budget')}</label><div className="budget-input-row"><input id="budget" inputMode="decimal" value={request.budget} onChange={(e) => update('budget', e.target.value)} aria-label="Budget amount" /><select value={request.currency} onChange={(e) => update('currency', e.target.value)} aria-label="Budget currency"><option>INR</option><option>USD</option><option>EUR</option><option>GBP</option><option>AED</option><option>THB</option><option>IDR</option><option>SGD</option><option>LKR</option><option>NPR</option></select></div></div>
          <button className="search-submit" type="submit" disabled={loading}>{loading ? <span className="spinner" /> : <><span>{t('search.findStay')}</span><ArrowRight size={17} /></>}</button>
        </form>

        <section className="assistant-panel core-agent-panel">
          <div className="panel-top"><div className="assistant-avatar"><Sparkles size={20} /></div><div><strong>{t('agent.title')}</strong><span>{conciergeService.isMock ? t('agent.preview') : t('agent.planStatus')}</span></div><span className="online-pill"><i /> {agentLoading ? t('agent.working') : t('agent.ready')}</span></div>
          <div className="chat-log" role="log" aria-live="polite" aria-label="Conversation with the Yatra trip agent">
            {chatMessages.map((message, index) => <div className={`chat-bubble ${message.role}`} key={`${message.role}-${index}`}><span>{message.role === 'assistant' ? 'YATRA' : 'YOU'}</span><p>{message.content}</p></div>)}
            {agentLoading && <div className="agent-working"><span className="spinner dark-spinner" /> {t('agent.checking')}</div>}
          </div>
          {agentSteps.length > 0 && <div className="tool-trace"><span className="mini-label">{t('agent.trace')}</span>{agentSteps.map((step) => <div key={step}><Check size={12} /> {step}</div>)}</div>}
          {conciergeService.isMock && <div className="preview-explainer">{t('agent.previewNote')}</div>}
          <form className="chat-composer" onSubmit={handleChatSubmit}>
            <label className="preferences-label" htmlFor="chat-input">{t('agent.ask')}</label>
            <textarea id="chat-input" rows={4} value={chatDraft} onChange={(e) => setChatDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit() } }} placeholder={t('agent.placeholder')} />
            <div className="chat-composer-footer"><span>{t('agent.enter')}</span><button className="send-preferences" type="submit" disabled={agentLoading || !chatDraft.trim()}>{agentLoading ? t('agent.planning') : t('agent.askButton')} <Send size={14} /></button></div>
          </form>
          <div className="suggestion-chips"><button type="button" onClick={() => setChatDraft('Plan a Bangkok trip for 2 travellers under 50000')}>{t('agent.chipBangkok')}</button><button type="button" onClick={() => setChatDraft('Find a stay in Bali under 50000000 for 2 people')}>{t('agent.chipBali')}</button></div>
        </section>

        <section className="content-grid">
          <div className="left-column">
            <div className="section-heading"><div><div className="eyebrow small-eyebrow">{t('stays.eyebrow')}</div><h2>{t('stays.heading')}</h2></div><button className="text-button" onClick={() => setNotice('Showing all matching demo stays.')}>{t('stays.viewAll')} <ArrowRight size={15} /></button></div>
            {conciergeService.isMock && <div className="demo-banner"><span className="demo-dot" /> {t('stays.dataset')} <span>{t('stays.datasetNote')}</span></div>}
            {error && <div className="state-card error-state" role="alert"><CircleHelp size={19} /><div><strong>We couldn’t load suggestions</strong><p>{error}</p><button className="text-button" onClick={() => void refreshResults()}>Try again <ArrowRight size={14} /></button></div></div>}
            {loading && hotels.length === 0 && <div className="loading-card"><span className="spinner dark-spinner" /> Finding thoughtful stays…</div>}
            {!error && !loading && hotels.length === 0 && <div className="state-card"><MapPin size={20} /><div><strong>{request.destination ? t('stays.noMatch') : t('stays.whereTo')}</strong><p>{request.destination ? t('stays.noMatchHelp') : t('stays.whereHelp')}</p></div></div>}
            <div className="hotel-list">
              {hotels.map((hotel, index) => <HotelCard key={`${hotel.hotelId}-${hotel.roomTypeId}`} hotel={hotel} featured={index === 0} onSelect={() => { setSelectedHotel(hotel); setHoldMessage('') }} />)}
            </div>
            <button className="assistant-card" onClick={() => document.getElementById('chat-input')?.focus()}>
              <div className="assistant-icon"><Sparkles size={18} /></div><div className="assistant-text"><strong>{t('stays.askSentence')}</strong><span>{t('stays.askSentenceHelp')}</span></div><ArrowUpRight size={18} className="assistant-arrow" />
            </button>
          </div>

          <aside className="right-column">
            <BudgetCard budget={budget} remaining={remaining} />

            <section className="itinerary-card">
              <div className="itinerary-heading"><div><span className="mini-label">{t('itinerary.eyebrow')}</span><h3>{t('itinerary.heading')}</h3></div><button className="round-arrow" aria-label="View itinerary" onClick={() => setNotice('Full itinerary editing will connect to the trip API.')}><ArrowUpRight size={17} /></button></div>
              {itinerary.length ? <><div className="itinerary-date"><span className="date-number">17</span><span><strong>{new Intl.DateTimeFormat(language.tag, { weekday: 'long' }).format(itinerarySampleDate)}</strong><small>{new Intl.DateTimeFormat(language.tag, { month: 'long' }).format(itinerarySampleDate)} · {t('itinerary.dayTwo')}</small></span><span className="sun-symbol">☀</span></div><div className="timeline">{itinerary.map((stop) => <TimelineStop key={stop.id} stop={stop} />)}</div><button className="text-button itinerary-more" onClick={() => setNotice('Full itinerary editing will connect to the backend agent.')}>{t('itinerary.fullDay')} <ArrowRight size={14} /></button></> : <p className="empty-panel-copy">{t('itinerary.empty')}</p>}
            </section>

            <XRCard destination={request.destination || 'Jaipur'} imageUrl={destinationPhoto(request.destination || 'Jaipur')} />
          </aside>
        </section>
        <ExplorePage request={request} onAskYatra={(prompt) => { setChatDraft(prompt); document.querySelector('.assistant-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); window.setTimeout(() => document.getElementById('chat-input')?.focus(), 450) }} onPlanDestination={(city) => { updateDestination(city); document.getElementById('plan')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); setNotice(t('explore.selectedNotice').replace('{city}', city)) }} />
        <MyTripsPage onPlanNew={(city) => { if (city) updateDestination(city); document.getElementById('plan')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }} />
        <footer className="footer"><span>© 2026 Yatra. Travel, thoughtfully planned.</span><span>{t('footer.tagline')} <span className="footer-heart">♥</span></span></footer>
      </main>

      {selectedHotel && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedHotel(null) }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><button className="modal-close" aria-label="Close" onClick={() => setSelectedHotel(null)}><X size={19} /></button><div className="modal-icon"><ShieldCheck size={21} /></div><span className="mini-label">{t('modal.review')}</span><h2 id="confirm-title">{t('modal.title')}</h2><p className="modal-hotel-name">{selectedHotel.name} · {selectedHotel.roomName}</p><div className="modal-summary"><span><MapPin size={15} /> {selectedHotel.city}</span><span><CalendarDays size={15} /> {formatShortDate(request.startDate, language.tag)} – {formatShortDate(request.endDate, language.tag)}</span><strong>{formatMoney(selectedHotel.price, selectedHotel.currency)} <small>/ stay</small></strong></div><p className="modal-disclaimer">Review the details with your travel group. This preview will not reserve a room or charge you.</p>{holdMessage && <div className="modal-result" role="status">{holdMessage}</div>}<button className="modal-primary" onClick={() => void handleHold()} disabled={holding}>{holding ? 'Checking…' : t('modal.bookingOptions')} <ArrowRight size={16} /></button><button className="modal-secondary" onClick={() => setSelectedHotel(null)}>{t('modal.keepExploring')}</button></section></div>}

      {signInOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSignInOpen(false) }}><section className="confirm-modal signin-modal" role="dialog" aria-modal="true" aria-labelledby="signin-title"><button className="modal-close" aria-label="Close sign in" onClick={() => setSignInOpen(false)}><X size={19} /></button><div className="modal-icon"><UserRound size={20} /></div><span className="mini-label">{t('signin.welcome')}</span><h2 id="signin-title">{t('signin.title')}</h2><p className="signin-subtitle">{t('signin.subtitle')}</p><form className="signin-form" onSubmit={handleSignIn}><label htmlFor="signin-email"><Mail size={14} /> {t('signin.email')}</label><input id="signin-email" type="email" autoComplete="email" required placeholder="you@example.com" /><label htmlFor="signin-password"><LockKeyhole size={14} /> {t('signin.password')}</label><input id="signin-password" type="password" autoComplete="current-password" required placeholder="Enter your password" /><button className="modal-primary" type="submit">{t('nav.signIn')} <ArrowRight size={15} /></button></form>{signInMessage && <div className="modal-result" role="status">{signInMessage}</div>}<div className="signin-divider"><span />{language.tag === 'hi' ? 'या' : 'or'}<span /></div><button className="modal-secondary" onClick={() => { setSignInOpen(false); setNotice(t('signin.guest')) }}>{t('signin.continue')}</button><p className="signin-footnote">{t('signin.note')}</p></section></div>}
    </div>
  )
}

function HotelCard({ hotel, featured, onSelect }: { hotel: HotelOption; featured: boolean; onSelect: () => void }) {
  const { t } = useLanguage()
  return <article className={`hotel-card ${featured ? 'featured-hotel' : ''}`}>
    <div className="hotel-image-wrap"><img src={hotel.imageUrl} alt={`Illustrative destination photo for ${hotel.city}, not a photo of ${hotel.name}`} loading="lazy" /><span className="image-location"><MapPin size={12} /> {hotel.city}</span>{featured && <span className="pick-badge"><Sparkles size={12} /> LOWEST DATASET TOTAL</span>}</div>
    <div className="hotel-info"><div className="hotel-title-row"><div><div className="hotel-kicker">{hotel.country.toUpperCase()} <span>·</span> {hotel.roomName}</div><h3>{hotel.name}</h3></div><button className="save-button" aria-label={`Save ${hotel.name}`} title="Save stay" onClick={(e) => { e.currentTarget.classList.toggle('saved'); e.currentTarget.setAttribute('aria-pressed', String(e.currentTarget.classList.contains('saved'))) }}>♡</button></div>
      <p className="hotel-description">{hotel.description}</p><div className="hotel-tags">{hotel.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
      <div className="hotel-bottom"><div><strong>{formatMoney(hotel.price, hotel.currency)}</strong><span>{t('stays.nights').startsWith('nights') ? `for ${hotel.nights} ${t('stays.nights')}` : `${hotel.nights} ${t('stays.nights')}`}</span><small>{t('stays.units').replace('{count}', String(hotel.availableUnits))}</small></div><button className="choose-button" onClick={onSelect}>{t('stays.viewStay')} <ArrowRight size={15} /></button></div>
    </div>
  </article>
}

function BudgetCard({ budget, remaining }: { budget: BudgetSummary | null; remaining: string }) {
  const { t } = useLanguage()
  if (!budget) return <section className="budget-card budget-empty"><div className="budget-header"><span className="budget-icon"><Wallet size={17} /></span><div><span className="mini-label">{t('budget.title')}</span><h3>{t('budget.overview')}</h3></div></div><p>{t('stays.budgetEmpty')}</p></section>
  const totalMinor = decimalToMinorUnits(budget.total)
  const usedMinor = decimalToMinorUnits(budget.committed) + decimalToMinorUnits(budget.planned)
  const progress = totalMinor <= 0n ? 0 : Math.min(100, Math.max(0, Number((usedMinor * 10000n) / totalMinor) / 100))
  return <section className="budget-card"><div className="budget-header"><span className="budget-icon"><Wallet size={17} /></span><div><span className="mini-label">{t('budget.title')}</span><h3>{t('budget.heading')}</h3></div><button className="help-button" title="Values shown are from the static dataset preview"><CircleHelp size={16} /></button></div><div className="budget-total"><span>{t('budget.allowance')}</span><strong>{formatMoney(budget.total, budget.currency)}</strong></div><div className="budget-track"><span style={{ width: `${progress}%` }} /></div><div className="budget-legend"><div><i className="planned-dot" /> {t('budget.planned')} <strong>{formatMoney(budget.planned, budget.currency)}</strong></div><div><i className="committed-dot" /> {t('budget.committed')} <strong>{formatMoney(budget.committed, budget.currency)}</strong></div></div><div className="budget-remaining"><span>{t('budget.remaining')}</span><strong>{formatMoney(remaining, budget.currency)}</strong></div><div className="budget-note"><Check size={13} /> {t('budget.preview')} <span>· backend will provide live totals</span></div></section>
}

function TimelineStop({ stop }: { stop: ItineraryStop }) {
  const icon = stop.category === 'food' ? '✳' : stop.category === 'nature' ? '⌁' : stop.category === 'stay' ? '⌂' : '✧'
  return <div className="timeline-stop"><div className={`timeline-icon ${stop.category}`}>{icon}</div><div className="timeline-time">{stop.time}</div><div className="timeline-copy"><strong>{stop.title}</strong><span>{stop.detail}</span></div></div>
}

function XRCard({ destination, imageUrl }: { destination: string; imageUrl: string }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  const [zoom, setZoom] = useState(1)
  return <>
    <section className="xr-card"><div className="xr-art" style={{ backgroundImage: `linear-gradient(90deg,#172e27bb,#172e2730),url("${imageUrl}")`, backgroundSize: 'cover', backgroundPosition: 'center' }}><span className="xr-orbit orbit-one" /><span className="xr-orbit orbit-two" /><span className="xr-label">{t('xr.label')}</span><div className="xr-object">⌖</div><span className="xr-caption">{t('xr.caption')}</span></div><button className="xr-action" onClick={() => setOpen(true)}>{t('xr.button')} <ArrowUpRight size={15} /></button><span className="xr-pending">{t('xr.pending')}</span></section>
    {open && <div className="modal-backdrop xr-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false) }}><section className="xr-preview-modal" role="dialog" aria-modal="true" aria-labelledby="xr-preview-title">
      <button className="modal-close" aria-label={t('xr.close')} onClick={() => setOpen(false)}><X size={19} /></button>
      <div className="xr-preview-scene" style={{ backgroundImage: `linear-gradient(0deg,#10231dcc,transparent 62%),url("${imageUrl}")`, backgroundSize: `${zoom * 100}% auto`, backgroundPosition: 'center' }}><span className="xr-preview-badge"><Compass size={14} /> {t('xr.badge')}</span><div><span>{t('xr.label')}</span><h2 id="xr-preview-title">{destination}</h2></div></div>
      <div className="xr-preview-controls"><div><strong>{t('xr.closer')}</strong><p>{t('xr.description')}</p></div><div className="xr-zoom-controls"><button onClick={() => setZoom((value) => Math.max(1, value - .15))} aria-label={t('xr.zoomOut')}>−</button><span>{Math.round(zoom * 100)}%</span><button onClick={() => setZoom((value) => Math.min(1.6, value + .15))} aria-label={t('xr.zoomIn')}>+</button></div></div>
    </section></div>}
  </>
}
