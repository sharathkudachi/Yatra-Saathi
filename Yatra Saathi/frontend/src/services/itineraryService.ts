import { apiData } from './apiClient'
import { authService } from './authService'
import type {
  GenerateItineraryResponse,
  ReplanItineraryRequest,
  StructuredTripPlan,
} from '../types/travel'

export type GeneratePlanParams = {
  sessionId?: string
  origin: string
  destination: string
  startDate: string
  endDate: string
  travellers: number
  budget?: string
  currency: string
  preferences?: string
  flightId?: string
  hotelId?: string
}

export function normalizeTripPlan(raw: any): StructuredTripPlan {
  if (!raw) return raw
  return {
    id: raw.id,
    tripId: raw.trip_id || raw.tripId || null,
    sessionId: raw.session_id || raw.sessionId || null,
    title: raw.title || '',
    origin: raw.origin || '',
    destination: raw.destination || '',
    startDate: raw.start_date || raw.startDate || '',
    endDate: raw.end_date || raw.endDate || '',
    travellers: raw.travellers ?? 1,
    currency: raw.currency || 'INR',
    budget: raw.budget || null,
    totalEstimatedCost: raw.total_estimated_cost || raw.totalEstimatedCost || null,
    totalAuthoritativeCost: raw.total_authoritative_cost || raw.totalAuthoritativeCost || null,
    transport: (raw.transport || []).map((t: any) => ({
      id: t.id || null,
      type: t.type || 'flight',
      origin: t.origin || '',
      originCode: t.origin_code || t.originCode || null,
      destination: t.destination || '',
      destCode: t.dest_code || t.destCode || null,
      carrier: t.carrier || null,
      reference: t.reference || null,
      departsAt: t.departs_at || t.departsAt || '',
      arrivesAt: t.arrives_at || t.arrivesAt || '',
      knownPrice: t.known_price || t.knownPrice || null,
      currency: t.currency || 'INR',
      originLatitude: t.origin_latitude ?? t.originLatitude ?? null,
      originLongitude: t.origin_longitude ?? t.originLongitude ?? null,
      destLatitude: t.dest_latitude ?? t.destLatitude ?? null,
      destLongitude: t.dest_longitude ?? t.destLongitude ?? null,
    })),
    accommodation: (raw.accommodation || []).map((a: any) => ({
      id: a.id || null,
      hotelId: a.hotel_id || a.hotelId || null,
      hotelName: a.hotel_name || a.hotelName || '',
      roomTypeId: a.room_type_id || a.roomTypeId || null,
      roomName: a.room_name || a.roomName || null,
      address: a.address || null,
      checkInDate: a.check_in_date || a.checkInDate || '',
      checkOutDate: a.check_out_date || a.checkOutDate || '',
      knownPrice: a.known_price || a.knownPrice || null,
      currency: a.currency || 'INR',
      latitude: a.latitude ?? null,
      longitude: a.longitude ?? null,
    })),
    days: (raw.days || []).map((d: any) => ({
      date: d.date || '',
      dayNumber: d.day_number ?? d.dayNumber ?? 1,
      title: d.title || '',
      locations: d.locations || [],
      notes: d.notes || null,
      estimatedCost: d.estimated_cost || d.estimatedCost || null,
      activities: (d.activities || []).map((act: any) => ({
        id: act.id,
        title: act.title,
        description: act.description || null,
        startTime: act.start_time || act.startTime || null,
        endTime: act.end_time || act.endTime || null,
        durationMinutes: act.duration_minutes ?? act.durationMinutes ?? null,
        location: act.location || null,
        latitude: act.latitude ?? null,
        longitude: act.longitude ?? null,
        estimatedCost: act.estimated_cost || act.estimatedCost || null,
        authoritativeCost: act.authoritative_cost || act.authoritativeCost || null,
        currency: act.currency || 'INR',
        category: act.category || 'activity',
        source: act.source || 'catalog',
        entityType: act.entity_type || act.entityType || null,
        entityId: act.entity_id || act.entityId || null,
      })),
    })),
    constraints: raw.constraints || {},
    status: raw.status || 'draft',
    version: raw.version || 1,
    createdAt: raw.created_at || raw.createdAt || null,
    updatedAt: raw.updated_at || raw.updatedAt || null,
  }
}

export const itineraryService = {
  /** Generate a structured itinerary draft with bounded alternatives. */
  async generate(params: GeneratePlanParams): Promise<GenerateItineraryResponse> {
    const raw = await apiData<any>('/api/v1/itineraries/generate', {
      method: 'POST',
      headers: authService.authHeaders(),
      body: JSON.stringify({
        session_id: params.sessionId,
        origin: params.origin,
        destination: params.destination,
        start_date: params.startDate,
        end_date: params.endDate,
        travellers: params.travellers,
        budget: params.budget,
        currency: params.currency,
        preferences: params.preferences,
        selected_transport_reference: params.flightId,
        selected_hotel_id: params.hotelId,
      }),
    })
    const active = raw.active_plan || raw.activePlan
    const alts = (raw.alternatives || []).map((alt: any) => ({
      optionId: alt.option_id || alt.optionId,
      label: alt.label,
      description: alt.description,
      totalCost: alt.total_cost || alt.totalCost || null,
      currency: alt.currency,
      plan: normalizeTripPlan(alt.plan),
    }))
    return {
      activePlan: normalizeTripPlan(active),
      alternatives: alts,
      executionSteps: raw.execution_steps || raw.executionSteps || [],
      validation: raw.validation,
      explanation: raw.explanation,
    }
  },

  /** Replan an existing itinerary with natural language instruction (e.g. "make it cheaper"). */
  async replan(
    itineraryId: string,
    req: ReplanItineraryRequest,
  ): Promise<{ itinerary: StructuredTripPlan }> {
    const res = await apiData<any>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}/replan`,
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({
          instruction: req.instruction,
          target_day: req.targetDay,
          remove_activity_id: req.removeActivityId,
          move_activity_id: req.moveActivityId,
          to_day: req.toDay,
          preference_update: req.preferenceUpdate,
        }),
      },
    )
    return { itinerary: normalizeTripPlan(res.itinerary) }
  },

  /** Regenerate activities for an existing itinerary while keeping transport & stay. */
  async regenerate(itineraryId: string): Promise<{ itinerary: StructuredTripPlan }> {
    const res = await apiData<any>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}/regenerate`,
      {
        method: 'POST',
        headers: authService.authHeaders(),
      },
    )
    return { itinerary: normalizeTripPlan(res.itinerary) }
  },

  /** Select one of the bounded alternative plans (balanced, budget, relaxed). */
  async selectAlternative(
    itineraryId: string,
    optionId: string,
  ): Promise<{ itinerary: StructuredTripPlan }> {
    const res = await apiData<any>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}/select-option`,
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({ option_id: optionId }),
      },
    )
    return { itinerary: normalizeTripPlan(res.itinerary) }
  },

  /** Get an existing itinerary by ID. */
  async get(itineraryId: string): Promise<{ itinerary: StructuredTripPlan }> {
    const res = await apiData<any>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}`,
      {
        method: 'GET',
        headers: authService.authHeaders(),
      },
    )
    return { itinerary: normalizeTripPlan(res.itinerary) }
  },

  /** Phase 3: Compare travel options with transparent scoring and trade-offs. */
  async compareOptions(
    params: import('../types/travel').CompareTravelOptionsRequest,
  ): Promise<import('../types/travel').CompareTravelOptionsResponse> {
    return apiData<import('../types/travel').CompareTravelOptionsResponse>(
      '/api/v1/travel-options/compare',
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({
          origin: params.origin,
          destination: params.destination,
          start_date: params.startDate,
          end_date: params.endDate,
          travellers: params.travellers ?? 1,
          currency: params.currency ?? 'INR',
          budget: params.budget,
          preferences: Array.isArray(params.preferences) ? params.preferences.join(', ') : (params.preferences ?? undefined),
          cabin_class: params.cabinClass ?? 'economy',
          category_filter: params.categoryFilter,
          max_options: params.maxOptions ?? 3,
        }),
      },
    )
  },

  /** Phase 3: Optimize trip budget or comfort with plan diff. */
  async optimizeTrip(
    itineraryId: string,
    req: import('../types/travel').OptimizeTripRequest,
  ): Promise<import('../types/travel').OptimizeTripResponse> {
    return apiData<import('../types/travel').OptimizeTripResponse>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}/optimize`,
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({
          itinerary_id: itineraryId,
          objective: req.objective ?? 'cheaper',
          target_budget: req.targetBudget,
          allowed_changes: req.allowedChanges ?? { flight: true, hotel: true, activities: false, dates: false },
          preferences: req.preferences,
        }),
      },
    )
  },

  /** Phase 3: Apply a selected TravelOption to the itinerary atomically. */
  async applyTravelOption(
    itineraryId: string,
    optionId: string,
    selectedOption?: import('../types/travel').TravelOption,
  ): Promise<{ itinerary: StructuredTripPlan }> {
    return apiData<{ itinerary: StructuredTripPlan }>(
      `/api/v1/itineraries/${encodeURIComponent(itineraryId)}/apply-travel-option`,
      {
        method: 'POST',
        headers: authService.authHeaders(),
        body: JSON.stringify({
          option_id: optionId,
          selected_option: selectedOption,
        }),
      },
    )
  },
}

