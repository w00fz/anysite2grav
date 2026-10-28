#!/usr/bin/env node
// Screenshot source vs local pages side by side and read computed design tokens from the source.
//
// Usage:
//   node capture_pages.mjs --migration migration --source https://example.com --local http://127.0.0.1:8000 \
//        [--routes /,/about] [--limit 12] [--widths 1440,390] [--tokens-only] [--no-tokens]
//        [--only local|source] [--metrics] [--no-reveal]
//
// --only local     reshoot just the local site while iterating (source shots are reused)
// --metrics        per-section computed numbers (height, padding, background, heading size/weight/
//                  line-height) for source vs local → screens/<slug>/metrics-<width>.json + report table
// Source captures force scroll-reveal content visible (builders animate opacity/transform on scroll);
// --no-reveal disables that.
//
// Without --routes it picks one example route per layout cluster (content-index.json).
// Writes:
//   migration/screens/<slug>/{source,local}-<width>.png   full-page screenshots (+ -fold.png viewport)
//   migration/screens/report.html                          side-by-side review page
//   migration/design-tokens.json                           computed styles of the source (fonts,
//                                                          sizes, colors, radii, container width)
// Playwright is installed on first run into migration/.tools (no global install needed).
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const PLAYWRIGHT_VERSION = '1.64.1'
const argv = process.argv.slice(2)
const option = (name, fallback) => {
  const index = argv.indexOf(`--${name}`)
  return index === -1 ? fallback : argv[index + 1]
}
const flag = (name) => argv.includes(`--${name}`)

const migration = resolve(option('migration', 'migration'))
const source = option('source')
const local = option('local')
const widths = option('widths', '1440,390').split(',').map(Number)
const limit = Number(option('limit', '12'))
if (!source || (!local && !flag('tokens-only'))) {
  console.error('usage: capture_pages.mjs --migration migration --source <url> --local <url> [--routes /a,/b]')
  process.exit(2)
}

const tools = join(migration, '.tools')
if (!existsSync(join(tools, 'node_modules', 'playwright'))) {
  mkdirSync(tools, { recursive: true })
  execFileSync('npm', ['install', '--prefix', tools, '--no-audit', '--no-fund', `playwright@${PLAYWRIGHT_VERSION}`], { stdio: 'inherit' })
  execFileSync(join(tools, 'node_modules', '.bin', 'playwright'), ['install', 'chromium'], { stdio: 'inherit' })
}
const require = createRequire(join(tools, 'package.json'))
const { chromium } = require('playwright')

const pickRoutes = () => {
  const explicit = option('routes')
  if (explicit) return explicit.split(',')
  const index = JSON.parse(readFileSync(join(migration, 'content-index.json'), 'utf8'))
  return index.clusters.slice(0, limit).map((cluster) => cluster.example)
}

const slug = (route) => (route.replace(/^\/|\/$/g, '').replace(/[^a-z0-9]+/gi, '-') || 'home').slice(0, 60)

// Runs in the page: computed styles of representative elements.
const readTokens = () => {
  // First visible match: hidden modals often contain the first <h1> in the DOM.
  const visible = (selector) => [...document.querySelectorAll(selector)].find((element) => element.offsetParent !== null && element.getBoundingClientRect().height > 0)
  const style = (selector) => {
    const element = selector === 'body' ? document.body : visible(selector)
    if (!element) return null
    const computed = getComputedStyle(element)
    return {
      fontFamily: computed.fontFamily, fontSize: computed.fontSize, fontWeight: computed.fontWeight,
      lineHeight: computed.lineHeight, letterSpacing: computed.letterSpacing, color: computed.color,
      background: computed.backgroundColor, borderRadius: computed.borderRadius, padding: computed.padding,
      textTransform: computed.textTransform,
    }
  }
  const button = [...document.querySelectorAll('a, button')].find((element) => /btn|button|cta/i.test(element.className) && element.offsetParent)
  const header = visible('header, nav, [class*=nav]')
  const footer = visible('footer, [class*=footer]')
  const widest = [...document.querySelectorAll('main *, body > div *')].slice(0, 4000)
    .map((element) => parseFloat(getComputedStyle(element).maxWidth))
    .filter((value) => value >= 900 && value <= 1600)
  return {
    body: style('body'), h1: style('h1'), h2: style('h2'), h3: style('h3'), p: style('p'),
    button: button ? (() => { const c = getComputedStyle(button); return { color: c.color, background: c.backgroundColor, borderRadius: c.borderRadius, padding: c.padding, fontWeight: c.fontWeight, fontSize: c.fontSize } })() : null,
    header: header ? { background: getComputedStyle(header).backgroundColor, color: getComputedStyle(header).color, height: header.getBoundingClientRect().height } : null,
    footer: footer ? { background: getComputedStyle(footer).backgroundColor, color: getComputedStyle(footer).color } : null,
    containerWidth: widest.length ? Math.max(...widest) : null,
  }
}

const toHex = (rgb) => {
  const match = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/.exec(rgb ?? '')
  if (!match || (match[4] !== undefined && Number(match[4]) < 0.5)) return null
  return '#' + match.slice(1, 4).map((value) => Number(value).toString(16).padStart(2, '0')).join('')
}

const readMetrics = () => {
  const root = document.querySelector('main') ?? document.body
  let sections = [...root.querySelectorAll(':scope > section, :scope > div > section, :scope > main > section, :scope > div')].filter((element) => element.offsetHeight > 40)
  if (sections.length < 2) sections = [...document.querySelectorAll('section')].filter((element) => element.offsetHeight > 40)
  return sections.slice(0, 40).map((element, index) => {
    const computed = getComputedStyle(element)
    const heading = element.querySelector('h1, h2, h3')
    const headingStyle = heading ? getComputedStyle(heading) : null
    const box = element.getBoundingClientRect()
    return {
      index, classes: element.className.toString().slice(0, 80), top: Math.round(box.top + scrollY), height: Math.round(box.height),
      padding: `${computed.paddingTop} ${computed.paddingBottom}`, background: computed.backgroundColor, backgroundImage: computed.backgroundImage !== 'none',
      heading: heading ? { text: heading.textContent.trim().slice(0, 50), size: headingStyle.fontSize, weight: headingStyle.fontWeight, lineHeight: headingStyle.lineHeight } : null,
    }
  })
}

const browser = await chromium.launch()
const routes = pickRoutes()
const only = option('only')
// Measure tokens on the homepage when it's among the routes: it carries the brand's main styles.
const tokenRoute = routes.includes('/') ? '/' : routes[0]
const report = []
let tokens = null
for (const route of routes) {
  const directory = join(migration, 'screens', slug(route))
  mkdirSync(directory, { recursive: true })
  const row = { route, shots: [] }
  for (const width of widths) {
    for (const [label, base] of [['source', source], ['local', local]]) {
      if (!base || (flag('tokens-only') && label === 'local') || (only && only !== label)) {
        if (base && only && only !== label) row.shots.push({ label, width, file: `${slug(route)}/${label}-${width}.png`, reused: true })
        continue
      }
      const page = await browser.newPage({ viewport: { width, height: width > 600 ? 900 : 844 } })
      try {
        await page.goto(new URL(route, base).href, { waitUntil: 'networkidle', timeout: 45000 })
        // Trigger lazy images and scroll-driven reveals before the full-page capture.
        await page.addStyleTag({ content: '*{scroll-behavior:auto!important}' })
        await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise((done) => setTimeout(done, 200)) } window.scrollTo(0, 0) })
        await page.waitForTimeout(800)
        if (label === 'source' && !flag('no-reveal')) {
          // Scroll-triggered reveals (Webflow IX2, AOS, GSAP) leave content at opacity 0 offscreen.
          await page.addStyleTag({ content: '[style*="opacity: 0"],[style*="opacity:0"],[data-aos]{opacity:1!important;transform:none!important}' })
        }
        if (flag('metrics')) writeFileSync(join(directory, `metrics-${label}-${width}.json`), JSON.stringify(await page.evaluate(readMetrics), null, 2))
        const file = join(directory, `${label}-${width}.png`)
        if (!flag('tokens-only')) {
          await page.screenshot({ path: file.replace('.png', '-fold.png') })
          await page.screenshot({ path: file, fullPage: true })
        }
        if (label === 'source' && width === widths[0] && !tokens && !flag('no-tokens') && (route === tokenRoute)) tokens = await page.evaluate(readTokens)
        row.shots.push({ label, width, file: `${slug(route)}/${label}-${width}.png`, height: await page.evaluate(() => document.body.scrollHeight) })
      } catch (error) {
        row.shots.push({ label, width, error: String(error) })
      }
      await page.close()
    }
  }
  report.push(row)
  console.error(`captured ${route}`)
}
await browser.close()

if (tokens) {
  const mapped = {
    'font-body': tokens.body?.fontFamily, 'font-heading': tokens.h1?.fontFamily ?? tokens.h2?.fontFamily,
    'font-weight-heading': tokens.h1?.fontWeight ?? tokens.h2?.fontWeight,
    'text-base': tokens.body?.fontSize, 'text-h1': tokens.h1?.fontSize, 'text-h2': tokens.h2?.fontSize, 'text-h3': tokens.h3?.fontSize,
    'color-text': toHex(tokens.body?.color), 'color-background': toHex(tokens.body?.background),
    'color-primary': toHex(tokens.button?.background), 'color-on-primary': toHex(tokens.button?.color),
    'radius-button': tokens.button?.borderRadius,
    'color-header-bg': toHex(tokens.header?.background), 'color-header-text': toHex(tokens.header?.color),
    'color-footer-bg': toHex(tokens.footer?.background), 'color-footer-text': toHex(tokens.footer?.color),
    container: tokens.containerWidth ? `${tokens.containerWidth}px` : null,
  }
  const clean = Object.fromEntries(Object.entries(mapped).filter(([, value]) => value))
  writeFileSync(join(migration, 'design-tokens.json'), JSON.stringify({ measured_on: routes[0], raw: tokens, tokens: clean }, null, 2) + '\n')
}

if (!flag('tokens-only')) {
  const metricsTable = (row, width) => {
    if (!flag('metrics')) return ''
    const read = (label) => { try { return JSON.parse(readFileSync(join(migration, 'screens', slug(row.route), `metrics-${label}-${width}.json`), 'utf8')) } catch { return [] } }
    const sourceMetrics = read('source'), localMetrics = read('local')
    const rows = Array.from({ length: Math.max(sourceMetrics.length, localMetrics.length) }, (_, index) => {
      const a = sourceMetrics[index] ?? {}, b = localMetrics[index] ?? {}
      const cell = (m) => m.index === undefined ? '—' : `${m.height}px · ${m.padding} · ${m.background}${m.backgroundImage ? ' +img' : ''}${m.heading ? ` · ${m.heading.size}/${m.heading.weight}/${m.heading.lineHeight} “${m.heading.text}”` : ''}`
      return `<tr><td>${index}</td><td>${cell(a)}</td><td>${cell(b)}</td></tr>`
    }).join('')
    return `<table><tr><th>#</th><th>source</th><th>local</th></tr>${rows}</table>`
  }
  const cells = report.map((row) => `<section><h2>${row.route}</h2>${widths.map((width) => `${metricsTable(row, width)}<div class="pair">${['source', 'local'].map((label) => {
    const shot = row.shots.find((entry) => entry.label === label && entry.width === width)
    return `<figure><figcaption>${label} · ${width}px${shot?.height ? ` · ${shot.height}px tall` : ''}</figcaption>${shot?.file ? `<img src="${shot.file}" loading="lazy">` : `<pre>${shot?.error ?? 'missing'}</pre>`}</figure>`
  }).join('')}</div>`).join('')}</section>`).join('')
  writeFileSync(join(migration, 'screens', 'report.html'), `<!doctype html><meta charset="utf-8"><title>Parity screenshots</title><style>body{font:14px system-ui;margin:1rem;background:#f4f4f4}.pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}figure{margin:0;background:#fff;padding:.5rem}img{width:100%;border:1px solid #ddd}table{border-collapse:collapse;font-size:12px;background:#fff}td,th{border:1px solid #ddd;padding:3px 6px;text-align:left}</style>${cells}`)
  console.log(`screenshots for ${report.length} routes → ${join(migration, 'screens', 'report.html')}`)
}
if (tokens) console.log(`design tokens → ${join(migration, 'design-tokens.json')}`)
