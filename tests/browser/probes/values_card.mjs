// The view toolbar's icons and the Values card on a GEOMETRY node (the
// Olympus IJK grid): its cells with I J K and centres, then its points.
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';
import { DATASET } from '../lib/dataset.mjs';
import { M } from '../lib/markers.mjs';
const url = process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8095/';
const state = (page, k) => page.evaluate((key) => { const s = window.trame && window.trame.state; return s && s.get ? s.get(key) : null; }, k);
const epc = path.join(path.dirname(DATASET.files[0]), 'olympus', 'OlympusGridAndProp.epc');
const files = [epc, ...(fs.existsSync(epc.replace(/\.epc$/i, '.h5')) ? [epc.replace(/\.epc$/i, '.h5')] : [])];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
await page.goto(url);
await page.locator(M.dockTab).first().waitFor({ timeout: 180000 });
await page.waitForTimeout(2000);
if (!(await page.locator('.up-sources').isVisible().catch(() => false))) {
  await page.locator(M.topBarButton, { hasText: /import data/i }).first().click({ force: true });
}
await page.setInputFiles(M.fileInput, files);
for (let i = 0; i < 240 && !(await state(page, 'ui_has_data')); i++) await page.waitForTimeout(500);
await page.waitForTimeout(3000);
console.log('import dialog still open:', await page.locator('.up-dialog').count());
const tree = page.locator(M.dockPart).filter({ has: page.locator('canvas') }).locator(M.tree).first();
for (let i = 0; i < 12; i += 1) {
  const n = await tree.evaluate((root, caret) => {
    const closed = [...root.querySelectorAll('.tn-caret')].filter((e) => e.textContent.trim() === caret);
    closed.forEach((e) => e.click());
    return closed.length;
  }, M.caretCollapsed);
  if (!n) break;
  await page.waitForTimeout(400);
}
const row = (re) => page.locator(M.treeRow).filter({ has: page.locator(M.treeTitle, { hasText: re }) }).first();
await row(/^Porosity$/).locator(M.treeCheck).dispatchEvent('click');
for (let i = 0; i < 120 && !((await state(page, 'ui_loaded_array_paths')) || []).length; i++) await page.waitForTimeout(500);
await page.waitForTimeout(2000);
await row(/^Sector$/).locator(M.treeTitle).first().click({ force: true });
await page.waitForTimeout(1500);
await page.locator('.tb-btn[title="Values"]').first().click({ force: true });
await page.waitForTimeout(4000);
await page.screenshot({ path: 'out/ui-values-cells.png' });
const v = ((await state(page, 'ui_node_values_by_view')) || {}).view_1 || {};
console.log('cells:', JSON.stringify(v.columns), JSON.stringify((v.rows || [])[0]));
await page.locator('.fap-assoc button, .fp-seg button', { hasText: /^Points$/ }).first().click({ force: true });
await page.waitForTimeout(3000);
const w = ((await state(page, 'ui_node_values_by_view')) || {}).view_1 || {};
console.log('points:', JSON.stringify(w.columns), JSON.stringify((w.rows || [])[0]), w.count);
await page.screenshot({ path: 'out/ui-values-points.png' });
await browser.close();
