/*
 * The Time-depth model view makes no velocity model by itself: it opens on
 * the inputs of one — one TDLaw on a line at 2 000 m/s once the data gives
 * a zone, none and Generate greyed without one —; Generate makes "Velocity
 * model 1", a lattice grid listed in the Seismic tree of the 3D view in use,
 * ticked and shown there, and the active model: its row says so. The view
 * closed, the model's eyes close and its row stays, read.
 */
import path from 'node:path';
import {
  test, expect, M, DATASET, OUT_DIR,
  ensureProperty, familyTree, focusRenderView, showView, state, treeRow, viewId,
} from '../lib/app.mjs';

const law = async (page) => (await state(page, 'ui_time_depth_law')) || {};
const model = async (page) => (await state(page, 'ui_cube_tree')) || {};

test('the model view generates a velocity model once a TDLaw is entered, listed under Seismic', async ({ app }) => {
  const { page, note } = app;
  // an object read: the zone a model stands on is the data's
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  await showView(page, 'Time-depth', page.locator('.tdp'));
  const view = page.locator('.tdl').first();
  const generate = view.locator('button', { hasText: /^Generate$/ });

  if (!(await law(page)).generated && !((await law(page)).columns || []).length) {
    // as a session starts: nothing to edit, nothing to generate, no grid made
    await expect(view.locator('.tls'), 'no TDLaw to start with').toHaveCount(0);
    await expect(generate, 'Generate waits for a TDLaw').toBeDisabled();
    expect((await law(page)).model, 'no model is active').toBe('new');
    expect((await model(page)).row, 'opening the view made no grid').toBeFalsy();

    await view.locator('.tdl-add button', { hasText: /^Place$/ }).click();
    await expect(view.locator('.tls'), 'its track').toHaveCount(1, { timeout: 15000 });
    expect(((await law(page)).columns[0].rows || []).map((r) => r.velocity), 'it starts on a line at 2 000 m/s')
      .toEqual([null, 2000]);
    await expect(generate, 'a TDLaw converts: Generate is offered').toBeEnabled({ timeout: 15000 });
    expect((await law(page)).generated, 'still no model: nothing is generated unasked').toBe(false);
    await page.screenshot({ path: path.join(OUT_DIR, 'td-model-to-generate.png') });
    await generate.click();
  } else if (!(await law(page)).generated) {
    await generate.click();
  }

  await expect.poll(async () => (await law(page)).generated, { message: 'generated', timeout: 60000 }).toBe(true);
  const st = await law(page);
  const name = (st.models.find((m) => m.value === st.model) || {}).label;
  note('model: ' + name);
  expect(name, 'named and numbered').toMatch(/^Velocity model \d+$/);
  await expect(generate, 'generated, it updates by itself: no button').toHaveCount(0);
  await expect.poll(async () => (await model(page)).row, { message: 'its grid in the tree', timeout: 90000 }).toBeTruthy();
  const row = (await model(page)).row;
  await expect.poll(async () => ((await state(page, 'selected_paths')) || []).some((p) => p.startsWith(row)),
    { message: 'read', timeout: 60000 }).toBe(true);
  await expect.poll(async () => ((await state(page, 'visible_paths__' + vid)) || []).some((p) => p.startsWith(row)),
    { message: 'shown in the 3D view in use', timeout: 60000 }).toBe(true);
  expect((await state(page, 'ui_hidden_tree_rows')) || [], 'its row is not hidden').not.toContain(row);
  expect((await state(page, 'ui_cube_grid_rows')) || [], 'a lattice grid among the others').toContain(row);
  // the Seismic card came with it
  await expect.poll(async () => ((await state(page, 'ui_open_tools_by_view'))[vid] || []).includes('tree_seismic'),
    { message: 'the Seismic tree card open', timeout: 30000 }).toBe(true);
  const seismic = await familyTree(page, 'Seismic');
  await expect(treeRow(seismic, name), 'its row under Seismic').toBeVisible({ timeout: 30000 });
  await expect(treeRow(seismic, name).locator('.tn-active-model'), 'its row says it is the model in use')
    .toHaveText('(active T→D)', { timeout: 15000 });
  await page.screenshot({ path: path.join(OUT_DIR, 'td-model-generated.png') });
  const reservoir = await familyTree(page, 'Reservoir');
  await expect(treeRow(reservoir, name), 'not under Reservoir').toHaveCount(0);

  // the view closed: the eyes close, the row stays, read
  await page.locator(M.topBarButton + '[title^="Time-depth"]').click();
  await expect.poll(() => state(page, 'ui_open_view_kinds'), { message: 'closed', timeout: 30000 })
    .not.toContain('timedepth');
  await expect.poll(async () => ((await state(page, 'visible_paths__' + vid)) || []).some((p) => p.startsWith(row)),
    { message: 'its eyes closed', timeout: 30000 }).toBe(false);
  expect(((await state(page, 'selected_paths')) || []).some((p) => p.startsWith(row)), 'still read').toBe(true);
  expect((await law(page)).generated, 'still the active model').toBe(true);
});
