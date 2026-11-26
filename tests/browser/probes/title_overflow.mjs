/*
 * Probe: does a 3D view's title strip overflow its tabs when the view's
 * group is narrow (two groups side by side)?
 *
 * Opens a second 3D view (a copy of the first) in a narrow window, then
 * measures, for every tab row, the tabs container and the strip (.t3): their
 * boxes, whether the strip's right edge passes the row, whether the strip
 * covers the tabs, and screenshots the top of the page.
 *
 *   .\tests\browser\instance.ps1 -Epc drogon.epc     (the container, drogon open)
 *   node probes/title_overflow.mjs [url] [width]      (width: the window, 1100 by default)
 */
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://localhost:8095/index.html';
const WIDTH = Number(process.argv[3] || 1100);
const OUT = process.env.FESPP_PROBE_OUT || 'out';
const log = (...a) => console.log(...a);

const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: WIDTH, height: 720 } })).newPage();
page.on('pageerror', (e) => log('PAGEERROR', e.message.slice(0, 200)));
await page.goto(URL, { waitUntil: 'domcontentloaded' });
await page.locator('canvas').first().waitFor({ timeout: 60000 });
await page.waitForTimeout(3000);

async function measure(tag) {
  const rows = await page.evaluate(() => {
    // the strip (.t3) is not a child of the tab row: the panel lifts it over
    // the row (render_panel.py), so each strip is matched with the tab row of
    // its own group (the closest .dv-groupview)
    const out = [];
    for (const strip of document.querySelectorAll('.t3')) {
      // the tab row of the strip's group: the one whose span holds the strip
      const s = strip.getBoundingClientRect();
      const row = [...document.querySelectorAll('.dv-tabs-and-actions-container')].find((el) => {
        const b = el.getBoundingClientRect(); return b.x - 1 <= s.x && s.right <= b.right + 200 && Math.abs(b.y - s.y) < 40; });
      const r = row ? row.getBoundingClientRect() : null;
      const lastTab = row ? [...row.querySelectorAll('.dv-tab')].pop() : null;
      const lt = lastTab ? lastTab.getBoundingClientRect() : null;
      const btns = [...strip.querySelectorAll('button, .fp-sel')];
      out.push({
        row: r ? [Math.round(r.x), Math.round(r.right)] : null,
        lastTabRight: lt ? Math.round(lt.right) : null,
        strip: [Math.round(s.x), Math.round(s.right), Math.round(s.width)],
        stripPastRow: r ? Math.round(s.right - r.right) : null,
        stripOverTabs: lt ? Math.round(lt.right - s.x) : null,
        buttons: btns.length,
        zoom: [...strip.querySelectorAll('.t3-zoom')].map((el) => getComputedStyle(el).display).join('/'),
        axes: [...strip.querySelectorAll('.t3-axes')].map((el) => getComputedStyle(el).display).join('/'),
        cqSupport: CSS.supports('container-type: inline-size'),
        ancestors: (() => { const out = []; let w = strip.parentElement;
          for (let i = 0; i < 4 && w; i++, w = w.parentElement) { const b = w.getBoundingClientRect(); const cs = getComputedStyle(w);
            out.push([w.tagName.toLowerCase(), Math.round(b.x), Math.round(b.right), cs.getPropertyValue('container-type') || '-', cs.position]); }
          return out; })(),
        hidden: [...strip.querySelectorAll('[class*="t3-"]')].filter((el) => getComputedStyle(el).display === 'none')
          .map((el) => el.className.split(' ').filter((c) => c.startsWith('t3-') && c !== 't3-btn').join('.')).join(','),
        buttonsInsideRow: r ? btns.filter((b) => { const bb = b.getBoundingClientRect(); return bb.width > 0 && bb.right <= r.right + 1 && bb.x >= r.x - 1; }).length : null,
      });
    }
    return out;
  });
  log(tag + ':', JSON.stringify(rows));
  mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: `${OUT}/title_overflow_${tag}.png`, clip: { x: 0, y: 0, width: WIDTH, height: 90 } });
}

await measure('one_view_' + WIDTH);
// a second view, a copy of the first, opens beside it: two groups side by side
await page.locator('header button[title="New 3D view"]').click();
const dialog = page.locator('.fnv');
await dialog.waitFor({ timeout: 15000 });
await dialog.locator('.fp-segbtn', { hasText: 'Copy a view' }).click();
await dialog.locator('button', { hasText: /^Open$/ }).click();
await dialog.waitFor({ state: 'hidden', timeout: 15000 });
await page.waitForTimeout(4000);
await measure('two_views_' + WIDTH);
await browser.close();
