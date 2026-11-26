/*
 * The rows of the Statistics view beyond its selection: right under an item,
 * the rows that follow it.
 *
 * A 3D view's row needs no gesture: a filter in a view that shows the property
 * gives a row reading what the view draws, and the row goes with the filter. A
 * part's row comes from the part's eye in the docked tree; on a blocked
 * wellbore it carries the mean along the hole. A following row has no picker and
 * no pin, its menu says why, and like any row it has a Distribution button: the
 * Distribution view opens at the realization or the time the row reads. A pinned
 * copy keeps where its row reads, and can be the baseline. And a wide matrix
 * scrolls its own table: the panel never scrolls sideways.
 *
 * The filter is driven on the smoke file. Parts and realizations are not in it:
 * ALK_14Layers is read in a session of its own, in which the shared session's
 * scenarios have no business, and these scenarios step aside without the file.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET,
  addToStats, closeFamilyCards, closeImportDoor, comparePartsListed, compareItems, compareRows, dataTree, ensureProperty,
  ensureShown, expandTree, familyCardTree,
  focusRenderView, holdVerdicts, openCompare, openTool, ownSession, slide, state, treeRow, viewId,
} from '../lib/app.mjs';

const ALK_EPC = path.join(path.dirname(DATASET.files[0]), 'ALK_14Layers.epc');
const ALK_PROP = 'PORV';           // a multi-realization property of the file's grid
const ALK_SERIES = 'SOIL';         // its time series

/* The session on ALK: one for this file's scenarios, a file that size is read once. */
let alk = null;

async function alkSession(app) {
  if (!alk) alk = await ownSession(app, [ALK_EPC, ALK_EPC.replace(/\.epc$/i, '.h5')]);
  alk.note = app.note;
  return alk;
}

test.afterAll(async () => {
  if (alk) await alk.page.close();
  alk = null;
});

/* A row of the current tab reading `nodePath` on what `support` says. */
async function rowOn(page, nodePath, support) {
  return (await compareRows(page)).find((r) => r.path === nodePath && support(r.support || ''));
}
const onAPart = (support) => !!support && !support.startsWith('view:');


/* The Property slicer card of the view on screen. */
function propertySlicer(page) {
  return page.locator(M.card + ':visible')
    .filter({ has: page.locator(M.cardTitle, { hasText: /^Property slicer/ }) })
    .locator('.fsl').first();
}

test('a filter in a 3D view gives a row On the view, and it goes with the filter', async ({ app }) => {
  const { page, note } = app;
  // the Import data door an empty session opens (or a previous scenario left
  // open) would take every click: its cross closes it, a click beside does not
  await closeImportDoor(page);
  const name = DATASET.properties[0];
  const nodePath = await ensureProperty(app, name);
  const panel = await addToStats(app, name, nodePath);

  await focusRenderView(page);
  const vid = await viewId(page);
  const viewTitle = ((await state(page, 'fespp_render_panels')) || []).find((p) => p.id === vid).title;
  const viewRow = () => rowOn(page, nodePath, (support) => support === 'view:' + vid);
  await ensureShown(app, name);

  // No filter to start from (the card opens on the active property, and a sweep
  // of the cards may have left it so): a view showing the whole grid has no row.
  const close = await openTool(page, vid, 'thresholds');
  const card = propertySlicer(page);
  await expect(card, 'the Property slicer card is on screen').toBeVisible({ timeout: 20000 });
  const chain = async () => ((await state(page, 'ui_thresholds__' + vid)) || []).length;
  await card.locator('.fsl-reset').dispatchEvent('click');
  await expect.poll(chain, { message: 'no filter left in the view', timeout: 30000 }).toBe(0);
  await expect.poll(viewRow, { message: 'a view showing the whole grid has no row', timeout: 30000 })
    .toBeUndefined();

  // A filter: the row comes by itself, no gesture in the Statistics view.
  const add = card.locator('select.fsl-addsel').first();
  const offered = await add.evaluate((el, n) => {
    const opt = [...el.options].find((o) => o.value && o.textContent.includes(n));
    return opt ? opt.value : null;
  }, name);
  expect(offered, 'the card offers ' + name).not.toBeNull();
  await add.selectOption(offered);
  await expect.poll(chain, { message: 'the property is the filter', timeout: 30000 }).toBe(1);
  await expect.poll(async () => ((await viewRow()) || {}).support_label,
    { message: 'the row of what the view draws', timeout: 30000 }).toBe(viewTitle);
  const whole = (await rowOn(page, nodePath, (support) => !support)).metrics.Cardinality;
  const coming = await viewRow();
  note('view row: ' + coming.label + ', ' + coming.metrics.Cardinality + ' cells of ' + whole);
  expect(coming.label, 'its label names the view').toContain('On ' + viewTitle);
  expect(coming.reals.concat(coming.ts_opts), 'it picks nothing: it reads the view\'s').toEqual([]);

  // The filter narrowed: the row reads what the view draws now.
  const low = card.locator('.fsl-volume').first().locator('.fsl-dual input[type="range"]').first();
  const middle = await low.evaluate((el) => (Number(el.min) + Number(el.max)) / 2);
  await slide(low, middle);
  await expect.poll(async () => ((await viewRow()) || { metrics: {} }).metrics.Cardinality,
    { message: 'the row follows the filter', timeout: 30000 }).toBeLessThan(whole);
  note('narrowed at ' + middle + ': ' + (await viewRow()).metrics.Cardinality + ' cells');

  // Drawn under its item, in the view's name: no picker, no pin, its Distribution.
  await openCompare(page);
  const drawn = panel.locator(M.compareFollows).filter({ hasText: viewTitle });
  await expect(drawn, 'the row is drawn under its item').toHaveCount(1, { timeout: 15000 });
  await expect(drawn.locator('.fcp-item-rep'), 'in place of the representation').toHaveText(viewTitle);
  await expect(drawn.locator('select'), 'no picker').toHaveCount(0);
  await expect(drawn.locator('button[title^="Pin a copy"]'), 'no pin').toHaveCount(0);

  // Its menu is not mute: each act refused says why.
  await drawn.locator('.fcp-item-title').click({ button: 'right' });
  const menu = page.locator(M.compareRowMenu);
  await expect(menu, 'the row menu opens').toHaveCount(1);
  const acts = await menu.locator('.fp-menu-item').evaluateAll((els) => els.map((e) => ({
    label: e.innerText.trim(), refused: e.getAttribute('aria-disabled') === 'true', why: e.getAttribute('title') || '',
  })));
  note('row menu: ' + acts.map((a) => a.label + (a.refused ? ' (refused)' : '')).join(' | '));
  expect(acts.filter((a) => !a.refused).map((a) => a.label), 'a view\'s row can do none of them').toEqual([]);
  for (const a of acts) expect(a.why, a.label + ' says why not').not.toBe('');
  await page.keyboard.press('Escape');
  await expect(menu, 'the menu closes').toHaveCount(0);

  // The filter goes: so does the row.
  await focusRenderView(page);
  await propertySlicer(page).locator('.fsl-prop-x').first().dispatchEvent('click');
  await expect.poll(chain, { message: 'no filter left', timeout: 30000 }).toBe(0);
  await expect.poll(viewRow, { message: 'the row goes with the filter', timeout: 30000 }).toBeUndefined();
  await propertySlicer(page).locator('.fsl-reset').dispatchEvent('click');
  await close();
  await openCompare(page);
  await expect(panel.locator(M.compareFollows).filter({ hasText: viewTitle }), 'and leaves the matrix')
    .toHaveCount(0, { timeout: 15000 });
  await focusRenderView(page);
});

test('a blocked wellbore\'s eye gives its row, with its mean along the hole', async ({ app }) => {
  test.skip(!fs.existsSync(ALK_EPC), 'no file with blocked wellbores: ' + ALK_EPC);
  test.setTimeout(420000);
  const own = await alkSession(app);
  const { page, note } = own;
  const nodePath = await ensureProperty(own, ALK_PROP);
  const panel = await addToStats(own, ALK_PROP, nodePath);
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);
  const held = (await compareItems(page)).length;

  // The tree lists the parts of the file's grids, read or not. A tick reads one
  // and takes it in, as any tick of a panel's tree.
  const well = (await comparePartsListed(page)).find((p) => p.kind === 'BlockedWellbore');
  expect(well, 'the tree lists the blocked wellbores').toBeTruthy();
  note('the part: ' + well.title);
  const partRow = () => rowOn(page, nodePath, onAPart);
  await treeRow(tree, well.title).locator(M.treeCheck).click();
  await expect.poll(async () => ((await partRow()) || {}).support_label,
    { message: 'the row of the part, under its grid\'s property', timeout: 120000 })
    .toBe('Blocked wellbore · ' + well.title);

  const row = await partRow();
  const whole = (await rowOn(page, nodePath, (support) => !support)).metrics.Cardinality;
  note('part row: ' + row.label + ', ' + row.metrics.Cardinality + ' intervals, Mean (L) ' + row.metrics['Mean (L)']);
  expect(row.metrics.Cardinality, 'read on the part: some values').toBeGreaterThan(0);
  expect(row.metrics.Cardinality, 'fewer than on its grid').toBeLessThan(whole);
  expect(typeof row.metrics['Mean (L)'], 'the mean along the hole').toBe('number');

  // On screen: the column of that mean exists because this row has it.
  const lengthColumn = panel.locator('th.fcp-th-metric', { hasText: 'Mean (L)' });
  await expect(lengthColumn, 'a column for it').toHaveCount(1, { timeout: 15000 });
  const drawn = panel.locator(M.compareFollows).filter({ hasText: well.title });
  await expect(drawn, 'the row is drawn under its item').toHaveCount(1);
  await expect(drawn.locator('select'), 'no picker').toHaveCount(0);
  await expect(drawn.locator('button[title^="Pin a copy"]'), 'no pin').toHaveCount(0);

  // The eye: closed, the row and its column go, the property stays; open, back.
  const eye = treeRow(tree, well.title).locator(M.treeEye);
  await expect(eye, 'what the tick read is in the panel').toHaveAttribute('title', 'Hide');
  await eye.click();
  await expect.poll(partRow, { message: 'the eye closed takes the row out', timeout: 30000 }).toBeUndefined();
  await expect(lengthColumn, 'and its column').toHaveCount(0, { timeout: 15000 });
  expect((await compareItems(page)).length, 'the selection did not move').toBe(held);
  await eye.click();
  await expect.poll(async () => ((await partRow()) || {}).support_label,
    { message: 'the eye opened gives the row', timeout: 60000 }).toBe('Blocked wellbore · ' + well.title);
  expect((await compareItems(page)).length, 'and the rest stays').toBe(held);

  // Its menu refuses, with why; its eye takes the part out.
  await panel.locator(M.compareFollows).filter({ hasText: well.title }).locator('.fcp-item-title')
    .click({ button: 'right' });
  const menu = page.locator(M.compareRowMenu);
  await expect(menu, 'the row menu opens').toHaveCount(1);
  const baseline = menu.locator('.fp-menu-item', { hasText: 'Set as baseline' });
  await expect(baseline, 'never the baseline').toHaveAttribute('aria-disabled', 'true');
  expect(await baseline.getAttribute('title'), 'and it says why').toContain('row of the property itself');
  await page.keyboard.press('Escape');
  await eye.click();
  await expect.poll(partRow, { message: 'the part leaves', timeout: 30000 }).toBeUndefined();
  await expect(eye, 'its eye closes with it').toHaveAttribute('title', 'Show');

  await holdVerdicts(own);
});

test('a pin keeps a row as it reads: one copy per realization, which can be the baseline', async ({ app }) => {
  test.skip(!fs.existsSync(ALK_EPC), 'no file with realizations: ' + ALK_EPC);
  test.setTimeout(420000);
  const own = await alkSession(app);
  const { page, note } = own;
  const nodePath = await ensureProperty(own, ALK_PROP);
  const panel = await addToStats(own, ALK_PROP, nodePath);
  const count = async () => (await compareItems(page)).length;
  const before = await count();
  const source = panel.locator(M.compareOwnItem).filter({ hasText: ALK_PROP })
    .filter({ hasNot: page.locator('button[title="Remove this pinned row"]') }).first();
  const copyRow = panel.locator(M.compareOwnItem).filter({ hasText: ALK_PROP })
    .filter({ has: page.locator('button[title="Remove this pinned row"]') }).first();
  const menu = page.locator(M.compareRowMenu);
  const act = (label) => menu.locator('.fp-menu-item', { hasText: label });

  // A pin from the menu: one more item, the copy marked pinned, no picker on it.
  await source.locator('.fcp-item-title').click({ button: 'right' });
  await expect(act('Pin a copy of this row'), 'this property has something to keep')
    .not.toHaveAttribute('aria-disabled', 'true');
  await act('Pin a copy of this row').click();
  await expect.poll(count, { message: 'the pinned copy joins the statistics', timeout: 60000 }).toBe(before + 1);
  await expect(copyRow, 'the matrix draws the copy').toHaveCount(1, { timeout: 30000 });
  await expect(copyRow.locator('select'), 'it picks nothing: it keeps where it reads').toHaveCount(0);
  const [pinnedId] = (await compareRows(page)).filter((r) => r.pinned && r.path === nodePath).map((r) => r.id);
  note('the copy: ' + pinnedId);

  // A second copy at the same coordinate is refused, and said.
  await source.locator('.fcp-item-title').click({ button: 'right' });
  await act('Pin a copy of this row').click();
  const band = panel.locator('.fp-note', { hasText: 'pinned row at this realization and time step already' });
  await expect(band, 'the band says why').toHaveCount(1, { timeout: 30000 });
  expect(await count(), 'nothing joined').toBe(before + 1);
  await band.locator('button').click();
  await expect(band, 'the reader closes it').toHaveCount(0);

  // The baseline: the yellow moves to the copy, and the server holds it by its id.
  await copyRow.locator('.fcp-item-title').click({ button: 'right' });
  await act('Set as baseline').click();
  await expect.poll(() => state(page, 'ui_compare_baseline'),
    { message: 'the pinned copy is the baseline of its kind', timeout: 30000 }).toBe(pinnedId);
  await expect(panel.locator(M.compareItem + '.fcp-row-base'), 'one yellow row').toHaveCount(1);
  await expect(copyRow, 'the yellow row is the copy').toHaveClass(/fcp-row-base/);

  // Unpin: the copy goes, its source stays.
  await copyRow.locator('.fcp-item-title').click({ button: 'right' });
  await act('Remove this pinned row').click();
  await expect.poll(count, { message: 'the copy left the statistics', timeout: 30000 }).toBe(before);
  await expect(source, 'its source stays').toBeVisible();

  await holdVerdicts(own);
});

test('a wide matrix scrolls its own table: the panel never scrolls sideways', async ({ app }) => {
  const { page, note } = app;
  const name = DATASET.properties[0];
  const nodePath = await ensureProperty(app, name);
  const panel = await addToStats(app, name, nodePath);

  // measured on a window too narrow for the columns
  const was = page.viewportSize();
  await page.setViewportSize({ width: 700, height: was.height });
  await page.waitForTimeout(600);   // dockview lays its parts out on a resize observer
  // the narrower layout may put another tab in front: the panel measured
  // must be the one on screen
  // (at the front, its button would close it)
  if (!(await panel.locator(M.compareOwnItem).first().isVisible())) {
    await page.locator(M.topBarButton + '[title^="Statistics"]').click();
  }
  await panel.locator(M.compareOwnItem).first().waitFor({ state: 'visible', timeout: 15000 });
  // a tree card (320 px) would take the whole width of a narrow panel: the
  // matrix is measured without them
  const families = (await state(page, 'ui_compare_tree_families')) || [];
  await closeFamilyCards(panel);
  const overflow = () => panel.evaluate((e) => {
    const body = e.querySelector('.fcp-body');
    const scroll = e.querySelector('.fcp-scroll');
    return { body: body.scrollWidth - body.clientWidth, table: scroll.scrollWidth - scroll.clientWidth };
  });
  await expect.poll(async () => (await overflow()).body,
    { message: 'the panel does not scroll sideways', timeout: 15000 }).toBeLessThanOrEqual(1);
  const widths = await overflow();
  await page.setViewportSize(was);
  await familyCardTree(page, panel, families[0] || 'Reservoir');
  note('at 700 px, sideways overflow: panel ' + widths.body + ' px, matrix ' + widths.table + ' px');
  expect(widths.table, 'the table is wider than its block: the block scrolls it').toBeGreaterThan(0);
  await focusRenderView(page);
});
