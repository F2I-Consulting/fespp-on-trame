/*
 * One full-page screenshot of the chrome: the test file imported, a second
 * 3D view, then an XML View opened on a property from the tree's menu. For
 * a look at the dockview tabs and the XML View, not an assertion. Needs a
 * running instance (.\test-browser.ps1 -Scenario boot -Keep) and
 * FESPP_SMOKE_URL; writes out/ui-shot.png.
 */
import { chromium } from '@playwright/test';
import path from 'node:path';
import { DATASET } from '../lib/dataset.mjs';
import { M } from '../lib/markers.mjs';

const url = process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8095/';
const out = path.join(process.env.FESPP_SMOKE_OUT || 'out', 'ui-shot.png');
const state = (page, k) => page.evaluate((key) => {
  const s = window.trame && window.trame.state;
  return s && s.get ? s.get(key) : null;
}, k);
const until = async (fn, ms = 120000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await fn()) return; await new Promise((r) => setTimeout(r, 500)); }
  throw new Error('timeout');
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
await page.goto(url);
await page.locator(M.dockTab).first().waitFor({ timeout: 180000 });
if (!(await state(page, 'ui_has_data'))) {
  if (!(await page.locator('.up-sources').isVisible().catch(() => false))) {
    await page.locator(M.topBarButton, { hasText: /import data/i }).first().click({ force: true });
  }
  await page.setInputFiles(M.fileInput, DATASET.files);
  await until(() => state(page, 'ui_has_data'));
  await page.locator(M.importClose).click({ force: true, timeout: 5000 }).catch(() => {});
}
await page.locator(M.treeRow).first().waitFor();
const step = async (what, fn) => {
  try { await fn(); } catch (e) { console.log('step skipped:', what, '-', String(e).split(String.fromCharCode(10))[0]); }
};
// a second 3D view, then the XML View on the first property
await step('new view', async () => {
  await page.locator('header button[title^="New 3D view"]').first().click({ force: true, timeout: 5000 });
  await page.waitForTimeout(3000);
  const dlg = page.locator('.v-overlay--active button, .fp-scrim button').filter({ hasText: /right|split|ok|add/i }).first();
  if (await dlg.count()) await dlg.click({ force: true, timeout: 5000 });
  await page.waitForTimeout(3000);
});
await page.screenshot({ path: out.replace('.png', '-1.png') });
await step('expand tree', async () => {
  for (const c of await page.locator('.tn-caret').all()) { await c.click({ force: true, timeout: 2000 }).catch(() => {}); }
});
await step('xml view', async () => {
  const prop = DATASET.properties[0];
  const row = page.locator(M.treeRow).filter({ has: page.locator(M.treeTitle, { hasText: new RegExp('^' + prop + '$') }) }).first();
  await row.click({ button: 'right', force: true, timeout: 5000 });
  await page.locator(M.ctxItem, { hasText: /^Explore the XML$/ }).click({ force: true, timeout: 5000 });
  await page.waitForTimeout(5000);
});
await page.screenshot({ path: out });
console.log('screenshot ->', out);
await browser.close();
