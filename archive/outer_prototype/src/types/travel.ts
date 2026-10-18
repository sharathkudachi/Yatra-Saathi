export type HotelOption = {
  hotelId: string
  roomTypeId: string
  inventoryIds: string[]
  maxOccupancy: number
  name: string
  city: string
  country: string
  description: string
  imageUrl: string
  roomName: string
  price: string
  currency: string
  nights: number
  availableUnits: number
  tags: string[]
  /** Optional property details supplied by the hotel/backend, never frontend demo placeholders. */
  roomImages?: string[]
  surroundingsImages?: string[]
  menuItems?: Array<{ name: string; description?: string; price?: string; currency?: string; category?: string }>
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
  category: 'stay' | 'food' | 'culture' | 'nature'
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
