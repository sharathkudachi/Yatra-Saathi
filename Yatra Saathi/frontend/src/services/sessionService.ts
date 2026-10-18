import { apiData } from './apiClient'
import { authService } from './authService'
import type { TripRequest } from '../types/travel'

// Client for the backend's agent-session API (/api/v1/sessions/...). The agent runs
// asynchronously: send a message, then poll the session until it leaves `executing`.
// Field names are mapped from the backend's snake_case in this file only.

export type SessionStatus = 'planning' | 'executing' | 'awaiting_input' | 'awaiting_confirmation' | 'paused' | 'completed' | 'failed'
export type PlanStep = { id?: string; description?: string; tool?: string; [key: string]: unknown }

export type AgentSession = {
  sessionId: string; status: SessionStatus; currency: string; goalText: string
  spendCap: string; effectiveCap: string; capSource: string; committed: string; cartTotal: string; remaining: string
  planVersion: number; planSteps: PlanStep[]; currentStep: number
  replanCount: number; replanLimit: number; lastErrorCode: string | null; updatedAt: string
}
/** Schedule/stay facts for a cart line (read-only; used to build the itinerary). */
export type CartItemDetails =
  | { type: 'flight'; airline: string; flight_number: string; cabin_class: string; departs_at: string; arrives_at: string;
      duration_minutes: number; stops: number; origin_code: string; origin_city: string; destination_code: string; destination_city: string }
  | { type: 'stay'; hotel: string; room: string; city: string; address: string | null; checkin_time: string | null; checkout_time: string | null }

export type CartItem = {
  cartItemId: string; itemGroupId: string; kind: string; entityType: string; entityId: string
  title: string | null; forDate: string; units: number; unitPrice: string; lineTotal: string
  details: CartItemDetails | null
}
export type Cart = { cartId: string; status: string; version: number; currency: string; subtotal: string; tax: string; total: string; items: CartItem[] }
export type Confirmation = {
  confirmationId: string; cartVersion: number; status: string; snapshotHash: string; currency: string
  subtotal: string; tax: string; total: string; effectiveCap: string; requestedAt: string; expiresAt: string
}
export type AuditEvent = {
  eventId: string; seq: number; eventType: string; occurredAt: string; actor: string; outcome: string
  reasonCode: string | null; reason: string | null; input: Record<string, unknown>; result: Record<string, unknown>
}
export type Booking = { bookingId: string; bookingReference: string; totalAmount: string; currency: string; taxAmount: string; status: string; createdAt: string }
export type BookingOutcome = { bookingId: string; bookingReference: string; totalAmount: string }
export type AuditVerification = { ok: boolean; chainOk: boolean; seqGapless: boolean; replayMatches: boolean; issues: string[] }

type Raw = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any

const MONEY_RE = /^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$/

/** Normalizes a typed budget ("25,000", " 25000.5 ") to the backend's 2-decimal string, or null if invalid. */
export function normalizeMoney(value: string): string | null {
  const compact = value.replace(/[\s,_]/g, '')
  if (!MONEY_RE.test(compact)) return null
  const [whole, fraction = ''] = compact.split('.')
  return `${whole}.${fraction.padEnd(2, '0')}`
}

function toSession(raw: Raw): AgentSession {
  return {
    sessionId: raw.session_id, status: raw.status, currency: raw.currency, goalText: raw.goal_text ?? '',
    spendCap: raw.spend_cap, effectiveCap: raw.effective_cap, capSource: raw.cap_source, committed: raw.committed,
    cartTotal: raw.cart_total, remaining: raw.remaining, planVersion: raw.plan_version ?? 0,
    planSteps: Array.isArray(raw.plan_steps) ? raw.plan_steps : [], currentStep: raw.current_step ?? 0,
    replanCount: raw.replan_count ?? 0, replanLimit: raw.replan_limit ?? 0, lastErrorCode: raw.last_error_code ?? null,
    updatedAt: raw.updated_at,
  }
}

function toConfirmation(raw: Raw): Confirmation {
  return {
    confirmationId: raw.confirmation_id, cartVersion: raw.cart_version, status: raw.status, snapshotHash: raw.snapshot_hash,
    currency: raw.currency, subtotal: raw.subtotal, tax: raw.tax, total: raw.total, effectiveCap: raw.effective_cap,
    requestedAt: raw.requested_at, expiresAt: raw.expires_at,
  }
}

function authed(init: RequestInit = {}): RequestInit {
  return { ...init, headers: { ...authService.authHeaders(), ...(init.headers as Record<string, string> | undefined) } }
}

const base = (sessionId: string) => `/api/v1/sessions/${encodeURIComponent(sessionId)}`

export const sessionService = {
  async create(goalText: string, trip: TripRequest, goalLanguage: string, spendCap: string): Promise<AgentSession> {
    // Constraint keys follow the agent's documented TripRequirements fields (backend stores them as-is).
    const constraints: Record<string, unknown> = {
      destination_name: trip.destination.trim() || null, start_date: trip.startDate || null, end_date: trip.endDate || null,
      travellers: trip.travellers, currency: trip.currency, language: goalLanguage, preferences: trip.preferences.trim() || null,
    }
    const raw = await apiData<Raw>('/api/v1/sessions', authed({
      method: 'POST',
      body: JSON.stringify({ trip_id: null, goal_text: goalText, goal_language: goalLanguage, constraints, spend_cap: spendCap, currency: trip.currency }),
    }))
    return toSession(raw)
  },

  async sendMessage(sessionId: string, message: string): Promise<void> {
    await apiData(`${base(sessionId)}/messages`, authed({ method: 'POST', body: JSON.stringify({ message }) }))
  },

  async get(sessionId: string): Promise<AgentSession> {
    return toSession(await apiData<Raw>(base(sessionId), authed()))
  },

  async cart(sessionId: string): Promise<Cart | null> {
    const raw = await apiData<Raw>(`${base(sessionId)}/cart`, authed())
    // Empty cart is {cart: null, items: []}; a present cart is flat {cart_id, ...}.
    if (!raw.cart_id) return null
    return {
      cartId: raw.cart_id, status: raw.status, version: raw.version, currency: raw.currency,
      subtotal: raw.subtotal, tax: raw.tax, total: raw.total,
      items: (raw.items as Raw[]).map((it) => ({
        cartItemId: it.cart_item_id, itemGroupId: it.item_group_id, kind: it.kind, entityType: it.entity_type, entityId: it.entity_id,
        title: it.title ?? null, details: it.details ?? null, forDate: it.for_date, units: it.units, unitPrice: it.unit_price, lineTotal: it.line_total,
      })),
    }
  },

  async audit(sessionId: string): Promise<AuditEvent[]> {
    const raw = await apiData<{ events: Raw[] }>(`${base(sessionId)}/audit`, authed())
    return raw.events.map((e) => ({
      eventId: e.event_id, seq: e.seq, eventType: e.event_type, occurredAt: e.occurred_at, actor: e.actor, outcome: e.outcome,
      reasonCode: e.reason_code ?? null, reason: e.reason ?? null, input: e.input ?? {}, result: e.result ?? {},
    }))
  },

  async verifyAudit(sessionId: string): Promise<AuditVerification> {
    const raw = await apiData<Raw>(`${base(sessionId)}/audit/verify`, authed())
    return { ok: raw.ok, chainOk: raw.chain_ok, seqGapless: raw.seq_gapless, replayMatches: raw.replay_matches, issues: raw.issues ?? [] }
  },

  async currentConfirmation(sessionId: string): Promise<Confirmation | null> {
    const raw = await apiData<Raw>(`${base(sessionId)}/confirmations/current`, authed())
    // No pending confirmation is {confirmation: null}; a pending one is flat.
    return raw.confirmation_id ? toConfirmation(raw) : null
  },

  async approve(sessionId: string, confirmation: Confirmation): Promise<BookingOutcome> {
    const raw = await apiData<Raw>(`${base(sessionId)}/confirmations/${encodeURIComponent(confirmation.confirmationId)}/approve`,
      authed({ method: 'POST', body: JSON.stringify({ snapshot_hash: confirmation.snapshotHash }) }))
    return { bookingId: raw.booking_id, bookingReference: raw.booking_reference, totalAmount: raw.total_amount }
  },

  async decline(sessionId: string, confirmationId: string, note?: string): Promise<void> {
    await apiData(`${base(sessionId)}/confirmations/${encodeURIComponent(confirmationId)}/decline`,
      authed({ method: 'POST', body: JSON.stringify({ note: note || null }) }))
  },

  async booking(sessionId: string): Promise<Booking | null> {
    const raw = await apiData<{ booking: Raw | null }>(`${base(sessionId)}/booking`, authed())
    const b = raw.booking
    return b ? { bookingId: b.booking_id, bookingReference: b.booking_reference, totalAmount: b.total_amount, currency: b.currency, taxAmount: b.tax_amount, status: b.status, createdAt: b.created_at } : null
  },
}
