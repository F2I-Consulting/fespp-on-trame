/*
 * Scenario (reconcile tree): the Log ↔ Grid panel chooses its own logs.
 *
 * The panel carries its own trees (a Reservoir and a Well card of its left
 * toolbar), like Statistics and the well log, so a reader who opens Log ↔ Grid
 * picks logs from there rather than through the well-log view ("Add to
 * well-log"). A tick puts a log channel in THIS table and reads it, born
 * hidden (in no 3D view); an untick takes it out of the table.
 *
 * Uses the Volve wells file, imported here when it is not in yet.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET,
  ensureData, expandTree, familyCardTree, openImportDoor, showView, state, waitUntil,
  closeImport,
} from '../lib/app.mjs';

const WELLS_EPC = path.join(path.dirname(DATASET.files[0]), 'Volve_Demo_Wells_Depth.epc');

const tableLogs = async (page) => (((await state(page, 'ui_reconcile')) || {}).logs || [])
  .map((l) => l.title);

test('the Log ↔ Grid tree: a tick puts a log in the table and in no 3D view', async ({ app }) => {
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
  const vids = ((await state(page, 'fespp_render_panels')) || []).map((p) => p.id);

  // the panel, and its Well tree card through its toolbar button
  await showView(page, 'Log ↔ Grid', page.locator(M.reconcile));
  const panel = page.locator(M.dockPart).filter({ visible: true })
    .filter({ has: page.locator(M.reconcile) }).first();
  await panel.locator(M.reconcile).waitFor({ timeout: 60000 });
  const tree = await familyCardTree(page, panel, 'Well');
  await expandTree(tree);

  // one log channel: a row three levels under a logs folder
  // (logs folder / frame / channel), not yet in the table
  const inTable = await tableLogs(page);
  const pick = await tree.locator(M.treeRow).evaluateAll((rows, held) => {
    for (const r of rows) {
      const p = r.getAttribute('data-path') || '';
      const t = (r.querySelector('.tn-title') || {}).textContent || '';
      if (/_logsfolder_[^/]+\/[^/]+\/[^/]+$/.test(p) && t && !held.includes(t.trim())) {
        return { path: p, title: t.trim() };
      }
    }
    return null;
  }, inTable);
  expect(pick, 'the panel\'s tree lists a log channel').not.toBeNull();
  note('tick ' + pick.title + ' in the Log ↔ Grid tree');
  const leaf = tree.locator(M.treeRow + '[data-path="' + pick.path + '"]');
  await leaf.locator(M.treeCheck).click();
  await expect.poll(async () => (await tableLogs(page)).includes(pick.title),
    { message: 'the tick put the log in the table', timeout: 60000 }).toBe(true);
  expect((await state(page, 'ui_welllog_wells')) || [], 'no well went through the log view')
    .not.toContain(pick.path);

  // THE RULE: what a panel tick reads is in the panel and in no 3D view
  for (const vid of vids) {
    const shown = ((await state(page, 'visible_paths__' + vid)) || []).includes(pick.path);
    expect(shown, 'a Log ↔ Grid tick showed the log in the 3D view ' + vid).toBe(false);
  }

  // and the untick takes it out of the table again
  await leaf.locator(M.treeCheck).click();
  await expect.poll(async () => (await tableLogs(page)).includes(pick.title),
    { message: 'the untick took the log out of the table', timeout: 30000 }).toBe(false);
});
