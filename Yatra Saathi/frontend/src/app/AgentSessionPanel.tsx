import { useEffect, useState } from 'react'
import { AlertTriangle, Check, ChevronDown, CircleDot, ListChecks, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'
import type { AgentSession, AuditEvent, AuditVerification, Booking, Cart, Confirmation } from '../services/sessionService'
import { formatMoney, minorUnitsToDecimal } from '../utils/format'
import AuditTimeline from './AuditTimeline'

type Props = {
  session: AgentSession
  events: AuditEvent[]
  cart: Cart | null
  confirmation: Confirmation | null
  booking: Booking | null
  verification: AuditVerification | null
  stalled: boolean
  deciding: boolean
  decisionError: string
  onApprove: () => void
  onDecline: () => void
  onRefresh: () => void
  onVerify: () => void
}

const TIMELINE_TYPES = new Set([
  'PLAN_CREATED', 'REPLAN', 'TOOL_CALL', 'TOOL_RESULT', 'BUDGET_CHECK', 'ACTION_REFUSED', 'CLARIFICATION_REQUESTED',
  'CART_CREATED', 'CART_UPDATED', 'CONFIRMATION_REQUIRED', 'CONFIRMATION_RECEIVED', 'CONFIRMATION_DECLINED',
  'CONFIRMATION_EXPIRED', 'CONFIRMATION_INVALIDATED', 'BOOKING_ATTEMPT', 'BOOKING_SUCCESS', 'BOOKING_REFUSED', 'BOOKING_FAILED', 'ERROR',
])

function minor(value: unknown, currency: string) {
  return typeof value === 'number' && Number.isInteger(value) ? formatMoney(minorUnitsToDecimal(BigInt(value)), currency) : '—'
}

/** One plain-language line per audit event, built only from fields the backend recorded. */
export function describeEvent(event: AuditEvent, currency: string, t: (key: string) => string) {
  const { input, result } = event
  switch (event.eventType) {
    case 'PLAN_CREATED': return t('session.ev.plan').replace('{version}', String(result.plan_version ?? '')).replace('{count}', String(Array.isArray(input.steps) ? input.steps.length : 0))
    case 'REPLAN': return t('session.ev.replan').replace('{reason}', String(input.reason ?? input.reason_code ?? ''))
    case 'TOOL_CALL': return t('session.ev.toolCall').replace('{tool}', String(input.tool ?? ''))
    case 'TOOL_RESULT': return t('session.ev.toolResult').replace('{accepted}', String(Array.isArray(result.accepted) ? result.accepted.length : 0)).replace('{rejected}', String(Array.isArray(result.rejected) ? result.rejected.length : 0))
    case 'BUDGET_CHECK': return t(result.passed ? 'session.ev.budgetPass' : 'session.ev.budgetFail').replace('{total}', minor(input.total_minor, currency)).replace('{cap}', minor(result.effective_cap_minor, currency))
    case 'ACTION_REFUSED': {
      // Backend reasons can carry raw minor units; prefer the translated message for known codes.
      const key = `session.refusal.${event.reasonCode}`
      return t('session.ev.refused').replace('{code}', event.reasonCode ?? '').replace('{reason}', t(key) !== key ? t(key) : event.reason ?? '')
    }
    case 'CLARIFICATION_REQUESTED': {
      // Offered options are shown as cards in the chat; the timeline keeps just the opening line.
      const question = String(input.question ?? '')
      const count = Array.isArray(input.options) ? input.options.length : 0
      return t('session.ev.clarify').replace('{question}', count ? `${question.split('\n')[0]} (${count})` : question)
    }
    case 'CART_CREATED': case 'CART_UPDATED': return t('session.ev.cart').replace('{version}', String(result.version ?? ''))
    case 'CONFIRMATION_REQUIRED': return t('session.ev.confirmRequired')
    case 'CONFIRMATION_RECEIVED': return t('session.ev.confirmReceived')
    case 'CONFIRMATION_DECLINED': return t('session.ev.confirmDeclined')
    case 'CONFIRMATION_EXPIRED': return t('session.ev.confirmExpired')
    case 'CONFIRMATION_INVALIDATED': return t('session.ev.confirmInvalidated')
    case 'BOOKING_ATTEMPT': return t('session.ev.bookingAttempt')
    case 'BOOKING_SUCCESS': return t('session.ev.bookingSuccess').replace('{reference}', String(result.booking_reference ?? ''))
    case 'BOOKING_REFUSED': case 'BOOKING_FAILED': return t('session.ev.bookingFailed').replace('{code}', event.reasonCode ?? '').replace('{reason}', event.reason ?? '')
    default: return `${event.eventType}${event.reason ? ` · ${event.reason}` : ''}`
  }
}

function groupCart(cart: Cart) {
  const groups = new Map<string, { title: string; kind: string; dates: string[]; units: number; total: bigint }>()
  for (const item of cart.items) {
    const group = groups.get(item.itemGroupId) ?? { title: item.title ?? item.entityId, kind: item.kind, dates: [], units: item.units, total: 0n }
    group.dates.push(item.forDate)
    const [whole, fraction = ''] = item.lineTotal.split('.')
    group.total += BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
    groups.set(item.itemGroupId, group)
  }
  return [...groups.entries()].map(([id, g]) => ({ id, ...g, dates: g.dates.sort(), total: minorUnitsToDecimal(g.total) }))
}

function useCountdown(expiresAt: string | undefined) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!expiresAt) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [expiresAt])
  if (!expiresAt) return null
  const ms = Date.parse(expiresAt) - now
  if (!Number.isFinite(ms)) return null
  const seconds = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export default function AgentSessionPanel(props: Props) {
  const { session, events, cart, confirmation, booking, verification, stalled, deciding, decisionError } = props
  const { t } = useLanguage()
  const countdown = useCountdown(confirmation?.expiresAt)
  const timeline = events.filter((event) => TIMELINE_TYPES.has(event.eventType))
  const lines = cart ? groupCart(cart) : []

  return <section className="session-panel" aria-label={t('session.title')}>
    <div className="session-status-row">
      <span className={`session-status status-${session.status}`}><CircleDot size={11} /> {t(`session.status.${session.status}`)}</span>
      <span className="session-replans">{t('session.replans').replace('{count}', String(session.replanCount)).replace('{limit}', String(session.replanLimit))}</span>
      <button type="button" className="session-refresh" onClick={props.onRefresh} aria-label={t('session.refresh')} title={t('session.refresh')}><RefreshCw size={13} /></button>
    </div>

    {stalled && <div className="session-alert" role="status"><AlertTriangle size={14} /> {t('session.stalled')}</div>}
    {session.status === 'failed' && <div className="session-alert session-error" role="alert"><AlertTriangle size={14} /> {t(`session.error.${session.lastErrorCode ?? 'unknown'}`)}</div>}

    {(session.planSteps.length > 0 || timeline.length > 0) && (
      <details className="session-audit-details">
        <summary className="audit-summary-header">
          <Sparkles size={12} className="trace-sparkle-icon" />
          <span>How Yatra planned this · AI Execution & Audit Trace ({session.planSteps.length} steps)</span>
          <ChevronDown size={13} className="accordion-chevron" />
        </summary>
        <div className="audit-details-body">
          {session.planSteps.length > 0 && (
            <div className="session-block">
              <span className="mini-label"><ListChecks size={11} /> {t('session.plan').replace('{version}', String(session.planVersion))}</span>
              <ol className="session-plan">{session.planSteps.map((step, index) => <li key={step.id ?? index} className={index < session.currentStep ? 'done' : index === session.currentStep ? 'current' : ''}>{String(step.description ?? step.tool ?? step.id ?? '')}</li>)}</ol>
            </div>
          )}
          {timeline.length > 0 && (
            <div className="session-block">
              <span className="mini-label">{t('session.timeline')}</span>
              <AuditTimeline events={events} currency={session.currency} />
            </div>
          )}
        </div>
      </details>
    )}

    {cart && <div className="session-block">
      <span className="mini-label">{t('session.cart')}</span>
      <ul className="session-cart">{lines.map((line) => <li key={line.id}><div><strong>{line.title}</strong><small>{line.dates.length > 1 ? `${line.dates[0]} → ${line.dates[line.dates.length - 1]} · ${t('session.nights').replace('{count}', String(line.dates.length))}` : line.dates[0]} · ×{line.units}</small></div><span>{formatMoney(line.total, cart.currency)}</span></li>)}</ul>
      <dl className="session-totals"><div><dt>{t('session.subtotal')}</dt><dd>{formatMoney(cart.subtotal, cart.currency)}</dd></div><div><dt>{t('session.tax')}</dt><dd>{formatMoney(cart.tax, cart.currency)}</dd></div><div className="grand"><dt>{t('session.total')}</dt><dd>{formatMoney(cart.total, cart.currency)}</dd></div></dl>
    </div>}

    {confirmation && <div className="session-confirm" role="region" aria-label={t('session.confirmTitle')}>
      <strong><ShieldCheck size={15} /> {t('session.confirmTitle')}</strong>
      <p>{t('session.confirmBody').replace('{total}', formatMoney(confirmation.total, confirmation.currency)).replace('{cap}', formatMoney(confirmation.effectiveCap, confirmation.currency))}</p>
      {countdown && <small>{t('session.expiresIn').replace('{time}', countdown)}</small>}
      {decisionError && <div className="session-alert session-error" role="alert">{decisionError}</div>}
      <div className="session-confirm-actions"><button type="button" className="modal-primary" disabled={deciding} onClick={props.onApprove}>{deciding ? <span className="spinner" /> : t('session.approve')}</button><button type="button" className="modal-secondary" disabled={deciding} onClick={props.onDecline}>{t('session.decline')}</button></div>
    </div>}

    {booking && <div className="session-booked" role="status"><Check size={15} /><div><strong>{t('session.booked')}</strong><span>{t('session.bookingRef').replace('{reference}', booking.bookingReference)} · {formatMoney(booking.totalAmount, booking.currency)}</span><small>{t('session.mockNote')}</small></div></div>}

    {timeline.length > 0 && <div className="session-verify">
      <button type="button" className="text-button" onClick={props.onVerify}>{t('session.verify')}</button>
      {verification && <span className={verification.ok ? 'verified' : 'unverified'}>{verification.ok ? t('session.verified') : `${t('session.unverified')} ${verification.issues.join('; ')}`}</span>}
    </div>}
  </section>
}
