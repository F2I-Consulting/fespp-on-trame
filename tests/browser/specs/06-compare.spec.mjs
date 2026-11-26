/*
 * Scenario (f): the Statistics view (`compare` in the code), its own docked
 * tree, and what a kind tab draws of the selection.
 *
 * Worth a scenario of its own: it is the panel that carries a second instance
 * of the tree component, drives it from a synthetic assembly, and draws at once
 * its matrix, its distributions and its cross-plot from the same selection. A
 * figure drawn while hidden keeps a zero size, so the only way to know they work
 * is to walk them. The rows that follow an item, and a pin (the driven file has
 * nothing to pin a copy at), are 21-stats-rows'.
 *
 * It also holds what makes this tree the same object as the data tree: the
 * view's toolbar opens it (no lookalike inside the widget), an unread leaf
 * carries no badge (the empty checkbox says it), and a folder tick that would
 * read more than MAX_TICK_LOAD properties asks before reading anything. And
 * the tree is cut as the data tree is, one card per family — Reservoir /
 * Surface / Well: a family with nothing greyed in the toolbar, and a folder
 * tick made in a card reads only what that card shows.
 */
import {
  test, expect, M, DATASET,
  compareItems, dataTree, depthView, emptyPropertySlicer, ensureData, ensureProperty, expandTree, familyCardTree, focusRenderView,
  openCompare, state, treeRow, waitUntil,
} from '../lib/app.mjs';

/* The number of unread properties one tick may stand for before the
   application asks first: `engine/tick_confirm.MAX_TICK_LOAD`, the SAME for
   every tree of the application. Spelled out here because the server
   publishes no state variable for it; keep the two in step. */
const MAX_TICK_LOAD = 20;

/* The tree's own reading of what the session has NOT read: the leaves the
   server marked `loadState="unloaded"` in the synthetic assembly. */
async function unreadLeaves(page) {
  const xml = (await state(page, 'ui_compare_tree_xml')) || '';
  return page.evaluate((doc) => {
    const root = new DOMParser().parseFromString(doc, 'application/xml');
    return [...root.querySelectorAll('[loadState="unloaded"]')]
      .map((e) => e.getAttribute('title'));
  }, xml);
}

/* The ids of the open 3D views: an earlier scenario may have left a second
   one open, and a panel eye acts on them all. */
async function renderViews(page) {
  return ((await state(page, 'fespp_render_panels')) || []).map((p) => p.id);
}

/* Empty the view as a hand does: the eye of an open folder closes what is under it. */
async function emptyByTheEyes(page, tree) {
  const open = tree.locator(M.treeEye + '[title="Hide"]');
  for (let i = 0; i < 20 && (await open.count()) && (await compareItems(page)).length; i += 1) {
    const before = (await compareItems(page)).length;
    await open.first().click();
    await expect.poll(async () => (await compareItems(page)).length,
      { message: 'the eye closes what is under it', timeout: 30000 }).toBeLessThan(before);
  }
}

/* The id the panel's own eye variable is published under. */
async function compareVid(page) {
  return page.evaluate(() => Object.keys(window.trame.state.state || window.trame.state)
    .filter((k) => k.startsWith('compare_tree_eye__'))
    .map((k) => k.replace('compare_tree_eye__', ''))[0]);
}

/*
 * A tick in this tree READS into the view (the one grammar: the checkbox is the
 * session's load; a panel's tick also puts what it read in that panel). The
 * properties it brought in (`ui_loaded_array_paths` minus `held`) are loaded, the
 * 3D view in use shows them (the eyes are linked), no other does, nor under the
 * panel's id (a bucket no 3D view reads); their rows carry an OPEN eye — the eye
 * of this tree is "in the statistics". `titles` are the rows whose eye is read.
 */
async function assertReadIsHidden(app, panel, tree, held, titles) {
  const { page, note } = app;
  const added = ((await state(page, 'ui_loaded_array_paths')) || [])
    .filter((p) => !held.includes(p));
  expect(added.length, 'the tick read something').toBeGreaterThan(0);
  const cvid = await compareVid(page);
  const shownIn = {};
  for (const rvid of await renderViews(page)) {
    shownIn[rvid] = ((await state(page, 'visible_paths__' + rvid)) || [])
      .filter((p) => added.includes(p));
  }
  const strayed = ((await state(page, 'visible_paths__' + cvid)) || [])
    .filter((p) => added.includes(p));
  const closed = [];
  const open = [];
  for (const title of titles) {
    const eye = treeRow(tree, title).locator(M.treeEye);
    await expect(eye, 'a property the session holds carries the eye: ' + title)
      .toHaveCount(1);
    ((await eye.getAttribute('title')) === 'Hide' ? open : closed).push(title);
  }
  note(`read ${added.length}; shown in ${JSON.stringify(shownIn)}; strayed: ${strayed.length};`
    + ` eyes closed: ${closed.length}, open: ${open.length}`);
  const inUse = await state(page, 'fespp_last_render_panel_id');
  for (const [rvid, paths] of Object.entries(shownIn)) {
    if (rvid === inUse) expect(paths.length, 'the 3D view in use shows what it read').toBeGreaterThan(0);
    else expect(paths, 'a tick of this tree showed what it read in the 3D view ' + rvid).toEqual([]);
  }
  expect(strayed, 'a read went under the panel\'s own id,'
    + ' a bucket no 3D view reads').toEqual([]);
  expect(closed, 'a property a tick of this tree read is in the view: its eye is open').toEqual([]);
  const said = (await panel.locator('.fp-note-text').allInnerTexts()).join(' ');
  expect(said, 'a read that went well says nothing about it').not.toMatch(/read into the statistics|never brought/);
}

test('the docked tree opens from the panel button and offers what the file holds', async ({ app }) => {
  const { page, note } = app;
  // No property is ticked for this: the tree is built from the assembly, which
  // names every property of the file without a single value being read.
  await ensureData(app);
  const panel = await openCompare(page);
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);

  const loaded = (await state(page, 'ui_loaded_array_paths')) || [];
  const rows = await tree.locator(M.treeRow).count();
  const unread = await unreadLeaves(page);
  note(`docked tree: ${rows} row(s), ${unread.length} not read, ${loaded.length} loaded`);
  expect(rows, 'the tree lists more than what is loaded').toBeGreaterThan(loaded.length);
  expect(unread.length, 'the file holds properties the session has not read')
    .toBeGreaterThan(0);
  // The empty checkbox is what says "not read": no badge repeats it. Only a
  // read in flight or a read that failed leaves a mark, and neither is on.
  expect(await tree.locator(M.treeLoadTag).count(),
    'an unread leaf carries no badge — the checkbox already says it').toBe(0);

  // Ticking one loads it — the same channel a tick in the data tree writes.
  // Held by its title, not as "the first unloaded row": that one moves to
  // another property the moment this one is read.
  const title = unread[0];
  const row = treeRow(tree, title);
  note('tick the unread ' + title);
  await row.locator(M.treeCheck).click();
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'an item appears for ' + title, timeout: 60000 }).toBeGreaterThan(0);
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).length > loaded.length,
    { what: 'the application to report ' + title + ' as loaded' });
  const added = ((await state(page, 'ui_loaded_array_paths')) || [])
    .filter((p) => !loaded.includes(p));
  note('loaded by the tick: ' + added.join(', '));

  // The tick read the property into the view and into the 3D view in use, as
  // their eyes are in sync; no other view moves, the leaf's eye is OPEN, and
  // nothing is said about it. The eye: clicked, the property leaves this view
  // and the 3D view in use follows; clicked again, back.
  await assertReadIsHidden(app, panel, tree, loaded, [title]);
  const eye = row.locator(M.treeEye);
  const inUse = await state(page, 'fespp_last_render_panel_id');
  const shown = async () => ((await state(page, 'visible_paths__' + inUse)) || [])
    .filter((p) => added.includes(p)).length;
  // the rest of its kind stays: an earlier scenario may have read some
  const held = (await compareItems(page)).length;
  await eye.click();
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'the eye took the property out of the statistics', timeout: 30000 }).toBe(held - 1);
  await expect(eye, 'the eye closes with it').toHaveAttribute('title', 'Show');
  await expect.poll(shown, { message: 'closed here, closed in the 3D view in use', timeout: 30000 }).toBe(0);
  await page.waitForTimeout(1500);
  await eye.click();
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'the eye put it back in the statistics', timeout: 30000 }).toBe(held);
  await expect.poll(shown, { message: 'opened here, opened in the 3D view in use', timeout: 30000 }).toBeGreaterThan(0);
  note('eye: ' + title + ' out of the statistics and back, the 3D view in use following');

  // Unticking UNLOADS (the checkbox is the session's load): the item goes
  // and the property is no longer loaded — the scenarios that follow start
  // where this one did. A Log <-> Grid panel left open by an earlier
  // scenario holds every loaded grid property, so the untick may ask first,
  // naming it: then the answer is Unload.
  await page.waitForTimeout(1500);
  await row.locator(M.treeCheck).click();
  const dialog = page.locator(M.dialog);
  if (await dialog.waitFor({ timeout: 3000 }).then(() => true).catch(() => false)) {
    const asked = (await dialog.innerText()).replace(/\s+/g, ' ');
    note('asked: ' + asked);
    expect(asked, 'a question names the view using it').toMatch(/used in /);
    await dialog.locator('button', { hasText: /^\s*Unload\s*$/ }).click();
    await expect(dialog, 'the question closes on the answer').toHaveCount(0);
  }
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'the item goes with the untick' }).toBe(held - 1);
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).length === loaded.length,
    { what: title + ' to be unloaded by the untick' });
});

/*
 * Untick a row (unload it); a question naming another view that uses it
 * (the one grammar) is answered Unload — a cleanup leaves the session as
 * the scenario found it.
 */
async function untickAnswering(page, row) {
  await row.locator(M.treeCheck).click();
  const dialog = page.locator(M.dialog);
  if (await dialog.waitFor({ timeout: 3000 }).then(() => true).catch(() => false)) {
    await dialog.locator('button', { hasText: /^\s*Unload\s*$/ }).click();
    await expect(dialog, 'the question closes on the answer').toHaveCount(0);
  }
}

/*
 * Unload what a kind folder of the tree holds already read, by the
 * checkbox of each leaf (the one grammar: the checkbox is the session's
 * load). A leaf another view uses asks first, naming it: then Unload. After
 * this a tick on the folder reads it all — a partly ticked folder would
 * empty on a click instead, as in the data tree.
 */
async function unloadLeaves(app, tree, titles) {
  const { page, note } = app;
  for (const title of titles) {
    const r = treeRow(tree, title);
    if (!(await r.count())) continue;
    if (!/☑/.test(await r.locator(M.treeCheck).innerText())) continue;
    await r.locator(M.treeCheck).click();
    const dialog = page.locator(M.dialog);
    if (await dialog.waitFor({ timeout: 3000 }).then(() => true).catch(() => false)) {
      note('asked: ' + (await dialog.innerText()).replace(/\s+/g, ' '));
      await dialog.locator('button', { hasText: /^\s*Unload\s*$/ }).click();
      await expect(dialog, 'the question closes on the answer').toHaveCount(0);
    }
    await expect(r.locator(M.treeCheck), title + ' is unloaded').toHaveText(/☐/, { timeout: 30000 });
  }
}

test('a folder tick cascades, and asks first when it would read more than it shows', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  // a property a box of the Property slicer reads stays checked: the boxes an
  // earlier scenario's card left go first
  await emptyPropertySlicer(page);
  // the 3D view in use follows this panel's eyes: left in time by a scenario
  // before, it would ask about each object in depth ticked here
  await focusRenderView(page);
  await depthView(page);
  const panel = await openCompare(page);
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);

  // The widest kind folder of the file, the properties it holds and which of
  // them the session has still to read: above the cap the tick has to ask.
  const folders = await page.evaluate((doc) => {
    const root = new DOMParser().parseFromString(doc, 'application/xml');
    return [...root.documentElement.children].map((k) => ({
      title: k.getAttribute('title'),
      unread: [...k.querySelectorAll('[loadState="unloaded"]')]
        .map((e) => e.getAttribute('title')),
      titles: [...k.querySelectorAll('[type="CompareItem"]')].map((e) => e.getAttribute('title')),
      leaves: k.querySelectorAll('[type="CompareItem"]').length,
    })).sort((a, b) => b.unread.length - a.unread.length);
  }, (await state(page, 'ui_compare_tree_xml')) || '');
  note('kind folders: ' + folders
    .map((f) => `${f.title} ${f.unread.length}/${f.leaves}`).join(', '));
  const big = folders.sort((a, b) => b.leaves - a.leaves)[0];
  test.skip(!big || big.leaves < 2,
    'this file has no kind folder of several properties: nothing cascades');
  // What an earlier scenario read of it is unloaded first: the checkbox is
  // the session's load (the one grammar), and a partly ticked folder
  // empties on a click, as in the data tree.
  await unloadLeaves(app, tree, big.titles.filter((t) => !big.unread.includes(t)));
  big.unread = big.titles.slice();

  const held = (await state(page, 'ui_loaded_array_paths')) || [];
  const loaded = held.length;
  await treeRow(tree, big.title).locator(M.treeCheck).click();

  const dialog = page.locator(M.dialog);
  if (big.unread.length > MAX_TICK_LOAD) {
    // Over the cap the question states the number and reads nothing — the
    // same box, raised the same way, as a tick in the data tree.
    await dialog.waitFor({ timeout: 30000 });
    const asked = await dialog.innerText();
    note('asked: ' + asked.replace(/\s+/g, ' ').trim());
    expect(asked, 'the question says how many properties it would read')
      .toContain(String(big.unread.length));
    expect((await compareItems(page)).length,
      'nothing joined the statistics before the answer').toBe(0);
    expect(((await state(page, 'ui_loaded_array_paths')) || []).length,
      'nothing was read before the answer').toBe(loaded);

    await dialog.locator('button', { hasText: /^\s*Cancel\s*$/ }).click();
    await expect(dialog, 'the question closes on the answer').toHaveCount(0);
    expect(((await state(page, 'ui_loaded_array_paths')) || []).length,
      'stepping back read something anyway').toBe(loaded);
    await expect(treeRow(tree, big.title).locator(M.treeCheck),
      'stepping back put the box back').toHaveText('☐');

    // Asked again and answered yes, the lot is read — into the view and into
    // no 3D view, like a tick under the cap.
    await treeRow(tree, big.title).locator(M.treeCheck).click();
    await dialog.waitFor({ timeout: 30000 });
    await dialog.locator('button', { hasText: /^\s*Read \d+ properties\s*$/ }).click();
    await expect(dialog, 'the question closes on the answer').toHaveCount(0);
  } else {
    // under the cap the cascade just happens, with no question at all
    await expect(dialog, 'a small folder asks nothing').toHaveCount(0);
  }
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'the folder tick cascaded to its leaves', timeout: 60000 })
    .toBe(big.leaves);
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).length
      >= loaded + big.unread.length,
    { what: 'the ' + big.unread.length + ' properties of ' + big.title + ' to be read' });
  await assertReadIsHidden(app, panel, tree, held, big.unread);
  await emptyByTheEyes(page, tree);

  // What this scenario read, it unreads: a tick here loads, and the
  // scenarios that follow start from the session this one found.
  await focusRenderView(page);
  const dt = dataTree(page);
  await expandTree(dt);
  for (const name of big.unread) {
    const r = treeRow(dt, name);
    if (await r.count()) await untickAnswering(page, r);
  }
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).length === loaded,
    { what: 'the ' + big.unread.length + ' properties of ' + big.title
      + ' to be unloaded again' });
});

/* The tree's own reading of its families: each kind folder with the family
   of each of its rep folders and the titles of the leaves under them, from
   the synthetic assembly the server built. */
async function kindsByFamily(page) {
  const xml = (await state(page, 'ui_compare_tree_xml')) || '';
  return page.evaluate((doc) => {
    const root = new DOMParser().parseFromString(doc, 'application/xml');
    return [...root.documentElement.children].map((k) => ({
      title: k.getAttribute('title'),
      reps: [...k.children].map((r) => ({
        family: r.getAttribute('family'),
        leaves: [...r.children].map((e) => e.getAttribute('title')),
        unread: [...r.querySelectorAll('[loadState="unloaded"]')]
          .map((e) => e.getAttribute('title')),
      })),
    }));
  }, xml);
}

test('the tree is cut into the data tree\'s family cards, and a tick in one reads what it shows', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  const panel = await openCompare(page);

  // One toolbar button per family, in the data tree's order, whatever the
  // file holds: a family the file has nothing of is GREYED and says why,
  // never missing. "Other" is drawn only while a rep fits none of the three.
  const kinds = await kindsByFamily(page);
  const families = ['Reservoir', 'Surface', 'Well', 'Seismic'];
  const count = (fam) => kinds.filter((k) => k.reps.some((r) => r.family === fam)).length;
  const other = kinds.some((k) => k.reps.some((r) => r.family === 'Other'));
  const buttons = await panel.locator(M.toolButton).evaluateAll((els) => els.map((e) => ({
    title: e.title, disabled: e.disabled })));
  note('toolbar: ' + buttons.map((b) => b.title + (b.disabled ? ' (greyed)' : '')).join(' | ')
    + ' — kinds: ' + kinds.map((k) => k.title + ' [' + k.reps.map((r) => r.family).join(', ') + ']').join(', '));
  expect(buttons.map((b) => b.title.split(' — ')[0]), 'one button per family, in the data tree\'s order')
    .toEqual([...families, ...(other ? ['Other'] : [])]);
  for (const f of families) {
    expect(buttons.find((b) => b.title.startsWith(f)).disabled, f + ' greyed when the file has nothing of it')
      .toBe(count(f) === 0);
  }
  expect(kinds.every((k) => k.reps.every((r) => r.family)),
    'every rep folder carries a family, so nothing the tree lists is out of every card')
    .toBe(true);

  const full = families.find((f) => count(f) > 0);
  const tree = await familyCardTree(page, panel, full);
  await expandTree(tree);

  // Under a tab a kind folder shows its reps of that family only, and a
  // tick on it reads THOSE: the smallest kind folder of the tab, under the
  // cap so nothing asks. A file whose every rep is of one family (the smoke
  // file: one grid) exercises the rule in its degenerate form — the whole
  // folder — which is what the count below then equals.
  const inTab = kinds.map((k) => ({
    title: k.title,
    shown: k.reps.filter((r) => r.family === full).flatMap((r) => r.leaves),
    hidden: k.reps.filter((r) => r.family !== full).flatMap((r) => r.leaves),
    unread: k.reps.filter((r) => r.family === full).flatMap((r) => r.unread),
  })).filter((k) => k.shown.length && k.shown.length <= MAX_TICK_LOAD)
    .sort((a, b) => a.shown.length - b.shown.length);
  test.skip(!inTab.length, 'no kind folder of ' + full + ' under the cap');
  const pick = inTab[0];
  // what an earlier scenario read of it is unloaded first (see unloadLeaves)
  await unloadLeaves(app, tree, pick.shown.filter((t) => !pick.unread.includes(t)));
  pick.unread = pick.shown.slice();
  note(`tick ${pick.title} under ${full}: ${pick.shown.length} shown, ${pick.hidden.length} in other tabs`);
  const shownRows = await tree.locator(M.treeRow).allInnerTexts();
  for (const name of pick.hidden) {
    expect(shownRows.some((r) => r.includes(name)), name + ' is of another family and not drawn here')
      .toBe(false);
  }
  const held = (await state(page, 'ui_loaded_array_paths')) || [];
  await treeRow(tree, pick.title).locator(M.treeCheck).click();
  await expect(page.locator(M.dialog), 'under the cap the tick asks nothing').toHaveCount(0);
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'the tick cascaded over what the tab shows of ' + pick.title, timeout: 60000 })
    .toBe(pick.shown.length);
  const titles = (await compareItems(page)).map((c) => c.title);
  for (const name of pick.hidden) {
    expect(titles.some((c) => c.includes(name)), name + ' belongs to another tab and was not read')
      .toBe(false);
  }
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).length >= held.length + pick.unread.length,
    { what: 'the ' + pick.unread.length + ' unread properties of ' + pick.title + ' to be read' });
  await assertReadIsHidden(app, panel, tree, held, pick.unread);
  await emptyByTheEyes(page, tree);

  // What this scenario read, it unreads, for the scenarios after it.
  await focusRenderView(page);
  const dt = dataTree(page);
  await expandTree(dt);
  for (const name of pick.unread) {
    const r = treeRow(dt, name);
    if (await r.count()) await untickAnswering(page, r);
  }
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).length === held.length,
    { what: 'the properties of ' + pick.title + ' to be unloaded again' });
});

test('two properties side by side: a tab shows its matrix and both charts', async ({ app }) => {
  const { page, note } = app;
  // Ticked in the data tree here, the usual path to this view; its own tree
  // offers them either way (the scenarios above).
  for (const name of DATASET.properties) await ensureProperty(app, name);

  const panel = await openCompare(page);
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);
  const rows = await tree.locator(M.treeTitle).allInnerTexts();
  note('docked tree: ' + rows.map((r) => r.trim()).join(', '));
  expect(rows.length, 'the docked tree lists the loaded properties')
    .toBeGreaterThan(1);

  // A tick in the data tree opened its eye, so here too; what a closed eye left
  // out comes by its eye, with every loaded property of its kind
  for (const name of DATASET.properties) {
    const eye = treeRow(tree, name).locator(M.treeEye);
    if ((await eye.getAttribute('title')) !== 'Hide') await eye.click();
    await expect(eye, 'in the view: ' + name).toHaveAttribute('title', 'Hide', { timeout: 30000 });
  }
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'an item for each property', timeout: 30000 }).toBe(DATASET.properties.length);
  const items = await compareItems(page);
  note('items: ' + items.map((c) => c.title + ' (' + c.kind + ')').join(' | '));
  expect(items.length, 'one item per ticked property')
    .toBe(DATASET.properties.length);

  // One tab per kind of the selection; a tab shows at once its matrix, its
  // distributions below at the left and its cross-plot below at the right.
  const kinds = (await state(page, 'ui_compare_kinds')) || [];
  const tabs = (await panel.locator(M.compareTab).allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim());
  note('tabs: ' + tabs.join(' | '));
  expect(kinds.length, 'the selection has at least one kind').toBeGreaterThan(0);
  expect(tabs.length, 'one tab per kind, nothing else').toBe(kinds.length);
  for (const k of kinds) {
    await panel.locator(M.compareTab, { hasText: k.kind }).first().click();
    await expect(panel.locator(M.compareTabOn), 'the kind tab is the current one').toContainText(k.kind);
    await expect(panel.locator(M.compareOwnItem), 'the matrix shows one row per item of the kind').toHaveCount(k.count);
    await expect(panel.locator('.fcp-chart'), 'the distributions and the cross-plot, under it').toHaveCount(2);
  }
  await expect.poll(async () => panel.locator('.fcp-chart').first().locator('.js-plotly-plot').count(),
    { message: 'the distributions drew their figure' }).toBeGreaterThan(0);
  expect((await compareItems(page)).length, 'the selection keeps its items').toBeGreaterThan(0);
  // The axes are picked over the chart, among the rows of the matrix
  const xplot = panel.locator('.fcp-chart').nth(1);
  const axes = await state(page, 'ui_compare_xplot_axes');
  expect(axes.y, 'an X and a Y, never the same row').not.toBe(axes.x);
  await xplot.locator('button[title="Swap X and Y"]').click();
  await expect.poll(() => state(page, 'ui_compare_xplot_axes'), { message: 'the axes swap', timeout: 30000 })
    .toEqual({ x: axes.y, y: axes.x });
});

test('the matrix rows carry the acts of an item: a right-click sets the baseline, removes, and says why it cannot pin', async ({ app }) => {
  const { page, note } = app;
  for (const name of DATASET.properties) await ensureProperty(app, name);
  const panel = await openCompare(page);
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);
  for (const name of DATASET.properties) {
    const held = await compareItems(page);
    if (held.some((c) => c.title.includes(name))) continue;
    // loaded already: its eye puts it in the view
    await treeRow(tree, name).locator(M.treeEye).click();
    await expect.poll(async () => (await compareItems(page)).length,
      { message: 'an item appears for ' + name, timeout: 60000 }).toBeGreaterThan(held.length);
  }

  // the matrix of the first kind: one row per item, and what follows them
  const kinds = (await state(page, 'ui_compare_kinds')) || [];
  await panel.locator(M.compareTab, { hasText: kinds[0].kind }).first().click();
  await expect.poll(() => panel.locator(M.compareOwnItem).count(),
    { message: 'the matrix draws the rows of the kind', timeout: 30000 }).toBe(kinds[0].count);
  const before = await compareItems(page);

  // a right-click on a row opens the menu of that item; an act it cannot
  // make on this property is there, disabled, with why
  const first = panel.locator(M.compareOwnItem).first();
  await first.click({ button: 'right' });
  const menu = page.locator(M.compareRowMenu);
  await menu.waitFor({ timeout: 10000 });
  const items = (await menu.locator('.fp-menu-item').allInnerTexts()).map((t) => t.trim());
  note('row menu: ' + items.join(' | '));
  expect(items, 'the row offers the baseline').toContain('Set as baseline');
  expect(items, 'the row offers a pinned copy').toContain('Pin a copy of this row');
  // its distribution and cross-plot are under the matrix, the eye takes it out
  for (const gone of ['Remove from stats', 'Show distribution', 'Cross-plot']) expect(items).not.toContain(gone);
  const disabledWhy = await menu.locator('.fp-menu-item[aria-disabled="true"]').evaluateAll(
    (els) => els.map((e) => [e.innerText.trim(), e.getAttribute('title') || '']));
  note('disabled: ' + disabledWhy.map(([l, t]) => l + ' — ' + t).join(' | '));
  for (const [label, why] of disabledWhy) expect(why, label + ' says why it is disabled').not.toBe('');

  // pin: this property names no realization and no time step, so a copy of its
  // row would keep nothing: no pin on the row, the entry greyed with why
  const blocks = (await state(page, 'ui_compare_blocks')) || [];
  const rows = (await state(page, 'ui_compare_rows')) || {};
  const read = rows[blocks[0].keys[0]];
  note('the first row: ' + read.title + ', ' + read.reals.length + ' realization(s), '
    + read.ts_opts.length + ' time step(s)');
  const pin = menu.locator('.fp-menu-item', { hasText: 'Pin a copy of this row' });
  if (!read.reals.length && !read.ts_opts.length) {
    await expect(pin, 'nothing to pin a copy at').toHaveAttribute('aria-disabled', 'true');
    expect(await pin.getAttribute('title'), 'and it says so').toContain('no realization and no time step');
    await expect(first.locator('button[title^="Pin a copy"]'), 'no pin on the row').toHaveCount(0);
  }
  await page.keyboard.press('Escape');
  await expect(menu, 'Escape closes it').toHaveCount(0);

  // The acts on the other row of the kind, found by its name: the matrix puts
  // its baseline first.
  const otherId = blocks[0].keys.find((k) => k !== blocks[0].keys[0] && !rows[k].support
    && DATASET.properties.some((n) => rows[k].title.includes(n)));
  test.skip(!otherId, 'one property of this kind: no other row to read against');
  const otherName = DATASET.properties.find((n) => rows[otherId].title.includes(n));
  const other = panel.locator(M.compareOwnItem).filter({ hasText: otherName }).first();

  // baseline: the yellow moves to it, and the server holds it by its id
  await other.click({ button: 'right' });
  await menu.locator('.fp-menu-item', { hasText: 'Set as baseline' }).click();
  await expect.poll(() => state(page, 'ui_compare_baseline'),
    { message: 'the row is the baseline of its kind', timeout: 30000 }).toBe(otherId);
  await expect(panel.locator(M.compareItem + '.fcp-row-base'), 'one yellow row').toHaveCount(1);
  await expect(other, 'the yellow row is the one picked').toHaveClass(/fcp-row-base/);

  // the same gesture on it goes back to plain statistics
  await other.click({ button: 'right' });
  await menu.locator('.fp-menu-item', { hasText: 'Clear baseline' }).click();
  await expect.poll(() => state(page, 'ui_compare_baseline'),
    { message: 'no baseline', timeout: 30000 }).toBe('');
  await expect(panel.locator(M.compareItem + '.fcp-row-base'), 'no yellow row').toHaveCount(0);

  // its eye takes it out: the row goes, the property stays loaded
  const otherPath = before.find((c) => c.uid === otherId).path;
  await treeRow(tree, otherName).locator(M.treeEye).click();
  await expect.poll(async () => (await compareItems(page)).length,
    { message: 'the row left the statistics', timeout: 30000 }).toBeLessThan(before.length);
  expect((await state(page, 'ui_loaded_array_paths')) || [], 'the property stays loaded').toContain(otherPath);

  // and brings it back for the scenarios after this one
  const eye = treeRow(tree, otherName).locator(M.treeEye);
  await expect(eye, 'its eye is closed').toHaveAttribute('title', 'Show', { timeout: 30000 });
  await eye.click();
  await expect.poll(async () => (await compareItems(page)).some((c) => c.path === otherPath),
    { message: 'the eye brought it back', timeout: 30000 }).toBe(true);
  await expect.poll(() => panel.locator(M.compareOwnItem).count(),
    { message: 'the matrix has its rows back' }).toBeGreaterThanOrEqual(kinds[0].count);
});
