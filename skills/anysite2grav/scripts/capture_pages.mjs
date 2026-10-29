#!/usr/bin/env node
// Screenshot source vs local pages side by side and read computed design tokens from the source.
//
// Usage:
//   node capture_pages.mjs --migration migration --source https://example.com --local http://127.0.0.1:8000 \
//        [--routes /,/about] [--limit 12] [--widths 1440,390] [--tokens-only] [--no-tokens]
//        [--only local|source] [--metrics] [--no-reveal]
// Each route with both shots gets a similarity score (fold/full, 0–100) in report.html and
// screens/scores.json, lowest first: work on the lowest scores next.
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
  // Headings: the most common computed size among visible content headings (ties → larger), so one
  // small eyebrow or card title doesn't become the whole site's h2.
  const typical = (selector) => {
    const candidates = [...document.querySelectorAll(selector)].filter((element) => element.offsetParent !== null
      && element.getBoundingClientRect().height > 0 && !element.closest('header, nav, footer, dialog, [role=dialog]'))
    if (!candidates.length) return visible(selector)
    const bySize = new Map()
    for (const element of candidates) {
      const size = getComputedStyle(element).fontSize
      bySize.set(size, [...(bySize.get(size) ?? []), element])
    }
    const [, elements] = [...bySize.entries()].sort((firstEntry, secondEntry) => secondEntry[1].length - firstEntry[1].length || parseFloat(secondEntry[0]) - parseFloat(firstEntry[0]))[0]
    return elements[0]
  }
  const style = (selector) => {
    const element = selector === 'body' ? document.body : /^h[1-6]$/.test(selector) ? typical(selector) : visible(selector)
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
    button: button ? (() => { const computed = getComputedStyle(button); return { color: computed.color, background: computed.backgroundColor, borderRadius: computed.borderRadius, padding: computed.padding, fontWeight: computed.fontWeight, fontSize: computed.fontSize } })() : null,
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

// Visual similarity of two screenshots (0–100): both scaled to 160px wide and compared on luminance,
// over the first viewport ("fold") and over the full shared height. A guide for the fidelity loop,
// not pass/fail: photos, carousels and dates differ legitimately.
const similarity = async (files, viewport) => {
  const page = await browser.newPage()
  const [sourceImage, localImage] = files.map((file) => 'data:image/png;base64,' + readFileSync(file).toString('base64'))
  const result = await page.evaluate(async ([first, second, viewportWidth, viewportHeight]) => {
    const load = (src) => new Promise((done) => { const image = new Image(); image.onload = () => done(image); image.src = src })
    const [left, right] = await Promise.all([load(first), load(second)])
    const width = 160
    const scaled = (image) => Math.round(image.height * width / image.width)
    const height = Math.min(scaled(left), scaled(right), 2400)
    const pixels = (image) => {
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const context = canvas.getContext('2d')
      context.drawImage(image, 0, 0, width, scaled(image))
      return context.getImageData(0, 0, width, height).data
    }
    const [sourcePixels, localPixels] = [pixels(left), pixels(right)]
    const score = (rows) => {
      let total = 0
      for (let index = 0; index < width * rows * 4; index += 4) {
        total += Math.abs((0.2126 * sourcePixels[index] + 0.7152 * sourcePixels[index + 1] + 0.0722 * sourcePixels[index + 2]) - (0.2126 * localPixels[index] + 0.7152 * localPixels[index + 1] + 0.0722 * localPixels[index + 2]))
      }
      return Math.round(100 - total / (width * rows) / 2.55)
    }
    const foldRows = Math.max(1, Math.min(height, Math.round(viewportHeight * width / viewportWidth)))
    return { fold: score(foldRows), full: score(height), heightRatio: +(scaled(right) / scaled(left)).toFixed(2) }
  }, [sourceImage, localImage, viewport.width, viewport.height])
  await page.close()
  return result
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
        await page.evaluate(async () => { for (let scrollPosition = 0; scrollPosition < document.body.scrollHeight; scrollPosition += 500) { window.scrollTo(0, scrollPosition); await new Promise((done) => setTimeout(done, 200)) } window.scrollTo(0, 0) })
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
    const pair = ['source', 'local'].map((label) => join(directory, `${label}-${width}.png`))
    if (pair.every((file) => existsSync(file))) {
      row.scores = row.scores ?? {}
      row.scores[width] = await similarity(pair, { width, height: width > 600 ? 900 : 844 })
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
      const sourceMetric = sourceMetrics[index] ?? {}, localMetric = localMetrics[index] ?? {}
      const cell = (metric) => metric.index === undefined ? '—' : `${metric.height}px · ${metric.padding} · ${metric.background}${metric.backgroundImage ? ' +img' : ''}${metric.heading ? ` · ${metric.heading.size}/${metric.heading.weight}/${metric.heading.lineHeight} “${metric.heading.text}”` : ''}`
      return `<tr><td>${index}</td><td>${cell(sourceMetric)}</td><td>${cell(localMetric)}</td></tr>`
    }).join('')
    return `<table><tr><th>#</th><th>source</th><th>local</th></tr>${rows}</table>`
  }
  // Lowest similarity first: that's where the next fidelity pass should go.
  const scoreOf = (row) => Math.min(...Object.values(row.scores ?? {}).map((score) => score.full), 101)
  report.sort((sourceRow, localRow) => scoreOf(sourceRow) - scoreOf(localRow))
  const badge = (row, width) => {
    const score = row.scores?.[width]
    return score ? ` <small>grayscale triage: fold ${score.fold} · full ${score.full} · height ×${score.heightRatio}</small>` : ''
  }
  const cells = report.map((row) => `<section><h2>${row.route}</h2>${widths.map((width) => `<h3>${width}px${badge(row, width)}</h3>${metricsTable(row, width)}<div class="pair">${['source', 'local'].map((label) => {
    const shot = row.shots.find((entry) => entry.label === label && entry.width === width)
    return `<figure><figcaption>${label} · ${width}px${shot?.height ? ` · ${shot.height}px tall` : ''}</figcaption>${shot?.file ? `<img src="${shot.file}" loading="lazy">` : `<pre>${shot?.error ?? 'missing'}</pre>`}</figure>`
  }).join('')}</div>`).join('')}</section>`).join('')
  writeFileSync(join(migration, 'screens', 'report.html'), `<!doctype html><meta charset="utf-8"><title>Parity screenshots</title><style>body{font:14px system-ui;margin:1rem;background:#f4f4f4}.pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}figure{margin:0;background:#fff;padding:.5rem}img{width:100%;border:1px solid #ddd}table{border-collapse:collapse;font-size:12px;background:#fff}td,th{border:1px solid #ddd;padding:3px 6px;text-align:left}</style><p>Grayscale scores are triage hints, not fidelity percentages or acceptance. They ignore hue and compare only a downsampled shared height. Review full-color screenshots, component measurements, working features and CMS editing separately.</p>${cells}`)
  const scored = report.filter((row) => row.scores)
  if (scored.length) {
    const scoresFile = join(migration, 'screens', 'scores.json')
    const previous = existsSync(scoresFile) ? JSON.parse(readFileSync(scoresFile, 'utf8')) : {}
    for (const row of scored) previous[row.route] = row.scores
    writeFileSync(scoresFile, JSON.stringify(previous, null, 1) + '\n')
    console.log('grayscale triage (fold/full, not fidelity percentages; inspect screenshots and component differences):')
    for (const row of scored) console.log(`  ${row.route.padEnd(32)} ${Object.entries(row.scores).map(([width, score]) => `${width}: ${score.fold}/${score.full}`).join('   ')}`)
  }
  console.log(`screenshots for ${report.length} routes → ${join(migration, 'screens', 'report.html')}`)
}
if (tokens) console.log(`design tokens → ${join(migration, 'design-tokens.json')}`)
