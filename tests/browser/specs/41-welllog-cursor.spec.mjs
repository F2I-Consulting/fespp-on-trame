/*
 * Scenario: a log sent to the log view from its own row, and the log view's
 * cursor on what the file holds.
 *
 * "Add to Well Log view" is offered on a log's row (not only on its frame) and
 * brings that log alone. The cursor of a track stands on the sample nearest
 * the pointer: its value is a sample's value, the depth it reads is that
 * sample's — never a value made up between two samples. TWTIME (Volve
 * 15/9-19 A) is a checkshot read at a few depths far apart: a pointer between
 * two of them is the case.
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

test('a log row sends that log to the log view, whose cursor stands on its samples', async ({ app }) => {
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
  // the log is in depth: a view an earlier scenario left in time would ask
  // whether to switch, and the question would stay over the page
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

  // the log view draws that log
  const payload = () => page.evaluate(() => {
    const s = window.trame && window.trame.state;
    const all = (s && (s.state || s)) || {};
    const key = Object.keys(all).find((k) => k.startsWith('welllog_data__') && all[k] && (all[k].wells || []).length);
    return key ? JSON.parse(JSON.stringify(all[key])) : null;
  });
  await waitUntil(app, async () => {
    const d = await payload();
    return !!d && d.wells.some((w) => (w.tracks || []).some((t) => (t.curves || []).some((c) => c.name === LOG)));
  }, { what: 'the log view to draw ' + LOG });
  const d = await payload();
  const names = d.wells.flatMap((w) => (w.tracks || []).flatMap((t) => (t.curves || []).map((c) => c.name)));
  note('curves in the log view: ' + names.join(', '));
  expect(names, 'the log alone, not every log of its well').toEqual([LOG]);

  // the log sent, lit in the log view's own tree: unfolded to, in sight
  const lit = page.locator('.wlp .tn-row.active').filter({ has: page.locator(`[data-path="${logPath}"]`) })
    .or(page.locator(`.wlp .tn-row.active[data-path="${logPath}"]`));
  await expect(lit.first(), 'the log sent is lit in the log view\'s tree').toBeVisible({ timeout: 15000 });
  note('lit in the log view\'s tree: ' + logPath);

  // the pointer half way between the two first samples far apart: the cursor reads a sample
  const read = await page.evaluate((log) => {
    const el = document.querySelector('.well-log-correlation');
    const H = el && el.__wlc && el.__wlc.hover;
    if (!H) return { error: 'no drawing' };
    const w = H.wells.findIndex((x) => (x.tracks || []).some((t) => (t.curves || []).some((c) => c.name === log)));
    const well = H.wells[w];
    const k = well.tracks.findIndex((t) => t.curves.some((c) => c.name === log));
    const curve = well.tracks[k].curves.find((c) => c.name === log);
    const s = curve.samples.filter((p) => p[0] != null && !Number.isNaN(p[0]));
    let i = 0;
    for (let j = 1; j < s.length; j++) if (s[j][1] - s[j - 1][1] > s[i + 1][1] - s[i][1]) i = j - 1;
    const between = s[i][1] + 0.4 * (s[i + 1][1] - s[i][1]);
    const box = H.svg.getBoundingClientRect();
    const x = box.left + H.geom[w].track(k) + 5;
    const y = box.top + H.scales[w](between);
    const hit = window.WellLogCorrelation.hover(el, x, y);
    return { between, samples: s.map((p) => [p[0], p[1], p.length > 2 ? p[2] : null]), hit };
  }, LOG);
  if (read.error) throw new Error(read.error);
  const cur = (read.hit && read.hit.curves || []).find((c) => c.name === LOG);
  note(`pointer at ${read.between.toFixed(1)}: ${JSON.stringify(cur)}, depth ${read.hit && read.hit.depths[0].value}`);
  expect(cur, 'the cursor reads the log').toBeTruthy();
  const sample = read.samples.find((p) => p[0] === cur.value && p[1] === cur.at);
  expect(sample, 'the value read is a sample of the file').toBeTruthy();
  expect(read.hit.depths[0].value, 'the depth read is that sample\'s').toBe(cur.at);
  // its other depth too, its own (the MD of a log laid out in TVD), never read back through a table
  if (read.hit.depths.length > 1 && sample[2] != null) {
    expect(read.hit.depths[1].value, 'the other depth read is that sample\'s own').toBe(sample[2]);
  }
});
