/*
 * Two gestures on a well's logs, as the browser sees them (drogon.epc, three
 * wells read, their first log drawn in the 3D view):
 *
 *   centre / zoom   the Well tree's right-click "Center / Zoom the 3D view on"
 *                   a log: the images the view received and the time from the
 *                   click to the last one
 *   values          the log made active, the Values view opened, the Well log
 *                   view holding its well, then a row of the Values table
 *                   clicked: what the 3D view and the Well log say they light
 *
 * One JSON line on stdout; the log lines go to stderr; shots in tests/browser/out.
 *
 *   node probes/flight_values.mjs http://127.0.0.1:8095/index.html
 */
import { chromium } from '@playwright/test';

const BASE = process.argv[2] || 'http://127.0.0.1:8095/index.html';
const EPC = process.env.BENCH_EPC || 'private/drogon.epc';
const WELLS = ['55/33-1', '55/33-A-1', '55/33-A-4'];
const LOG = process.env.FLIGHT_LOG || 'Relative AI Near (Depth, 2018)';
const SKIP_VALUES = !!process.env.FLIGHT_ONLY;
const t0 = Date.now();
const log = (...a) => process.stderr.write(String(Date.now() - t0).padStart(7) + ' ' + a.join(' ') + '\n');
const out = {};
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');

const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 950 } })).newPage();
page.on('pageerror', (e) => log('PAGEERROR', e.message.slice(0, 200)));
const state = (k) => page.evaluate((key) => {
  const s = window.trame && window.trame.state;
  if (!s) return null;
  const v = s.get ? s.get(key) : (s.state || {})[key];
  return v === undefined ? null : JSON.parse(JSON.stringify(v));
}, k);
const until = async (what, test, timeout = 300000) => {
  const start = Date.now();
  while (!(await test())) {
    if (Date.now() - start > timeout) throw new Error(what + ': not within ' + timeout / 1000 + ' s');
    await page.waitForTimeout(200);
  }
};

try {
  await page.goto(BASE + '?epc=' + encodeURIComponent(EPC), { waitUntil: 'domcontentloaded' });
  await page.locator('.dv-tab').first().waitFor({ timeout: 180000 });
  await until('the file read', async () => !!(await state('ui_has_data')) && !((await state('ui_load_progress')) || {}).running);
  const door = page.locator('.up-dialog');
  for (let i = 0; i < 60 && await door.isVisible().catch(() => false); i += 1) {
    await door.locator('.fp-dialog-head button[title="Close"]').click({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(500);
  }
  const panel = page.locator('.dv-vue-part').filter({ has: page.locator('img') }).first();
  const img = panel.locator('img').first();
  await img.waitFor({ timeout: 60000 });
  await img.evaluate((el) => {
    window.__frames = [];
    window.__sizes = [];
    new MutationObserver(() => {
      window.__frames.push(performance.now());
      const i = window.__frames.length - 1;
      fetch(el.src).then((r) => r.blob()).then((b) => { window.__sizes[i] = b.size; }).catch(() => {});
    }).observe(el, { attributes: true, attributeFilter: ['src'] });
  });
  const frames = () => page.evaluate(() => window.__frames.length);
  const lastFrame = () => page.evaluate(() => window.__frames[window.__frames.length - 1] || 0);
  const now = () => page.evaluate(() => performance.now());
  const settled = async (ms = 2500, timeout = 120000) => {
    const start = Date.now();
    for (;;) {
      if ((await now()) - (await lastFrame()) > ms || Date.now() - start > timeout) return;
      await page.waitForTimeout(200);
    }
  };

  // the Well family card of the 3D view
  const view = page.locator('.dv-vue-part:visible').filter({ has: page.locator('[id^="fc-rb-"]') }).first();
  const card = view.locator('.fc:visible').filter({ has: page.locator('.fc-title', { hasText: /^Well$/ }) }).first();
  if (!(await card.count())) {
    await view.locator('.tb .tb-btn:visible[title^="Well"]').first().click();
    await card.waitFor({ state: 'visible', timeout: 15000 });
  }
  const tree = card.locator('.fdx').first();
  const expandAll = async () => {
    for (let i = 0; i < 12; i += 1) {
      const n = await tree.evaluate((root) => {
        const closed = [...root.querySelectorAll('.tn-caret')].filter((e) => e.textContent.trim() === '▸');
        closed.forEach((e) => e.click()); return closed.length;
      });
      if (!n) return;
      await page.waitForTimeout(300);
    }
  };
  const row = (title, under) => {
    const rows = tree.locator('.tn-row').filter({ has: page.locator('.tn-title', { hasText: new RegExp('^' + esc(title) + '$') }) });
    return under === undefined ? rows.first() : rows.nth(under);
  };
  const yes = page.locator('.fp-dialog-foot button.fp-primary').first();
  for (const well of WELLS) {
    const before = ((await state('ui_loaded_rep_paths')) || []).length;
    await row(well).locator('.tn-check').click({ timeout: 20000 });
    await until(well + ' read', async () => {
      if (await yes.isVisible().catch(() => false)) await yes.click().catch(() => {});
      return ((await state('ui_loaded_rep_paths')) || []).length > before && !((await state('ui_load_progress')) || {}).running;
    });
    log(well, 'read');
  }
  await settled();
  await expandAll();
  // the log of the last well: the one under 55/33-A-4 (the third row of that title)
  const logRows = tree.locator('.tn-row').filter({ has: page.locator('.tn-title', { hasText: new RegExp('^' + esc(LOG) + '$') }) });
  const nLogs = await logRows.count();
  // the last one READ (its box ticked): the log of the last well read, 55/33-A-4
  const ticked = await logRows.evaluateAll((rows) => rows.map((r) => (r.querySelector('.tn-check') || {}).textContent === '☑'));
  const logRow = logRows.nth(ticked.lastIndexOf(true));
  log(nLogs + ' rows titled ' + LOG + ', read: ' + ticked.map((t) => (t ? 'x' : '.')).join(''));
  await page.screenshot({ path: 'out/flight_values_before.png' });

  const flight = async (key, label) => {
    await settled(1500);
    await logRow.locator('.tn-title').first().click({ button: 'right' });
    const item = page.locator('.fdx-ctx .fp-menu-item', { hasText: new RegExp('^' + label) }).first();
    await item.waitFor({ state: 'visible', timeout: 10000 });
    const f0 = await frames();
    const g0 = await now();
    await item.click();
    await until(key + ': a first image', async () => (await frames()) > f0, 15000).catch(() => {});
    await settled(2500);
    const last = await lastFrame();
    const f1 = await frames();
    out[key + '_frames'] = f1 - f0;
    out[key + '_s'] = Math.round(Math.max(0, last - g0) / 100) / 10;
    const sizes = (await page.evaluate(([a, b]) => window.__sizes.slice(a, b), [f0, f1])).filter((x) => x);
    out[key + '_kb'] = Math.round(sizes.reduce((x, y) => x + y, 0) / 1024);
    out[key + '_at_ms'] = (await page.evaluate(([a, b]) => window.__frames.slice(a, b), [f0, f1])).map((t) => Math.round(t - g0));
    log(key, out[key + '_frames'] + ' images,', 'last one after', out[key + '_s'] + ' s,', out[key + '_kb'] + ' KB in all');
  };
  {
    await settled(1500);
    const box = await img.boundingBox();
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
    const f0 = await frames();
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    for (let i = 1; i <= 20; i += 1) { await page.mouse.move(cx + i * 8, cy + i * 3); await page.waitForTimeout(50); }
    await page.mouse.up();
    await settled(2500);
    const f1 = await frames();
    const sizes = (await page.evaluate(([a, b]) => window.__sizes.slice(a, b), [f0, f1])).filter((x) => x);
    out.rotate_frames = f1 - f0;
    out.rotate_kb_each = sizes.length ? Math.round(sizes.reduce((x, y) => x + y, 0) / sizes.length / 1024) : null;
    out.still_kb = sizes.length ? Math.round(sizes[sizes.length - 1] / 1024) : null;
    log('rotate', out.rotate_frames + ' images,', out.rotate_kb_each + ' KB each, the still one ' + out.still_kb + ' KB');
  }
  if (!process.env.SKIP_FLIGHT) {
    await flight('centre', 'Center the 3D view on');
    await flight('zoom', 'Zoom the 3D view on');
  }
  await page.screenshot({ path: 'out/flight_values_flown.png' });

  if (!SKIP_VALUES) {
    // the log active, the Values view, the Well log holding its well
    await logRow.locator('.tn-title').first().click();
    await page.waitForTimeout(1500);
    const values = page.locator('.fap');
    if (!(await values.first().isVisible().catch(() => false))) {
      await page.locator('header button[title^="Values"]').first().click();
    }
    await values.first().waitFor({ state: 'visible', timeout: 60000 });
    await logRow.locator('.tn-title').first().click({ button: 'right' });
    await page.locator('.fdx-ctx .fp-menu-item', { hasText: /^Add to Well Log view/ }).first().click();
    await until('the well in the log', async () => ((await state('ui_welllog_wells')) || []).length > 0, 60000);
    await page.waitForTimeout(4000);
    const vrow = values.locator('tbody tr').nth(40);
    await vrow.waitFor({ state: 'visible', timeout: 30000 });
    // a row under the pointer (no real mouse move: nothing leaves the table after)
    const wl = page.locator('.well-log-correlation').first();
    const marks = () => wl.evaluate((el) => {
      const H = el.__wlc && el.__wlc.hover;
      return H ? { crosses: H.crosses.childElementCount, shown: H.cursor.style.display !== 'none', top: el.scrollTop } : null;
    });
    out.log_view_before_hover = await marks();
    await vrow.dispatchEvent('pointerenter');
    await page.waitForTimeout(2500);
    out.log_pointer = await state('ui_log_pointer');
    out.log_view_hovered = await marks();
    log('Values row hovered: pointer', JSON.stringify(out.log_pointer), 'log view', JSON.stringify(out.log_view_hovered));
    await page.screenshot({ path: 'out/values_hover_log.png' });
    // the 3D view in front (its tab), the row still under the pointer
    await page.locator('.dv-tab', { hasText: /^3D view 1/ }).first().dispatchEvent('click').catch(() => {});
    await page.locator('.dv-tab', { hasText: /3D view/ }).first().click().catch(() => {});
    await page.waitForTimeout(2500);
    await page.screenshot({ path: 'out/values_hover_3d.png' });
    await page.locator('.dv-tab', { hasText: /^Well log/ }).first().click().catch(() => {});
    await page.waitForTimeout(1500);
    // the log view zoomed in and scrolled to its top: the sample clicked stands out of sight
    const wbox = await wl.boundingBox();
    await page.mouse.move(wbox.x + wbox.width / 2, wbox.y + wbox.height / 2);
    for (let i = 0; i < 10; i += 1) { await page.mouse.wheel(0, -240); await page.waitForTimeout(150); }
    await page.waitForTimeout(1500);
    await wl.evaluate((el) => { el.scrollTop = 0; });
    await page.mouse.move(5, 5);
    await page.waitForTimeout(800);
    out.log_view_zoomed = await marks();
    await vrow.dispatchEvent('pointerdown');
    await page.waitForTimeout(3000);
    out.values_row_selected = await values.locator('tbody tr.fap-sel').count();
    out.log_view_lit = await state('ui_log_lit');
    out.log_view_after_click = await marks();
    // the sample held: a magenta dot on its curve in the log view
    out.log_view_held_dots = await wl.evaluate((el) => el.querySelectorAll('circle[fill="#ff00ff"]').length);
    out.log_view_header = await page.locator('.wlp .fp-bar').count();
    out.log_view_height = await wl.evaluate((el) => [el.clientHeight, el.scrollHeight]);
    log('Values row clicked: selected', out.values_row_selected, 'log view lit', JSON.stringify(out.log_view_lit));
    await page.screenshot({ path: 'out/flight_values_lit.png' });
  }
  out.ok = true;
} catch (e) {
  out.ok = false;
  out.error = String(e.message || e).slice(0, 300);
  log('FAILED', out.error);
  await page.screenshot({ path: 'out/flight_values_failed.png' }).catch(() => {});
}
await browser.close();
process.stdout.write(JSON.stringify(out) + '\n');
