/*
 * Scenario: the page's query opens data without a click (S1, 21/10).
 *
 * `?epc=<name under the server's open directory>` reads the file as soon as
 * the client is mounted; the session document the query builds applies by
 * itself and the Session door's status says "done". A name that leaves the
 * open directory is refused, on the red snackbar.
 *
 * Last on purpose: each goto below starts a NEW server session for the
 * shared page (the smoke instance's launcher spawns one per page load).
 */
import {
  test, expect, M, APP_URL, dataTree, state, waitUntil, closeImportDoor,
} from '../lib/app.mjs';

test('an EPC named in the URL is read at mount, without a click', async ({ app }) => {
  const { page, note } = app;
  await page.goto(APP_URL + '?epc=private/vector_props.epc', { waitUntil: 'domcontentloaded' });
  await waitUntil(app, async () => ((await state(page, 'ui_loaded_files')) || [])
    .some((f) => f.name === 'vector_props.epc'), { what: 'the file of the URL to be read' });
  // the empty-session door may have come up before the read landed
  await closeImportDoor(page);
  await waitUntil(app, async () => ((await state(page, 'ui_session_status')) || {}).phase === 'done',
    { what: 'the document of the URL to apply' });
  const st = await state(page, 'ui_session_status');
  note('status: ' + JSON.stringify(st).slice(0, 240));
  expect(st.report.some((r) => /Session restored/.test(r.text)), 'the report says so').toBe(true);
  const tree = dataTree(page);
  await expect(tree.locator(M.treeRow).first(), 'the tree lists the file').toBeVisible({ timeout: 30000 });
});

test('a name that leaves the open directory is refused', async ({ app }) => {
  const { page, note } = app;
  await page.goto(APP_URL + '?epc=../../etc/passwd', { waitUntil: 'domcontentloaded' });
  await waitUntil(app, async () => !!(await state(page, 'load_error')), { what: 'the refusal' });
  const why = await state(page, 'load_error');
  note('refused: ' + why);
  expect(why).toMatch(/open directory/);
  expect((await state(page, 'ui_loaded_files')) || [], 'nothing was read').toEqual([]);
});
