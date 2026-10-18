import { useEffect, useState } from 'react'
import {
  Bell,
  BellCheck,
  Check,
  CheckCheck,
  Compass,
  FileText,
  Filter,
  RefreshCw,
  Settings,
  Sparkles,
  X,
} from 'lucide-react'
import { phase6Service } from '../services/phase6Service'
import type { NotificationItem, NotificationPreferencesData } from '../types/travel'

interface NotificationCenterModalProps {
  isOpen: boolean
  onClose: () => void
  currentUserId?: string | null
  onOpenTrip?: (tripId: string) => void
  onOpenBooking?: (bookingId: string) => void
}

export default function NotificationCenterModal({
  isOpen,
  onClose,
  currentUserId: _currentUserId,
  onOpenTrip,
  onOpenBooking,
}: NotificationCenterModalProps) {
  const [activeTab, setActiveTab] = useState<'notifications' | 'preferences'>('notifications')
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [preferences, setPreferences] = useState<NotificationPreferencesData | null>(null)
  const [loading, setLoading] = useState(false)
  const [savingPrefs, setSavingPrefs] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>('ALL')

  useEffect(() => {
    if (isOpen) {
      void loadData()
    }
  }, [isOpen])

  async function loadData() {
    setLoading(true)
    setMessage(null)
    try {
      const [items, prefs] = await Promise.all([
        phase6Service.getNotifications(false, 50).catch(() => []),
        phase6Service.getNotificationPreferences().catch(() => null),
      ])
      const notifList = Array.isArray(items) ? items : ((items as any)?.notifications || [])
      setNotifications(notifList)
      setPreferences(prefs)
    } catch {
      setMessage('Could not load notifications from backend.')
    } finally {
      setLoading(false)
    }
  }

  async function handleMarkRead(id: string) {
    try {
      await phase6Service.markAsRead(id)
      setNotifications((prev) =>
        prev.map((item) => (item.notification_id === id ? { ...item, is_read: true } : item)),
      )
    } catch {
      // ignore
    }
  }

  async function handleMarkAllRead() {
    try {
      await phase6Service.markAllAsRead()
      setNotifications((prev) => prev.map((item) => ({ ...item, is_read: true })))
      setMessage('All notifications marked as read.')
    } catch {
      setMessage('Failed to mark all as read.')
    }
  }

  async function handleSavePreferences(e: React.FormEvent) {
    e.preventDefault()
    if (!preferences) return
    setSavingPrefs(true)
    setMessage(null)
    try {
      const updated = await phase6Service.updateNotificationPreferences(preferences)
      setPreferences(updated)
      setMessage('Notification preferences successfully updated.')
    } catch {
      setMessage('Failed to save notification preferences.')
    } finally {
      setSavingPrefs(false)
    }
  }

  async function handleGenerateDemoAlerts() {
    setLoading(true)
    try {
      const res = await phase6Service.generateLifecycleNotifications()
      setMessage(`Generated ${res.created_count} authoritative lifecycle alerts.`)
      await loadData()
    } catch {
      setMessage('Could not generate lifecycle alerts.')
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  const notifList = Array.isArray(notifications) ? notifications : []
  const unreadCount = notifList.filter((n) => !n.is_read).length
  const filteredNotifications =
    filterCategory === 'ALL'
      ? notifList
      : notifList.filter((n) => n.category === filterCategory)

  return (
    <div
      className="modal-backdrop notifications-modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <section
        className="confirm-modal notification-center-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="notif-center-title"
      >
        <button className="modal-close" aria-label="Close notifications" onClick={onClose}>
          <X size={19} />
        </button>

        <div className="notif-modal-header">
          <div className="notif-title-row">
            <div className="modal-icon notif-bell-icon">
              <Bell size={20} />
            </div>
            <div>
              <span className="mini-label">Travel Events & Alerts</span>
              <h2 id="notif-center-title">
                Notifications {unreadCount > 0 && <span className="unread-counter-badge">{unreadCount}</span>}
              </h2>
            </div>
          </div>

          <div className="notif-tab-buttons" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'notifications'}
              className={`notif-tab-btn ${activeTab === 'notifications' ? 'active' : ''}`}
              onClick={() => setActiveTab('notifications')}
            >
              <Bell size={14} /> Alerts ({notifications.length})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'preferences'}
              className={`notif-tab-btn ${activeTab === 'preferences' ? 'active' : ''}`}
              onClick={() => setActiveTab('preferences')}
            >
              <Settings size={14} /> Preferences
            </button>
          </div>
        </div>

        {message && (
          <div className="modal-result notif-banner" role="status">
            {message}
          </div>
        )}

        {/* Tab 1: Notifications List */}
        {activeTab === 'notifications' && (
          <div className="notif-tab-content">
            <div className="notif-actions-bar">
              <div className="category-filter-wrap">
                <Filter size={14} />
                <select
                  value={filterCategory}
                  onChange={(e) => setFilterCategory(e.target.value)}
                  aria-label="Filter notifications by category"
                >
                  <option value="ALL">All Categories</option>
                  <option value="TRIP_LIFECYCLE">Trip Lifecycle</option>
                  <option value="BOOKING_LIFECYCLE">Booking Lifecycle</option>
                  <option value="TRAVEL_REMINDER">Travel Reminders</option>
                  <option value="HOLD_LIFECYCLE">Holds</option>
                </select>
              </div>

              <div className="right-actions">
                {unreadCount > 0 && (
                  <button
                    type="button"
                    className="notif-text-btn"
                    onClick={() => void handleMarkAllRead()}
                    title="Mark all notifications as read"
                  >
                    <CheckCheck size={14} /> Mark all read
                  </button>
                )}
                <button
                  type="button"
                  className="notif-text-btn"
                  onClick={() => void loadData()}
                  title="Refresh notifications"
                >
                  <RefreshCw size={14} className={loading ? 'spinning' : ''} /> Refresh
                </button>
              </div>
            </div>

            {loading && notifications.length === 0 ? (
              <div className="notif-loading">
                <span className="spinner" /> Loading notifications...
              </div>
            ) : filteredNotifications.length === 0 ? (
              <div className="notif-empty-state">
                <BellCheck size={32} />
                <p>No notifications at this time.</p>
                <small>Authoritative travel events will appear here automatically.</small>
                <button
                  type="button"
                  className="demo-alert-btn"
                  onClick={() => void handleGenerateDemoAlerts()}
                >
                  <Sparkles size={14} /> Check for Upcoming Trip Alerts
                </button>
              </div>
            ) : (
              <ul className="notif-items-list" aria-label="Notifications list">
                {filteredNotifications.map((item) => (
                  <li
                    key={item.notification_id}
                    className={`notif-item ${item.is_read ? 'is-read' : 'is-unread'}`}
                  >
                    <div className="notif-item-top">
                      <span className={`notif-category-badge cat-${(item.category || 'general').toLowerCase()}`}>
                        {(item.category || 'General').replace('_', ' ')}
                      </span>
                      <span className="notif-time">
                        {new Date(item.created_at).toLocaleString([], {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                    </div>

                    <h4 className="notif-item-title">{item.title}</h4>
                    <p className="notif-item-body">{item.body}</p>

                    <div className="notif-item-footer">
                      <div className="notif-links">
                        {item.trip_id && (
                          <button
                            type="button"
                            className="notif-link-btn"
                            onClick={() => {
                              onOpenTrip?.(item.trip_id!)
                              onClose()
                            }}
                          >
                            <Compass size={12} /> View Trip
                          </button>
                        )}
                        {item.booking_id && (
                          <button
                            type="button"
                            className="notif-link-btn"
                            onClick={() => {
                              onOpenBooking?.(item.booking_id!)
                              onClose()
                            }}
                          >
                            <FileText size={12} /> View Booking
                          </button>
                        )}
                      </div>

                      {!item.is_read && (
                        <button
                          type="button"
                          className="mark-read-btn"
                          onClick={() => void handleMarkRead(item.notification_id)}
                          title="Mark this notification as read"
                        >
                          <Check size={14} /> Mark Read
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Tab 2: Notification Preferences */}
        {activeTab === 'preferences' && preferences && (
          <form className="notif-tab-content prefs-form" onSubmit={handleSavePreferences}>
            <div className="pref-section">
              <label className="pref-toggle-row">
                <div>
                  <strong>Enable Travel Notifications</strong>
                  <p>Receive notifications for your trips, bookings, and reminders.</p>
                </div>
                <input
                  type="checkbox"
                  checked={preferences.enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, enabled: e.target.checked })
                  }
                />
              </label>

              <label className="pref-toggle-row">
                <div>
                  <strong>In-App Notification Center</strong>
                  <p>Display alerts within the Yatra Saathi notification drawer.</p>
                </div>
                <input
                  type="checkbox"
                  checked={preferences.in_app_enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, in_app_enabled: e.target.checked })
                  }
                />
              </label>

              <label className="pref-toggle-row">
                <div>
                  <strong>Browser Push Alerts</strong>
                  <p>Show desktop notifications when Yatra Saathi is in the background.</p>
                </div>
                <input
                  type="checkbox"
                  checked={preferences.browser_enabled}
                  onChange={(e) =>
                    setPreferences({ ...preferences, browser_enabled: e.target.checked })
                  }
                />
              </label>
            </div>

            <div className="pref-categories-section">
              <h4>Alert Categories</h4>
              {[
                { key: 'TRIP_LIFECYCLE', label: 'Trip Lifecycle (Upcoming & Active Trips)' },
                { key: 'BOOKING_LIFECYCLE', label: 'Booking Lifecycle (Confirmations & Cancellations)' },
                { key: 'TRAVEL_REMINDER', label: 'Travel Day Reminders' },
                { key: 'HOLD_LIFECYCLE', label: 'Inventory Hold Expirations' },
                { key: 'ITINERARY_UPDATE', label: 'Itinerary Replanning & Changes' },
              ].map(({ key, label }) => {
                const checked = preferences.categories.includes(key)
                return (
                  <label key={key} className="cat-checkbox-row">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        const newCats = e.target.checked
                          ? [...preferences.categories, key]
                          : preferences.categories.filter((c) => c !== key)
                        setPreferences({ ...preferences, categories: newCats })
                      }}
                    />
                    <span>{label}</span>
                  </label>
                )
              })}
            </div>

            <div className="pref-quiet-hours">
              <h4>Quiet Hours (Do Not Disturb)</h4>
              <div className="quiet-hours-inputs">
                <label>
                  <span>Start:</span>
                  <input
                    type="time"
                    value={preferences.quiet_hours_start || ''}
                    onChange={(e) =>
                      setPreferences({ ...preferences, quiet_hours_start: e.target.value })
                    }
                  />
                </label>
                <label>
                  <span>End:</span>
                  <input
                    type="time"
                    value={preferences.quiet_hours_end || ''}
                    onChange={(e) =>
                      setPreferences({ ...preferences, quiet_hours_end: e.target.value })
                    }
                  />
                </label>
              </div>
            </div>

            <button type="submit" className="modal-primary save-prefs-btn" disabled={savingPrefs}>
              {savingPrefs ? <span className="spinner" /> : 'Save Notification Preferences'}
            </button>
          </form>
        )}
      </section>
    </div>
  )
}
