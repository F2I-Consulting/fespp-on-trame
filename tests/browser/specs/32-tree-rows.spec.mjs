/*
 * The data tree's rows say which object is which (the PO, 20/10): a loaded
 * representation wears its solid colour as a chip; an extract's row sits
 * right under the object it was selected on, one step in, its × first
 * where a box would be, without the "session" word, and a pencil renames
 * it. The extract row is posed in the client's state (making one takes a
 * pick in 3D; the server side of it is the visual scenario pointset_pick).
 */
import path_ from 'node:path';
import {
  test, expect, DATASET, OUT_DIR, ensureProperty, focusRenderView, state, viewId,
  dataTree, depthView, expandTree, familyTree,
} from '../lib/app.mjs';

test('a loaded representation wears its solid colour as a chip', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const chips = (await state(page, 'ui_tree_solid_colors')) || {};
  note('chips: ' + JSON.stringify(chips));
  expect(Object.keys(chips).length, 'a colour per loaded representation').toBeGreaterThan(0);
  // the card of its family: an earlier scenario may have left another one in front
  const tree = await familyTree(page, 'Reservoir');
  await expandTree(tree);
  await expect(tree.locator('.tn-chip').first(), 'its row wears it').toBeVisible({ timeout: 15000 });
});

test("an extract's row sits in its grid's SubRep folder, its × first, renamed by its pencil", async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  // in depth: in a view in time the rows of what is in depth carry no eye
  await depthView(page);
  const vid = await viewId(page);
  const tree = dataTree(page);
  await expandTree(tree);
  // the grid's folder: the chip key its geometry leaf lends its colour to
  // (one this view shows, whose geometry has its eye: another scenario may have left others read)
  const chips = Object.keys((await state(page, 'ui_tree_solid_colors')) || {});
  const shown = await page.evaluate((all) => all.filter((k) => document.querySelector(
    `.tn-row[data-path="${k}"] .tn-eye`)), chips);
  const geometry = shown.find((k) => k.includes('/_propsfolder_'));
  const folder = geometry && geometry.split('/_propsfolder_')[0];
  expect(folder, 'a grid folder among the chips').toBeTruthy();
  const path = 'session://' + vid + '/x9';
  await page.evaluate(([v, parent, p]) => window.trame.state.set('ui_session_rows__' + v, [{
    path: p, parent, title: 'Kept #9 · 12 cells', kind: 'extract',
    type: 'SelectionExtract', visible: true, info: '',
  }]), [vid, folder, path]);
  // a subset of the grid's cells, as a SubRepresentation: in its SubRep
  // folder (made, the grid has none), opened at once
  const row = tree.locator(`.tn-row[data-path="${path}"]`);
  await expect(row, 'the extract row is drawn').toHaveCount(1, { timeout: 15000 });
  const holder = await row.evaluate((el) => {
    const f = el.closest('.tn').parentElement.closest('.tn');
    const frow = f && f.querySelector('.tn-row');
    return frow ? { path: frow.dataset.path, title: frow.querySelector('.tn-title').textContent.trim(),
      box: !!frow.querySelector('.tn-check:not(:empty)') } : null;
  });
  note('held by ' + JSON.stringify(holder));
  expect(holder && holder.path, 'in a SubRep folder of the session').toBe('session://subreps' + folder);
  expect(holder.title, 'named as the file names one').toBe('SubRep');
  expect(holder.box, 'the made folder has no box to tick').toBe(false);
  // the × where the box would be, no "session" word, the eye at the right
  // under the other eyes
  await expect(row.locator('.tn-check.tn-x'), 'its × first').toHaveCount(1);
  await expect(row.locator('.tn-tag-session'), 'no "session" word').toHaveCount(0);
  const eyes = await page.evaluate(([p, g]) => {
    const right = (sel) => {
      const r = document.querySelector(`.tn-row[data-path="${sel}"] .tn-eye`);
      return r ? Math.round(r.getBoundingClientRect().right) : null;
    };
    return { extract: right(p), geometry: right(g) };
  }, [path, geometry]);
  note('eyes right edges: ' + JSON.stringify(eyes));
  expect(eyes.extract, 'its eye in the column of the others').toBe(eyes.geometry);
  // the tree as a reader sees it, for the review
  await tree.screenshot({ path: path_.join(OUT_DIR, 'tree-rows.png') });
  // the pencil opens the name in place; Enter puts it back as a title
  // sent to it: a card left open by an earlier spec may lie over the tree, and a
  // forced click lands on whatever is on top
  await row.locator('.tn-pencil').dispatchEvent('click');
  const input = row.locator('.tn-rename');
  await expect(input, 'the name opens for writing').toHaveCount(1);
  await input.fill('My kept cells');
  await input.press('Enter');
  await expect(row.locator('.tn-rename'), 'Enter closes it').toHaveCount(0);
});
