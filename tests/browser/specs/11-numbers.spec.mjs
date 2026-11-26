/*
 * Scenario (k): every number on screen is written the one way — four
 * significant digits, scientific notation outside [1e-3, 1e6], a thin space
 * between thousands, an en dash for a missing value — and a volume column
 * says its unit in its header, not in a footer.
 *
 * The rule lives in widgets/_shared/numfmt.js and is bundled into every
 * widget that formats a number; it only ever runs in a browser, so this is
 * where it is read back: the Volumetrics table (the totals row, every volume
 * cell) and the Colormap card (its two range labels; and its Hide NaN cells
 * box, which lives on the same card). The same rule on the
 * server side (engine/utils/numfmt.py) has its own unit tests.
 */
import {
  test, expect, M, DATASET,
  dataTree, ensureProperty, ensureShown, expandTree, focusRenderView, openTool, state, treeRow, viewId,
} from '../lib/app.mjs';

// a number as the shared rule writes it: "1 235", "0.00123", "1.2e-14",
// "3.4e+12", "-0.5", or the en dash of a missing value
const NUMBER = /^(\u2013|-?\d{1,3}(\u2009\d{3})*(\.\d+)?|-?\d(\.\d+)?e[+-]\d+)$/;

test('the Volumetrics table writes its volumes by the shared rule, under a header that names the unit', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);

  const close = await openTool(page, vid, 'volumetrics');
  const card = page.locator('.fvo').first();
  await expect(card, 'the Volumetrics card is on screen').toBeVisible({ timeout: 20000 });
  // the terms the card picked read as chips, the pickers behind Edit — and
  // no select is on screen until then (the grid's is in the bar above)
  const chain = card.locator('.fvo-chain');
  await expect(chain, 'the summary line is on screen').toBeVisible();
  const chips = (await chain.locator('.fp-chip').allInnerTexts()).map((t) => t.trim());
  note('chain: ' + chips.join(' | '));
  expect(chips.some((c) => /^φ: /.test(c)), 'the porosity term is named').toBe(true);
  expect(chips.some((c) => /^NTG: /.test(c)) && chips.some((c) => /^Sw: /.test(c)), 'NTG and Sw are named').toBe(true);
  expect(chips.some((c) => /no contact|GOC /.test(c)), 'the contacts are named').toBe(true);
  await expect(card.locator('.fvo-params select'), 'no picker until Edit').toHaveCount(0);
  await chain.locator('button', { hasText: /^Edit$/ }).click();
  await expect(card.locator('.fvo-params select').first(), 'Edit shows the pickers').toBeVisible();
  // the surface line: four optional numbers, each saying what it does
  const surface = card.locator('.fvo-surface .fvo-num');
  await expect(surface, 'Bo, Bg, RF oil and RF gas').toHaveCount(4);
  await surface.first().fill('1,25');
  await surface.first().dispatchEvent('change');
  await expect.poll(async () => (((await state(page, 'ui_volumetrics__' + vid)) || {}).params || {}).bo,
    { message: 'the server reads Bo', timeout: 30000 }).toBe(1.25);
  await card.locator('.fvo-surface button', { hasText: /^Done$/ }).click();
  await expect(chain, 'Done folds the fields back').toBeVisible();
  expect((await chain.locator('.fp-chip').allInnerTexts()).some((c) => /Bo 1\.25/.test(c)), 'the chip says Bo').toBe(true);
  await card.locator('button', { hasText: /^Compute$/ }).click();
  const table = card.locator('table.fvo-table');
  await expect(table, 'the table is built').toBeVisible({ timeout: 60000 });

  // The unit is in the header of every volume column (the default unit is
  // millions of cubic metres), not in a footer.
  const headers = await table.locator('thead th').allInnerTexts();
  note('headers: ' + headers.map((h) => h.trim()).join(' | '));
  for (const col of ['GRV', 'NRV', 'PV', 'HCPV']) {
    const th = headers.find((h) => h.trim().startsWith(col));
    expect(th, 'a header for ' + col).toBeDefined();
    expect(th, col + ' header names its unit').toContain('(10⁶ m³)');
  }

  // Every numeric cell of the totals row follows the rule.
  const totals = table.locator('tbody tr.total').last();
  await expect(totals, 'a totals row').toHaveCount(1);
  const cells = (await totals.locator('td.num').allInnerTexts()).map((t) => t.trim());
  note('totals: ' + cells.join(' | '));
  expect(cells.length, 'the totals row has numeric cells').toBeGreaterThan(0);
  for (const c of cells) expect(c, 'cell "' + c + '" follows the number rule').toMatch(NUMBER);

  // The unit selects say what a barrel is here — one per family of
  // columns: the reservoir volumes, and the oil at surface since Bo was
  // given (no Bg: no gas select, no GIIP column).
  const units = card.locator('.fvo-units select');
  await expect(units, 'a reservoir unit and an oil unit').toHaveCount(2);
  const options = await units.first().locator('option').allInnerTexts();
  note('unit options: ' + options.join(' | '));
  expect(options, 'the barrel option says it is a reservoir barrel').toContain('rbbl (reservoir barrel)');
  expect(options, 'millions of reservoir barrels are offered').toContain('MMrbbl');
  const oilOptions = await units.nth(1).locator('option').allInnerTexts();
  expect(oilOptions, 'the oil unit says it is a stock-tank barrel').toContain('stb (stock-tank barrel)');
  const heads = (await table.locator('thead th').allInnerTexts()).map((h) => h.trim());
  expect(heads.some((h) => h.startsWith('STOIIP (MMstb)')), 'the STOIIP column is there, in MMstb').toBe(true);
  expect(heads.some((h) => h.startsWith('GIIP')), 'no Bg: no GIIP column').toBe(false);
  // leave the session as found: Bo cleared
  await chain.locator('button', { hasText: /^Edit$/ }).click();
  await surface.first().fill('');
  await surface.first().dispatchEvent('change');
  await expect.poll(async () => (((await state(page, 'ui_volumetrics__' + vid)) || {}).params || {}).bo,
    { message: 'an emptied Bo is cleared' }).toBeNull();
  await close();
});

test('the Colormap card writes its range by the shared rule', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  // the card edits a colormap on a property node, a colour on a geometry
  const tree = dataTree(page);
  await expandTree(tree);
  await treeRow(tree, DATASET.properties[0]).locator(M.treeTitle).click();

  const close = await openTool(page, vid, 'colormap');
  // the first card on screen: a second 3D view may have one too
  const labels = page.locator('.fcm:visible').first().locator('.fcm-range-labels > span');
  await expect(labels, 'the range labels are on screen').toHaveCount(3, { timeout: 20000 });
  const lo = (await labels.nth(0).innerText()).trim();
  const hi = (await labels.nth(2).innerText()).trim();
  note('range labels: "' + lo + '" … "' + hi + '"');
  expect(lo, 'the min label follows the number rule').toMatch(NUMBER);
  expect(hi, 'the max label follows the number rule').toMatch(NUMBER);
  await close();
});

test('Symmetric around 0 sets a range of [-m, +m]', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);

  const close = await openTool(page, vid, 'colormap');
  const before = (await state(page, 'ui_colormap__' + vid)) || {};
  note('before: [' + before.min + ', ' + before.max + ']');
  // the click goes straight to the button: the floating cards overlap, and
  // what is under test is the server's answer, not the card's reachability
  await page.locator('.fcm:visible').first().locator('button', { hasText: /^Symmetric around 0$/ }).dispatchEvent('click');
  await expect.poll(async () => {
    const c = (await state(page, 'ui_colormap__' + vid)) || {};
    return typeof c.min === 'number' && typeof c.max === 'number' && c.max > 0 && c.min === -c.max;
  }, { message: 'the server applied a range symmetric around 0', timeout: 30000 }).toBe(true);
  const after = (await state(page, 'ui_colormap__' + vid)) || {};
  note('after: [' + after.min + ', ' + after.max + ']' + (after.note ? ' — ' + after.note : ''));
  // back to the data range, so the next scenario finds the card as it was
  await page.locator('.fcm:visible').first().locator('button', { hasText: /^Data range$/ }).dispatchEvent('click');
  await close();
});

/*
 * Hide NaN cells: the box beside the NaN swatch. A NaN cell made transparent
 * leaves a see-through hole; the box removes the NaN cells before the skin is
 * extracted, so the faces of their neighbours show. Two ways in, read back
 * from the server's projection of the card: the box by hand, and the NaN
 * opacity at 0, which checks it ("auto") and unchecks it back above 0. What
 * the mask draws is the headless scenarios' business (hide_nan, hide_nan_ijk).
 */
const cardOf = async (page, vid) => (await state(page, 'ui_colormap__' + vid)) || {};

/* Set a checkbox or a slider the way a hand does: the value, then its events. */
async function setInput(locator, value) {
  await locator.evaluate((el, v) => {
    if (el.type === 'checkbox') el.checked = v; else el.value = String(v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

test('Hide NaN cells: the box by hand, and the NaN opacity at 0 that checks it', async ({ app }) => {
  const { page, note } = app;
  await ensureShown(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  const close = await openTool(page, vid, 'colormap');

  const box = page.locator('.fcm:visible').first().locator('label.fcm-check', { hasText: 'Hide NaN cells' })
    .locator('input[type="checkbox"]');
  await expect(box, 'the box is on the card').toHaveCount(1, { timeout: 20000 });
  const c0 = await cardOf(page, vid);
  note('card: array=' + c0.array + ' ok=' + c0.hide_nan_ok
    + (c0.hide_nan_why ? ' why=' + c0.hide_nan_why : ''));
  expect(c0.hide_nan_ok, 'a cell property painting a visible grid can hide its NaN cells').toBe(true);
  await expect(box, 'unchecked to begin with').not.toBeChecked();
  await expect(box, 'and usable').toBeEnabled();

  // by hand
  await setInput(box, true);
  await expect.poll(async () => (await cardOf(page, vid)).hide_nan,
    { message: 'the server turned the mask on', timeout: 30000 }).toBe(true);
  const c1 = await cardOf(page, vid);
  note('by hand: ' + c1.hide_nan_hidden + ' cell(s) hidden');
  expect(c1.hide_nan_auto, 'a hand on the box is not the opacity').toBe(false);
  await expect(box, 'the box reads the server back').toBeChecked();
  await setInput(box, false);
  await expect.poll(async () => (await cardOf(page, vid)).hide_nan,
    { message: 'and turned it off', timeout: 30000 }).toBe(false);

  // through the NaN opacity: its palette, the opacity bar to 0 and back
  const swatch = page.locator('.fcm:visible').first().locator('[title="NaN color / opacity"]');
  await swatch.dispatchEvent('click');
  const bar = page.locator('.fp-cswatch-pop .fp-cpick-alpha');
  await expect(bar, 'the NaN palette and its opacity bar').toHaveCount(1);
  const across = await bar.boundingBox();
  await page.mouse.click(across.x + 0.5, across.y + across.height / 2);
  await expect.poll(async () => {
    const c = await cardOf(page, vid);
    return c.hide_nan === true && c.hide_nan_auto === true;
  }, { message: 'a NaN opacity of 0 checks the box', timeout: 30000 }).toBe(true);
  await expect(box, 'checked on screen').toBeChecked();
  await page.mouse.click(across.x + across.width - 0.5, across.y + across.height / 2);
  await expect.poll(async () => (await cardOf(page, vid)).hide_nan,
    { message: 'the opacity back above 0 unchecks what it checked', timeout: 30000 }).toBe(false);
  await swatch.dispatchEvent('click');
  await close();
});
