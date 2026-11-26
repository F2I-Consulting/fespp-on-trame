/*
 * Scenario (timereal): the Time & Realizations card as the shared slicer
 * card (the PO, 29/10), driven by the hand in the browser: the time cut's
 * slider moved, the view's time step follows — after the player ran too
 * (the PO, 29/10 evening: "I move the point, the select box moves, the 3D
 * view does not; play goes back to where it was": the card read again
 * between the gesture and its drawing set the cut back to the view's
 * value) — and the card shows only its rows: no box row, no Range | Slice,
 * no ≤ = ≥.
 *
 * The smoke file carries no time series: the Volve demo grid (GasSat, 50
 * time steps) is imported when it is not in yet.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET,
  dataTree, ensureData, expandTree, focusRenderView, openImportDoor, openTool, slide, state, treeRow, viewId,
  waitUntil, closeImport,
  familyTree,
} from '../lib/app.mjs';

const VOLVE_EPC = path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Reservoir_Grid_Depth.epc');
const VOLVE_PROP = 'GasSat';

test('the Time & Realizations card: the time cut moved by hand reaches the view, after a play too', async ({ app }) => {
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
  // the time series: the last row titled GasSat is the property under its
  // series folder; its tick loads the series
  const row = treeRow(tree, VOLVE_PROP).last();
  await expect(row, 'the data tree shows a row titled ' + VOLVE_PROP).toBeVisible({ timeout: 30000 });
  const vid = await viewId(page);
  const timeState = async () => ((await state(page, 'ui_timereal__' + vid)) || {}).time || {};
  // the series read: the view has time steps (the row's path and the
  // loaded array's may differ: the series folder holds the property)
  if (!(((await timeState()).nb || 0) > 1)) {
    note('tick ' + VOLVE_PROP);
    await row.locator(M.treeCheck).dispatchEvent('click');
    await waitUntil(app, async () => ((await timeState()).nb || 0) > 1,
      { what: 'the view to have the time steps of ' + VOLVE_PROP });
  }
  await typeFilter('');
  await focusRenderView(page);
  const cardOf = (title) => page.locator(M.card).filter({ has: page.locator(M.cardTitle, { hasText: title }) });

  const close = await openTool(page, vid, 'timereal');
  const card = cardOf(/^Time & Realizations/).locator('.fsl').first();
  await expect(card, 'the Time & Realizations card is on screen').toBeVisible({ timeout: 20000 });
  const cardState = async () => (await state(page, 'ui_timereal_card__' + vid)) || {};
  const playerState = async () => (await state(page, 'ui_timereal_player__' + vid)) || {};
  const cutAt = async () => {
    const boxes = ((await cardState()).card || {}).boxes || [];
    return (((boxes[0] || {}).cuts || {}).time || [{}])[0].at;
  };
  await expect.poll(async () => (await timeState()).nb, { message: 'the view has time steps', timeout: 30000 })
    .toBeGreaterThan(1);
  await expect.poll(async () => ((await cardState()).subjects || []).map((s) => s.value),
    { message: 'the card has the time row', timeout: 30000 }).toContain('time');

  // rows of one value, nothing else (the PO, 29/10 evening)
  await expect(card.locator('.fsl-vol'), 'no "Boxes +"').toHaveCount(0);
  await expect(card.locator('.fsl-vrow'), 'no box row').toHaveCount(0);
  await expect(card.locator('.fsl-cmp'), 'no ≤ = ≥').toHaveCount(0);
  await expect(card.locator('.fsl-cut'), 'the time cut on screen').toHaveCount(1, { timeout: 20000 });
  const cut = card.locator('.fsl-cut').first();
  const slider = cut.locator('.fp-range input[type="range"]').first();

  // the slider moved by hand: the cut, then the view's time step
  const nb = (await timeState()).nb;
  const target = Math.min(nb - 1, 3);
  await slide(slider, target);
  await expect.poll(cutAt, { message: 'the slider moved the cut on the server', timeout: 30000 }).toBe(target);
  await expect.poll(async () => (await timeState()).index,
    { message: 'the view is at the time step the cut asks', timeout: 30000 }).toBe(target);

  // the player run then paused: the hand on the slider still moves the view
  const play = cut.locator('button[title^="Play"]').first();
  await expect(play, 'the time cut has a player').toBeVisible();
  await play.dispatchEvent('click');
  await expect.poll(async () => (await playerState()).playing, { message: 'the player plays', timeout: 30000 }).toBe(true);
  await expect.poll(async () => (await timeState()).index,
    { message: 'the player moves the time step', timeout: 30000 }).not.toBe(target);
  await cut.locator('button[title^="Pause"]').first().dispatchEvent('click');
  await expect.poll(async () => (await playerState()).playing, { message: 'the player pauses', timeout: 30000 }).toBe(false);
  const paused = (await timeState()).index;
  const after = paused === 0 ? Math.min(nb - 1, 5) : 0;
  note('paused at ' + paused + ', the hand asks ' + after);
  await slide(slider, after);
  await expect.poll(cutAt, { message: 'the slider moved the cut after the play', timeout: 30000 }).toBe(after);
  await expect.poll(async () => (await timeState()).index,
    { message: 'the view follows the hand after the play', timeout: 30000 }).toBe(after);
  // play again: from where the hand left the cut, not from the pause — the
  // first step the view leaves the hand's for is the next one (read every
  // 50 ms: the player goes 5 steps a second, a growing poll missed it)
  await play.dispatchEvent('click');
  let first = after;
  for (let t = 0; t < 200 && first === after; t += 1) {
    first = (await timeState()).index;
    if (first === after) await page.waitForTimeout(50);
  }
  await cut.locator('button[title^="Pause"]').first().dispatchEvent('click');
  note('after the hand\'s step ' + after + ', the player went to ' + first);
  expect(first, 'the player steps on from the hand\'s step').toBe(Math.min(nb - 1, after + 1));
  await close();
});
