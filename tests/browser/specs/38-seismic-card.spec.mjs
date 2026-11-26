/*
 * The Seismic tree card: the IJK grids whose geometry is a lattice (a
 * velocity model, a seismic cube) are filed there with what they hold, and
 * no longer under Reservoir; its button is greyed while the data holds none.
 * The file is data/private/velocity_lattice — a 4 x 4 x 3 velocity grid in
 * time written by engine/resqml_epc, outside the repository: the scenario
 * steps aside when it is not there.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M,
  closeImport, ensureData, expandTree, familyTree, focusRenderView, openImportDoor, state, treeRow, viewId,
  waitUntil, DATASET, OUT_DIR,
} from '../lib/app.mjs';

const DIR = path.resolve(import.meta.dirname, '..', '..', '..', 'data', 'private');
const FILES = ['velocity_lattice.epc', 'velocity_lattice.h5'].map((f) => path.join(DIR, f));
const GRID = '5e150001-0000-4000-8000-000000000002';
const TITLE = 'Velocity lattice';

const seismicTool = async (page) => {
  const tools = (await state(page, 'view_tools_' + (await viewId(page)))) || [];
  return tools.find((t) => t.key === 'tree_seismic');
};

test('a lattice grid is filed under Seismic and no longer under Reservoir', async ({ app }) => {
  test.skip(!FILES.every((f) => fs.existsSync(f)), 'velocity_lattice is not under data/private');
  const { page, note } = app;
  await ensureData(app);
  await focusRenderView(page);

  const before = await seismicTool(page);
  expect(before, 'the view offers the Seismic card').toBeTruthy();
  if (!((await state(page, 'ui_cube_grid_rows')) || []).length) {
    expect(before.disabled, 'greyed while the data holds no lattice grid').toBe(true);
    expect(before.title).toContain('no lattice grid');
  }

  note('import ' + FILES.map((f) => path.basename(f)).join(' + '));
  await openImportDoor(page);
  await page.setInputFiles(M.fileInput, FILES);
  await waitUntil(app, async () => ((await state(page, 'assembly_xml')) || '').includes(GRID),
    { what: 'the lattice grid to reach the tree' });
  await closeImport(page);
  await waitUntil(app, async () => ((await state(page, 'ui_cube_grid_rows')) || []).some((r) => r.includes(GRID)),
    { what: 'the lattice grid to be listed (ui_cube_grid_rows)' });
  await focusRenderView(page);
  await expect.poll(async () => !!(await seismicTool(page)).disabled, { message: 'the Seismic button no longer greyed' })
    .toBe(false);

  const seismic = await familyTree(page, 'Seismic');
  await expect(treeRow(seismic, TITLE), 'its row in the Seismic card').toBeVisible({ timeout: 15000 });
  await expandTree(seismic);
  await expect(treeRow(seismic, 'geometry'), 'its geometry under it').toBeVisible();
  await expect(treeRow(seismic, DATASET.properties[0]), 'no property of the reservoir grid there').toHaveCount(0);
  await page.screenshot({ path: path.join(OUT_DIR, 'seismic-card.png') });

  const reservoir = await familyTree(page, 'Reservoir');
  await expandTree(reservoir);
  await expect(treeRow(reservoir, DATASET.properties[0]), 'the reservoir grid still under Reservoir').toBeVisible();
  await expect(treeRow(reservoir, TITLE), 'the lattice grid gone from Reservoir').toHaveCount(0);
});
