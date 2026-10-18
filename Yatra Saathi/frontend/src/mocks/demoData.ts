import type { BudgetSummary, ItineraryStop } from '../types/travel'

// These records are from one matching seeded trip. Generic destination searches
// use the full hotelCatalog.json fixture and do not reuse this trip's budget.
export const demoItinerary: ItineraryStop[] = [
  { id: 'itm_ed031217', time: 'Flexible', title: 'Textile Museum', detail: 'Selected inside the stated budget cap after two alternatives were rejected.', category: 'culture' },
  { id: 'itm_b646d495', time: '13:00', title: 'Jaipur Bazaar', detail: 'Carried 3–1 in the group vote.', category: 'culture' },
  { id: 'itm_416a0f2c', time: '18:00', title: 'Handloom Cooperative', detail: 'From the saved trip itinerary.', category: 'culture' },
]

export const demoBudget: BudgetSummary = {
  currency: 'INR', total: '16000.00', committed: '3115.44', planned: '12750.00',
}
