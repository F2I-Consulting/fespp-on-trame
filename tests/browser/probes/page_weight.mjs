/*
 * Probe: what the page loads before the interface shows, and how long each
 * part takes — the resources (scripts, styles, fonts) by size and duration,
 * the websocket, the first state, Vue's mount, the first 3D view.
 *
 *   node probes/page_weight.mjs [url]
 *
 * It asserts nothing: it prints, so that a diet of the page (widgets loaded
 * on demand, a long cache) is measured, not guessed.
 */
import { chromium } from '@playwright/test';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8082/fespp/index.html';
const t0 = Date.now();
const ms = () => String(Date.now() - t0).padStart(6);

const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
const marks = {};
// BLOCK=regex: the resources NOT to load (what a diet would gain, measured
// before it is written — a blocked module logs a lookup error and the page
// goes on without it)
if (process.env.BLOCK) {
  const re = new RegExp(process.env.BLOCK);
  // an empty script, not an abort: the client awaits every script's load
  // event and never mounts on a failed one
  await page.route((u) => re.test(u.href), (route) => route.fulfill({
    status: 200, contentType: 'application/javascript', body: '/* blocked by the probe */' }));
  console.log('blocking', process.env.BLOCK);
}
page.on('websocket', (ws) => { marks.websocket = Date.now() - t0; });
await page.goto(URL, { waitUntil: 'domcontentloaded' });
marks.domcontentloaded = Date.now() - t0;

const state = () => page.evaluate(() => {
  const app = document.getElementById('app');
  return { mounted: !!(app && app.__vue_app__), canvas: document.querySelectorAll('canvas').length };
});
for (let i = 0; i < 100; i++) {
  const s = await state();
  if (s.mounted && !marks.mounted) marks.mounted = Date.now() - t0;
  if (s.canvas && !marks.canvas) { marks.canvas = Date.now() - t0; break; }
  await page.waitForTimeout(50);
}
await page.waitForTimeout(500);

const res = await page.evaluate(() => performance.getEntriesByType('resource').map((r) => ({
  name: r.name.replace(/^https?:\/\/[^/]+/, ''), type: r.initiatorType,
  bytes: r.transferSize, decoded: r.decodedBodySize,
  start: Math.round(r.startTime), dur: Math.round(r.duration),
})));
const nav = await page.evaluate(() => {
  const n = performance.getEntriesByType('navigation')[0];
  return n ? { domInteractive: Math.round(n.domInteractive), domComplete: Math.round(n.domComplete), load: Math.round(n.loadEventEnd) } : {};
});
console.log('marks (ms since goto):', JSON.stringify(marks), 'navigation:', JSON.stringify(nav));
const byType = {};
for (const r of res) { const k = r.type; byType[k] = byType[k] || { n: 0, bytes: 0, decoded: 0 }; byType[k].n++; byType[k].bytes += r.bytes; byType[k].decoded += r.decoded; }
console.log('by type:', JSON.stringify(byType));
console.log('resources, heaviest first (transfer KB, decoded KB, start ms, duration ms):');
for (const r of res.sort((a, b) => b.decoded - a.decoded).slice(0, 40)) {
  console.log(String(Math.round(r.bytes / 1024)).padStart(6), String(Math.round(r.decoded / 1024)).padStart(7),
    String(r.start).padStart(6), String(r.dur).padStart(6), r.name.slice(0, 110));
}
const last = res.reduce((m, r) => Math.max(m, r.start + r.dur), 0);
console.log('last resource done at', Math.round(last), 'ms; resources:', res.length);
await browser.close();
