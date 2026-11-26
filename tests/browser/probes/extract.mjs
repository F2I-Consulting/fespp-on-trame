// A selection kept as an extract (the PO, 15/10): cells highlighted on the
// Olympus grid, its tree row's "+" -> Keep, then the extract's eye and x.
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';
import { DATASET } from '../lib/dataset.mjs';
import { M } from '../lib/markers.mjs';
const url = process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8095/';
const mode = process.env.MODE || 'Keep';
const state = (page, k) => page.evaluate((key) => { const s = window.trame && window.trame.state; return s && s.get ? s.get(key) : null; }, k);
// VOLVE=1: the Volve demo grid, PROP=<title> the property ticked
const volve = !!process.env.VOLVE;
const epc = volve ? path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Reservoir_Grid_Depth.epc')
  : path.join(path.dirname(DATASET.files[0]), 'olympus', 'OlympusGridAndProp.epc');
const prop = process.env.PROP || (volve ? 'Fluids' : 'Porosity');
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
await row(new RegExp('^' + prop + '$')).locator(M.treeCheck).dispatchEvent('click');
for (let i = 0; i < 120 && !((await state(page, 'ui_loaded_array_paths')) || []).length; i++) await page.waitForTimeout(500);
await page.waitForTimeout(volve ? 8000 : 2000);
await page.screenshot({ path: 'out/ui-extract-before.png' });
// select a rectangle of cells on the surface
await page.locator('.tb-btn[title^="Select cells"]').first().click({ force: true });
await page.waitForTimeout(800);
// PICK=volume: the group's switch, through the volume
if (process.env.PICK === 'volume') {
  await page.locator('.tb-btn.tb-sub').first().click({ force: true });
  await page.waitForTimeout(800);
}
const box = await page.locator('canvas').first().boundingBox();
const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
await page.mouse.move(cx - 30, cy - 120);
await page.mouse.down();
await page.mouse.move(cx + 30, cy - 20, { steps: 5 });
await page.mouse.up();
for (let i = 0; i < 30 && !Object.keys((await state(page, 'ui_sel_counts__view_1')) || {}).length; i++) await page.waitForTimeout(500);
console.log('counts:', JSON.stringify(await state(page, 'ui_sel_counts__view_1')));
await page.waitForTimeout(300);
await page.locator('.tn-pick', { hasText: new RegExp('^' + mode + '$') }).first().click({ force: true });
for (let i = 0; i < 30 && !((await state(page, 'ui_session_rows__view_1')) || []).length; i++) await page.waitForTimeout(500);
await page.waitForTimeout(2000);
console.log('rows:', JSON.stringify(await state(page, 'ui_session_rows__view_1')));
console.log('note:', await state(page, 'ui_pick_info__view_1'));
await page.screenshot({ path: 'out/ui-extract-' + mode.toLowerCase() + '.png' });
// the extract's eye: the grid comes back
await page.locator('.tn-row', { has: page.locator('.tn-session') }).locator('.tn-eye').first().click({ force: true });
await page.waitForTimeout(2500);
console.log('after eye:', JSON.stringify(((await state(page, 'ui_session_rows__view_1')) || []).map((r) => r.visible)));
await page.screenshot({ path: 'out/ui-extract-hidden.png' });
await page.locator('.tn-row', { has: page.locator('.tn-session') }).locator('.tn-x').first().click({ force: true });
await page.waitForTimeout(2000);
console.log('after x:', JSON.stringify(await state(page, 'ui_session_rows__view_1')));
await browser.close();
