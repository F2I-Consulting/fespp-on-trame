/*
 * Scenario (slicers): the Geometry slicer and the Property slicer — one card
 * (the PO's manager, 28/10) — driven by the hand, in the browser: the "+"
 * beside Boxes, the Range | Slice toggle of a box, a cut's slider, a range's
 * thumb, a property added. What the server holds is read back, and what the
 * card draws: a card changed in place on the server once reached the browser
 * as "no change" and nothing on screen moved (28/10, s52).
 *
 * The smoke file's grid is unstructured (no IJK crop), so this scenario
 * uses the small Olympus IJK grid ("Sector", property Porosity) the partial-grid
 * scenario also reads, imported here when it is not in yet.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET,
  dataTree, ensureData, expandTree, focusRenderView, openImportDoor, openTool, slide, state, treeRow, viewId,
  waitUntil, closeImport,
  familyTree,
} from '../lib/app.mjs';

const IJK_DIR = path.join(path.dirname(DATASET.files[0]), 'olympus');
const IJK_EPC = path.join(IJK_DIR, 'OlympusGridAndProp.epc');
const IJK_UUID = '43338d80-4db2-54a6-9a3e-7be39e1310d1'; // the grid
const IJK_PROP = 'Porosity';

test('the Geometry and Property slicers, one card, driven by the hand', async ({ app }) => {
  const { page, note } = app;
  test.skip(!fs.existsSync(IJK_EPC), 'IJK test file not found: ' + IJK_EPC);
  await ensureData(app);
  // the grid in the tree the server built (its assembly), whatever tab or
  // filter an earlier scenario left the tree on
  const gridIn = async () => ((await state(page, 'assembly_xml')) || '').includes(IJK_UUID);
  if (!(await gridIn())) {
    note('import ' + path.basename(IJK_EPC));
    await openImportDoor(page);
    const h5 = IJK_EPC.replace(/\.epc$/i, '.h5');
    await page.setInputFiles(M.fileInput, [IJK_EPC, ...(fs.existsSync(h5) ? [h5] : [])]);
    await closeImport(page);
    await waitUntil(app, gridIn, { what: 'the Olympus grid to reach the tree' });
  }
  // the grid's property lives on the Reservoir tab of the tree, which an
  // earlier scenario may have left on another one; and after the Olympus
  // files of the import scenario the tree holds too many rows to find this
  // one by scrolling: a reader types its name in the filter, and so does this
  // test
  await focusRenderView(page);
  const filter = (await familyTree(page, 'Reservoir')).locator('.fdx-filter-input');
  const typeFilter = async (text) => filter.evaluate((el, t) => {
    el.value = t;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, text);
  await typeFilter(IJK_PROP);
  // ticked by an event on the box itself: a card an earlier scenario left
  // open may lie over the tree, and what is tested here is the Slicers card
  const tree = dataTree(page);
  await expandTree(tree);
  const row = treeRow(tree, IJK_PROP);
  await expect(row, 'the data tree shows a row titled ' + IJK_PROP).toHaveCount(1, { timeout: 15000 });
  const nodePath = await row.getAttribute('data-path');
  if (!(((await state(page, 'ui_loaded_array_paths')) || []).includes(nodePath))) {
    note('tick ' + IJK_PROP);
    await row.locator(M.treeCheck).dispatchEvent('click');
    await waitUntil(app, async () => ((await state(page, 'ui_loaded_array_paths')) || []).includes(nodePath),
      { what: 'the application to report ' + IJK_PROP + ' as loaded' });
  }
  await typeFilter('');
  await focusRenderView(page);
  const vid = await viewId(page);
  const cardOf = (title) => page.locator(M.card).filter({ has: page.locator(M.cardTitle, { hasText: title }) });

  // ---- the Geometry slicer: one Range box keeping everything
  const close = await openTool(page, vid, 'slicers');
  const geo = cardOf(/^Geometry slicer/).locator('.fsl').first();
  await expect(geo, 'the Geometry slicer card is on screen').toBeVisible({ timeout: 20000 });
  const geoCard = async () => ((await state(page, 'ui_geometry_card__' + vid)) || {}).card || {};
  // with no object active the card cuts the whole scene (the PO, 29/10),
  // its list starting with it: the grid is picked there when the card is
  // not on it already
  await expect.poll(async () => ((((await state(page, 'ui_geometry_card__' + vid)) || {}).targets || [])[0] || {}).value,
    { message: 'the card lists the whole scene first', timeout: 30000 }).toBe('@scene');
  const targets = (((await state(page, 'ui_tool_targets__' + vid)) || {}).slicers || []);
  // the grid whose folder holds the property ticked
  const gridTarget = (targets.find((t) => nodePath.startsWith(t.value.split('/_propsfolder_')[0] + '/'))
    || targets[0] || {}).value;
  note('the grid the card cuts: ' + gridTarget);
  if (((await state(page, 'ui_geometry_card__' + vid)) || {}).target !== gridTarget) {
    await geo.locator('select.fsl-target').selectOption(gridTarget);
  }
  await expect.poll(async () => ((await state(page, 'ui_geometry_card__' + vid)) || {}).target,
    { message: 'the card is on the grid', timeout: 30000 }).toBe(gridTarget);
  await expect(geo.locator('.fsl-volume'), 'one box to start with').toHaveCount(1, { timeout: 20000 });

  // the "+" beside Boxes: a second box ON SCREEN (the server's card reached
  // the browser), switched to Slice — keeping everything until a cut is
  // added (the manager, 29/10) — and a cut through the middle of I, J and K
  await geo.locator('.fsl-vol button').first().dispatchEvent('click');
  await expect(geo.locator('.fsl-volume'), 'the "+" beside Boxes adds a box').toHaveCount(2, { timeout: 20000 });
  await geo.locator('.fsl-volume').nth(1).locator('button', { hasText: /^Slice$/ }).dispatchEvent('click');
  // the box IS a Slice box on the server and on screen (a Range box also
  // shows three axes and no cut: its sliders going away says the switch
  // came back)
  await expect.poll(async () => (((await geoCard()).boxes || [])[1] || {}).mode,
    { message: 'the second box is a Slice box', timeout: 30000 }).toBe('slice');
  await expect(geo.locator('.fsl-volume').nth(1).locator('.fp-range'),
    'the Slice box shows no slider before a cut').toHaveCount(0, { timeout: 20000 });
  await expect(geo.locator('.fsl-volume').nth(1).locator('.fsl-axis'),
    'the Slice box lists I, J and K').toHaveCount(3, { timeout: 20000 });
  await expect(geo.locator('.fsl-volume').nth(1).locator('.fsl-cut'),
    'the Slice toggle cuts nothing yet').toHaveCount(0, { timeout: 20000 });
  for (let a = 0; a < 3; a += 1) {
    await geo.locator('.fsl-volume').nth(1).locator('.fsl-axis').nth(a)
      .locator('button', { hasText: /^\+$/ }).first().dispatchEvent('click');
    await expect(geo.locator('.fsl-volume').nth(1).locator('.fsl-cut'),
      'a cut more on the axis\'s "+"').toHaveCount(a + 1, { timeout: 20000 });
  }

  // a cut moved by its slider, to the far end of I
  const ext = (((await state(page, 'ui_geometry_card__' + vid)) || {}).subjects || [])[0].extent;
  note('I extent ' + JSON.stringify(ext));
  const firstCut = geo.locator('.fsl-volume').nth(1).locator('.fsl-cut').first();
  await slide(firstCut.locator('.fp-range input[type="range"]').first(), ext[1]);
  await expect.poll(async () => (((await geoCard()).boxes || [])[1].cuts.i || [])[0].at,
    { message: 'the slider moved the cut on the server', timeout: 30000 }).toBe(ext[1]);
  // ≤: the cut keeps everything below it (the PO, 28/10)
  await firstCut.locator('button', { hasText: /^≤$/ }).dispatchEvent('click');
  await expect.poll(async () => (((await geoCard()).boxes || [])[1].cuts.i || [])[0].cmp,
    { message: 'the cut keeps what is below it', timeout: 30000 }).toBe('below');
  // one cut hidden by its eye, on screen in the card: the others stay
  const eye = geo.locator('.fsl-volume').nth(1).locator('.fsl-cut').nth(1).locator('.fsl-eye');
  // scrolled to (the card scrolls), then within the card's width
  await eye.scrollIntoViewIfNeeded();
  const cardBox = await geo.boundingBox();
  const eyeBox = await eye.boundingBox();
  note('card right ' + Math.round(cardBox.x + cardBox.width) + ', eye right ' + Math.round(eyeBox.x + eyeBox.width));
  expect(eyeBox.x + eyeBox.width, "a cut's eye is in the card, not pushed out of it")
    .toBeLessThanOrEqual(cardBox.x + cardBox.width + 1);
  await eye.dispatchEvent('click');
  await expect.poll(async () => (((await geoCard()).boxes || [])[1].cuts.j || [])[0].visible,
    { message: 'the J cut is hidden', timeout: 30000 }).toBe(false);
  await expect.poll(async () => (((await geoCard()).boxes || [])[1].cuts.k || [])[0].visible,
    { message: 'the K cut stays', timeout: 30000 }).toBe(true);

  // the first box's I range: the lower thumb moved by hand
  const dual = geo.locator('.fsl-volume').first().locator('.fsl-dual').first();
  const width = ((await dual.boundingBox()) || {}).width || 0;
  note('range slider width: ' + Math.round(width) + ' px');
  expect(width, 'the range slider has room to be seen').toBeGreaterThan(50);
  await slide(dual.locator('input[type="range"]').first(), ext[0] + 1);
  await expect.poll(async () => (((await geoCard()).boxes || [])[0].ranges.i || [])[0].low,
    { message: 'the lower thumb moved the range on the server', timeout: 30000 }).toBe(ext[0] + 1);
  await expect.poll(async () => ((await state(page, 'ui_slicers__' + vid)) || {}).mode,
    { message: 'the grid is cut', timeout: 30000 }).toBe('range');

  // a second I range (∪), its × in a NARROW card: the PO had to widen the
  // window to find it (28/10)
  await geo.evaluate((el) => { el.style.width = '260px'; });
  await geo.locator('.fsl-volume').first().locator('.fsl-axis').first().locator('.fsl-end')
    .first().dispatchEvent('click');
  const iRows = geo.locator('.fsl-volume').first().locator('.fsl-axis').first().locator('.fsl-arow');
  await expect(iRows, 'the "+" of I adds a second I range').toHaveCount(2, { timeout: 20000 });
  const drop = iRows.nth(1).locator('.fsl-end');
  const narrow = await geo.boundingBox();
  const dropBox = await drop.boundingBox();
  note('narrow card right ' + Math.round(narrow.x + narrow.width) + ', × right ' + Math.round(dropBox.x + dropBox.width));
  expect(dropBox.x + dropBox.width, "a range's × is in a narrow card, not pushed out of it")
    .toBeLessThanOrEqual(narrow.x + narrow.width + 1);
  await drop.dispatchEvent('click');
  await expect.poll(async () => (((await geoCard()).boxes || [])[0].ranges.i || []).length,
    { message: 'the × removes the second I range', timeout: 30000 }).toBe(1);
  await geo.evaluate((el) => { el.style.width = ''; });

  // ⟲: one box keeping everything again, the grid whole
  await geo.locator('.fsl-reset').dispatchEvent('click');
  await expect(geo.locator('.fsl-volume'), '⟲ leaves one box').toHaveCount(1, { timeout: 20000 });
  await close();

  // ---- the Property slicer: the same card, on the property added to it
  const closeProps = await openTool(page, vid, 'thresholds');
  const props = cardOf(/^Property slicer/).locator('.fsl').first();
  await expect(props, 'the Property slicer card is on screen').toBeVisible({ timeout: 20000 });
  // opened on a property, the card holds it already; on its grid, it is added here
  const add = props.locator('select.fsl-addsel');
  if (await add.count()) await add.selectOption(IJK_PROP);
  await expect(props.locator('.fsl-volume'), 'a property added: a box with its range').toHaveCount(1, { timeout: 30000 });
  await expect.poll(async () => ((await state(page, 'ui_thresholds__' + vid)) || []).length,
    { message: 'the box is the threshold chain', timeout: 30000 }).toBe(1);
  await props.locator('.fsl-volume').first().locator('button', { hasText: /^Slice$/ }).dispatchEvent('click');
  // a Slice box starts keeping everything (the manager, 29/10): its "+"
  // adds a cut of one value
  await expect.poll(async () => ((((await state(page, 'ui_property_card__' + vid)) || {}).card || {}).boxes || [{}])[0].mode,
    { message: 'the box is a Slice box', timeout: 30000 }).toBe('slice');
  await expect(props.locator('.fsl-volume').first().locator('.fp-range'),
    'the Slice box shows no slider before a cut').toHaveCount(0, { timeout: 20000 });
  await expect(props.locator('.fsl-cut'), 'the Slice toggle: no cut yet').toHaveCount(0, { timeout: 20000 });
  await props.locator('.fsl-volume').first().locator('.fsl-axis').first()
    .locator('button', { hasText: /^\+$/ }).first().dispatchEvent('click');
  await expect(props.locator('.fsl-cut'), 'its "+": a cut of one value').toHaveCount(1, { timeout: 20000 });
  // leave the card as found: the property no longer cut on
  await props.locator('.fsl-prop-x').first().dispatchEvent('click');
  await expect.poll(async () => ((await state(page, 'ui_thresholds__' + vid)) || []).length,
    { message: 'the property removed, no threshold left', timeout: 30000 }).toBe(0);
  await closeProps();
});
