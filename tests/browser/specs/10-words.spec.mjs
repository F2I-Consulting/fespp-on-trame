/*
 * Scenario (j): what the application SAYS — a card that names its target, a
 * door that refuses out loud, a number written the way the application reads
 * it.
 *
 * Three things only a browser sees: the Colormap card's title bar (a widget
 * prop, rendered by the shared card frame), the amber snackbar a refused
 * action raises, and the decimal separator a value field shows. Chromium
 * writes a `type="number"` input in the BROWSER's locale — "0,25" for a
 * French user, whatever `lang` the input carries (the lang-aware form
 * controls are an experimental flag) — beside a card writing "0.25"; the
 * fields that take a decimal are text fields with `inputmode="decimal"`, so
 * they show the value as it is, and a typed comma is read as the point.
 */
import {
  test, expect, M, DATASET,
  ensureProperty, expandTree, dataTree, focusRenderView, openTool, readContextMenu, statsHold, treeRow, state,
  viewId, waitUntil,
} from '../lib/app.mjs';

// The grid's own row: the container that holds the properties folder. Its
// title is the file's, so it is found from the loaded rep path, not by name.
async function gridRow(page, tree) {
  // a velocity model the session generated is read too: a lattice grid, under Seismic
  const own = [...((await state(page, 'ui_hidden_tree_rows')) || []), ...((await state(page, 'ui_cube_grid_rows')) || [])];
  const loaded = ((await state(page, 'ui_loaded_rep_paths')) || [])
    .filter((p) => !own.some((row) => p === row || p.startsWith(row + '/')));
  const containerPath = loaded[0].split('/_propsfolder_')[0];
  return tree.locator(M.treeRow + '[data-path="' + containerPath + '"]').first();
}

test('the Colormap card is the Color of the object when the grid node is active', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const vid = await viewId(page);

  const row = await gridRow(page, tree);
  await expect(row, 'the tree shows the grid container row').toHaveCount(1);
  const gridTitle = (await row.locator(M.treeTitle).innerText()).trim();
  await row.locator(M.treeTitle).click();
  await expect.poll(() => state(page, 'active_path__' + vid),
    { message: 'the grid node becomes the active node' })
    .toBe(await row.getAttribute('data-path'));

  // a geometry node: its solid colour, not the colormap of a property
  await expect.poll(async () => ((await state(page, 'ui_tool_target__' + vid)) || {}).colormap,
    { message: 'the card names the object' }).toBe(gridTitle);
  await expect.poll(async () => ((await state(page, 'ui_tool_title__' + vid)) || {}).colormap,
    { message: 'the card is titled Color' }).toBe('Color');
  note('active: ' + gridTitle);
});

test('an unread property offers the whole menu; Stats reads it first, then gives it its row', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);

  // A property no scenario ticks: the third one of the file.
  const untouched = 'stress';
  const row = treeRow(tree, untouched);
  await expect(row, 'the tree shows ' + untouched).toHaveCount(1);
  const path = await row.getAttribute('data-path');
  expect((await state(page, 'ui_loaded_array_paths')) || [],
    untouched + ' is not loaded').not.toContain(path);

  // Not read, a whole property offers what a read one does: the entry reads
  // it first, as its box would
  const unread = await readContextMenu(tree, untouched);
  note('menu on the unread ' + untouched + ': ' + unread.items.join(' | '));
  expect(unread.items, 'the whole menu on an unread property').toEqual(expect.arrayContaining(['Stats', 'Info']));

  await row.click({ button: 'right' });
  await page.locator(M.ctxMenu).waitFor({ timeout: 10000 });
  await page.locator(M.ctxItem, { hasText: /^Stats$/ }).click();
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).includes(path),
    { what: untouched + ' to be read by the entry' });
  expect((await state(page, 'selected_paths')) || [], 'its box ticked by the read').toContain(path);
  await expect.poll(() => statsHold(page, path), { message: 'the Statistics view holds it' }).toBe(true);
  note(untouched + ' read, then added by the right-click');

  // Left as found: unticking it in the data tree unloads what the
  // Statistics panel holds, so the question names the panel — answered.
  await focusRenderView(page);
  await expandTree(tree);
  await treeRow(tree, untouched).locator(M.treeCheck).click();
  const dialog = page.locator(M.dialog);
  await dialog.waitFor({ timeout: 30000 });
  const asked = (await dialog.innerText()).replace(/\s+/g, ' ');
  note('asked: ' + asked);
  expect(asked, 'the question names the panel using it').toContain('Statistics');
  await dialog.locator('button', { hasText: /^\s*Unload\s*$/ }).click();
  await expect(dialog, 'the question closes on the answer').toHaveCount(0);
  await waitUntil(app,
    async () => !((await state(page, 'ui_loaded_array_paths')) || []).includes(path),
    { what: untouched + ' to be unloaded' });
  await expect.poll(() => statsHold(page, path), { message: 'its row leaves with the unload' }).toBe(false);
  await focusRenderView(page);
});

test('a value field writes a decimal point and reads a typed comma', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);

  const close = await openTool(page, vid, 'volumetrics');
  // at rest the card says what it understood in one line of chips; the
  // fields are behind Edit
  const card = page.locator('.fvo').first();
  await expect(card.locator('.fvo-chain'), 'the card opens on its summary line').toBeVisible({ timeout: 20000 });
  await card.locator('.fvo-chain button', { hasText: /^Edit$/ }).click();
  const goc = page.locator('.fvo-num').first();
  await expect(goc, 'the card has a GOC field').toBeVisible({ timeout: 20000 });
  const kind = await goc.evaluate((e) => [e.getAttribute('type'), e.getAttribute('inputmode')]);
  note('GOC field: type=' + kind[0] + ' inputmode=' + kind[1]);
  expect(kind, 'a text field with a decimal keyboard, not a locale-formatted number input')
    .toEqual(['text', 'decimal']);

  // the 3D box has nothing to draw until a contact is typed, and says so
  const box = card.locator('.fvo-check input');
  await expect(box, 'no contact: the 3D box is greyed').toBeDisabled();
  expect(await box.getAttribute('title'), 'the greyed box says why').toMatch(/no contact to draw/);
  // Typed with a decimal comma: the application reads 1250.5 (not 1250, not
  // nothing), and the field shows it back with a point.
  await goc.fill('1250,5');
  await goc.dispatchEvent('change');
  await expect.poll(async () => (((await state(page, 'ui_volumetrics__' + vid)) || {}).params || {}).goc,
    { message: 'the server reads the contact depth', timeout: 30000 }).toBe(1250.5);
  await expect(box, 'a contact typed: the 3D box is live').toBeEnabled();
  await expect.poll(() => goc.inputValue(), { message: 'the field shows the point' })
    .toBe('1250.5');
  note('typed "1250,5" → params.goc = 1250.5, field "' + (await goc.inputValue()) + '"');
  await goc.fill('');
  await goc.dispatchEvent('change');
  await expect.poll(async () => (((await state(page, 'ui_volumetrics__' + vid)) || {}).params || {}).goc,
    { message: 'an emptied field clears the contact' }).toBeNull();
  // leave the card as found: the fields folded back (the card outlives its
  // close)
  await card.locator('.fvo-surface button', { hasText: /^Done$/ }).click();
  await expect(card.locator('.fvo-chain'), 'Done folds the fields back').toBeVisible();
  await close();
});
