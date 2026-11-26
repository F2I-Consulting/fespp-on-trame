/*
 * Scenario: any click on a tree row makes it the active node — its box
 * ticked or unticked included (the PO, 23/11: "unticking Acoustic Impedance
 * does not highlight the node; any click on anything should highlight it").
 * Unticked, the row stays the active one.
 */
import {
  test, expect, M,
  ensureData, expandTree, familyTree, focusRenderView, state, viewId, waitUntil,
} from '../lib/app.mjs';

test('a box clicked makes its row the active node, ticked or unticked', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  await focusRenderView(page);
  const vid = await viewId(page);
  const active = () => state(page, 'active_path__' + vid);
  const tree = await familyTree(page, 'Reservoir');
  await expandTree(tree);
  const rows = tree.locator(M.treeRow).filter({ has: page.locator(M.treeCheck) });
  const count = await rows.count();
  let row = null;
  let where = '';
  for (let i = count - 1; i >= 0; i--) {
    const r = rows.nth(i);
    const p = await r.getAttribute('data-path');
    if (p && p !== (await active()) && await r.isVisible()) { row = r; where = p; break; }
  }
  expect(row, 'a row other than the active one').not.toBeNull();
  const ticked = async () => ((await state(page, 'selected_paths')) || []).includes(where);
  const was = await ticked();

  await row.locator(M.treeCheck).click();
  await waitUntil(app, async () => (await ticked()) !== was, { what: where + ' to be ' + (was ? 'unticked' : 'ticked') });
  await expect.poll(active, { message: 'its box clicked: the row is the active node', timeout: 15000 }).toBe(where);
  await expect(row, 'and lit').toHaveClass(/\bactive\b/);
  note((was ? 'unticked: ' : 'ticked: ') + where);

  await row.locator(M.treeCheck).click();
  await waitUntil(app, async () => (await ticked()) === was, { what: where + ' to be clicked back' });
  await expect.poll(active, { message: 'clicked back: still the active node', timeout: 15000 }).toBe(where);
  await expect(row, 'still lit').toHaveClass(/\bactive\b/);
  note('clicked back, still active');
});
