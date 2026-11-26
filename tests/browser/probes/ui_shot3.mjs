// The XML View on a property, its Tree then its Graph reading: a look at the
// reference chips that open their object.
import { chromium } from '@playwright/test';
import { DATASET } from '../lib/dataset.mjs';
import { M } from '../lib/markers.mjs';
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
await page.setInputFiles(M.fileInput, DATASET.files);
for (let i = 0; i < 240 && !(await state(page, 'ui_has_data')); i++) await page.waitForTimeout(500);
await page.locator(M.importClose).click({ force: true, timeout: 5000 }).catch(() => {});
await page.waitForTimeout(2000);
const prop = DATASET.properties[0];
const row = page.locator(M.treeRow).filter({ has: page.locator(M.treeTitle, { hasText: new RegExp('^' + prop + '$') }) }).first();
// expand every closed caret, as lib/app.mjs expandTree does, in the data tree
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
await row.click({ button: 'right', force: true });
await page.locator(M.ctxItem, { hasText: /^Explore the XML$/ }).click({ force: true });
await page.waitForTimeout(4000);
await page.screenshot({ path: 'out/ui-xml-tree.png' });
await page.locator('.fp-seg button, .fp-seg-btn', { hasText: /^Graph$/ }).first().click({ force: true }).catch((e) => console.log('graph:', String(e).slice(0, 80)));
await page.waitForTimeout(3000);
await page.screenshot({ path: 'out/ui-xml-graph.png' });
console.log('links:', await page.locator('.fx-link').count());
await browser.close();
