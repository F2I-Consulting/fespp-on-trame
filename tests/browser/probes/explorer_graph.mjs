// The Explorer's Graph reading on Volve's reservoir grid: the series folded
// into one box per property (GasSat · TS ×N), a series opened, the raw XML of
// two members read beside the graph, the first pinned. A look, not an
// assertion. Start the instance on the file first:
//   .\tests\browser\instance.ps1 -Epc Volve_Demo_Reservoir_Grid_Depth.epc
//   cd tests\browser; node probes\explorer_graph.mjs
import { chromium } from '@playwright/test';
import { M } from '../lib/markers.mjs';
const url = process.env.FESPP_SMOKE_URL || 'http://127.0.0.1:8095/';
const state = (page, k) => page.evaluate((key) => { const s = window.trame && window.trame.state; return s && s.get ? s.get(key) : null; }, k);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
await page.goto(url);
await page.locator(M.dockTab).first().waitFor({ timeout: 180000 });
for (let i = 0; i < 240 && !(await state(page, 'ui_has_data')); i++) await page.waitForTimeout(500);
await page.locator(M.importClose).click({ force: true, timeout: 3000 }).catch(() => {});
await page.waitForTimeout(1500);
await page.locator('header button[title^="Explorer"]').first().click({ force: true });
await page.waitForTimeout(2500);
await page.locator('.fxv-find-in input, input.fxv-find-in, .fxv-find input').first().fill('GasSat');
await page.locator('.fxv-hit').first().waitFor({ timeout: 30000 });
await page.locator('.fxv-hit').first().click({ force: true });
await page.waitForTimeout(2500);
await page.locator('.fp-seg button, .fp-seg-btn', { hasText: /^Graph$/ }).first().click({ force: true });
await page.waitForTimeout(3000);
// the grid the property references: open it, its Graph shows the series
await page.locator('g.fxr-box-obj', { hasText: /IjkGrid/ }).first().click({ force: true });
await page.waitForTimeout(5000);
await page.screenshot({ path: 'out/ui-explorer-graph-grid.png' });
console.log('groups:', await page.locator('g.fxr-box-group').count(),
            'objects:', await page.locator('g.fxr-box-obj').count(),
            'more:', await page.locator('g.fxr-box-more').count());
console.log('group labels:', (await page.locator('g.fxr-box-group').allInnerTexts()).slice(0, 6).join(' | '));
await page.locator('g.fxr-box-group').first().click({ force: true });
await page.waitForTimeout(1500);
await page.screenshot({ path: 'out/ui-explorer-group-open.png' });
console.log('members:', await page.locator('g.fxr-box-member').count());
await page.locator('g.fxr-box-member').first().click({ button: 'right', force: true });
await page.waitForTimeout(2500);
await page.locator('.fxr-raw .fp-btn', { hasText: /^Pin$/ }).first().click({ force: true });
await page.waitForTimeout(1000);
await page.locator('g.fxr-box-member').nth(1).click({ button: 'right', force: true });
await page.waitForTimeout(2500);
console.log('raw panes:', await page.locator('.fxr-raw').count(),
            'pinned:', await page.locator('.fxr-raw-pinned').count());
await page.screenshot({ path: 'out/ui-explorer-raw.png' });
await browser.close();
