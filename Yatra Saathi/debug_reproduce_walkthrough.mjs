import http from 'http'
import fs from 'fs'
import { spawn } from 'child_process'

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

async function getWsUrl(port = 9222) {
  return new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/json/version`, (res) => {
      let data = ''
      res.on('data', (c) => (data += c))
      res.on('end', () => {
        try {
          const json = JSON.parse(data)
          resolve(json.webSocketDebuggerUrl)
        } catch (e) {
          reject(e)
        }
      })
    }).on('error', reject)
  })
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl
    this.id = 1
    this.callbacks = new Map()
    this.events = []
    this.networkLogs = []
    this.consoleLogs = []
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl)
      this.ws.onopen = () => resolve()
      this.ws.onerror = (err) => reject(err)
      this.ws.onmessage = (event) => {
        const parsed = JSON.parse(event.data)
        if (parsed.id && this.callbacks.has(parsed.id)) {
          const cb = this.callbacks.get(parsed.id)
          this.callbacks.delete(parsed.id)
          if (parsed.error) cb.reject(parsed.error)
          else cb.resolve(parsed.result)
        } else if (parsed.method) {
          this.events.push(parsed)
          if (parsed.method === 'Network.requestWillBeSent') {
            this.networkLogs.push({ type: 'REQ', url: parsed.params.request.url, method: parsed.params.request.method })
          } else if (parsed.method === 'Network.responseReceived') {
            this.networkLogs.push({ type: 'RES', url: parsed.params.response.url, status: parsed.params.response.status })
          } else if (parsed.method === 'Runtime.consoleAPICalled') {
            this.consoleLogs.push({ type: parsed.params.type, args: parsed.params.args })
          }
        }
      }
    })
  }

  send(method, params = {}) {
    const id = this.id++
    return new Promise((resolve, reject) => {
      this.callbacks.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }

  async eval(expr) {
    const res = await this.send('Runtime.evaluate', {
      expression: `(() => { ${expr} })()`,
      returnByValue: true,
      awaitPromise: true,
    })
    return res.result?.value
  }

  async screenshot(filename) {
    const res = await this.send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(filename, Buffer.from(res.data, 'base64'))
    console.log(`Saved screenshot: ${filename}`)
  }

  close() {
    this.ws.close()
  }
}

async function main() {
  const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
  const chrome = spawn(
    CHROME_PATH,
    [
      '--remote-debugging-port=9222',
      '--headless=new',
      '--disable-gpu',
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--window-size=1440,900',
    ],
    { stdio: 'ignore' }
  )

  try {
    let pageTarget = null
    for (let i = 0; i < 20; i++) {
      try {
        const res = await fetch('http://127.0.0.1:9222/json/list')
        if (res.ok) {
          const targets = await res.json()
          pageTarget = targets.find((t) => t.type === 'page') || targets[0]
          if (pageTarget?.webSocketDebuggerUrl) break
        }
      } catch {}
      await sleep(500)
    }

    if (!pageTarget) throw new Error('Could not connect to Chrome page target on port 9222')
    const cdp = new CdpClient(pageTarget.webSocketDebuggerUrl)
    await cdp.connect()

    await cdp.send('Page.enable')
    await cdp.send('Network.enable')
    await cdp.send('Runtime.enable')

    console.log('Navigating to http://localhost:5173...')
    await cdp.send('Page.navigate', { url: 'http://localhost:5173' })
    await sleep(3500)

    // Helper: set react input value
    await cdp.eval(`
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

    // Sign in with demo user
    console.log('Signing in demo user...')
    await cdp.eval(`
      const btn = document.querySelector('.sign-in-button');
      if (btn) btn.click();
    `)
    await sleep(800)
    await cdp.eval(`
      const idInput = document.getElementById('signin-identifier');
      const pwInput = document.getElementById('signin-password');
      if (idInput) window.__setReactValue(idInput, 'usr_demo0001');
      if (pwInput) window.__setReactValue(pwInput, 'DemoPass1234!');
      const submit = document.querySelector('.signin-form button[type="submit"]');
      if (submit) submit.click();
    `)
    await sleep(2000)

    // Fill the chat input with the user request
    const prompt = 'Plan a trip from Mumbai to Lucknow for 2 adults from 16 to 19 November 2026 under ₹45000.'
    console.log(`Submitting trip prompt: "${prompt}"...`)
    await cdp.eval(`
      const chatInput = document.getElementById('chat-input');
      if (chatInput) {
        window.__setReactValue(chatInput, ${JSON.stringify(prompt)});
        const form = chatInput.closest('form');
        if (form) form.requestSubmit();
      }
    `)

    // Wait for the agent to finish planning
    console.log('Waiting for trip planning response...')
    let done = false
    for (let wait = 0; wait < 35; wait++) {
      await sleep(2000)
      const status = await cdp.eval(`
        const pill = document.querySelector('.online-pill')?.textContent || '';
        const submitBtn = document.querySelector('.chat-composer-footer button[type="submit"]')?.textContent || '';
        const isWorking = pill.includes('WORKING') || submitBtn.includes('Planning');
        const hasStructuredPlan = !!document.querySelector('.structured-trip-plan-card:not(.empty-plan)');
        const hasComparison = !!document.querySelector('.travel-comparison-container, .travel-comparison-card');
        const hotels = document.querySelectorAll('.hotel-card').length;
        return {
          onlinePill: pill,
          isWorking,
          hasStructuredPlan,
          hasComparison,
          hasHotels: hotels,
          structuredPlanTitle: document.querySelector('.plan-card-title')?.textContent || '',
        };
      `)
      console.log(`[Status ${wait * 2}s]:`, JSON.stringify(status))
      if (!status.isWorking && wait > 2 && (status.hasStructuredPlan || status.hasHotels > 0 || status.hasComparison)) {
        done = true
        break
      }
    }

    await sleep(2000)
    // Scroll down to the itinerary / map section
    await cdp.eval(`
      const target = document.querySelector('.yatra-travel-map-card, .structured-trip-plan-card');
      if (target) target.scrollIntoView({ behavior: 'instant', block: 'start' });
      else window.scrollTo(0, 800);
    `)
    await sleep(1000)
    await cdp.screenshot('walkthrough_1_planned.png')

    // Inspect map
    const mapInfo = await cdp.eval(`
      const mapEl = document.querySelector('.yatra-travel-map-card');
      const svg = mapEl?.querySelector('svg');
      const leaflet = mapEl?.querySelector('.leaflet-container');
      const maptiler = mapEl?.querySelector('.maplibregl-map, .mapboxgl-map');
      return {
        mapElExists: !!mapEl,
        isSvg: !!svg,
        isLeaflet: !!leaflet,
        isMapTiler: !!maptiler,
        filterChips: Array.from(document.querySelectorAll('.map-day-filter-bar button')).map(b => b.textContent.trim()),
      };
    `)
    console.log('Map Inspection:', JSON.stringify(mapInfo, null, 2))

    // Inspect flights in comparison
    const comparisonInfo = await cdp.eval(`
      const compCard = document.querySelector('.travel-comparison-card');
      const cards = Array.from(document.querySelectorAll('.comparison-option-card')).map(card => {
        return {
          title: card.querySelector('h4')?.textContent?.trim() || '',
          badges: Array.from(card.querySelectorAll('.option-badge')).map(b => b.textContent.trim()),
          cost: card.querySelector('.option-cost-total strong')?.textContent?.trim() || '',
          carrier: card.querySelector('.carrier-info strong')?.textContent?.trim() || '',
          flightTiming: card.querySelector('.flight-timing')?.textContent?.trim() || '',
          hotelName: card.querySelector('.hotel-preview strong')?.textContent?.trim() || '',
        };
      });
      return {
        compExists: !!compCard,
        cardCount: cards.length,
        cards,
      };
    `)
    console.log('Comparison Cards Inspection:', JSON.stringify(comparisonInfo, null, 2))

    // Inspect Itinerary
    const itineraryInfo = await cdp.eval(`
      const planCard = document.querySelector('.structured-trip-plan-card');
      const days = Array.from(document.querySelectorAll('.plan-day-accordion')).map(day => {
        return {
          dayHeader: day.querySelector('.day-header-title')?.textContent?.trim() || '',
          actCount: day.querySelectorAll('.activity-timeline-item').length,
          activities: Array.from(day.querySelectorAll('.activity-timeline-item')).map(a => {
            return {
              time: a.querySelector('.act-time')?.textContent?.trim() || '',
              title: a.querySelector('.act-details strong')?.textContent?.trim() || '',
              category: a.querySelector('.act-category')?.textContent?.trim() || '',
            };
          }),
        };
      });
      const executionTrace = Array.from(document.querySelectorAll('.tool-trace div, .plan-execution-trace div')).map(d => d.textContent.trim());
      return {
        planExists: !!planCard,
        dayCount: days.length,
        days,
        executionTraceCount: executionTrace.length,
      };
    `)
    console.log('Itinerary Inspection:', JSON.stringify(itineraryInfo, null, 2))

    // Test clicking "Review & Reserve Demo Booking" or "Book Trip"
    console.log('\nTesting "Book Trip" / "Review & Reserve Demo Booking"...')
    await cdp.eval(`
      const bookBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent && (b.textContent.includes('Book This Plan') || b.textContent.includes('Review Booking') || b.textContent.includes('Book Trip')));
      if (bookBtn) bookBtn.click();
    `)
    await sleep(2500)
    await cdp.screenshot('walkthrough_2_booking_clicked.png')

    const bookingModalInfo = await cdp.eval(`
      const modal = document.querySelector('.booking-review-modal');
      const errorMsg = document.querySelector('.booking-review-modal .modal-error, .booking-review-modal .error-banner, .booking-review-modal [role="alert"]')?.textContent || '';
      const bodyText = modal?.innerText || '';
      return {
        modalExists: !!modal,
        errorMsg,
        hasFailedToFetch: bodyText.includes('Failed to fetch'),
        bodyPreview: bodyText.slice(0, 400),
      };
    `)
    console.log('Booking Modal Inspection:', JSON.stringify(bookingModalInfo, null, 2))

    console.log('\nRecent Network Logs (last 15):')
    console.log(cdp.networkLogs.slice(-15))

    console.log('\nRecent Console Logs (errors):')
    console.log(cdp.consoleLogs.filter(c => c.type === 'error' || c.type === 'warning'))

    cdp.close()
  } finally {
    try {
      chrome.kill()
    } catch {}
  }
}

main().catch(console.error)
