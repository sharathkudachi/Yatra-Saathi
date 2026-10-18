import React, { useEffect, useState } from 'react'
import { preferenceService } from '../services/preferenceService'
import type { DestinationExploreResponse, POIExploreItem } from '../types/travel'

interface DestinationExplorerCardProps {
  destination: string
  itineraryId?: string
  totalDays?: number
  onSelectCoordinates?: (lat: number, lng: number, title: string) => void
  onActivityAdded?: () => void
}

export const DestinationExplorerCard: React.FC<DestinationExplorerCardProps> = ({
  destination,
  itineraryId,
  totalDays = 3,
  onSelectCoordinates,
  onActivityAdded,
}) => {
  const [data, setData] = useState<DestinationExploreResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedCategory, setSelectedCategory] = useState<string>('all')
  const [addingPoiId, setAddingPoiId] = useState<string | null>(null)
  const [targetDay, setTargetDay] = useState<number>(2)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)

  useEffect(() => {
    const hasToken = typeof localStorage !== 'undefined' && !!localStorage.getItem('yatra-auth-token')
    if (destination && hasToken) {
      loadDestination(destination, selectedCategory)
    }
  }, [destination, selectedCategory])

  const loadDestination = async (dest: string, cat: string) => {
    try {
      setLoading(true)
      setError(null)
      const res = await preferenceService.exploreDestination({
        destination: dest,
        categoryFilter: cat === 'all' ? undefined : cat,
        limit: 20,
      })
      setData(res)
    } catch (err: any) {
      setError(err?.message || 'Failed to explore destination')
    } finally {
      setLoading(false)
    }
  }

  const handleAddActivity = async (poi: POIExploreItem) => {
    if (!itineraryId) return
    try {
      setAddingPoiId(poi.poi_id)
      setError(null)
      await preferenceService.addActivityToItinerary(itineraryId, poi.poi_id, targetDay)
      setActionSuccess(`Added "${poi.title}" to Day ${targetDay}`)
      setTimeout(() => setActionSuccess(null), 3000)
      if (onActivityAdded) onActivityAdded()
    } catch (err: any) {
      setError(err?.message || 'Failed to add activity')
    } finally {
      setAddingPoiId(null)
    }
  }

  const handleFocusMap = (poi: POIExploreItem) => {
    if (poi.latitude && poi.longitude && onSelectCoordinates) {
      onSelectCoordinates(poi.latitude, poi.longitude, poi.title)
    }
  }

  const categories = ['all', 'sightseeing', 'culture', 'nature', 'food', 'relaxation', 'adventure', 'shopping']

  return (
    <div className="destination-explorer-card">
      <div className="explorer-header">
        <div className="explorer-title-box">
          <span className="explorer-badge">AUTHORITATIVE CATALOG</span>
          <h3>Explore {destination}</h3>
          <p className="explorer-subtitle">
            Grounded local attractions & activities validated from backend reference records.
          </p>
        </div>
        {data && data.latitude && data.longitude && (
          <button
            type="button"
            className="btn-map-focus"
            onClick={() => onSelectCoordinates && onSelectCoordinates(data.latitude!, data.longitude!, data.destination)}
          >
            📍 Center City Map
          </button>
        )}
      </div>

      {actionSuccess && <div className="preferences-success-banner">{actionSuccess}</div>}
      {error && <div className="preferences-error-banner">{error}</div>}

      {/* Category Filter Pills */}
      <div className="category-filter-bar">
        {categories.map((cat) => (
          <button
            key={cat}
            type="button"
            className={`category-pill ${selectedCategory === cat ? 'active' : ''}`}
            onClick={() => setSelectedCategory(cat)}
          >
            {cat.charAt(0).toUpperCase() + cat.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="explorer-loading">Loading authoritative attractions for {destination}...</div>
      ) : !data || data.activities.length === 0 ? (
        <div className="explorer-empty">No catalog activities found matching this category filter.</div>
      ) : (
        <div className="poi-cards-grid">
          {data.activities.map((poi) => (
            <div key={poi.poi_id} className="poi-item-card">
              <div className="poi-card-top">
                <span className="poi-cat-badge">{poi.category.toUpperCase()}</span>
                <span className="poi-cost-tag">
                  {poi.cost === '0.00' ? 'Free Admission' : `${poi.currency} ${poi.cost}`}
                </span>
              </div>

              <h4 className="poi-title">{poi.title}</h4>
              <p className="poi-desc">{poi.description || `Verified local attraction in ${poi.city_name}`}</p>

              <div className="poi-meta-row">
                <span>⏱ {poi.duration_minutes || 90} mins</span>
                {poi.times_planned > 0 && <span>👥 Highly Recommended ({poi.times_planned} visits)</span>}
              </div>

              {poi.preference_matches && poi.preference_matches.length > 0 && (
                <div className="poi-match-box">
                  {poi.preference_matches.map((m, idx) => (
                    <span key={idx} className="poi-match-pill">
                      ✓ {m.evidence}
                    </span>
                  ))}
                </div>
              )}

              <div className="poi-card-actions">
                {poi.latitude && poi.longitude && (
                  <button
                    type="button"
                    className="btn-poi-map"
                    onClick={() => handleFocusMap(poi)}
                    title="View coordinates on map"
                  >
                    📍 Show Map
                  </button>
                )}

                {itineraryId && (
                  <div className="add-to-day-box">
                    <select
                      className="day-select"
                      value={targetDay}
                      onChange={(e) => setTargetDay(parseInt(e.target.value, 10))}
                      disabled={addingPoiId === poi.poi_id}
                    >
                      {Array.from({ length: totalDays }, (_, i) => i + 1).map((d) => (
                        <option key={d} value={d}>
                          Day {d}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn-add-activity"
                      onClick={() => handleAddActivity(poi)}
                      disabled={addingPoiId === poi.poi_id}
                    >
                      {addingPoiId === poi.poi_id ? 'Adding...' : '+ Add to Itinerary'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
