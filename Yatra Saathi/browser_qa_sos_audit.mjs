// browser_qa_sos_audit.mjs
// Full live Chrome CDP automated browser verification for SOS & Emergency Assistance workflow.

import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'

const CDP_HTTP = 'http://127.0.0.1:9222'
const TARGET_URL = 'http://localhost:5173'

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function startChrome() {
  const profileDir = path.join(process.env.TEMP || 'C:\\Temp', `chrome_sos_qa_${Date.now()}`)
  console.log('Launching headless Chrome for SOS browser verification on port 9222...')
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    '--remote-debugging-port=9222',
    `--user-data-dir=${profileDir}`,
    '--window-size=1440,900',
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
  throw new Error('Chrome failed to start on port 9222.')
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl
    this.ws = null
    this.nextId = 1
    this.pending = new Map()
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl)
      this.ws.onopen = () => resolve()
      this.ws.onerror = (err) => reject(err)
      this.ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.id && this.pending.has(data.id)) {
          const { resolve, reject } = this.pending.get(data.id)
          this.pending.delete(data.id)
          if (data.error) reject(data.error)
          else resolve(data.result)
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
    return res.result?.value
  }

  async screenshot(filePath) {
    const res = await this.send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(filePath, Buffer.from(res.data, 'base64'))
    console.log(`Saved screenshot: ${filePath}`)
  }

  close() {
    if (this.ws) this.ws.close()
  }
}

async function runSosBrowserVerification() {
  const chrome = await startChrome()
  const report = {
    timestamp: new Date().toISOString(),
    tests: [],
    passed: true,
  }

  function addStep(name, success, details) {
    console.log(`[${success ? 'PASS' : 'FAIL'}] ${name}: ${details || ''}`)
    report.tests.push({ name, success, details })
    if (!success) report.passed = false
  }

  try {
    // Connect to first page
    const listRes = await fetch(`${CDP_HTTP}/json/list`)
    const targets = await listRes.json()
    const pageTarget = targets.find((t) => t.type === 'page') || targets[0]

    const cdp = new CDPClient(pageTarget.webSocketDebuggerUrl)
    await cdp.connect()
    await cdp.send('Page.enable')
    await cdp.send('DOM.enable')
    await cdp.send('Runtime.enable')

    console.log(`Navigating to ${TARGET_URL}...`)
    await cdp.send('Page.navigate', { url: TARGET_URL })
    await sleep(3500)

    // Helper: set react input value using _valueTracker
    await cdp.evaluate(`
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

    // Sign in using demo credentials (usr_demo0001 / DemoPass1234!)
    console.log('Authenticating as demo user (usr_demo0001)...')
    await cdp.evaluate(`
      (() => {
        const btn = document.querySelector('.sign-in-button');
        if (btn) btn.click();
      })()
    `)
    await sleep(1000)

    await cdp.evaluate(`
      (() => {
        const idInput = document.getElementById('signin-identifier');
        const pwInput = document.getElementById('signin-password');
        if (idInput) window.__setReactValue(idInput, 'usr_demo0001');
        if (pwInput) window.__setReactValue(pwInput, 'DemoPass1234!');
      })()
    `)
    await sleep(600)

    await cdp.evaluate(`
      (() => {
        const submitBtn = document.querySelector('.auth-form button[type="submit"]') ||
          Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.includes('Sign in') && b.classList.contains('modal-primary'));
        if (submitBtn) submitBtn.click();
      })()
    `)
    await sleep(2500)

    const signedIn = await cdp.evaluate(`
      !!document.querySelector('.signed-in-user')
    `)
    addStep('User Authentication', signedIn, 'Signed in as verified user usr_demo0001')

    // STEP 1: Click the SOS button in the topbar
    console.log('Opening Emergency Assistance modal...')
    await cdp.evaluate(`
      (() => {
        const btn = document.querySelector('.emergency-topbar-button');
        if (btn) btn.click();
      })()
    `)
    await sleep(1500)

    // Verify modal is open
    const modalTitle = await cdp.evaluate(`
      document.querySelector('#emergency-modal-title')?.textContent?.trim()
    `)
    const modalVisible = modalTitle === 'Emergency Assistance'
    addStep('Open Emergency Assistance Modal', modalVisible, `Modal title: "${modalTitle}"`)

    await cdp.screenshot('qa_sos_1_modal_open.png')

    // STEP 2: Verify official emergency numbers are visibly rendered
    const officialNumbers = await cdp.evaluate(`
      (() => {
        const cards = Array.from(document.querySelectorAll('.emergency-number-card'));
        return cards.map(c => ({
          number: c.querySelector('.dial-digit')?.textContent?.trim(),
          name: c.querySelector('.number-details strong')?.textContent?.trim(),
          href: c.getAttribute('href')
        }));
      })()
    `)

    console.log('Detected Official Emergency Numbers:', officialNumbers)
    const has112 = officialNumbers.some((n) => n.number === '112' && n.href === 'tel:112')
    const has100 = officialNumbers.some((n) => n.number === '100' && n.href === 'tel:100')
    const has102 = officialNumbers.some((n) => n.number === '102' && n.href === 'tel:102')
    const has101 = officialNumbers.some((n) => n.number === '101' && n.href === 'tel:101')
    const numbersValid = has112 && has100 && has102 && has101 && officialNumbers.length >= 6
    addStep(
      'Verified Official Emergency Numbers (India)',
      numbersValid,
      `Found ${officialNumbers.length} authoritative numbers including 112, 100, 102, 101 with tel: dialers.`,
    )

    // STEP 3: Click Add Contact button and submit functional form
    console.log('Opening Add Contact form...')
    await cdp.evaluate(`
      (() => {
        const btn = document.querySelector('.add-contact-btn');
        if (btn) btn.click();
      })()
    `)
    await sleep(800)

    const formVisible = await cdp.evaluate(`
      !!document.querySelector('.add-contact-form')
    `)
    addStep('Add Contact Form Opens', formVisible, 'Form displayed')

    // Fill form using __setReactValue
    await cdp.evaluate(`
      (() => {
        const nameInput = document.querySelector('#contact-name-input');
        const relInput = document.querySelector('#contact-rel-input');
        const phoneInput = document.querySelector('#contact-phone-input');
        if (nameInput) window.__setReactValue(nameInput, 'Ramesh Verma');
        if (relInput) window.__setReactValue(relInput, 'Brother');
        const randDigits = Math.floor(10000 + Math.random() * 90000);
        if (phoneInput) window.__setReactValue(phoneInput, '+91 98765 ' + randDigits);
      })()
    `)
    await sleep(500)

    await cdp.evaluate(`
      (() => {
        const submitBtn = document.querySelector('.save-contact-btn');
        if (submitBtn) submitBtn.click();
      })()
    `)
    await sleep(2000)

    // Verify contact is in the list
    const contactNames = await cdp.evaluate(`
      (() => {
        return Array.from(document.querySelectorAll('.trusted-contact-card .contact-name-row strong'))
          .map(el => el.textContent.trim());
      })()
    `)
    const contactAdded = contactNames.includes('Ramesh Verma')
    addStep('Add Trusted Contact End-to-End', contactAdded, `Contacts in list: ${contactNames.join(', ')}`)

    await cdp.screenshot('qa_sos_2_contact_added.png')

    // STEP 4: Edit Contact
    console.log('Editing trusted contact...')
    await cdp.evaluate(`
      (() => {
        const editBtn = document.querySelector('.contact-icon-btn[title="Edit contact"]');
        if (editBtn) editBtn.click();
      })()
    `)
    await sleep(800)

    await cdp.evaluate(`
      (() => {
        const nameInput = document.querySelector('#edit-name-input');
        if (nameInput) window.__setReactValue(nameInput, 'Ramesh K. Verma');
      })()
    `)
    await sleep(500)

    await cdp.evaluate(`
      (() => {
        const saveBtn = document.querySelector('.edit-contact-form .save-contact-btn');
        if (saveBtn) saveBtn.click();
      })()
    `)
    await sleep(2000)

    const updatedContactNames = await cdp.evaluate(`
      (() => {
        return Array.from(document.querySelectorAll('.trusted-contact-card .contact-name-row strong'))
          .map(el => el.textContent.trim());
      })()
    `)
    const contactUpdated = updatedContactNames.includes('Ramesh K. Verma')
    addStep('Edit Trusted Contact', contactUpdated, `Updated list: ${updatedContactNames.join(', ')}`)

    // STEP 5: Geolocation manual search, selection, and unverified fallback
    console.log('Testing manual location search workflow (Hoskote, Bangalore)...')
    
    // 5a: Search for Hoskote, Bangalore
    await cdp.evaluate(`
      (() => {
        const locInput = document.querySelector('#manual-location-input');
        if (locInput) window.__setReactValue(locInput, 'Hoskote, Bangalore');
      })()
    `)
    await sleep(400)

    // Click Find Location button
    await cdp.evaluate(`
      (() => {
        const findBtn = document.querySelector('#find-location-btn');
        if (findBtn) findBtn.click();
      })()
    `)
    await sleep(2500)

    // Check search results
    const searchResultsInfo = await cdp.evaluate(`
      (() => {
        const results = document.querySelectorAll('.search-result-item');
        const header = document.querySelector('.search-results-header')?.textContent?.trim();
        const attribution = document.querySelector('.osm-attribution-note')?.textContent?.trim();
        return {
          count: results.length,
          header,
          attribution,
          firstPlace: results[0]?.querySelector('.result-place-info strong')?.textContent?.trim(),
          firstCoords: results[0]?.querySelector('.result-coords')?.textContent?.trim()
        };
      })()
    `)
    console.log('Search Results Info:', searchResultsInfo)
    const searchSucceeded = searchResultsInfo.count > 0 && !!searchResultsInfo.firstPlace
    addStep(
      'Geocoding Location Search (Find Location)',
      searchSucceeded,
      `Found ${searchResultsInfo.count} results for Hoskote. Attribution: ${searchResultsInfo.attribution}`
    )

    // 5b: Confirm selection with "Use This Location"
    console.log('Confirming place with "Use This Location"...')
    await cdp.evaluate(`
      (() => {
        const useBtn = document.querySelector('.use-location-btn');
        if (useBtn) useBtn.click();
      })()
    `)
    await sleep(800)

    const confirmedGeocoded = await cdp.evaluate(`
      (() => {
        const card = document.querySelector('.confirmed-location-card.confirmed-geocoded');
        if (!card) return null;
        return {
          pill: card.querySelector('.pill-geocoded')?.textContent?.trim(),
          label: card.querySelector('.confirmed-loc-body strong')?.textContent?.trim(),
          coordsInfo: card.querySelector('.confirmed-loc-body small')?.textContent?.trim()
        };
      })()
    `)
    console.log('Confirmed Geocoded Card:', confirmedGeocoded)
    const geocodedConfirmed =
      !!confirmedGeocoded &&
      confirmedGeocoded.pill.includes('Geocoding Confirmed') &&
      confirmedGeocoded.coordsInfo.includes('Resolved via Map Search')
    addStep(
      'Use This Location Action & Geocoded Confirmation Card',
      geocodedConfirmed,
      `Label: ${confirmedGeocoded?.label}, Coords: ${confirmedGeocoded?.coordsInfo}`
    )

    await cdp.screenshot('qa_sos_location_geocoded.png')

    // 5c: Test Change / Remove
    console.log('Testing Change/Remove confirmed location...')
    await cdp.evaluate(`
      (() => {
        const clearBtn = document.querySelector('.location-clear-btn');
        if (clearBtn) clearBtn.click();
      })()
    `)
    await sleep(500)
    const cleared = await cdp.evaluate(`!document.querySelector('.confirmed-location-card')`)
    addStep('Change / Remove Location Action', cleared, 'Location reset to unselected')

    // 5d: Test "Attach as Unverified Note"
    console.log('Testing Attach as Unverified Note...')
    await cdp.evaluate(`
      (() => {
        const locInput = document.querySelector('#manual-location-input');
        if (locInput) window.__setReactValue(locInput, 'Near Hoskote Toll Gate 2');
      })()
    `)
    await sleep(300)

    await cdp.evaluate(`
      (() => {
        const attachBtn = document.querySelector('#attach-manual-landmark-btn');
        if (attachBtn) attachBtn.click();
      })()
    `)
    await sleep(600)

    const confirmedManual = await cdp.evaluate(`
      (() => {
        const card = document.querySelector('.confirmed-location-card.confirmed-manual_unverified');
        if (!card) return null;
        return {
          pill: card.querySelector('.pill-manual')?.textContent?.trim(),
          label: card.querySelector('.confirmed-loc-body strong')?.textContent?.trim(),
          note: card.querySelector('.confirmed-loc-body small')?.textContent?.trim()
        };
      })()
    `)
    console.log('Confirmed Manual Note Card:', confirmedManual)
    const manualConfirmed =
      !!confirmedManual &&
      confirmedManual.pill.includes('Unverified Landmark Text') &&
      confirmedManual.note.includes('No GPS coordinates attached')
    addStep(
      'Attach as Unverified Note Fallback',
      manualConfirmed,
      `Label: ${confirmedManual?.label}, Note: ${confirmedManual?.note}`
    )

    await cdp.screenshot('qa_sos_location_manual_note.png')

    // 5e: Re-select geocoded Hoskote location for end-to-end SOS activation
    await cdp.evaluate(`
      (() => {
        const locInput = document.querySelector('#manual-location-input');
        if (locInput) window.__setReactValue(locInput, 'Hoskote, Bangalore');
      })()
    `)
    await sleep(300)
    await cdp.evaluate(`
      (() => {
        const findBtn = document.querySelector('#find-location-btn');
        if (findBtn) findBtn.click();
      })()
    `)
    await sleep(2000)
    await cdp.evaluate(`
      (() => {
        const useBtn = document.querySelector('.use-location-btn');
        if (useBtn) useBtn.click();
      })()
    `)
    await sleep(600)

    // STEP 6: SOS Confirmation & Activation
    console.log('Opening SOS confirmation dialog...')
    await cdp.evaluate(`
      (() => {
        const btn = document.querySelector('.sos-activate-btn');
        if (btn) btn.click();
      })()
    `)
    await sleep(800)

    const confirmOpened = await cdp.evaluate(`
      !!document.querySelector('.inner-confirm-card h3') &&
      document.querySelector('.inner-confirm-card h3').textContent.includes('Confirm SOS')
    `)
    addStep('SOS Confirmation Dialog Prompt', confirmOpened, 'Requires explicit confirmation before activating')

    // Test Cancel on confirmation dialog
    await cdp.evaluate(`
      (() => {
        const cancelBtn = document.querySelector('.inner-confirm-actions .modal-secondary');
        if (cancelBtn) cancelBtn.click();
      })()
    `)
    await sleep(600)

    const cancelDismissed = await cdp.evaluate(`
      !document.querySelector('.inner-confirm-card')
    `)
    addStep('SOS Cancel Behavior', cancelDismissed, 'Cancelled without activating SOS')

    // Now re-open confirmation and verify geocoded location preview
    await cdp.evaluate(`
      (() => {
        const btn = document.querySelector('.sos-activate-btn');
        if (btn) btn.click();
      })()
    `)
    await sleep(800)

    const confirmPreview = await cdp.evaluate(`
      (() => {
        const preview = document.querySelector('.sos-confirm-loc-preview.geocoded-confirmed');
        return preview ? preview.textContent.trim() : null;
      })()
    `)
    const previewValid = !!confirmPreview && confirmPreview.includes('Geocoded Location Attached') && confirmPreview.includes('Hoskote')
    addStep('SOS Confirmation Dialog Location Preview', previewValid, confirmPreview || 'Preview missing')

    console.log('Activating SOS with real backend...')
    await cdp.evaluate(`
      (() => {
        const actBtn = document.querySelector('.sos-danger-btn');
        if (actBtn) actBtn.click();
      })()
    `)
    await sleep(2500)

    // Verify active card rendered
    const sosActiveData = await cdp.evaluate(`
      (() => {
        const card = document.querySelector('.sos-active-card');
        if (!card) return null;
        return {
          title: card.querySelector('.sos-active-header strong')?.textContent?.trim(),
          ref: card.querySelector('.sos-active-header small')?.textContent?.trim(),
          notice: card.querySelector('.sos-active-notice')?.textContent?.trim(),
          instructionsCount: card.querySelectorAll('.sos-instructions-list li').length,
          has112Button: !!card.querySelector('.sos-dial-112-btn'),
          hasCopyButton: !!card.querySelector('.sos-copy-btn'),
          honestDisclosure: card.querySelector('.sos-honest-disclosure')?.textContent?.trim()
        };
      })()
    `)

    console.log('SOS Active Result:', sosActiveData)
    const sosSuccessful =
      !!sosActiveData &&
      sosActiveData.title === 'SOS Assistance Logged' &&
      sosActiveData.ref.includes('sos_') &&
      sosActiveData.instructionsCount >= 4 &&
      sosActiveData.has112Button &&
      sosActiveData.hasCopyButton

    addStep(
      'SOS Activation with Backend Audit & Crisis Instructions',
      sosSuccessful,
      JSON.stringify(sosActiveData),
    )

    await cdp.screenshot('qa_sos_3_sos_activated.png')

    // STEP 7: Mobile viewport responsiveness
    console.log('Testing mobile viewport responsiveness (390x844)...')
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true,
    })
    await sleep(1000)

    const mobileResponsive = await cdp.evaluate(`
      (() => {
        const modal = document.querySelector('.emergency-modal');
        if (!modal) return false;
        const rect = modal.getBoundingClientRect();
        return rect.width <= 390 && rect.height <= 844;
      })()
    `)
    addStep('Mobile Viewport & Responsiveness', mobileResponsive, 'Modal fits iPhone viewport cleanly')

    await cdp.screenshot('qa_sos_4_mobile_viewport.png')

    // Reset viewport
    await cdp.send('Emulation.clearDeviceMetricsOverride')
    await sleep(500)

    // STEP 8: Close modal using close button
    console.log('Testing close button to dismiss modal...')
    await cdp.evaluate(`
      (() => {
        const closeBtn = document.querySelector('.emergency-modal .modal-close');
        if (closeBtn) closeBtn.click();
      })()
    `)
    await sleep(800)

    const modalClosed = await cdp.evaluate(`
      !document.querySelector('.emergency-modal')
    `)
    addStep('Modal Close Button Dismissal', modalClosed, 'Modal dismissed with close button')

    cdp.close()
  } catch (err) {
    console.error('Browser QA Error:', err)
    addStep('Browser Test Execution', false, err.message)
  } finally {
    try {
      chrome.kill()
    } catch {
      // ignore
    }
  }

  fs.writeFileSync('qa_sos_browser_report.json', JSON.stringify(report, null, 2))
  console.log('Browser QA Report saved to qa_sos_browser_report.json')
  console.log(`Summary: ${report.tests.filter((t) => t.success).length}/${report.tests.length} passed.`)
  if (!report.passed) {
    process.exit(1)
  }
}

runSosBrowserVerification()
