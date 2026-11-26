// A frustum selection ("through the volume") on the smoke file's grid: the
// readout must name cells, not "(no cell selected)" (the PO, 15/10). The
// server log says what the frustum walked when it finds nothing.
// OLYMPUS=1: the small Olympus IJK grid, with the Slicers card open (its
// grid is then drawn by the slicer's crops, not by the composite).
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';
import { DATASET } from '../lib/dataset.mjs';
import { M } from '../lib/markers.mjs';
const olympus = !!process.env.OLYMPUS;
const ijkEpc = path.join(path.dirname(DATASET.files[0]), 'olympus', 'OlympusGridAndProp.epc');
// VOLVE=1: the Volve demo grid (data/private), the PO's case of 15/10;
// TICK=<regex> the tree row ticked (default: the first title matching /grid/i)
const volve = !!process.env.VOLVE;
const volveEpc = path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Reservoir_Grid_Depth.epc');
const withH5 = (epc) => [epc, ...(fs.existsSync(epc.replace(/\.epc$/i, '.h5')) ? [epc.replace(/\.epc$/i, '.h5')] : [])];
const files = olympus ? withH5(ijkEpc) : volve ? withH5(volveEpc) : DATASET.files;
const url = process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8095/';
const state = (page, k) => page.evaluate((key) => { const s = window.trame && window.trame.state; return s && s.get ? s.get(key) : null; }, k);
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
await page.locator(M.importClose).click({ force: true, timeout: 5000 }).catch(() => {});
await page.waitForTimeout(2000);
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
const prop = olympus ? '^Porosity$' : volve ? (process.env.TICK || 'grid') : '^' + DATASET.properties[0] + '$';
if (volve) console.log('rows:', (await page.locator(M.treeTitle).allTextContents()).slice(0, 40).join(' | '));
const row = page.locator(M.treeRow).filter({ has: page.locator(M.treeTitle, { hasText: new RegExp(prop, 'i') }) }).first();
console.log('tick:', await row.locator(M.treeTitle).first().textContent());
await row.locator(M.treeCheck).dispatchEvent('click');
for (let i = 0; i < 120 && !((await state(page, 'ui_loaded_array_paths')) || []).length; i++) await page.waitForTimeout(500);
await page.waitForTimeout(3000);
if (olympus) {
  await page.locator('.tb-btn[title="Slicers"]').first().click({ force: true });
  await page.waitForTimeout(4000);
  console.log('slicer mode:', ((await state(page, 'ui_slicers__view_1')) || {}).mode);
}
const mode = process.env.PICK_MODE || 'frustum';
await page.evaluate((m) => window.trame.state.set(m === 'frustum' ? 'ui_frustum_mode__view_1' : 'ui_pick_mode__view_1', true), mode);
await page.waitForTimeout(1000);
const canvas = page.locator('canvas').first();
const box = await canvas.boundingBox();
const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
await page.mouse.move(cx - 150, cy - 100);
await page.mouse.down();
await page.mouse.move(cx, cy, { steps: 5 });
await page.mouse.move(cx + 150, cy + 100, { steps: 5 });
await page.mouse.up();
// a frustum through a large grid takes its time: wait for the readout
for (let i = 0; i < 60 && !(await state(page, 'ui_pick_info__view_1')); i++) await page.waitForTimeout(1000);
console.log(mode, 'readout:', await state(page, 'ui_pick_info__view_1'));
await page.screenshot({ path: 'out/ui-frustum.png' });
await browser.close();
