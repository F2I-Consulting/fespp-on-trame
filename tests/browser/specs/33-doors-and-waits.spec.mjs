/*
 * Scenario: the top bar's views, the wait that greys what it holds, the menus
 * of the trees, the Kind layout.
 *
 * In the browser: a button of the top bar opens a view and closes it; a wait
 * named in the pill covers what lies under the app bar; a second right-click
 * replaces the menu; the Kind layout moves no tick; Values shows no wait from
 * one row nothing read to another, and a click on the colour bar opens the
 * Colormap card.
 */
import {
  test, expect, M, DATASET,
  anchorButton, closeView, ensureProperty, ensureShown, focusRenderView, openCompare, showView, state, viewButton, viewId, dataTree, expandTree, treeRow,
} from '../lib/app.mjs';

const rowOf = (page, title) => page.locator('.fdx-body:visible .tn-row', { hasText: title }).first();

test('a button of the top bar opens a view, and closes it at the front', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const button = page.locator(M.topBarButton + '[title^="Values"]');
  await showView(page, 'Values', page.locator('.fap'));
  await expect.poll(() => state(page, 'ui_open_view_kinds'), { message: 'the view opened', timeout: 30000 })
    .toContain('values');
  await expect(button, 'the button says it is open').toHaveClass(/v-btn--active/);
  await button.click();
  await expect.poll(() => state(page, 'ui_open_view_kinds'), { message: 'the view closed', timeout: 30000 })
    .not.toContain('values');
});

test('the views of the work stand left of the spacer, what is about the data right of it', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  const lefts = await page.locator(M.topBarButton).evaluateAll((els) => els.map((e) => [
    (e.getAttribute('title') || '').split(' ')[0], e.getBoundingClientRect().left]));
  const at = (word) => (lefts.find(([w]) => w === word) || [null, -1])[1];
  const order = ['3D', 'Globe', 'Values', 'Explorer', 'Statistics', 'Calculator', 'Stratigraphy', 'Log', 'Data'];
  const seen = order.map(at);
  expect(seen.every((x) => x >= 0), 'every button is there: ' + JSON.stringify(lefts)).toBe(true);
  expect([...seen].sort((a, b) => a - b), 'in that order').toEqual(seen);
  const room = await page.evaluate(() => window.innerWidth);
  expect(at('Data'), 'Data health is on the right').toBeGreaterThan(room / 2);
  expect(at('Statistics'), 'Statistics on the left').toBeLessThan(room / 2);
});

test('a wait named in the pill greys what it holds, a read in steps holds nothing', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  const scrim = page.locator('[data-fp-page-wait]');
  await expect(scrim, 'no wait, nothing over the page').toHaveCount(0);
  const say = (note) => page.evaluate((v) => {
    window.trame.state.set('ui_work_note', v);
    return window.trame.state.flush();
  }, note);
  await say('Updating the velocity model…');
  await expect(scrim, 'the wait greys the page').toBeVisible({ timeout: 10000 });
  await expect(page.locator('header ~ * .fp-progress[role="progressbar"], .fp-progress[role="progressbar"]').last(),
    'its pill stays over it').toBeVisible();
  await say('');
  await expect(scrim, 'and the grey goes with it').toHaveCount(0, { timeout: 10000 });
});

test('a right-click beside the menu closes it and opens the one of the row it landed on', async ({ app }) => {
  const { page, note } = app;
  const [a, b] = DATASET.properties;
  await ensureProperty(app, a);
  await ensureProperty(app, b);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const boxOf = async (name) => treeRow(tree, name).boundingBox();
  const title = page.locator('.fdx-ctx .fp-menu-title');
  const menuOn = async (name) => {
    await treeRow(tree, name).click({ button: 'right' });
    await expect(title.first(), 'the first menu').toHaveText(name, { timeout: 10000 });
  };
  // A point of the row the open menu leaves clear, in the tree's own rows: the
  // right-click centred the first row, the other may stand half under the
  // tree's toolbar or past its bottom; and the menu, opened upward when the
  // room below is short, may cover the row's middle.
  const clearOf = async (name) => {
    const box = await boxOf(name);
    const rows = await tree.locator('.fdx-body').boundingBox();
    const menu = await page.locator('.fdx-ctx .fp-menu').first().boundingBox();
    const under = (x, y) => menu && x >= menu.x && x <= menu.x + menu.width && y >= menu.y && y <= menu.y + menu.height;
    const ys = [0.5, 0.25, 0.75].map((f) => box.y + box.height * f)
      .filter((y) => y > rows.y + 2 && y < rows.y + rows.height - 2);
    for (const y of ys) {
      const x = [0.5, 0.25, 0.75, 0.9].map((f) => box.x + box.width * f).find((v) => !under(v, y));
      if (x !== undefined) return { x, y };
    }
    return null;
  };
  // the lower row first: its menu opens below the pointer, the upper row stays
  // clear. Near the end of the rows it opens upward, and in a narrow tree it
  // may cover the upper row across its width: then the other way round.
  let [first, other] = (await boxOf(a)).y > (await boxOf(b)).y ? [a, b] : [b, a];
  await menuOn(first);
  let spot = await clearOf(other);
  if (!spot) {
    note('the menu of ' + first + ' covers ' + other + ': the other way round');
    await page.locator(M.backdrop).first().dispatchEvent('click');
    await expect(title, 'the first menu closes').toHaveCount(0, { timeout: 10000 });
    [first, other] = [other, first];
    await menuOn(first);
    spot = await clearOf(other);
  }
  expect(spot, 'a point of the other row that the menu leaves clear').not.toBeNull();
  await page.mouse.click(spot.x, spot.y, { button: 'right' });
  await expect(title, 'one menu').toHaveCount(1, { timeout: 10000 });
  await expect(title.first(), 'the menu of the other row').toHaveText(other);
  const items = (await page.locator(M.ctxItem).allInnerTexts()).map((t) => t.trim());
  expect(items.slice(-2), 'Stats, then Info, last').toEqual(['Stats', 'Info']);
  await page.keyboard.press('Escape');
});

test('the Kind layout moves no tick, and a kind folder ticks what it holds', async ({ app }) => {
  const { page } = app;
  const name = DATASET.properties[0];
  const path = await ensureProperty(app, name);
  await focusRenderView(page);
  const tree = dataTree(page);
  const strip = tree.locator('.fdx-layout .fp-seg');
  const before = (await state(page, 'selected_paths')) || [];
  await strip.locator('button', { hasText: /^Prop\. kind$/ }).click();
  await expect(strip.locator('button.fp-on'), 'Kind is in force').toHaveText('Prop. kind', { timeout: 15000 });
  expect((await state(page, 'selected_paths')) || [], 'no tick moved').toEqual(before);
  await expandTree(tree);
  await expect(treeRow(tree, name).first(), 'the property under its kind').toBeVisible({ timeout: 15000 });
  expect(await treeRow(tree, name).first().getAttribute('data-path'), 'on its own path').toBe(path);
  await strip.locator('button', { hasText: /^Representation$/ }).click();
  await expect(strip.locator('button.fp-on'), 'back').toHaveText('Representation', { timeout: 15000 });
});

test('Values: no wait from one row nothing read to another, the tab names the row', async ({ app }) => {
  const { page } = app;
  const [a] = DATASET.properties;
  await ensureProperty(app, a);
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  // the properties nothing read: a row with a box, not ticked, and nothing under it
  const read = new Set((await state(page, 'selected_paths')) || []);
  const titles = await tree.locator('.tn-row').evaluateAll((els, ticked) => els
    .filter((e) => e.querySelector('.tn-check') && !ticked.includes(e.dataset.path)
      && !e.querySelector('.tn-caret, .tn-toggle') && /_propsfolder_/.test(e.dataset.path || ''))
    .map((e) => (e.querySelector('.tn-title') || {}).innerText || '').filter(Boolean), [...read]);
  test.skip(titles.length < 2, 'this file has no two unread properties');
  await showView(page, 'Values', page.locator('.fap'));
  await focusRenderView(page);
  await rowOf(page, titles[0]).click();
  await expect(page.locator(M.dockTab, { hasText: 'Values' }).first(), 'the tab names it')
    .toContainText(titles[0], { timeout: 15000 });
  await rowOf(page, titles[1]).click();
  await expect(page.locator(M.dockTab, { hasText: 'Values' }).first(), 'and the next one')
    .toContainText(titles[1], { timeout: 15000 });
  await expect(page.locator('.fap .fp-progress:visible'), 'nothing to wait for').toHaveCount(0);
  // left closed for the scenarios after this one: to the front, then shut
  await showView(page, 'Values', page.locator('.fap'));
  await page.locator(M.topBarButton + '[title^="Values"]').click();
  await expect.poll(() => state(page, 'ui_open_view_kinds'), { timeout: 30000 }).not.toContain('values');
});

test('a click on the colour bar opens the Colormap card on what it paints', async ({ app }) => {
  const { page } = app;
  const name = DATASET.properties[0];
  await ensureProperty(app, name);
  await ensureShown(app, name);
  await focusRenderView(page);
  const vid = await viewId(page);
  const hit = page.locator('.fp-bar-hit:visible').first();
  await expect(hit, 'the bar is clickable').toBeVisible({ timeout: 30000 });
  await hit.click();
  await expect.poll(async () => ((await state(page, 'ui_open_tools_by_view')) || {})[vid] || [],
    { message: 'the card opens', timeout: 15000 }).toContain('colormap');
  // the Colormap card in front, on the property (the tree's card, behind its
  // tab, names it too)
  const card = page.locator(M.card + ':visible')
    .filter({ has: page.locator(M.cardTitle, { hasText: /^Colou?r/ }) }).filter({ hasText: name });
  await expect(card.first(), 'on the property').toBeVisible({ timeout: 15000 });
});

test('the time-depth model is a view along the whole bottom, the same for every 3D view', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const button = page.locator(M.topBarButton + '[title^="Time-depth"]');
  const view = page.locator('.tdp').first();
  await showView(page, 'Time-depth', page.locator('.tdp'));
  await expect(view, 'its widget').toBeVisible({ timeout: 15000 });
  const box = await view.boundingBox();
  const room = page.viewportSize();
  expect(box.width, 'along the whole width').toBeGreaterThan(room.width * 0.9);
  expect(box.y, 'at the bottom').toBeGreaterThan(room.height / 3);
  // its zoom stands in its tab row, and a track keeps its size as it zooms
  await expect(page.locator('.tdp-chrome .fp-z'), 'its Z').toBeVisible();
  await expect(page.locator('[data-fp-page-wait]'), 'the model written').toHaveCount(0, { timeout: 60000 });
  // no TDLaw to start with: one placed at the centre of the zone, its track
  if (!(await page.locator('.tls').count())) {
    await page.locator('.tdl-add button', { hasText: /^Place$/ }).click();
  }
  const track = page.locator('.tls').first();
  await expect(track, 'a track').toBeVisible({ timeout: 15000 });
  const before = (await track.boundingBox()).width;
  const rows = await page.locator('.tdl-rows').first().boundingBox();
  await page.mouse.move(rows.x + 60, rows.y + rows.height / 2);
  for (let i = 0; i < 5; i++) await page.mouse.wheel(0, -100);
  await expect.poll(async () => Number(await page.locator('.tdp-chrome .fp-num').inputValue()),
    { message: 'the wheel moves the Z', timeout: 15000 }).toBeGreaterThan(1);
  expect((await track.boundingBox()).width, 'the track keeps its width').toBe(before);
  await expect(page.locator('.tdp .fp-vscroll'), 'a scrollbar on the active track').toBeVisible();
  // detached, it moves by the empty part of its title row, its controls still answer
  const tdPart = page.locator(M.dockPart).filter({ has: page.locator('.tdp') });
  await (await viewButton(page, tdPart, 'float')).click();
  const win = page.locator(M.dockWindow);
  await expect(win, 'in a floating window').toHaveCount(1, { timeout: 30000 });
  const was = await win.boundingBox();
  const grip = await win.locator('.dv-void-container').boundingBox();
  await page.mouse.move(grip.x + 20, grip.y + grip.height / 2);
  await page.mouse.down();
  await page.mouse.move(grip.x - 40, grip.y + 40, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await win.boundingBox()).x, { message: 'the window followed the mouse' })
    .toBeLessThan(was.x - 30);
  await expect(page.locator('.tdp-chrome .fp-num'), 'its Z answers').toBeEditable();
  await expect(anchorButton(page), 'its detach button anchors it').toHaveAttribute('title', 'Anchor');
  await anchorButton(page).click();
  await expect.poll(() => state(page, 'ui_floating_views'), { message: 'anchored', timeout: 30000 }).toEqual([]);
  await button.click();
  await expect.poll(() => state(page, 'ui_open_view_kinds'), { message: 'in sight, its button closes it', timeout: 30000 })
    .not.toContain('timedepth');
});

test('a view in time draws time alone: what is in depth waits, its tag no button', async ({ app }) => {
  const { page } = app;
  const name = DATASET.properties[0];
  // in depth, as its file is: the row of the property is what is followed
  const path = await ensureShown(app, name);
  await focusRenderView(page);
  const vid = await viewId(page);
  const switchIt = page.locator('[data-t3-domain]:visible').first();
  test.skip(!(await switchIt.count()), 'this session holds one domain: no switch');
  const domain = () => state(page, 'ui_vdomain__' + vid);
  const rows = async (key) => (await state(page, key + '__' + vid)) || [];
  await expect.poll(() => rows('undrawn_paths'),
    { message: 'in depth, what is in depth is drawn', timeout: 30000 }).not.toContain(path);
  await switchIt.click();
  await expect.poll(domain, { timeout: 30000 }).toBe('time');
  await expect.poll(() => rows('undrawn_paths'),
    { message: 'in time, what is in depth is not drawn', timeout: 30000 }).toContain(path);
  expect(await rows('converted_paths'), 'nothing in depth is converted to time').toEqual([]);
  expect(await rows('fixed_paths'), 'and its tag does not offer it').toContain(path);
  await expect(page.locator('.fdx-body:visible .tn-tag[data-click]'), 'no tag is a button').toHaveCount(0);
  await switchIt.click();
  await expect.poll(domain, { timeout: 30000 }).toBe('depth');
  await expect.poll(() => rows('undrawn_paths'),
    { message: 'back in depth, drawn again', timeout: 30000 }).not.toContain(path);
});

test('a view is detached by its button and anchored again, its content kept', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  const eyes = await state(page, 'visible_paths__' + vid);
  const tabs = (await page.locator(M.dockTab).allInnerTexts()).map((x) => x.trim());
  await (await viewButton(page, page.locator(M.dockPart + ':visible').filter({ has: page.locator('canvas') }).first(), 'float')).click();
  await expect.poll(async () => ((await state(page, 'ui_floating_views')) || []).length,
    { message: 'it floats', timeout: 30000 }).toBe(1);
  await expect(page.locator(M.dockWindow), 'in a floating window').toHaveCount(1);
  const box = await page.locator(M.dockWindow).boundingBox();
  expect(box.width, 'at a size to work in').toBeGreaterThan(page.viewportSize().width / 2);
  const dock = await page.locator(M.dockWindow).locator('xpath=..').boundingBox();
  expect(Math.abs(box.x - dock.x - (dock.width - box.width) / 2), 'centred across the dock').toBeLessThan(3);
  expect(Math.abs(box.y - dock.y - (dock.height - box.height) / 2), 'centred down the dock').toBeLessThan(3);
  expect(await state(page, 'visible_paths__' + vid), 'what it shows stays').toEqual(eyes);
  await anchorButton(page).click();
  await expect.poll(() => state(page, 'ui_floating_views'), { message: 'anchored', timeout: 30000 }).toEqual([]);
  await expect(page.locator(M.dockWindow), 'no floating window').toHaveCount(0);
  expect((await page.locator(M.dockTab).allInnerTexts()).map((x) => x.trim()), 'back among its tabs, at its place')
    .toEqual(tabs);
});

test('a detached view fills the dock on a double click, the other views as its tabs', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await openCompare(page);
  await focusRenderView(page);
  const titles = async (scope) => (await scope.locator(M.dockTab).allInnerTexts()).map((x) => x.trim()).sort();
  const all = await titles(page);
  const part = page.locator(M.dockPart + ':visible').filter({ has: page.locator('canvas') }).first();
  const anchored = await part.boundingBox();
  await page.locator(M.dockTab).first().dblclick();
  await page.waitForTimeout(300);
  expect(await part.boundingBox(), 'an anchored view stays as it is').toEqual(anchored);
  await (await viewButton(page, part, 'float')).click();
  const win = page.locator(M.dockWindow);
  await expect(win, 'in a floating window').toHaveCount(1, { timeout: 30000 });
  await expect.poll(async () => ((await state(page, 'ui_floating_views')) || []).length, { message: 'reported', timeout: 30000 }).toBe(1);
  const [vid] = await state(page, 'ui_floating_views');
  const eyes = await state(page, 'visible_paths__' + vid);
  const own = (await win.locator(M.dockTab).first().innerText()).trim();
  const was = await win.boundingBox();
  const room = await win.locator('xpath=..').boundingBox();
  const near = (a, b) => !!a && Math.abs(a.x - b.x) <= 2 && Math.abs(a.y - b.y) <= 2
    && Math.abs(a.width - b.width) <= 2 && Math.abs(a.height - b.height) <= 2;
  await win.locator(M.dockTab).first().dblclick();
  await expect.poll(async () => near(await win.boundingBox(), room), { message: 'by its title, it fills the dock', timeout: 30000 }).toBe(true);
  await expect.poll(() => titles(win), { message: 'the other views are its tabs', timeout: 30000 }).toEqual(all);
  // the render grows with it, wider than the whole window was (cards in panels
  // stand beside the render, floating cards over it)
  const canvas = page.locator('.dv-render-overlay:visible canvas:visible').first();
  await expect.poll(async () => (await canvas.boundingBox()).width, { message: 'its content follows', timeout: 15000 })
    .toBeGreaterThan(was.width);
  expect(await state(page, 'visible_paths__' + vid), 'what it shows stays').toEqual(eyes);
  await expect.poll(() => state(page, 'fespp_active_panel_id'), { message: 'it stays the view in use' }).toBe(vid);
  // the button of the top bar reaches a view behind a tab, it does not close it
  await page.locator(M.topBarButton + '[title^="Statistics"]').click();
  // the view whole, its tree card with it: a scenario before may have left that card wide
  const compare = page.locator(M.dockPart).filter({ has: page.locator(M.compare) }).first();
  await expect.poll(async () => ((await compare.boundingBox()) || { width: 0 }).width, { message: 'at the same size', timeout: 30000 })
    .toBeGreaterThan(room.width * 0.7);
  expect(await state(page, 'ui_open_view_kinds'), 'still open').toContain('compare');
  await win.locator(M.dockTab, { hasText: own }).click();
  await expect.poll(async () => (await canvas.boundingBox()).width, { message: 'back by its tab', timeout: 15000 })
    .toBeGreaterThan(was.width);
  const grip = await win.locator('.dv-void-container').boundingBox();
  const free = await page.evaluate(({ x, y, width }) => {
    for (let at = x + width - 5; at > x; at -= 10) {
      if (document.elementFromPoint(at, y)?.closest('.dv-void-container')) return at;
    }
    return null;
  }, { x: grip.x, y: grip.y + grip.height / 2, width: grip.width });
  expect(free, 'part of the row is free').not.toBeNull();
  await page.mouse.dblclick(free, grip.y + grip.height / 2);
  await expect.poll(async () => near(await win.boundingBox(), was), { message: 'by the free part of its row, back where it was', timeout: 30000 }).toBe(true);
  await expect.poll(() => state(page, 'ui_floating_views'), { message: 'it alone floats', timeout: 30000 }).toEqual([vid]);
  expect(await titles(win), 'its tab alone').toEqual([own]);
  expect(await titles(page), 'the others back in the dock').toEqual(all);
  await anchorButton(page).click();
  await expect.poll(() => state(page, 'ui_floating_views'), { message: 'anchored', timeout: 30000 }).toEqual([]);
  expect(await titles(page), 'nothing lost').toEqual(all);
});

test('while a window fills the dock, a view opened joins it, one closed stays closed, its button anchors it', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await openCompare(page);
  await focusRenderView(page);
  const titles = async (scope) => (await scope.locator(M.dockTab).allInnerTexts()).map((x) => x.trim()).sort();
  const order = async () => (await page.locator(M.dockTab).allInnerTexts()).map((x) => x.trim());
  const tabs = await order();
  await (await viewButton(page, page.locator(M.dockPart + ':visible').filter({ has: page.locator('canvas') }).first(), 'float')).click();
  const win = page.locator(M.dockWindow);
  await expect(win, 'in a floating window').toHaveCount(1, { timeout: 30000 });
  await expect.poll(async () => ((await state(page, 'ui_floating_views')) || []).length, { message: 'reported', timeout: 30000 }).toBe(1);
  const [vid] = await state(page, 'ui_floating_views');
  const own = (await win.locator(M.dockTab).first().innerText()).trim();
  await win.locator(M.dockTab).first().dblclick();
  await expect.poll(async () => (await titles(win)).length, { message: 'the others joined', timeout: 30000 }).toBeGreaterThan(1);
  await page.locator(M.topBarButton + '[title^="Explorer"]').click();
  await expect.poll(() => titles(win), { message: 'a view opened joins it', timeout: 30000 }).toContain('Explorer');
  await closeView(page, 'Statistics', 'compare');
  await expect.poll(() => titles(win), { message: 'closed by its button', timeout: 30000 }).not.toContain('Statistics');
  await win.locator(M.dockTab, { hasText: own }).click();
  await expect.poll(() => state(page, 'fespp_active_panel_id'), { timeout: 15000 }).toBe(vid);
  await anchorButton(page).click();
  await expect.poll(() => state(page, 'ui_floating_views'), { message: 'anchored', timeout: 30000 }).toEqual([]);
  await expect(win, 'no window left').toHaveCount(0, { timeout: 30000 });
  await expect.poll(() => titles(page), { message: 'what was opened stays, what was closed stays closed', timeout: 30000 })
    .toEqual(expect.arrayContaining(['Explorer']));
  expect(await titles(page)).not.toContain('Statistics');
  await closeView(page, 'Explorer', 'xml');
  await expect.poll(() => titles(page), { message: 'left as it was', timeout: 30000 }).not.toContain('Explorer');
  expect(await order(), 'each tab at its place, the one closed gone').toEqual(tabs.filter((t) => t !== 'Statistics' && t !== 'Explorer'));
});

test('the eyes of Statistics and of the 3D view in use are in sync', async ({ app }) => {
  const { page } = app;
  const name = DATASET.properties[0];
  const path = await ensureProperty(app, name);
  await focusRenderView(page);
  const vid = await viewId(page);
  const shown3d = async () => ((await state(page, 'visible_paths__' + vid)) || []).includes(path);
  const held = async () => ((await state(page, 'ui_compare_items')) || []).some((it) => it.path === path);
  const panel = await openCompare(page);
  const tree = panel.locator(M.tree).first();
  await expandTree(tree);
  const eye = treeRow(tree, name).locator(M.treeEye);
  // from Statistics — taken in first: the view may hold another kind, the 3D view still showing this one
  if (!(await held())) {
    await eye.click();
    await expect.poll(held, { timeout: 30000 }).toBe(true);
  }
  await eye.click();
  await expect.poll(held, { timeout: 30000 }).toBe(false);
  await expect.poll(shown3d, { message: 'closed here, closed there', timeout: 30000 }).toBe(false);
  await eye.click();
  await expect.poll(held, { timeout: 30000 }).toBe(true);
  await expect.poll(shown3d, { message: 'opened here, opened there', timeout: 30000 }).toBe(true);
  // from the 3D view's tree
  await focusRenderView(page);
  const tree3d = dataTree(page);
  await expandTree(tree3d);
  await treeRow(tree3d, name).locator(M.treeEye).click();
  await expect.poll(held, { message: 'closed there, closed here', timeout: 30000 }).toBe(false);
  await treeRow(tree3d, name).locator(M.treeEye).click();
  await expect.poll(held, { message: 'opened there, opened here', timeout: 30000 }).toBe(true);
});

test('a burst of clicks on Open opens one view, the question gone at the first', async ({ app }) => {
  const { page } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const views = async () => ((await state(page, 'fespp_render_panels')) || []).length;
  const before = await views();
  await page.locator(M.viewsDoor).click();
  await page.locator(M.viewsDoorAdd).click();
  const dialog = page.locator(M.newViewDialog);
  await expect(dialog, 'the question').toBeVisible({ timeout: 15000 });
  await dialog.locator('.fp-segbtn', { hasText: 'Empty view' }).click();
  const box = await dialog.locator('button', { hasText: /^Open$/ }).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.up();
  await expect(dialog, 'gone at the first click').toHaveCount(0, { timeout: 200 });
  for (let i = 0; i < 3; i++) await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect.poll(views, { message: 'one more view', timeout: 30000 }).toBe(before + 1);
  await page.waitForTimeout(3000);
  expect(await views(), 'and only one').toBe(before + 1);
});
