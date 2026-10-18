import { apiData } from './apiClient'
import { authService } from './authService'

// Web Push for this device: register the service worker, subscribe with the backend's VAPID
// key, and store the subscription (with the bell-panel preferences) on the backend, which
// sends plan-ready / booking / flight notifications even when Yatra isn't open.

export type PushState = 'unsupported' | 'insecure' | 'blocked' | 'off' | 'on' | 'server-disabled'

const authed = (init: RequestInit = {}) => ({ ...init, headers: { ...(init.headers as Record<string, string>), ...authService.authHeaders() } })

function keyBytes(base64url: string): ArrayBuffer {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0)).buffer
}

export const pushService = {
  supported() { return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window },

  async state(): Promise<PushState> {
    if (!window.isSecureContext) return 'insecure'
    if (!this.supported()) return 'unsupported'
    if (Notification.permission === 'denied') return 'blocked'
    const registration = await navigator.serviceWorker.getRegistration('/')
    const subscription = await registration?.pushManager.getSubscription()
    return subscription && Notification.permission === 'granted' ? 'on' : 'off'
  },

  /** Ask permission, subscribe this device and register it with the backend. */
  async enable(prefs: Record<string, boolean>): Promise<PushState> {
    if (!window.isSecureContext) return 'insecure'
    if (!this.supported()) return 'unsupported'
    const { publicKey, enabled } = await apiData<{ publicKey: string | null; enabled: boolean }>('/api/v1/notifications/public-key')
    if (!enabled || !publicKey) return 'server-disabled'
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') return permission === 'denied' ? 'blocked' : 'off'
    const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
    await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.getSubscription()
      ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) })
    await apiData('/api/v1/notifications/subscriptions', authed({ method: 'POST', body: JSON.stringify({ subscription: subscription.toJSON(), prefs }) }))
    return 'on'
  },

  /** Re-send preferences for an existing subscription (after a toggle changes). */
  async updatePrefs(prefs: Record<string, boolean>) {
    const subscription = await (await navigator.serviceWorker.getRegistration('/'))?.pushManager.getSubscription()
    if (subscription) await apiData('/api/v1/notifications/subscriptions', authed({ method: 'POST', body: JSON.stringify({ subscription: subscription.toJSON(), prefs }) }))
  },

  async disable() {
    const subscription = await (await navigator.serviceWorker.getRegistration('/'))?.pushManager.getSubscription()
    if (!subscription) return
    await apiData('/api/v1/notifications/subscriptions', authed({ method: 'DELETE', body: JSON.stringify({ endpoint: subscription.endpoint }) })).catch(() => undefined)
    await subscription.unsubscribe()
  },

  sendTest(kind: 'test' | 'flight_landed' = 'test') {
    return apiData<{ sent: boolean; title: string; body: string; pushEnabled: boolean }>('/api/v1/notifications/test', authed({ method: 'POST', body: JSON.stringify({ kind }) }))
  },

  history() {
    return apiData<{ notifications: Array<{ notification_id: string; kind: string; title: string; body: string; url: string | null; created_at: string }> }>('/api/v1/notifications', authed())
  },
}
