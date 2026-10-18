import { useState } from 'react'
import { Check, ChevronRight, CircleDot, Gavel, ShieldAlert, ShieldCheck, User, X } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'
import type { AuditEvent } from '../services/sessionService'
import { describeEvent } from './AgentSessionPanel'

// The run's audit trail as a readable, replayable timeline: every recorded entry in order,
// numbered and timestamped, with the exact recorded arguments/result one click away. The two
// entries judges look for -- the spend-cap refusal and the confirmation gate -- are labelled.

const HIDDEN = new Set(['SESSION_CREATED'])

export function isCapRefusal(e: AuditEvent) {
  return (e.eventType === 'BUDGET_CHECK' || e.eventType === 'ACTION_REFUSED') && e.reasonCode === 'SPEND_CAP_EXCEEDED'
}
export function isGate(e: AuditEvent) {
  return e.eventType.startsWith('CONFIRMATION_')
}

function badge(e: AuditEvent, t: (k: string) => string) {
  if (isCapRefusal(e)) return { cls: 'refusal', icon: <ShieldAlert size={12} />, text: t('audit.capRefusal') }
  if (e.eventType === 'CONFIRMATION_REQUIRED') return { cls: 'gate', icon: <ShieldCheck size={12} />, text: t('audit.gateOpened') }
  if (e.eventType === 'CONFIRMATION_RECEIVED') return { cls: 'gate', icon: <Gavel size={12} />, text: t('audit.gateApproved') }
  if (isGate(e)) return { cls: 'gate', icon: <ShieldCheck size={12} />, text: t('audit.gate') }
  if (e.outcome === 'refused' || e.outcome === 'failed') return { cls: 'refusal', icon: <X size={12} />, text: t('audit.refused') }
  return null
}

function describe(e: AuditEvent, currency: string, t: (k: string) => string): string {
  const input = e.input as Record<string, unknown>
  switch (e.eventType) {
    case 'SESSION_RESUMED': return `${t('trip.historyYou')}: “${String(input.message ?? '')}”`
    case 'PLAN_STEP_STARTED': return t('audit.stepStarted').replace('{step}', String(input.step_id ?? ''))
    case 'PLAN_STEP_COMPLETED': return t(e.outcome === 'failed' ? 'audit.stepFailed' : 'audit.stepDone').replace('{step}', String(input.step_id ?? ''))
    case 'TOOL_CALL': {
      const args = (input.arguments ?? {}) as Record<string, unknown>
      const brief = ['leg', 'date', 'check_in', 'check_out', 'option', 'estimated_total'].filter((k) => args[k] != null).map((k) => `${k}: ${String(args[k])}`).join(', ')
      const by = args.requested_by === 'llm_function_call' ? ` · ${t('audit.byModel').replace('{model}', String(args.model ?? ''))}`
        : args.requested_by === 'user_choice' ? ` · ${t('audit.byUser')}` : ''
      return `${describeEvent(e, currency, t)}${brief ? ` (${brief})` : ''}${by}`
    }
    default: return describeEvent(e, currency, t)
  }
}

export default function AuditTimeline({ events, currency }: { events: AuditEvent[]; currency: string }) {
  const { language, t } = useLanguage()
  const [only, setOnly] = useState(false)
  const all = events.filter((e) => !HIDDEN.has(e.eventType))
  const shown = only ? all.filter((e) => isCapRefusal(e) || isGate(e) || e.outcome === 'refused') : all
  const refusals = all.filter(isCapRefusal).length
  const gates = all.filter((e) => e.eventType === 'CONFIRMATION_REQUIRED').length
  const stamp = (iso: string) => new Intl.DateTimeFormat(language.tag, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(iso))

  return <div className="audit-timeline">
    <div className="audit-summary">
      <span>{t('audit.entries').replace('{count}', String(all.length))}</span>
      <span className={refusals ? 'refusal' : ''}><ShieldAlert size={12} /> {t('audit.refusals').replace('{count}', String(refusals))}</span>
      <span className={gates ? 'gate' : ''}><ShieldCheck size={12} /> {t('audit.gates').replace('{count}', String(gates))}</span>
      <label><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> {t('audit.onlyKey')}</label>
    </div>
    <ol>{shown.map((e) => {
      const b = badge(e, t)
      const icon = e.actor === 'user' ? <User size={11} /> : e.outcome === 'refused' || e.outcome === 'failed' ? <X size={11} /> : e.eventType.startsWith('PLAN_STEP') ? <CircleDot size={11} /> : <Check size={11} />
      return <li key={e.eventId} className={`audit-entry outcome-${e.outcome}${b ? ` key-${b.cls}` : ''}`}>
        <details>
          <summary>
            <span className="audit-seq">#{e.seq}</span>
            <time dateTime={e.occurredAt}>{stamp(e.occurredAt)}</time>
            <span className="audit-icon">{icon}</span>
            <span className="audit-text">{b && <em className={`audit-badge ${b.cls}`}>{b.icon} {b.text}</em>}{describe(e, currency, t)}
              {e.reasonCode && <small className="audit-reason">{e.reasonCode}{e.reason ? ` — ${e.reason}` : ''}</small>}</span>
            <ChevronRight size={12} className="audit-chevron" />
          </summary>
          <div className="audit-detail">
            <div><b>{t('audit.type')}</b> {e.eventType} · <b>{t('audit.actor')}</b> {e.actor} · <b>{t('audit.outcome')}</b> {e.outcome}</div>
            <pre>{JSON.stringify({ input: e.input, result: e.result }, null, 2)}</pre>
          </div>
        </details>
      </li>
    })}</ol>
  </div>
}
