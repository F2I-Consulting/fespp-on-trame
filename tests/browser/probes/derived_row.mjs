// A derived property listed in the tree (the PO, 15/10): a recipe as the
// calculator publishes it (ui_derived_props) must hang under its grid's
// "properties", drawn as a session row.
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
const geom = await page.locator(M.treeRow).filter({ has: page.locator(M.treeTitle, { hasText: /^geometry$/ }) }).first().getAttribute('data-path');
await page.evaluate((rep) => window.trame.state.set('ui_derived_props', [{
  path: 'derived://' + rep + '#PhiTwice', rep_path: rep, rep_title: 'Sector', name: 'PhiTwice',
  expression: 'Porosity * 2', uom: '', prop_kind: '', type: 'expr', quantile: null, role: '',
  stale: false, error: '' }]), geom);
await page.waitForTimeout(2500);
console.log('rows:', JSON.stringify(await state(page, 'ui_session_rows__view_1')));
await page.screenshot({ path: 'out/ui-derived-row.png', clip: { x: 40, y: 100, width: 380, height: 440 } });
await browser.close();
