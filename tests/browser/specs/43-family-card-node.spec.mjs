/*
 * Scenario: each family's tree card keeps its own active node.
 *
 * The PO, 23/11: the Surface tree card clicked, the Geometry slicer stayed on
 * the Reservoir's Geogrid — "a slicer on a node of a tree not in use". A tree
 * card brought into use (its tab) makes its own active node the view's again:
 * the one it had last. The Surface card's memory must not erase the
 * Reservoir's (each tree said its own tabs, the last one won).
 *
 * Uses fesapi's testing package (grids, surfaces, wells), in a session of its
 * own.
 */
import path from 'node:path';
import fs from 'node:fs';
import {
  test, expect, M, DATASET,
  familyTree, focusRenderView, holdVerdicts, ownSession, state, viewId, waitUntil,
} from '../lib/app.mjs';

const EPC = path.join(path.dirname(DATASET.files[0]), 'testingPackageCpp_blockWellbore.epc');

test('a family tree card in use brings back its own active node', async ({ app }) => {
  test.skip(!fs.existsSync(EPC), 'test file not found: ' + EPC);
  const own = await ownSession(app, [EPC, EPC.replace(/\.epc$/i, '.h5')]);
  const { page, note } = own;
  await focusRenderView(page);
  const vid = await viewId(page);
  const active = () => state(page, 'active_path__' + vid);
  const cardTab = (name) => page.locator('.fp-cards .dv-tab', { hasText: new RegExp('^\\s*' + name + '\\s*$') }).first();

  // a row of each family ticked, then clicked: the node each card had last
  const pick = async (family) => {
    const tree = await familyTree(page, family);
    const row = tree.locator(M.treeRow).filter({ has: page.locator(M.treeCheck) }).first();
    const where = await row.getAttribute('data-path');
    await row.locator(M.treeCheck).click();
    await waitUntil(own, async () => ((await state(page, 'selected_paths')) || []).includes(where),
      { what: family + ': ' + where + ' to be read' });
    await row.locator(M.treeTitle).click();
    await expect.poll(active, { message: family + ': the row clicked is the active node', timeout: 15000 })
      .toBe(where);
    note(family + ': ' + where);
    return where;
  };
  const reservoir = await pick('Reservoir');
  const surface = await pick('Surface');

  // each card brought back into use: its own node, the other's kept
  await cardTab('Reservoir').click();
  await expect.poll(active, { message: 'the Reservoir card brings back its node', timeout: 15000 }).toBe(reservoir);
  await cardTab('Surface').click();
  await expect.poll(active, { message: 'the Surface card brings back its node', timeout: 15000 }).toBe(surface);
  await cardTab('Reservoir').click();
  await expect.poll(active, { message: 'and the Reservoir card its own again', timeout: 15000 }).toBe(reservoir);
  const byTab = (await state(page, 'active_by_tab__' + vid)) || {};
  expect(byTab.reservoir, 'the Reservoir memory survives the Surface card').toBe(reservoir);
  expect(byTab.surface, 'the Surface memory survives the Reservoir card').toBe(surface);
  await holdVerdicts(own);
  await page.close();
});
