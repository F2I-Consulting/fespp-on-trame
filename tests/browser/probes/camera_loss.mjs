/*
 * Probe: does the scene vanish when the camera moves?
 *
 * The case it replays: a coloured grid and a well, the log's colour bar
 * unchecked in the Colormap card, then a camera move; the failure it looks
 * for is everything but the wellhead disappearing. It goes through the real
 * path (trame's remote view, its half-resolution interactive renders, the
 * still render on release) and measures the image before, during and after
 * each gesture: pixels drawn (off the background) and coloured pixels.
 *
 *   .\tests\browser\instance.ps1 -Epc drogon.epc     (the container, drogon open)
 *   node probes/camera_loss.mjs [url]
 *
 * The URL defaults to FESPP_SMOKE_URL, then to that instance.
 */
import { chromium } from '@playwright/test';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://localhost:8095/index.html';
const t0 = Date.now();
const ms = () => String(Date.now() - t0).padStart(6);
const log = (...a) => console.log(ms(), ...a);

const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1500, height: 950 } })).newPage();
page.on('pageerror', (e) => log('PAGEERROR', e.message.slice(0, 200)));
page.on('console', (m) => { if (m.type() === 'error') log('CONSOLE', m.text().slice(0, 200)); });

const state = (k) => page.evaluate((key) => {
  const s = window.trame && window.trame.state;
  if (!s) return null;
  const v = s.get ? s.get(key) : (s.state || {})[key];
  return v === undefined ? null : JSON.parse(JSON.stringify(v));
}, k);

const rpc = [];
let watchRpc = false;
page.on('websocket', (ws) => {
  log('ws ' + ws.url().slice(0, 80));
  ws.on('framesent', (f) => {
    if (!watchRpc) return;
    try {
      const txt = typeof f.payload === 'string' ? f.payload : f.payload.toString('utf8');
      rpc.push(txt.slice(0, 160));
    } catch (e) { rpc.push('<binary>'); }
  });
});
await page.goto(URL, { waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => window.trame && window.trame.state, null, { timeout: 60000 });
await page.waitForFunction(() => {
  const s = window.trame.state; const v = s.get ? s.get('ui_has_data') : s.state.ui_has_data; return !!v;
}, null, { timeout: 120000 });
log('data loaded');

// the 3D view's image (the remote view draws its frames into an <img>
// or a canvas: take whichever the panel holds)
const panel = page.locator('.dv-vue-part').filter({ has: page.locator('canvas, img') }).first();
await panel.waitFor({ timeout: 60000 });
log('render panel holds: ' + await panel.evaluate((p) => [...p.querySelectorAll('canvas, img')].map((e) => e.tagName + ' ' + e.className + ' ' + e.width + 'x' + e.height).join(' | ')));
const canvas = panel.locator('img').first();

async function measure(tag) {
  // the pixels of the view as the browser shows them
  const m = await canvas.evaluate((c) => {
    const w = c.naturalWidth || c.width, h = c.naturalHeight || c.height;
    const off = document.createElement('canvas'); off.width = w; off.height = h;
    const ctx = off.getContext('2d'); ctx.drawImage(c, 0, 0, w, h);
    const d = ctx.getImageData(0, 0, w, h).data;
    const r0 = d[0], g0 = d[1], b0 = d[2];
    let drawn = 0, coloured = 0;
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i], g = d[i + 1], b = d[i + 2];
      if (Math.abs(r - r0) > 8 || Math.abs(g - g0) > 8 || Math.abs(b - b0) > 8) drawn++;
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
      if (mx - mn > 40 && mx > 60) coloured++;
    }
    return { w, h, drawn, coloured };
  });
  log(tag + ': ' + JSON.stringify(m));
  return m;
}

// tick Facies then the well through the tree
const tree = page.locator('.dv-vue-part').filter({ has: page.locator('canvas') }).locator('.fdx').first();
async function expandAll() {
  for (let i = 0; i < 12; i += 1) {
    const n = await tree.evaluate((root) => {
      const closed = [...root.querySelectorAll('.tn-caret')].filter((e) => e.textContent.trim() === '▸');
      closed.forEach((e) => e.click()); return closed.length;
    });
    if (!n) return; await page.waitForTimeout(300);
  }
}
async function tick(title) {
  await expandAll();
  const row = tree.locator('.tn-row').filter({ has: page.locator('.tn-title', { hasText: new RegExp('^' + title.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&') + '$') }) }).first();
  await row.locator('.tn-check').click();
  log('ticked ' + title);
}
await tick('Facies');
await page.waitForFunction(() => {
  const s = window.trame.state; const v = s.get ? s.get('ui_loaded_array_paths') : s.state.ui_loaded_array_paths; return (v || []).length > 0;
}, null, { timeout: 120000 });
await page.waitForTimeout(4000);
await measure('grid coloured');

if (process.env.PROBE_WELL !== "0") {
await page.locator('.fdx-tab', { hasText: /^Well/ }).first().click();
await tick('55/33-A-4');
// the confirmation of a big read
const yes = page.locator('.fp-dialog-foot button.fp-primary').first();
try { await yes.click({ timeout: 8000 }); log('confirmed the read'); } catch (e) { log('no confirmation box'); }
await page.waitForFunction(() => {
  const s = window.trame.state; const v = s.get ? s.get('ui_loaded_rep_paths') : s.state.ui_loaded_rep_paths; return (v || []).length > 2;
}, null, { timeout: 180000 });
await page.waitForTimeout(6000);
await measure('grid + well');
}

// the log channel active: click its row title (the Colormap card edits it)
if (process.env.PROBE_WELL !== "0") {
await page.locator('.fdx-tab', { hasText: /^Well/ }).first().click();
await expandAll();
const channel = tree.locator('.tn-row').filter({ has: page.locator('.tn-check') })
  .filter({ has: page.locator('.tn-title', { hasText: /Coal Facies Indicator|CoalFaciesIndicator/ }) }).first();
if (await channel.count()) { await channel.locator('.tn-title').click(); log('log channel active'); }
await page.waitForTimeout(1500);
}

// the Colormap card: uncheck the bar
const vid = await page.evaluate(() => { const s = window.trame.state; const all = s.state || s; const k = Object.keys(all).find((x) => /^view_tools_/.test(x)); return k ? k.replace('view_tools_', '') : null; });
const tools = (await state('view_tools_' + vid)) || [];
const idx = tools.findIndex((t) => t.key === 'colormap');
const open = ((await state('ui_open_tools_by_view')) || {})[vid] || [];
if (!open.includes('colormap')) await page.locator('.tb .tb-btn').nth(idx).click().catch(() => {});
await page.waitForTimeout(1500);
const barBox = page.locator('.fcm-check input[type=checkbox]').first();
log('bar box present: ' + (await barBox.count()) + ' checked: ' + (await barBox.count() ? await barBox.isChecked() : 'n/a'));
if (process.env.PROBE_BAR !== "0" && await barBox.count()) { await barBox.evaluate((el) => { el.checked = false; el.dispatchEvent(new Event('change', { bubbles: true })); }); log('bar unchecked'); await page.waitForTimeout(3000); }
await measure('after bar unchecked');
log('bars on screen: ' + JSON.stringify(await page.evaluate(() => null)));
await page.evaluate(([v]) => window.trame.trigger('debug_scene_probe', [v, 'bars after uncheck']), [vid]);

// the camera: a drag on the canvas, then a wait for the still frame
const box = await canvas.boundingBox();
const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
const dbg = (tag) => page.evaluate(([v, g]) => window.trame.trigger('debug_scene_probe', [v, g]), [vid, tag]);
await dbg('before drag');
watchRpc = true;
await page.mouse.move(cx, cy);
await page.mouse.down();
for (let i = 1; i <= 12; i += 1) { await page.mouse.move(cx + i * 15, cy + i * 6); await page.waitForTimeout(60); }
await measure('during the drag');
await dbg('during drag');
await page.mouse.up();
log('camera dragged');
await page.waitForTimeout(3000);
await measure('after the drag');
await page.waitForTimeout(4000);
await measure('after the drag (7 s)');
await dbg('after drag');
watchRpc = false;
log('frames during the drag: ' + rpc.length);
for (const r of rpc.slice(0, 40)) log('  ' + r);
await page.screenshot({ path: 'out/camera_loss.png' });
await browser.close();
