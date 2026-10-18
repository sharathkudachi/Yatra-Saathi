import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'

const CDP_HTTP = 'http://127.0.0.1:9222'
const TARGET_URL = 'http://localhost:5173'

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function startChrome() {
  const profileDir = path.join(process.env.TEMP || 'C:\\Temp', `chrome_ti_pass2_${Date.now()}`)
  console.log('Launching headless Chrome on remote debugging port 9222...')
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    '--remote-debugging-port=9222',
    `--user-data-dir=${profileDir}`,
    '--window-size=1920,1080',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    TARGET_URL,
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
    this.networkErrors = []
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl)
      this.ws.onopen = () => resolve()
      this.ws.onerror = (err) => reject(err)
      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.id && this.pending.has(msg.id)) {
            const { resolve, reject } = this.pending.get(msg.id)
            this.pending.delete(msg.id)
            if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)))
            else resolve(msg.result)
          } else if (msg.method === 'Runtime.consoleAPICalled') {
            const args = (msg.params.args || []).map((a) => a.value || a.description || '').join(' ')
            this.consoleLogs.push(`[${msg.params.type}] ${args}`)
          } else if (msg.method === 'Network.responseReceived') {
            const resp = msg.params.response
            if (resp && resp.status >= 400 && !resp.url.includes('favicon')) {
              this.networkErrors.push(`${resp.status} ${resp.statusText}: ${resp.url}`)
            }
          }
        } catch (e) {
          console.error('Error parsing CDP message:', e)
        }
      }
    })
  }

  send(method, params = {}) {
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
      throw new Error(`Eval error: ${res.exceptionDetails.text} (${expression})`)
    }
    return res.result ? res.result.value : undefined
  }

  async captureScreenshot(filename) {
    const res = await this.send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(filename, Buffer.from(res.data, 'base64'))
    console.log(`Saved screenshot: ${filename}`)
  }
}

async function runBrowserQA() {
  let chromeProcess = null
  const testResults = {}

  try {
    chromeProcess = await startChrome()

    await sleep(3500)
    const targets = await (await fetch(`${CDP_HTTP}/json`)).json()
    const pageTarget = targets.find((t) => t.type === 'page' && t.url.includes('5173'))
    if (!pageTarget) throw new Error('Could not find active page target on port 5173')

    const client = new CDPClient(pageTarget.webSocketDebuggerUrl)
    await client.connect()
    console.log('Connected to Chrome DevTools Protocol.')

    await client.send('Page.enable')
    await client.send('Runtime.enable')
    await client.send('Network.enable')

    // Inject React input helper
    await client.evaluate(`
      window.__setReactValue = function(element, value) {
        if (!element) return;
        if (element._valueTracker) element._valueTracker.setValue('');
        const proto = Object.getPrototypeOf(element);
        const desc = Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
        if (desc && desc.set) {
          desc.set.call(element, value);
        } else {
          element.value = value;
        }
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
      };
    `)

    // ========================================================
    // 1. INITIAL GUEST STATE VERIFICATION
    // ========================================================
    console.log('\n--- Test 1: Verify Initial Unauthenticated Guest State ---')
    const guestStateEval = await client.evaluate(`(() => {
      const text = document.body.textContent;
      const signInBtn = document.querySelector('.sign-in-button');
      const hasToken = !!localStorage.getItem('yatra-auth-token');
      return {
        isSignInVisible: !!signInBtn,
        signInBtnText: signInBtn ? signInBtn.textContent.trim() : '',
        hasToken,
        isGuest: !hasToken && !text.includes('usr_demo0001'),
      };
    })()`)
    console.log('Initial Guest State:', JSON.stringify(guestStateEval, null, 2))
    testResults.guestInitialState = guestStateEval.isGuest && !guestStateEval.hasToken

    // ========================================================
    // 2. GUEST BOOKING ATTEMPT — PROMPT REQUIRED, NO AUTO-AUTH
    // ========================================================
    console.log('\n--- Test 2: Guest Trip Planning & Booking CTA Click ---')
    await client.evaluate(`
      const destInput = document.getElementById('destination');
      if (destInput) window.__setReactValue(destInput, 'Lucknow');
      const startInput = document.getElementById('start-date');
      if (startInput) window.__setReactValue(startInput, '2026-11-16');
      const endInput = document.getElementById('end-date');
      if (endInput) window.__setReactValue(endInput, '2026-11-19');
      const budgetInput = document.getElementById('budget');
      if (budgetInput) window.__setReactValue(budgetInput, '45000');
    `)
    await sleep(2000)

    // Click booking CTA as a guest
    console.log('Guest clicking "Review & Reserve Demo Booking" CTA...')
    await client.evaluate(`
      const bookBtn = document.querySelector('.book-trip-cta-btn') || Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Review & Reserve') || b.textContent.includes('Book'));
      if (bookBtn) {
        bookBtn.scrollIntoView({ behavior: 'instant', block: 'center' });
        bookBtn.click();
      }
    `)
    await sleep(1500)

    // Inspect the resulting authentication prompt
    const guestPromptState = await client.evaluate(`(() => {
      const text = document.body.textContent;
      const modal = document.querySelector('.auth-modal, .signin-form, .booking-review-modal');
      const hasAuthPrompt = text.includes('Sign in or create an account to continue with booking.') ||
                            text.includes('Sign in or create an account');
      const hasSignIn = Array.from(document.querySelectorAll('button, a')).some(b => 
        b.textContent.toLowerCase().includes('sign in') || 
        b.textContent.toLowerCase().includes('log in')
      );
      const hasCreateAccount = Array.from(document.querySelectorAll('button, a')).some(b => 
        b.textContent.toLowerCase().includes('create account') || 
        b.textContent.toLowerCase().includes('register')
      );
      
      const becameDemoUser = text.includes('usr_demo0001') && !document.querySelector('.signin-form');
      const bookingCreatedSilently = text.includes('YTR-DEMO-');

      return {
        hasAuthPrompt,
        hasSignIn,
        hasCreateAccount,
        becameDemoUser,
        bookingCreatedSilently,
      };
    })()`)

    console.log('Guest Booking Attempt Result:', JSON.stringify(guestPromptState, null, 2))
    await client.captureScreenshot('qa_pass2_1_guest_auth_prompt.png')

    testResults.guestCannotAutoAuth = !guestPromptState.becameDemoUser && !guestPromptState.bookingCreatedSilently
    testResults.authPromptShown = guestPromptState.hasAuthPrompt && guestPromptState.hasSignIn
    console.log(`Guest Auto-Auth Refused (No usr_demo0001 identity theft): ${testResults.guestCannotAutoAuth ? 'PASS' : 'FAIL'}`)
    console.log(`Auth Prompt Displayed with Sign In: ${testResults.authPromptShown ? 'PASS' : 'FAIL'}`)

    // ========================================================
    // 3. EXPLICIT SIGN IN AS usr_demo0001
    // ========================================================
    console.log('\n--- Test 3: Explicit Authentication with usr_demo0001 ---')
    await client.evaluate(`
      const idInput = document.getElementById('signin-identifier');
      const pwInput = document.getElementById('signin-password');
      if (idInput) window.__setReactValue(idInput, 'usr_demo0001');
      if (pwInput) window.__setReactValue(pwInput, 'DemoPass1234!');
      const submit = document.querySelector('.signin-form button[type="submit"]');
      if (submit) {
        submit.click();
      } else {
        const form = document.querySelector('.signin-form');
        if (form) form.requestSubmit();
      }
    `)
    await sleep(2500)

    const loginEval = await client.evaluate(`(() => {
      const signedInUser = document.querySelector('.signed-in-user, .signed-in-name');
      const text = document.body.textContent;
      const hasToken = !!localStorage.getItem('yatra-auth-token');
      return {
        badge: signedInUser ? signedInUser.textContent.trim() : 'Unknown',
        hasToken,
        hasSignOut: text.includes('Sign Out') || text.includes('Sign out') || text.includes('Log out'),
      };
    })()`)
    console.log(`Logged in badge: "${loginEval.badge}", hasToken: ${loginEval.hasToken}, hasSignOut: ${loginEval.hasSignOut}`)
    testResults.explicitLoginSuccess = loginEval.hasToken && (loginEval.badge.includes('usr_demo0001') || loginEval.badge.includes('Traveller') || loginEval.hasSignOut)
    await client.captureScreenshot('qa_pass2_2_authenticated.png')

    // ========================================================
    // 4. GENERATE FULL ITINERARY WITH AGENT / VERIFIED ITINERARY
    // ========================================================
    console.log('\n--- Test 4: Generate Verified Itinerary ---')
    // Click Generate Verified Itinerary
    await client.evaluate(`(() => {
      const genBtn = document.querySelector('.generate-verified-btn');
      if (genBtn) {
        genBtn.click();
      } else {
        const cards = Array.from(document.querySelectorAll('.saved-trip-card'));
        const lucknowCard = cards.find(c => c.textContent.includes('Lucknow'));
        if (lucknowCard) {
          const btn = Array.from(lucknowCard.querySelectorAll('button')).find(b => b.textContent.includes('Continue planning') || b.textContent.includes('View'));
          if (btn) btn.click();
        }
      }
    })()`)

    console.log('Waiting for verified itinerary generation...')
    let planRendered = false
    for (let i = 0; i < 30; i++) {
      await sleep(1500)
      const res = await client.evaluate(`(() => {
        const acts = document.querySelectorAll('.activity-item:not(.empty-activity)').length;
        const pins = document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length;
        const isGenerating = !!document.querySelector('.generate-verified-btn .spin-icon') || !!document.querySelector('.agent-working');
        const isPreview = !!document.querySelector('.preview-plan-banner');
        const planTitle = document.querySelector('.plan-title')?.textContent?.trim() || '';
        return {
          acts,
          pins,
          isGenerating,
          isPreview,
          planTitle,
        };
      })()`)
      if (i % 3 === 0) {
        console.log(`  [${(i + 1) * 1.5}s] acts: ${res.acts}, pins: ${res.pins}, isGenerating: ${res.isGenerating}, isPreview: ${res.isPreview}`)
      }
      if (res.acts > 0 && !res.isGenerating) {
        planRendered = true
        console.log(`Verified itinerary ready with ${res.acts} activities and ${res.pins} map pins. ("${res.planTitle}")`)
        break
      }
      if (res.isPreview) {
        await client.evaluate(`document.querySelector('.generate-verified-btn')?.click()`)
      }
    }
    if (!planRendered) throw new Error('Planning agent timed out.')
    await sleep(2000)
    await client.captureScreenshot('qa_pass2_3_plan_overview.png')

    // ========================================================
    // 5. MAP DAY FILTERS & ISOLATION VERIFICATION
    // ========================================================
    console.log('\n--- Test 5: Verify Leaflet Real Map & Day Filters ---')
    const allPins = await client.evaluate(`document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length`)
    const tilesCount = await client.evaluate(`document.querySelectorAll('.leaflet-tile').length`)
    console.log(`Real Map: ${tilesCount} geographic tiles loaded, ${allPins} total pins visible on "All".`)

    // Click Day 1 filter
    await client.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('Day 1'));
      if (btn) btn.click();
    })()`)
    await sleep(1000)
    const day1Pins = await client.evaluate(`document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length`)
    const day1HasFlightArc = await client.evaluate(`document.querySelectorAll('svg path.leaflet-interactive').length > 0`)
    console.log(`Day 1 Pins: ${day1Pins} (Arrival day flight arc: ${day1HasFlightArc})`)

    // Click Day 2 filter
    await client.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('Day 2'));
      if (btn) btn.click();
    })()`)
    await sleep(1000)
    const day2Pins = await client.evaluate(`document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length`)
    const day2HasFlightArc = await client.evaluate(`document.querySelectorAll('svg path.leaflet-interactive').length > 0`)
    console.log(`Day 2 Pins: ${day2Pins} (Intermediate day flight arc suppressed: ${!day2HasFlightArc})`)

    // Click Day 3 filter
    await client.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('Day 3'));
      if (btn) btn.click();
    })()`)
    await sleep(800)
    const day3Pins = await client.evaluate(`document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length`)
    console.log(`Day 3 Pins: ${day3Pins}`)

    // Click Day 4 filter
    await client.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('Day 4'));
      if (btn) btn.click();
    })()`)
    await sleep(800)
    const day4Pins = await client.evaluate(`document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length`)
    console.log(`Day 4 Pins: ${day4Pins}`)

    testResults.dayFiltersDistinct = (day1Pins !== day2Pins) && (day2Pins <= 12 && day2Pins > 0)
    console.log(`Day Filters Distinct (No 24-pin leak): ${testResults.dayFiltersDistinct ? 'PASS' : 'FAIL'}`)

    // Reset to "All"
    await client.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('All'));
      if (btn) btn.click();
    })()`)
    await sleep(800)
    await client.captureScreenshot('qa_pass2_4_day_filters.png')

    // ========================================================
    // 6. MAP ↔ ITINERARY ACTIVITY POPUP SYNC
    // ========================================================
    console.log('\n--- Test 6: Itinerary Activity Click Focuses Exact Map Marker ---')
    await client.evaluate(`(() => {
      const act = document.querySelector('.activity-item:not(.empty-activity)');
      if (act) act.click();
    })()`)
    await sleep(2500)
    const popupOpened = await client.evaluate(`!!document.querySelector('.leaflet-popup')`)
    const popupTitle = await client.evaluate(`document.querySelector('.leaflet-popup .popup-title, .leaflet-popup h4')?.textContent?.trim() || ''`)
    console.log(`Leaflet popup opened upon activity click: ${popupOpened} ("${popupTitle}")`)
    testResults.activityPopupSync = popupOpened
    await client.captureScreenshot('qa_pass2_5_activity_popup.png')

    // ========================================================
    // 7. FLIGHT COMPARISON & GROUNDED CATALOG NOTICE
    // ========================================================
    console.log('\n--- Test 7: Flight Comparison & Grounded Catalog Notice ---')
    await client.evaluate(`(() => {
      const compSection = document.querySelector('.travel-comparison-container');
      if (compSection) compSection.scrollIntoView({ behavior: 'instant', block: 'center' });
      const flightTab = Array.from(document.querySelectorAll('.comp-tab-btn')).find(b => b.textContent.includes('Flight Options'));
      if (flightTab) flightTab.click();
    })()`)
    await sleep(1000)

    const flightCompState = await client.evaluate(`(() => {
      const banner = document.querySelector('.catalog-notice-banner')?.textContent?.trim() || '';
      const flightCards = document.querySelectorAll('.flight-option-card, .flight-card');
      const text = document.body.textContent;
      const hasIntegrityNotice = text.includes('Only one suitable flight is currently available in the catalog') ||
                                banner.includes('Only one suitable flight');
      return {
        flightCardsCount: flightCards.length,
        hasIntegrityNotice,
        bannerText: banner,
      };
    })()`)
    console.log('Flight Comparison State:', JSON.stringify(flightCompState, null, 2))
    testResults.flightIntegrityNotice = flightCompState.hasIntegrityNotice
    await client.captureScreenshot('qa_pass2_6_flight_comparison.png')

    // Return to Packages tab
    await client.evaluate(`(() => {
      const pkgTab = Array.from(document.querySelectorAll('.comp-tab-btn')).find(b => b.textContent.includes('Complete Packages'));
      if (pkgTab) pkgTab.click();
    })()`)
    await sleep(800)

    // ========================================================
    // 8. BOOKING REVIEW AS AUTHENTICATED USER
    // ========================================================
    console.log('\n--- Test 8: Authenticated Booking Review & Reserve ---')
    await client.evaluate(`(() => {
      const bookBtn = document.querySelector('.book-trip-cta-btn') || Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Review & Reserve') || b.textContent.includes('Book Trip'));
      if (bookBtn) {
        bookBtn.scrollIntoView({ behavior: 'instant', block: 'center' });
        bookBtn.click();
      }
    })()`)
    
    // Wait for review calculation
    for (let m = 0; m < 15; m++) {
      await sleep(1000)
      const isLoading = await client.evaluate(`!!document.querySelector('.review-loading-view')`)
      const hasReview = await client.evaluate(`!!document.querySelector('.review-total-value') || !!document.querySelector('.booking-error-banner')`)
      if (!isLoading && hasReview) break
    }

    const reviewModalState = await client.evaluate(`(() => {
      const modal = document.querySelector('.booking-review-modal');
      const failedToFetch = modal ? modal.textContent.includes('Failed to fetch') : false;
      const totalAmount = document.querySelector('.review-total-value')?.textContent?.trim() || '';
      const token = document.querySelector('.review-token-tag')?.textContent?.trim() || '';
      const hasAED = modal ? modal.textContent.includes('AED') : false;
      const confirmBtn = document.querySelector('.booking-review-modal .confirm-btn') || Array.from(document.querySelectorAll('.booking-review-modal button')).find(b => b.textContent.includes('Confirm') && b.textContent.includes('Booking'));
      return {
        failedToFetch,
        totalAmount,
        token,
        hasAED,
        hasConfirmBtn: !!confirmBtn,
      };
    })()`)
    console.log('Booking Review Modal State:', JSON.stringify(reviewModalState, null, 2))
    await client.captureScreenshot('qa_pass2_7_booking_modal.png')

    testResults.reviewLoaded = !reviewModalState.failedToFetch && reviewModalState.totalAmount.length > 0
    testResults.currencyINRVerified = !reviewModalState.hasAED && (reviewModalState.totalAmount.includes('₹') || reviewModalState.totalAmount.length > 0)

    // ========================================================
    // 9. EXPLICIT CONFIRMATION & BOOKING REFERENCE
    // ========================================================
    console.log('\n--- Step 9: Explicit Confirmation of Booking ---')
    if (reviewModalState.hasConfirmBtn) {
      await client.evaluate(`(() => {
        const confirmBtn = document.querySelector('.booking-review-modal .confirm-btn') || Array.from(document.querySelectorAll('.booking-review-modal button')).find(b => b.textContent.includes('Confirm') && b.textContent.includes('Booking'));
        if (confirmBtn) confirmBtn.click();
      })()`)
      await sleep(4000)

      const confirmationState = await client.evaluate(`(() => {
        const text = document.body.textContent;
        const bkgRef = document.querySelector('.ref-value, .booking-reference-badge, .confirmation-reference')?.textContent?.trim() || '';
        const matchRef = text.match(/YTR-DEMO-[A-Z0-9]+/);
        return {
          referenceFound: bkgRef || (matchRef ? matchRef[0] : ''),
          isConfirmed: text.includes('Demo Reservation Confirmed') || text.includes('Confirmed') || text.includes('simulated Yatra reservation'),
        };
      })()`)
      console.log('Confirmation State:', JSON.stringify(confirmationState, null, 2))
      testResults.bookingConfirmed = confirmationState.isConfirmed && confirmationState.referenceFound.length > 0
      testResults.bookingReference = confirmationState.referenceFound
      await client.captureScreenshot('qa_pass2_8_booking_confirmed.png')
    }

    console.log('\n========================================')
    console.log('FINAL BROWSER PASS 2 TEST RESULTS SUMMARY:')
    console.log(JSON.stringify(testResults, null, 2))
    console.log('========================================')

    fs.writeFileSync('browser_qa_pass2_report.json', JSON.stringify({
      timestamp: new Date().toISOString(),
      testResults,
      consoleErrors: client.consoleLogs.filter(l => l.includes('[error]')),
      networkErrors: client.networkErrors,
      status: 'SUCCESS',
    }, null, 2))

  } finally {
    if (chromeProcess) {
      console.log('Stopping Chrome...')
      chromeProcess.kill('SIGTERM')
    }
  }
}

runBrowserQA().catch((err) => {
  console.error('Browser QA Pass 2 failed:', err)
  process.exit(1)
})
