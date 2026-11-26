/*
 * The Values view's Keep / Remove / Clear on a grid property's rows, clicked
 * with the mouse as a reader does (drogon.epc, Facies): what each click
 * changes, and whether something stands over the buttons.
 *
 *   node probes/values_keep.mjs http://127.0.0.1:8095/index.html
 */
import { chromium } from '@playwright/test';

const BASE = process.argv[2] || 'http://127.0.0.1:8095/index.html';
const EPC = process.env.BENCH_EPC || 'private/drogon.epc';
const t0 = Date.now();
const log = (...a) => process.stderr.write(String(Date.now() - t0).padStart(7) + ' ' + a.join(' ') + '\n');
const out = {};
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: Number(process.env.PROBE_W || 1600), height: 950 } })).newPage();
page.on('pageerror', (e) => log('PAGEERROR', e.message.slice(0, 200)));
page.on('console', (m) => { if (m.type() === 'error') log('CONSOLE', m.text().slice(0, 200)); });
const state = (k) => page.evaluate((key) => {
  const s = window.trame && window.trame.state;
  const v = s && (s.get ? s.get(key) : (s.state || {})[key]);
  return v === undefined ? null : JSON.parse(JSON.stringify(v));
}, k);
const until = async (what, test, timeout = 300000) => {
  const start = Date.now();
  while (!(await test())) {
    if (Date.now() - start > timeout) throw new Error(what + ': not within ' + timeout / 1000 + ' s');
    await page.waitForTimeout(200);
  }
};
try {
  await page.goto(BASE + '?epc=' + encodeURIComponent(EPC), { waitUntil: 'domcontentloaded' });
  await page.locator('.dv-tab').first().waitFor({ timeout: 180000 });
  await until('the file read', async () => !!(await state('ui_has_data')) && !((await state('ui_load_progress')) || {}).running);
  const door = page.locator('.up-dialog');
  for (let i = 0; i < 60 && await door.isVisible().catch(() => false); i += 1) {
    await door.locator('.fp-dialog-head button[title="Close"]').click({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(500);
  }
  const view = page.locator('.dv-vue-part:visible').filter({ has: page.locator('[id^="fc-rb-"]') }).first();
  const card = view.locator('.fc:visible').filter({ has: page.locator('.fc-title', { hasText: /^Reservoir$/ }) }).first();
  if (!(await card.count())) {
    await view.locator('.tb .tb-btn:visible[title^="Reservoir"]').first().click();
    await card.waitFor({ state: 'visible', timeout: 15000 });
  }
  const tree = card.locator('.fdx').first();
  for (let i = 0; i < 12; i += 1) {
    const n = await tree.evaluate((root) => {
      const closed = [...root.querySelectorAll('.tn-caret')].filter((e) => e.textContent.trim() === '▸');
      closed.forEach((e) => e.click()); return closed.length;
    });
    if (!n) break;
    await page.waitForTimeout(300);
  }
  const facies = tree.locator('.tn-row').filter({ has: page.locator('.tn-title', { hasText: /^Facies$/ }) }).first();
  await facies.locator('.tn-check').click();
  const yes = page.locator('.fp-dialog-foot button.fp-primary').first();
  await until('Facies read', async () => {
    if (await yes.isVisible().catch(() => false)) await yes.click().catch(() => {});
    return ((await state('ui_loaded_array_paths')) || []).length > 0 && !((await state('ui_load_progress')) || {}).running;
  });
  // the node the Values view reads: Facies, or the grid's geometry (PROBE_NODE=geometry)
  const node = process.env.PROBE_NODE === 'geometry'
    ? tree.locator('.tn-row').filter({ has: page.locator('.tn-title', { hasText: /^geometry$/ }) }).first()
    : facies;
  await node.locator('.tn-title').click();
  await page.waitForTimeout(1500);
  const values = page.locator('.fap').first();
  if (!(await values.isVisible().catch(() => false))) await page.locator('header button[title^="Values"]').first().click();
  await values.waitFor({ state: 'visible', timeout: 60000 });
  await values.locator('tbody tr').nth(3).waitFor({ state: 'visible', timeout: 60000 });
  // rows swept with the mouse, from the 4th to the 9th: highlighted
  const r3 = await values.locator('tbody tr').nth(3).boundingBox();
  const r8 = await values.locator('tbody tr').nth(8).boundingBox();
  await page.mouse.move(r3.x + 20, r3.y + r3.height / 2);
  await page.mouse.down();
  for (let i = 1; i <= 10; i += 1) { await page.mouse.move(r3.x + 20, r3.y + r3.height / 2 + (r8.y - r3.y) * i / 10); await page.waitForTimeout(40); }
  await page.mouse.up();
  await page.waitForTimeout(2500);
  out.selected_after_click = await values.locator('tbody tr.fap-sel').count();
  out.buttons = await values.locator('.fap-hl').allInnerTexts();
  log('row clicked: selected', out.selected_after_click, 'buttons', JSON.stringify(out.buttons));
  await page.screenshot({ path: 'out/values_keep_lit.png' });
  // what stands over each button's middle
  out.over = await values.locator('.fap-hl').evaluateAll((els) => els.map((b) => {
    const r = b.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { label: b.innerText.trim(), w: Math.round(r.width), h: Math.round(r.height), top: top ? (top.className || top.tagName) : null, inside: !!top && b.contains(top) };
  }));
  log('over the buttons', JSON.stringify(out.over));
  // Keep, with the mouse
  const keep = values.locator('.fap-hl', { hasText: /^Keep$/ }).first();
  if (await keep.count()) {
    await keep.click({ timeout: 5000 }).catch((e) => log('KEEP CLICK FAILED', e.message.slice(0, 160)));
    await page.waitForTimeout(4000);
    out.rows_after_keep = await tree.locator('.tn-title', { hasText: /^Kept #/ }).count();
    log('after Keep: Kept rows in the tree', out.rows_after_keep);
  }
  const clear = values.locator('.fap-hl', { hasText: /Clear/ }).first();
  if (await clear.count()) {
    await clear.click({ timeout: 5000 }).catch((e) => log('CLEAR CLICK FAILED', e.message.slice(0, 160)));
    await page.waitForTimeout(2500);
    out.selected_after_clear = await values.locator('tbody tr.fap-sel').count();
    log('after Clear: selected', out.selected_after_clear);
  }
  await page.screenshot({ path: 'out/values_keep_after.png' });

  // the same on the extract's cells: Read on the extract, a row clicked, Keep / Remove / Clear
  const part = values.locator('select.fap-part, .fap-part select').first();
  if (await part.count()) {
    const opts = await part.locator('option').allInnerTexts();
    out.read_on = opts;
    const ex = opts.findIndex((t) => /Kept/.test(t));
    if (ex >= 0) {
      await part.selectOption({ index: ex });
      await page.waitForTimeout(3000);
      await values.locator('tbody tr').nth(0).click();
      await page.waitForTimeout(2500);
      out.extract_selected = await values.locator('tbody tr.fap-sel').count();
      out.extract_buttons = await values.locator('.fap-hl').allInnerTexts();
      log('on the extract: selected', out.extract_selected, 'buttons', JSON.stringify(out.extract_buttons));
      await page.screenshot({ path: 'out/values_keep_extract.png' });
      const kept0 = await tree.locator('.tn-title', { hasText: /^Kept #|^Removed #/ }).count();
      const keep2 = values.locator('.fap-hl', { hasText: /^Keep$/ }).first();
      if (await keep2.count()) {
        await keep2.click({ timeout: 5000 }).catch((e) => log('KEEP ON EXTRACT FAILED', e.message.slice(0, 160)));
        await page.waitForTimeout(4000);
        out.extract_rows_after_keep = (await tree.locator('.tn-title', { hasText: /^Kept #|^Removed #/ }).count()) - kept0;
        log('on the extract, after Keep: new rows', out.extract_rows_after_keep);
      }
      const clear2 = values.locator('.fap-hl', { hasText: /Clear/ }).first();
      if (await clear2.count()) {
        await clear2.click({ timeout: 5000 }).catch((e) => log('CLEAR ON EXTRACT FAILED', e.message.slice(0, 160)));
        await page.waitForTimeout(2500);
        out.extract_selected_after_clear = await values.locator('tbody tr.fap-sel').count();
        log('on the extract, after Clear: selected', out.extract_selected_after_clear);
      }
      // a double click on a row: what it sets off
      const busy = [];
      await page.exposeFunction('__busy', (t) => busy.push(t));
      await values.locator('tbody tr').nth(1).dblclick();
      await page.waitForTimeout(2500);
      out.after_dblclick_selected = await values.locator('tbody tr.fap-sel').count();
      log('after a double click: selected', out.after_dblclick_selected);
    }
  }
  out.ok = true;
} catch (e) {
  out.ok = false;
  out.error = String(e.message || e).slice(0, 300);
  log('FAILED', out.error);
  await page.screenshot({ path: 'out/values_keep_failed.png' }).catch(() => {});
}
await browser.close();
process.stdout.write(JSON.stringify(out) + '\n');
