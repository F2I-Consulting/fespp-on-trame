/*
 * Scenario (p): a second 3D view starts from the one it copies.
 *
 * "New 3D view", asked for a copy, opens the second view as a tab of its own,
 * in front, as every view opens; it shows what the first shows and starts
 * from its camera, so no eye has to be reopened. The two cameras are not
 * linked: that choice is left to the Synchronize camera card, and an
 * unlinked camera gesture sends nothing to the server.
 */
import {
  test, expect, M, DATASET,
  ensureProperty, focusRenderView, state, viewId, viewPart, dataTree, expandTree, treeRow,
} from '../lib/app.mjs';

test('a second 3D view opens as a tab of its own, with the eyes and the camera of the first', async ({ app }) => {
  const { page, note } = app;
  const nodePath = await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const first = await viewId(page);
  // shown in the first view — an earlier scenario may have closed its eye
  if (!((await state(page, 'visible_paths__' + first)) || []).includes(nodePath)) {
    const tree = dataTree(page);
    await expandTree(tree);
    await treeRow(tree, DATASET.properties[0]).locator(M.treeEye).click();
    await expect.poll(async () => (await state(page, 'visible_paths__' + first)) || [],
      { message: 'the first view shows the property', timeout: 15000 }).toContain(nodePath);
  }

  const renderViews = () => page.evaluate(() => {
    const s = window.trame.state;
    const all = s.state || s;
    return Object.keys(all).filter((x) => /^view_tools_/.test(x)).map((x) => x.replace('view_tools_', ''));
  });
  const before = await renderViews();
  const tabsBefore = await page.locator(M.dockTab).count();
  // the 3D views door's "+" tile ASKS what the view starts from: empty, or a
  // copy of one of the open views. Here we ask for a copy of the one we are in.
  await page.locator('header .fvd button').first().click();
  await page.locator('.fvd-add').click();
  const dialog = page.locator(M.newViewDialog);
  await expect(dialog, 'the new-view question is asked').toBeVisible({ timeout: 15000 });
  await dialog.locator('.fp-segbtn', { hasText: 'Copy a view' }).click();
  note('copy from: ' + await dialog.locator('select, .fp-sel-one').first().innerText());
  await dialog.locator('button', { hasText: /^Open$/ }).click();
  await expect(dialog, 'the question closes once answered').toBeHidden({ timeout: 15000 });
  await expect(page.locator(M.dockTab), 'a new tab appears').toHaveCount(tabsBefore + 1, { timeout: 30000 });

  // the new view's id: the render view that was not there before the click
  // (an earlier scenario may have opened one of its own)
  await expect.poll(async () => (await renderViews()).length, { message: 'a new render view has a state of its own' })
    .toBe(before.length + 1);
  const second = (await renderViews()).find((v) => !before.includes(v));
  note('views: ' + first + ' → ' + second + ' (open before: ' + before.join(', ') + ')');

  // a tab of its own, in front: the view it copies keeps its tab, behind
  await expect(viewPart(page, second), 'the new view is in front').toBeVisible({ timeout: 30000 });
  await expect.poll(() => state(page, 'fespp_last_render_panel_id'),
    { message: 'and it is the 3D view in use', timeout: 15000 }).toBe(second);

  await expect.poll(async () => (await state(page, 'visible_paths__' + second)) || [],
    { message: 'the second view inherits the eyes of the first', timeout: 15000 })
    .toContain(nodePath);
  // ...and the two cameras are NOT synchronized. A copy is a starting point:
  // a view that dragged its neighbour along from the first click would make
  // that choice before the user does. The Synchronize camera card is where
  // it is made.
  const links = (await state(page, 'view_links')) || {};
  note('camera synchronization: ' + JSON.stringify(links));
  expect(links[first] || [], 'the copy does not drag the view it came from').not.toContain(second);
  expect(links[second] || [], 'nor the other way round').not.toContain(first);

  // AND THE GESTURE COSTS NOTHING WHILE THERE IS NO LINK. The browser tests
  // `view_links` itself before calling the sync handler, so an unlinked
  // view sends nothing on camera release. trame's client counts a trigger
  // as BUSY: a call on every release would light, on a plain rotate, the
  // two loading bars the application shows while it reads a file. Here we
  // read the very expression the EndAnimation handler runs.
  const guard = (vid) => page.evaluate((v) => {
    const s = window.trame.state;
    const all = s.state || s;
    const links = all.view_links;
    return !!(links && (links[v] || []).length);
  }, vid);
  expect(await guard(first), 'an unlinked view sends nothing on mouse release').toBe(false);
  expect(await guard(second), 'nor does the one it was copied from').toBe(false);

  // ...and it DOES send once a link is made, or the card would be dead.
  await focusRenderView(page);
  await page.locator(M.toolButton + ':visible[title*="Synchronize camera"]').first().click();
  const card = page.locator('.fcl:visible').first();
  await expect(card, 'the Synchronize camera card opens').toBeVisible({ timeout: 15000 });
  await card.locator('input[type=checkbox]').first().click();
  await expect.poll(() => guard(first),
    { message: 'a linked view does send on mouse release', timeout: 15000 }).toBe(true);
  note('the link is made: ' + JSON.stringify((await state(page, 'view_links')) || {}));
  // put it back, so the next scenario finds the session as this one did
  await card.locator('input[type=checkbox]').first().click();
  await expect.poll(() => guard(first),
    { message: 'unticking takes the link back off', timeout: 15000 }).toBe(false);
});
