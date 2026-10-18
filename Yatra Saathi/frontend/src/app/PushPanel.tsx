import { useEffect, useState } from 'react'
import { BellRing, PlaneLanding, Send } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'
import { pushService, type PushState } from '../services/pushService'

type Note = { notification_id: string; kind: string; title: string; body: string; created_at: string }

// Bell panel: turn on push notifications for this device (phone or computer), send a test,
// preview the "you've landed" notification, and see recent notifications.
export default function PushPanel({ prefs, signedIn }: { prefs: Record<string, boolean>; signedIn: boolean }) {
  const { language, t } = useLanguage()
  const [state, setState] = useState<PushState | 'loading'>('loading')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [notes, setNotes] = useState<Note[]>([])

  const refreshHistory = () => { if (signedIn) void pushService.history().then((d) => setNotes(d.notifications)).catch(() => undefined) }
  useEffect(() => { void pushService.state().then(setState).catch(() => setState('unsupported')); refreshHistory() }, [signedIn])
  // Preference toggles above apply to this device's pushes too.
  useEffect(() => { if (state === 'on') void pushService.updatePrefs(prefs).catch(() => undefined) }, [prefs, state])

  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage('')
    try { await action() } catch { setMessage(t('push.error')) } finally { setBusy(false); refreshHistory() }
  }
  const enable = () => run(async () => { const next = await pushService.enable(prefs); setState(next); if (next === 'on') setMessage(t('push.enabled')) })
  const disable = () => run(async () => { await pushService.disable(); setState('off') })
  const test = (kind: 'test' | 'flight_landed') => run(async () => {
    const r = await pushService.sendTest(kind)
    setMessage(r.pushEnabled && state === 'on' ? t('push.sent') : `${t('push.recordedOnly')} — ${r.title}: ${r.body}`)
  })

  if (!signedIn) return <div className="push-panel"><p className="push-hint">{t('push.signIn')}</p></div>
  const stateText: Record<string, string> = {
    on: t('push.stateOn'), off: t('push.stateOff'), blocked: t('push.stateBlocked'), unsupported: t('push.stateUnsupported'),
    insecure: t('push.stateInsecure'), 'server-disabled': t('push.stateServerOff'), loading: '…',
  }
  return <div className="push-panel">
    <div className="push-status"><BellRing size={16} /><div><strong>{t('push.title')}</strong><span>{stateText[state]}</span></div>
      {state === 'on'
        ? <button type="button" className="push-secondary" disabled={busy} onClick={() => void disable()}>{t('push.turnOff')}</button>
        : (state === 'off' || state === 'server-disabled') && <button type="button" className="push-primary" disabled={busy} onClick={() => void enable()}>{t('push.turnOn')}</button>}
    </div>
    <div className="push-actions">
      <button type="button" disabled={busy} onClick={() => void test('test')}><Send size={13} /> {t('push.test')}</button>
      <button type="button" disabled={busy} onClick={() => void test('flight_landed')}><PlaneLanding size={13} /> {t('push.previewLanding')}</button>
    </div>
    {message && <p className="push-message" role="status">{message}</p>}
    <p className="push-hint">{t('push.phoneHint')}</p>
    {notes.length > 0 && <div className="push-history"><strong>{t('push.recent')}</strong><ol>{notes.slice(0, 6).map((n) =>
      <li key={n.notification_id}><span>{new Intl.DateTimeFormat(language.tag, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(n.created_at))}</span><b>{n.title}</b><p>{n.body}</p></li>)}</ol></div>}
  </div>
}
