/*
 * Scenario (i): an export says what it did, never does nothing, and the file
 * it hands over says where it comes from.
 *
 * The table widgets hand their CSV to the clipboard, which a browser exposes
 * only in a secure context — https, or localhost. On the plain-http address a
 * container is reached at from another machine, `navigator.clipboard` does
 * not exist; the widget then downloads the file instead, and the button says
 * which of the two happened. That branch is walked here by taking the
 * clipboard away from the page, the way plain http does.
 *
 * Every CSV carries a provenance header (application, date, what the table
 * is) and a dated, contextual file name — both decided server-side and
 * carried in the panel's payload; the widget writes the rows itself. The
 * Statistics view's export is walked here too — on a property of the file, and
 * on a difference made in the calculator, which is a recipe and no object of the
 * file: it must stay in the view all the same.
 */
import nodePath from 'node:path';
import {
  test, expect, M, DATASET, OUT_DIR,
  addToStats, compareRows, ensureProperty, showView, expandTree, dataTree, focusRenderView, openCompare, statsHold, treeRow, state,
} from '../lib/app.mjs';

/* The Data health panel and its export button. */
async function healthPanel(page) {
  await showView(page, 'Data health', page.locator(M.health));
  const panel = page.locator(M.dockPart).filter({ has: page.locator(M.health) })
    .filter({ visible: true }).first();
  await panel.locator(M.health).waitFor({ timeout: 60000 });
  return panel;
}

/* A download's text. */
async function textOf(file) {
  return (await file.createReadStream()).toArray()
    .then((chunks) => Buffer.concat(chunks).toString('utf8'));
}

/* The matrix of the Statistics view as a file: the clipboard taken away, so
   that it lands here rather than in a paste buffer this test cannot read. */
async function downloadMatrix(app, panel) {
  const { page, note } = app;
  const button = panel.locator(M.bar + ' button', { hasText: /^Copy CSV$/ });
  await expect(button, 'the Statistics view offers Copy CSV').toBeEnabled({ timeout: 30000 });
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard',
    { value: undefined, configurable: true }));
  const download = page.waitForEvent('download', { timeout: 30000 });
  await button.click();
  const file = await download;
  await page.evaluate(() => { delete navigator.clipboard; });
  await expect(panel.locator(M.bar + ' button', { hasText: /^Downloaded$/ }),
    'the button says which of the two it did').toHaveCount(1, { timeout: 10000 });
  note('downloaded: ' + file.suggestedFilename());
  expect(file.suggestedFilename(), 'a dated, contextual CSV file name')
    .toMatch(/^statistics_\d{4}-\d{2}-\d{2}\.csv$/);
  return (await textOf(file)).split('\n');
}

test('Copy CSV downloads the table when the browser has no clipboard, and says so', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  const panel = await healthPanel(page);
  const button = panel.locator('button', { hasText: /^Copy CSV$/ });
  await expect(button, 'the export button is offered').toBeEnabled({ timeout: 30000 });

  // Plain http: no clipboard object at all.
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard',
    { value: undefined, configurable: true }));
  const download = page.waitForEvent('download', { timeout: 15000 });
  await button.click();
  const file = await download;
  note('downloaded: ' + file.suggestedFilename());
  expect(file.suggestedFilename(), 'a dated, contextual CSV file name')
    .toMatch(/^health_\d{4}-\d{2}-\d{2}\.csv$/);
  await expect(panel.locator('button', { hasText: /^Downloaded$/ }),
    'the button says the file was downloaded').toHaveCount(1);
  const lines = (await textOf(file)).split('\n');
  note('csv head: ' + lines[0]);
  expect(lines[0], 'the CSV starts with its provenance header').toMatch(/^# fespp-on-trame /);
  const columns = lines.find((l) => !l.startsWith('#'));
  note('csv columns: ' + columns);
  expect(columns, 'the column line follows the header').toBe('severity,category,object,path,message,count');
  expect(lines, 'the widget says the rows are the filtered ones').toContain('# rows: as filtered on screen');
  // the files the session holds, in the panel and in the export
  const filesLine = lines.find((l) => l.startsWith('# files: '));
  note('csv files: ' + filesLine);
  const epcName = DATASET.files.map((f) => f.split(/[\\/]/).pop()).find((n) => /\.epc$/i.test(n));
  expect(filesLine, 'the header names the file imported').toContain(epcName + ' (');
  expect(filesLine, 'with what it added').toMatch(/\(\d+ objects\)/);
  const filesRow = (await panel.locator('.fhl-files').innerText()).replace(/\s+/g, ' ').trim();
  note('panel files row: ' + filesRow);
  expect(filesRow, 'the panel lists the files under its bar').toMatch(/^Files .*\.epc \d+/);

  // The clipboard back: the button reports a copy, or falls back to the
  // download when the driver denies the write — never silence.
  await page.evaluate(() => { delete navigator.clipboard; });
  await expect(button, 'the button label came back').toHaveCount(1, { timeout: 5000 });
  await button.click();
  await expect(panel.locator('button', { hasText: /^(Copied|Downloaded)$/ }),
    'the button says what happened').toHaveCount(1);
  note('with a clipboard: "' + (await panel.locator('button', { hasText: /^(Copied|Downloaded)$/ }).innerText()).trim() + '"');
});

test('the Statistics view exports a dated CSV with a provenance header', async ({ app }) => {
  const { page, note } = app;
  const name = DATASET.properties[0];
  const path = await ensureProperty(app, name);
  const panel = await addToStats(app, name, path);

  const lines = await downloadMatrix(app, panel);
  note('csv head: ' + lines[0]);
  expect(lines[0], 'the CSV starts with its provenance header').toMatch(/^# fespp-on-trame /);
  const columns = lines.find((l) => !l.startsWith('#')) || '';
  note('csv columns: ' + columns.slice(0, 80));
  expect(columns, 'the column line names where a row reads, then each measured statistic')
    .toMatch(/^property,representation,realization,time_step,(unit,)?value_count,no_value_count,min/);
  // the weighted means travel with the table, and the header says what
  // weighs them
  expect(columns, 'the two weighted means are exported beside the plain mean')
    .toContain('mean_volume_weighted');
  expect(columns, 'the pore-volume-weighted mean is exported too')
    .toContain('mean_pore_volume_weighted');
  expect(lines.some((l) => l.startsWith('# metrics: ') && l.includes('mean_volume_weighted is weighted by')),
    'the header says what each weighted mean is weighted by').toBe(true);

  // a screenshot of the view for visual review
  await panel.screenshot({ path: nodePath.join(OUT_DIR, 'statistics-view.png') });
  // and they are on screen, named by their convention, beside the plain mean
  const headers = await panel.locator('th').filter({ visible: true }).allInnerTexts();
  note('stat columns: ' + headers.join(' | ').slice(0, 200));
  expect(headers.some((h) => h.startsWith('Mean (V)')),
    'the matrix shows the volume-weighted mean').toBe(true);
  expect(headers.some((h) => h.startsWith('Mean (PV)')),
    'the matrix shows the pore-volume-weighted mean').toBe(true);
  // the five percentiles of the cell values, P10 and P90 around the
  // quartiles, on screen and in the file
  expect(headers.some((h) => h.startsWith('P10')), 'the matrix shows P10').toBe(true);
  expect(headers.some((h) => h.startsWith('P90')), 'the matrix shows P90').toBe(true);
  expect(columns, 'P10 and P90 are exported').toMatch(/,p10\b.*,p90\b/);
  // and a Sum only where adding the values means something: the smoke
  // porosity is a fraction (Euc), its row says so, and a block with no row
  // whose Sum means anything has no such column
  const row = (await compareRows(page)).find((r) => r.path === path && !r.support);
  const block = ((await state(page, 'ui_compare_blocks')) || []).find((b) => b.keys.includes(row.id));
  note('sum_meaningful: row ' + row.sum_meaningful + ', block ' + block.sum_meaningful + ' (uom ' + row.uom + ')');
  expect(typeof block.sum_meaningful, 'the block says whether its Sum means anything').toBe('boolean');
  const hasSum = headers.some((h) => h.startsWith('Sum'));
  expect(hasSum, 'the Sum column is there exactly when the block says it means something')
    .toBe(block.sum_meaningful);
  if (/^poro/i.test(name)) {
    expect(row.sum_meaningful, 'a porosity offers no Sum').toBe(false);
  }
});


test('a difference from the calculator joins the Statistics view and exports', async ({ app }) => {
  const { page, note } = app;
  const [a, b] = DATASET.properties;
  await ensureProperty(app, a);
  await ensureProperty(app, b);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);

  // The calculator, through the tree's door.
  await treeRow(tree, a).click({ button: 'right' });
  await page.locator(M.ctxMenu).waitFor({ timeout: 10000 });
  await page.locator(M.ctxItem, { hasText: /^Derived property$/ }).click();
  const calc = page.locator('.fcalc').filter({ visible: true }).first();
  await expect(calc, 'the calculator is on screen').toBeVisible({ timeout: 30000 });

  // A − B on the two loaded properties, then the row's Statistics button.
  const pickA = calc.locator('select.fcalc-pick[title^="A:"]');
  const pickB = calc.locator('select.fcalc-pick[title^="B:"]');
  await expect(pickA, 'the A − B row offers the properties').toBeVisible({ timeout: 30000 });
  const labels = await pickA.locator('option').allInnerTexts();
  note('A − B candidates: ' + labels.map((l) => l.trim()).join(' | '));
  const optionOf = (name) => labels.find((l) => l.trim().replace(/^ƒ /, '').startsWith(name));
  expect(optionOf(a), a + ' is offered').toBeDefined();
  expect(optionOf(b), b + ' is offered').toBeDefined();
  await pickA.selectOption({ label: optionOf(a) });
  await pickB.selectOption({ label: optionOf(b) });
  await calc.locator('button', { hasText: /^Create A − B$/ }).click();
  const row = calc.locator('.fcalc-def').filter({ hasText: a }).filter({ hasText: b }).first();
  await expect(row, 'the difference is listed among the derived properties of the grid')
    .toBeVisible({ timeout: 30000 });
  const derived = ((await state(page, 'ui_derived_props')) || [])
    .find((d) => d.expression.includes(a) && d.expression.includes(b));
  note('derived: ' + JSON.stringify(derived && { path: derived.path, role: derived.role }));
  expect(derived && derived.role, 'the row is marked a difference').toBe('difference');
  await row.locator('button[title^="Statistics"]').click();

  // In the view, and still there once its tree, which lists a recipe as a leaf
  // of its kind, has opened.
  await expect.poll(() => statsHold(page, derived.path),
    { message: 'the difference joins the Statistics view', timeout: 30000 }).toBe(true);
  await expect.poll(async () => (await compareRows(page))
    .some((r) => r.path === derived.path && Object.keys(r.metrics || {}).length > 0),
  { message: 'its row has figures', timeout: 60000 }).toBe(true);
  await page.waitForTimeout(1000);
  expect(await statsHold(page, derived.path), 'it stays once the view has opened').toBe(true);

  // Its export names the grid, not the geometry leaf the property hangs off.
  const panel = page.locator(M.dockPart).filter({ has: page.locator(M.compare) }).first();
  const lines = await downloadMatrix(app, panel);
  const item = lines.find((l) => l.startsWith('# item: ') && l.includes(derived.name)) || '';
  note('csv: ' + item);
  expect(item, 'the header lists the difference').toBeTruthy();
  expect(item, 'where it was read names the grid').not.toContain('SolidColor');

  // In the tree a formula has its eye and its menu, and no box: nothing to read
  // or unload, so its folder does not count it and still ticks what is under it.
  const statsPanel = await openCompare(page);
  const statsTree = statsPanel.locator(M.tree).first();
  await expandTree(statsTree);
  const rowOf = (title) => statsTree.locator(M.treeRow)
    .filter({ has: page.locator(M.treeTitle, { hasText: title }) }).first();
  const leaf = rowOf(derived.name);
  await expect(leaf, 'the formula is a leaf of the tree').toBeVisible({ timeout: 30000 });
  await expect(leaf.locator(M.treeCheck), 'it has no box').toHaveText('');
  await expect(leaf.locator(M.treeEye), 'it has its eye').toBeVisible();
  await leaf.click({ button: 'right' });
  await expect(page.locator(M.ctxMenu), 'it has its menu').toBeVisible({ timeout: 10000 });
  await page.keyboard.press('Escape');
  await expect(page.locator(M.ctxMenu)).toHaveCount(0, { timeout: 10000 });

  const { folder, leaves } = await statsTree.evaluate((root, title) => {
    const rows = [...root.querySelectorAll('.tn-row')];
    const pad = (el) => parseFloat(el.style.paddingLeft) || 0;
    const name = (el) => (el.querySelector('.tn-title') || {}).textContent || '';
    const at = rows.findIndex((r) => name(r).includes(title));
    let i = at;
    while (--i >= 0 && pad(rows[i]) >= pad(rows[at]));
    const kids = [];
    for (let j = i + 1; j < rows.length && pad(rows[j]) > pad(rows[i]); j++) {
      kids.push({ title: name(rows[j]), box: (rows[j].querySelector('.tn-check') || {}).textContent || '' });
    }
    return { folder: name(rows[i]), leaves: kids };
  }, derived.name);
  note(`the formula's folder ${folder}: ` + JSON.stringify(leaves));
  const unread = leaves.filter((l) => /☐/.test(l.box));
  if (unread.length === leaves.filter((l) => l.box).length && unread.length) {
    await rowOf(folder).locator(M.treeCheck).click();
    for (const l of unread) {
      await expect(rowOf(l.title).locator(M.treeCheck), l.title + ' is read by its folder')
        .toHaveText(/☑/, { timeout: 60000 });
    }
    expect(await state(page, 'selected_paths'), 'a recipe is never selected').not.toContain(derived.path);
  }
  expect(await statsHold(page, derived.path), 'the formula stays').toBe(true);
});
