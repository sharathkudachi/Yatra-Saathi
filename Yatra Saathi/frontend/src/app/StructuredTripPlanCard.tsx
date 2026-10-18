import React, { useState } from 'react'
import {
  Calendar, Clock, MapPin, Plane, Building2,
  Sparkles, RefreshCw, Navigation, CheckCircle2,
  AlertCircle, ArrowRight, Layers, SlidersHorizontal,
  ChevronDown, ChevronUp, UserCheck, Car, Utensils, Coffee,
  TrendingDown, Landmark, Trees, Scale,
} from 'lucide-react'
import type {
  ItineraryActivity,
  ItineraryAlternativeOption,
  StructuredTripPlan,
} from '../types/travel'

type Props = {
  plan: StructuredTripPlan | null
  alternatives?: ItineraryAlternativeOption[]
  selectedOptionId?: string
  executionSteps?: string[]
  replanning?: boolean
  replanError?: string | null
  selectedActivity?: ItineraryActivity | null
  activeDayFilter?: number | null
  onDayFilterChange?: (day: number | null) => void
  onSelectActivity?: (activity: ItineraryActivity) => void
  onSelectAlternative?: (optionId: string) => void
  onReplan?: (instruction: string) => void
  onRegenerate?: () => void
  onGenerate?: () => void
  onCompareOptions?: () => void
  onOptimizeBudget?: () => void
  onBookTrip?: () => void
  className?: string
}

function parseMinutes(t?: string): number | null {
  if (!t) return null
  const parts = t.split(':')
  if (parts.length < 2) return null
  const h = parseInt(parts[0], 10)
  const m = parseInt(parts[1], 10)
  if (isNaN(h) || isNaN(m)) return null
  return h * 60 + m
}

function formatDuration(start?: string, end?: string, durMins?: number): string | null {
  if (durMins && durMins > 0) {
    const h = Math.floor(durMins / 60)
    const m = durMins % 60
    if (h > 0 && m > 0) return `${h}h ${m}m`
    if (h > 0) return `${h}h`
    return `${m}m`
  }
  const s = parseMinutes(start)
  const e = parseMinutes(end)
  if (s !== null && e !== null && e > s) {
    const total = e - s
    const h = Math.floor(total / 60)
    const m = total % 60
    if (h > 0 && m > 0) return `${h}h ${m}m`
    if (h > 0) return `${h}h`
    return `${m}m`
  }
  return null
}

function getActivityIcon(category?: string, title?: string) {
  const cat = (category || '').toLowerCase()
  const tit = (title || '').toLowerCase()
  if (tit.includes('arrive') || tit.includes('flight') || tit.includes('airport') || cat === 'transport') {
    return <Plane size={14} className="act-type-icon plane-icon" />
  }
  if (tit.includes('transfer') || tit.includes('taxi') || tit.includes('travel') || tit.includes('drive')) {
    return <Car size={14} className="act-type-icon car-icon" />
  }
  if (tit.includes('hotel') || tit.includes('check-in') || tit.includes('check-out') || tit.includes('luggage')) {
    return <Building2 size={14} className="act-type-icon hotel-icon" />
  }
  if (tit.includes('lunch') || tit.includes('dinner') || tit.includes('breakfast') || cat === 'food' || cat === 'restaurant') {
    return <Utensils size={14} className="act-type-icon food-icon" />
  }
  if (tit.includes('tea') || tit.includes('coffee') || tit.includes('break')) {
    return <Coffee size={14} className="act-type-icon coffee-icon" />
  }
  return <MapPin size={14} className="act-type-icon attraction-icon" />
}

export default function StructuredTripPlanCard({
  plan,
  alternatives = [],
  selectedOptionId = 'balanced',
  executionSteps = [],
  replanning = false,
  replanError = null,
  selectedActivity = null,
  activeDayFilter = null,
  onDayFilterChange,
  onSelectActivity,
  onSelectAlternative,
  onReplan,
  onRegenerate,
  onGenerate,
  onCompareOptions,
  onOptimizeBudget,
  onBookTrip,
  className = '',
}: Props) {
  const [customReplanText, setCustomReplanText] = useState('')
  const [showTrace, setShowTrace] = useState(false)

  if (!plan) {
    return (
      <section className={`structured-trip-plan-card empty-plan ${className}`} aria-label="Trip Plan">
        <div className="plan-card-header">
          <div className="plan-card-title">
            <Calendar size={16} className="plan-icon" />
            <span>Structured Trip Plan</span>
          </div>
        </div>
        <div className="plan-empty-state">
          <Calendar size={32} className="empty-plan-icon" />
          <h4>No structured trip plan yet</h4>
          <p>Ask Yatra Saathi to plan a trip or select an example above to generate your verified daily itinerary.</p>
        </div>
      </section>
    )
  }

  const statusLabel = plan.status.toUpperCase()

  const handleCustomReplanSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!customReplanText.trim() || replanning) return
    if (onReplan) {
      onReplan(customReplanText.trim())
      setCustomReplanText('')
    }
  }

  // Filter days by day tab if set
  const filteredDays = activeDayFilter !== null
    ? plan.days.filter((d) => d.dayNumber === activeDayFilter)
    : plan.days

  return (
    <section className={`structured-trip-plan-card ${className}`} aria-label={`Trip Plan: ${plan.title}`}>
      {/* Header bar */}
      <div className="plan-card-header">
        <div className="plan-card-title">
          <Calendar size={16} className="plan-icon" />
          <span>{plan.title || 'Structured Trip Plan'}</span>
          <span className={`status-badge status-${plan.status}`}>{statusLabel}</span>
          {typeof plan.version === 'number' && (
            <span className="version-pill" title="Itinerary revision version">
              v{plan.version}
            </span>
          )}
        </div>
        <div className="plan-meta-brief">
          <span className="route-text">
            {plan.origin} → {plan.destination}
          </span>
          <span className="divider">·</span>
          <span>{plan.startDate} to {plan.endDate}</span>
          <span className="divider">·</span>
          <span>{plan.travellers} {plan.travellers === 1 ? 'traveller' : 'travellers'}</span>
        </div>
      </div>

      {/* Preliminary Preview CTA Banner */}
      {plan.id === 'preview_plan' && onGenerate && (
        <div className="preview-plan-banner">
          <div className="preview-plan-info">
            <Sparkles size={16} className="sparkle-icon" />
            <div>
              <strong>Preliminary Route Schedule</strong>
              <p>Generate a complete AI itinerary with grounded attractions, transport, stays, and budget alternatives.</p>
            </div>
          </div>
          <button
            type="button"
            className="generate-verified-btn"
            disabled={replanning}
            onClick={onGenerate}
          >
            {replanning ? (
              <><RefreshCw size={13} className="spin-icon" /> Generating…</>
            ) : (
              <><Sparkles size={13} /> Generate Verified Itinerary</>
            )}
          </button>
        </div>
      )}

      {/* Bounded Alternatives Switcher */}
      {alternatives.length > 0 && (
        <div className="plan-alternatives-bar">
          <div className="alt-label">
            <Layers size={13} />
            <span>Trip Options:</span>
          </div>
          <div className="alt-buttons-group">
            {alternatives.map((alt) => {
              const isSelected = selectedOptionId === alt.optionId
              return (
                <button
                  key={alt.optionId}
                  type="button"
                  className={`alt-btn ${isSelected ? 'active' : ''}`}
                  onClick={() => onSelectAlternative && onSelectAlternative(alt.optionId)}
                  disabled={replanning}
                >
                  <span className="alt-name">{alt.label}</span>
                  {alt.totalCost && (
                    <span className="alt-cost">
                      {alt.currency} {alt.totalCost}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Cost summary strip */}
      {(plan.totalAuthoritativeCost || plan.totalEstimatedCost || plan.budget) && (
        <div className="plan-cost-strip">
          {plan.totalAuthoritativeCost && (
            <div className="cost-item authoritative">
              <span className="cost-label">Authoritative Total</span>
              <strong className="cost-val">
                {plan.currency} {plan.totalAuthoritativeCost}
              </strong>
            </div>
          )}
          {plan.totalEstimatedCost && plan.totalEstimatedCost !== plan.totalAuthoritativeCost && (
            <div className="cost-item estimated">
              <span className="cost-label">Estimated Total</span>
              <span className="cost-val">
                {plan.currency} {plan.totalEstimatedCost}
              </span>
            </div>
          )}
          {plan.budget && (
            <div className="cost-item budget">
              <span className="cost-label">Target Budget</span>
              <span className="cost-val">
                {plan.currency} {plan.budget}
              </span>
            </div>
          )}
          <div className="cost-badge-note">
            <CheckCircle2 size={12} className="check-icon" />
            <span>Pricing strictly computed by backend money engine</span>
          </div>
          {onBookTrip && (
            <button
              type="button"
              className="book-trip-cta-btn"
              onClick={onBookTrip}
              title="Review & Reserve Demo Booking"
            >
              <UserCheck size={14} />
              <span>Review & Reserve Demo Booking</span>
              <ArrowRight size={14} />
            </button>
          )}
        </div>
      )}

      {/* Structured AI Planning State / Execution Steps Banner */}
      {executionSteps.length > 0 && (
        <div className="plan-trace-banner">
          <button
            type="button"
            className="trace-toggle-btn"
            onClick={() => setShowTrace(!showTrace)}
          >
            <Sparkles size={13} className="trace-icon" />
            <span>AI Planning Trace ({executionSteps.length} verified steps)</span>
            {showTrace ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {showTrace && (
            <div className="trace-steps-list">
              {executionSteps.map((step, idx) => (
                <div key={idx} className="trace-step-item">
                  <CheckCircle2 size={12} className="step-check" />
                  <span>{step}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Conversational Replanning Bar */}
      <div className="plan-replan-bar">
        <div className="replan-header-row">
          <span className="replan-title">
            <SlidersHorizontal size={13} /> Conversational Replanning
          </span>
          {replanning && (
            <span className="replan-spinner-label">
              <RefreshCw size={12} className="spin-icon" /> Updating plan…
            </span>
          )}
        </div>

        {/* Quick modification action chips */}
        <div className="replan-chips-row">
          <button
            type="button"
            className="replan-chip"
            disabled={replanning}
            onClick={() => onReplan && onReplan('Make it cheaper')}
          >
            <TrendingDown size={12} /> Make it cheaper
          </button>
          <button
            type="button"
            className="replan-chip"
            disabled={replanning}
            onClick={() => onReplan && onReplan('Make Day 2 more relaxed')}
          >
            <Coffee size={12} /> Relax Day 2
          </button>
          <button
            type="button"
            className="replan-chip"
            disabled={replanning}
            onClick={() => onReplan && onReplan('Add more cultural activities')}
          >
            <Landmark size={12} /> Add culture
          </button>
          <button
            type="button"
            className="replan-chip"
            disabled={replanning}
            onClick={() => onReplan && onReplan('Add more nature activities')}
          >
            <Trees size={12} /> Add nature
          </button>
          {onCompareOptions && (
            <button
              type="button"
              className="replan-chip compare-chip"
              disabled={replanning}
              onClick={onCompareOptions}
            >
              <Scale size={12} /> Compare options
            </button>
          )}
          {onOptimizeBudget && (
            <button
              type="button"
              className="replan-chip optimize-chip"
              disabled={replanning}
              onClick={onOptimizeBudget}
            >
              <SlidersHorizontal size={12} /> Optimize budget
            </button>
          )}
          {onRegenerate && (
            <button
              type="button"
              className="replan-chip regen-chip"
              disabled={replanning}
              onClick={onRegenerate}
            >
              <RefreshCw size={11} /> Regenerate activities
            </button>
          )}
        </div>

        {/* Custom instruction form */}
        <form className="replan-form" onSubmit={handleCustomReplanSubmit}>
          <input
            type="text"
            className="replan-input"
            placeholder="Type a change, e.g. 'Remove the museum', 'Free afternoon on Day 3'…"
            value={customReplanText}
            onChange={(e) => setCustomReplanText(e.target.value)}
            disabled={replanning}
          />
          <button
            type="submit"
            className="replan-submit-btn"
            disabled={replanning || !customReplanText.trim()}
          >
            <span>Modify</span>
            <ArrowRight size={13} />
          </button>
        </form>

        {replanError && (
          <div className="replan-error-banner" role="alert">
            <AlertCircle size={14} />
            <span>{replanError}</span>
          </div>
        )}
      </div>

      {/* Transport highlights */}
      {plan.transport.length > 0 && (
        <div className="plan-section transport-section">
          <h5>
            <Plane size={14} /> Grounded Transport
          </h5>
          <div className="transport-list">
            {plan.transport.map((t, idx) => (
              <div key={t.id ? `${t.id}-${idx}` : `trans-${idx}`} className="transport-row">
                <div className="t-main">
                  <strong>{t.carrier || 'Flight'} {t.reference || ''}</strong>
                  <span>{t.origin} ({t.originCode || ''}) → {t.destination} ({t.destCode || ''})</span>
                </div>
                <div className="t-time">
                  <span>{t.departsAt?.slice(11, 16) || t.departsAt} - {t.arrivesAt?.slice(11, 16) || t.arrivesAt}</span>
                  {t.knownPrice && <em className="t-price">{t.currency} {t.knownPrice}</em>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Accommodation highlights */}
      {plan.accommodation.length > 0 && (
        <div className="plan-section accommodation-section">
          <h5>
            <Building2 size={14} /> Grounded Accommodation
          </h5>
          <div className="accommodation-list">
            {plan.accommodation.map((a, idx) => (
              <div key={a.id ? `${a.id}-${idx}` : `acc-${idx}`} className="accommodation-row">
                <div className="a-main">
                  <strong>{a.hotelName}</strong>
                  {a.address && <span className="a-addr"><MapPin size={11} /> {a.address}</span>}
                </div>
                <div className="a-stay">
                  <span>{a.checkInDate} to {a.checkOutDate}</span>
                  {a.knownPrice && <em className="a-price">{a.currency} {a.knownPrice}</em>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Daily Itinerary breakdown */}
      <div className="plan-days-container">
        <div className="days-header-row">
          <h5>Daily Schedule</h5>

          {/* Day Tabs */}
          {plan.days.length > 1 && onDayFilterChange && (
            <div className="day-filter-tabs">
              <button
                type="button"
                className={`day-tab ${activeDayFilter === null ? 'active' : ''}`}
                onClick={() => onDayFilterChange(null)}
              >
                All Days
              </button>
              {plan.days.map((d, dIdx) => (
                <button
                  key={`day-tab-${d.dayNumber}-${dIdx}`}
                  type="button"
                  className={`day-tab ${activeDayFilter === d.dayNumber ? 'active' : ''}`}
                  onClick={() => onDayFilterChange(d.dayNumber)}
                >
                  Day {d.dayNumber}
                </button>
              ))}
            </div>
          )}
        </div>

        {filteredDays.length === 0 ? (
          <p className="no-days-text">No itinerary days scheduled for this filter.</p>
        ) : (
          <div className="days-accordion">
            {filteredDays.map((day, dayIdx) => {
              const activityCount = day.activities.length
              let totalDurationMins = 0
              day.activities.forEach((a) => {
                const s = parseMinutes(a.startTime ?? undefined)
                const e = parseMinutes(a.endTime ?? undefined)
                if (a.durationMinutes && a.durationMinutes > 0) {
                  totalDurationMins += a.durationMinutes
                } else if (s !== null && e !== null && e > s) {
                  totalDurationMins += (e - s)
                }
              })
              const durationLabel = totalDurationMins > 0
                ? `${Math.floor(totalDurationMins / 60)}h ${totalDurationMins % 60 ? `${totalDurationMins % 60}m` : ''} planned`
                : null
              const pace = activityCount <= 4 ? 'Relaxed pace' : activityCount <= 6 ? 'Balanced pace' : 'Active pace'

              return (
                <div key={`day-card-${day.dayNumber}-${dayIdx}`} className="day-card">
                  <div className="day-card-header">
                    <div className="day-title-group">
                      <span className="day-pill">Day {day.dayNumber}</span>
                      <strong className="day-title">{day.title}</strong>
                    </div>
                    <span className="day-date">{day.date}</span>
                  </div>

                  {/* Daily Summary Metrics Strip */}
                  <div className="day-summary-strip">
                    <span className="summary-pill count">
                      <Layers size={11} /> {activityCount} events
                    </span>
                    {durationLabel && (
                      <span className="summary-pill duration">
                        <Clock size={11} /> {durationLabel}
                      </span>
                    )}
                    <span className={`summary-pill pace ${pace.toLowerCase().replace(' ', '-')}`}>
                      {pace}
                    </span>
                  </div>

                  <div className="day-activities-list">
                    {day.activities.length === 0 ? (
                      <div className="activity-item empty-activity">
                        <Clock size={12} />
                        <span>No activities planned for this period</span>
                      </div>
                    ) : (
                      day.activities.map((act, actIdx) => {
                        const isSelected = selectedActivity?.id === act.id
                        const hasCoords = typeof act.latitude === 'number' && typeof act.longitude === 'number'
                        const durationText = formatDuration(act.startTime ?? undefined, act.endTime ?? undefined, act.durationMinutes ?? undefined)

                        return (
                          <div
                            key={`act-${day.dayNumber}-${act.id || actIdx}`}
                            className={`activity-item category-${act.category} ${isSelected ? 'selected' : ''}`}
                            onClick={() => onSelectActivity && onSelectActivity(act)}
                            style={{ cursor: 'pointer' }}
                          >
                            <div className="activity-icon-col">
                              {getActivityIcon(act.category, act.title)}
                            </div>
                            <div className="activity-time-col">
                              {act.startTime ? (
                                <span className="activity-time">
                                  {act.startTime}
                                  {act.endTime ? ` - ${act.endTime}` : ''}
                                </span>
                              ) : (
                                <span className="activity-time untimed">—</span>
                              )}
                              {durationText && (
                                <span className="activity-duration-pill">{durationText}</span>
                              )}
                            </div>
                            <div className="activity-content-col">
                              <div className="act-header">
                                <span className={`cat-tag tag-${act.category}`}>{act.category}</span>
                                <strong className="act-title">{act.title}</strong>
                                {act.source && (
                                  <span className="source-tag" title={`Source: ${act.source}`}>
                                    {act.source === 'catalog' ? 'Grounded' : act.source}
                                  </span>
                                )}
                              </div>
                              {act.description && <p className="act-desc">{act.description}</p>}
                              <div className="act-meta-row">
                                {act.location && (
                                  <span className="act-loc">
                                    <MapPin size={10} /> {act.location}
                                  </span>
                                )}
                                {hasCoords && onSelectActivity && (
                                  <button
                                    type="button"
                                    className="focus-map-btn"
                                    onClick={() => onSelectActivity(act)}
                                    title="Focus location on interactive map"
                                  >
                                    <Navigation size={10} />
                                    <span>View on Map</span>
                                  </button>
                                )}
                              </div>
                            </div>
                            {(act.authoritativeCost || act.estimatedCost) && (
                              <div className="act-cost-col">
                                <em>
                                  {act.currency} {act.authoritativeCost || act.estimatedCost}
                                </em>
                              </div>
                            )}
                          </div>
                        )
                      })
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}
