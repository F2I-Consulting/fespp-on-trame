/*
 * Scenario: the Time & Realizations player, paused, another node highlighted,
 * then played again (the PO, 23/11: "the button stays on pause — it seems to
 * be pausing, highlighting another node and trying to play"). The button the
 * reader sees, and the time step of the view, must both start again.
 *
 * Uses the Volve demo grid (GasSat, 50 time steps), imported when it is not
 * in yet.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET,
  dataTree, ensureData, expandTree, focusRenderView, openImportDoor, openTool, state, treeRow, viewId,
  waitUntil, closeImport, familyTree,
} from '../lib/app.mjs';

const VOLVE_EPC = path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Reservoir_Grid_Depth.epc');
const VOLVE_PROP = 'GasSat';

test('the player plays again after a pause and another node highlighted', async ({ app }) => {
  const { page, note } = app;
  test.skip(!fs.existsSync(VOLVE_EPC), 'Volve test file not found: ' + VOLVE_EPC);
  await ensureData(app);
  const propIn = async () => (await treeRow(dataTree(page), VOLVE_PROP).count()) > 0;
  if (!(await propIn())) {
    note('import ' + path.basename(VOLVE_EPC));
    await openImportDoor(page);
    const h5 = VOLVE_EPC.replace(/\.epc$/i, '.h5');
    await page.setInputFiles(M.fileInput, [VOLVE_EPC, ...(fs.existsSync(h5) ? [h5] : [])]);
    await closeImport(page);
  }
  await focusRenderView(page);
  const filter = (await familyTree(page, 'Reservoir')).locator('.fdx-filter-input');
  const typeFilter = async (text) => filter.evaluate((el, t) => {
    el.value = t;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, text);
  await typeFilter(VOLVE_PROP);
  const tree = dataTree(page);
  await expandTree(tree);
  const row = treeRow(tree, VOLVE_PROP).last();
  await expect(row, 'the data tree shows a row titled ' + VOLVE_PROP).toBeVisible({ timeout: 30000 });
  const vid = await viewId(page);
  const timeState = async () => ((await state(page, 'ui_timereal__' + vid)) || {}).time || {};
  if (!(((await timeState()).nb || 0) > 1)) {
    note('tick ' + VOLVE_PROP);
    await row.locator(M.treeCheck).dispatchEvent('click');
    await waitUntil(app, async () => ((await timeState()).nb || 0) > 1,
      { what: 'the view to have the time steps of ' + VOLVE_PROP });
  }
  await typeFilter('');
  await focusRenderView(page);
  await openTool(page, vid, 'timereal');
  const card = page.locator(M.card).filter({ has: page.locator(M.cardTitle, { hasText: /^Time & Realizations/ }) })
    .locator('.fsl').first();
  await expect(card.locator('.fsl-cut'), 'the time cut on screen').toHaveCount(1, { timeout: 30000 });
  const cut = card.locator('.fsl-cut').first();
  const playerState = async () => (await state(page, 'ui_timereal_player__' + vid)) || {};
  const button = () => cut.locator('.fpb button').first();
  const moving = async (what) => {
    const from = (await timeState()).index;
    await expect.poll(async () => (await timeState()).index, { message: what, timeout: 20000 }).not.toBe(from);
  };

  await button().click();
  await expect(button(), 'the button says Pause once playing').toHaveAttribute('title', /^Pause/, { timeout: 15000 });
  await moving('the player moves the time step');
  await button().click();
  await expect(button(), 'the button says Play once paused').toHaveAttribute('title', /^Play/, { timeout: 15000 });
  await expect.poll(async () => (await playerState()).playing, { message: 'paused', timeout: 15000 }).toBe(false);

  // another node highlighted in the data tree
  const reservoir = await familyTree(page, 'Reservoir');
  await expandTree(reservoir);
  const other = reservoir.locator(M.treeRow).filter({ has: page.locator(M.treeCheck) })
    .filter({ hasNotText: VOLVE_PROP }).first();
  const otherPath = await other.getAttribute('data-path');
  await other.locator(M.treeTitle).click();
  await expect.poll(async () => state(page, 'active_path__' + vid), { message: 'the other node is active', timeout: 15000 })
    .toBe(otherPath);
  note('highlighted ' + otherPath);

  // the card back in sight (the tree card it may share a dock group with came forward)
  const tab = page.locator('.fp-cards .dv-tab', { hasText: /Time & Realizations/ }).first();
  if (await tab.count()) await tab.click();
  else await openTool(page, vid, 'timereal');
  await expect(button(), 'the player bar is back in sight').toBeVisible({ timeout: 15000 });
  note('play button: ' + (await button().getAttribute('title')));
  await button().click();
  await expect(button(), 'the button says Pause again').toHaveAttribute('title', /^Pause/, { timeout: 15000 });
  await expect.poll(async () => (await playerState()).playing, { message: 'playing again', timeout: 15000 }).toBe(true);
  await moving('the time step moves again');
  await button().click();
  await expect(button(), 'and it pauses').toHaveAttribute('title', /^Play/, { timeout: 15000 });
});
