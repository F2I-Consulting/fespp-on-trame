// The Stratigraphy panel on columns built from ADME (lutetia: dated; Volve:
// not dated), pushed into the state of a running instance: a look, not an
// assertion. Needs FESPP_SMOKE_URL and the JSON files from strati_cols.py.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import { DATASET } from '../lib/dataset.mjs';
import { M } from '../lib/markers.mjs';
const url = process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8095/';
const dir = process.env.STRATI_JSON_DIR;
const state = (page, k) => page.evaluate((key) => { const s = window.trame && window.trame.state; return s && s.get ? s.get(key) : null; }, k);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
await page.goto(url);
await page.locator(M.dockTab).first().waitFor({ timeout: 180000 });
await page.waitForTimeout(2000);
if (!(await page.locator('.up-sources').isVisible().catch(() => false))) {
  await page.locator(M.topBarButton, { hasText: /import data/i }).first().click({ force: true });
}
await page.setInputFiles(M.fileInput, DATASET.files);
for (let i = 0; i < 240 && !(await state(page, 'ui_has_data')); i++) await page.waitForTimeout(500);
await page.locator(M.importClose).click({ force: true, timeout: 5000 }).catch(() => {});
await page.waitForTimeout(1500);
await page.locator('header button[title^="Stratigraphy"]').first().click({ force: true });
await page.waitForTimeout(3000);
// [file, rank, image, how far down the chart to scroll, in px]
const shots = [['geosiris_lutetia_cols.json', /— eonothem$/, 'ui-strati-lutetia-eon.png', 1600],
               ['geosiris_lutetia_cols.json', /Cretaceous — stage$/, 'ui-strati-lutetia.png', 0],
               ['demo_Volve_cols.json', /./, 'ui-strati-volve.png', 3550]];
for (const [file, pick, out, down] of shots) {
  const cols = JSON.parse(fs.readFileSync(dir + '/' + file, 'utf8'));
  const want = cols.find((c) => pick.test(c.title)) || cols[0];
  // the rank is per panel, and a panel that chose none shows the FIRST:
  // the wanted rank goes first, no panel keeps a choice
  const ordered = [want, ...cols.filter((c) => c !== want)];
  await page.evaluate((c) => { window.trame.state.update({ ui_strati_columns: c, ui_strati_selected_by_view: {} }); }, ordered);
  await page.waitForTimeout(2500);
  await page.evaluate((y) => { const c = document.querySelector('.fst-chart'); if (c) c.scrollTop = y; }, down);
  await page.waitForTimeout(500);
  const panel = page.locator('.fst').first();
  await panel.screenshot({ path: 'out/' + out });
  console.log(out, 'blocks', await page.locator('.fst-blk').count(), 'holes', await page.locator('.fst-hole').count());
}
await browser.close();
