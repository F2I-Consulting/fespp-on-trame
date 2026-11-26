/*
 * Scenario (w): the 3D view's title bar carries ITS camera.
 *
 * The camera buttons are PER VIEW. A single global `interaction_mode` that
 * drives whichever view is active makes one view's 3D/2D button show and
 * write another's as soon as two views are open. So the reading that matters
 * here is not that the buttons exist but that there is one strip per render
 * view, and pressing the mode chip of one leaves the others where they were.
 *
 * The second test reads the other half of "a widget you open comes to the
 * front": a card is hidden, never destroyed, so reopening one must raise it
 * above everything opened since, not bring it back at the depth it was left
 * at.
 */
import {
  test, expect, M, DATASET,
  ensureProperty, focusRenderView,
} from '../lib/app.mjs';

/* Every view's interaction mode, by view id. */
function modes(page) {
  return page.evaluate(() => {
    const s = window.trame.state;
    const all = s.state || s;
    const out = {};
    Object.keys(all).filter((k) => /^ui_interaction_mode__/.test(k))
      .forEach((k) => { out[k.replace('ui_interaction_mode__', '')] = all[k]; });
    return out;
  });
}

test('each 3D view has its own camera strip, and its own interaction mode', async ({ app }) => {
  const { page, note } = app;
  // something shown: on an empty view the framings and the zoom are
  // greyed (28/10), and this scenario zooms
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);

  const strips = page.locator(M.titleStrip + ':visible');
  const count = await strips.count();
  note('camera strips on screen: ' + count);
  expect(count, 'a camera strip above every 3D view').toBeGreaterThan(0);

  const strip = strips.first();
  // the gestures it must carry: the hand and the mouse (what the mouse does
  // in this view: move the scene, or read under the pointer with the scene
  // held still — 31-pointer-modes), the mode chip, the shading toggle
  // (exact colours), the framing, the Navigation card's door
  // and the domain's chip, when the session holds a model or a file in the other one
  await expect(strip.locator(M.titleStripBtn),
    'hand + mouse + mode + shading + fit + navigation')
    .toHaveCount(6 + await strip.locator('[data-t3-domain]').count());
  await expect(strip.locator('[data-t3-hand]'), 'the hand').toHaveCount(1);
  await expect(strip.locator('[data-t3-mouse]'), 'the mouse').toHaveCount(1);
  await expect(strip.locator('[title="Frame everything in this view"]'), 'the framing').toHaveCount(1);
  await expect(strip.locator('[title^="Navigation"]'), 'the Navigation card\'s door').toHaveCount(1);
  await expect(page.locator(M.toolButton + '[title^="Navigation"]:visible'), 'not in the toolbar too')
    .toHaveCount(0);

  // "Represent by" rides up here too. Its prop must not be called `style`:
  // that is a reserved DOM attribute, Vue takes the value for CSS, the whole
  // element's attribute serialisation fails with it and the select silently
  // does not render. Only the screen shows that, so it is read on screen.
  const sel = strip.locator('select');
  await expect(sel, 'the strip carries the Represent by select').toHaveCount(1);
  note('represent by: ' + (await sel.inputValue())
    + ' among ' + (await sel.locator('option').count()) + ' styles');
  await expect(sel.locator('option'), 'every style on offer').toHaveCount(5);

  const before = await modes(page);
  note('interaction modes: ' + JSON.stringify(before));
  const chip = strip.locator(M.titleStripMode);
  await expect(chip, 'the mode reads as the mode it is IN').toHaveText('3D');

  await chip.click();
  await expect(chip, 'the chip says 2D once pressed').toHaveText('2D', { timeout: 15000 });
  const after = await modes(page);
  note('after the click: ' + JSON.stringify(after));
  const changed = Object.keys(after).filter((v) => after[v] !== before[v]);
  expect(changed.length, 'exactly ONE view changed mode').toBe(1);
  if (Object.keys(after).length > 1) {
    note('the other views kept their mode: '
      + Object.keys(after).filter((v) => !changed.includes(v)).join(', '));
  }

  // back to 3D: the scenarios share one session, and a view left with its
  // rotation locked is a trap for the next one
  await chip.click();
  await expect(chip, 'and back to 3D').toHaveText('3D', { timeout: 15000 });

  // the shading toggle: exact colours (no shading) in THIS view only, and back
  const flat = async () => page.evaluate(() => {
    const s = window.trame.state; const all = s.state || s;
    return Object.fromEntries(Object.keys(all).filter((k) => /^ui_flat_colors__/.test(k))
      .map((k) => [k.replace('ui_flat_colors__', ''), !!all[k]]));
  });
  const shade = strip.locator('[title^="Shading on"]');
  await expect(shade, 'the strip carries the shading toggle').toHaveCount(1);
  await shade.click();
  await expect.poll(async () => Object.values(await flat()).filter(Boolean).length,
    { message: 'exact colours in exactly one view', timeout: 15000 }).toBe(1);
  await strip.locator('[title^="Exact colors"]').click();
  await expect.poll(async () => Object.values(await flat()).filter(Boolean).length,
    { message: 'and shaded again', timeout: 15000 }).toBe(0);
  // the Navigation card opens from the strip, and closes from it
  const nav = strip.locator('[title^="Navigation"]');
  await nav.click();
  await expect(page.locator(M.card + ':visible').filter({ has: page.locator(M.cardTitle, { hasText: /^Navigation/ }) }),
    'its card').toHaveCount(1, { timeout: 15000 });
  await expect(nav, 'the door says it is open').toHaveAttribute('aria-pressed', 'true');
  await nav.click();
  await expect(page.locator(M.card + ':visible').filter({ has: page.locator(M.cardTitle, { hasText: /^Navigation/ }) }),
    'closed again').toHaveCount(0, { timeout: 15000 });
  await expect(strip, 'the strip survives its own gestures').toBeVisible();
});

test('a card behind a tab comes in front by its button, closes by it in front, comes back in front', async ({ app }) => {
  const { page, note } = app;
  // something read: the cards are greyed on a session that has read nothing
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);

  const bar = page.locator(M.toolbar + ':visible').first();
  const btn = (title) => bar.locator('.tb-btn[title=' + JSON.stringify(title) + ']');
  // two cards that are always offered, whatever the file holds; the first says
  // Color on a geometry
  const first = (await btn('Colormap').count()) ? 'Colormap' : 'Color';
  // a grid is read: its Geometry slicer is offered
  const second = 'Geometry slicer';
  const part = page.locator(M.dockPart + ':visible').filter({ has: bar }).first();
  // the tabs of the view's cards, hidden ones included
  const tabs = async () => (await part.locator(M.cardDock + ' .dv-tab').allInnerTexts()).map((x) => x.trim());
  const has = async (title) => (await tabs()).some((x) => x.startsWith(title));
  const shown = (title) => part.locator(M.card + ':visible')
    .filter({ has: page.locator(M.cardTitle, { hasText: new RegExp('^' + title) }) });
  for (const title of [first, second]) {
    if (!(await has(title))) await btn(title).click();
    await expect.poll(() => has(title), { message: title + ' open', timeout: 30000 }).toBe(true);
  }
  note('tabs: ' + JSON.stringify(await tabs()));
  // the second in front: the first, open behind its tab, comes in front by
  // its button and stays open
  if (!(await shown(second).count())) await btn(second).click();
  await expect(shown(second), second + ' in front').toHaveCount(1, { timeout: 15000 });
  if (!(await shown(first).count())) {
    await btn(first).click();
    await expect(shown(first), 'its button brings ' + first + ' in front').toHaveCount(1, { timeout: 15000 });
    expect(await has(first), 'still open').toBe(true);
  }
  // in front, its button closes it; opened again, it comes back in front
  await btn(first).click();
  await expect.poll(() => has(first), { message: 'the first card closed', timeout: 15000 }).toBe(false);
  await btn(first).click();
  await expect(shown(first), 'the reopened card is on screen, its panel in front').toHaveCount(1, { timeout: 15000 });
});
