import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  Calendar,
  Hotel,
  MapPin,
  Plane,
  Printer,
  RefreshCw,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react'
import { bookingService, type TripPackResponse } from '../services/bookingService'
import { formatMoney } from '../utils/format'

type Props = {
  bookingId: string
  onClose: () => void
}

export default function TripPackModal({ bookingId, onClose }: Props) {
  const [pack, setPack] = useState<TripPackResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    bookingService
      .getTripPack(bookingId)
      .then((data) => {
        if (alive) setPack(data)
      })
      .catch((err: any) => {
        if (alive) setError(err?.message || 'Could not load trip pack.')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [bookingId])

  const handlePrint = () => {
    const url = bookingService.getTripPackExportUrl(bookingId)
    window.open(url, '_blank')
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="trip-pack-modal-title">
      <div className="trip-pack-modal">
        {/* Header */}
        <div className="modal-header">
          <div className="title-group">
            <h2 id="trip-pack-modal-title">Yatra Saathi Demo Trip Pack</h2>
            <div className="demo-badge">
              <ShieldCheck size={13} />
              <span>SIMULATED SUMMARY · NOT AN OFFICIAL TRAVEL DOCUMENT</span>
            </div>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="modal-body">
          {error && (
            <div className="booking-error-banner" role="alert">
              <AlertTriangle size={16} />
              <span>{error}</span>
            </div>
          )}

          {loading ? (
            <div className="review-loading-view">
              <RefreshCw size={24} className="spin-icon" />
              <p>Compiling structured trip pack and travel summaries…</p>
            </div>
          ) : pack ? (
            <div className="trip-pack-document">
              {/* Official Disclaimer Banner */}
              <div className="trip-pack-disclaimer">
                <AlertTriangle size={18} className="warn-icon" />
                <div className="disclaimer-text">
                  <strong>{pack.demoLabel}</strong>
                  <p>{pack.demoNotice}</p>
                </div>
              </div>

              {/* Reference Header */}
              <div className="doc-meta-banner">
                <div className="doc-route">
                  <h3>{pack.destination}</h3>
                  <p>
                    <MapPin size={13} /> From {pack.origin} &bull; <Calendar size={13} /> {pack.startDate} to{' '}
                    {pack.endDate}
                  </p>
                </div>
                <div className="doc-reference">
                  <span className="ref-label">BOOKING REFERENCE</span>
                  <strong className="ref-val">{pack.bookingReference}</strong>
                </div>
              </div>

              {/* Travellers */}
              <div className="doc-section">
                <h4>
                  <Users size={14} /> Registered Travellers
                </h4>
                <ul className="doc-traveller-list">
                  {pack.travellers.map((trv, idx) => (
                    <li key={idx}>
                      <strong>{trv.display_name}</strong> ({trv.traveller_role})
                    </li>
                  ))}
                </ul>
              </div>

              {/* Transport Summary */}
              <div className="doc-section">
                <h4>
                  <Plane size={14} /> Transport & Flights
                </h4>
                {pack.transportSummary.length > 0 ? (
                  <table className="doc-table">
                    <thead>
                      <tr>
                        <th>Item</th>
                        <th>Authoritative Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pack.transportSummary.map((item, idx) => (
                        <tr key={idx}>
                          <td>{item.title}</td>
                          <td>
                            {item.authoritative_price
                              ? formatMoney(item.authoritative_price, item.currency)
                              : 'Included'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="no-items-note">No scheduled transport segments.</p>
                )}
              </div>

              {/* Accommodation Summary */}
              <div className="doc-section">
                <h4>
                  <Hotel size={14} /> Accommodation
                </h4>
                {pack.accommodationSummary.length > 0 ? (
                  <table className="doc-table">
                    <thead>
                      <tr>
                        <th>Property</th>
                        <th>Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pack.accommodationSummary.map((item, idx) => (
                        <tr key={idx}>
                          <td>{item.title}</td>
                          <td>
                            {item.authoritative_price
                              ? formatMoney(item.authoritative_price, item.currency)
                              : 'Included'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="no-items-note">No hotel bookings included.</p>
                )}
              </div>

              {/* Total Box */}
              <div className="doc-total-box">
                <span className="total-label">Authoritative Trip Total</span>
                <strong className="total-amount">
                  {formatMoney(pack.authoritativeTotal, pack.currency)}
                </strong>
              </div>

              {/* Notes */}
              <div className="doc-section notes-section">
                <h4>Important Information</h4>
                <ul className="doc-notes-list">
                  {pack.importantNotes.map((note, idx) => (
                    <li key={idx}>{note}</li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button type="button" className="cancel-btn" onClick={onClose}>
            Close
          </button>
          {pack && (
            <button type="button" className="export-html-btn" onClick={handlePrint}>
              <Printer size={14} />
              <span>Print / Export HTML</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
