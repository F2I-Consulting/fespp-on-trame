/*
 * Scenario (m): the zones table of the well-log view exports a CSV of raw
 * values, with n/a where a figure could not be evaluated and the reason in
 * a `note` column; on screen a depth keeps its centimetres (fmtFixed, not
 * the four significant digits of a measured quantity).
 *
 * The file the pass drives has no well, so the widget is mounted here on its
 * own — in a sandbox page whose only scripts are the application's Vue build
 * and the well-log bundle of the WORKING TREE (served straight from disk,
 * the same file the container injects) — on a payload shaped like the
 * server's: one well with two zones, one evaluable, one not. The button, the
 * file name and header the server decided, and the rows the widget writes
 * from its raw props are what is under test; the server's side of the seam
 * (the `csv` key of `welllog_data`) is covered by the headless harness.
 */
import fs from 'node:fs';
import path from 'node:path';
import { test, expect, APP_URL, faults } from '../lib/app.mjs';

const note = (line) => process.stdout.write('    · ' + line + '\n');

const SERVE = path.resolve(import.meta.dirname, '..', '..', '..', 'widgets', 'welllog',
  'trame_welllog', 'module', 'serve');
const SANDBOX = new URL('smoke-zones.html', APP_URL).toString();
const SANDBOX_HTML = '<!doctype html><html><head><meta charset="utf-8">'
  + '<script src="vue.global.js"></script>'
  + '<link rel="stylesheet" href="smoke-welllog.css">'
  + '<script src="smoke-welllog.umd.js"></script></head>'
  + '<body><div id="host" style="height:600px"></div></body></html>';

// what the server publishes under `welllog_data` for one well under cutoffs:
// the Upper zone evaluated, the Lower one not (its cutoff log is not logged)
const CSV = {
  name: 'zones_W1_2026-09-11.csv',
  header: ['# fespp-on-trame 0.1.0 - zones', '# date: 2026-09-11 14:03', '# wells: W1',
    '# n/a = not available'],
};
// The well is deviated: the zones are drawn on measured depth and every
// thickness is summed on the vertical, so Gross is 40 where the drawn top and
// base are 50 apart — the columns must say which is which.
function payload() {
  const zone = (name, top, bottom, top_tvd, bottom_tvd, extra) => ({
    name, color: '#c8a2c8', top, bottom, thickness: bottom - top, source: 'markers',
    top_tvd, bottom_tvd, thickness_tvd: bottom_tvd - top_tvd, tvd_na: null, ...extra,
  });
  return {
    wells: [{
      name: 'W1', color: '#1565c0', depthRef: 'MD', integrationRef: 'TVD',
      depth: { min: 900, max: 1200 }, tvd_up_hole: 0,
      // one track, so the pay band is actually shaded: the band is DRAWN,
      // i.e. on measured depth, near the base of a 900–1200 track, while the
      // same pay on the vertical sits at the very top — the two cannot be
      // confused on this well, which is the point of the fixture
      tracks: [{
        kind: 'porosity', unit: 'm3/m3', logScale: false,
        curves: [{ name: 'PHIF', color: '#c62828', unit: 'm3/m3', range: [0, 0.4],
          missing: false, samples: [[0.2, 950], [0.25, 1100], [0.2, 1190]] }],
      }],
      tops: [], absent: {},
      pay: [[1150, 1200]], pay_tvd: [[900, 940]], pay_na: [], pay_na_why: {},
      summation: { phi: 'PHIF', phi_candidates: [], phi_absent: {}, sw: 'SW', sw_candidates: [], sw_absent: {} },
      zones: [
        zone('Upper', 1000, 1050, 900, 940, {
          net: 20, ntg: 0.5, phih: 4.2, hcph: 2.1, pay_na: [],
          curves: [{ name: 'PHIF', unit: 'm3/m3', n: 100, mean: 0.21, min: 0.1, max: 0.3,
            p10: 0.12, p50: 0.2, p90: 0.29, n_pay: 40, mean_pay: 0.25 }],
        }),
        zone('Lower', 1050.5725, 1120.43, 940, 995.5, {
          net: null, ntg: null, phih: null, hcph: null, pay_na: ['VSH'], curves: [] }),
      ],
    }],
    markers: [], flattenOn: null, csv: CSV,
  };
}

test('the zones table exports raw values, n/a where a figure could not be evaluated', async ({ browser }) => {
  const messages = [];
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') {
      messages.push({ kind: 'console.' + m.type(), text: m.text().replace(/\s+/g, ' ') });
    }
  });
  page.on('pageerror', (e) => messages.push({ kind: 'uncaught', text: String(e.message) }));

  const bundle = path.join(SERVE, 'trame_welllog.umd.js');
  expect(fs.existsSync(bundle), 'the well-log bundle is built: ' + bundle).toBe(true);
  await page.route(SANDBOX, (r) => r.fulfill({ contentType: 'text/html; charset=utf-8', body: SANDBOX_HTML }));
  await page.route('**/smoke-welllog.umd.js', (r) => r.fulfill({
    contentType: 'application/javascript; charset=utf-8', body: fs.readFileSync(bundle) }));
  await page.route('**/smoke-welllog.css', (r) => r.fulfill({
    contentType: 'text/css; charset=utf-8', body: fs.readFileSync(path.join(SERVE, 'style.css')) }));
  await page.goto(SANDBOX);

  // the tracks laid out on their measured depth, the zone statistics card's
  // content under them, as the log view docks it
  await page.evaluate((data) => {
    window.Vue.createApp({
      data: () => ({ data, cutoffs: [{ curve: 'VSH', op: '<=', value: 0.4 }] }),
      template: '<div style="display:flex; flex-direction:column; height:600px">'
        + '<div style="flex:1 1 auto; position:relative; min-height:0">'
        + '<well-log-correlation :data="data" align="MD" /></div>'
        + '<div style="flex:0 0 260px; min-height:0"><well-log-zones :data="data" :cutoffs="cutoffs" /></div>'
        + '</div>',
    }).use(window.trame_welllog).mount('#host');
  }, payload());
  const table = page.locator('table.wlc-zones-table');
  await expect(table, 'the zones table renders').toBeVisible({ timeout: 15000 });
  const rows = await table.locator('tbody tr').count();
  note('zones table: ' + rows + ' row(s)');
  expect(rows, 'a gross row per zone and one per curve').toBe(3);
  // a depth on screen: two decimals and the thousands grouped — 1050.5725
  // reads "1 050.57", not "1 051"
  const lowerCells = (await table.locator('tbody tr').nth(2).locator('td').allInnerTexts())
    .map((t) => t.trim());
  note('Lower row: ' + lowerCells.slice(0, 5).join(' | '));
  expect(lowerCells[2], 'the zone top keeps its centimetres').toBe('1 050.57');
  expect(lowerCells[3], 'the zone base too').toBe('1 120.43');

  // the depths are drawn along the hole, the thicknesses summed on the
  // vertical: Gross (TVD) reads 55.50 where the hole ran 69.86 — and the
  // along-hole figure the band is drawn over stays beside it, never replaced
  expect(lowerCells[4], 'Gross (MD) is the drawn interval').toBe('69.86');
  expect(lowerCells[5], 'Gross (TVD) is the VERTICAL thickness').toBe('55.50');
  const heads = (await table.locator('thead th').allInnerTexts()).map((t) => t.trim());
  note('heads: ' + heads.slice(2, 10).join(' | '));
  expect(heads.slice(2, 8), 'each depth column names the axis it follows')
    .toEqual(['Top (MD)', 'Base (MD)', 'Gross (MD)', 'Gross (TVD)', 'Net (TVD)', 'N/G (TVD)']);
  expect(heads[8].startsWith('Φ·h (TVD)'), 'and so does the porosity-thickness').toBe(true);

  // THE PAY BAND IS SHADED ON THE DRAWN AXIS. `pay` is MD [1150, 1200] on a
  // 900–1200 track, so the green band belongs to the bottom sixth; shading
  // the vertical intervals instead (TVD [900, 940], what `pay_tvd` holds)
  // would put it at the very top of every track, hundreds of metres above
  // the rock it flags.
  const band = page.locator('rect[fill="#7ed321"]');
  await expect(band, 'the pay is shaded').toHaveCount(1);
  const place = await band.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const svg = el.ownerSVGElement.getBoundingClientRect();
    return { top: (r.top - svg.top) / svg.height, bottom: (r.bottom - svg.top) / svg.height };
  });
  note('pay band at ' + place.top.toFixed(2) + '…' + place.bottom.toFixed(2) + ' of the plot');
  expect(place.top, 'the band is drawn where the MEASURED depth puts it').toBeGreaterThan(0.5);
  const notes = (await page.locator('.wlc-zones-notes div').allInnerTexts()).map((t) => t.trim());
  note('note: ' + notes[0]);
  expect(notes, 'the panel says which axis the depths are on and which is integrated')
    .toContain('Top and base are on measured depth; thicknesses, N/G and the Φ·h'
      + ' sums are integrated on true vertical depth.');

  // Plain http: no clipboard, the file is downloaded.
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard',
    { value: undefined, configurable: true }));
  const button = page.locator('.wlc-zones-head button', { hasText: /^Copy CSV$/ });
  await expect(button, 'the zones table offers Copy CSV').toBeEnabled();
  const download = page.waitForEvent('download', { timeout: 15000 });
  await button.click();
  const file = await download;
  note('downloaded: ' + file.suggestedFilename());
  expect(file.suggestedFilename(), 'the name the server decided').toBe(CSV.name);
  await expect(page.locator('.wlc-zones-head button', { hasText: /^Downloaded$/ }),
    'the button says the file was downloaded').toHaveCount(1);

  const text = await (await file.createReadStream()).toArray()
    .then((chunks) => Buffer.concat(chunks).toString('utf8'));
  const lines = text.split('\n');
  note('csv: ' + lines.slice(0, 7).map((l) => l.slice(0, 90)).join(' ⏎ '));
  expect(lines.slice(0, CSV.header.length), 'the header lines are the server\'s, verbatim')
    .toEqual(CSV.header);
  expect(lines[CSV.header.length], 'one unit and one axis per column header')
    .toBe('well,depth_axis,zone,zone_source,top (depth_axis),base (depth_axis),top_tvd,base_tvd,'
      + 'gross (depth_axis),gross_tvd,net_tvd,ntg (fraction),phih_tvd,hcph_tvd,'
      + 'curve,unit,n,mean,mean_pay,p10,p50,p90,min,max,note');
  const upper = lines[CSV.header.length + 1].split(',');
  const phif = lines[CSV.header.length + 2].split(',');
  const lower = lines[CSV.header.length + 3].split(',');
  expect(upper.slice(0, 14), 'the gross row carries the raw zone figures, both axes')
    .toEqual(['W1', 'MD', 'Upper', 'markers', '1000', '1050', '900', '940',
      '50', '40', '20', '0.5', '4.2', '2.1']);
  expect(upper.slice(14, 24).every((c) => c === ''), 'a gross row has no curve figure').toBe(true);
  expect(phif.slice(14, 19), 'the curve row carries the raw curve figures')
    .toEqual(['PHIF', 'm3/m3', '100', '0.21', '0.25']);
  // raw, so the along-hole gross carries the last bits of 1120.43 − 1050.5725
  expect(Number(lower[8]), 'the along-hole gross is exported unrounded')
    .toBeCloseTo(69.8575, 9);
  expect(lower.slice(9, 14), 'a zone whose pay cannot be evaluated reads n/a')
    .toEqual(['55.5', 'n/a', 'n/a', 'n/a', 'n/a']);
  expect(lower[lower.length - 1], 'and its note says why').toMatch(/VSH.*cannot be evaluated/);

  const seen = faults(messages);
  expect(seen.map((m) => m.kind + ': ' + m.text), 'the console stayed silent').toEqual([]);
  await context.close();
});
