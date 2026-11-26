/*
 * Scenario (l): a category is named, not numbered — the cross-plot legend
 * coloured by a categorical property reads the file's labels (its string
 * lookup), not "1, 2, 3".
 *
 * The file the pass drives by default (vector_props.epc) has no categorical
 * property, so this scenario runs only when FESPP_SMOKE_CATEGORY names one
 * of the driven file (FESPP_SMOKE_EPC, with FESPP_SMOKE_PROPS naming two
 * plain continuous properties of the same grid). Only a RESQML
 * CategoricalProperty carries names, through its StringTableLookup: a
 * DiscreteProperty never does — drogon's "Facies" is one, and its legend of
 * bare codes is the correct reading, not a failure. Without the variable the
 * scenario is skipped and says so; it never passes silently on a file that
 * cannot show the point.
 */
import {
  test, expect, M, DATASET,
  addToStats, ensureProperty, expandTree, dataTree, focusRenderView, treeRow,
} from '../lib/app.mjs';

const CATEGORY = process.env.FESPP_SMOKE_CATEGORY || '';

/* Pick, in a widget select, the option whose text starts with `name`. */
async function pickOption(select, name) {
  const value = await select.evaluate((el, n) => {
    const opt = [...el.options].find((o) => o.textContent.trim().startsWith(n));
    return opt ? opt.value : null;
  }, name);
  expect(value, 'the select offers ' + name).not.toBeNull();
  await select.selectOption(value);
}

test('the cross-plot legend names the categories of the colouring property', async ({ app }) => {
  test.skip(!CATEGORY, 'FESPP_SMOKE_CATEGORY is not set: the default file has no categorical'
    + ' property, so the category labels cannot be read here (name a CategoricalProperty'
    + ' of the file given by FESPP_SMOKE_EPC — one with a StringTableLookup)');
  const { page, note } = app;
  const [xName, yName] = DATASET.properties;
  const px = await ensureProperty(app, xName);
  const py = await ensureProperty(app, yName);
  await ensureProperty(app, CATEGORY);
  await addToStats(app, xName, px);
  const stats = await addToStats(app, yName, py);
  const panel = stats.locator('.fcp-chart').nth(1);
  await pickOption(panel.locator('select[title^="Color by"]'), CATEGORY);
  const gd = panel.locator(M.plotly).first();
  await expect.poll(() => gd.evaluate((e) => (e.data ? e.data.length : 0)),
    { message: 'one trace per category', timeout: 60000 }).toBeGreaterThan(1);
  const names = await gd.evaluate((e) => e.data.map((t) => String(t.name)));
  note('legend: ' + names.join(' | '));
  expect(names.some((n) => !/^-?\d+$/.test(n)),
    'at least one category is named rather than numbered').toBe(true);
});
