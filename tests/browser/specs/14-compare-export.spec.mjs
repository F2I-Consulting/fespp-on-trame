/*
 * Scenario (n): the matrix of the Statistics view names the unit of a block in
 * its header — or says the block mixes units — writes its cells by the shared
 * number rule, and exports raw metrics under the server's provenance header,
 * one unit per column.
 *
 * Mounted in a sandbox on the bundle of the working tree, on a payload
 * shaped like the server's (`ui_compare_*`): two porosity items declaring
 * different units, one permeability item with a realization and a time step.
 * The values are chosen to walk the number rule where it bites: a count in
 * the hundreds of thousands, a permeability in m², a variance below 1e-3.
 * Then the rows that follow an item, which the driven file cannot all give:
 * a blocked wellbore's and a 3D view's, under one item. Then the rows of one
 * block that differ: a Sum that means something on one of them only, a pin with
 * nothing to keep on a property that has no axis, a pinned copy at a named date.
 */
import fs from 'node:fs';
import path from 'node:path';
import { test, expect, APP_URL, faults, M } from '../lib/app.mjs';

const note = (line) => process.stdout.write('    · ' + line + '\n');

const SERVE = path.resolve(import.meta.dirname, '..', '..', '..', 'widgets', 'compare',
  'trame_fespp_compare', 'module', 'serve');
const SANDBOX = new URL('smoke-compare.html', APP_URL).toString();
const SANDBOX_HTML = '<!doctype html><html><head><meta charset="utf-8">'
  + '<script src="vue.global.js"></script>'
  + '<link rel="stylesheet" href="smoke-compare.css">'
  + '<script src="smoke-compare.umd.js"></script></head>'
  + '<body><div id="host" style="height:600px"></div></body></html>';

const CSV = {
  name: 'statistics_2026-09-11.csv',
  header: ['# fespp-on-trame 0.1.0 - statistics', '# date: 2026-09-11 14:03', '# baseline: PHIF',
    '# items: 3', '# n/a = not available'],
};
function payload() {
  const chip = (key, title, kind, uom, extra) => ({
    key, uid: key, path: '/' + key, title, rep: 'Geogrid', kind, uom, real: null, ts: null,
    reals: [], ts_opts: [], baseline: false, align: 'ok', ...extra,
  });
  return {
    chips: [chip('a', 'PHIF', 'porosity', 'm3/m3', { baseline: true }),
      chip('b', 'PORO_2', 'porosity', '%'), chip('c', 'PERMX', 'permeability', 'mD', { real: 3, ts: 1 })],
    blocks: [{ kind: 'porosity', keys: ['a', 'b'], uom: '', uom_mixed: true },
      { kind: 'permeability', keys: ['c'], uom: 'mD', uom_mixed: false }],
    rows: {
      a: { label: 'PHIF', rep: 'Geogrid', kind: 'porosity', uom: 'm3/m3', real: null, ts: null,
        metrics: { Cardinality: 926808, Mean: 0.187654321, Variance: 0.000123 }, profile: '', note: '' },
      b: { label: 'PORO_2', rep: 'Geogrid', kind: 'porosity', uom: '%', real: null, ts: null,
        metrics: { Cardinality: 926808, Mean: 18.7654321, Variance: 1.23 }, profile: '', note: '' },
      c: { label: 'PERMX', rep: 'Geogrid', kind: 'permeability', uom: 'mD', real: 3, ts: 1,
        metrics: { Cardinality: 1234, Mean: 1.2e-14, Minimum: 0 }, profile: '', note: '' },
    },
    visibleMetrics: ['Cardinality', 'Mean', 'Variance'],
    // what the server writes under the cells of the baseline's kind
    deltas: { b: { Cardinality: { abs: 0, rel: 0 }, Mean: { abs: 18.577846, rel: 9900.0 },
      Variance: { abs: 1.229877, rel: 999900.0 } } },
    csv: CSV,
  };
}

/* One item, read also on a blocked wellbore and on what a 3D view draws: a Sum
   that means nothing in this block, a mean along the hole on one of its rows,
   a note on the item's hover. */
function followingPayload() {
  const item = { path: '/a', title: 'PHIF', rep: 'Geogrid', kind: 'porosity', uom: 'm3/m3', pinned: false,
    reals: [{ title: 'real 0', value: 0 }, { title: 'real 1', value: 1 }], ts_opts: [], real: null, ts: null,
    real_read: 0, ts_text: '', note: '', profile: '', value_type: 'Continuous', support: '', follows: '' };
  const following = (support, label, supportLabel, metrics) => ({
    ...item, reals: [], support, follows: 'a', label, support_label: supportLabel, metrics,
  });
  return {
    chips: [{ key: '/a||', uid: 'a', path: '/a', title: 'PHIF', kind: 'porosity', baseline: true }],
    blocks: [{ kind: 'porosity', keys: ['a', 'a@/w1', 'a@view:v1'], uom: 'm3/m3', uom_mixed: false,
      sum_meaningful: false, has_length: true }],
    rows: {
      a: { ...item, label: 'PHIF', metrics: { Cardinality: 100, Mean: 0.2, Sum: 20 },
        note: 'No porosity property on Geogrid: the pore-volume-weighted mean is not reported.' },
      'a@/w1': following('/w1', 'PHIF on W1', 'Blocked wellbore · W1',
        { Cardinality: 10, Mean: 0.25, 'Mean (L)': 0.21 }),
      'a@view:v1': following('view:v1', 'PHIF On 3D view 1', '3D view 1', { Cardinality: 40, Mean: 0.3 }),
    },
    visibleMetrics: ['Cardinality', 'Mean', 'Mean (L)', 'Sum'],
    csv: CSV,
  };
}

/* The rows of one tab that differ: a fraction beside a volume, whose block keeps
   its Sum for the row where it means something; a property with nothing to pin a
   copy at; a time series, its copy pinned at a date, a row at a step with no words. */
function differentRowsPayload() {
  const row = (label, metrics, extra) => ({ path: '/' + label, label, title: label, rep: 'Geogrid',
    kind: 'no kind', uom: '', pinned: false, reals: [], ts_opts: [], real: null, ts: null,
    real_read: null, ts_text: '', note: '', profile: '', support: '', follows: '', metrics, ...extra });
  const steps = [{ title: '2022-01-01', value: 0 }, { title: '2022-06-01', value: 1 }];
  const rows = {
    vol: row('VOL', { Cardinality: 10, Mean: 5, Sum: 50 }, { sum_meaningful: true }),
    phi: row('PHI', { Cardinality: 10, Mean: 0.2, Sum: 2 }, { sum_meaningful: false }),
    soil: row('SOIL', { Cardinality: 10, Mean: 0.5, Sum: 5 },
      { sum_meaningful: true, ts_opts: steps, ts_text: '2022-01-01' }),
    copy: row('SOIL', { Cardinality: 10, Mean: 0.6, Sum: 6 },
      { sum_meaningful: true, ts_opts: steps, ts: 1, ts_text: '2022-06-01', pinned: true }),
    raw: row('RAW', { Cardinality: 10, Mean: 1, Sum: 10 }, { sum_meaningful: true, ts: 2 }),
  };
  return {
    chips: Object.keys(rows).map((uid) => ({ key: uid, uid, path: rows[uid].path, title: rows[uid].title,
      kind: 'no kind', baseline: uid === 'vol' })),
    blocks: [{ kind: 'no kind', keys: Object.keys(rows), uom: '', uom_mixed: false, sum_meaningful: true }],
    rows,
    annotations: { phi: { Mean: 'neg', Sum: 'neg' }, vol: { Mean: 'pos', Sum: 'pos' } },
    deltas: { phi: { Mean: { abs: -4.8, rel: -96 }, Sum: { abs: -48, rel: -96 } },
      vol: { Mean: { abs: 4.8, rel: 2400 }, Sum: { abs: 48, rel: 2400 } } },
    visibleMetrics: ['Cardinality', 'Mean', 'Sum'],
    csv: CSV,
  };
}

/* The sandbox: a page holding the bundle of the working tree, and what its
   console says. */
async function sandbox(browser) {
  const messages = [];
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') {
      messages.push({ kind: 'console.' + m.type(), text: m.text().replace(/\s+/g, ' ') });
    }
  });
  page.on('pageerror', (e) => messages.push({ kind: 'uncaught', text: String(e.message) }));

  const bundle = path.join(SERVE, 'trame_fespp_compare.umd.js');
  expect(fs.existsSync(bundle), 'the compare bundle is built: ' + bundle).toBe(true);
  await page.route(SANDBOX, (r) => r.fulfill({ contentType: 'text/html; charset=utf-8', body: SANDBOX_HTML }));
  await page.route('**/smoke-compare.umd.js', (r) => r.fulfill({
    contentType: 'application/javascript; charset=utf-8', body: fs.readFileSync(bundle) }));
  await page.route('**/smoke-compare.css', (r) => r.fulfill({
    contentType: 'text/css; charset=utf-8', body: fs.readFileSync(path.join(SERVE, 'style.css')) }));
  await page.goto(SANDBOX);
  return { context, page, messages };
}

/* A download's lines. */
async function linesOf(file) {
  const text = await (await file.createReadStream()).toArray()
    .then((chunks) => Buffer.concat(chunks).toString('utf8'));
  return text.split('\n');
}

test('the matrix names its units, writes its cells by the rule and exports raw metrics', async ({ browser }) => {
  const { context, page, messages } = await sandbox(browser);

  await page.evaluate((p) => {
    window.Vue.createApp({
      data: () => p,
      template: '<compare-panel :chips="chips" :blocks="blocks" :rows="rows" :deltas="deltas"'
        + ' :visible-metrics="visibleMetrics" :csv="csv" tab="porosity" baseline="a" />',
    }).use(window.trame_fespp_compare).mount('#host');
  }, payload());
  const blocks = page.locator('.fcp-block');
  await expect(blocks, 'one block per kind').toHaveCount(2, { timeout: 15000 });

  // The Property header says the unit; units that differ have a column.
  const unitTh = blocks.nth(0).locator('th', { hasText: /^Unit$/ });
  expect(await unitTh.getAttribute('title'), 'the column names the units').toMatch(/m3\/m3, %/);
  await expect(blocks.nth(1).locator('.fcp-th-item'), 'the permeability block names its unit')
    .toHaveText('Property (mD)');
  const varianceTh = blocks.nth(1).locator('th.fcp-th-metric', { hasText: /^Variance/ });
  expect(await varianceTh.getAttribute('title'), 'a metric header names the unit at its power')
    .toBe('Variance ((mD)²) — click to sort');

  // The cells: a count in full, a quantity to four digits, scientific outside the band.
  const cells = async (i, row) => (await blocks.nth(i).locator('tbody tr').nth(row)
    .locator('td.fcp-num').allInnerTexts()).map((t) => t.trim());
  const phif = await cells(0, 0);
  const permx = await cells(1, 0);
  note('PHIF: ' + phif.join(' | ') + ' — PERMX: ' + permx.join(' | '));
  expect(phif, 'the three counts, mean and variance of PHIF')
    .toEqual(['926\u2009808', '926\u2009808', '\u2013', '0.1877', '1.23e-4']);
  expect(permx, 'the three counts, mean and a missing variance of PERMX')
    .toEqual(['1\u2009234', '1\u2009234', '\u2013', '1.2e-14', '\u2013']);
  // under a cell of the baseline's kind: the difference to the baseline,
  // signed, by the same rule, then in percent of the baseline
  const poro2 = (await blocks.nth(0).locator('tbody tr').nth(1).locator('.fcp-delta').allInnerTexts())
    .map((t) => t.trim());
  note('PORO_2 deltas: ' + poro2.join(' | '));
  expect(poro2, 'a count delta in full, a quantity delta to four digits, the percent beside')
    .toEqual(['0 (0 %)', '+18.58 (+9\u2009900 %)', '+1.23 (+999\u2009900 %)']);
  expect(await blocks.nth(0).locator('tbody tr').nth(0).locator('.fcp-delta').count(),
    'the baseline row carries no delta').toBe(0);

  // The export: raw metrics, every metric, one unit per column.
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard',
    { value: undefined, configurable: true }));
  const button = page.locator(M.compare + ' ' + M.bar + ' button', { hasText: /^Copy CSV$/ });
  await expect(button, 'the matrix offers Copy CSV').toBeEnabled();
  const download = page.waitForEvent('download', { timeout: 15000 });
  await button.click();
  const file = await download;
  note('downloaded: ' + file.suggestedFilename());
  expect(file.suggestedFilename(), 'the name the server decided').toBe(CSV.name);
  const lines = await linesOf(file);
  note('csv: ' + lines.slice(0, 9).map((l) => l.slice(0, 80)).join(' ⏎ '));
  expect(lines.slice(0, CSV.header.length), 'the header lines are the server\'s, verbatim')
    .toEqual(CSV.header);
  const kinds = lines.filter((l) => l.startsWith('# kind: '));
  expect(kinds, 'one kind line per block, the unit or the mixing said')
    .toEqual(['# kind: porosity (mixed units)', '# kind: permeability (mD)']);
  const porosityColumns = lines[lines.indexOf(kinds[0]) + 1];
  expect(porosityColumns, 'a mixed block gets a unit column and unitless metric headers, every metric named')
    .toMatch(/^property,representation,realization,time_step,unit,value_count,no_value_count,min,max,mean,mean_volume_weighted,mean_pore_volume_weighted,std_dev,variance,sum,p10,q1,median,q3,p90,skewness,kurtosis,m2,m3,m4$/);
  const permColumns = lines[lines.indexOf(kinds[1]) + 1];
  expect(permColumns, 'a block with one unit writes it at its power in each header, every metric named')
    .toMatch(/^property,representation,realization,time_step,value_count,no_value_count,min \(mD\),max \(mD\),mean \(mD\),mean_volume_weighted \(mD\),mean_pore_volume_weighted \(mD\),std_dev \(mD\),variance \(\(mD\)\^2\),sum \(mD\),p10 \(mD\),q1 \(mD\),median \(mD\),q3 \(mD\),p90 \(mD\),skewness,kurtosis,m2 \(\(mD\)\^2\),m3 \(\(mD\)\^3\),m4 \(\(mD\)\^4\)$/);
  const permRow = lines[lines.indexOf(kinds[1]) + 2].split(',');
  expect(permRow.slice(0, 9), 'raw values, n/a for a metric the row lacks')
    .toEqual(['PERMX', 'Geogrid', '3', '1', '1234', 'n/a', '0', 'n/a', '1.2e-14']);
  const phifRow = lines[lines.indexOf(kinds[0]) + 2].split(',');
  expect(phifRow.slice(0, 5), 'the unit column of a mixed block')
    .toEqual(['PHIF', 'Geogrid', '', '', 'm3/m3']);
  expect(phifRow[9], 'the mean is raw, not the four-digit text').toBe('0.187654321');

  const seen = faults(messages);
  expect(seen.map((m) => m.kind + ': ' + m.text), 'the console stayed silent').toEqual([]);
  await context.close();
});

test('the rows of a block differ: a Sum, a pin and a date say so row by row', async ({ browser }) => {
  const { context, page, messages } = await sandbox(browser);
  await page.evaluate((p) => {
    window.gestures = [];
    window.panel = window.Vue.createApp({
      data: () => ({ ...p, baseline: 'vol' }),
      methods: { said(e) { window.gestures.push(e); } },
      template: '<compare-panel :chips="chips" :blocks="blocks" :rows="rows" :annotations="annotations"'
        + ' :deltas="deltas" :visible-metrics="visibleMetrics" :csv="csv" tab="no kind"'
        + ' :baseline="baseline" @set="said" />',
    }).use(window.trame_fespp_compare).mount('#host');
  }, differentRowsPayload());
  const items = page.locator(M.compareItem);
  await expect(items, 'one row per item').toHaveCount(5, { timeout: 15000 });

  // A column of the block: the cell of a row, by the metric's header.
  const heads = (await page.locator('th.fcp-th-metric').allInnerTexts()).map((t) => t.trim());
  note('metric columns: ' + heads.join(' | '));
  const cellOf = (row, name) => page.locator(M.compareItem).filter({ hasText: row }).first()
    .locator('td.fcp-num').nth(heads.findIndex((h) => h.startsWith(name)));
  expect(heads.some((h) => h.startsWith('Sum')), 'a row of the block has a Sum that means something').toBe(true);

  // Against a baseline with a Sum: the fraction writes a dash, no difference, no tint.
  await expect(cellOf('PHI', 'Sum'), 'a Sum that means nothing is a dash').toHaveText('\u2013');
  await expect(cellOf('PHI', 'Sum').locator('.fcp-delta'), 'with no difference').toHaveCount(0);
  await expect(cellOf('PHI', 'Sum'), 'and no tint').not.toHaveClass(/fcp-cell-/);
  await expect(cellOf('PHI', 'Mean').locator('.fcp-delta'), 'its mean is read as ever').toHaveCount(1);
  await expect(cellOf('PHI', 'Mean'), 'tinted').toHaveClass(/fcp-cell-neg/);

  // Against a baseline whose Sum means nothing: the figure stays, read against nothing.
  await page.evaluate(() => { window.panel.baseline = 'phi'; });
  await expect(page.locator(M.compareItem + '.fcp-row-base'), 'the yellow moved').toContainText('PHI');
  await expect(cellOf('VOL', 'Sum'), 'its own figure').toHaveText('50');
  await expect(cellOf('VOL', 'Sum').locator('.fcp-delta'), 'no difference to a figure that means nothing').toHaveCount(0);
  await expect(cellOf('VOL', 'Sum'), 'and no tint').not.toHaveClass(/fcp-cell-/);
  await expect(cellOf('VOL', 'Mean').locator('.fcp-delta'), 'its mean is read against the baseline').toHaveCount(1);

  // A property with nothing to keep: no pin on the row, the menu's entry says why.
  const menu = page.locator(M.compareRowMenu);
  const pin = menu.locator('.fp-menu-item', { hasText: 'Pin a copy of this row' });
  const plain = items.filter({ hasText: 'VOL' }).first();
  await expect(plain.locator('button[title^="Pin a copy"]'), 'no pin on a row with nothing to keep').toHaveCount(0);
  await plain.locator('.fcp-item-title').click({ button: 'right' });
  await expect(pin, 'greyed').toHaveAttribute('aria-disabled', 'true');
  expect(await pin.getAttribute('title'), 'with why').toContain('no realization and no time step');
  await page.keyboard.press('Escape');
  await expect(menu, 'Escape closes it').toHaveCount(0);

  // A time series pins, by the button as by the menu.
  const series = items.filter({ has: page.locator('select') }).first();
  await expect(series.locator('button[title^="Pin a copy"]'), 'its pin is on the row').toHaveCount(1);
  await series.locator('.fcp-item-title').click({ button: 'right' });
  await expect(pin, 'offered').not.toHaveAttribute('aria-disabled', 'true');
  await pin.click();
  expect((await page.evaluate(() => window.gestures)).at(-1), 'the gesture names the row').toEqual(['pin', 'soil']);

  // The copy says its date on the row and takes itself out from its menu.
  const copy = items.filter({ has: page.locator('button[title="Remove this pinned row"]') }).first();
  await expect(copy.locator('.fcp-td-axis').first(), 'its time step in words').toHaveText('2022-06-01');
  await copy.locator('.fcp-item-title').click({ button: 'right' });
  await expect(menu.locator('.fp-menu-item', { hasText: 'Remove this pinned row' }), 'its own entry').toHaveCount(1);
  await page.keyboard.press('Escape');
  await expect(menu, 'Escape closes it').toHaveCount(0);

  // In the file: the Sum the screen hides stays, and the time step is a date
  // wherever the row has one, an index only where it has no words.
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard',
    { value: undefined, configurable: true }));
  const download = page.waitForEvent('download', { timeout: 15000 });
  await page.locator(M.compare + ' ' + M.bar + ' button', { hasText: /^Copy CSV$/ }).click();
  const lines = await linesOf(await download);
  const at = lines.findIndex((l) => l.startsWith('# kind: no kind'));
  const columns = lines[at + 1].split(',');
  const fileRows = lines.slice(at + 2, at + 7).map((l) => l.split(','));
  note('time steps in the file: ' + fileRows.map((r) => r[columns.indexOf('time_step')]).join(' | '));
  expect(fileRows.map((r) => r[columns.indexOf('time_step')]), 'one nature down the column')
    .toEqual(['', '', '2022-01-01', '2022-06-01', '2']);
  expect(fileRows[1][columns.indexOf('sum')], 'the raw figure of a Sum the screen hides').toBe('2');

  const seen = faults(messages);
  expect(seen.map((m) => m.kind + ': ' + m.text), 'the console stayed silent').toEqual([]);
  await context.close();
});

test('the rows that follow an item: where they read, no picker, no pin, a menu that says why', async ({ browser }) => {
  const { context, page, messages } = await sandbox(browser);
  await page.evaluate((p) => {
    window.gestures = [];
    window.Vue.createApp({
      data: () => p,
      methods: { said(e) { window.gestures.push(e); } },
      template: '<compare-panel :chips="chips" :blocks="blocks" :rows="rows"'
        + ' :visible-metrics="visibleMetrics" :csv="csv" tab="porosity" baseline="a" @set="said" />',
    }).use(window.trame_fespp_compare).mount('#host');
  }, followingPayload());
  const items = page.locator(M.compareItem);
  await expect(items, 'the item and its two rows').toHaveCount(3, { timeout: 15000 });
  await expect(page.locator(M.compareFollows), 'two of them follow it').toHaveCount(2);

  // A block's columns: no Sum when no row's Sum means anything, Mean (L) when a
  // row has it, each with its unit; what a row has to say is on its hover.
  const heads = (await page.locator('th.fcp-th-metric').allInnerTexts()).map((t) => t.trim());
  note('metric columns: ' + heads.join(' | '));
  expect(heads, 'the mean along the hole, in its unit').toContain('Mean (L) (m3/m3)');
  expect(heads.some((h) => h.startsWith('Sum')), 'no Sum on this block').toBe(false);
  await expect(page.locator('.fcp-block-note'), 'no sentence under the block').toHaveCount(0);
  await expect(items.nth(0), 'the note is on the row\'s hover')
    .toHaveAttribute('title', /No porosity property on Geogrid/);

  // A following row says what it reads on and the realization it reads; the
  // item picks, its placeholder the one read.
  const reps = (await page.locator('.fcp-item-rep').allInnerTexts()).map((t) => t.trim());
  expect(reps, 'in place of the representation').toEqual(['Geogrid', 'Blocked wellbore · W1', '3D view 1']);
  await expect(items.nth(0).locator('select'), 'the item has its picker').toHaveCount(1);
  await expect(items.nth(0).locator('select option').first(), 'its first line is what it reads').toHaveText('0');
  for (const i of [1, 2]) {
    await expect(items.nth(i).locator('select'), 'no picker').toHaveCount(0);
    await expect(items.nth(i).locator('button[title^="Pin a copy"]'), 'no pin').toHaveCount(0);
    await expect(items.nth(i).locator('.fcp-td-axis').first(), 'the realization it reads').toHaveText('0');
  }
  // The menu of a following row refuses, and says why.
  const menu = page.locator(M.compareRowMenu);
  const menuItem = (label) => menu.locator('.fp-menu-item', { hasText: label });
  await items.nth(2).locator('.fcp-item-title').click({ button: 'right' });
  await expect(menu, 'the row menu opens').toHaveCount(1);
  await expect(menuItem('Set as baseline'), 'never the baseline').toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('Escape');
  await expect(menu, 'Escape closes it').toHaveCount(0);

  // In the file: every metric, the mean along the hole among them, and where
  // each row read.
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard',
    { value: undefined, configurable: true }));
  const download = page.waitForEvent('download', { timeout: 15000 });
  await page.locator(M.compare + ' ' + M.bar + ' button', { hasText: /^Copy CSV$/ }).click();
  const lines = await linesOf(await download);
  const at = lines.findIndex((l) => l.startsWith('# kind: porosity'));
  const columns = lines[at + 1].split(',');
  note('csv columns: ' + columns.join(',').slice(0, 120));
  expect(columns, 'the mean along the hole, at its place').toContain('mean_length_weighted (m3/m3)');
  expect(columns, 'a Sum the screen hides stays in the file').toContain('sum (m3/m3)');
  const well = lines[at + 3].split(',');
  expect(well.slice(0, 4), 'where it read, the realization it read').toEqual(['PHIF on W1', 'Blocked wellbore · W1', '0', '']);
  expect(well[columns.indexOf('mean_length_weighted (m3/m3)')], 'the raw figure').toBe('0.21');

  const seen = faults(messages);
  expect(seen.map((m) => m.kind + ': ' + m.text), 'the console stayed silent').toEqual([]);
  await context.close();
});
