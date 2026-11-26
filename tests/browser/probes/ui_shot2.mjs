// The XML explorer opened from its toolbar door, beside the 3D view: two
// dockview tabs, the XML View in use; then the 3D view back in use.
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
await page.locator('header button[title^="Explorer"]').first().click({ force: true });
await page.waitForTimeout(4000);
await page.screenshot({ path: 'out/ui-shot-xml.png' });
console.log('tabs:', (await page.locator(M.dockTab).allInnerTexts()).join(' | '));
await page.locator(M.dockTab, { hasText: /^3D view/ }).first().click({ force: true });
await page.waitForTimeout(2000);
await page.screenshot({ path: 'out/ui-shot-3d.png', clip: { x: 0, y: 60, width: 1600, height: 80 } });
await browser.close();
