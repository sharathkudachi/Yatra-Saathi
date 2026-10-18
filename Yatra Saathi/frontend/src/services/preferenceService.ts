import { apiData } from './apiClient'
import { authService } from './authService'
import type {
  DestinationExploreResponse,
  HotelExploreResponse,
  POIExploreItem,
  PreferenceItem,
  StructuredTripPlan,
  UserTravelProfile,
} from '../types/travel'

export const preferenceService = {
  /** Get the current authenticated user's travel preferences profile. */
  async getPreferences(): Promise<UserTravelProfile> {
    return apiData<UserTravelProfile>('/api/v1/preferences', {
      method: 'GET',
      headers: authService.authHeaders(),
    })
  },

  /** Update or save preferences. */
  async updatePreferences(preferences: PreferenceItem[]): Promise<UserTravelProfile> {
    return apiData<UserTravelProfile>('/api/v1/preferences', {
      method: 'PUT',
      headers: authService.authHeaders(),
      body: JSON.stringify({ preferences }),
    })
  },

  /** Remove a specific preference key. */
  async deletePreference(preferenceKey: string): Promise<{ deleted: boolean; preference_key: string }> {
    return apiData<{ deleted: boolean; preference_key: string }>(
      `/api/v1/preferences/${encodeURIComponent(preferenceKey)}`,
      {
        method: 'DELETE',
        headers: authService.authHeaders(),
      },
    )
  },

  /** Reset all preferences for the current user. */
  async resetPreferences(): Promise<{ cleared_count: number }> {
    return apiData<{ cleared_count: number }>('/api/v1/preferences/reset', {
      method: 'POST',
      headers: authService.authHeaders(),
    })
  },

  /** Explore destination POIs grounded in catalog data. */
  async exploreDestination(params: {
    destination: string
    categoryFilter?: string
    currency?: string
    limit?: number
  }): Promise<DestinationExploreResponse> {
    return apiData<DestinationExploreResponse>('/api/v1/destinations/explore', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify({
        destination: params.destination,
        category_filter: params.categoryFilter,
        currency: params.currency ?? 'INR',
        limit: params.limit ?? 20,
      }),
    })
  },

  /** Search destination activities by keyword. */
  async searchActivities(destination: string, query: string, limit = 20): Promise<{ activities: POIExploreItem[] }> {
    return apiData<{ activities: POIExploreItem[] }>('/api/v1/destinations/activities/search', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify({ destination, query, limit }),
    })
  },

  /** Explore grounded hotel offers with preference match indicators. */
  async exploreHotels(params: {
    destination: string
    startDate: string
    endDate: string
    travellers?: number
    currency?: string
    minStars?: number
    minGuestScore?: number
    limit?: number
  }): Promise<HotelExploreResponse> {
    return apiData<HotelExploreResponse>('/api/v1/hotels/explore', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify({
        destination: params.destination,
        start_date: params.startDate,
        end_date: params.endDate,
        travellers: params.travellers ?? 1,
        currency: params.currency ?? 'INR',
        min_stars: params.minStars,
        min_guest_score: params.minGuestScore,
        limit: params.limit ?? 20,
      }),
    })
  },

  /** Add an authoritative catalog POI to an existing itinerary. */
  async addActivityToItinerary(
    itineraryId: string,
    poiId: string,
    dayNumber: number,
    slotTime?: string,
  ): Promise<{ itinerary: StructuredTripPlan }> {
    return apiData<{ itinerary: StructuredTripPlan }>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}/activities/add`,
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({
          poi_id: poiId,
          day_number: dayNumber,
          slot_time: slotTime,
        }),
      },
    )
  },

  /** Select and atomically switch the itinerary hotel accommodation. */
  async selectHotelForItinerary(
    itineraryId: string,
    hotelId: string,
    roomTypeId: string,
  ): Promise<{ itinerary: StructuredTripPlan }> {
    return apiData<{ itinerary: StructuredTripPlan }>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}/hotel/select`,
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({
          hotel_id: hotelId,
          room_type_id: roomTypeId,
        }),
      },
    )
  },
}
