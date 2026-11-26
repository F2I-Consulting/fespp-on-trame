/*
 * Scenario: the top bar's door to the 3D views.
 *
 * A click opens a pop-over with one tile per 3D view and a "+ New 3D view"
 * tile. A click on a tile makes that view the active one; its eye alone
 * hides the view — it leaves the dock, its state kept — and shows it again;
 * the Globe is not listed.
 */
import path from 'node:path';
import { test, expect, state, waitUntil, ensureData, OUT_DIR } from '../lib/app.mjs';

const renderPanels = async (page) => ((await state(page, 'fespp_render_panels')) || []).filter((p) => !p.globe);

test('the 3D views door: a tile activates its view, its eye hides and shows it', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  const door = page.locator('header .fvd button').first();
  await expect(door, 'the top bar has the 3D views door').toHaveCount(1, { timeout: 30000 });

  // a second view, through the door's "+" tile
  await door.click();
  await expect(page.locator('.fvd-pop'), 'the pop-over opens').toBeVisible({ timeout: 10000 });
  const before = (await renderPanels(page)).length;
  await expect(page.locator('.fvd-tile:not(.fvd-add)'), 'one tile per 3D view').toHaveCount(before);
  await page.locator('.fvd-add').click();
  // the question of the new view: an empty one
  await expect(page.locator('.fnv'), 'the new view asks what it starts from').toBeVisible({ timeout: 15000 });
  await page.locator('.fnv button', { hasText: /^Empty view$/ }).click();
  await page.locator('.fnv button', { hasText: /^Open$/ }).click();
  await waitUntil(app, async () => (await renderPanels(page)).length === before + 1, { what: 'a new 3D view' });
  const views = await renderPanels(page);
  const last = views[views.length - 1];
  note('views: ' + views.map((v) => v.title).join(', '));

  // a click on the first view's tile: it becomes the active view, nothing hidden
  const first = views[0];
  await door.click();
  await page.locator('.fvd-tile', { hasText: first.title }).first().click();
  await expect.poll(() => state(page, 'fespp_active_panel_id'), { message: 'the tile made it active' }).toBe(first.id);
  await expect.poll(async () => (await renderPanels(page)).filter((v) => v.hidden).length,
    { message: 'a tile hides nothing' }).toBe(0);
  await expect(page.locator('.fvd-pop'), 'the pop-over closes on the way').toHaveCount(0);

  // hidden from its eye: out of the dock, still a view of the session
  await door.click();
  await page.locator('.fvd-tile', { hasText: last.title }).locator('.fvd-eye').click();
  await waitUntil(app, async () => ((await renderPanels(page)).find((v) => v.id === last.id) || {}).hidden === true,
    { what: last.title + ' hidden' });
  await expect(page.locator('.dv-tab', { hasText: last.title }), 'its tab left the dock').toHaveCount(0, { timeout: 15000 });
  await expect(page.locator('.fvd-tile.fvd-hidden', { hasText: last.title }), 'its tile says it is hidden').toHaveCount(1);
  await page.screenshot({ path: path.join(OUT_DIR, '42-views-door-popover.png') });

  // shown again from its eye
  await page.locator('.fvd-tile', { hasText: last.title }).locator('.fvd-eye').click();
  await waitUntil(app, async () => ((await renderPanels(page)).find((v) => v.id === last.id) || {}).hidden === false,
    { what: last.title + ' shown again' });
  await expect(page.locator('.dv-tab', { hasText: last.title }), 'its tab is back').toHaveCount(1, { timeout: 15000 });
  await expect.poll(() => state(page, 'fespp_active_panel_id'), { message: 'it is the active view' }).toBe(last.id);

  // an eye leaves the pop-over open; Escape closes it, its scrim with it
  await page.keyboard.press('Escape');
  await expect(page.locator('.fvd-pop'), 'Escape closes the pop-over').toHaveCount(0);
});
