import React, { useEffect, useState } from 'react'
import { MapPin } from 'lucide-react'
import { preferenceService } from '../services/preferenceService'
import type { HotelExploreItem, HotelExploreResponse } from '../types/travel'

interface HotelExplorerCardProps {
  destination: string
  startDate: string
  endDate: string
  travellers?: number
  itineraryId?: string
  currency?: string
  onSelectCoordinates?: (lat: number, lng: number, title: string) => void
  onHotelSelected?: () => void
}

export const HotelExplorerCard: React.FC<HotelExplorerCardProps> = ({
  destination,
  startDate,
  endDate,
  travellers = 1,
  itineraryId,
  currency = 'INR',
  onSelectCoordinates,
  onHotelSelected,
}) => {
  const [data, setData] = useState<HotelExploreResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectingHotelId, setSelectingHotelId] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [minStars, setMinStars] = useState<number | undefined>(undefined)

  useEffect(() => {
    const hasToken = typeof localStorage !== 'undefined' && !!localStorage.getItem('yatra-auth-token')
    if (destination && startDate && endDate && hasToken) {
      loadHotels(minStars)
    }
  }, [destination, startDate, endDate, minStars])

  const loadHotels = async (stars?: number) => {
    try {
      setLoading(true)
      setError(null)
      const res = await preferenceService.exploreHotels({
        destination,
        startDate,
        endDate,
        travellers,
        currency,
        minStars: stars,
        limit: 15,
      })
      setData(res)
    } catch (err: any) {
      setError(err?.message || 'Failed to explore hotels')
    } finally {
      setLoading(false)
    }
  }

  const handleSelectHotel = async (hotel: HotelExploreItem) => {
    if (!itineraryId) return
    try {
      setSelectingHotelId(hotel.hotel_id)
      setError(null)
      await preferenceService.selectHotelForItinerary(itineraryId, hotel.hotel_id, hotel.room_type_id)
      setActionSuccess(`Switched itinerary hotel to "${hotel.name}"`)
      setTimeout(() => setActionSuccess(null), 3000)
      if (onHotelSelected) onHotelSelected()
    } catch (err: any) {
      setError(err?.message || 'Failed to select hotel')
    } finally {
      setSelectingHotelId(null)
    }
  }

  const handleFocusMap = (hotel: HotelExploreItem) => {
    if (hotel.latitude && hotel.longitude && onSelectCoordinates) {
      onSelectCoordinates(hotel.latitude, hotel.longitude, hotel.name)
    }
  }

  return (
    <div className="hotel-explorer-card">
      <div className="explorer-header">
        <div className="explorer-title-box">
          <span className="explorer-badge">AUTHORITATIVE INVENTORY</span>
          <h3>Explore Hotels in {destination}</h3>
          <p className="explorer-subtitle">
            Live catalog inventory matched against your saved travel preferences.
          </p>
        </div>
        <div className="hotel-filter-group">
          <button
            type="button"
            className={`category-pill ${minStars === undefined ? 'active' : ''}`}
            onClick={() => setMinStars(undefined)}
          >
            All Ratings
          </button>
          <button
            type="button"
            className={`category-pill ${minStars === 4 ? 'active' : ''}`}
            onClick={() => setMinStars(4)}
          >
            4★+ Only
          </button>
          <button
            type="button"
            className={`category-pill ${minStars === 5 ? 'active' : ''}`}
            onClick={() => setMinStars(5)}
          >
            5★ Luxury
          </button>
        </div>
      </div>

      {actionSuccess && <div className="preferences-success-banner">{actionSuccess}</div>}
      {error && <div className="preferences-error-banner">{error}</div>}

      {loading ? (
        <div className="explorer-loading">Searching available hotel rooms in {destination}...</div>
      ) : !data || data.hotels.length === 0 ? (
        <div className="explorer-empty">No hotels found matching the selected dates and criteria.</div>
      ) : (
        <div className="hotel-cards-grid">
          {data.hotels.map((hotel) => (
            <div key={hotel.hotel_id} className="hotel-detail-card">
              <div className="hotel-card-header">
                <div>
                  <h4 className="hotel-title">{hotel.name}</h4>
                  <div className="hotel-stars-row">
                    <span className="hotel-stars">
                      {'★'.repeat(Math.round(hotel.star_rating || 3))}
                      {'☆'.repeat(5 - Math.round(hotel.star_rating || 3))}
                    </span>
                    <span className="hotel-guest-score">
                      {hotel.guest_score ? `${hotel.guest_score.toFixed(1)}/10 Guest Score` : 'Recommended'}
                    </span>
                    {hotel.distance_to_centre_km && (
                      <span className="hotel-dist-badge">
                        <MapPin size={11} className="inline-pin-icon" /> {hotel.distance_to_centre_km.toFixed(1)} km to centre
                      </span>
                    )}
                  </div>
                </div>
                <div className="hotel-pricing-box">
                  <div className="hotel-nightly-rate">
                    {hotel.currency} {hotel.nightly_price} <span className="rate-sub">/night</span>
                  </div>
                  <div className="hotel-stay-total">
                    Total stay: {hotel.currency} {hotel.total_stay_price}
                  </div>
                </div>
              </div>

              <div className="hotel-room-line">
                <span className="room-label">Room Type:</span> <strong>{hotel.room_name}</strong>
                {hotel.address_line && <span className="hotel-address"> · {hotel.address_line}</span>}
              </div>

              {/* Preference match justification */}
              {hotel.why_it_matches && hotel.why_it_matches.length > 0 && (
                <div className="why-it-matches-box">
                  <span className="why-title">Why it matches your profile:</span>
                  <ul className="why-list">
                    {hotel.why_it_matches.map((reason, idx) => (
                      <li key={idx}>✓ {reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="hotel-card-actions">
                {hotel.latitude && hotel.longitude && (
                  <button
                    type="button"
                    className="btn-poi-map"
                    onClick={() => handleFocusMap(hotel)}
                  >
                    <MapPin size={13} /> Show on Map
                  </button>
                )}

                {itineraryId && (
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => handleSelectHotel(hotel)}
                    disabled={selectingHotelId === hotel.hotel_id}
                  >
                    {selectingHotelId === hotel.hotel_id ? 'Updating Itinerary...' : 'Select this Hotel'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
