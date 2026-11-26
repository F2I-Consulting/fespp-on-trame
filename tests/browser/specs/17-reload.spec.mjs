/*
 * Scenario (q): a tool card is remembered where it was left, and the reload
 * button says what it costs before it does it.
 *
 * Behind the launcher a page reload is a NEW session: the loaded files, the
 * views, the comparisons go with the old one, so the button asks before it
 * reloads. The cards, for their part, report where they end up (moved,
 * resized, docked) and the server keeps it per view and per tool: what a
 * single-session server restores on its reload, and what a saved session
 * carries.
 */
import {
  test, expect, M, DATASET,
  dataTree, ensureProperty, focusRenderView, state, treeRow, viewId,
} from '../lib/app.mjs';

test('a dragged tool card is remembered where it was left', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);

  // the Colormap card reads the active node — the property, clicked in the tree
  if ((((await state(page, 'view_tools_' + vid)) || []).find((t) => t.key === 'colormap') || {}).disabled) {
    await treeRow(dataTree(page), DATASET.properties[0]).locator(M.treeTitle).first().click();
  }
  await expect.poll(async () => !(((await state(page, 'view_tools_' + vid)) || [])
    .find((t) => t.key === 'colormap') || { disabled: true }).disabled,
  { message: 'the Colormap card is offered on the active property', timeout: 20000 }).toBe(true);
  const tools = (await state(page, 'view_tools_' + vid)) || [];
  const index = tools.findIndex((t) => t.key === 'colormap');
  expect(index, 'the view offers the Colormap card').toBeGreaterThanOrEqual(0);
  if (!(((await state(page, 'ui_open_tools_by_view')) || {})[vid] || []).includes('colormap')) {
    await page.locator(M.toolButton).nth(index).click();
  }
  const card = page.locator(M.card).filter({ has: page.locator(M.cardTitle, { hasText: /^Colormap( · |$)/ }) }).first();
  await card.waitFor({ timeout: 20000 });
  if (await card.evaluate((e, sel) => e.matches(sel), M.cardInPanel)) {
    // a card in a panel of the view's own dock is not dragged by its header:
    // the dock places it, and the server keeps the dock's layout, what a
    // reload and a saved session put back
    const kept = async () => {
      const layout = (await state(page, 'ui_card_layout__' + vid)) || {};
      return Object.keys(layout.panels || {}).includes('colormap')
        && JSON.stringify((layout.grid || {}).root || {}).includes('"colormap"');
    };
    await expect.poll(kept, { message: 'the server keeps the place of the Colormap panel', timeout: 15000 })
      .toBe(true);
    note('remembered: the Colormap panel in the layout of the view\'s cards');
    return;
  }
  // grab the header on its right part: the cards open staggered and the
  // Data Explorer card, wider, covers the left of this one; the dock and
  // close buttons sit at the far right, so stay 100 px short of the edge
  const head = card.locator('.fc-head');
  const hb = await head.boundingBox();
  const gx = hb.x + hb.width - 100;
  const gy = hb.y + hb.height / 2;
  expect(await page.evaluate(([x, y]) => { const e = document.elementFromPoint(x, y); return !!(e && e.closest('.fc-head')); }, [gx, gy]),
    'the grab point is on the card header').toBe(true);
  const boxBefore = await card.boundingBox();
  await page.mouse.move(gx, gy);
  await page.mouse.down();
  await page.mouse.move(gx + 140, gy + 90, { steps: 8 });
  await page.mouse.up();
  const boxAfter = await card.boundingBox();
  note('card moved from ' + Math.round(boxBefore.x) + ',' + Math.round(boxBefore.y)
    + ' to ' + Math.round(boxAfter.x) + ',' + Math.round(boxAfter.y));
  expect(boxAfter.x - boxBefore.x, 'the card followed the pointer').toBeGreaterThan(100);

  await expect.poll(async () => ((((await state(page, 'ui_card_geometry__' + vid)) || {}).colormap) || {}).x,
    { message: 'the server remembers where the card was left', timeout: 15000 }).toBeGreaterThan(0);
  const remembered = ((await state(page, 'ui_card_geometry__' + vid)) || {}).colormap;
  note('remembered: ' + JSON.stringify(remembered));
  // what is remembered is the card's own position in its view, the same
  // numbers its style carries
  const style = await card.evaluate((e) => ({ left: parseFloat(e.style.left), top: parseFloat(e.style.top) }));
  expect(remembered.x, 'the remembered x is the card\'s left').toBeCloseTo(style.left, 0);
  expect(remembered.y, 'the remembered y is the card\'s top').toBeCloseTo(style.top, 0);
  expect(remembered.dock, 'floating').toBe('float');
});

test('the reload button asks before starting a new session', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  let asked = '';
  page.once('dialog', async (d) => { asked = d.message(); await d.dismiss(); });
  await page.locator(M.topBarButton + '[title^="Reload the page"]').click();
  await expect.poll(() => asked, { message: 'the button asks first' }).toMatch(/new session/);
  note('asked: "' + asked + '"');
  // dismissed: the session is still here, with its data
  await page.waitForTimeout(1000);
  expect(await state(page, 'ui_has_data'), 'the session was kept').toBe(true);
});
