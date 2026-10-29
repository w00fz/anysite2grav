#!/usr/bin/env node
// Measure the source's real layout for every extracted section and layout block, so pages carry
// the source's design (columns ratio, cards per row, card style, dividers, full-bleed, type scale,
// fonts, header color per page) instead of generic defaults.
//
// Usage:
//   node measure_layout.mjs --migration migration --source https://example.com [--routes /a,/b]
//        [--width 1440] [--all-languages] [--no-reveal]
//
// Reads content/*.json (section and block `_path`s written by extract_content.py) and writes
// migration/layout.json:
//   {routes: {"/news": {chrome: {header, footer}, sections: {<path>: metrics}, blocks: {<path>: metrics}}}}
// build_pages.py turns it into frontmatter (tone, space, divider, bleed, ratio, per_row, size, font…)
// and scaffold_theme.py into tokens (type scale, font roles). Rerun after changing the extraction.
// Without --routes it measures every default-language route (translations reuse their counterpart).
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
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
const width = Number(option('width', '1440'))
if (!source) {
  console.error('usage: measure_layout.mjs --migration migration --source <url> [--routes /a,/b]')
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

// Targets per route: section paths and layout-block paths with a text hint to confirm the match.
const records = readdirSync(join(migration, 'content')).filter((name) => name.endsWith('.json'))
  .map((name) => JSON.parse(readFileSync(join(migration, 'content', name), 'utf8')))
const defaultLang = (() => {
  const counts = {}
  for (const record of records) counts[record.lang] = (counts[record.lang] ?? 0) + 1
  return Object.entries(counts).sort((firstEntry, secondEntry) => secondEntry[1] - firstEntry[1])[0]?.[0]
})()
const wanted = option('routes')?.split(',')
const targets = records.filter((record) => wanted ? wanted.includes(record.route) : (flag('all-languages') || record.lang === defaultLang))

const collect = (blocks, into) => {
  for (const block of blocks ?? []) {
    if (block._path) into.push({ path: block._path, type: block.type })
    for (const inner of [...(block.columns ?? []), ...(block.cards ?? [])]) collect(inner.blocks, into)
  }
  return into
}

// Runs in the page. Everything is computed style or geometry at the given viewport.
const measure = ({ sections, blocks }) => {
  const viewport = document.documentElement.clientWidth
  const style = (element) => getComputedStyle(element)
  const colorOf = (value) => (/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/.exec(value) ?? []).slice(1)
  const visible = (value) => { const [redChannel, , , alphaChannel] = colorOf(value); return redChannel !== undefined && (alphaChannel === undefined || Number(alphaChannel) > 0.05) }
  const text = (element) => (element?.textContent ?? '').replace(/\s+/g, ' ').trim()
  const find = (path, hint) => {
    let element = null
    try { element = document.querySelector(path) } catch { element = null }
    const start = (hint ?? '').replace(/\s+/g, ' ').trim().slice(0, 24)
    if (element && (!start || text(element).startsWith(start))) return element
    if (!start) return element
    // The parser and the browser can disagree on the tree: fall back to the smallest element whose
    // text starts with the hint and has the same tag.
    const tag = path.split('>').pop().trim().split(':')[0]
    const candidates = [...document.querySelectorAll(tag)].filter((node) => text(node).startsWith(start))
    return candidates.sort((firstElement, secondElement) => text(firstElement).length - text(secondElement).length)[0] ?? element
  }
  const border = (computed, side) => {
    const widthValue = parseFloat(computed[`border${side}Width`])
    return widthValue >= 1 && computed[`border${side}Style`] !== 'none' && visible(computed[`border${side}Color`]) ? { width: widthValue, color: computed[`border${side}Color`] } : null
  }
  const typography = (element) => {
    const computed = style(element)
    return {
      text: text(element).slice(0, 80), tag: element.tagName.toLowerCase(), size: parseFloat(computed.fontSize),
      family: computed.fontFamily, weight: computed.fontWeight, lineHeight: computed.lineHeight,
      letterSpacing: computed.letterSpacing, transform: computed.textTransform, color: computed.color,
    }
  }
  const imageInfo = (element) => {
    const image = element.querySelector('img')
    if (!image) return null
    const box = image.getBoundingClientRect()
    const computed = style(image)
    return box.width > 4 && box.height > 4 ? { ratio: box.width / box.height, filter: computed.filter, fit: computed.objectFit, radius: computed.borderRadius } : null
  }
  // Builders style an inner wrapper as often as the section itself: step into a single child that
  // covers the section while the outer element paints nothing.
  const effective = (element) => {
    let current = element
    for (let depth = 0; depth < 4; depth += 1) {
      const computed = style(current)
      const kids = [...current.children].filter((child) => child.getBoundingClientRect().height > 4)
      const paints = visible(computed.backgroundColor) || computed.backgroundImage !== 'none' || parseFloat(computed.paddingTop) > 0 || border(computed, 'Top') || border(computed, 'Bottom')
      if (paints || kids.length !== 1 || kids[0].getBoundingClientRect().height < 0.9 * current.getBoundingClientRect().height) break
      current = kids[0]
    }
    return current
  }
  // Items on the first visual row: they overlap the first item vertically (tops can differ when
  // items align to the baseline or bottom).
  const sameRow = (items) => {
    const first = items[0].getBoundingClientRect()
    return items.filter((item) => { const box = item.getBoundingClientRect(); return box.top < first.bottom - 2 && box.bottom > first.top + 2 })
  }
  // The element that paints an item: itself, or a single wrapper inside it (li > div.card).
  const painted = (element) => {
    let current = element
    for (let depth = 0; depth < 3; depth += 1) {
      const computed = style(current)
      if (visible(computed.backgroundColor) || border(computed, 'Top') || computed.boxShadow !== 'none') return current
      const kids = [...current.children].filter((child) => child.getBoundingClientRect().height > 4)
      if (kids.length !== 1) return current
      current = kids[0]
    }
    return current
  }
  const gridOf = (element, heading) => {
    const computed = style(element)
    const kids = [...element.children].filter((child) => child.getBoundingClientRect().height > 4)
    if (!kids.length || !/grid|flex/.test(computed.display) || (computed.display.includes('flex') && computed.flexDirection.startsWith('column'))) return null
    const row = sameRow(kids)
    if (row.length < 2) return null
    // Which track holds the section's own first heading (a split layout: title beside content).
    const headingAt = heading ? row.findIndex((child) => child === heading || child.contains(heading)) : -1
    return {
      tracks: row.map((child) => child.getBoundingClientRect().width),
      headingColumn: headingAt,
      divider: row.some((child, index) => (index < row.length - 1 && border(style(child), 'Right')) || (index > 0 && border(style(child), 'Left'))),
    }
  }
  const sectionMetrics = {}
  for (const { path, hint } of sections) {
    const found = find(path, hint)
    if (!found) continue
    const element = effective(found)
    const computed = style(element)
    const box = element.getBoundingClientRect()
    const widest = [...element.querySelectorAll('*')].slice(0, 400).reduce((max, node) => {
      const rect = node.getBoundingClientRect()
      return rect.height > 40 ? Math.max(max, rect.width) : max
    }, 0)
    sectionMetrics[path] = {
      background: visible(computed.backgroundColor) ? computed.backgroundColor : null,
      backgroundImage: computed.backgroundImage !== 'none',
      color: computed.color,
      padding: [parseFloat(computed.paddingTop), parseFloat(computed.paddingBottom)],
      // Space from the section's edges to its first/last visible content: builders often pad an
      // inner wrapper (or use margins), leaving the section's own padding at 0.
      inset: (() => {
        const content = [...found.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, img, a, button, input, figure')].map((node) => node.getBoundingClientRect()).filter((rect) => rect.height > 2 && rect.width > 2)
        if (!content.length) return null
        const outer = found.getBoundingClientRect()
        return [Math.max(0, Math.min(...content.map((rect) => rect.top)) - outer.top), Math.max(0, outer.bottom - Math.max(...content.map((rect) => rect.bottom)))]
      })(),
      borderTop: border(computed, 'Top'), borderBottom: border(computed, 'Bottom'),
      align: computed.textAlign, height: box.height, width: box.width, widestChild: widest, viewport,
      grid: (() => {
        const heading = element.querySelector('h1, h2, h3, h4')
        // The row holding the heading can sit a few wrappers deep (group > row > heading + text).
        const candidates = [element, ...[...element.querySelectorAll('*')].slice(0, 300).filter((node) => node.getBoundingClientRect().height > 30 && heading && node.contains(heading))]
        return candidates.map((node) => gridOf(node, heading)).find((grid) => grid && grid.headingColumn >= 0) ?? gridOf(element, heading)
      })(),
      headings: [...element.querySelectorAll('h1, h2, h3, h4, h5, h6')].slice(0, 30).map(typography),
      paragraphs: [...element.querySelectorAll('p')].filter((node) => text(node).length > 20).slice(0, 6).map(typography),
    }
  }
  const blockMetrics = {}
  for (const { path, hint, type } of blocks) {
    const element = find(path, hint)
    if (!element) continue
    const computed = style(element)
    const children = [...element.children].filter((child) => child.getBoundingClientRect().height > 4)
    if (!children.length) continue
    if (type === 'list') {
      const items = children
      const top = items[0].getBoundingClientRect().top
      const active = items.find((item) => item.matches('.current, .active, .is-active, [class*=current]') || item.querySelector('[aria-current], .current, .active, .is-active'))
      const activeLink = active ? (active.querySelector('a') ?? active) : null
      blockMetrics[path] = {
        list: true, inline: items.filter((item) => Math.abs(item.getBoundingClientRect().top - top) < 6).length > 1,
        bullets: style(items[0]).listStyleType !== 'none' && style(element).listStyleType !== 'none',
        activeIndex: active ? items.indexOf(active) : null,
        activeBackground: activeLink && visible(style(activeLink).backgroundColor) ? style(activeLink).backgroundColor : null,
        size: parseFloat(style(items[0]).fontSize),
      }
      continue
    }
    const row = sameRow(children)
    const first = painted(children[0])
    const childStyle = style(first)
    blockMetrics[path] = {
      display: computed.display, columns: computed.gridTemplateColumns, gap: [parseFloat(computed.columnGap) || 0, parseFloat(computed.rowGap) || 0],
      align: computed.alignItems, width: element.getBoundingClientRect().width, viewport,
      perRow: row.length, rowWidths: row.map((child) => child.getBoundingClientRect().width), count: children.length,
      child: {
        background: visible(childStyle.backgroundColor) ? childStyle.backgroundColor : null,
        border: border(childStyle, 'Top') ?? border(childStyle, 'Left'), radius: childStyle.borderRadius,
        shadow: childStyle.boxShadow !== 'none', padding: parseFloat(childStyle.paddingTop),
        dividers: children.slice(1).some((child) => border(style(child), 'Left') || border(style(child), 'Top')) ||
          children.slice(0, -1).some((child) => border(style(child), 'Right') || border(style(child), 'Bottom')),
      },
      image: imageInfo(first),
      title: (() => { const heading = first.querySelector('h1, h2, h3, h4, h5, h6'); return heading ? typography(heading) : null })(),
    }
  }
  const chromeOf = (selector) => {
    const element = document.querySelector(selector)
    if (!element) return null
    const computed = style(element)
    let background = computed.backgroundColor
    // Headers often paint their color on an inner bar.
    if (!visible(background)) background = [...element.querySelectorAll('*')].slice(0, 30).map((node) => style(node).backgroundColor).find(visible) ?? null
    const result = { background, color: computed.color, height: element.getBoundingClientRect().height, position: computed.position }
    if (!/header|banner/.test(selector)) return result
    // Header anatomy: logo position and size, nav type, where the menu starts, the CTA button.
    const logo = [...element.querySelectorAll('a img, a svg')].find((node) => node.getBoundingClientRect().width > 8)
    const links = [...element.querySelectorAll('nav a, nav button')].filter((node) => node.getBoundingClientRect().width > 4 && text(node))
    const cta = [...element.querySelectorAll('a, button')].reverse().find((node) => visible(style(node).backgroundColor) && text(node) && node.getBoundingClientRect().width > 40)
    if (logo) {
      const box = logo.getBoundingClientRect()
      result.logo = { left: box.left, right: box.right, height: box.height }
    }
    if (links.length) {
      const first = links[0]
      const linkStyle = style(first)
      result.nav = {
        left: first.getBoundingClientRect().left, size: parseFloat(linkStyle.fontSize), weight: linkStyle.fontWeight,
        paddingX: parseFloat(linkStyle.paddingLeft), gap: links.length > 1 ? links[1].getBoundingClientRect().left - first.getBoundingClientRect().right : 0,
      }
    }
    if (cta) {
      const ctaStyle = style(cta)
      result.cta = { size: parseFloat(ctaStyle.fontSize), weight: ctaStyle.fontWeight, padding: [parseFloat(ctaStyle.paddingTop), parseFloat(ctaStyle.paddingLeft)], radius: ctaStyle.borderRadius, right: viewport - cta.getBoundingClientRect().right }
    }
    return result
  }
  // Form controls: the first visible text-like input and its submit button.
  const inputOf = () => {
    const input = [...document.querySelectorAll('main input[type=search], main input[type=text], main input[type=email], input[type=search]')].find((node) => node.getBoundingClientRect().width > 40)
    if (!input) return null
    const computed = style(input)
    const button = input.form ? [...input.form.querySelectorAll('button, input[type=submit]')].find((node) => node.getBoundingClientRect().width > 4) : null
    return {
      background: computed.backgroundColor, border: border(computed, 'Top'), radius: computed.borderRadius,
      height: input.getBoundingClientRect().height, size: parseFloat(computed.fontSize),
      iconButton: button ? !text(button) || text(button).length <= 1 : null,
    }
  }
  return {
    sections: sectionMetrics, blocks: blockMetrics,
    chrome: { header: chromeOf('header, [role=banner]'), footer: chromeOf('footer:last-of-type, [role=contentinfo]') },
    input: inputOf(),
    body: typography(document.querySelector('main p, p') ?? document.body),
  }
}

const browser = await chromium.launch()
const output = { measured_at: new Date().toISOString(), width, routes: {} }
const outputFile = join(migration, 'layout.json')
if (existsSync(outputFile) && wanted) Object.assign(output.routes, JSON.parse(readFileSync(outputFile, 'utf8')).routes ?? {})
for (const record of targets) {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  try {
    await page.goto(record.url, { waitUntil: 'networkidle', timeout: 45000 })
    await page.evaluate(async () => { for (let scrollPosition = 0; scrollPosition < document.body.scrollHeight; scrollPosition += 600) { window.scrollTo(0, scrollPosition); await new Promise((done) => setTimeout(done, 120)) } window.scrollTo(0, 0) })
    if (!flag('no-reveal')) await page.addStyleTag({ content: '[style*="opacity: 0"],[style*="opacity:0"],[data-aos]{opacity:1!important;transform:none!important}' })
    const sections = record.sections.filter((section) => section._path).map((section) => ({ path: section._path, hint: section._hint }))
    const blocks = record.sections.flatMap((section) => collect(section.blocks, []))
    output.routes[record.route] = await page.evaluate(measure, { sections, blocks })
    console.error(`measured ${record.route}: ${Object.keys(output.routes[record.route].sections).length}/${sections.length} sections, ${Object.keys(output.routes[record.route].blocks).length}/${blocks.length} blocks`)
  } catch (error) {
    console.error(`failed ${record.route}: ${error.message}`)
  }
  await page.close()
}
await browser.close()
writeFileSync(outputFile, JSON.stringify(output, null, 1) + '\n')
console.log(`layout for ${Object.keys(output.routes).length} routes → ${outputFile}`)
