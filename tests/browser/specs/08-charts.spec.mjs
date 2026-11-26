/*
 * Scenario (h): a chart keeps the reader's zoom across a refresh, and says how
 * much of the data it draws.
 *
 * Every plotly figure is rebuilt server-side and pushed whole; the client is
 * told, through `layout.uirevision`, which axes still mean the same thing, so
 * a zoom set by hand survives a refresh of the data and goes away when the
 * axis itself changes. Only a browser runs plotly, so only a browser can see
 * either happen — the unit tests check the keys, not their effect.
 *
 * The driven file has no time step and no realization, so the refresh used
 * here is a log toggle of the OTHER axis (the figure is recomputed and re-sent
 * exactly as it is for a new time step); the log toggle of the zoomed axis
 * is then the case that must re-frame.
 */
import {
  test, expect, M, DATASET,
  addToStats, compareItems, ensureProperty, expandTree, dataTree, focusRenderView, openCompare, treeRow, state,
} from '../lib/app.mjs';

/* A plotly graph div `gd`, once it holds at least one trace. */
async function figureDrawn(gd) {
  await expect.poll(() => gd.evaluate((e) => (e.data ? e.data.length : 0)),
    { message: 'the figure holds a trace', timeout: 60000 }).toBeGreaterThan(0);
}

/* The x axis as plotly holds it: its range, and whether it framed itself. */
function xAxis(gd) {
  return gd.evaluate((e) => {
    const ax = e._fullLayout.xaxis;
    return { range: ax.range.map((v) => Number(v.toFixed(6))),
      auto: !!ax.autorange, type: ax.type };
  });
}
const xRange = async (gd) => (await xAxis(gd)).range;

/* Zoom the way a reader does: a box dragged over the plot area. */
async function dragZoom(page, gd) {
  const box = await gd.locator('.nsewdrag').first().boundingBox();
  expect(box, 'the plot has a drag area').not.toBeNull();
  const y = box.y + box.height * 0.5;
  await page.mouse.move(box.x + box.width * 0.3, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.6, y - box.height * 0.2, { steps: 12 });
  await page.mouse.up();
}

/* Pick, in a widget select, the option whose text starts with `name`. */
async function pickOption(select, name) {
  const value = await select.evaluate((el, n) => {
    const opt = [...el.options].find((o) => o.textContent.trim().startsWith(n));
    return opt ? opt.value : null;
  }, name);
  expect(value, 'the select offers ' + name).not.toBeNull();
  await select.selectOption(value);
}

test('the cross-plot keeps its x zoom across a refresh and re-frames on an axis change', async ({ app }) => {
  const { page, note } = app;
  const [xName, yName] = DATASET.properties;
  const px = await ensureProperty(app, xName);
  const py = await ensureProperty(app, yName);
  await addToStats(app, xName, px);
  const panel = await addToStats(app, yName, py);
  await expect.poll(async () => ((await state(page, 'ui_compare_xplot_axes')) || {}).y,
    { message: 'a Y among the rows', timeout: 30000 }).toBeTruthy();
  const xplot = panel.locator('.fcp-chart').nth(1);
  const gd = xplot.locator(M.plotly).first();
  await figureDrawn(gd);
  const full = await xRange(gd);
  note('drawn: x range ' + JSON.stringify(full));

  // ONE caption line carries its two acts: drawn alone, pinned
  const cell = xplot.locator('.fxg-cell').first();
  await expect(cell.locator('.fxg-caption button[title="Show this chart alone"]'), 'the focus is on the caption').toHaveCount(1);
  await expect(cell.locator('.fxg-caption button[title^="Pin a snapshot"]'), 'the pin is on the caption').toHaveCount(1);

  await dragZoom(page, gd);
  await expect.poll(() => xRange(gd), { message: 'the drag zoomed the x axis' })
    .not.toEqual(full);
  const zoomed = await xRange(gd);
  note('zoomed: x range ' + JSON.stringify(zoomed));

  // A refresh: log Y recomputes and re-sends the whole figure. The x axis
  // still means the same thing, so its zoom must survive.
  const logY = xplot.locator('label', { hasText: /^log Y$/ }).locator('input');
  await logY.click();
  await expect.poll(() => gd.evaluate((e) => e._fullLayout.yaxis.type),
    { message: 'the figure was refreshed with a log Y axis', timeout: 30000 }).toBe('log');
  const kept = await xAxis(gd);
  note('after log Y: x ' + JSON.stringify(kept));
  expect(kept.range, 'the x zoom survived the refresh').toEqual(zoomed);
  expect(kept.auto, 'the x axis did not frame itself again').toBe(false);

  // The axis itself changes: log X is another framing, the zoom goes and
  // the axis frames itself on the data.
  const logX = xplot.locator('label', { hasText: /^log X$/ }).locator('input');
  await logX.click();
  await expect.poll(async () => (await xAxis(gd)).type,
    { message: 'the figure was refreshed with a log X axis', timeout: 30000 }).toBe('log');
  const reframed = await xAxis(gd);
  note('after log X: x ' + JSON.stringify(reframed));
  expect(reframed.auto, 'log X re-framed the x axis').toBe(true);
  await logX.click();
  await logY.click();
});

test('the Statistics view\'s distributions keep their zoom across a binning change', async ({ app }) => {
  const { page, note } = app;
  for (const name of DATASET.properties) await ensureProperty(app, name);

  const panel = await openCompare(page);
  // The view may already hold what 06-compare put in it; put in what
  // it does not hold yet — the EYE of a loaded property — so the scenario
  // runs alone as well.
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);
  for (const name of DATASET.properties) {
    const held = await compareItems(page);
    if (held.some((c) => c.title.includes(name))) continue;
    await treeRow(tree, name).locator(M.treeEye).click();
    await expect.poll(async () => (await compareItems(page)).length,
      { message: 'an item appears for ' + name, timeout: 30000 }).toBeGreaterThan(held.length);
  }

  // the histograms stand under the matrix of a kind tab, beside its cross-plot
  const kinds = (await state(page, 'ui_compare_kinds')) || [];
  await panel.locator(M.compareTab, { hasText: kinds[0].kind }).first().click();
  await expect(panel.locator('.fcp-chart').first().locator(M.plotly), 'the histograms, at the left').toHaveCount(1);
  const gd = panel.locator(M.plotly).first();
  await figureDrawn(gd);
  const full = await xRange(gd);
  note('drawn: x range ' + JSON.stringify(full));
  const meta = await state(page, 'ui_compare_dist_meta');
  note('drawn: ' + meta.kept + ' of ' + meta.total + ' values');
  expect(meta.kept, 'values are drawn').toBeGreaterThan(0);
  await expect(panel.locator(M.compareBadge), 'no count over the chart: the table says it').toHaveCount(0);

  await dragZoom(page, gd);
  await expect.poll(() => xRange(gd), { message: 'the drag zoomed the x axis' })
    .not.toEqual(full);
  const zoomed = await xRange(gd);

  // Another bin count: the bars are recomputed and re-sent, the axes are
  // the same axes — the zoom must survive.
  const bins = panel.locator('.fcp-chart').first().locator('.fp-hist-options input.fp-num');
  const was = await bins.inputValue();
  const bars = () => gd.evaluate((e) => e.data[0].x.length);
  const barsBefore = await bars();
  await bins.fill(String(Number(was) + 7));
  await bins.dispatchEvent('change');
  await expect.poll(bars, { message: 'the histogram was rebuilt with more bins', timeout: 30000 })
    .not.toBe(barsBefore);
  const kept = await xAxis(gd);
  note('after ' + (Number(was) + 7) + ' bins: x ' + JSON.stringify(kept));
  expect(kept.range, 'the x zoom survived the binning change').toEqual(zoomed);
  expect(kept.auto, 'the x axis did not frame itself again').toBe(false);
  await bins.fill(was);
  await bins.dispatchEvent('change');
});
