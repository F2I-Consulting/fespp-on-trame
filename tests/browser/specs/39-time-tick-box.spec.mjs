/*
 * An object in time ticked first, in an empty 3D view (it opens saying
 * depth), with no velocity model generated: the view takes the object's
 * domain, nothing asked — no default domain, the first objects ticked give
 * theirs; the boxes are for the ticks that follow, of the domain the view is
 * not in (tests/visual/scenarios/view_domain, view_domain_retick). The file
 * is data/private's Volve time horizons, outside the repository: the
 * scenario steps aside when it is not there.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M,
  dataTree, expandTree, holdVerdicts, ownSession, state, treeRow, viewId, OUT_DIR,
} from '../lib/app.mjs';

const DIR = path.resolve(import.meta.dirname, '..', '..', '..', 'data', 'private');
const FILES = ['Volve_Demo_Fault_Horizon_TIME.epc', 'Volve_Demo_Fault_Horizon_TIME.h5'].map((f) => path.join(DIR, f));
const TITLE = 'BCU_ts';

test('a time object ticked first turns an empty view to time, nothing asked', async ({ app }) => {
  test.skip(!FILES.every((f) => fs.existsSync(f)), 'data/private holds no Volve time horizons');
  const own = await ownSession(app, FILES);
  const { page } = own;
  const vid = await viewId(page);
  expect(await state(page, 'ui_vdomain__' + vid), 'a view opens saying depth').toBe('depth');
  expect((await state(page, 'ui_time_depth_law')).generated, 'no velocity model to start with').toBe(false);

  const tree = dataTree(page);
  await expandTree(tree);
  const row = treeRow(tree, TITLE);
  const tabs = tree.locator('.fdx-tab');
  for (let i = 0; !(await row.count()) && i < await tabs.count(); i += 1) {
    await tabs.nth(i).click();
    await expandTree(tree);
  }
  await expect(row, 'the data tree shows a row titled ' + TITLE).toHaveCount(1, { timeout: 15000 });
  await row.locator(M.treeCheck).click();

  await expect.poll(() => state(page, 'ui_vdomain__' + vid), { message: 'the view takes the domain of its first object', timeout: 30000 })
    .toBe('time');
  await expect.poll(async () => ((await state(page, 'ui_loaded_rep_paths')) || []).length, { message: 'the object is read', timeout: 30000 })
    .toBeGreaterThan(0);
  await page.screenshot({ path: path.join(OUT_DIR, 'time-tick-first.png') });
  await expect(page.locator(M.dialog), 'no box asks anything').toHaveCount(0);
  expect((await state(page, 'ui_tick_confirm')) || {}, 'no question stands on the server either').toEqual({});
  expect((await state(page, 'undrawn_paths__' + vid)) || [], 'the object is drawn, in its own domain').toEqual([]);
  await holdVerdicts(own);
  await page.close();
});
