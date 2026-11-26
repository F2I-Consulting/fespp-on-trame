/*
 * Scenario (b): a file goes in, the tree fills, a ticked property colours the
 * grid.
 *
 * A tree component that throws while rendering (an undefined variable in its
 * template, say) renders nothing at all; a tree with no rows fails here.
 */
import {
  test, expect, M, DATASET,
  ensureData, ensureProperty, expandTree, state, treeRow, dataTree, focusRenderView, viewId, waitUntil,
} from '../lib/app.mjs';

test('an EPC loads and the tree shows its nodes', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);

  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const rows = await tree.locator(M.treeRow).evaluateAll(
    (els) => els.map((e) => (e.querySelector('.tn-title') || {}).innerText.trim()));
  expect(rows.length, 'the tree holds rows').toBeGreaterThan(1);
  note('rows: ' + rows.join(', '));

  for (const name of DATASET.properties) {
    await expect(treeRow(tree, name), 'row ' + name).toHaveCount(1);
  }
  // A row is a row only if it can be acted on.
  expect(await tree.locator(M.treeCheck).count(),
    'rows offer a checkbox').toBeGreaterThan(0);
});

test('ticking a property colours the grid', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  const view = page.locator(M.dockPart).filter({ has: page.locator('canvas') }).first();
  const before = await view.locator('canvas').first().screenshot();

  const nodePath = await ensureProperty(app, DATASET.properties[0]);

  // The application says which array colours which representation...
  const coloured = (await state(page, 'ui_active_array_by_rep')) || {};
  expect(Object.keys(coloured).length,
    'the grid is coloured by an array').toBeGreaterThan(0);
  note('coloured by: ' + JSON.stringify(Object.values(coloured)[0]));
  expect((await state(page, 'ui_loaded_array_paths')) || []).toContain(nodePath);

  // ...and the 3D view has actually repainted (no pixel is inspected: only
  // that the streamed image differs from the one before the tick).
  const after = await view.locator('canvas').first().screenshot();
  expect(Buffer.compare(before, after) !== 0,
    'the 3D view repainted after the tick').toBe(true);
  note('the rendered image changed (' + before.length + ' → ' + after.length + ' bytes)');
});

test('ticking a property also makes it the active node of the view', async ({ app }) => {
  // A tick on a leaf also activates it, so the cards that follow the active
  // node (Attributes, Colormap, Thresholds) show the property at once instead
  // of "Activate a property". The property is the one the other scenarios
  // work with, unticked then ticked again, so the session is left as they
  // expect it: that property loaded, shown, active.
  const { page, note } = app;
  await ensureData(app);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const title = DATASET.properties[0];
  const row = treeRow(tree, title);
  await expect(row, 'the data tree shows a row titled ' + title).toHaveCount(1);
  const nodePath = await row.getAttribute('data-path');
  const vid = await viewId(page);
  if (((await state(page, 'ui_loaded_array_paths')) || []).includes(nodePath)) {
    note('untick ' + title + ' first');
    await row.locator(M.treeCheck).click();
    await waitUntil(app,
      async () => !((await state(page, 'ui_loaded_array_paths')) || []).includes(nodePath),
      { what: title + ' to be unloaded' });
  }
  note('tick ' + title);
  await row.locator(M.treeCheck).click();
  await expect.poll(async () => state(page, 'active_path__' + vid),
    { message: 'the ticked property is the active node of ' + vid, timeout: 15000 })
    .toBe(nodePath);
  // the server fills the Attributes header from the activation, one flush later
  await expect.poll(async () => ((await state(page, 'ui_active_node_by_view')) || {})[vid],
    { message: 'the Attributes card names the ticked property', timeout: 15000 })
    .toBe(title);
  note('active after the tick: ' + title);
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).includes(nodePath),
    { what: title + ' to be loaded again' });
});

test('the Select menu unticks what it ticked', async ({ app }) => {
  // "Select ▾" removes as well as adds: a row whose kinds are all ticked
  // reads "Clear …" and unticks them in one click, and a last row clears
  // every tick.
  const { page, note } = app;
  await ensureData(app);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const menuRows = async () => {
    await tree.locator(M.treeBulk).click();
    const rows = await tree.locator(M.treeBulkItem).allInnerTexts();
    return rows.map((r) => r.trim());
  };
  const clickRow = async (label) => {
    // the exact row text, so "Clear all ticked (3)" never matches "all (3)"
    const rows = tree.locator(M.treeBulkItem);
    const texts = (await rows.allInnerTexts()).map((t) => t.trim());
    const i = texts.indexOf(label);
    expect(i, 'the menu offers ' + label).toBeGreaterThanOrEqual(0);
    await rows.nth(i).click();
  };

  let rows = await menuRows();
  note('menu: ' + rows.join(' | '));
  // the grid the loaded property rides on is ticked: its row offers to clear
  const clearRow = rows.find((r) => /^Clear /.test(r) && !/ticked/.test(r));
  expect(clearRow, 'a row whose kind is fully ticked offers to clear it').toBeTruthy();
  const repsBefore = ((await state(page, 'ui_loaded_rep_paths')) || []).length;
  await clickRow(clearRow);
  await waitUntil(app, async () => ((await state(page, 'ui_loaded_rep_paths')) || []).length < repsBefore,
    { what: 'the cleared kind to be unloaded' });
  note('cleared "' + clearRow + '": ' + ((await state(page, 'ui_loaded_rep_paths')) || []).length
    + ' representation(s) left of ' + repsBefore);

  rows = await menuRows();
  note('menu once cleared: ' + rows.join(' | '));
  const tickRow = clearRow.replace(/^Clear /, '');
  expect(rows, 'the same row offers to tick again').toContain(tickRow);
  await clickRow(tickRow);
  await waitUntil(app, async () => ((await state(page, 'ui_loaded_rep_paths')) || []).length >= repsBefore,
    { what: 'the kind to be loaded again' });
  note('ticked "' + tickRow + '" again');

  // leave the session as the scenarios after this one expect it: the first
  // property ticked
  await ensureProperty(app, DATASET.properties[0]);
});

test('a layout moves no tick and no eye, its rows group the same objects', async ({ app }) => {
  const { page, note } = app;
  const name = DATASET.properties[0];
  const path = await ensureProperty(app, name);
  await focusRenderView(page);
  const vid = await viewId(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const strip = tree.locator('.fdx-layout .fp-seg');
  await expect(strip, 'the layout strip').toHaveCount(1);
  const labels = (await strip.locator('button').allInnerTexts()).map((x) => x.trim());
  note('layouts: ' + labels.join(' | '));
  expect(labels, 'the layouts').toEqual(['Representation', 'Interpretation', 'Feature', 'Prop. kind']);
  const held = async () => JSON.stringify([
    ((await state(page, 'selected_paths')) || []).slice().sort(),
    ((await state(page, 'visible_paths__' + vid)) || []).slice().sort()]);
  const before = await held();
  const rows = tree.locator(M.treeRow);
  for (const [label, mode] of [['Feature', 'by_feature_and_interpretation'], ['Interpretation', 'by_interpretation']]) {
    await strip.locator('button', { hasText: label }).click();
    await expect.poll(() => state(page, 'ui_tree_layout__' + vid), { message: label + ' in force', timeout: 15000 }).toBe(mode);
    await expandTree(tree);
    expect(await held(), label + ': nothing unticked, no eye moved').toBe(before);
    await expect(treeRow(tree, name).locator(M.treeCheck), label + ': its tick there').toHaveText(/☑/);
    note(label + ': ' + await rows.count() + ' rows');
  }
  await strip.locator('button', { hasText: 'Representation' }).click();
  await expect.poll(() => state(page, 'ui_tree_layout__' + vid), { timeout: 15000 }).toBe('flat');
  expect(await held(), 'back: the same').toBe(before);
  expect((await state(page, 'selected_paths')) || [], 'its property').toContain(path);
});
