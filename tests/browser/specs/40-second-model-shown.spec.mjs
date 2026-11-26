/*
 * A second velocity model generated after a first: while its inputs are
 * entered the first stays ticked, its eyes closed, and the active one; once
 * generated, its row in the Seismic tree is ticked with its geometry and its
 * velocity, their eyes open — as the server's selection says —, and the first
 * is unticked. The active model's box, clicked, stays ticked and says why.
 */
import path from 'node:path';
import {
  test, expect, M, DATASET, OUT_DIR,
  ensureProperty, expandTree, familyTree, focusRenderView, showView, state, treeRow, viewId,
} from '../lib/app.mjs';

const law = async (page) => (await state(page, 'ui_time_depth_law')) || {};
const model = async (page) => (await state(page, 'ui_cube_tree')) || {};

async function generated(page, view) {
  const generate = view.locator('button', { hasText: /^Generate$/ });
  await expect(generate, 'Generate is offered').toBeEnabled({ timeout: 20000 });
  await generate.click();
  await expect.poll(async () => (await law(page)).model, { message: 'a model of the session generated', timeout: 60000 })
    .toMatch(/^m\d+$/);
  await expect.poll(async () => {
    const m = await model(page);
    const ticked = (await state(page, 'selected_paths')) || [];
    return !!m.grid && ticked.includes(m.grid) && ticked.includes(m.prop);
  }, { message: 'the server ticked its grid and its velocity', timeout: 90000 }).toBe(true);
  return model(page);
}

test('a second velocity model is ticked and shown in the tree as the first was', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  await showView(page, 'Time-depth', page.locator('.tdp'));
  const view = page.locator('.tdl').first();
  if ((await law(page)).generated) {
    await view.locator('select').first().selectOption({ label: 'New velocity model' });
    await expect.poll(async () => (await law(page)).generated, { message: 'the inputs of a new model', timeout: 20000 }).toBe(false);
  }
  const first = await generated(page, view);
  await view.locator('select').first().selectOption({ label: 'New velocity model' });
  await expect.poll(async () => (await law(page)).generated, { message: 'the inputs of a new model', timeout: 20000 }).toBe(false);
  // the model left for them goes on converting: it stays read and ticked, its eyes closed
  await expect.poll(async () => ((await state(page, 'visible_paths__' + vid)) || []).some((p) => p.startsWith(first.row)),
    { message: 'the eyes of the model left are closed', timeout: 30000 }).toBe(false);
  const ticked = (await state(page, 'selected_paths')) || [];
  expect(ticked.includes(first.grid) && ticked.includes(first.prop), 'the model left stays ticked').toBe(true);
  expect(await state(page, 'ui_active_model_row'), 'and the active one, as its row says').toBe(first.row);
  const second = await generated(page, view);
  expect(second.row, 'another row than the first model').not.toBe(first.row);
  // the model it took over from is unticked then, not before
  await expect.poll(async () => ((await state(page, 'selected_paths')) || []).some((p) => p.startsWith(first.row)),
    { message: 'the model that no longer converts is unticked', timeout: 60000 }).toBe(false);
  expect(await state(page, 'ui_active_model_row'), 'the generated model is the active one').toBe(second.row);

  const eyes = async () => (await state(page, 'visible_paths__' + vid)) || [];
  await expect.poll(async () => (await eyes()).includes(second.grid) && (await eyes()).includes(second.prop),
    { message: 'the server opened its eyes in the 3D view in use', timeout: 60000 }).toBe(true);

  const seismic = await familyTree(page, 'Seismic');
  await expandTree(seismic);
  const rows = (p) => seismic.locator(M.treeRow + '[data-path="' + p + '"]');
  await page.screenshot({ path: path.join(OUT_DIR, 'second-model-shown.png') });
  for (const [what, p] of [['geometry', second.grid], ['velocity', second.prop]]) {
    await expect(rows(p), 'the row of its ' + what).toHaveCount(1, { timeout: 15000 });
    await expect(rows(p).locator(M.treeCheck), 'its ' + what + ' is ticked in the tree').toHaveText('☑', { timeout: 15000 });
    await expect(rows(p).locator('.tn-eye'), 'its ' + what + ' has its eye').toHaveCount(1, { timeout: 15000 });
  }
  // the model the conversions read cannot be unloaded from the tree
  await rows(second.grid).locator(M.treeCheck).click();
  await expect.poll(async () => (await state(page, 'empty_color_snackbar_text')) || '',
    { message: 'the refusal says why', timeout: 15000 }).toContain('stays checked: it is the active');
  const kept = (await state(page, 'selected_paths')) || [];
  expect(kept.includes(second.grid) && kept.includes(second.prop), 'the active model stays ticked').toBe(true);
  await expect(rows(second.grid).locator(M.treeCheck), 'its box is ticked again').toHaveText('☑', { timeout: 15000 });
});
