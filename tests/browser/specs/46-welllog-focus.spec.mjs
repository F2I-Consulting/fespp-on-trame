/*
 * Scenario: the log view's own tree brings the active node's graph to the
 * middle of the view.
 *
 * A log sent to the log view, the view zoomed in so that the log's depths
 * no longer all stand in sight, then the log made active in the log view's
 * tree: the view scrolls to the middle of the depths the log holds values
 * over, its track in sight. TWTIME (Volve 15/9-19 A) holds values over a
 * stretch of its own.
 *
 * Uses the Volve wells file, imported here when it is not in yet.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET,
  depthView, ensureData, expandTree, focusRenderView, openImportDoor, state, treeRow,
  waitUntil, closeImport, familyTree,
} from '../lib/app.mjs';

const WELLS_EPC = path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Wells_Depth.epc');
const LOG = 'TWTIME';

test('a log made active in the log view\'s tree is brought to the middle of the view', async ({ app }) => {
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
  await depthView(page);
  const tree = await familyTree(page, 'Well');
  const filter = tree.locator('.fdx-filter-input');
  await filter.evaluate((el, t) => {
    el.value = t;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, LOG);
  await expandTree(tree);
  const row = treeRow(tree, LOG).first();
  const logPath = await row.getAttribute('data-path');
  await row.click({ button: 'right' });
  await page.locator(M.ctxMenu).waitFor({ timeout: 10000 });
  await page.locator(M.ctxItem, { hasText: /^Add to Well Log view$/ }).click();

  // the log view that draws the log, and its drawing
  const holder = () => page.evaluate((log) => {
    const s = window.trame && window.trame.state;
    const all = (s && (s.state || s)) || {};
    const key = Object.keys(all).find((k) => k.startsWith('welllog_data__') && all[k]
      && (all[k].wells || []).some((w) => (w.tracks || []).some((t) => (t.curves || []).some((c) => c.name === log))));
    return key ? key.slice('welllog_data__'.length) : null;
  }, LOG);
  await waitUntil(app, async () => !!(await holder()), { what: 'the log view to hold ' + LOG });
  const vid = await holder();
  const drawn = () => page.evaluate((log) => {
    const el = document.querySelector('.well-log-correlation');
    const H = el && el.__wlc && el.__wlc.hover;
    return !!H && (H.wells || []).some((w) => (w.tracks || []).some((t) => (t.curves || []).some((c) => c.name === log)));
  }, LOG);
  await waitUntil(app, drawn, { what: 'the log view to draw ' + LOG });
  note('log view: ' + vid);

  // zoomed in, back at the top: the log's depths out of sight
  await page.evaluate((v) => window.trame.state.set('welllog_zoom__' + v, 10), vid);
  await page.waitForTimeout(800);
  await page.evaluate(() => { document.querySelector('.well-log-correlation').scrollTop = 0; });

  // the log made active in the log view's own tree (its frame first: the log
  // came in active, a click on the active row changes nothing)
  const logTree = page.locator('.wlp');
  const frame = logTree.locator(M.treeRow).filter({ has: page.locator(`[data-path="${logPath.slice(0, logPath.lastIndexOf('/'))}"]`) })
    .or(logTree.locator(`${M.treeRow}[data-path="${logPath.slice(0, logPath.lastIndexOf('/'))}"]`)).first();
  await frame.locator(M.treeTitle).click();
  await page.waitForTimeout(500);
  await treeRow(logTree, LOG).locator(M.treeTitle).click();

  const where = () => page.evaluate((log) => {
    const el = document.querySelector('.well-log-correlation');
    const H = el && el.__wlc && el.__wlc.hover;
    if (!H) return null;
    const w = H.wells.findIndex((x) => (x.tracks || []).some((t) => (t.curves || []).some((c) => c.name === log)));
    if (w < 0) return null;
    const k = H.wells[w].tracks.findIndex((t) => t.curves.some((c) => c.name === log));
    const curve = H.wells[w].tracks[k].curves.find((c) => c.name === log);
    const depths = curve.samples.filter((s) => s[0] != null && !Number.isNaN(s[0])).map((s) => s[1]);
    const mid = H.scales[w]((Math.min(...depths) + Math.max(...depths)) / 2);
    const head = H.headTotal || 0;
    const x = H.geom[w].track(k);
    return { top: el.scrollTop, mid, seen: el.scrollTop + head + (el.clientHeight - head) / 2,
             left: el.scrollLeft, width: el.clientWidth, x, trackW: H.L.trackW };
  }, LOG);
  await waitUntil(app, async () => {
    const at = await where();
    return !!at && at.top > 0 && Math.abs(at.mid - at.seen) < 40;
  }, { what: 'the log view to bring ' + LOG + ' to its middle', timeout: 15000 });
  const at = await where();
  note('brought: ' + JSON.stringify(at));
  expect(at.x + at.trackW / 2 - at.left, 'its track in sight').toBeGreaterThan(0);
  expect(at.x + at.trackW / 2 - at.left, 'its track in sight').toBeLessThan(at.width);
});
