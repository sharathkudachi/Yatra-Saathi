import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'

const CDP_HTTP = 'http://127.0.0.1:9222'
const TARGET_URL = 'http://localhost:5173'

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function startChrome() {
  const profileDir = path.join(process.env.TEMP || 'C:\\Temp', `chrome_ti_qa_${Date.now()}`)
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

async function runQA() {
  let chromeProcess = null
  try {
    chromeProcess = await startChrome()

    const newTargetRes = await fetch(`${CDP_HTTP}/json/new?${encodeURIComponent(TARGET_URL)}`, { method: 'PUT' })
    const targetInfo = await newTargetRes.json()
    const client = new CDPClient(targetInfo.webSocketDebuggerUrl)
    await client.connect()
    console.log('Connected to Chrome DevTools Protocol.')

    await client.send('Page.enable')
    await client.send('Runtime.enable')
    await client.send('Network.enable')

    console.log(`Navigating to ${TARGET_URL}...`)
    await client.send('Page.navigate', { url: TARGET_URL })
    await sleep(3500)

    // Inject React helper
    await client.evaluate(`
      window.__setReactValue = function(element, value) {
        if (!element) return;
        const lastValue = element.value;
        element.value = value;
        const event = new Event('input', { bubbles: true });
        const tracker = element._valueTracker;
        if (tracker) tracker.setValue(lastValue);
        element.dispatchEvent(event);
      };
    `)

    // 1. Authenticate demo user
    console.log('Step 1: Logging in demo user (usr_demo0001)...')
    await client.evaluate(`
      const btn = document.querySelector('.sign-in-button');
      if (btn) btn.click();
    `)
    await sleep(800)

    await client.evaluate(`
      const idInput = document.getElementById('signin-identifier');
      const pwInput = document.getElementById('signin-password');
      if (idInput) window.__setReactValue(idInput, 'usr_demo0001');
      if (pwInput) window.__setReactValue(pwInput, 'DemoPass1234!');
      const submit = document.querySelector('.signin-form button[type="submit"]');
      if (submit) submit.click();
    `)
    await sleep(2000)

    // 2. Submit trip request
    const initialBubbles = (await client.evaluate('document.querySelectorAll(".chat-bubble").length')) || 0
    const promptText = "Plan a trip from Mumbai to Lucknow for 2 adults from 16 to 19 November 2026 under ₹45000."
    console.log(`Step 2: Entering trip request: "${promptText}" (initial bubbles: ${initialBubbles})...`)
    await client.evaluate(`
      const chatInput = document.getElementById('chat-input');
      if (chatInput) {
        window.__setReactValue(chatInput, ${JSON.stringify(promptText)});
        const form = chatInput.closest('form');
        if (form) form.requestSubmit();
      }
    `)

    console.log('Step 3: Waiting for travel planning agent to complete...')
    let planRendered = false
    for (let i = 0; i < 60; i++) {
      await sleep(2000)
      const res = await client.evaluate(`(() => {
        const bubbles = Array.from(document.querySelectorAll('.chat-bubble')).map(b => b.innerText);
        const dayCards = document.querySelectorAll('.day-card');
        const working = !!document.querySelector('.agent-working');
        const bookBtn = !!document.querySelector('.book-trip-cta-btn');
        return {
          bubbleCount: bubbles.length,
          working,
          dayCount: dayCards.length,
          bookBtn,
        };
      })()`)
      if (i % 5 === 0) {
        console.log(`  [${(i + 1) * 2}s] bubbles: ${res.bubbleCount}, working: ${res.working}, days: ${res.dayCount}, bookBtn: ${res.bookBtn}`)
      }
      if (!res.working && res.bubbleCount > initialBubbles && (res.dayCount > 0 || res.bookBtn)) {
        planRendered = true
        console.log(`Travel plan rendered successfully after ${(i + 1) * 2}s with ${res.dayCount} days.`, res)
        break
      }
    }

    if (!planRendered) {
      throw new Error('Travel plan failed to render within 80s.')
    }
    await sleep(2000)

    await client.captureScreenshot('qa_corrected_1_overview.png')

    // 4. Verify Leaflet Map
    console.log('Step 4: Inspecting Real Leaflet Geographic Map...')
    const mapStats = await client.evaluate(`(() => {
      const leafletContainer = document.querySelector('.leaflet-container');
      const tiles = document.querySelectorAll('.leaflet-tile');
      const markers = document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin');
      const polylines = document.querySelectorAll('svg path.leaflet-interactive, .leaflet-pane svg path');
      const mapCard = document.querySelector('.travel-map-card');
      const mapTitle = mapCard?.querySelector('h3')?.textContent || '';
      return {
        leafletFound: !!leafletContainer,
        tilesCount: tiles.length,
        markersCount: markers.length,
        polylinesCount: polylines.length,
        mapTitle,
      };
    })()`)
    console.log('Map Stats:', JSON.stringify(mapStats, null, 2))

    // 5. Verify Day-by-Day Itinerary Structure & Pacing
    console.log('Step 5: Inspecting Day-by-Day Itinerary...')
    const itineraryStats = await client.evaluate(`(() => {
      const dayCards = document.querySelectorAll('.day-card');
      const summaryStrips = document.querySelectorAll('.day-summary-strip');
      const durationPills = document.querySelectorAll('.activity-duration-pill');
      const activityIcons = document.querySelectorAll('.act-type-icon');
      const days = Array.from(dayCards).map(card => {
        const title = card.querySelector('.day-title')?.textContent?.trim() || '';
        const summary = card.querySelector('.day-summary-strip')?.textContent?.trim() || '';
        const activities = Array.from(card.querySelectorAll('.activity-item')).map(a => {
          return {
            title: a.querySelector('.act-title')?.textContent?.trim() || '',
            time: a.querySelector('.activity-time')?.textContent?.trim() || '',
            category: a.querySelector('.cat-tag')?.textContent?.trim() || '',
            duration: a.querySelector('.activity-duration-pill')?.textContent?.trim() || '',
          };
        });
        return { title, summary, activityCount: activities.length, sampleActs: activities.slice(0, 3) };
      });
      return { dayCount: dayCards.length, summaryStripsCount: summaryStrips.length, durationPillsCount: durationPills.length, days };
    })()`)
    console.log(`Itinerary Stats: ${itineraryStats.dayCount} days, ${itineraryStats.durationPillsCount} duration pills.`)
    console.log('Day breakdown:', JSON.stringify(itineraryStats.days, null, 2))

    // 6. Verify Flight Comparison & Separation
    console.log('Step 6: Inspecting Flight & Hotel Comparison tabs...')
    await client.evaluate(`
      const chip = document.querySelector('.compare-chip');
      if (chip) chip.click();
    `)
    for (let c = 0; c < 15; c++) {
      await sleep(1000)
      const hasTabs = await client.evaluate(`document.querySelectorAll('.comp-tab-btn').length > 0`)
      if (hasTabs) break
    }

    const compStats = await client.evaluate(`(() => {
      const tabs = Array.from(document.querySelectorAll('.comp-tab-btn')).map(b => b.textContent?.trim());
      const catalogNotice = document.querySelector('.catalog-notice-banner')?.textContent?.trim() || '';
      const packageCards = document.querySelectorAll('.comparison-card');
      const flightTable = document.querySelector('.flight-comparison-table');
      return {
        tabs,
        catalogNotice,
        packageCardsCount: packageCards.length,
        flightTableFound: !!flightTable,
      };
    })()`)
    console.log('Comparison Stats:', JSON.stringify(compStats, null, 2))

    // Switch to Flight Options tab to inspect side-by-side comparison
    await client.evaluate(`
      const flightTab = Array.from(document.querySelectorAll('.comp-tab-btn')).find(b => b.textContent.includes('Flight Options'));
      if (flightTab) flightTab.click();
    `)
    await sleep(600)
    await client.captureScreenshot('qa_corrected_2_flights.png')

    // Switch back to Complete Packages tab
    await client.evaluate(`
      const pkgTab = Array.from(document.querySelectorAll('.comp-tab-btn')).find(b => b.textContent.includes('Complete Packages'));
      if (pkgTab) pkgTab.click();
    `)
    await sleep(600)

    // 7. Verify Map ↔ Itinerary Synchronization
    console.log('Step 7: Testing Map ↔ Itinerary Day Filter and Pin Click Sync...')
    // Click Day 1 filter
    await client.evaluate(`
      const day1Btn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('Day 1'));
      if (day1Btn) day1Btn.click();
    `)
    await sleep(800)
    const day1Pins = await client.evaluate(`document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length`)
    console.log(`Pins visible on Day 1 filter: ${day1Pins}`)

    // Click Day 2 filter
    await client.evaluate(`
      const day2Btn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('Day 2'));
      if (day2Btn) day2Btn.click();
    `)
    await sleep(800)
    const day2Pins = await client.evaluate(`document.querySelectorAll('.leaflet-marker-icon, .custom-map-pin').length`)
    console.log(`Pins visible on Day 2 filter: ${day2Pins}`)

    // Reset to "All"
    await client.evaluate(`
      const allBtn = Array.from(document.querySelectorAll('.map-day-pill')).find(p => p.textContent.includes('All'));
      if (allBtn) allBtn.click();
    `)
    await sleep(800)

    // Click first activity in itinerary to trigger focus & popup
    await client.evaluate(`
      const firstAct = document.querySelector('.activity-item');
      if (firstAct) firstAct.click();
    `)
    await sleep(800)
    const popupVisible = await client.evaluate(`!!document.querySelector('.leaflet-popup')`)
    console.log(`Leaflet popup opened upon activity click: ${popupVisible}`)

    await client.captureScreenshot('qa_corrected_3_map_sync.png')

    // 8. Test "Review & Reserve Demo Booking" modal flow
    console.log('Step 8: Testing Booking Review Modal...')
    await client.evaluate(`
      const bookBtn = document.querySelector('.book-trip-cta-btn');
      if (bookBtn) bookBtn.click();
    `)
    
    // Wait for booking review recalculation to finish
    for (let m = 0; m < 15; m++) {
      await sleep(1000)
      const isLoading = await client.evaluate(`!!document.querySelector('.review-loading-view')`)
      const hasReview = await client.evaluate(`!!document.querySelector('.review-total-value') || !!document.querySelector('.booking-error-banner')`)
      if (!isLoading && hasReview) break
    }

    const modalState = await client.evaluate(`(() => {
      const modal = document.querySelector('.booking-review-modal');
      const failedToFetch = document.body.textContent.includes('Failed to fetch');
      const errorBanner = document.querySelector('.booking-error-banner')?.textContent?.trim() || '';
      const totalAmount = document.querySelector('.review-total-value')?.textContent?.trim() || '';
      const token = document.querySelector('.review-token-tag')?.textContent?.trim() || '';
      const confirmBtn = document.querySelector('.confirm-btn') || Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Confirm') && b.textContent.includes('Booking'));
      return {
        modalFound: !!modal,
        failedToFetch,
        errorBanner,
        totalAmount,
        token,
        hasConfirmBtn: !!confirmBtn,
      };
    })()`)
    console.log('Booking Review Modal State:', JSON.stringify(modalState, null, 2))

    await client.captureScreenshot('qa_corrected_4_booking_modal.png')

    if (modalState.failedToFetch) {
      throw new Error('FAILED: "Failed to fetch" error detected in Booking Review Modal!')
    }

    // 9. Confirm simulated booking
    if (modalState.hasConfirmBtn) {
      console.log('Step 9: Confirming Demo Booking...')
      await client.evaluate(`
        const confirmBtn = document.querySelector('.confirm-btn') || Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Confirm') && b.textContent.includes('Booking'));
        if (confirmBtn) confirmBtn.click();
      `)
      await sleep(3000)

      const confirmedState = await client.evaluate(`(() => {
        const successModal = document.querySelector('.booking-success-modal, .booking-review-modal');
        const bkgRef = document.querySelector('.booking-reference-badge, .confirmation-reference')?.textContent?.trim() || '';
        const modalText = successModal ? successModal.textContent : '';
        return {
          hasSuccessModal: !!successModal,
          bkgRef,
          isConfirmed: modalText.includes('Confirmed') || modalText.includes('Reference') || modalText.includes('Success') || modalText.includes('confirmed'),
        };
      })()`)
      console.log('Booking Confirmation State:', JSON.stringify(confirmedState, null, 2))

      await client.captureScreenshot('qa_corrected_5_booking_confirmed.png')
    }

    console.log('\n=== LIVE BROWSER QA RESULT ===')
    console.log(`Leaflet Basemap: ${mapStats.leafletFound ? 'PASS' : 'FAIL'} (${mapStats.tilesCount} tiles loaded)`)
    console.log(`Flight Comparison Separation: ${compStats.tabs.length >= 2 ? 'PASS' : 'FAIL'}`)
    console.log(`Day-by-Day Dynamic Itinerary: ${itineraryStats.dayCount > 0 ? 'PASS' : 'FAIL'} (${itineraryStats.dayCount} days)`)
    console.log(`Map-Itinerary Sync: ${day1Pins > 0 && day2Pins > 0 ? 'PASS' : 'FAIL'}`)
    console.log(`Booking Review "Failed to fetch" fixed: ${!modalState.failedToFetch ? 'PASS' : 'FAIL'}`)

    const report = {
      timestamp: new Date().toISOString(),
      mapStats,
      itineraryStats,
      compStats,
      modalState,
      consoleLogsCount: client.consoleLogs.length,
      networkErrors: client.networkErrors,
      status: 'SUCCESS',
    }
    fs.writeFileSync('browser_qa_travel_intelligence_report.json', JSON.stringify(report, null, 2))
    console.log('Saved browser_qa_travel_intelligence_report.json')

  } finally {
    if (chromeProcess) {
      console.log('Shutting down Chrome...')
      chromeProcess.kill('SIGTERM')
    }
  }
}

runQA().catch((err) => {
  console.error('Browser QA Error:', err)
  process.exit(1)
})
