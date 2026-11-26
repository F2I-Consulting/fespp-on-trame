/*
 * The browser's Back while something is loaded: the page asks first, in a
 * Warning (widgets/session LeaveGuard). Stay keeps the page and the guard;
 * Leave is not pressed here, the session is shared by every spec.
 */
import { test, expect, state, ensureData } from '../lib/app.mjs';

test("the browser's Back asks before a loaded session is left", async ({ app }) => {
  const { page } = app;
  await ensureData(app);
  const box = page.locator('[data-fp-leave-guard] .fp-dialog');
  const back = () => page.goBack({ timeout: 5000 }).catch(() => null);
  await back();
  await expect(box, 'a Warning asks').toBeVisible({ timeout: 10000 });
  await expect(box.locator('.fp-title')).toHaveText('Warning');
  await box.locator('.fp-dialog-foot button', { hasText: 'Stay' }).click();
  await expect(box, 'Stay: the question goes').toHaveCount(0);
  expect(await state(page, 'ui_has_data'), 'still the same session').toBe(true);
  // the guard is set again: a second Back asks too, and Esc stays
  await back();
  await expect(box, 'asked again').toBeVisible({ timeout: 10000 });
  await page.keyboard.press('Escape');
  await expect(box, 'Esc stays').toHaveCount(0);
  expect(await state(page, 'ui_has_data')).toBe(true);
});
