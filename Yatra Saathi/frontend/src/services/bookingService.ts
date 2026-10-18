/**
 * Phase 5 Booking Lifecycle, Trip Management & Trip Pack Frontend Service.
 */
import { apiData } from './apiClient'
import { authService } from './authService'

export type BookingTraveller = {
  displayName: string
  travellerRole: 'adult' | 'child' | 'infant'
}

export type BookingItemSummary = {
  itemType: string
  title: string
  entityType?: string
  entityId?: string
  forDate?: string
  quantity: number
  authoritativePrice?: string
  estimatedPrice?: string
  currency: string
  isAuthoritative: boolean
}

export type BookingReviewResponse = {
  reviewToken: string
  itineraryId: string
  itineraryVersion: number
  destination: string
  origin: string
  startDate: string
  endDate: string
  travellers: Array<{ display_name: string; traveller_role: string }>
  travellerCount: number
  items: Array<{
    item_type: string
    title: string
    entity_type?: string
    entity_id?: string
    for_date?: string
    quantity: number
    authoritative_price?: string
    estimated_price?: string
    currency: string
    is_authoritative: boolean
  }>
  transportTotal: string
  accommodationTotal: string
  estimatedActivitiesTotal: string
  authoritativeSubtotal: string
  taxAmount: string
  authoritativeTotal: string
  currency: string
  bookingMode: string
  demoLabel: string
  reviewExpiresAt: string
}

export type ConfirmBookingResponse = {
  bookingId: string
  bookingReference: string
  status: string
  lifecycleStatus: string
  itineraryId: string
  itineraryVersion: number
  authoritativeTotal: string
  currency: string
  createdAt: string
  bookingMode: string
  demoLabel: string
}

export type TripPackResponse = {
  packId: string
  bookingId: string
  bookingReference: string
  destination: string
  origin: string
  startDate: string
  endDate: string
  travellers: Array<{ display_name: string; traveller_role: string }>
  transportSummary: Array<{ item_type: string; title: string; authoritative_price?: string; currency: string }>
  accommodationSummary: Array<{ item_type: string; title: string; authoritative_price?: string; currency: string }>
  activitiesSummary: Array<{ item_type: string; title: string; authoritative_price?: string; estimated_price?: string; currency: string }>
  authoritativeTotal: string
  currency: string
  importantNotes: string[]
  generatedAt: string
  demoLabel: string
  demoNotice: string
}

export type TripDetailResponse = {
  tripId?: string
  bookingId?: string
  bookingReference?: string
  destination: string
  origin: string
  startDate: string
  endDate: string
  travellerCount: number
  status: string
  lifecycleStatus: string
  authoritativeTotal?: string
  currency?: string
  bookingMode: string
  itinerary?: unknown
  items: Array<{ item_type: string; title: string; line_total?: string; authoritative_price?: string; currency: string }>
  timelineEvents: Array<{
    event_id: string
    event_type: string
    occurred_at: string
    actor: string
    prev_status?: string
    new_status?: string
  }>
}

export const bookingService = {
  async getBookingReview(
    itineraryId: string,
    version: number,
    travellers: BookingTraveller[] = [{ displayName: 'Primary Traveller', travellerRole: 'adult' }],
  ): Promise<BookingReviewResponse> {
    const payload = {
      itinerary_id: itineraryId,
      itinerary_version: version,
      travellers: travellers.map((t) => ({ display_name: t.displayName, traveller_role: t.travellerRole })),
    }
    const res = await apiData<any>(`/api/v1/itineraries/${itineraryId}/booking-review`, {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify(payload),
    })
    return {
      reviewToken: res.review_token,
      itineraryId: res.itinerary_id,
      itineraryVersion: res.itinerary_version,
      destination: res.destination,
      origin: res.origin,
      startDate: res.start_date,
      endDate: res.end_date,
      travellers: res.travellers,
      travellerCount: res.traveller_count,
      items: res.items,
      transportTotal: res.transport_total,
      accommodationTotal: res.accommodation_total,
      estimatedActivitiesTotal: res.estimated_activities_total,
      authoritativeSubtotal: res.authoritative_subtotal,
      taxAmount: res.tax_amount,
      authoritativeTotal: res.authoritative_total,
      currency: res.currency,
      bookingMode: res.booking_mode,
      demoLabel: res.demo_label,
      reviewExpiresAt: res.review_expires_at,
    }
  },

  async confirmBooking(
    reviewToken: string,
    itineraryId: string,
    version: number,
    authoritativeTotal: string,
    currency: string,
    travellers: BookingTraveller[],
    idempotencyKey: string,
  ): Promise<ConfirmBookingResponse> {
    const payload = {
      review_token: reviewToken,
      itinerary_id: itineraryId,
      itinerary_version: version,
      authoritative_total: authoritativeTotal,
      currency,
      travellers: travellers.map((t) => ({ display_name: t.displayName, traveller_role: t.travellerRole })),
      idempotency_key: idempotencyKey,
    }
    const res = await apiData<any>('/api/v1/bookings/confirm', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify(payload),
    })
    return {
      bookingId: res.booking_id,
      bookingReference: res.booking_reference,
      status: res.status,
      lifecycleStatus: res.lifecycle_status,
      itineraryId: res.itinerary_id,
      itineraryVersion: res.itinerary_version,
      authoritativeTotal: res.authoritative_total,
      currency: res.currency,
      createdAt: res.created_at,
      bookingMode: res.booking_mode,
      demoLabel: res.demo_label,
    }
  },

  async getBooking(bookingId: string) {
    return apiData<any>(`/api/v1/bookings/${bookingId}`, {
      headers: authService.authHeaders(),
    })
  },

  async cancelBooking(bookingId: string, reason?: string) {
    return apiData<any>(`/api/v1/bookings/${bookingId}/cancel`, {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify({ reason }),
    })
  },

  async getTripPack(bookingId: string): Promise<TripPackResponse> {
    const res = await apiData<any>(`/api/v1/bookings/${bookingId}/trip-pack`, {
      headers: authService.authHeaders(),
    })
    return {
      packId: res.pack_id,
      bookingId: res.booking_id,
      bookingReference: res.booking_reference,
      destination: res.destination,
      origin: res.origin,
      startDate: res.start_date,
      endDate: res.end_date,
      travellers: res.travellers,
      transportSummary: res.transport_summary,
      accommodationSummary: res.accommodation_summary,
      activitiesSummary: res.activities_summary,
      authoritativeTotal: res.authoritative_total,
      currency: res.currency,
      importantNotes: res.important_notes,
      generatedAt: res.generated_at,
      demoLabel: res.demo_label,
      demoNotice: res.demo_notice,
    }
  },

  getTripPackExportUrl(bookingId: string): string {
    const rawBaseUrl = import.meta.env.VITE_API_BASE_URL
    const baseUrl = (rawBaseUrl !== undefined ? rawBaseUrl : 'http://localhost:8000').replace(/\/+$/, '')
    return `${baseUrl}/api/v1/bookings/${bookingId}/trip-pack/export`
  },

  async getTripDetails(tripId: string): Promise<TripDetailResponse> {
    const res = await apiData<any>(`/api/v1/trips/${tripId}`, {
      headers: authService.authHeaders(),
    })
    return {
      tripId: res.trip_id,
      bookingId: res.booking_id,
      bookingReference: res.booking_reference,
      destination: res.destination,
      origin: res.origin,
      startDate: res.start_date,
      endDate: res.end_date,
      travellerCount: res.traveller_count,
      status: res.status,
      lifecycleStatus: res.lifecycle_status,
      authoritativeTotal: res.authoritative_total,
      currency: res.currency,
      bookingMode: res.booking_mode,
      itinerary: res.itinerary,
      items: res.items,
      timelineEvents: res.timeline_events,
    }
  },
}
