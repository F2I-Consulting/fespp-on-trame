/*
 * Probe: the rows of each family tree card (Reservoir, Surface, Well,
 * Seismic) of a file opened by the page's query, every node expanded: what a
 * bench can tick by its title.
 *
 *   node probes/tree_dump.mjs http://localhost:8095/index.html private/x.epc
 */
import { chromium } from '@playwright/test';

const BASE = process.argv[2];
const EPC = process.argv[3];
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1500, height: 950 } })).newPage();
const state = (k) => page.evaluate((key) => {
  const s = window.trame && window.trame.state;
  if (!s) return null;
  const v = s.get ? s.get(key) : (s.state || {})[key];
  return v === undefined ? null : JSON.parse(JSON.stringify(v));
}, k);
await page.goto(BASE + '?epc=' + encodeURIComponent(EPC), { waitUntil: 'domcontentloaded' });
await page.locator('.dv-tab').first().waitFor({ timeout: 180000 });
for (let i = 0; i < 600 && !((await state('ui_has_data')) && !((await state('ui_load_progress')) || {}).running); i++) {
  await page.waitForTimeout(500);
}
const door = page.locator('.up-dialog');
for (let i = 0; i < 40 && await door.isVisible().catch(() => false); i++) {
  await door.locator('.fp-dialog-head button[title="Close"]').click({ timeout: 2000 }).catch(() => {});
  await page.waitForTimeout(500);
}
const view = page.locator('.dv-vue-part:visible').filter({ has: page.locator('[id^="fc-rb-"]') }).first();
for (const name of ['Reservoir', 'Surface', 'Well', 'Seismic']) {
  const button = view.locator('.tb .tb-btn:visible[title^="' + name + '"]').first();
  if (!(await button.count()) || await button.isDisabled()) continue;
  const card = view.locator('.fc:visible').filter({ has: page.locator('.fc-title', { hasText: new RegExp('^' + name + '$') }) }).first();
  if (!(await card.count())) { await button.click(); await card.waitFor({ state: 'visible', timeout: 15000 }).catch(() => {}); }
  const tree = card.locator('.fdx').first();
  for (let i = 0; i < 12; i++) {
    const n = await tree.evaluate((root) => {
      const closed = [...root.querySelectorAll('.tn-caret')].filter((e) => e.textContent.trim() === '▸');
      closed.forEach((e) => e.click()); return closed.length;
    }).catch(() => 0);
    if (!n) break;
    await page.waitForTimeout(300);
  }
  const rows = await tree.evaluate((root) => [...root.querySelectorAll('.tn-row')].map((r) => {
    const t = r.querySelector('.tn-title');
    return (r.querySelector('.tn-check') ? '[x] ' : '    ') + (t ? t.innerText.trim() : '?');
  })).catch(() => []);
  const bulk = await tree.locator('.fdx-select-btn').click().then(() => tree.locator('.fdx-select .fdx-menu-item').allInnerTexts()).catch(() => []);
  await page.keyboard.press('Escape').catch(() => {});
  console.log('== ' + name + ': ' + rows.length + ' rows; Select menu: ' + bulk.map((b) => b.trim()).join(' | '));
  console.log(rows.slice(0, 40).join('\n'));
  await button.click().catch(() => {});
}
await browser.close();
