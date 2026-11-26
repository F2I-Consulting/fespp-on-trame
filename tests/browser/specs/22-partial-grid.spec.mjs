/*
 * A grid known by reference only. The Olympus split: one EPC carries the
 * properties and names the grid, another carries the grid. Read in that
 * order, the grid is a partial stub first — the plugin builds its layout
 * anyway, and the tree must say, on every row of it, that nothing can show
 * in 3D until the grid's own file is read; once it is, the same rows load.
 * The files live under data/private/olympus, outside the repository: the
 * scenario steps aside when they are not there.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M,
  dataTree, ensureData, expandTree, focusRenderView, openImportDoor, state, treeRow, waitUntil,
  closeImport,
  familyTree,
} from '../lib/app.mjs';

const DIR = path.resolve(import.meta.dirname, '..', '..', '..', 'data', 'private', 'olympus');
const files = (name) => [path.join(DIR, name + '.epc'), path.join(DIR, name + '.h5')];
const present = ['OlympusOnlyProp', 'OlympusGridAndProp'].every((n) => files(n).every((f) => fs.existsSync(f)));

async function importFiles(app, paths, uuid = '43338d80-4db2-54a6-9a3e-7be39e1310d1') {
  const { page, note } = app;
  const before = (await state(page, 'ui_loaded_rep_paths')) || [];
  note('import ' + paths.map((f) => path.basename(f)).join(' + '));
  await openImportDoor(page);
  // no tab to press: the door holds both sources at once, so the drop zone
  // is there whatever an earlier scenario did with the OSDU half
  await page.setInputFiles(M.fileInput, paths);
  // no button: the files go as soon as the drop has settled
  await waitUntil(app, async () => {
    const xml = (await state(page, 'assembly_xml')) || '';
    return xml.includes(uuid);
  }, { what: 'the Olympus object ' + uuid + ' to reach the tree' });
  await closeImport(page);
  return before;
}

test('a grid known by reference greys its rows and says why, until its file comes', async ({ app }) => {
  test.skip(!present, 'the Olympus files are not under data/private/olympus');
  const { page, note } = app;
  await ensureData(app);
  await focusRenderView(page);

  // the properties' file alone: the grid is a reference
  await importFiles(app, files('OlympusOnlyProp'));
  const tree = dataTree(page);
  await expandTree(tree);
  const container = treeRow(tree, 'Sector');
  await expect(container, 'the grid container row').toHaveCount(1, { timeout: 15000 });
  const geometry = treeRow(tree, 'geometry').filter({ has: page.locator('.tn-partial') });
  await expect(geometry, 'a geometry row marked PARTIAL').toHaveCount(1);
  await expect(geometry.locator(M.treeCheck), 'no box on a geometry that is not here').toHaveCount(0);
  const why = await geometry.getAttribute('title');
  note('geometry row says: ' + (why || '').split('\n').pop());
  expect(why, 'the row says why nothing shows in 3D').toMatch(/Reference only.*import the grid/);
  const swat = treeRow(tree, 'SWAT');
  await expect(swat, 'a property of the referenced grid').toHaveCount(1);
  await expect(swat.locator(M.treeCheck), 'its properties cannot be ticked').toHaveCount(0);
  expect(await swat.getAttribute('title'), 'a property row says why').toMatch(/Reference only/);
  await expect(swat.locator('.tn-partial'), 'a property row wears the badge').toHaveText(/NOT IN 3D/);

  // the grid's own file: the same rows come alive
  await importFiles(app, files('OlympusGridAndProp'));
  await expandTree(tree);
  const live = treeRow(tree, 'geometry').filter({ hasNot: page.locator('.tn-partial') })
    .filter({ has: page.locator(M.treeCheck) });
  await expect.poll(async () => live.count(), { message: 'a live geometry row', timeout: 20000 })
    .toBeGreaterThan(0);
  await expect(treeRow(tree, 'SWAT').locator(M.treeCheck), 'SWAT can be ticked now').toHaveCount(1);
  await expect(treeRow(tree, 'properties'), 'the properties folder is there').toHaveCount(1);
  note('rows: ' + (await tree.locator(M.treeRow).count()));
});

test('a well is laid out like a grid: folders first, the trajectory after', async ({ app }) => {
  test.skip(!fs.existsSync(path.join(DIR, 'OlympusWell.epc')), 'the Olympus well file is not under data/private/olympus');
  const { page, note } = app;
  await ensureData(app);
  await focusRenderView(page);
  await importFiles(app, files('OlympusWell'), 'd938f215-09a5');
  // the 3D view's own Well tree: other panels carry a tree of their own
  const tree = await familyTree(page, 'Well');
  await expandTree(tree);
  const well = treeRow(tree, 'DEV');
  await expect(well, 'the DEV wellbore row').toHaveCount(1, { timeout: 15000 });
  // the rows under the well, in the order the tree draws them
  const order = await tree.locator(M.treeRow).evaluateAll((rows) => {
    const start = rows.findIndex((r) => (r.querySelector('.tn-title') || {}).innerText === 'DEV');
    const depth = (r) => parseInt(r.style.paddingLeft, 10);
    const d0 = depth(rows[start]);
    const out = [];
    for (let i = start + 1; i < rows.length && depth(rows[i]) > d0; i += 1) {
      if (depth(rows[i]) === d0 + 16) out.push((rows[i].querySelector('.tn-title') || {}).innerText);
    }
    return out;
  });
  note('under DEV: ' + order.join(' | '));
  expect(order, 'the completions folder comes before the trajectory').toEqual(['completions', 'OP']);
  await expect(treeRow(tree, 'completions').locator(M.treeCheck), 'a folder has a box').toHaveCount(1);
});
