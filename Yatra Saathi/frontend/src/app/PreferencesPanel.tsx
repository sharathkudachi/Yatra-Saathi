import React, { useEffect, useState } from 'react'
import { preferenceService } from '../services/preferenceService'
import type { PreferenceItem, UserTravelProfile } from '../types/travel'

interface PreferencesPanelProps {
  isOpen?: boolean
  onClose?: () => void
  onPreferencesUpdated?: () => void
}

export const PreferencesPanel: React.FC<PreferencesPanelProps> = ({ isOpen, onClose, onPreferencesUpdated }) => {
  const [profile, setProfile] = useState<UserTravelProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Editable local state
  const [directFlights, setDirectFlights] = useState(false)
  const [directIsHard, setDirectIsHard] = useState(false)
  const [minStars, setMinStars] = useState(3.0)
  const [minGuestScore, setMinGuestScore] = useState(7.0)
  const [dailyPace, setDailyPace] = useState('moderate')
  const [comfortPriority, setComfortPriority] = useState('moderate')
  const [pricePriority, setPricePriority] = useState('moderate')
  const [categories, setCategories] = useState<string[]>(['sightseeing', 'culture'])
  const [dontChangeHotels, setDontChangeHotels] = useState(false)

  const availableCategories = ['sightseeing', 'culture', 'nature', 'food', 'relaxation', 'adventure', 'shopping']

  useEffect(() => {
    loadPreferences()
  }, [])

  const loadPreferences = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await preferenceService.getPreferences()
      setProfile(data)
      const p = data.preferences || {}

      if (p.direct_flights_only) {
        setDirectFlights(Boolean(p.direct_flights_only.value))
        setDirectIsHard(Boolean(p.direct_flights_only.is_hard))
      }
      if (p.min_hotel_star_rating) {
        setMinStars(Number(p.min_hotel_star_rating.value) || 3.0)
      }
      if (p.min_hotel_guest_score) {
        setMinGuestScore(Number(p.min_hotel_guest_score.value) || 7.0)
      }
      if (p.preferred_daily_pace) {
        setDailyPace(String(p.preferred_daily_pace.value))
      }
      if (p.comfort_priority) {
        setComfortPriority(String(p.comfort_priority.value))
      }
      if (p.price_priority) {
        setPricePriority(String(p.price_priority.value))
      }
      if (p.preferred_activity_categories && Array.isArray(p.preferred_activity_categories.value)) {
        setCategories(p.preferred_activity_categories.value as string[])
      }
      if (p.dont_change_hotels) {
        setDontChangeHotels(Boolean(p.dont_change_hotels.value))
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load preferences')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      setError(null)
      const items: PreferenceItem[] = [
        {
          preference_key: 'direct_flights_only',
          value: directFlights,
          is_hard: directIsHard,
          priority: directIsHard ? 'hard' : 'high',
          confidence: 1.0,
          source: 'explicit_user',
        },
        {
          preference_key: 'min_hotel_star_rating',
          value: minStars,
          is_hard: false,
          priority: 'high',
          confidence: 1.0,
          source: 'explicit_user',
        },
        {
          preference_key: 'min_hotel_guest_score',
          value: minGuestScore,
          is_hard: false,
          priority: 'medium',
          confidence: 1.0,
          source: 'explicit_user',
        },
        {
          preference_key: 'preferred_daily_pace',
          value: dailyPace,
          is_hard: false,
          priority: 'high',
          confidence: 1.0,
          source: 'explicit_user',
        },
        {
          preference_key: 'comfort_priority',
          value: comfortPriority,
          is_hard: false,
          priority: 'medium',
          confidence: 1.0,
          source: 'explicit_user',
        },
        {
          preference_key: 'price_priority',
          value: pricePriority,
          is_hard: false,
          priority: 'medium',
          confidence: 1.0,
          source: 'explicit_user',
        },
        {
          preference_key: 'preferred_activity_categories',
          value: categories,
          is_hard: false,
          priority: 'high',
          confidence: 1.0,
          source: 'explicit_user',
        },
        {
          preference_key: 'dont_change_hotels',
          value: dontChangeHotels,
          is_hard: false,
          priority: 'medium',
          confidence: 1.0,
          source: 'explicit_user',
        },
      ]

      const updated = await preferenceService.updatePreferences(items)
      setProfile(updated)
      setSuccessMsg('Preferences saved successfully')
      setTimeout(() => setSuccessMsg(null), 3000)
      if (onPreferencesUpdated) onPreferencesUpdated()
    } catch (err: any) {
      setError(err?.message || 'Failed to save preferences')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!window.confirm('Reset all saved travel preferences to defaults?')) return
    try {
      setSaving(true)
      await preferenceService.resetPreferences()
      await loadPreferences()
      setSuccessMsg('Preferences reset to defaults')
      setTimeout(() => setSuccessMsg(null), 3000)
      if (onPreferencesUpdated) onPreferencesUpdated()
    } catch (err: any) {
      setError(err?.message || 'Failed to reset preferences')
    } finally {
      setSaving(false)
    }
  }

  const toggleCategory = (cat: string) => {
    if (categories.includes(cat)) {
      if (categories.length > 1) {
        setCategories(categories.filter((c) => c !== cat))
      }
    } else {
      setCategories([...categories, cat])
    }
  }

  if (isOpen === false) return null

  return (
    <div className="preferences-modal-backdrop" onClick={onClose}>
      <div className="preferences-panel-card" onClick={(e) => e.stopPropagation()}>
        <div className="preferences-header">
          <div className="preferences-title-group">
            <h3>Travel Preferences</h3>
            <span className="preferences-subtitle">
              Authoritative Profile {profile?.user_id ? `(${profile.user_id})` : ''} · Privacy Isolated
            </span>
          </div>
          {onClose && (
            <button className="preferences-close-btn" onClick={onClose} aria-label="Close">
              ✕
            </button>
          )}
        </div>

        {error && <div className="preferences-error-banner">{error}</div>}
        {successMsg && <div className="preferences-success-banner">{successMsg}</div>}

        {loading ? (
          <div className="preferences-loading">Loading travel preferences...</div>
        ) : (
          <div className="preferences-body">
            {/* Active summary badges */}
            <div className="preferences-badges-summary">
              <span className="pref-summary-title">Active Profile Signals:</span>
              <div className="pref-badge-row">
                {directFlights && (
                  <span className={`pref-pill ${directIsHard ? 'pref-pill-hard' : 'pref-pill-soft'}`}>
                    ✓ {directIsHard ? 'Only Direct Flights' : 'Prefer Direct Flights'}
                  </span>
                )}
                <span className="pref-pill pref-pill-soft">
                  ✓ {minStars}★+ Quality ({minGuestScore}+ score)
                </span>
                <span className="pref-pill pref-pill-soft">
                  ✓ {dailyPace.charAt(0).toUpperCase() + dailyPace.slice(1)} Pace
                </span>
                {categories.map((c) => (
                  <span key={c} className="pref-pill pref-pill-soft">
                    ✓ {c.charAt(0).toUpperCase() + c.slice(1)}
                  </span>
                ))}
              </div>
            </div>

            <div className="preferences-grid">
              {/* Flights Section */}
              <div className="preference-section">
                <h4>Flight Preferences</h4>
                <div className="pref-field">
                  <label className="pref-toggle-label">
                    <input
                      type="checkbox"
                      checked={directFlights}
                      onChange={(e) => setDirectFlights(e.target.checked)}
                    />
                    <span>Prefer direct / non-stop flights</span>
                  </label>
                </div>
                {directFlights && (
                  <div className="pref-field pref-indent">
                    <label className="pref-toggle-label">
                      <input
                        type="checkbox"
                        checked={directIsHard}
                        onChange={(e) => setDirectIsHard(e.target.checked)}
                      />
                      <span className="pref-label-hard">
                        Strict requirement (reject options with stops)
                      </span>
                    </label>
                  </div>
                )}
              </div>

              {/* Hotels Section */}
              <div className="preference-section">
                <h4>Hotel Quality & Stay</h4>
                <div className="pref-field">
                  <label>Minimum Star Rating: {minStars}★</label>
                  <input
                    type="range"
                    min="3"
                    max="5"
                    step="1"
                    value={minStars}
                    onChange={(e) => setMinStars(parseFloat(e.target.value))}
                  />
                  <div className="range-ticks">
                    <span>3★ Standard</span>
                    <span>4★ Upscale</span>
                    <span>5★ Luxury</span>
                  </div>
                </div>

                <div className="pref-field">
                  <label>Minimum Guest Score: {minGuestScore.toFixed(1)} / 10</label>
                  <input
                    type="range"
                    min="6.0"
                    max="9.0"
                    step="0.5"
                    value={minGuestScore}
                    onChange={(e) => setMinGuestScore(parseFloat(e.target.value))}
                  />
                </div>

                <div className="pref-field">
                  <label className="pref-toggle-label">
                    <input
                      type="checkbox"
                      checked={dontChangeHotels}
                      onChange={(e) => setDontChangeHotels(e.target.checked)}
                    />
                    <span>Don't change hotels during the trip</span>
                  </label>
                </div>
              </div>

              {/* Itinerary Pacing */}
              <div className="preference-section">
                <h4>Itinerary Pacing & Flow</h4>
                <div className="pref-btn-group">
                  <button
                    type="button"
                    className={`pref-select-btn ${dailyPace === 'relaxed' ? 'active' : ''}`}
                    onClick={() => setDailyPace('relaxed')}
                  >
                    Relaxed (1-2 POIs/day)
                  </button>
                  <button
                    type="button"
                    className={`pref-select-btn ${dailyPace === 'moderate' ? 'active' : ''}`}
                    onClick={() => setDailyPace('moderate')}
                  >
                    Moderate (2-3 POIs/day)
                  </button>
                  <button
                    type="button"
                    className={`pref-select-btn ${dailyPace === 'fast' ? 'active' : ''}`}
                    onClick={() => setDailyPace('fast')}
                  >
                    Fast (Cover all sights)
                  </button>
                </div>
              </div>

              {/* Preferred Activity Categories */}
              <div className="preference-section">
                <h4>Activity Interests</h4>
                <div className="pref-category-chips">
                  {availableCategories.map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      className={`pref-chip ${categories.includes(cat) ? 'selected' : ''}`}
                      onClick={() => toggleCategory(cat)}
                    >
                      {categories.includes(cat) ? '✓ ' : '+ '}
                      {cat.charAt(0).toUpperCase() + cat.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Priority Trade-off */}
              <div className="preference-section">
                <h4>Priority Focus</h4>
                <div className="pref-field">
                  <label>Comfort vs. Price Balance</label>
                  <div className="pref-btn-group">
                    <button
                      type="button"
                      className={`pref-select-btn ${comfortPriority === 'high' ? 'active' : ''}`}
                      onClick={() => {
                        setComfortPriority('high')
                        setPricePriority('low')
                      }}
                    >
                      Comfort Priority
                    </button>
                    <button
                      type="button"
                      className={`pref-select-btn ${comfortPriority === 'moderate' && pricePriority === 'moderate' ? 'active' : ''}`}
                      onClick={() => {
                        setComfortPriority('moderate')
                        setPricePriority('moderate')
                      }}
                    >
                      Balanced Value
                    </button>
                    <button
                      type="button"
                      className={`pref-select-btn ${pricePriority === 'high' ? 'active' : ''}`}
                      onClick={() => {
                        setPricePriority('high')
                        setComfortPriority('low')
                      }}
                    >
                      Budget / Price Priority
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="preferences-actions">
              <button
                type="button"
                className="btn-danger-outline"
                onClick={handleReset}
                disabled={saving}
              >
                Reset to Defaults
              </button>
              <div className="pref-actions-right">
                {onClose && (
                  <button type="button" className="btn-secondary" onClick={onClose}>
                    Cancel
                  </button>
                )}
                <button
                  type="button"
                  className="btn-primary"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? 'Saving...' : 'Save Preferences'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
