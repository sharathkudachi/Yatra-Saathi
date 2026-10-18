import { useEffect, useState } from 'react'
import {
  AlertCircle,
  ArrowRight,
  Calendar,
  CheckCircle2,
  Clock,
  Download,
  Hotel,
  Layers,
  MapPin,
  Plane,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import {
  bookingService,
  type BookingReviewResponse,
  type BookingTraveller,
  type ConfirmBookingResponse,
} from '../services/bookingService'
import { formatMoney } from '../utils/format'

type Props = {
  itineraryId: string
  itineraryVersion: number
  currency?: string
  onClose: () => void
  onBookingConfirmed?: (confirmed: ConfirmBookingResponse) => void
  onOpenTripPack?: (bookingId: string) => void
  onRequireAuth?: (mode: 'signin' | 'register') => void
}

function useCountdown(expiresAtIso: string | undefined) {
  const [timeLeft, setTimeLeft] = useState('')
  useEffect(() => {
    if (!expiresAtIso) return
    const update = () => {
      const ms = Date.parse(expiresAtIso) - Date.now()
      if (ms <= 0) {
        setTimeLeft('Expired')
      } else {
        const totalSec = Math.floor(ms / 1000)
        const mins = Math.floor(totalSec / 60)
        const secs = totalSec % 60
        setTimeLeft(`${mins}:${String(secs).padStart(2, '0')}`)
      }
    }
    update()
    const timer = setInterval(update, 1000)
    return () => clearInterval(timer)
  }, [expiresAtIso])
  return timeLeft
}

export default function BookingReviewModal({
  itineraryId,
  itineraryVersion,
  currency: _currency = 'INR',
  onClose,
  onBookingConfirmed,
  onOpenTripPack,
  onRequireAuth,
}: Props) {
  const [travellers, setTravellers] = useState<BookingTraveller[]>([
    { displayName: 'Primary Traveller', travellerRole: 'adult' },
  ])
  const [review, setReview] = useState<BookingReviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [authRequired, setAuthRequired] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmedBooking, setConfirmedBooking] = useState<ConfirmBookingResponse | null>(null)

  const countdown = useCountdown(review?.reviewExpiresAt)

  // Fetch initial review
  const loadReview = async (customTravellers = travellers) => {
    setLoading(true)
    setError(null)
    setAuthRequired(false)
    try {
      // Require explicit authenticated identity; a guest must NEVER silently become usr_demo0001
      const token = typeof localStorage !== 'undefined' ? localStorage.getItem('yatra-auth-token') : null
      if (!token) {
        setAuthRequired(true)
        setLoading(false)
        return
      }
      const data = await bookingService.getBookingReview(itineraryId, itineraryVersion, customTravellers)
      setReview(data)
    } catch (err: any) {
      const msg = String(err?.message || '')
      if (msg.includes('TOKEN_MISSING') || msg.includes('missing bearer token') || msg.includes('401') || msg.includes('Unauthorized')) {
        setAuthRequired(true)
      } else if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('fetch')) {
        setError('Unable to load booking review details. The backend service may be reconnecting.')
      } else {
        setError(msg || 'Could not generate booking review. Please verify itinerary.')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadReview()
  }, [itineraryId, itineraryVersion])

  const handleAddTraveller = () => {
    if (travellers.length >= 10) return
    const next: BookingTraveller[] = [
      ...travellers,
      { displayName: `Traveller ${travellers.length + 1}`, travellerRole: 'adult' },
    ]
    setTravellers(next)
    void loadReview(next)
  }

  const handleUpdateTravellerName = (idx: number, name: string) => {
    const next = [...travellers]
    next[idx].displayName = name
    setTravellers(next)
  }

  const handleConfirmReservation = async () => {
    if (!review) return
    setConfirming(true)
    setError(null)
    try {
      const idempotencyKey = `idemp_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`
      const res = await bookingService.confirmBooking(
        review.reviewToken,
        review.itineraryId,
        review.itineraryVersion,
        review.authoritativeTotal,
        review.currency,
        travellers,
        idempotencyKey,
      )
      setConfirmedBooking(res)
      if (onBookingConfirmed) onBookingConfirmed(res)
    } catch (err: any) {
      setError(err?.message || 'Booking confirmation failed. Please refresh review.')
    } finally {
      setConfirming(false)
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="booking-review-title">
      <div className="booking-review-modal">
        {/* Header */}
        <div className="modal-header">
          <div className="title-group">
            <h2 id="booking-review-title">Review & Reserve Demo Booking</h2>
            <div className="demo-badge">
              <ShieldAlert size={13} />
              <span>DEMO / SIMULATED — NO REAL PAYMENT</span>
            </div>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Content Body */}
        <div className="modal-body">
          {error && (
            <div className="booking-error-banner" role="alert">
              <AlertCircle size={16} />
              <span style={{ flex: 1 }}>{error}</span>
              <button
                type="button"
                className="retry-review-btn"
                onClick={() => void loadReview()}
                style={{
                  background: 'var(--color-primary-600, #2563eb)',
                  color: '#fff',
                  border: 'none',
                  padding: '4px 10px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                <RefreshCw size={12} /> Retry
              </button>
            </div>
          )}

          {confirmedBooking ? (
            /* Confirmed Success State */
            <div className="booking-success-view">
              <div className="success-icon-box">
                <CheckCircle2 size={48} className="success-icon" />
              </div>
              <h3>Demo Reservation Confirmed!</h3>
              <p className="success-subtitle">
                Your simulated Yatra Saathi reservation has been recorded with authoritative integrity.
              </p>

              <div className="booking-reference-card">
                <span className="ref-label">DEMO BOOKING REFERENCE</span>
                <strong className="ref-value">{confirmedBooking.bookingReference}</strong>
                <span className="ref-note">Backend authoritative identifier · Non-sensitive demo record</span>
              </div>

              <div className="confirmed-meta-grid">
                <div>
                  <span className="meta-label">Authoritative Total</span>
                  <span className="meta-val">
                    {formatMoney(confirmedBooking.authoritativeTotal, confirmedBooking.currency)}
                  </span>
                </div>
                <div>
                  <span className="meta-label">Status</span>
                  <span className="meta-val status-confirmed">Confirmed</span>
                </div>
                <div>
                  <span className="meta-label">Travellers</span>
                  <span className="meta-val">{travellers.length} Guest(s)</span>
                </div>
              </div>

              <div className="success-actions">
                {onOpenTripPack && (
                  <button
                    type="button"
                    className="trip-pack-button"
                    onClick={() => onOpenTripPack(confirmedBooking.bookingId)}
                  >
                    <Download size={14} />
                    <span>View Trip Pack</span>
                  </button>
                )}
                <button type="button" className="close-success-btn" onClick={onClose}>
                  Done
                </button>
              </div>
            </div>
          ) : authRequired ? (
            <div className="booking-auth-required-view" style={{ textAlign: 'center', padding: '36px 20px' }}>
              <div style={{ marginBottom: '16px' }}>
                <ShieldAlert size={48} color="#bb8750" />
              </div>
              <h3 style={{ fontSize: '18px', color: '#1e293b', marginBottom: '8px' }}>Authentication Required</h3>
              <p className="auth-required-prompt" style={{ fontSize: '13px', color: '#64748b', maxWidth: '380px', margin: '0 auto 24px', lineHeight: 1.5 }}>
                Sign in or create an account to continue with booking.
              </p>
              <div className="auth-prompt-buttons" style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                <button
                  type="button"
                  className="modal-primary btn-auth-signin"
                  style={{ minWidth: '130px' }}
                  onClick={() => {
                    if (onRequireAuth) onRequireAuth('signin')
                    onClose()
                  }}
                >
                  Sign In
                </button>
                <button
                  type="button"
                  className="modal-secondary btn-auth-create"
                  style={{ minWidth: '130px', background: '#f1f5f9', border: '1px solid #cbd5e1', color: '#334155' }}
                  onClick={() => {
                    if (onRequireAuth) onRequireAuth('register')
                    onClose()
                  }}
                >
                  Create Account
                </button>
              </div>
            </div>
          ) : loading ? (
            <div className="review-loading-view">
              <RefreshCw size={24} className="spin-icon" />
              <p>Recalculating authoritative catalog rates and validating inventory…</p>
            </div>
          ) : review ? (
            /* Review & Breakdown View */
            <div className="review-breakdown-view">
              {/* Trip Overview Pill */}
              <div className="review-route-card">
                <div className="route-endpoints">
                  <MapPin size={16} />
                  <span>
                    <strong>{review.origin}</strong> → <strong>{review.destination}</strong>
                  </span>
                </div>
                <div className="route-dates">
                  <Calendar size={14} />
                  <span>
                    {review.startDate} to {review.endDate}
                  </span>
                </div>
                {countdown && (
                  <div className={`countdown-chip ${countdown === 'Expired' ? 'expired' : ''}`}>
                    <Clock size={12} />
                    <span>Rate Hold: {countdown}</span>
                  </div>
                )}
                <div className="review-token-pill" style={{ fontSize: '11px', color: '#556b2f', display: 'flex', alignItems: 'center', gap: '5px', padding: '3px 8px', background: '#f4f7f0', borderRadius: '4px' }}>
                  <ShieldCheck size={13} />
                  <span>Verified Token: <strong className="review-token-tag">{review.reviewToken.slice(0, 18)}…</strong></span>
                </div>
              </div>

              {/* Travellers Configuration */}
              <div className="review-section">
                <div className="section-header">
                  <Users size={15} />
                  <h4>Travellers ({travellers.length})</h4>
                  <button type="button" className="add-traveller-btn" onClick={handleAddTraveller}>
                    <UserPlus size={13} /> Add Guest
                  </button>
                </div>
                <div className="travellers-list">
                  {travellers.map((trv, idx) => (
                    <div key={idx} className="traveller-row">
                      <span className="trv-seq">#{idx + 1}</span>
                      <input
                        type="text"
                        value={trv.displayName}
                        onChange={(e) => handleUpdateTravellerName(idx, e.target.value)}
                        placeholder="Full Legal / Display Name"
                        aria-label={`Traveller ${idx + 1} Name`}
                      />
                      <span className="trv-role-badge">{trv.travellerRole}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Component Breakdowns */}
              <div className="review-section">
                <div className="section-header">
                  <Layers size={15} />
                  <h4>Booking Components</h4>
                </div>
                <div className="items-breakdown-list">
                  {review.items.map((item, idx) => (
                    <div key={idx} className={`breakdown-item ${item.item_type}`}>
                      <div className="item-type-icon">
                        {item.item_type === 'flight' || item.item_type === 'transport' ? (
                          <Plane size={15} />
                        ) : item.item_type === 'hotel' ? (
                          <Hotel size={15} />
                        ) : (
                          <MapPin size={15} />
                        )}
                      </div>
                      <div className="item-info">
                        <strong>{item.title}</strong>
                        {item.for_date && <span className="item-date">{item.for_date}</span>}
                      </div>
                      <div className="item-cost">
                        {item.authoritative_price ? (
                          <span className="auth-price">
                            {formatMoney(item.authoritative_price, item.currency)}
                          </span>
                        ) : item.estimated_price ? (
                          <span className="est-price" title="Estimated, not authoritative">
                            ~{formatMoney(item.estimated_price, item.currency)} (est.)
                          </span>
                        ) : (
                          <span className="included">Included</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Cost Summary Box */}
              <div className="review-cost-box">
                <div className="cost-line">
                  <span>Authoritative Subtotal</span>
                  <strong>{formatMoney(review.authoritativeSubtotal, review.currency)}</strong>
                </div>
                <div className="cost-line">
                  <span>Tax & Fees (12% standard)</span>
                  <span>{formatMoney(review.taxAmount, review.currency)}</span>
                </div>
                {review.estimatedActivitiesTotal !== '0.00' && (
                  <div className="cost-line estimated-note">
                    <span>Estimated Activities (Pay on Site)</span>
                    <span>~{formatMoney(review.estimatedActivitiesTotal, review.currency)}</span>
                  </div>
                )}
                <div className="cost-line total-line">
                  <span>Authoritative Total Due (Simulated)</span>
                  <strong className="grand-total review-total-value">
                    {formatMoney(review.authoritativeTotal, review.currency)}
                  </strong>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        {/* Modal Footer Actions */}
        {!confirmedBooking && review && (
          <div className="modal-footer">
            <button type="button" className="cancel-btn" onClick={onClose} disabled={confirming}>
              Go Back
            </button>
            <button
              type="button"
              className="confirm-btn"
              onClick={handleConfirmReservation}
              disabled={confirming || countdown === 'Expired'}
            >
              {confirming ? (
                <>
                  <RefreshCw size={14} className="spin-icon" /> Securing Inventory Hold…
                </>
              ) : (
                <>
                  <UserCheck size={14} /> Confirm & Reserve Demo Booking <ArrowRight size={14} />
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
