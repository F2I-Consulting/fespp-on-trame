/*
 * A property whose values are codes (a facies, a zone) is painted one
 * colour per code, and the Colormap card lists the codes with a colour
 * picker and an opacity slider each instead of the ramp controls (an
 * indexed table ignores the opacity graph); a continuous property keeps
 * the ramp. Only a browser sees the card's two faces.
 *
 * The smoke file carries no discrete property, so the codes face runs on
 * a discrete property named by FESPP_SMOKE_DISCRETE (with
 * FESPP_SMOKE_EPC=drogon.epc FESPP_SMOKE_PROPS=Temperature,Facies (the
 * ramp face colours by the first one)
 * FESPP_SMOKE_DISCRETE=Facies it runs in full); the ramp face runs always.
 */
import path from 'node:path';
import { test, expect, DATASET, OUT_DIR, state, viewId, viewPart, ensureProperty, focusRenderView, openTool }
  from '../lib/app.mjs';

const DISCRETE = process.env.FESPP_SMOKE_DISCRETE || '';

/* The cards of ONE 3D view (its part holds them, wherever they sit): another
   view left open by an earlier scenario has its own Colormap card, which edits
   the table holding that view's colour bar (engine/legends). */
const viewCards = viewPart;

test('a continuous property keeps the ramp, and the card says nothing about codes', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  const close = await openTool(page, vid, 'colormap');
  const cards = viewCards(page, vid);
  const cmap = (await state(page, 'ui_colormap__' + vid)) || {};
  note('categorical: ' + cmap.categorical + ' note: ' + JSON.stringify(cmap.categories_note || ''));
  expect(cmap.categorical, 'the state says the property is not painted by code').toBe(false);
  expect(cmap.categories_note || '', 'no reason is given, there is nothing to explain').toBe('');
  await expect(cards.locator('.fcm-cats'), 'no code list on the card').toHaveCount(0);
  await expect(cards.locator('.fcm-tag-cat'), 'no codes tag in the header').toHaveCount(0);
  await expect(cards.locator('.fcm-range-labels'), 'the ramp has its range labels').toHaveCount(1);
  await close();
});

test('a discrete property is painted by code and the card lists the codes', async ({ app }) => {
  test.skip(!DISCRETE, 'no discrete property named (FESPP_SMOKE_DISCRETE) — the smoke file has none');
  const { page, note } = app;
  await ensureProperty(app, DISCRETE);
  await focusRenderView(page);
  const vid = await viewId(page);
  await expect.poll(async () => ((await state(page, 'ui_colormap__' + vid)) || {}).array,
    { message: 'the view colours by the discrete property', timeout: 30000 }).toBeTruthy();
  const close = await openTool(page, vid, 'colormap');
  const cards = viewCards(page, vid);
  const cmap = (await state(page, 'ui_colormap__' + vid)) || {};
  note('categorical: ' + cmap.categorical + ' codes: ' + (cmap.categories || []).length
    + ' preset: ' + cmap.preset + (cmap.categories_note ? ' — ' + cmap.categories_note : ''));
  expect(cmap.categorical, 'the state says the property is painted by code').toBe(true);
  const n = (cmap.categories || []).length;
  expect(n, 'the codes are listed').toBeGreaterThan(1);
  await expect(cards.locator('.fcm-tag-cat'), 'the header carries the codes tag').toHaveCount(1);
  await expect(cards.locator('.fcm-cat .fp-cswatch'), 'one swatch per code').toHaveCount(n);
  await expect(cards.locator('.fcm-range-labels'), 'no ramp range on a property painted by code').toHaveCount(0);
  const labels = await cards.locator('.fcm-cat-label').allInnerTexts();
  note('codes: ' + labels.join(' | '));
  // the card as a human would see it, for the review
  await cards.locator('.fcm').first().screenshot({ path: path.join(OUT_DIR, 'codes-card.png') });
  expect(labels.every((l) => l.trim().length > 0), 'every code has a name or its number').toBe(true);
  // the preset select offers the qualitative palettes
  const options = await cards.locator('.fcm select option').allInnerTexts();
  expect(options.some((o) => /Qualitative|KAAMS/.test(o)), 'the qualitative presets are offered').toBe(true);
  // one code's colour changes through the picker and the state follows
  await cards.locator('.fcm-cat .fp-cswatch-btn').first().click();
  const hex = page.locator('.fp-cswatch-pop .fp-cpick-hex');
  await hex.fill('#123456');
  await hex.press('Enter');
  await page.keyboard.press('Escape');
  await expect.poll(async () => (((await state(page, 'ui_colormap__' + vid)) || {}).categories || [])[0]?.color,
    { message: 'the server painted the first code with the picked colour', timeout: 30000 }).toBe('#123456');
  // and its opacity through its slider: 0 hides that code alone (an indexed
  // table reads one opacity per code, the graph is not offered)
  await expect(cards.locator('.fcm-cat .fcm-cat-op input'), 'one opacity slider per code').toHaveCount(n);
  const slider = cards.locator('.fcm-cat .fcm-cat-op input').first();
  await slider.evaluate((el) => { el.value = '0'; el.dispatchEvent(new Event('change', { bubbles: true })); });
  await expect.poll(async () => ((((await state(page, 'ui_colormap__' + vid)) || {}).categories || [])
    .map((c) => c.opacity)).join(','),
    { message: 'the first code alone is transparent', timeout: 30000 })
    .toBe(['0'].concat(Array(n - 1).fill('1')).join(','));
  await expect(cards.locator('.fcm-cat-hidden'), 'the hidden code is struck through').toHaveCount(1);
  await cards.locator('.fcm').first().screenshot({ path: path.join(OUT_DIR, 'codes-card-opacity.png') });
  await close();
});
