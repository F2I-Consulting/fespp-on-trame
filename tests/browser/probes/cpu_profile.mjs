/*
 * Probe: where the browser's CPU goes between the page and the mounted
 * interface — JavaScript self time per script file, from Chrome's profiler.
 *
 *   node probes/cpu_profile.mjs [url]
 *
 * Parse and compile are not in the profile (they are V8's, not a script's):
 * what it says is what each bundle EXECUTES, which is what a bundle loaded
 * on demand would spare the first paint.
 */
import { chromium } from '@playwright/test';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8082/fespp/index.html';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send('Profiler.enable');
await cdp.send('Profiler.setSamplingInterval', { interval: 500 });
await cdp.send('Profiler.start');
const t0 = Date.now();
await page.goto(URL, { waitUntil: 'domcontentloaded' });
let mounted = 0;
for (let i = 0; i < 120; i++) {
  const m = await page.evaluate(() => { const a = document.getElementById('app'); return !!(a && a.__vue_app__); });
  if (m) { mounted = Date.now() - t0; break; }
  await page.waitForTimeout(50);
}
const { profile } = await cdp.send('Profiler.stop');
const byId = new Map(profile.nodes.map((n) => [n.id, n]));
const self = new Map();
let total = 0;
for (let i = 0; i < profile.samples.length; i++) {
  const n = byId.get(profile.samples[i]);
  const dt = profile.timeDeltas[i] || 0;
  total += dt;
  const f = n.callFrame;
  const key = f.url ? f.url.replace(/^https?:\/\/[^/]+/, '') : `(${f.functionName || 'anonymous'})`;
  self.set(key, (self.get(key) || 0) + dt);
}
console.log('mounted at', mounted, 'ms; profiled', Math.round(total / 1000), 'ms of samples');
console.log('self time by script (ms), heaviest first:');
for (const [k, v] of [...self.entries()].sort((a, b) => b[1] - a[1]).slice(0, 25)) {
  console.log(String(Math.round(v / 1000)).padStart(6), k.slice(0, 120));
}
await browser.close();
