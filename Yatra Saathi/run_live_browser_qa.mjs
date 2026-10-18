// run_live_browser_qa.mjs
// Full End-to-End Live Chrome DevTools Protocol automation for Yatra v1.0 Release Audit

import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'

const CDP_HTTP = 'http://127.0.0.1:9222'
const TARGET_URL = 'http://localhost:5173'

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function startChrome() {
  const profileDir = path.join(process.env.TEMP || 'C:\\Temp', `chrome_qa_${Date.now()}`)
  console.log('Launching headless Chrome with debugging port 9222...')
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    '--remote-debugging-port=9222',
    `--user-data-dir=${profileDir}`,
    '--window-size=1920,1080',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ], { detached: false })

  for (let i = 0; i < 20; i++) {
    await sleep(500)
    try {
      const res = await fetch(`${CDP_HTTP}/json/version`)
      if (res.ok) {
        console.log('Chrome CDP ready on port 9222.')
        return chrome
      }
    } catch {
      // wait
    }
  }
  throw new Error('Chrome failed to start on port 9222 within 10 seconds.')
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl
    this.ws = null
    this.nextId = 1
    this.pending = new Map()
    this.consoleLogs = []
    this.networkRequests = []
    this.networkErrors = []
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl)
      this.ws.onopen = () => resolve()
      this.ws.onerror = (err) => reject(err)
      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id)
          this.pending.delete(msg.id)
          if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)))
          else resolve(msg.result)
        } else if (msg.method) {
          this.handleEvent(msg.method, msg.params)
        }
      }
    })
  }

  handleEvent(method, params) {
    if (method === 'Runtime.consoleAPICalled') {
      const text = params.args.map((a) => a.value ?? a.description ?? '').join(' ')
      this.consoleLogs.push({ type: params.type, text, timestamp: params.timestamp })
    } else if (method === 'Runtime.exceptionThrown') {
      const text = params.exceptionDetails?.exception?.description || params.exceptionDetails?.text
      this.consoleLogs.push({ type: 'error', text, exception: true })
    } else if (method === 'Network.responseReceived') {
      const resp = params.response
      this.networkRequests.push({
        url: resp.url,
        status: resp.status,
        statusText: resp.statusText,
        mimeType: resp.mimeType,
      })
      if (resp.status >= 400) {
        this.networkErrors.push({ url: resp.url, status: resp.status })
      }
    }
  }

  async send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++
      this.pending.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }

  async evaluate(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    if (res.exceptionDetails) {
      throw new Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text)
    }
    return res.result?.value
  }

  async saveScreenshot(filepath) {
    try {
      const res = await this.send('Page.captureScreenshot', { format: 'png' })
      if (res && res.data) {
        fs.writeFileSync(filepath, Buffer.from(res.data, 'base64'))
        return true
      }
    } catch {
      // ignore
    }
    return false
  }
}

async function runQA() {
  console.log('======================================================')
  console.log('       YATRA V1.0 LIVE BROWSER AUDIT & QA SUITE')
  console.log('======================================================')
  console.log('Target URL:', TARGET_URL)

  const chromeProcess = await startChrome()

  try {
    console.log('\n[Phase 1] Initializing browser session and loading Yatra...')
    const newTargetRes = await fetch(`${CDP_HTTP}/json/new?${encodeURIComponent(TARGET_URL)}`, { method: 'PUT' })
    const targetInfo = await newTargetRes.json()
    const cdp = new CDPClient(targetInfo.webSocketDebuggerUrl)
    await cdp.connect()

    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await cdp.send('Network.enable')

    // Inject React input helper into window
    await cdp.evaluate(`
      window.__setReactValue = function(el, val) {
        if (!el) return;
        const proto = el instanceof HTMLTextAreaElement
          ? window.HTMLTextAreaElement.prototype
          : el instanceof HTMLSelectElement
          ? window.HTMLSelectElement.prototype
          : window.HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) setter.call(el, val);
        else el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      };
    `)

    // Initial wait for React & assets
    await sleep(4000)

    const qaReport = {
      testResults: {},
      consoleErrors: [],
      networkErrors: [],
      capturedScreenshots: [],
      details: {},
    }

    // -------------------------------------------------------------------------
    // TEST 1: Application Startup
    // -------------------------------------------------------------------------
    console.log('\n[TEST 1] Application Startup & Layout Verification...')
    const startupCheck = await cdp.evaluate(`(() => {
      return {
        title: document.title,
        topbar: !!document.querySelector('.topbar'),
        brand: document.querySelector('.brand')?.innerText || '',
        voiceButton: !!document.querySelector('.voice-topbar-button'),
        emergencyButton: !!document.querySelector('.emergency-topbar-button'),
        notificationsButton: !!document.querySelector('.notifications-button'),
        signInButton: !!document.querySelector('.sign-in-button'),
        chatInput: !!document.getElementById('chat-input'),
        mapContainer: !!document.querySelector('.yatra-travel-map-card') || !!document.querySelector('.map-container') || !!document.getElementById('map'),
        navLinks: Array.from(document.querySelectorAll('nav.nav-links a, nav.nav-links button')).map(e => e.innerText.trim()),
      }
    })()`)

    console.log('  Page Title:', startupCheck.title)
    console.log('  Brand:', startupCheck.brand.trim())
    console.log('  Header Controls:', {
      voice: startupCheck.voiceButton,
      emergency: startupCheck.emergencyButton,
      notifications: startupCheck.notificationsButton,
      signIn: startupCheck.signInButton,
    })
    console.log('  Navigation Links:', startupCheck.navLinks)

    qaReport.testResults['TEST 1: Startup'] =
      startupCheck.topbar &&
      startupCheck.voiceButton &&
      startupCheck.emergencyButton &&
      startupCheck.chatInput
    qaReport.details['Startup'] = startupCheck

    await cdp.saveScreenshot('screenshot_1_startup.png')
    qaReport.capturedScreenshots.push('screenshot_1_startup.png')

    // -------------------------------------------------------------------------
    // TEST 2: Demo Authentication Flow
    // -------------------------------------------------------------------------
    console.log('\n[TEST 2] Demo Authentication (usr_demo0001)...')
    await cdp.evaluate(`document.querySelector('.sign-in-button')?.click()`)
    await sleep(800)

    // Populate credentials
    await cdp.evaluate(`(() => {
      window.__setReactValue(document.getElementById('signin-user-id'), 'usr_demo0001');
      window.__setReactValue(document.getElementById('signin-name'), '[DEMO] Traveller');
      window.__setReactValue(document.getElementById('signin-email'), 'demo.traveller@example.invalid');
    })()`)

    // Submit form
    await cdp.evaluate(`document.querySelector('.signin-form')?.requestSubmit()`)
    await sleep(2000)

    const authCheck = await cdp.evaluate(`(() => {
      const userBadge = document.querySelector('.signed-in-user')
      return {
        signedIn: !!userBadge,
        name: userBadge?.innerText || '',
        token: !!localStorage.getItem('yatra-auth-token'),
      }
    })()`)

    console.log('  Auth State:', authCheck)
    qaReport.testResults['TEST 2: Demo Authentication'] = authCheck.signedIn && authCheck.token
    qaReport.details['Auth'] = authCheck

    await cdp.saveScreenshot('screenshot_2_authenticated.png')
    qaReport.capturedScreenshots.push('screenshot_2_authenticated.png')

    // -------------------------------------------------------------------------
    // TEST 3: English Trip Planning
    // -------------------------------------------------------------------------
    console.log('\n[TEST 3] Natural Language Trip Planning Flow (Mumbai -> Lucknow)...')
    const initialBubbles = await cdp.evaluate('document.querySelectorAll(".chat-bubble").length')
    const promptText = 'Plan a trip from Mumbai to Lucknow for 2 adults from 16 to 19 November 2026 under ₹45000.'
    await cdp.evaluate(`(() => {
      const input = document.getElementById('chat-input')
      if (input) {
        window.__setReactValue(input, ${JSON.stringify(promptText)});
      }
    })()`)

    await sleep(400)
    await cdp.evaluate(`document.querySelector('.chat-composer')?.requestSubmit()`)
    console.log('  Dispatched chat plan prompt. Waiting for agent workflow...')

    let agentFinished = false
    let planDetails = null
    for (let i = 0; i < 35; i++) {
      await sleep(2000)
      const res = await cdp.evaluate(`(() => {
        const bubbles = Array.from(document.querySelectorAll('.chat-bubble')).map(b => b.innerText)
        const planCard = document.querySelector('.structured-trip-plan-card')
        const planTitle = planCard?.querySelector('.plan-hero-title')?.innerText || ''
        const authTotal = planCard?.querySelector('.cost-item.authoritative .cost-val')?.innerText || ''
        const days = document.querySelectorAll('.plan-day-section').length
        const working = !!document.querySelector('.agent-working')
        const bookBtn = !!document.querySelector('.book-trip-cta-btn')
        return {
          bubbleCount: bubbles.length,
          working,
          hasPlan: !!planCard,
          planTitle,
          authTotal,
          days,
          bookBtn,
        }
      })()`)

      if (!res.working && (res.bubbleCount > initialBubbles || res.bookBtn || res.days > 0)) {
        agentFinished = true
        planDetails = res
        console.log('  Agent Completed Plan:', res)
        break
      }
    }

    qaReport.testResults['TEST 3: English Trip Planning'] = agentFinished && (planDetails?.hasPlan || planDetails?.bubbleCount >= 2)
    qaReport.details['Plan'] = planDetails

    await cdp.saveScreenshot('screenshot_3_trip_planning.png')
    qaReport.capturedScreenshots.push('screenshot_3_trip_planning.png')

    // -------------------------------------------------------------------------
    // TEST 4: Preferences Modal Interaction & Persistence
    // -------------------------------------------------------------------------
    console.log('\n[TEST 4] Preferences Modal Interaction...')
    await cdp.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('nav.nav-links button')).find(b => b.innerText.includes('Preferences'))
      if (btn) btn.click()
    })()`)
    await sleep(1000)

    const prefState = await cdp.evaluate(`(() => {
      const card = document.querySelector('.preferences-panel-card')
      const closeBtn = document.querySelector('.preferences-close-btn')
      const directToggle = document.querySelector('.preferences-body input[type="checkbox"]')
      return {
        cardVisible: !!card,
        hasCloseBtn: !!closeBtn,
        hasDirectToggle: !!directToggle,
      }
    })()`)
    console.log('  Preferences Opened:', prefState)

    // Close preferences modal cleanly
    await cdp.evaluate(`(() => {
      const closeBtn = document.querySelector('.preferences-close-btn')
      if (closeBtn) closeBtn.click()
    })()`)
    await sleep(800)

    const prefClosed = await cdp.evaluate(`!document.querySelector('.preferences-modal-backdrop')`)
    console.log('  Preferences Closed Cleanly:', prefClosed)
    qaReport.testResults['TEST 4: Preferences Modal'] = prefState.cardVisible && prefClosed

    // -------------------------------------------------------------------------
    // TEST 5: Multilingual Interface Switching (Hindi & Tamil)
    // -------------------------------------------------------------------------
    console.log('\n[TEST 5] Multilingual Support (Hindi & Tamil Switching)...')
    // Switch to Hindi
    await cdp.evaluate(`(() => {
      const sel = document.querySelector('.language-select')
      if (sel) {
        for (let i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value === 'hi') { sel.selectedIndex = i; break; }
        }
        sel.value = 'hi'
        sel.dispatchEvent(new Event('change', { bubbles: true }))
      }
    })()`)
    await sleep(1500)

    const hindiCheck = await cdp.evaluate(`(() => {
      return {
        docLang: document.documentElement.lang,
        heroTitle: document.querySelector('.hero-copy h1')?.innerText || '',
      }
    })()`)
    console.log('  Switched to Hindi (hi):', hindiCheck)

    // Switch to Tamil
    await cdp.evaluate(`(() => {
      const sel = document.querySelector('.language-select')
      if (sel) {
        for (let i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value === 'ta') { sel.selectedIndex = i; break; }
        }
        sel.value = 'ta'
        sel.dispatchEvent(new Event('change', { bubbles: true }))
      }
    })()`)
    await sleep(1500)

    const tamilCheck = await cdp.evaluate(`(() => {
      return {
        docLang: document.documentElement.lang,
        heroTitle: document.querySelector('.hero-copy h1')?.innerText || '',
      }
    })()`)
    console.log('  Switched to Tamil (ta):', tamilCheck)

    // Switch back to English
    await cdp.evaluate(`(() => {
      const sel = document.querySelector('.language-select')
      if (sel) {
        for (let i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value === 'en-IN') { sel.selectedIndex = i; break; }
        }
        sel.value = 'en-IN'
        sel.dispatchEvent(new Event('change', { bubbles: true }))
      }
    })()`)
    await sleep(800)

    qaReport.testResults['TEST 5: Multilingual Switching'] =
      hindiCheck.docLang === 'hi' && tamilCheck.docLang === 'ta'

    // -------------------------------------------------------------------------
    // TEST 6: Voice Assistant Modal & Material Action Safety Guard
    // -------------------------------------------------------------------------
    console.log('\n[TEST 6] Voice Assistant & Material Confirmation Safety...')
    await cdp.evaluate(`document.querySelector('.voice-topbar-button')?.click()`)
    await sleep(1000)

    const voiceModalOpened = await cdp.evaluate(`!!document.querySelector('.voice-modal')`)
    console.log('  Voice Modal Opened:', voiceModalOpened)

    // Submit simulated voice input: "Book this trip."
    await cdp.evaluate(`(() => {
      const input = document.getElementById('voice-manual-input')
      if (input) window.__setReactValue(input, 'Book this trip.')
    })()`)

    await cdp.evaluate(`document.querySelector('.text-fallback-send')?.click()`)
    await sleep(2000)

    const voiceSafetyCheck = await cdp.evaluate(`(() => {
      const confirmBox = document.querySelector('.material-confirmation-box')
      return {
        hasBox: !!confirmBox,
        prompt: confirmBox?.querySelector('.confirmation-prompt')?.innerText || '',
        hasConfirmBtn: !!confirmBox?.querySelector('.confirm-action-btn'),
        hasRejectBtn: !!confirmBox?.querySelector('.reject-action-btn'),
      }
    })()`)

    console.log('  Voice Explicit Confirmation Intercepted:', voiceSafetyCheck)

    // Reject and close modal cleanly
    await cdp.evaluate(`(() => {
      document.querySelector('.reject-action-btn')?.click()
      document.querySelector('.voice-modal .modal-close')?.click()
    })()`)
    await sleep(800)

    qaReport.testResults['TEST 6: Voice Safety Guard'] =
      voiceModalOpened && voiceSafetyCheck.hasBox && voiceSafetyCheck.hasConfirmBtn

    await cdp.saveScreenshot('screenshot_4_voice_safety.png')
    qaReport.capturedScreenshots.push('screenshot_4_voice_safety.png')

    // -------------------------------------------------------------------------
    // TEST 7: Notification Center & Preferences Tab
    // -------------------------------------------------------------------------
    console.log('\n[TEST 7] Notification Center & Preferences...')
    await cdp.evaluate(`document.querySelector('.notifications-button')?.click()`)
    await sleep(1000)

    const notifModalOpened = await cdp.evaluate(`!!document.querySelector('.notification-center-modal')`)
    console.log('  Notification Center Opened:', notifModalOpened)

    // Click Preferences tab
    await cdp.evaluate(`(() => {
      const prefTab = Array.from(document.querySelectorAll('.notif-tab-btn')).find(b => b.innerText.includes('Preferences'))
      if (prefTab) prefTab.click()
    })()`)
    await sleep(800)

    const prefsTabActive = await cdp.evaluate(`!!document.querySelector('.prefs-form')`)
    console.log('  Notification Preferences Form Rendered:', prefsTabActive)

    // Close Notification Center
    await cdp.evaluate(`document.querySelector('.notification-center-modal .modal-close')?.click()`)
    await sleep(800)

    qaReport.testResults['TEST 7: Notification Center'] = notifModalOpened && prefsTabActive

    // -------------------------------------------------------------------------
    // TEST 8: Emergency Assistance & SOS Explicit Confirmation
    // -------------------------------------------------------------------------
    console.log('\n[TEST 8] Emergency Assistance & SOS Confirmation Safety...')
    await cdp.evaluate(`document.querySelector('.emergency-topbar-button')?.click()`)
    await sleep(1200)

    const emergencyModal = await cdp.evaluate(`(() => {
      const modal = document.querySelector('.emergency-modal')
      const disclaimer = document.querySelector('.emergency-banner-disclaimer')?.innerText || ''
      const numbers = Array.from(document.querySelectorAll('.emergency-number-card .dial-digit')).map(d => d.innerText)
      const hasSosBtn = !!document.querySelector('.sos-activate-btn')
      return {
        isOpen: !!modal,
        disclaimer112: disclaimer.includes('112'),
        numbersCount: numbers.length,
        hasSosBtn,
      }
    })()`)
    console.log('  Emergency Modal Rendered:', emergencyModal)

    // Trigger SOS confirmation dialog
    await cdp.evaluate(`document.querySelector('.sos-activate-btn')?.click()`)
    await sleep(800)

    const sosConfirmDialog = await cdp.evaluate(`(() => {
      const innerCard = document.querySelector('.inner-confirm-card')
      const dangerBtn = innerCard?.querySelector('.sos-danger-btn')
      const cancelBtn = Array.from(document.querySelectorAll('.inner-confirm-actions button')).find(b => b.innerText.includes('Cancel'))
      return {
        hasDialog: !!innerCard,
        hasDangerBtn: !!dangerBtn,
        hasCancelBtn: !!cancelBtn,
      }
    })()`)
    console.log('  SOS Explicit Confirmation Dialog Activated:', sosConfirmDialog)

    // Cancel SOS confirmation and close emergency modal
    await cdp.evaluate(`(() => {
      const cancelBtn = Array.from(document.querySelectorAll('.inner-confirm-actions button')).find(b => b.innerText.includes('Cancel'))
      if (cancelBtn) cancelBtn.click()
      document.querySelector('.emergency-modal .modal-close')?.click()
    })()`)
    await sleep(800)

    qaReport.testResults['TEST 8: Emergency & SOS Safety'] =
      emergencyModal.isOpen && emergencyModal.disclaimer112 && sosConfirmDialog.hasDialog

    await cdp.saveScreenshot('screenshot_5_emergency_sos.png')
    qaReport.capturedScreenshots.push('screenshot_5_emergency_sos.png')

    // -------------------------------------------------------------------------
    // TEST 9: Booking Review Simulation & Authoritative Totals
    // -------------------------------------------------------------------------
    console.log('\n[TEST 9] Simulated Booking Review Flow...')
    let bookCtaAvailable = await cdp.evaluate(`!!document.querySelector('.book-trip-cta-btn')`)
    console.log('  Initial Book Trip CTA Available:', bookCtaAvailable)

    if (!bookCtaAvailable) {
      const hasGenBtn = await cdp.evaluate(`!!document.querySelector('.generate-verified-btn')`)
      if (hasGenBtn) {
        console.log('  Triggering Generate Verified Itinerary button...')
        await cdp.evaluate(`document.querySelector('.generate-verified-btn')?.click()`)
        await sleep(3500)
        bookCtaAvailable = await cdp.evaluate(`!!document.querySelector('.book-trip-cta-btn')`)
        console.log('  Book Trip CTA Available after generation:', bookCtaAvailable)
      }
    }

    let bookingResult = null
    if (bookCtaAvailable) {
      await cdp.evaluate(`document.querySelector('.book-trip-cta-btn')?.click()`)

      // Wait up to 5 seconds for booking review to load and confirm button to be rendered
      for (let w = 0; w < 10; w++) {
        await sleep(500)
        const hasBtn = await cdp.evaluate(`!!document.querySelector('.booking-review-modal .confirm-btn')`)
        if (hasBtn) break
      }

      bookingResult = await cdp.evaluate(`(() => {
        const modal = document.querySelector('.booking-review-modal')
        const subtotal = modal?.querySelector('.review-cost-box .grand-total')?.innerText || ''
        const hasConfirmBtn = !!modal?.querySelector('.confirm-btn')
        return {
          isOpen: !!modal,
          authoritativeTotal: subtotal,
          hasConfirmBtn,
        }
      })()`)
      console.log('  Booking Review Modal Opened:', bookingResult)

      if (bookingResult.isOpen && bookingResult.hasConfirmBtn) {
        console.log('  Confirming simulated reservation...')
        await cdp.evaluate(`document.querySelector('.booking-review-modal .confirm-btn')?.click()`)
        await sleep(2500)

        const confirmedState = await cdp.evaluate(`(() => {
          const refBadge = document.querySelector('.booking-reference-badge strong')?.innerText || ''
          return {
            reference: refBadge,
            hasRef: refBadge.startsWith('YTR-DEMO-'),
          }
        })()`)
        console.log('  Confirmed Demo Booking Reference:', confirmedState)
        bookingResult.confirmed = confirmedState

        // Close modal
        await cdp.evaluate(`document.querySelector('.booking-review-modal .modal-close')?.click()`)
        await sleep(800)
      }
    }

    qaReport.testResults['TEST 9: Booking Simulation'] =
      bookCtaAvailable && (bookingResult?.confirmed?.hasRef || bookingResult?.isOpen)
    qaReport.details['Booking'] = bookingResult

    // -------------------------------------------------------------------------
    // TEST 10: My Trips Navigation & History Inspection
    // -------------------------------------------------------------------------
    console.log('\n[TEST 10] My Trips Page & Trip Pack...')
    const myTripsState = await cdp.evaluate(`(() => {
      const section = document.getElementById('my-trips')
      const cards = document.querySelectorAll('.saved-trip-card').length
      return {
        sectionExists: !!section,
        tripCardsCount: cards,
      }
    })()`)
    console.log('  My Trips Section Status:', myTripsState)

    qaReport.testResults['TEST 10: My Trips'] = myTripsState.sectionExists

    // -------------------------------------------------------------------------
    // TEST 11: Console & Network Inspection
    // -------------------------------------------------------------------------
    console.log('\n[TEST 11] Console & Network Inspection...')
    qaReport.consoleErrors = cdp.consoleLogs.filter((l) => l.type === 'error' || l.exception)
    // Filter external 3rd-party tile server errors (MapTiler cloud key)
    qaReport.networkErrors = cdp.networkErrors.filter((e) => !e.url.includes('maptiler.com'))

    console.log('  Total Application Console Errors:', qaReport.consoleErrors.length)
    qaReport.consoleErrors.forEach((e) => console.log('    [Console Error]', e.text))

    console.log('  Total Internal API Errors (>= 400):', qaReport.networkErrors.length)
    qaReport.networkErrors.forEach((e) => console.log('    [Network Error]', e.status, e.url))

    const isClean = qaReport.consoleErrors.length === 0 && qaReport.networkErrors.length === 0
    qaReport.testResults['TEST 11: Error Free Execution'] = isClean

    // -------------------------------------------------------------------------
    // Final Summary Output
    // -------------------------------------------------------------------------
    console.log('\n======================================================')
    console.log('       BROWSER QA TEST EXECUTION REPORT')
    console.log('======================================================')
    let allPassed = true
    for (const [testName, result] of Object.entries(qaReport.testResults)) {
      const statusStr = result ? 'PASS' : 'FAIL'
      console.log(`  ${testName.padEnd(40)}: [${statusStr}]`)
      if (!result) allPassed = false
    }
    console.log('------------------------------------------------------')
    console.log(`OVERALL RESULT: ${allPassed ? 'ALL TESTS PASSED (100%)' : 'SOME TESTS FAILED'}`)
    console.log('======================================================\n')

    fs.writeFileSync('qa_browser_report.json', JSON.stringify(qaReport, null, 2))
  } finally {
    try {
      chromeProcess.kill()
    } catch {
      // ignore
    }
  }
}

runQA().catch((err) => {
  console.error('QA Runner Exception:', err)
  process.exit(1)
})
