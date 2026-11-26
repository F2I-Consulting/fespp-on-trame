/*
 * Scenario (c): the tree's context menu.
 *
 * The action list is serialised into a template attribute: a double quote in
 * it that closes the attribute early leaves a template that does not compile
 * and a menu that never appears. Nothing but a right-click in a real browser
 * tests that path.
 *
 * The menu is also where the tree's typing shows: value actions are offered on
 * a property; a folder, which has no values to read, opens no menu at all.
 *
 * "Add to Well Log view" is offered on a wellbore and on what sits under one. The
 * driven file (vector_props.epc) holds one grid and no well, so only the
 * negative side is asserted here: a grid property must NOT offer it. The positive side (right-click a wellbore → the entry is there and
 * opens the log view) needs a file with a well; drive one with
 * FESPP_SMOKE_EPC to check it.
 */
import {
  test, expect, M, DATASET,
  ensureData, ensureProperty, expandTree, readContextMenu, dataTree, focusRenderView,
  state, treeRow, viewId,
} from '../lib/app.mjs';

const VALUE_ACTIONS = ['Stats', 'Derived property'];
const WELL_ACTION = 'Add to Well Log view';
const XML_ACTION = 'Info';

test('a property offers its actions', async ({ app }) => {
  const { page, note } = app;
  // loaded: an unread row offers Info alone (10-words)
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);

  const name = DATASET.properties[0];
  const menu = await readContextMenu(tree, name);
  note('menu on ' + name + ': ' + menu.items.join(' | '));

  expect(menu.title, 'the menu names the node').toBe(name);
  expect(menu.items.length, 'the menu has items').toBeGreaterThan(1);
  for (const action of VALUE_ACTIONS) {
    expect(menu.items, 'action offered on a property').toContain(action);
  }
  expect(menu.items, 'a grid property has no well to send').not.toContain(WELL_ACTION);
  expect(menu.items, 'every row can be explored as XML').toContain(XML_ACTION);
});

test('a folder opens no menu: the right-click makes it the active node', async ({ app }) => {
  const { page } = app;
  await ensureData(app);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const vid = await viewId(page);

  const row = treeRow(tree, DATASET.folder);
  const path = await row.getAttribute('data-path');
  await row.click({ button: 'right' });
  await expect.poll(() => state(page, 'active_path__' + vid), { message: 'the folder is active' }).toBe(path);
  await expect(page.locator(M.ctxMenu), 'no menu on a folder').toHaveCount(0);
});

async function treeRightClick(page, tree, title) {
  await tree.locator(M.treeRow)
    .filter({ has: page.locator(M.treeTitle, { hasText: new RegExp('^' + title + '$') }) })
    .first()
    .click({ button: 'right' });
  await page.locator(M.ctxMenu).waitFor({ timeout: 10000 });
}

test('Info opens the explorer on the row', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);

  const before = await page.locator(M.dockTab).count();
  await treeRightClick(page, tree, DATASET.properties[0]);
  await page.locator(M.ctxItem, { hasText: /^Info$/ }).click();
  await page.locator(M.dockTab).nth(before).waitFor({ timeout: 60000 });
  const tabs = (await page.locator(M.dockTab).allInnerTexts()).map((t) => t.trim());
  note('panels: ' + tabs.join(', '));
  expect(tabs[before], 'an Explorer panel opened').toMatch(/Explorer/);
  // the explorer opens on the object, not on its empty state: the tab
  // strip of the viewer names the property
  const opened = page.locator(M.dockPart).nth(before);
  await expect(opened.getByText(DATASET.properties[0], { exact: false }).first(),
    'the explorer names the object it opened on').toBeVisible({ timeout: 20000 });
  // the view is independent: its own find row lists the repository, and a
  // pick opens a tab of THIS panel
  const other = DATASET.properties[1] || DATASET.properties[0];
  await opened.locator('.fxv-find-in').fill(other);
  const hits = opened.locator('.fxv-hit');
  await expect(hits.first(), 'the find row lists a matching object').toBeVisible({ timeout: 15000 });
  const hitTitles = await hits.locator('.fxv-hit-t').allInnerTexts();
  note('find "' + other + '": ' + hitTitles.slice(0, 5).join(' | '));
  expect(hitTitles.some((t) => t.trim() === other), 'the property is among the hits').toBe(true);
  await hits.filter({ hasText: other }).first().click();
  await expect(opened.locator('.fxv-tab', { hasText: other }), 'the pick opened a tab in the same panel')
    .toHaveCount(1, { timeout: 15000 });
  await expect(opened.locator('.fxv-hit'), 'the list is cleared after the pick').toHaveCount(0);
  expect(await page.locator(M.dockTab).count(), 'no second panel opened').toBe(before + 1);
  // leave the session as found: the panel closed (an extra panel narrows the
  // layout every later scenario measures)
  await page.locator(M.dockTab).nth(before).locator('.dv-default-tab-action').click();
  await expect(page.locator(M.dockTab), 'the explorer panel closed').toHaveCount(before, { timeout: 10000 });
});

