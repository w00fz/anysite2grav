import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runComparison } from '../scripts/compare_components.mjs';

const tools = process.env.GRAV_PLAYWRIGHT_TOOLS;

function fixture(route) {
  const change = route.includes('different') ? '.hero{padding-left:55px;background:#f6c6f6}'
    : route.includes('hover-only') ? 'button:hover{background:rgb(255,0,0)}'
    : route.includes('pseudo-only') ? 'button::before{content:"?"}' : '';
  return `<!doctype html><html lang="en"><meta charset="utf-8"><title>Fixture</title>
    <style>body{margin:0;font:16px/1.4 Arial}.hero{padding:31px 37px;background:#f6f6f6;display:grid;grid-template-columns:1fr 2fr;gap:23px}
    h1{font-size:32px;margin:0}.cards{display:grid;grid-template-columns:1fr 1fr;gap:19px}.card{border:1px solid #333;padding:7px}
    button{font:inherit;padding:11px 17px;border:2px solid #123;background:white;transition:none}button:hover{background:rgb(255,255,0)}
    button:focus{outline:3px solid blue;outline-offset:2px}button::before{content:"!";margin-right:5px}
    @media(max-width:600px){.hero{padding:13px 19px;grid-template-columns:1fr}.cards{grid-template-columns:1fr}}
    ${change}</style><main><section class="hero"><h1>Source heading</h1><div><p>Paragraph with <mark>highlight</mark>.</p>
    <button aria-controls="panel" aria-expanded="false">Filters</button><div id="panel" hidden>Filter controls</div></div>
    <div class="cards"><article class="card">First</article>${route.includes('missing') ? '' : '<article class="card">Second</article>'}</div></section></main>
    <script>document.querySelector('button').onclick=()=>{document.querySelector('#panel').hidden=false;document.querySelector('button').setAttribute('aria-expanded','true')}</script></html>`;
}

test('real-browser comparisons distinguish exact responsive/state matches from visible regressions', { skip: !tools }, async (context) => {
  const server = createServer((request, response) => {
    if (request.url.includes('unavailable')) { response.writeHead(404); response.end('missing'); return; }
    response.writeHead(200, { 'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'" });
    response.end(fixture(request.url));
  });
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  context.after(() => new Promise((done) => server.close(done)));
  const base = `http://127.0.0.1:${server.address().port}`;
  const directory = mkdtempSync(join(tmpdir(), 'grav-components-'));
  context.after(() => rmSync(directory, { recursive: true, force: true }));
  const elements = {
    hero: { source: '.hero', local: '.hero', count: 1 },
    heading: { source: 'h1', local: 'h1', count: 1 },
    highlight: { source: 'mark', local: 'mark', count: 1 },
    button: { source: 'button', local: 'button', count: 1 },
    cards: { source: '.card', local: '.card', count: 2 },
  };
  const compare = async (name, cases, widths = [390]) => {
    const out = join(directory, name);
    const status = await runComparison({ plan: { widths, settleMs: 0, cases }, source: base, local: base, tools, out });
    return { status, report: JSON.parse(readFileSync(join(out, 'components.json'), 'utf8')) };
  };
  await context.test('same design matches at three widths, hover, focus and open/closed states under CSP', async () => {
    const { status, report } = await compare('same', [{ id: 'same', route: { source: '/source/', local: '/same/' }, elements,
      states: [
        { name: 'default', elements: { ...elements, panel: { source: '#panel', local: '#panel', count: 1, visible: false } } },
        { name: 'hover', steps: [{ action: 'hover', selector: 'button' }] },
        { name: 'focus', steps: [{ action: 'focus', selector: 'button' }] },
        { name: 'open', steps: [{ action: 'click', selector: 'button' }], elements: { ...elements, panel: { source: '#panel', local: '#panel', count: 1 } } },
      ] }], [1440, 768, 390]);
    assert.equal(status, 0);
    assert.equal(report.results.length, 12);
    const first = report.results[0].source.elements.hero[0].styles;
    const mobile = report.results[8].source.elements.hero[0].styles;
    assert.equal(first['padding-left'], '37px');
    assert.equal(mobile['padding-left'], '19px');
    assert.equal(report.results[1].source.elements.button[0].styles['background-color'], 'rgb(255, 255, 0)');
    assert.equal(report.results[2].source.elements.button[0].styles['outline-width'], '3px');
    assert.equal(report.results[3].source.elements.button[0].attributes['aria-expanded'], 'true');
  });
  await context.test('reports exact color, padding, hover, pseudo-element, count and capture regressions', async () => {
    const cases = ['different', 'hover-only', 'pseudo-only', 'missing', 'unavailable'].map((variant) => ({
      id: variant, route: { source: '/source/', local: `/${variant}/` }, elements,
      states: [{ name: 'hover', steps: [{ action: 'hover', selector: 'button' }] }],
    }));
    const { status, report } = await compare('regressions', cases);
    assert.equal(status, 1);
    const differences = (name) => report.results.find((result) => result.case === name).differences;
    assert.ok(differences('different').some((item) => item.property.endsWith('styles.padding-left')));
    assert.ok(differences('different').some((item) => item.property.endsWith('styles.background-color')));
    assert.ok(differences('hover-only').some((item) => item.element === 'button' && item.property.endsWith('styles.background-color')));
    assert.ok(differences('pseudo-only').some((item) => item.property.endsWith('before.content')));
    assert.ok(differences('missing').some((item) => item.element === 'cards' && item.property === 'count'));
    assert.ok(differences('unavailable').some((item) => item.property === 'local.capture' && item.error.includes('404')));
  });
  await context.test('an empty state override is invalid rather than a vacuous match', async () => {
    await assert.rejects(() => compare('invalid-state', [{ id: 'invalid-state', route: '/source/', elements,
      states: [{ name: 'empty', elements: {} }] }]), /elements are required/);
  });
  await context.test('matching nothing on both sides never passes', async () => {
    const { status, report } = await compare('empty', [{ id: 'empty', route: '/source/', elements: { absent: { source: '.absent', local: '.absent' } } }]);
    assert.equal(status, 1);
    assert.equal(report.results[0].differences[0].property, 'count');
  });
  await context.test('ambiguous action selectors are reported instead of clicking an arbitrary item', async () => {
    const { status, report } = await compare('ambiguous', [{ id: 'ambiguous', route: '/source/', elements,
      states: [{ name: 'click', steps: [{ action: 'click', selector: '.card' }] }] }]);
    assert.equal(status, 1);
    assert.ok(report.results[0].differences.every((item) => item.error.includes('exactly one')));
  });
});
