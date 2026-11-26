/*
 * Scenario (k): the application reads as ONE product.
 *
 * The rules under test are the ones an eye checks and a unit test cannot: the
 * header a panel wears, the sentence an empty panel says and whether the
 * gesture it names exists, which tree offers a bulk-select, the verb on an
 * action button, and the one confirmation box.
 *
 * It runs BEFORE the panel sweep on purpose: Statistics and the well log are
 * singletons whose docked tree is given its opening state when the panel is
 * BUILT, and that state ("closed, unless the panel is empty") can only be read
 * on the first opening.
 */
import {
  test, expect, M, ensureData, dataTree, familyCardTree, focusRenderView, state,
} from '../lib/app.mjs';

/* A top-bar button by the beginning of its tooltip (the tooltips carry an
 * em dash and a "↔": reading them off the bar beats spelling them here). */
async function topBar(page, prefix) {
  const titles = await page.locator(M.topBarButton + '[title]').evaluateAll(
    (els) => els.map((e) => e.getAttribute('title')));
  const title = titles.find((t) => t.startsWith(prefix));
  expect(title, 'the top bar offers "' + prefix + '"').toBeTruthy();
  return page.locator(M.topBarButton + '[title=' + JSON.stringify(title) + ']');
}

/* The panel whose header title is exactly `name`.
 *
 * `\s*` around it on purpose: a panel written in Python has its markup
 * generated line by line, so the title's text node carries the newlines of
 * the source — and a Playwright regex is matched against the text AS IS,
 * without the whitespace folding a plain string gets. */
function panelTitled(page, name) {
  return page.locator(M.dockPart)
    .filter({
      has: page.locator(M.bar + ' ' + M.title,
        { hasText: new RegExp('^\\s*' + name + '\\s*$') }),
    })
    .first();
}

async function openStats(app) {
  const { page } = app;
  await ensureData(app);
  const panel = panelTitled(page, 'Statistics');
  // at the front, its button would close it
  if (!(await panel.locator(M.bar).first().isVisible().catch(() => false))) {
    await (await topBar(page, 'Statistics')).click();
  }
  await panel.locator(M.bar).first().waitFor({ timeout: 60000 });
  return panel;
}

test('the statistics panel wears the charter header, its trees in its toolbar',
  async ({ app }) => {
    const { page, note } = app;
    const panel = await openStats(app);

    const bar = panel.locator(M.bar).first();
    await expect(bar.locator(M.title), 'the bar names the panel')
      .toHaveText('Statistics');
    expect(await bar.locator(M.treeToggle).count(), 'no tree button in the header').toBe(0);

    // one toolbar button per family, as a 3D view's, greyed when the file
    // has no property of it
    const titles = await panel.locator(M.toolButton).evaluateAll((els) => els.map((e) => e.title));
    note('toolbar: ' + titles.join(' | '));
    for (const family of ['Reservoir', 'Surface', 'Well']) {
      expect(titles.some((t) => t.startsWith(family)), 'a ' + family + ' button').toBe(true);
    }
  });

test('an empty statistics panel opens its own tree and names doors that exist',
  async ({ app }) => {
    const { page, note } = app;
    const held = (await state(page, 'ui_compare_items')) || [];
    const panel = await openStats(app);
    note(held.length + ' held when the panel was built');
    const tree = panel.locator(M.tree).first();

    await expect(tree, 'the view opens with its tree showing').toBeVisible({ timeout: 30000 });
    if (held.length === 0) {
      const words = (await panel.locator(M.empty).first().innerText())
        .replace(/\s+/g, ' ').trim();
      note('empty state: "' + words + '"');
      expect(words, 'the empty state names the tree').toContain('own tree');
      expect(words, 'the empty state names the right-click door').toContain('Stats');
      // no icon is named: the panel draws none for the reader to look for
      expect(words, 'the empty state names an icon nobody renders')
        .not.toMatch(/icon/i);
    }

    // and its toolbar button closes its card, and opens it again
    const button = panel.locator(M.toolButton + '.active').first();
    const family = (await button.getAttribute('title')).split(' — ')[0];
    await button.click();
    await expect(tree, 'the toolbar button closes the tree card').toBeHidden({ timeout: 30000 });
    await familyCardTree(page, panel, family);
    await expect(panel.locator(M.tree).first(), 'and opens it').toBeVisible({ timeout: 30000 });
  });

test('"Select ▾" is offered in the data tree and in no panel tree',
  async ({ app }) => {
    const { page, note } = app;
    await openStats(app);
    const door = await topBar(page, 'Log view');
    test.skip(await door.isDisabled(), 'the Log view needs a wellbore: drive a file with one (FESPP_SMOKE_EPC)');
    await door.click();
    const log = page.locator(M.dockPart)
      .filter({ has: page.locator('button[title$="well tree"]') }).first();
    await log.waitFor({ timeout: 60000 });

    await focusRenderView(page);
    const counts = {
      data: await dataTree(page).locator(M.treeBulk).count(),
      stats: await panelTitled(page, 'Statistics').locator(M.treeBulk).count(),
      welllog: await log.locator(M.treeBulk).count(),
    };
    note('Select ▾ — data ' + counts.data + ', statistics ' + counts.stats
      + ', well log ' + counts.welllog);
    expect(counts.data, 'the data tree keeps its bulk select').toBe(1);
    // its "Select all (N)" row ticks representations into the 3D scene, and a
    // panel's tree has no business commanding the scene
    expect(counts.stats, 'the statistics tree still offers Select ▾').toBe(0);
    expect(counts.welllog, 'the well-log tree still offers Select ▾').toBe(0);
  });

test('one verb per act: Log ↔ Grid refreshes, nothing recomputes',
  async ({ app }) => {
    const { page, note } = app;
    await ensureData(app);
    const door = await topBar(page, 'Log ↔ Grid');
    test.skip(await door.isDisabled(), 'Log ↔ Grid needs logs and a grid: drive a file with both (FESPP_SMOKE_EPC)');
    await door.click();
    const panel = page.locator(M.reconcile).first();
    await panel.waitFor({ timeout: 60000 });

    const labels = (await panel.locator(M.bar + ' button').allInnerTexts())
      .map((t) => t.trim()).filter(Boolean);
    note('Log ↔ Grid bar: ' + labels.join(', '));
    expect(labels, 'the panel forces its recompute with "Refresh"')
      .toContain('Refresh');

    // one verb for "read the inputs again and rebuild the table": Compute
    // when nothing exists yet, Refresh otherwise, never a third one
    const onScreen = await page.locator('body').innerText();
    expect(onScreen, 'something on screen still says "Recompute"')
      .not.toMatch(/\bRecompute\b/);
  });

test('the confirmation box is the one box of the application', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  // The box is raised by a tick standing for more than
  // engine/tick_confirm.MAX_TICK_LOAD unread properties. The smoke file holds
  // three, so the question is posed here by hand: what is under test is the
  // box the LAYOUT draws and the answer travelling back to the server, not
  // the counting, which the unit suite holds.
  const posed = await page.evaluate(async () => {
    const s = window.trame && window.trame.state;
    if (!s || typeof s.set !== 'function') return false;
    await s.set('ui_tick_confirm', {
      title: 'Read 42 properties?',
      body: 'Reading them also puts them, and the representations they'
        + ' belong to, in the 3D views. Nothing has been read yet.',
      ok: 'Read 42 properties',
    });
    // the client holds a write back while a call of its own runs: an answer
    // overtaking it would find nothing to clear on the server
    while (s.dirtyKeys.size) {
      await new Promise((done) => { setTimeout(done, 50); });
      await s.flush();
    }
    return true;
  });
  test.skip(!posed,
    'this trame client exposes no state setter: the box cannot be posed by hand');

  const dialog = page.locator(M.dialog);
  await dialog.waitFor({ timeout: 30000 });
  const words = (await dialog.innerText()).replace(/\s+/g, ' ').trim();
  note('asked: ' + words);
  expect(words, 'the box says how many properties it would read')
    .toContain('42');
  expect(words, 'the box says what reading them also does')
    .toContain('3D views');

  const cancel = dialog.locator('button', { hasText: /^\s*Cancel\s*$/ });
  await expect(cancel, 'stepping back is offered').toHaveCount(1);

  // The two escape hatches of charter rule R7 (see
  // doc/wiki/UI-Drawer-Toolbar-Shared.md). The box is opened by a CLICK,
  // which leaves the focus on the row behind the veil: a browser then refuses
  // the autofocus of a button inserted after page load, and a key pressed
  // outside the box never reaches a listener inside it. So the dialog focuses
  // Cancel itself, and Esc is listened for where the focus then is.
  const focused = await page.evaluate(() => {
    const el = document.activeElement;
    return el ? (el.className || '') + '|' + (el.innerText || '').trim() : '';
  });
  note('focus with the box up: ' + focused);
  expect(focused, 'Cancel has the focus').toContain('Cancel');

  await page.keyboard.press('Escape');
  await expect(dialog, 'Esc answers what the scrim answers')
    .toHaveCount(0, { timeout: 30000 });
  expect(await state(page, 'ui_tick_confirm'),
    'the server dropped the question Esc stepped back from').toEqual({});
});
