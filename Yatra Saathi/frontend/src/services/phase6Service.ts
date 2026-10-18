/**
 * Phase 6 Multimodal Intelligence, Voice, Notifications & Emergency Service.
 */
import { apiData } from './apiClient'
import { authService } from './authService'
import type {
  ActivateSosResponse,
  EmergencyInfoResponse,
  GeocodeSearchResponse,
  LanguagePreferenceResponse,
  LocationCoordinates,
  NotificationItem,
  NotificationPreferencesData,
  TrustedContact,
  VoiceTranscriptionResponse,
} from '../types/travel'

export const phase6Service = {
  // ---------------------------------------------------------------------------
  // Language & Localization
  // ---------------------------------------------------------------------------
  async getLanguagePreference(): Promise<LanguagePreferenceResponse> {
    return apiData<LanguagePreferenceResponse>('/api/v1/language/preference', {
      headers: authService.authHeaders(),
    })
  },

  async setLanguagePreference(languageCode: string): Promise<LanguagePreferenceResponse> {
    return apiData<LanguagePreferenceResponse>('/api/v1/language/preference', {
      method: 'PUT',
      headers: authService.authHeaders(),
      body: JSON.stringify({ language_code: languageCode }),
    })
  },

  async detectLanguage(text: string): Promise<{ language_code: string; confidence: number; detection_source: string }> {
    return apiData('/api/v1/language/detect', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify({ text }),
    })
  },

  // ---------------------------------------------------------------------------
  // Voice Assistant
  // ---------------------------------------------------------------------------
  async transcribeAudio(payload: {
    audio_base64?: string
    audio_format?: string
    mime_type?: string
    text_hint?: string
    transcript?: string
  }): Promise<VoiceTranscriptionResponse> {
    const body = {
      transcript: payload.transcript || payload.text_hint || '',
      text_hint: payload.text_hint,
      audio_base64: payload.audio_base64,
      audio_format: payload.audio_format,
      mime_type: payload.mime_type,
    }
    return apiData<VoiceTranscriptionResponse>('/api/v1/voice/transcribe', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify(body),
    })
  },

  async processVoiceIntent(transcript: string, preferredLanguage?: string) {
    return apiData<{
      canonical_intent: Record<string, unknown>
      transcript: string
      detected_language: string
      requires_confirmation: boolean
      confirmation_prompt?: string | null
      structured_action?: { action_type: string; target_id?: string | null; details?: Record<string, unknown> } | null
    }>('/api/v1/voice/intent', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify({ transcript, user_preferred_language: preferredLanguage }),
    })
  },

  // ---------------------------------------------------------------------------
  // Notifications & Alerts
  // ---------------------------------------------------------------------------
  async getNotifications(unreadOnly = false, limit = 50): Promise<NotificationItem[]> {
    const res = await apiData<any>(
      `/api/v1/notifications?unread_only=${unreadOnly}&limit=${limit}`,
      { headers: authService.authHeaders() },
    )
    if (Array.isArray(res)) return res
    if (res && Array.isArray(res.notifications)) return res.notifications
    if (res && Array.isArray(res.items)) return res.items
    return []
  },

  async getUnreadCount(): Promise<number> {
    const res = await apiData<{ unread_count: number }>('/api/v1/notifications/unread-count', {
      headers: authService.authHeaders(),
    })
    return res.unread_count
  },

  async markAsRead(notificationId: string): Promise<NotificationItem> {
    return apiData<NotificationItem>(`/api/v1/notifications/${notificationId}/read`, {
      method: 'POST',
      headers: authService.authHeaders(),
    })
  },

  async markAllAsRead(): Promise<{ success: boolean; marked_count: number }> {
    return apiData<{ success: boolean; marked_count: number }>('/api/v1/notifications/read-all', {
      method: 'POST',
      headers: authService.authHeaders(),
    })
  },

  async getNotificationPreferences(): Promise<NotificationPreferencesData> {
    return apiData<NotificationPreferencesData>('/api/v1/notification-preferences', {
      headers: authService.authHeaders(),
    })
  },

  async updateNotificationPreferences(
    prefs: Partial<NotificationPreferencesData>,
  ): Promise<NotificationPreferencesData> {
    return apiData<NotificationPreferencesData>('/api/v1/notification-preferences', {
      method: 'PUT',
      headers: authService.authHeaders(),
      body: JSON.stringify(prefs),
    })
  },

  async generateLifecycleNotifications(tripId?: string): Promise<{ created_count: number }> {
    return apiData<{ created_count: number }>(
      '/api/v1/notifications/events/generate-lifecycle',
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({ trip_id: tripId }),
      },
    )
  },

  // ---------------------------------------------------------------------------
  // Emergency / SOS Assistance
  // ---------------------------------------------------------------------------
  async getEmergencyInfo(tripId?: string): Promise<EmergencyInfoResponse> {
    const path = tripId ? `/api/v1/emergency/info?trip_id=${encodeURIComponent(tripId)}` : '/api/v1/emergency/info'
    return apiData<EmergencyInfoResponse>(path, {
      headers: authService.authHeaders(),
    })
  },

  async addTrustedContact(contact: {
    contact_name: string
    name?: string
    relationship: string
    phone_number: string
    is_primary?: boolean
  }): Promise<TrustedContact> {
    const payload = {
      name: contact.contact_name || contact.name,
      contact_name: contact.contact_name || contact.name,
      relationship: contact.relationship,
      phone_number: contact.phone_number,
      is_primary: contact.is_primary ?? true,
    }
    return apiData<TrustedContact>('/api/v1/emergency/contacts', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify(payload),
    })
  },

  async updateTrustedContact(
    contactId: string,
    contact: {
      contact_name?: string
      name?: string
      relationship?: string
      phone_number?: string
      is_primary?: boolean
    },
  ): Promise<TrustedContact> {
    const payload = {
      name: contact.contact_name || contact.name,
      contact_name: contact.contact_name || contact.name,
      relationship: contact.relationship,
      phone_number: contact.phone_number,
      is_primary: contact.is_primary,
    }
    return apiData<TrustedContact>(`/api/v1/emergency/contacts/${contactId}`, {
      method: 'PUT',
      headers: authService.authHeaders(),
      body: JSON.stringify(payload),
    })
  },

  async deleteTrustedContact(contactId: string): Promise<{ deleted: boolean; contact_id: string }> {
    return apiData<{ deleted: boolean; contact_id: string }>(`/api/v1/emergency/contacts/${contactId}`, {
      method: 'DELETE',
      headers: authService.authHeaders(),
    })
  },

  async searchLocation(query: string, limit = 5): Promise<GeocodeSearchResponse> {
    const q = encodeURIComponent(query.trim())
    return apiData<GeocodeSearchResponse>(`/api/v1/emergency/geocode?query=${q}&limit=${limit}`, {
      headers: authService.authHeaders(),
    })
  },

  async activateSOS(payload: {
    trip_id?: string
    booking_id?: string
    location?: LocationCoordinates | null
    location_text?: string
    notes?: string
    reason?: string
    explicit_confirmation: boolean
  }): Promise<ActivateSosResponse> {
    return apiData<ActivateSosResponse>('/api/v1/emergency/activate', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify(payload),
    })
  },

  async shareTripDetails(payload: {
    trip_id: string
    trusted_contact_id?: string
    explicit_user_confirmation?: boolean
    explicit_share_consent?: boolean
    location?: LocationCoordinates | null
    location_text?: string
  }): Promise<{
    share_event_id: string
    trip_id: string
    status: string
    summary: Record<string, unknown>
    timestamp: string
  }> {
    const body = {
      ...payload,
      explicit_user_confirmation: true,
      explicit_share_consent: true,
    }
    return apiData('/api/v1/emergency/share-trip', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify(body),
    })
  },
}
