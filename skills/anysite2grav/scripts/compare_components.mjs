#!/usr/bin/env node
// Compare explicitly paired components in the real source and Grav render, including UI states.
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const STYLE_PROPERTIES = `display position box-sizing overflow overflow-x overflow-y visibility opacity
  width height min-width max-width min-height max-height
  padding-top padding-right padding-bottom padding-left margin-top margin-right margin-bottom margin-left
  row-gap column-gap grid-template-columns grid-template-rows grid-auto-flow
  flex-direction flex-wrap flex-grow flex-shrink flex-basis justify-content align-items align-content align-self
  font-family font-size font-weight font-style font-stretch line-height letter-spacing text-align text-transform
  text-decoration-line text-decoration-color text-decoration-thickness text-underline-offset white-space
  color background-color background-image background-size background-position background-repeat
  border-top-width border-right-width border-bottom-width border-left-width
  border-top-style border-right-style border-bottom-style border-left-style
  border-top-color border-right-color border-bottom-color border-left-color
  border-top-left-radius border-top-right-radius border-bottom-right-radius border-bottom-left-radius
  outline-width outline-style outline-color outline-offset box-shadow text-shadow
  object-fit object-position aspect-ratio filter transform transform-origin clip-path z-index
  transition-property transition-duration transition-timing-function`.split(/\s+/);

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[character]);

const sideValue = (value, side) => typeof value === 'object' && value !== null ? value[side] : value;

function validatePlan(plan) {
  if (!Array.isArray(plan.cases) || !plan.cases.length) throw new Error('plan.cases must be a nonempty array');
  const identifiers = new Set();
  for (const entry of plan.cases) {
    if (!entry.id || identifiers.has(entry.id)) throw new Error('Every case needs a unique id');
    identifiers.add(entry.id);
    for (const route of ['source', 'local'].map((side) => sideValue(entry.route, side))) {
      if (typeof route !== 'string' || !route.startsWith('/') || route.startsWith('//')) throw new Error(`${entry.id}: route must start with one slash`);
    }
    const widths = entry.widths ?? plan.widths ?? [1440, 768, 390];
    if (!Array.isArray(widths) || !widths.length || widths.some((width) => !Number.isInteger(width) || width < 1)) throw new Error(`${entry.id}: invalid widths`);
    const states = entry.states ?? [{ name: 'default' }];
    if (!Array.isArray(states) || !states.length || new Set(states.map((state) => state.name)).size !== states.length || states.some((state) => !state.name)) throw new Error(`${entry.id}: states need unique names`);
    for (const definitions of [entry.elements, ...states.filter((state) => state.elements !== undefined).map((state) => state.elements)]) {
      if (!definitions || Array.isArray(definitions) || !Object.keys(definitions).length) throw new Error(`${entry.id}: elements are required`);
      for (const [name, element] of Object.entries(definitions)) {
        if (typeof element.source !== 'string' || !element.source || typeof element.local !== 'string' || !element.local) throw new Error(`${entry.id}/${name}: source and local selectors are required`);
        if (element.count !== undefined && (!Number.isInteger(element.count) || element.count < 1)) throw new Error(`${entry.id}/${name}: count must be positive`);
      }
    }
  }
  if (plan.tolerance !== undefined && (!Number.isFinite(plan.tolerance) || plan.tolerance < 0)) throw new Error('tolerance must be a nonnegative number');
}

// Runs inside the page; serializable so the same measurement is used on both sites.
function readElements(elements, properties) {
  return elements.map((element) => {
    const rectangle = element.getBoundingClientRect();
    const computed = getComputedStyle(element);
    const styleOf = (style) => Object.fromEntries(properties.map((property) => [property, style.getPropertyValue(property)]));
    const pseudoOf = (pseudo) => {
      const style = getComputedStyle(element, pseudo);
      return ['none', 'normal', ''].includes(style.content) ? null : { content: style.content, ...styleOf(style) };
    };
    const images = [...element.querySelectorAll('img'), ...(element.matches('img') ? [element] : [])];
    const text = element.innerText ?? element.textContent ?? '';
    return {
      text: text.replace(/\s+/g, ' ').trim(),
      bounds: { x: rectangle.x + scrollX, y: rectangle.y + scrollY, width: rectangle.width, height: rectangle.height },
      visible: computed.display !== 'none' && computed.visibility !== 'hidden' && rectangle.width > 0 && rectangle.height > 0,
      styles: styleOf(computed),
      before: pseudoOf('::before'), after: pseudoOf('::after'),
      attributes: Object.fromEntries(['aria-expanded', 'aria-selected', 'aria-pressed', 'aria-current', 'aria-invalid', 'disabled', 'placeholder'].map((name) => [name, element.getAttribute(name)])),
      brokenImages: images.filter((image) => image.getBoundingClientRect().width > 0 && (!image.complete || image.naturalWidth === 0)).map((image) => image.currentSrc || image.src),
    };
  });
}

function difference(path, source, local, tolerance, output) {
  if (source === local) return;
  if (typeof source === 'number' && typeof local === 'number' && Math.abs(source - local) <= tolerance) return;
  // Only pixel lengths get numeric tolerance. Colors, font weights, transforms and content stay exact.
  if (typeof source === 'string' && typeof local === 'string' && /^-?[\d.]+px$/.test(source) && /^-?[\d.]+px$/.test(local)
    && Math.abs(parseFloat(source) - parseFloat(local)) <= tolerance) return;
  if (source && local && typeof source === 'object' && typeof local === 'object') {
    for (const key of new Set([...Object.keys(source), ...Object.keys(local)])) difference(`${path}.${key}`, source[key], local[key], tolerance, output);
    return;
  }
  output.push({ property: path, source: source ?? null, local: local ?? null });
}

export function compareElements(source, local, definition, tolerance) {
  const differences = [];
  const expectedCount = definition.count ?? source.length;
  if (!source.length || source.length !== expectedCount || local.length !== expectedCount) {
    differences.push({ property: 'count', source: source.length, local: local.length, expected: expectedCount });
  }
  for (let index = 0; index < Math.min(source.length, local.length); index += 1) {
    const sourceElement = source[index], localElement = local[index];
    const elementPath = `[${index}]`;
    const visible = definition.visible ?? true;
    if (sourceElement.visible !== visible || localElement.visible !== visible) differences.push({ property: `${elementPath}.visible`, source: sourceElement.visible, local: localElement.visible, expected: visible });
    if (!sourceElement.visible || !localElement.visible) continue;
    for (const side of ['source', 'local']) {
      const snapshot = side === 'source' ? sourceElement : localElement;
      if (snapshot.brokenImages.length) differences.push({ property: `${elementPath}.brokenImages.${side}`, source: side === 'source' ? snapshot.brokenImages : [], local: side === 'local' ? snapshot.brokenImages : [] });
    }
    const geometry = definition.geometry ?? ['x', 'y', 'width', 'height'];
    for (const dimension of geometry) difference(`${elementPath}.bounds.${dimension}`, sourceElement.bounds[dimension], localElement.bounds[dimension], tolerance, differences);
    for (const property of ['styles', 'before', 'after', ...(definition.text === false ? [] : ['text'])]) {
      difference(`${elementPath}.${property}`, sourceElement[property], localElement[property], tolerance, differences);
    }
    for (const attribute of definition.attributes ?? Object.keys(sourceElement.attributes)) difference(`${elementPath}.attributes.${attribute}`, sourceElement.attributes[attribute], localElement.attributes[attribute], tolerance, differences);
  }
  return differences;
}

async function applySteps(page, steps, side) {
  for (const step of steps) {
    const selector = sideValue(step.selector, side);
    if (step.action === 'scroll') {
      await page.evaluate((top) => window.scrollTo(0, top), step.top);
    } else if (step.action === 'press' && !selector) {
      await page.keyboard.press(step.key);
    } else {
      if (!selector) throw new Error(`${step.action}: selector is required`);
      const target = page.locator(selector);
      if (await target.count() !== 1) throw new Error(`${step.action}: ${selector} must match exactly one element`);
      switch (step.action) {
        case 'hover': await target.hover(); break;
        case 'focus': await target.focus(); break;
        case 'click': await target.click(); break;
        case 'fill': await target.fill(step.value); break;
        case 'press': await target.press(step.key); break;
        case 'waitFor': await target.waitFor({ state: step.state ?? 'visible' }); break;
        default: throw new Error(`Unknown action: ${step.action}`);
      }
    }
  }
}

async function capture(browser, base, entry, state, width, plan, side, directory, stem) {
  const page = await browser.newPage({ viewport: { width, height: plan.height ?? 900 }, deviceScaleFactor: 1,
    reducedMotion: plan.reducedMotion ?? 'reduce', colorScheme: plan.colorScheme ?? 'light', locale: plan.locale ?? 'en-US' });
  page.setDefaultTimeout(plan.timeout ?? 15000);
  try {
    const response = await page.goto(`${base.replace(/\/$/, '')}${sideValue(entry.route, side)}`, { waitUntil: 'load' });
    if (!response || !response.ok()) throw new Error(`HTTP ${response?.status() ?? 'missing response'}`);
    await page.evaluate(() => Promise.race([document.fonts.ready, new Promise((resolveTimer, reject) => setTimeout(() => reject(new Error('Fonts did not finish loading')), 10000))]));
    // Load lazy media without altering the source's opacity, transforms or styles.
    await page.evaluate(async () => {
      const height = document.documentElement.scrollHeight;
      for (let position = 0; position < height; position += Math.max(100, innerHeight / 2)) {
        scrollTo(0, position);
        await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
      }
      scrollTo(0, 0);
    });
    await page.mouse.move(0, 0);
    await applySteps(page, [...(entry.setup ?? []), ...(state.steps ?? [])], side);
    await page.waitForTimeout(state.settleMs ?? plan.settleMs ?? 350);
    await page.evaluate(() => Promise.race([
      Promise.all([document.fonts.ready, ...[...document.images].filter((image) => image.getBoundingClientRect().width > 0).map((image) => image.decode().catch(() => {}))]),
      new Promise((resolveTimer, reject) => setTimeout(() => reject(new Error('Fonts or images did not finish loading')), 10000)),
    ]));
    const elements = {};
    for (const [name, definition] of Object.entries(state.elements ?? entry.elements)) {
      elements[name] = await page.locator(definition[side]).evaluateAll(readElements, definition.properties ?? STYLE_PROPERTIES);
    }
    const screenshot = `${stem}-${side}.png`;
    await page.screenshot({ path: join(directory, screenshot), fullPage: true });
    const documentMetrics = await page.evaluate(() => ({ height: document.documentElement.scrollHeight, width: document.documentElement.scrollWidth, viewport: innerWidth, scroll: scrollY }));
    return { elements, screenshot, document: documentMetrics };
  } finally {
    await page.close();
  }
}

export async function runComparison({ plan, source, local, out, tools }) {
  validatePlan(plan);
  const require = createRequire(join(resolve(tools), 'package.json'));
  const { chromium } = require('playwright');
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const [caseIndex, entry] of plan.cases.entries()) {
      for (const width of entry.widths ?? plan.widths ?? [1440, 768, 390]) {
        for (const [stateIndex, state] of (entry.states ?? [{ name: 'default' }]).entries()) {
          const result = { case: entry.id, route: entry.route, width, state: state.name, differences: [] };
          const stem = `${caseIndex}-${width}-${stateIndex}`;
          for (const side of ['source', 'local']) {
            try {
              result[side] = await capture(browser, side === 'source' ? source : local, entry, state, width, plan, side, out, stem);
            } catch (error) {
              result.differences.push({ property: `${side}.capture`, error: String(error) });
            }
          }
          if (result.source && result.local) {
            for (const [name, definition] of Object.entries(state.elements ?? entry.elements)) {
              result.differences.push(...compareElements(result.source.elements[name], result.local.elements[name], definition, plan.tolerance ?? 1).map((item) => ({ element: name, ...item })));
            }
            difference('document.height', result.source.document.height, result.local.document.height, plan.tolerance ?? 1, result.differences);
            if (result.local.document.width > width) result.differences.push({ property: 'document.overflow', local: result.local.document.width, expected: width });
          }
          results.push(result);
          console.log(`${result.differences.length ? 'DIFF' : 'MATCH'} ${entry.id} ${width}px ${state.name}: ${result.differences.length} differences`);
        }
      }
    }
  } finally {
    await browser.close();
  }
  const report = { capturedAt: new Date().toISOString(), source, local, tolerance: plan.tolerance ?? 1,
    note: 'Matched selected elements and states only. This is not whole-site visual or functionality sign-off.', results };
  writeFileSync(join(out, 'components.json'), JSON.stringify(report, null, 2) + '\n');
  const sections = results.map((result) => `<section><h2>${escapeHtml(`${result.case} · ${result.width}px · ${result.state}`)}</h2><p>${result.differences.length} differences</p><table><thead><tr><th>Element / property</th><th>Source</th><th>Local / error</th></tr></thead><tbody>${result.differences.map((item) => `<tr><td>${escapeHtml(`${item.element ?? ''} ${item.property}`)}</td><td>${escapeHtml(JSON.stringify(item.source) ?? '')}</td><td>${escapeHtml(item.error ?? JSON.stringify(item.local) ?? '')}</td></tr>`).join('')}</tbody></table><div class="pair">${['source', 'local'].map((side) => result[side] ? `<figure><figcaption>${side}</figcaption><img loading="lazy" src="${result[side].screenshot}"></figure>` : `<p>${side} capture failed</p>`).join('')}</div></section>`).join('');
  writeFileSync(join(out, 'components.html'), `<!doctype html><html lang="en"><meta charset="utf-8"><title>Component fidelity</title><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{padding:6px;border:1px solid #ccc;text-align:left;overflow-wrap:anywhere}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:16px 0}img{width:100%}</style><h1>Component fidelity</h1><p>${escapeHtml(report.note)}</p>${sections}</html>`);
  return results.some((result) => result.differences.length) ? 1 : 0;
}

async function main() {
  const argumentsList = process.argv.slice(2);
  const option = (name, fallback) => {
    const index = argumentsList.indexOf(`--${name}`);
    return index === -1 ? fallback : argumentsList[index + 1];
  };
  if (argumentsList.includes('--help')) {
    console.log('compare_components.mjs --plan fidelity.json --source https://example.com --local http://127.0.0.1:8000 --out migration/components [--tools migration/.tools]\nExit 0: measured matches; 1: differences; 2: invalid plan/runtime. See references/fidelity.md.');
    return 0;
  }
  if (!option('plan') || !option('source') || !option('local') || !option('out')) throw new Error('Required: --plan, --source, --local, --out (see --help)');
  const out = resolve(option('out'));
  return runComparison({ plan: JSON.parse(readFileSync(option('plan'), 'utf8')), source: option('source'), local: option('local'), out,
    tools: option('tools', join(dirname(out), '.tools')) });
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(resolve(process.argv[1]))).href) {
  try { process.exitCode = await main(); } catch (error) { console.error(String(error)); process.exitCode = 2; }
}
