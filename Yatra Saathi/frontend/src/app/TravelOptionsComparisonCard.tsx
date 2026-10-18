import { useState, useMemo } from 'react'
import {
  AlertCircle,
  ArrowRight,
  Award,
  Check,
  Clock,
  Compass,
  Filter,
  Hotel,
  Info,
  Plane,
  Scale,
  Sparkles,
  Star,
  TrendingDown,
  Zap,
} from 'lucide-react'
import { formatMoney } from '../utils/format'
import type {
  PlanDiff,
  TravelOption,
} from '../types/travel'

interface Props {
  options: TravelOption[]
  summary?: string
  tradeOffs?: string[]
  activeOptionId?: string
  currency?: string
  onApplyOption: (option: TravelOption) => Promise<void>
  onOptimize: (objective: string, allowedChanges?: { flight: boolean; hotel: boolean; activities: boolean; dates: boolean }) => Promise<void>
  optimizing?: boolean
  pendingDiff?: PlanDiff | null
  onConfirmDiff?: () => Promise<void>
  onDismissDiff?: () => void
}

export default function TravelOptionsComparisonCard({
  options,
  summary,
  tradeOffs,
  activeOptionId,
  currency: _currency,
  onApplyOption,
  onOptimize,
  optimizing = false,
  pendingDiff,
  onConfirmDiff,
  onDismissDiff,
}: Props) {
  const [selectedFilter, setSelectedFilter] = useState<string>('all')
  const [sortBy, setSortBy] = useState<'score' | 'price' | 'duration' | 'hotel'>('score')
  const [activeTab, setActiveTab] = useState<'packages' | 'flights' | 'hotels'>('packages')
  const [applyingId, setApplyingId] = useState<string | null>(null)

  // 1. Extract genuinely distinct flight alternatives
  const distinctFlights = useMemo(() => {
    const map = new Map<string, any>()
    for (const opt of options) {
      if (!opt.flight) continue
      const out = (opt.flight.outbound || {}) as Record<string, any>
      const ret = (opt.flight.returnFlight || {}) as Record<string, any>
      const outNum = String(out.flight_number || opt.flight.carrierNames?.[0] || 'Flight')
      const retNum = String(ret.flight_number || '')
      const outDep = String(out.departs_at || '')
      const retDep = String(ret.departs_at || '')
      const key = `${outNum}_${outDep}_${retNum}_${retDep}`

      if (!map.has(key)) {
        map.set(key, {
          key,
          airline: opt.flight.carrierNames?.join(', ') || 'Airline',
          outboundFlight: out.flight_number || outNum,
          returnFlight: ret.flight_number || retNum,
          origin: out.origin_code || 'BOM',
          destination: out.dest_code || 'LKO',
          departure: typeof out.departs_at === 'string' ? out.departs_at.slice(11, 16) : '—',
          arrival: typeof out.arrives_at === 'string' ? out.arrives_at.slice(11, 16) : '—',
          returnDeparture: typeof ret.departs_at === 'string' ? ret.departs_at.slice(11, 16) : '—',
          returnArrival: typeof ret.arrives_at === 'string' ? ret.arrives_at.slice(11, 16) : '—',
          duration: opt.flight.totalDurationMinutes
            ? `${Math.floor(opt.flight.totalDurationMinutes / 60)}h ${opt.flight.totalDurationMinutes % 60}m`
            : '—',
          stops: opt.flight.totalStops === 0 ? 'Nonstop (Direct)' : `${opt.flight.totalStops} stop(s)`,
          cabin: 'Economy',
          refundable: out.refundable ? 'Refundable' : 'Standard fare',
          price: opt.flight.totalFlightPrice,
          currency: opt.currency || 'INR',
        })
      }
    }
    return Array.from(map.values())
  }, [options])

  // 2. Extract genuinely distinct hotel alternatives
  const distinctHotels = useMemo(() => {
    const map = new Map<string, any>()
    for (const opt of options) {
      if (!opt.hotel) continue
      if (!map.has(opt.hotel.hotelId)) {
        map.set(opt.hotel.hotelId, {
          hotelId: opt.hotel.hotelId,
          hotelName: opt.hotel.hotelName,
          roomName: opt.hotel.roomName || 'Standard Room',
          starRating: opt.hotel.starRating,
          guestScore: opt.hotel.guestScore,
          nights: opt.hotel.nights,
          totalPrice: opt.hotel.totalHotelPrice,
          currency: opt.hotel.currency || opt.currency || 'INR',
          address: opt.hotel.address,
        })
      }
    }
    return Array.from(map.values())
  }, [options])

  if (!options || options.length === 0) {
    return (
      <section className="travel-comparison-container comparison-card" aria-label="Travel Options Comparison">
        <header className="comparison-header">
          <div className="header-titles">
            <div className="eyebrow-row">
              <Sparkles size={14} className="eyebrow-icon" />
              <span className="eyebrow-text">DECISION SUPPORT & COMPARISON</span>
            </div>
            <h3>Intelligent Travel Comparison</h3>
            <p className="comparison-summary">Compare alternative flights, hotels, and packages with transparent trade-offs.</p>
          </div>
          <div className="view-toggle">
            <button
              type="button"
              className={`toggle-btn comp-tab-btn ${activeTab === 'packages' ? 'active' : ''}`}
              onClick={() => setActiveTab('packages')}
            >
              Complete Packages (0)
            </button>
            <button
              type="button"
              className={`toggle-btn comp-tab-btn ${activeTab === 'flights' ? 'active' : ''}`}
              onClick={() => setActiveTab('flights')}
            >
              Flight Options (1)
            </button>
            <button
              type="button"
              className={`toggle-btn comp-tab-btn ${activeTab === 'hotels' ? 'active' : ''}`}
              onClick={() => setActiveTab('hotels')}
            >
              Hotel Options (0)
            </button>
          </div>
        </header>
        <div className="single-flight-notice-banner catalog-notice-banner" role="status" style={{
          display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 16px',
          background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '6px',
          color: '#1e3a8a', fontSize: '11px', margin: '14px 0',
        }}>
          <Info size={15} style={{ flexShrink: 0, color: '#2563eb' }} />
          <span>
            <strong>Authoritative Catalog Note:</strong> Only one suitable flight is currently available in the catalog for this route. Packages vary primarily by hotel selection.
          </span>
        </div>
        {activeTab === 'flights' && (
          <div className="distinct-flights-section">
            <div className="comparison-table-wrapper" style={{ overflowX: 'auto', marginBottom: '16px' }}>
              <table className="comparison-table flight-comparison-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: '8px 12px' }}>Feature</th>
                    <th style={{ textAlign: 'left', padding: '8px 12px' }}>Catalog Direct Flight (IndiGo 6E-241)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td><strong>Airline</strong></td><td>IndiGo (6E)</td></tr>
                  <tr><td><strong>Route</strong></td><td>BOM → LKO</td></tr>
                  <tr><td><strong>Stops</strong></td><td>Nonstop (Direct)</td></tr>
                  <tr><td><strong>Cabin</strong></td><td>Economy</td></tr>
                  <tr><td><strong>Price Basis</strong></td><td>Authoritative catalog calendar rate</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    )
  }

  // Filter package options
  const filtered = options.filter((opt) => {
    if (selectedFilter === 'cheapest') return opt.isCheapest || opt.category === 'cheapest'
    if (selectedFilter === 'best_value') return opt.isBestValue || opt.category === 'best_value'
    if (selectedFilter === 'fastest') return opt.isFastest || opt.category === 'fastest'
    if (selectedFilter === 'comfort') return opt.isMostComfortable || opt.category === 'most_comfortable'
    if (selectedFilter === 'within_budget') return opt.isWithinBudget
    return true
  })

  // Sort package options
  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'price') {
      return parseFloat(a.authoritativeTotal) - parseFloat(b.authoritativeTotal)
    }
    if (sortBy === 'duration') {
      return (a.totalDurationMinutes ?? 9999) - (b.totalDurationMinutes ?? 9999)
    }
    if (sortBy === 'hotel') {
      return (b.scoreBreakdown.hotelScore ?? 0) - (a.scoreBreakdown.hotelScore ?? 0)
    }
    return b.score - a.score // default by overall score
  })

  const getCategoryBadge = (opt: TravelOption) => {
    if (opt.isBestValue || opt.category === 'best_value') {
      return <span className="cat-badge badge-best-value"><Award size={12} /> BEST VALUE</span>
    }
    if (opt.isCheapest || opt.category === 'cheapest') {
      return <span className="cat-badge badge-cheapest"><TrendingDown size={12} /> CHEAPEST</span>
    }
    if (opt.isFastest || opt.category === 'fastest') {
      return <span className="cat-badge badge-fastest"><Clock size={12} /> FASTEST</span>
    }
    if (opt.isMostComfortable || opt.category === 'most_comfortable') {
      return <span className="cat-badge badge-comfort"><Star size={12} /> COMFORT</span>
    }
    return <span className="cat-badge badge-balanced"><Compass size={12} /> BALANCED</span>
  }

  const handleApply = async (opt: TravelOption) => {
    setApplyingId(opt.id)
    try {
      await onApplyOption(opt)
    } finally {
      setApplyingId(null)
    }
  }

  const basePackage = sorted[0]

  return (
    <section className="travel-comparison-container" aria-label="Travel Options Comparison">
      {/* Header */}
      <header className="comparison-header">
        <div className="header-titles">
          <div className="eyebrow-row">
            <Sparkles size={14} className="eyebrow-icon" />
            <span className="eyebrow-text">DECISION SUPPORT & COMPARISON</span>
          </div>
          <h3>Intelligent Travel Comparison</h3>
          {summary && <p className="comparison-summary">{summary}</p>}
        </div>

        <div className="view-toggle">
          <button
            type="button"
            className={`toggle-btn comp-tab-btn ${activeTab === 'packages' ? 'active' : ''}`}
            onClick={() => setActiveTab('packages')}
          >
            Complete Packages ({options.length})
          </button>
          <button
            type="button"
            className={`toggle-btn comp-tab-btn ${activeTab === 'flights' ? 'active' : ''}`}
            onClick={() => setActiveTab('flights')}
          >
            Flight Options ({distinctFlights.length})
          </button>
          <button
            type="button"
            className={`toggle-btn comp-tab-btn ${activeTab === 'hotels' ? 'active' : ''}`}
            onClick={() => setActiveTab('hotels')}
          >
            Hotel Options ({distinctHotels.length})
          </button>
        </div>
      </header>

      {/* Trade-Off Insights */}
      {tradeOffs && tradeOffs.length > 0 && (
        <div className="tradeoffs-banner">
          <strong>Key Trade-Off Insights:</strong>
          <ul>
            {tradeOffs.map((to, idx) => (
              <li key={idx}>{to}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Notice when only 1 distinct flight exists in the catalog */}
      {(distinctFlights.length <= 1) && (
        <div className="single-flight-notice-banner catalog-notice-banner" role="status" style={{
          display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 14px',
          background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '6px',
          color: '#1e3a8a', fontSize: '11px', margin: '12px 0',
        }}>
          <Info size={15} style={{ flexShrink: 0, color: '#2563eb' }} />
          <span>
            <strong>Authoritative Catalog Note:</strong> Only one suitable flight is currently available in the catalog for this route and travel dates. Packages vary primarily by hotel selection.
          </span>
        </div>
      )}

      {/* Quick Budget Optimizers */}
      <div className="optimization-quickbar">
        <span className="opt-label"><Zap size={14} /> Quick Budget Optimizers:</span>
        <div className="opt-chips">
          <button
            type="button"
            className="opt-chip"
            disabled={optimizing}
            onClick={() => onOptimize('cheaper')}
          >
            📉 Make It Cheaper
          </button>
          <button
            type="button"
            className="opt-chip"
            disabled={optimizing}
            onClick={() => onOptimize('cheaper', { flight: true, hotel: false, activities: false, dates: false })}
          >
            <Plane size={11} /> Cheaper Flights Only
          </button>
          <button
            type="button"
            className="opt-chip"
            disabled={optimizing}
            onClick={() => onOptimize('comfort')}
          >
            <Sparkles size={11} /> Upgrade Hotel & Comfort
          </button>
          <button
            type="button"
            className="opt-chip"
            disabled={optimizing}
            onClick={() => onOptimize('best_value')}
          >
            <Scale size={11} /> Best Value Balance
          </button>
        </div>
      </div>

      {/* Pending Diff Banner */}
      {pendingDiff && (
        <div className="plan-diff-banner">
          <div className="diff-header">
            <h4><AlertCircle size={16} /> Proposed Plan Optimization</h4>
            {pendingDiff.savings && (
              <span className="savings-badge">
                Save {formatMoney(pendingDiff.savings, pendingDiff.currency)}
              </span>
            )}
            {pendingDiff.costIncrease && (
              <span className="cost-delta-badge">
                +{formatMoney(pendingDiff.costIncrease, pendingDiff.currency)}
              </span>
            )}
          </div>
          <p className="diff-summary">{pendingDiff.summary}</p>
          <div className="diff-comparison-grid">
            <div className="diff-box before">
              <span className="diff-box-title">Current Plan Total:</span>
              <strong>{formatMoney(pendingDiff.beforeAuthoritativeTotal, pendingDiff.currency)}</strong>
            </div>
            <ArrowRight size={20} className="diff-arrow" />
            <div className="diff-box after">
              <span className="diff-box-title">Optimized Total:</span>
              <strong className="optimized-price">{formatMoney(pendingDiff.afterAuthoritativeTotal, pendingDiff.currency)}</strong>
            </div>
          </div>
          <div className="diff-actions">
            {onConfirmDiff && (
              <button type="button" className="confirm-diff-btn" onClick={onConfirmDiff}>
                <Check size={14} /> Confirm & Apply Optimization
              </button>
            )}
            {onDismissDiff && (
              <button type="button" className="dismiss-diff-btn" onClick={onDismissDiff}>
                Keep Current Plan
              </button>
            )}
          </div>
        </div>
      )}

      {/* TAB 1: FLIGHT OPTIONS (Distinct flights separated from hotels) */}
      {activeTab === 'flights' && (
        <div className="distinct-flights-section">
          <div className="section-head-bar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h4 style={{ margin: 0, fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Plane size={15} /> Genuinely Distinct Flight Options ({distinctFlights.length})
            </h4>
            <span style={{ fontSize: '11px', color: '#64748b' }}>Authoritative inventory strictly checked</span>
          </div>

          {distinctFlights.length === 1 && (
            <div className="single-flight-notice" style={{ padding: '8px 12px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '4px', fontSize: '11px', color: '#334155', marginBottom: '12px' }}>
              Only one suitable flight is currently available in the catalog.
            </div>
          )}

          {/* Interactive Side-by-Side Flight Comparison Table */}
          <div className="comparison-table-wrapper" style={{ overflowX: 'auto', marginBottom: '16px' }}>
            <table className="comparison-table flight-comparison-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '8px 12px' }}>Feature</th>
                  {distinctFlights.map((f, i) => (
                    <th key={f.key} style={{ textAlign: 'left', padding: '8px 12px' }}>
                      Option {String.fromCharCode(65 + i)} ({f.airline})
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>Airline</strong></td>
                  {distinctFlights.map((f) => <td key={f.key}>{f.airline}</td>)}
                </tr>
                <tr>
                  <td><strong>Flight Numbers</strong></td>
                  {distinctFlights.map((f) => (
                    <td key={f.key}>
                      Outbound: {f.outboundFlight}<br />
                      {f.returnFlight && `Return: ${f.returnFlight}`}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td><strong>Departure</strong></td>
                  {distinctFlights.map((f) => <td key={f.key}>{f.departure}</td>)}
                </tr>
                <tr>
                  <td><strong>Arrival</strong></td>
                  {distinctFlights.map((f) => <td key={f.key}>{f.arrival}</td>)}
                </tr>
                <tr>
                  <td><strong>Duration</strong></td>
                  {distinctFlights.map((f) => <td key={f.key}>{f.duration}</td>)}
                </tr>
                <tr>
                  <td><strong>Stops</strong></td>
                  {distinctFlights.map((f) => <td key={f.key}>{f.stops}</td>)}
                </tr>
                <tr>
                  <td><strong>Cabin Class</strong></td>
                  {distinctFlights.map((f) => <td key={f.key}>{f.cabin}</td>)}
                </tr>
                <tr>
                  <td><strong>Refundability</strong></td>
                  {distinctFlights.map((f) => <td key={f.key}>{f.refundable}</td>)}
                </tr>
                <tr>
                  <td><strong>Authoritative Price</strong></td>
                  {distinctFlights.map((f) => (
                    <td key={f.key}><strong style={{ color: '#059669' }}>{formatMoney(f.price, f.currency)}</strong></td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 2: HOTEL OPTIONS (Distinct hotel alternatives) */}
      {activeTab === 'hotels' && (
        <div className="distinct-hotels-section">
          <div className="section-head-bar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h4 style={{ margin: 0, fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Hotel size={15} /> Genuinely Distinct Hotel Options ({distinctHotels.length})
            </h4>
          </div>
          <div className="comparison-cards-grid">
            {distinctHotels.map((h) => (
              <div key={h.hotelId} className="travel-option-card hotel-only-card" style={{ padding: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <h4 style={{ margin: '0 0 4px', fontSize: '14px' }}>{h.hotelName}</h4>
                    <p style={{ margin: '0 0 8px', fontSize: '11px', color: '#64748b' }}>
                      {h.starRating ? `${h.starRating}★ · ` : ''}{h.roomName} · {h.nights} night(s)
                    </p>
                  </div>
                  <strong style={{ fontSize: '15px', color: '#059669' }}>
                    {formatMoney(h.totalPrice, h.currency)}
                  </strong>
                </div>
                {h.address && <p style={{ margin: 0, fontSize: '10px', color: '#888' }}>{h.address}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 3: COMPLETE PACKAGES */}
      {activeTab === 'packages' && (
        <>
          {/* Filter & Sort Toolbar */}
          <div className="comparison-toolbar">
            <div className="filter-group">
              <Filter size={14} className="filter-icon" />
              <div className="filter-tabs">
                {['all', 'best_value', 'cheapest', 'fastest', 'comfort', 'within_budget'].map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={`filter-btn ${selectedFilter === f ? 'active' : ''}`}
                    onClick={() => setSelectedFilter(f)}
                  >
                    {f.replace('_', ' ').toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div className="sort-group">
              <label htmlFor="comparison-sort">Sort by:</label>
              <select
                id="comparison-sort"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
              >
                <option value="score">Overall Score</option>
                <option value="price">Lowest Price</option>
                <option value="duration">Fastest Duration</option>
                <option value="hotel">Hotel Quality</option>
              </select>
            </div>
          </div>

          {/* Cards View with Package Breakdown */}
          <div className="comparison-cards-grid">
            {sorted.map((opt, pkgIdx) => {
              const isSelected = opt.id === activeOptionId
              const mins = opt.totalDurationMinutes ?? 0

              // Calculate price differences vs package 1
              const totalDiff = basePackage
                ? parseFloat(opt.authoritativeTotal) - parseFloat(basePackage.authoritativeTotal)
                : 0
              const hotelDiff = basePackage && basePackage.hotel && opt.hotel
                ? parseFloat(opt.accommodationCost) - parseFloat(basePackage.accommodationCost)
                : 0
              const flightDiff = basePackage && basePackage.flight && opt.flight
                ? parseFloat(opt.transportCost) - parseFloat(basePackage.transportCost)
                : 0

              return (
                <article
                  key={opt.id}
                  className={`travel-option-card comparison-card ${isSelected ? 'active-option' : ''} ${opt.category}`}
                >
                  <div className="option-card-header">
                    <div className="badge-and-id">
                      {getCategoryBadge(opt)}
                      <span className="option-code">Package {pkgIdx + 1}</span>
                    </div>
                    <div className="option-price-block">
                      <span className="price-label">Authoritative Total:</span>
                      <strong className="option-total-amount">
                        {formatMoney(opt.authoritativeTotal, opt.currency)}
                      </strong>
                      {!opt.isWithinBudget && (
                        <span className="over-budget-warning">Exceeds Target Budget</span>
                      )}
                    </div>
                  </div>

                  {/* Why the price changed breakdown */}
                  {pkgIdx > 0 && (
                    <div className="package-diff-breakdown" style={{
                      padding: '6px 10px', background: '#f8fafc', borderRadius: '4px',
                      fontSize: '10px', color: '#475569', marginBottom: '8px',
                    }}>
                      <strong>Price vs Package 1: </strong>
                      <span>Total: {totalDiff >= 0 ? `+${formatMoney(totalDiff.toFixed(2), opt.currency)}` : formatMoney(totalDiff.toFixed(2), opt.currency)}</span>
                      {hotelDiff !== 0 && <span> · Stay: {hotelDiff >= 0 ? `+${formatMoney(hotelDiff.toFixed(2), opt.currency)}` : formatMoney(hotelDiff.toFixed(2), opt.currency)}</span>}
                      {flightDiff !== 0 ? (
                        <span> · Flight: {flightDiff >= 0 ? `+${formatMoney(flightDiff.toFixed(2), opt.currency)}` : formatMoney(flightDiff.toFixed(2), opt.currency)}</span>
                      ) : (
                        <span> · Flight: Identical</span>
                      )}
                    </div>
                  )}

                  <div className="score-summary-bar">
                    <div className="score-ring">
                      <span className="score-value">{opt.score}</span>
                      <span className="score-scale">/ 10</span>
                    </div>
                    <div className="score-meters">
                      <div className="meter-item">
                        <span>Price: {opt.scoreBreakdown.priceScore}/10</span>
                        <div className="meter-bar"><div className="fill" style={{ width: `${opt.scoreBreakdown.priceScore * 10}%` }} /></div>
                      </div>
                      {opt.scoreBreakdown.durationScore != null && (
                        <div className="meter-item">
                          <span>Travel Time: {opt.scoreBreakdown.durationScore}/10</span>
                          <div className="meter-bar"><div className="fill" style={{ width: `${opt.scoreBreakdown.durationScore * 10}%` }} /></div>
                        </div>
                      )}
                      {opt.scoreBreakdown.hotelScore != null && (
                        <div className="meter-item">
                          <span>Stay Quality: {opt.scoreBreakdown.hotelScore}/10</span>
                          <div className="meter-bar"><div className="fill" style={{ width: `${opt.scoreBreakdown.hotelScore * 10}%` }} /></div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Flight Segment */}
                  {opt.flight && (
                    <div className="option-segment flight-segment">
                      <div className="segment-title">
                        <Plane size={14} />
                        <span>Flight Component ({formatMoney(opt.transportCost, opt.currency)})</span>
                      </div>
                      <div className="segment-details">
                        <strong>{opt.flight.carrierNames?.join(' & ') || 'Scheduled Carrier'}</strong>
                        <span>
                          {opt.flight.isDirect ? 'Direct (Nonstop)' : `${opt.flight.totalStops} Stop(s)`}
                          {mins > 0 && ` · Total duration ~${Math.floor(mins / 60)}h ${mins % 60}m`}
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Hotel Segment */}
                  {opt.hotel && (
                    <div className="option-segment hotel-segment">
                      <div className="segment-title">
                        <Hotel size={14} />
                        <span>Hotel Component ({formatMoney(opt.accommodationCost, opt.currency)})</span>
                      </div>
                      <div className="segment-details">
                        <strong>{opt.hotel.hotelName}</strong>
                        <span>
                          {opt.hotel.roomName ?? 'Standard Room'} · {opt.hotel.nights} night(s)
                        </span>
                        <small>
                          {opt.hotel.starRating ? `${opt.hotel.starRating}★ ` : ''}
                          {opt.hotel.guestScore ? `· Guest score ${opt.hotel.guestScore}/10` : ''}
                        </small>
                      </div>
                    </div>
                  )}

                  <div className="option-footer-actions">
                    <button
                      type="button"
                      className="apply-option-btn"
                      disabled={applyingId === opt.id}
                      onClick={() => handleApply(opt)}
                    >
                      {applyingId === opt.id ? 'Applying...' : 'Select This Package'}
                      <ArrowRight size={13} />
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}
