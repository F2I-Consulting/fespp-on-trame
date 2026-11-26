/*
 * Probe: a large read runs in steps (fespp_on_trame/engine/progressive_load.py).
 * The pill at the bottom of the view counts the objects, Stop keeps what has
 * arrived and unticks the rest, a "clear all" mid-read supersedes the read,
 * and a read left to finish ends on the selection a one-shot read would have
 * loaded.
 *
 * Only a server read runs in steps; without a server, the instance's
 * container needs FESPP_STEP_LOCAL=1 in its environment and the same steps
 * run on a file. The file is drogon (data/private, or FESPP_SMOKE_DATA),
 * with every object of its wells and surfaces tabs ticked. Prints the counts
 * it saw and the duration of the whole read; asserts nothing.
 *
 *   node probes/stepped-read.mjs [url]
 *
 * The url defaults to FESPP_SMOKE_URL, else to the instance that
 * tests/browser/instance.ps1 starts (http://localhost:8095/index.html).
 *
 * A file reads in one load by default because, on a local file, a stepped
 * read is several times slower than a one-shot read.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://localhost:8095/index.html';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = (process.env.FESPP_SMOKE_DATA || path.join(HERE, '..', '..', '..', 'data', 'private')) + '/';
const OUT = process.env.FESPP_SMOKE_OUT || path.join(HERE, '..', 'out');
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
const st = (k) => page.evaluate((key) => window.trame.state.get(key), k);
const set = (k, v) => page.evaluate(([key, val]) => window.trame.state.set(key, val), [k, v]);
async function until(fn, what, ms = 180000) {
  const t0 = Date.now();
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() - t0 > ms) throw new Error('timeout: ' + what);
    await page.waitForTimeout(150);
  }
}
async function answerQuestion() {
  const box = page.locator('.fp-dialog .fp-primary');
  if (await box.isVisible().catch(() => false)) {
    log('question:', (await page.locator('.fp-dialog .fp-title').innerText()).trim());
    await box.click();
  }
}

await page.goto(URL);
await page.waitForFunction(() => window.trame && window.trame.state, null, { timeout: 60000 });
await page.locator('.up-dialog').waitFor({ state: 'visible', timeout: 60000 });
await page.setInputFiles('input[type=file]', [DATA + 'drogon.epc', DATA + 'drogon.h5']);
await until(() => st('ui_has_data'), 'drogon loaded', 300000);
await page.locator('button.uf-close').click();
log('drogon loaded');

// every path of the well and surface tabs, as a "select all" would tick them
const paths = await page.evaluate(() => {
  const out = new Set();
  const walk = (x) => {
    if (Array.isArray(x)) return x.forEach(walk);
    if (x && typeof x === 'object') {
      if (typeof x.path === 'string' && x.path.startsWith('/')) out.add(x.path);
      Object.values(x).forEach(walk);
    }
  };
  for (const k of ['ui_subtree_well', 'ui_subtree_surface']) walk(window.trame.state.get(k));
  return [...out];
});
log('paths to tick:', paths.length);

// 1. Stop, clicked the moment the pill shows a count
await page.evaluate(() => {
  window.__stopSeen = null;
  const obs = new MutationObserver(() => {
    const b = document.querySelector('[data-fp-load-stop]');
    const c = document.querySelector('[data-fp-load-count]');
    if (b && c && !window.__stopSeen && /Loading [1-9]/.test(c.textContent)) {
      window.__stopSeen = c.textContent.trim();
      b.click();
    }
  });
  obs.observe(document.body, { childList: true, subtree: true, characterData: true });
  window.__obs = obs;
});
await set('selected_paths', paths);
await page.waitForTimeout(400);
await answerQuestion();
await until(async () => (await st('ui_load_progress') || {}).running, 'the pill shows', 60000);
log('pill:', JSON.stringify(await st('ui_load_progress')));
await page.screenshot({ path: path.join(OUT, 'stepped-pill.png') });
await until(async () => !(await st('ui_load_progress') || {}).running, 'the read ends after Stop');
log('stop clicked at:', await page.evaluate(() => window.__stopSeen));
const sel1 = await st('selected_paths'), fds1 = await st('fespp_data_selectors');
log('after Stop: selected', sel1.length, '/ loaded', fds1.length, 'of', paths.length,
  '| same set:', JSON.stringify([...sel1].sort()) === JSON.stringify([...fds1].sort()));
log('snackbar:', await st('empty_color_snackbar_text'));
await page.evaluate(() => window.__obs.disconnect());

// 2. the whole read, sampled: the count should grow in steps
await set('selected_paths', paths);
await page.waitForTimeout(400);
await answerQuestion();
const samples = [];
const t0 = Date.now();
await until(async () => {
  const p = await st('ui_load_progress') || {};
  if (p.running) samples.push(p.done);
  return samples.length > 0 && !p.running;
}, 'the whole read ends', 300000);
const fds2 = await st('fespp_data_selectors'), sel2 = await st('selected_paths');
log('whole read:', ((Date.now() - t0) / 1000).toFixed(1), 's, counts seen', [...new Set(samples)].join(','),
  '| loaded', fds2.length, '| selected', sel2.length);
await page.screenshot({ path: path.join(OUT, 'stepped-done.png') });

// 3. "clear all" in the middle of a read supersedes it
await set('selected_paths', []);
await until(async () => (await st('fespp_data_selectors') || []).length === 0, 'cleared');
await set('selected_paths', paths);
await page.waitForTimeout(400);
await answerQuestion();
await until(async () => ((await st('ui_load_progress')) || {}).done > 0, 'a first step', 60000);
await set('selected_paths', []);
await until(async () => !((await st('ui_load_progress')) || {}).running, 'the pill goes', 60000);
await page.waitForTimeout(1500);
log('clear all mid-read: loaded', (await st('fespp_data_selectors')).length,
  '| selected', (await st('selected_paths')).length);
await browser.close();
