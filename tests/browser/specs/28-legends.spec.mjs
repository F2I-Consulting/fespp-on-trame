/*
 * Scenario (legends): ONE colour bar per 3D view, and the legend list.
 *
 * A view shows the bar of the table the Colormap card edits, and no other:
 * one bar per colour table would pile up into an unreadable block on a
 * wellbore that colours dozens of logs. A list inset in the view (top right)
 * shows every table colouring it, by section (grids, wells, surfaces) with
 * the objects each paints, and picking a row makes that table the edited
 * one, and so the one holding the bar.
 *
 * ParaView draws the bar itself into the image; what is read here is the
 * state the image is drawn from: the legend rows (one marked as holding the
 * bar) and the Colormap card's target.
 *
 * Uses the Volve wells file, imported here when it is not in yet.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET, OUT_DIR,
  dataTree, ensureData, expandTree, focusRenderView, openImportDoor, state, treeRow, viewId, viewPart,
  waitUntil, closeImport,
  familyTree,
} from '../lib/app.mjs';

const WELLS_EPC = path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Wells_Depth.epc');
// three logs of three wellbores, each title on one wellbore only: a view
// draws one log per wellbore, so three colour tables
const LOGS = ['SWIRR', 'DT_EDIT', 'AI_2013'];
const named = (r, name) => r.title === name || r.title.startsWith(name + ' ');

const rowsOf = async (page, vid) => ((await state(page, 'ui_legends__' + vid)) || {}).tables || [];
const cardOf = async (page, vid) => (await state(page, 'ui_colormap__' + vid)) || {};
// a constant field says so in its bar title, after the name the card shows
const sameName = (title, label) => title === label || title.startsWith(label + ' — constant');

test('one colour bar per view, and a Legends row puts its table on it', async ({ app }) => {
  const { page, note } = app;
  test.skip(!fs.existsSync(WELLS_EPC), 'wells test file not found: ' + WELLS_EPC);
  await ensureData(app);
  const loadedNames = async () => ((await state(page, 'ui_loaded_files')) || []).map((f) => f.name);
  if (!(await loadedNames()).includes(path.basename(WELLS_EPC))) {
    note('import ' + path.basename(WELLS_EPC));
    await openImportDoor(page);
    const h5 = WELLS_EPC.replace(/\.epc$/i, '.h5');
    await page.setInputFiles(M.fileInput, [WELLS_EPC, ...(fs.existsSync(h5) ? [h5] : [])]);
    await closeImport(page);
    await waitUntil(app, async () => (await loadedNames()).includes(path.basename(WELLS_EPC)),
      { what: 'the server to read the wells file' });
  }
  await focusRenderView(page);
  const vid = await viewId(page);
  // these logs are in depth: a view a scenario before left in time does not draw them
  const inTime = page.locator(M.titleStrip + ':visible').first().locator('[data-t3-domain].t3-time');
  if (await inTime.count()) {
    await inTime.click();
    await expect(inTime, 'the view is back in depth').toHaveCount(0, { timeout: 30000 });
  }

  // three logs ticked in the data tree, each shown in the view with its own
  // table, found through the filter as a reader would among many wells
  const tree = await familyTree(page, 'Well');
  const filter = tree.locator('.fdx-filter-input');
  const typeFilter = async (text) => filter.evaluate((el, t) => {
    el.value = t;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, text);
  for (const name of LOGS) {
    await typeFilter(name);
    await expandTree(tree);
    const row = treeRow(tree, name);
    await expect(row, 'the data tree shows a log titled ' + name).toHaveCount(1, { timeout: 15000 });
    const nodePath = await row.getAttribute('data-path');
    if (!((await state(page, 'visible_paths__' + vid)) || []).includes(nodePath)) {
      // read but hidden (a panel tick in an earlier scenario reads without
      // showing): its eye shows it, whereas a click on its box would unload it
      if (((await state(page, 'selected_paths')) || []).includes(nodePath)) {
        note('open the eye of ' + name);
        await row.locator(M.treeEye).dispatchEvent('click');
      } else {
        note('tick ' + name);
        await row.locator(M.treeCheck).dispatchEvent('click');
      }
      await expect.poll(async () => (await rowsOf(page, vid)).some((r) => named(r, name)),
        { message: name + ' colours the view with its own table', timeout: 60000 })
        .toBe(true);
    }
  }
  await typeFilter('');

  // ONE bar, and it is the table the Colormap card edits
  let rows = await rowsOf(page, vid);
  note('legends: ' + rows.map((r) => r.title + (r.bar ? ' [bar]' : '')).join(', '));
  expect(rows.length, 'three logs, three tables').toBeGreaterThanOrEqual(3);
  const held = rows.filter((r) => r.bar);
  expect(held.length, 'exactly one table holds the view\'s colour bar').toBe(1);
  expect(sameName(held[0].title, (await cardOf(page, vid)).label || ''),
    'the bar is the table the Colormap card edits').toBe(true);

  // the list inset in the view (top right, not a card) shows them by
  // section, and a row puts its table on the bar
  const card = viewPart(page, vid).locator('.flg').first();
  await expect(card, 'the legend list is on the view').toBeVisible({ timeout: 20000 });
  // grids and wells apart: the logs under Wells, each naming its wellbore;
  // a grid property an earlier scenario left shown, under Grids
  const isLog = (r) => LOGS.some((n) => named(r, n));
  for (const r of rows) {
    if (isLog(r)) {
      expect(r.family, r.title + ' is listed under Wells').toBe('well');
      expect((r.owners || []).length, r.title + ' names its wellbore').toBeGreaterThan(0);
    } else {
      expect(r.family, r.title + ' is listed under Grids').toBe('grid');
    }
  }
  await expect(card.locator('.flg-row'), 'one row per table').toHaveCount(rows.length);
  const other = card.locator('.flg-row:not(.flg-held)').first();
  const picked = (await other.locator('.flg-name').textContent()).trim();
  note('pick ' + picked);
  await other.locator('.flg-pick').click();
  await expect.poll(async () => (await rowsOf(page, vid)).filter((r) => r.bar).map((r) => r.title),
    { message: 'the picked table holds the bar', timeout: 30000 }).toEqual([picked]);
  await expect.poll(async () => sameName(picked, (await cardOf(page, vid)).label || ''),
    { message: 'the Colormap card edits the picked table', timeout: 30000 }).toBe(true);
  await expect(card.locator('.flg-held .flg-name'), 'the card marks the picked row')
    .toHaveText(picked);
  rows = await rowsOf(page, vid);
  expect(rows.filter((r) => r.bar).length, 'still one bar').toBe(1);
  // a screenshot for review, the view as the reader sees it: the list top
  // right, the axes bottom left, the one bar bottom right
  await page.waitForTimeout(1500);
  await card.locator('xpath=..').screenshot({ path: path.join(OUT_DIR, 'legends-view.png') });
});
