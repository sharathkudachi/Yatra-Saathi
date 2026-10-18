import type { AuditEvent } from './sessionService'
import { isTripOptions, type TripOption } from '../app/TripOptions'

// A trip's conversation, rebuilt from its (hash-chained) audit trail: the user's messages are
// SESSION_RESUMED events, Yatra's side is its questions, the approval request and the outcome.
// Used when a trip is reopened, after a reload, and in My trips.

export type DateSuggestion = { label: string; reply: string; detail: string }
export type HistoryMessage = { role: 'user' | 'assistant'; content: string; at: string; options?: TripOption[]; suggestions?: DateSuggestion[] }
export function dateSuggestions(value: unknown): DateSuggestion[] | undefined {
  return Array.isArray(value) && value.length && value.every((s) => s && typeof s.reply === 'string' && typeof s.label === 'string') ? value as DateSuggestion[] : undefined
}
type T = (key: string) => string

export function historyFromEvents(events: AuditEvent[], t: T): HistoryMessage[] {
  const said = events.filter((e) => e.eventType === 'SESSION_RESUMED' && e.actor === 'user' && typeof e.input.message === 'string')
  const out: HistoryMessage[] = []
  for (const e of events) {
    const at = e.occurredAt
    switch (e.eventType) {
      case 'SESSION_CREATED':
        // Sessions from before messages were recorded: their opening request is all we have.
        if (!said.length && typeof e.input.goal_text === 'string') out.push({ role: 'user', content: e.input.goal_text, at })
        break
      case 'SESSION_RESUMED':
        if (e.actor === 'user' && typeof e.input.message === 'string') out.push({ role: 'user', content: e.input.message, at })
        break
      case 'CLARIFICATION_REQUESTED':
        if (typeof e.input.question === 'string') {
          // Offered trip options show as cards; the text keeps just its opening line.
          const options = isTripOptions(e.input.options) ? e.input.options : undefined
          out.push({ role: 'assistant', content: options ? e.input.question.split('\n')[0] : e.input.question, at, options,
            suggestions: dateSuggestions(e.input.suggestions) })
        }
        break
      case 'CONFIRMATION_REQUIRED': {
        const picked = chosenOption(events.filter((x) => x.seq <= e.seq))
        out.push({ role: 'assistant', content: t('session.msg.confirm'), at, options: picked ? [picked] : undefined })
        break
      }
      case 'CONFIRMATION_DECLINED': out.push({ role: 'assistant', content: t('session.error.confirmation_declined'), at }); break
      case 'BOOKING_SUCCESS':
        out.push({ role: 'assistant', content: t('session.msg.booked').replace('{reference}', String(e.result.booking_reference ?? '')), at })
        break
      case 'BOOKING_FAILED': out.push({ role: 'assistant', content: t('session.error.booking_failed'), at }); break
    }
  }
  return out
}

/** The option the user picked (from the agent's choose_option call), for the plan-ready recap. */
export function chosenOption(events: AuditEvent[]): TripOption | undefined {
  const pick = [...events].reverse().find((e) => e.eventType === 'TOOL_CALL' && e.input.tool === 'choose_option')
  const key = (pick?.input.arguments as Record<string, unknown> | undefined)?.option
  if (!pick || typeof key !== 'string') return undefined
  const offered = [...events].reverse().find((e) => e.seq < pick.seq && e.eventType === 'CLARIFICATION_REQUESTED' && isTripOptions(e.input.options))
  return offered && isTripOptions(offered.input.options) ? offered.input.options.find((o) => o.key === key) : undefined
}
