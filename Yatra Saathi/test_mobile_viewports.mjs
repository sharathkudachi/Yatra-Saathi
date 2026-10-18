import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'

const CDP_HTTP = 'http://127.0.0.1:9222'
const TARGET_URL = 'http://localhost:5173'

const VIEWPORTS = [
  { name: 'Desktop Full HD', width: 1920, height: 1080 },
  { name: 'Laptop Standard', width: 1366, height: 768 },
  { name: 'Tablet Landscape', width: 1024, height: 768 },
  { name: 'Mobile Modern (iPhone 14/15)', width: 390, height: 844, isMobile: true },
  { name: 'Mobile Compact (Android)', width: 360, height: 800, isMobile: true },
]

const ROUTES = [
  { path: '/', name: 'Homepage' },
  { path: '/privacy', name: 'Privacy Policy' },
  { path: '/terms', name: 'Terms of Service' },
  { path: '/custom-404-test-page', name: 'Custom 404 Route' },
]

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function startChrome() {
  const profileDir = path.join(process.env.TEMP || 'C:\\Temp', `chrome_viewport_qa_${Date.now()}`)
  console.log('Launching headless Chrome for Viewport QA on port 9222...')
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
      if (res.ok) return chrome
    } catch {}
  }
  throw new Error('Chrome failed to start.')
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
        const msg = JSON.parse(event.data)
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id)
          this.pending.delete(msg.id)
          if (msg.error) reject(new Error(msg.error.message))
          else resolve(msg.result)
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

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    return res.result ? res.result.value : undefined
  }
}

async function main() {
  const chrome = await startChrome()
  const results = {}

  try {
    const newTab = await (await fetch(`${CDP_HTTP}/json/new?${encodeURIComponent(TARGET_URL)}`, { method: 'PUT' })).json()
    const cdp = new CDPClient(newTab.webSocketDebuggerUrl)
    await cdp.connect()

    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await sleep(2500)

    console.log('\n--- TESTING ALL 5 MANDATORY VIEWPORTS ACROSS ROUTES ---')

    for (const vp of VIEWPORTS) {
      console.log(`\nTesting Viewport: ${vp.name} (${vp.width}x${vp.height})...`)
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: vp.width,
        height: vp.height,
        deviceScaleFactor: 1,
        mobile: !!vp.isMobile,
      })
      await sleep(800)

      const vpResults = {}

      for (const route of ROUTES) {
        // Navigate
        await cdp.eval(`(() => {
          if (window.location.pathname !== '${route.path}') {
            window.history.pushState({}, '', '${route.path}');
            window.dispatchEvent(new PopStateEvent('popstate'));
          }
        })()`)
        await sleep(800)

        // Check horizontal overflow
        const overflowCheck = await cdp.eval(`(() => {
          const docWidth = document.documentElement.scrollWidth;
          const winWidth = window.innerWidth;
          const bodyWidth = document.body.scrollWidth;
          const hasHScroll = docWidth > winWidth + 1 || bodyWidth > winWidth + 1;
          const title = document.title;
          const metaDesc = document.querySelector('meta[name="description"]')?.getAttribute('content') || '';
          return {
            docWidth,
            winWidth,
            bodyWidth,
            hasHScroll,
            title,
            metaDescLen: metaDesc.length,
          };
        })()`)

        const routePass = !overflowCheck.hasHScroll && overflowCheck.title.length > 0 && overflowCheck.metaDescLen > 0
        vpResults[route.name] = {
          pass: routePass,
          details: overflowCheck,
        }
        console.log(`  Route [${route.name}]: ${routePass ? 'PASS (No H-Scroll)' : 'FAIL'} [doc: ${overflowCheck.docWidth}px, win: ${overflowCheck.winWidth}px, title: "${overflowCheck.title.slice(0, 35)}..."]`)
      }

      // Check Mobile Menu on Mobile Viewports on Homepage
      if (vp.isMobile) {
        await cdp.eval(`(() => {
          window.history.pushState({}, '', '/');
          window.dispatchEvent(new PopStateEvent('popstate'));
        })()`)
        await sleep(500)

        const isMenuBtnVisible = await cdp.eval(`(() => {
          const btn = document.querySelector('.mobile-menu');
          return !!btn && window.getComputedStyle(btn).display !== 'none';
        })()`);

        // Click open
        await cdp.eval(`document.querySelector('.mobile-menu')?.click()`);
        await sleep(400);
        const isNavOpenVisible = await cdp.eval(`!!document.querySelector('.nav-links.nav-open')`);

        // Click close
        await cdp.eval(`document.querySelector('.mobile-menu')?.click()`);
        await sleep(400);
        const navClosed = await cdp.eval(`!document.querySelector('.nav-links.nav-open')`);

        const mobileMenuCheck = { isMenuBtnVisible, isNavOpenVisible, navClosed };
        vpResults['Mobile Menu Toggle'] = isMenuBtnVisible && isNavOpenVisible && navClosed;
        console.log(`  Mobile Menu Toggle: ${vpResults['Mobile Menu Toggle'] ? 'PASS' : 'FAIL'}`, mobileMenuCheck);
      }

      results[vp.name] = vpResults
    }

    console.log('\n========================================================')
    console.log('VIEWPORT RESPONSIVENESS AUDIT COMPLETE:')
    console.log(JSON.stringify(results, null, 2))
    console.log('========================================================')

    fs.writeFileSync('qa_viewport_report.json', JSON.stringify(results, null, 2))
  } finally {
    try {
      chrome.kill('SIGKILL')
    } catch {}
  }
}

main().catch(err => {
  console.error('Viewport QA Error:', err)
  process.exit(1)
})
