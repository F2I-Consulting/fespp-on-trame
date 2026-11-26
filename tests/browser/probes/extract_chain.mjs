// A selection made THROUGH the volume on an extract (the PO, 15/10): it
// must count the extract's cells only, not the hidden grid behind it, and
// "Remove" must take them out of that extract.
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
await page.locator('.tb-btn[title^="Select cells"]').first().click({ force: true });
await page.waitForTimeout(600);
await page.locator('.tb-btn.tb-sub').first().click({ force: true });   // through the volume
await page.waitForTimeout(600);
const box = await page.locator('canvas').first().boundingBox();
const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
const drag = async (x0, y0, x1, y1) => {
  await page.mouse.move(x0, y0); await page.mouse.down();
  await page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, { steps: 4 });
  await page.mouse.move(x1, y1, { steps: 4 }); await page.mouse.up();
  await page.waitForTimeout(2500);
};
const counts = async () => Object.values((await state(page, 'ui_sel_counts__view_1')) || {})[0] || 0;
const plus = async (mode) => {
  await page.waitForTimeout(300);
  await page.locator('.tn-pick', { hasText: new RegExp('^' + mode + '$') }).first().click({ force: true });
  await page.waitForTimeout(3000);
};
await drag(cx - 60, cy - 300, cx + 60, cy);       // the upper half of the column
const k1 = await counts();
await plus('Keep');
const r1 = (await state(page, 'ui_session_rows__view_1')) || [];
console.log('1st selection', k1, '->', r1.map((r) => r.title).join(' | '));
await drag(cx - 60, cy - 400, cx + 60, cy + 400);  // across everything: only the extract's cells count
const k2 = await counts();
console.log('2nd selection over the whole view:', k2, '(the extract holds', k1, ')');
await drag(cx - 60, cy - 300, cx + 60, cy - 150); // a part of the extract
const k3 = await counts();
await plus('Remove');
const r2 = (await state(page, 'ui_session_rows__view_1')) || [];
console.log('3rd selection', k3, '->', r2.map((r) => r.title + (r.visible ? ' [shown]' : ' [hidden]')).join(' | '));
await page.screenshot({ path: 'out/ui-extract-chain.png' });
await browser.close();
