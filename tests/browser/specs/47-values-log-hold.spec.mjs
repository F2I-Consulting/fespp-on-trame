/*
 * Scenario: the log view and the Values view reading the same log.
 *
 * The Values view reads a log sample by sample, one row held at a time. The
 * log view's pointer on that log's column marks the row of the nearest
 * sample (blue); off the tracks it marks none. A click on the column holds
 * that sample (its row selected, red); a click off the tracks lets it go.
 * TWTIME (Volve 15/9-19 A) is the log.
 *
 * Uses the Volve wells file, imported here when it is not in yet.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET,
  depthView, ensureData, expandTree, focusRenderView, openImportDoor, showView, state, treeRow,
  waitUntil, closeImport, familyTree,
} from '../lib/app.mjs';

const WELLS_EPC = path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Wells_Depth.epc');
const LOG = 'TWTIME';

test('the log view marks and holds the Values row of the log it points at, only on that log\'s column', async ({ app }) => {
  const { page, note } = app;
  test.skip(!fs.existsSync(WELLS_EPC), 'wells test file not found: ' + WELLS_EPC);
  await ensureData(app);
  const loadedNames = async () => ((await state(page, 'ui_loaded_files')) || []).map((f) => f.name);
  if (!(await loadedNames()).includes(path.basename(WELLS_EPC))) {
    note('import ' + path.basename(WELLS_EPC));
    await openImportDoor(page);
    const h5 = WELLS_EPC.replace(/\.epc$/i, '.h5');
    await page.setInputFiles(M.fileInput, [WELLS_EPC, ...(fs.existsSync(h5) ? [h5] : [])]);
    await closeImport(page);
    await waitUntil(app, async () => (await loadedNames()).includes(path.basename(WELLS_EPC)),
      { what: 'the server to read the wells file' });
  }
  await focusRenderView(page);
  const vid = await state(page, 'fespp_last_render_panel_id');
  await depthView(page);
  const tree = await familyTree(page, 'Well');
  const filter = tree.locator('.fdx-filter-input');
  await filter.evaluate((el, t) => {
    el.value = t;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, LOG);
  await expandTree(tree);
  const row = treeRow(tree, LOG).first();
  await row.click({ button: 'right' });
  await page.locator(M.ctxMenu).waitFor({ timeout: 10000 });
  await page.locator(M.ctxItem, { hasText: /^Add to Well Log view$/ }).click();
  await waitUntil(app, () => page.evaluate((log) => {
    const el = document.querySelector('.well-log-correlation');
    const H = el && el.__wlc && el.__wlc.hover;
    return !!H && (H.wells || []).some((w) => (w.tracks || []).some((t) => (t.curves || []).some((c) => c.name === log)));
  }, LOG), { what: 'the log view to draw ' + LOG });

  // the Values view reads the log, one row per sample, one held at a time
  await showView(page, 'Values', page.locator('.fap'));
  const values = async () => ((await state(page, 'ui_node_values_by_view')) || {})[vid] || {};
  await waitUntil(app, async () => (await values()).single === true,
    { what: 'the Values view to read ' + LOG + ' sample by sample' });

  // where on screen: a sample of the log's column, and a place off the tracks
  const spots = await page.evaluate((log) => {
    const el = document.querySelector('.well-log-correlation');
    const H = el.__wlc.hover;
    const w = H.wells.findIndex((x) => (x.tracks || []).some((t) => (t.curves || []).some((c) => c.name === log)));
    const k = H.wells[w].tracks.findIndex((t) => t.curves.some((c) => c.name === log));
    const curve = H.wells[w].tracks[k].curves.find((c) => c.name === log);
    const s = curve.samples.filter((p) => p[0] != null && !Number.isNaN(p[0]));
    const at = s[Math.floor(s.length / 2)];
    el.scrollTop = Math.max(0, H.scales[w](at[1]) - el.clientHeight / 2);
    const box = H.svg.getBoundingClientRect();
    const y = box.top + H.scales[w](at[1]);
    return { on: { x: box.left + H.geom[w].track(k) + H.L.trackW / 2, y },
             off: { x: box.left + H.geom[w].plotR + 60, y }, md: at.length > 2 && at[2] != null ? at[2] : at[1] };
  }, LOG);
  note('spots: ' + JSON.stringify(spots));

  // the pointer on the column: its row marked
  await page.mouse.move(spots.on.x, spots.on.y);
  await waitUntil(app, async () => (await values()).cursor != null, { what: 'the Values view to mark the row pointed at' });
  // off the tracks: none
  await page.mouse.move(spots.off.x, spots.off.y);
  await waitUntil(app, async () => (await values()).cursor == null, { what: 'the mark to go off the tracks' });

  // a click on the column holds the sample: its row selected in the table
  await page.mouse.click(spots.on.x, spots.on.y);
  await waitUntil(app, async () => ((await values()).held || []).length === 1, { what: 'the sample clicked to be held' });
  await expect(page.locator('.fap-table.fap-one tbody tr.fap-sel'), 'its row selected').toHaveCount(1);
  const lit = (await state(page, 'ui_log_lit')) || {};
  note('lit in the log view: ' + JSON.stringify(lit));
  expect(Object.values(lit).some((logs) => (logs[LOG] || []).length === 1), 'lit on the log view').toBeTruthy();

  // a click off the tracks lets it go
  await page.mouse.click(spots.off.x, spots.off.y);
  await waitUntil(app, async () => ((await values()).held || []).length === 0, { what: 'the sample to be let go' });
  await expect(page.locator('.fap-table.fap-one tbody tr.fap-sel'), 'no row selected').toHaveCount(0);

  // in the table: one row held at a time
  const rows = page.locator('.fap-table.fap-one tbody tr');
  await rows.nth(2).click();
  await rows.nth(4).click();
  await expect(page.locator('.fap-table.fap-one tbody tr.fap-sel'), 'one row at a time').toHaveCount(1);
});
