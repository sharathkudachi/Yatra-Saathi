export type HotelOption = {
  hotelId: string
  roomTypeId: string
  inventoryIds: string[]
  maxOccupancy: number
  name: string
  city: string
  country: string
  description: string
  /** Optional backend-localized copy for the selected UI language. */
  localizedDescription?: string
  imageUrl: string
  roomName: string
  localizedRoomName?: string
  price: string
  currency: string
  /** The catalog's own price when `price` was converted into the trip currency. */
  localPrice?: string
  localCurrency?: string
  nights: number
  availableUnits: number
  tags: string[]
  localizedTags?: string[]
  /** Authoritative geographic coordinates from backend SQLite. */
  latitude?: number | null
  longitude?: number | null
  address?: string
  /** Optional property details supplied by the hotel/backend, never frontend demo placeholders. */
  roomImages?: string[]
  surroundingsImages?: string[]
  menuItems?: Array<{ name: string; description?: string; price?: string; currency?: string; category?: string }>
  localizedMenuItems?: Array<{ name: string; description?: string; price?: string; currency?: string; category?: string }>
}

export type CityLocation = {
  cityId: string
  name: string
  state?: string | null
  countryCode: string
  latitude: number
  longitude: number
  timezone?: string
  region?: string
}

export type FlightSearchRequest = {
  originCity: string
  destinationCity: string
  departureDate: string
  passengers: number
  cabinClass: 'economy' | 'business' | 'first'
  currency: string
}

export type FlightOption = {
  flightId: string
  fareId: string
  inventoryId: string
  airlineName: string
  airlineCode: string
  flightNumber: string
  originCity: string
  originAirport: string
  originCode: string
  originLatitude?: number | null
  originLongitude?: number | null
  destinationCity: string
  destinationAirport: string
  destinationCode: string
  destLatitude?: number | null
  destLongitude?: number | null
  departsAt: string
  arrivesAt: string
  /** Same instants in each airport's own timezone, and how many local days later it lands. */
  departsAtLocal?: string
  arrivesAtLocal?: string
  arrivalDayOffset?: number
  durationMinutes: number
  stops: number
  cabinClass: string
  fareClass: string
  price: string
  currency: string
  localPrice?: string
  localCurrency?: string
  baggageKg: number
  seatsAvailable: number
  refundable: boolean
  changeable: boolean
  carbonKg: string
}

export type AgentTurnResponse = {
  assistantMessage: string
  tripRequest: TripRequest
  toolSteps: string[]
  hotels: HotelOption[]
  budget: BudgetSummary | null
  itinerary: ItineraryStop[]
}

export type ItineraryStop = {
  id: string
  time: string
  title: string
  detail: string
  category: 'stay' | 'food' | 'culture' | 'nature' | 'flight'
}

export type BudgetSummary = {
  currency: string
  total: string
  committed: string
  planned: string
}

export type TripRequest = {
  destination: string
  startDate: string
  endDate: string
  travellers: number
  budget: string
  currency: string
  preferences: string
}

export type HoldResult = {
  status: 'mock_only' | 'held'
  message: string
  holdId?: string
}

/** One room type of a hotel for the chosen stay (POST /api/v1/search/hotels/{id}/rooms). */
export type StayRoom = {
  roomTypeId: string
  name: string
  bedConfig: string
  sizeSqm: number | null
  maxOccupancy: number
  maxAdults: number
  maxChildren: number
  smokingAllowed: boolean
  fitsParty: boolean
  bookable: boolean
  unavailableReason: string | null
  /** not_offered | sold_out | no_checkin | min_stay | stay_length | mixed_currency */
  unavailableCode: string | null
  /** The date (YYYY-MM-DD) or night count the code refers to. */
  unavailableDetail: string | null
  availableUnits: number
  nightly: Array<{ date: string; price: string }>
  price: string | null
  currency: string
  localPrice?: string | null
  localCurrency?: string
  inventoryIds: string[]
}

export type StayDetails = {
  hotel: {
    hotelId: string; name: string; description: string; city: string; country: string; propertyType: string
    starRating: number | null; guestScore: number | null; reviewCount: number | null; address: string
    distanceToCentreKm: number | null; checkinTime: string | null; checkoutTime: string | null; hasXrScene: boolean
  }
  startDate: string
  endDate: string
  nights: number
  travellers: number
  rooms: StayRoom[]
}

export type ItineraryStatus = 'draft' | 'planned' | 'awaiting_input' | 'confirmed' | 'cancelled'

export type ActivityCategory =
  | 'arrival'
  | 'departure'
  | 'stay'
  | 'flight'
  | 'food'
  | 'culture'
  | 'nature'
  | 'activity'
  | 'transport'
  | 'free_time'
  | 'other'

export type TransportType = 'flight' | 'train' | 'bus' | 'cab' | 'ferry' | 'other'

export type ItineraryActivity = {
  id: string
  title: string
  description?: string | null
  startTime?: string | null
  endTime?: string | null
  durationMinutes?: number | null
  location?: string | null
  latitude?: number | null
  longitude?: number | null
  estimatedCost?: string | null
  authoritativeCost?: string | null
  currency: string
  category: ActivityCategory
  source?: string
  entityType?: string | null
  entityId?: string | null
}

export type StructuredItineraryDay = {
  date: string
  dayNumber: number
  title: string
  activities: ItineraryActivity[]
  locations: string[]
  notes?: string | null
  estimatedCost?: string | null
}

export type TransportSegment = {
  id?: string | null
  type: TransportType
  origin: string
  originCode?: string | null
  destination: string
  destCode?: string | null
  carrier?: string | null
  reference?: string | null
  departsAt: string
  arrivesAt: string
  knownPrice?: string | null
  currency: string
  originLatitude?: number | null
  originLongitude?: number | null
  destLatitude?: number | null
  destLongitude?: number | null
}

export type AccommodationStay = {
  id?: string | null
  hotelId?: string | null
  hotelName: string
  roomTypeId?: string | null
  roomName?: string | null
  address?: string | null
  checkInDate: string
  checkOutDate: string
  knownPrice?: string | null
  currency: string
  latitude?: number | null
  longitude?: number | null
}

export type StructuredTripPlan = {
  id: string
  tripId?: string | null
  sessionId?: string | null
  title: string
  origin: string
  destination: string
  startDate: string
  endDate: string
  travellers: number
  currency: string
  budget?: string | null
  totalEstimatedCost?: string | null
  totalAuthoritativeCost?: string | null
  transport: TransportSegment[]
  accommodation: AccommodationStay[]
  days: StructuredItineraryDay[]
  constraints?: Record<string, unknown>
  status: ItineraryStatus
  version?: number
  createdAt?: string | null
  updatedAt?: string | null
}

export type ItineraryAlternativeOption = {
  optionId: string
  label: string
  description: string
  totalCost?: string | null
  currency: string
  plan: StructuredTripPlan
}

export type GenerateItineraryResponse = {
  activePlan: StructuredTripPlan
  alternatives: ItineraryAlternativeOption[]
  executionSteps: string[]
  validation: { valid: boolean; errors: string[]; warnings: string[] }
  explanation?: string | null
}

export type ReplanItineraryRequest = {
  instruction: string
  targetDay?: number | null
  removeActivityId?: string | null
  moveActivityId?: string | null
  toDay?: number | null
  preferenceUpdate?: string | null
}

// Phase 3: Intelligent Travel Comparison + Trade-offs + Budget Optimization

export type ComparisonCategory =
  | 'cheapest'
  | 'best_value'
  | 'fastest'
  | 'most_comfortable'
  | 'balanced'
  | 'budget_friendly'

export type ScoreBreakdown = {
  priceScore: number
  durationScore?: number | null
  hotelScore?: number | null
  comfortScore?: number | null
  preferenceScore?: number | null
  overallScore: number
  explanation: string
}

export type FlightComparisonDetail = {
  outbound?: Record<string, unknown> | null
  returnFlight?: Record<string, unknown> | null
  totalFlightPrice: string
  totalDurationMinutes?: number | null
  totalStops: number
  isDirect: boolean
  carrierNames: string[]
  currency: string
}

export type HotelComparisonDetail = {
  hotelId: string
  hotelName: string
  roomTypeId?: string | null
  roomName?: string | null
  starRating?: number | null
  guestScore?: number | null
  distanceToCentreKm?: number | null
  address?: string | null
  totalHotelPrice: string
  nightlyPrice: string
  nights: number
  currency: string
  latitude?: number | null
  longitude?: number | null
}

export type TravelOption = {
  id: string
  label: string
  category: ComparisonCategory
  flight?: FlightComparisonDetail | null
  hotel?: HotelComparisonDetail | null
  transportCost: string
  accommodationCost: string
  activityCost: string
  authoritativeTotal: string
  estimatedTotal: string
  currency: string
  totalDurationMinutes?: number | null
  score: number
  scoreBreakdown: ScoreBreakdown
  tradeOffs: string[]
  isWithinBudget: boolean
  isCheapest?: boolean
  isBestValue?: boolean
  isFastest?: boolean
  isMostComfortable?: boolean
}

export type CompareTravelOptionsRequest = {
  origin: string
  destination: string
  startDate: string
  endDate: string
  travellers?: number
  currency?: string
  budget?: string | null
  preferences?: string | null
  cabinClass?: string
  categoryFilter?: ComparisonCategory | null
  maxOptions?: number
  weights?: Record<string, number>
}

export type CompareTravelOptionsResponse = {
  options: TravelOption[]
  totalCandidatesAnalyzed: number
  cheapestOptionId?: string | null
  bestValueOptionId?: string | null
  fastestOptionId?: string | null
  mostComfortableOptionId?: string | null
  recommendationSummary: string
  tradeOffAnalysis: string[]
  feasible: boolean
  noFeasibleReason?: string | null
  suggestedAlternatives: string[]
}

export type PlanDiff = {
  flightChange?: { before: Record<string, unknown>; after: Record<string, unknown> } | null
  hotelChange?: { before: Record<string, unknown>; after: Record<string, unknown> } | null
  activityChange?: { before: Record<string, unknown>; after: Record<string, unknown> } | null
  beforeAuthoritativeTotal: string
  afterAuthoritativeTotal: string
  savings?: string | null
  costIncrease?: string | null
  currency: string
  summary: string
  isMaterialChange: boolean
  confirmationPrompt?: string | null
}

export type OptimizeTripRequest = {
  itineraryId: string
  objective?: string
  targetBudget?: string | null
  allowedChanges?: { flight: boolean; hotel: boolean; activities: boolean; dates: boolean }
  preferences?: string | null
}

export type OptimizeTripResponse = {
  itineraryId: string
  optimizedOption?: TravelOption | null
  diff?: PlanDiff | null
  status: string
  explanation: string
  feasible: boolean
  alternatives: string[]
}

// --- Phase 4 Preferences & Exploration Types ---

export type PreferenceSource = 'explicit_user' | 'inferred_request' | 'inferred_accepted' | 'system_default'
export type PreferencePriority = 'hard' | 'high' | 'medium' | 'low'

export type PreferenceItem = {
  preference_key: string
  value: boolean | number | string | string[]
  is_hard: boolean
  priority: PreferencePriority
  confidence: number
  source: PreferenceSource
  created_at?: string | null
  updated_at?: string | null
  active?: boolean
}

export type PreferenceMatch = {
  preference_key: string
  matched: boolean
  strength: number
  evidence: string
  source?: PreferenceSource | null
}

export type UserTravelProfile = {
  user_id: string
  preferences: Record<string, PreferenceItem>
  updated_at: string
}

export type PreferenceProposal = {
  proposal_id: string
  preferences: PreferenceItem[]
  explanation: string
  requires_confirmation: boolean
  is_ambiguous?: boolean
  clarification_question?: string | null
}

export type POIExploreItem = {
  poi_id: string
  title: string
  city_id: string
  city_name: string
  latitude?: number | null
  longitude?: number | null
  category: string
  cost: string
  currency: string
  duration_minutes?: number | null
  times_planned: number
  description?: string | null
  preference_matches?: PreferenceMatch[]
}

export type DestinationExploreResponse = {
  destination: string
  city_id: string
  city_name: string
  latitude?: number | null
  longitude?: number | null
  activities: POIExploreItem[]
  supported_categories: string[]
  total_activities: number
}

export type HotelExploreItem = {
  hotel_id: string
  name: string
  city_id: string
  city_name: string
  property_type?: string | null
  star_rating?: number | null
  guest_score?: number | null
  review_count?: number | null
  address_line?: string | null
  latitude?: number | null
  longitude?: number | null
  distance_to_centre_km?: number | null
  room_type_id: string
  room_name: string
  nightly_price: string
  total_stay_price: string
  currency: string
  preference_matches?: PreferenceMatch[]
  match_score: number
  why_it_matches: string[]
}

export type HotelExploreResponse = {
  destination: string
  hotels: HotelExploreItem[]
  total_found: number
}

export type AddActivityRequest = {
  poi_id: string
  day_number: number
  slot_time?: string | null
}

export type SelectHotelRequest = {
  hotel_id: string
  room_type_id: string
}

// ---------------------------------------------------------------------------
// Phase 6: Multimodal, Multilingual, Notifications & Emergency Types
// ---------------------------------------------------------------------------

export type Phase6SupportedLanguage = 'en-IN' | 'hi-IN' | 'ta-IN'

export type LanguagePreferenceResponse = {
  language_code: string
  fallback_language: string
  is_explicit: boolean
  updated_at?: string
}

export type NotificationItem = {
  notification_id: string
  user_id: string
  event_type: string
  category: string
  title: string
  body: string
  language: string
  trip_id?: string | null
  booking_id?: string | null
  is_read: boolean
  created_at: string
  read_at?: string | null
}

export type NotificationPreferencesData = {
  user_id: string
  enabled: boolean
  categories: string[]
  in_app_enabled: boolean
  browser_enabled: boolean
  preferred_language: string
  quiet_hours_start?: string | null
  quiet_hours_end?: string | null
}

export type EmergencyOfficialNumber = {
  name: string
  number: string
  description: string
  service_name?: string
  is_toll_free?: boolean
}

export type TrustedContact = {
  contact_id: string
  user_id?: string
  contact_name: string
  name?: string
  relationship: string
  phone_number: string
  is_primary?: boolean
  is_verified?: boolean
  created_at?: string
  updated_at?: string
}

export type EmergencyTripContext = {
  trip_id: string
  title?: string
  destination: string
  destination_city?: string
  booking_reference?: string
  hotel_name?: string
  start_date?: string
  end_date?: string
  traveller_count?: number
  status?: string
}

export type LocationSource = 'gps' | 'geocoded' | 'manual_unverified'

export type LocationCoordinates = {
  latitude: number
  longitude: number
  accuracy_meters?: number | null
  captured_at?: string | null
  address_or_landmark?: string | null
  source?: LocationSource | null
  display_label?: string | null
  place_id?: string | null
}

export interface GeocodePlaceResult {
  place_id: string
  display_name: string
  name: string
  locality?: string | null
  state?: string | null
  country?: string | null
  latitude: number
  longitude: number
  bounding_box?: number[] | null
}

export interface GeocodeSearchResponse {
  query: string
  results: GeocodePlaceResult[]
  attribution: string
  provider: string
  rate_limited?: boolean
}

export type ActivateSosResponse = {
  sos_event_id: string
  event_id: string
  status: string
  emergency_notice: string
  disclaimer: string
  official_number_to_dial: string
  trusted_contacts_notified_mode: string
  instructions: string[]
  delivery_provider_status?: {
    sms_configured: boolean
    push_configured: boolean
    mode: string
    message: string
  }
  location_captured?: LocationCoordinates | null
  location_source?: string | null
  location_display?: string | null
  timestamp: string
}

export type EmergencyInfoResponse = {
  disclaimer?: string
  safety_notice?: string
  primary_emergency_number?: string
  official_numbers: EmergencyOfficialNumber[]
  official_services?: EmergencyOfficialNumber[]
  user_contacts: TrustedContact[]
  trusted_contacts?: TrustedContact[]
  trip_context?: EmergencyTripContext | null
  current_trip_context?: EmergencyTripContext | null
  location_tracking_status?: string
}

export type StructuredVoiceAction = {
  action_type: string
  target_id?: string | null
  details?: Record<string, unknown>
}

export type VoiceTranscriptionResponse = {
  transcript: string
  language_code: string
  confidence: number
  detection_source: string
  requires_explicit_confirmation: boolean
  confirmation_prompt?: string | null
  structured_action?: StructuredVoiceAction | null
  raw_audio_persisted: boolean
}



