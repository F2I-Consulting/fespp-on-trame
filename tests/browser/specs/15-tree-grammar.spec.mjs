/*
 * The one grammar of every tree, in a real browser.
 *
 * A CHECKBOX is the session's load, common to every view and the same in
 * every tree: ticked anywhere = read; unticked = unloaded, after a question
 * naming the views that use the object when another one does. A tick in a
 * panel's tree also puts what it read in that panel, and in no 3D view.
 * An EYE means "shown in THIS view": in a 3D view, drawn there; in a panel,
 * held by it — a row of the Statistics view, a well or a curve in the log, a
 * row of the Log <-> Grid table.
 *
 * Each gesture is checked where the reader makes it: the Statistics tree ticks
 * what the session holds and its eye gives the row without moving the 3D views;
 * an untick of what another view uses asks first and names it; and the
 * right-click of a panel tree offers that panel's acts, on the side of its eye.
 * What a tick of that tree reads, and its untick, are 06-compare's.
 *
 * The driven file (vector_props.epc) holds one grid and no well: the log
 * panel's tree needs a file with a wellbore (the visual scenario
 * `panel_trees` drives it server-side).
 */
import {
  test, expect, M, DATASET,
  compareItems, dataTree, ensureProperty, expandTree, focusRenderView, openCompare, state, statsHold, treeRow,
} from '../lib/app.mjs';

/* The Statistics view with its tree open and unfolded. */
async function statisticsTree(page) {
  const panel = await openCompare(page);
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);
  return { panel, tree };
}

/*
 * Put the panel in a known state: `want` says whether the view must hold the
 * property when this returns. The way in is the EYE of its tree. The scenarios
 * share one session, so what an earlier one left in the view is the starting
 * point here — the eye is a toggle and asserting on it blind would test the
 * previous scenario.
 */
async function setHeld(page, tree, title, path, want) {
  if ((await statsHold(page, path)) === want) return;
  await treeRow(tree, title).locator(M.treeEye).click();
  await expect.poll(() => statsHold(page, path), {
    message: 'the eye ' + (want ? 'took ' + title + ' in' : 'let ' + title + ' go'),
  }).toBe(want);
}

/* Right-click a row, read the entries of its menu, close the menu. */
async function menuOf(page, scope, title) {
  await treeRow(scope, title).click({ button: 'right' });
  await expect(page.locator(M.ctxMenu), 'no menu appeared on a right-click of ' + title)
    .toHaveCount(1, { timeout: 10000 });
  const items = await page.locator(M.ctxItem).allInnerTexts();
  await page.locator(M.backdrop).first().dispatchEvent('click');
  await expect(page.locator(M.ctxMenu)).toHaveCount(0, { timeout: 10000 });
  return items.map((t) => t.trim());
}

/* A kind folder of the tree and a representation under it, by their titles. */
async function firstFolders(page) {
  const xml = (await state(page, 'ui_compare_tree_xml')) || '';
  return page.evaluate((doc) => {
    const kind = new DOMParser().parseFromString(doc, 'application/xml').documentElement.children[0];
    return { kind: kind.getAttribute('title'), rep: kind.children[0].getAttribute('title') };
  }, xml);
}

test('the Statistics tree: its checkbox is the load, its eye is the row', async ({ app }) => {
  const { page, note } = app;
  const name = DATASET.properties[0];
  // read through the DATA tree of the 3D view
  const path = await ensureProperty(app, name);
  const { panel, tree } = await statisticsTree(page);

  // THE CHECKBOX. The session holds it, so it is ticked here too: one load,
  // common to every view.
  await setHeld(page, tree, name, path, false);
  await expect(treeRow(tree, name).locator(M.treeCheck),
    'the Statistics tree ticks what the session holds').toHaveText(/☑/);
  const eyes = await tree.locator(M.treeEye).count();
  note('eyes offered with the property out of the view: ' + eyes);
  expect(eyes, 'what the session holds carries an eye, in the view or not')
    .toBeGreaterThan(0);

  // THE EYE. A row in this panel: opened, the row comes and the 3D view in use
  // follows; closed, the row goes, there too, and the property stays loaded.
  const inUse = await state(page, 'fespp_last_render_panel_id');
  const shown = async () => ((await state(page, 'visible_paths__' + inUse)) || []).includes(path);
  await setHeld(page, tree, name, path, true);
  await expect(panel.locator(M.compareOwnItem).filter({ hasText: name }).first(),
    'a row for the property whose eye was opened').toBeVisible({ timeout: 15000 });
  await expect.poll(shown, { message: 'opened here, opened in the 3D view in use', timeout: 30000 }).toBe(true);
  await setHeld(page, tree, name, path, false);
  await expect.poll(shown, { message: 'closed here, closed in the 3D view in use', timeout: 30000 }).toBe(false);
  expect((await state(page, 'ui_loaded_array_paths')) || [],
    'closing the eye unloads nothing').toContain(path);
  note('eye: ' + name + ' in and out of the view, the 3D view in use following');
});

test('an untick of what another view uses asks first, and names it', async ({ app }) => {
  const { page, note } = app;
  const name = DATASET.properties[0];
  const path = await ensureProperty(app, name);

  // the Statistics view holds it (its eye)...
  const { tree } = await statisticsTree(page);
  await setHeld(page, tree, name, path, true);

  // ...so unticking it in the 3D view's data tree asks, and names the panel
  await focusRenderView(page);
  const dt = dataTree(page);
  await expandTree(dt);
  await treeRow(dt, name).locator(M.treeCheck).click();
  const dialog = page.locator(M.dialog);
  await dialog.waitFor({ timeout: 30000 });
  const asked = (await dialog.innerText()).replace(/\s+/g, ' ');
  note('asked: ' + asked);
  expect(asked, 'the question names what would be unloaded').toContain('Unload ' + name);
  expect(asked, 'and the view that uses it').toContain('Statistics');

  // Cancel: nothing changes — still loaded, still ticked, still in the view
  await dialog.locator('button', { hasText: /^\s*Cancel\s*$/ }).click();
  await expect(dialog, 'the question closes on the answer').toHaveCount(0);
  await expect.poll(async () => ((await state(page, 'selected_paths')) || []).includes(path),
    { message: 'Cancel keeps it loaded' }).toBe(true);
  await expect(treeRow(dt, name).locator(M.treeCheck), 'and its box ticked').toHaveText(/☑/);
  expect(await statsHold(page, path), 'and its row').toBe(true);
});

test('the Statistics tree offers the acts of its own panel', async ({ app }) => {
  const { page, note } = app;
  const name = DATASET.properties[0];
  const path = await ensureProperty(app, name);
  const { tree } = await statisticsTree(page);

  await setHeld(page, tree, name, path, true);
  const items = await menuOf(page, tree, name);
  note('menu on ' + name + ' in the view: ' + items.join(' | '));
  expect(items, 'it can become the reference').toContain('Set as baseline');
  // what the eye and the charts under the matrix give, the menu does not repeat
  for (const gone of ['Add to stats', 'Remove from stats', 'Show distribution', 'Cross-plot']) {
    expect(items).not.toContain(gone);
  }
  expect(items, 'the file always has something to say about an object')
    .toContain('Show in Data health');
  // not the acts of the data tree: half of them mean nothing here
  expect(items, 'the data tree actions are not replayed').not.toContain('Derived property');
  expect(items).not.toContain('Add to Well Log view');

  await setHeld(page, tree, name, path, false);
  const out = await menuOf(page, tree, name);
  note('menu on ' + name + ' out of the view: ' + out.join(' | '));
  expect(out, 'no row to be the reference').not.toContain('Set as baseline');
  expect(out, 'and what needs nothing held stays').toContain('Show in Data health');

  // A kind folder opens no menu; a representation opens one line saying why it
  // has nothing: a statistic is computed on a property.
  const folders = await firstFolders(page);
  await treeRow(tree, folders.kind).click({ button: 'right' });
  await expect(page.locator(M.ctxMenu), 'no menu on a kind folder').toHaveCount(0);
  const onRep = await menuOf(page, tree, folders.rep);
  note('menu on the representation ' + folders.rep + ': ' + onRep.join(' | '));
  expect(onRep.length, 'one line').toBe(1);
  expect(onRep[0], 'saying why').toContain('computed on a property');

  // its eye: it joins the view, its row comes.
  await setHeld(page, tree, name, path, true);
  await expect.poll(() => statsHold(page, path), { message: 'its eye adds it', timeout: 30000 }).toBe(true);
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'the view holds something', timeout: 30000 }).toBeGreaterThan(0);

  // The one act that leaves the panel: the Data health table opens with that
  // object named in its filter — and says so when a healthy object has no
  // finding at all, rather than showing an empty table.
  await treeRow(tree, name).click({ button: 'right' });
  await page.locator(M.ctxItem, { hasText: /^Show in Data health$/ }).click();
  const health = page.locator(M.dockPart).filter({ has: page.locator(M.health) })
    .filter({ visible: true }).first();
  await health.locator(M.health).waitFor({ timeout: 60000 });
  await expect.poll(async () => ((await state(page, 'ui_health_focus')) || {}).text,
    { message: 'the object is named to the table', timeout: 30000 }).toBe(name);
  const search = health.locator('input[type=search]');
  if (await search.count()) {
    await expect(search, 'the name lands in the table filter').toHaveValue(name);
    const body = (await health.innerText()).replace(/\s+/g, ' ');
    expect(body, 'a table filtered down to nothing says why')
      .toMatch(/Nothing matches the filters above|●/);
  }
  await focusRenderView(page);
});
