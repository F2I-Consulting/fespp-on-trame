/*
 * Scenario (d): every panel reachable from the top bar.
 *
 * The list is read off the bar itself, so a panel added to the application is
 * swept from the next run on, with nothing to declare here. Each one must come
 * to the front and show something: text, or a 3D canvas for a view that has no
 * text to show.
 */
import {
  test, expect, M, DATASET, clickTopBar, ensureProperty, visiblePanels,
} from '../lib/app.mjs';

test('every panel of the top bar opens with content', async ({ app }) => {
  const { page, note } = app;
  // Panels read what is loaded (statistics, health, cross-plots): sweeping them
  // on an empty session would only prove they can say "nothing to show".
  await ensureProperty(app, DATASET.properties[0]);

  const buttons = await page.locator(M.topBarButton + '[title]').evaluateAll(
    // a door greyed says why in its title: its panel has nothing to show here
    (els) => els.filter((e) => !e.disabled).map((e) => e.getAttribute('title'))
      .filter((t) => t && !/^(reload|import|session|about)/i.test(t)));
  expect(buttons.length, 'the top bar offers panels').toBeGreaterThan(3);

  const empty = [];
  for (const title of buttons) {
    const name = title.split('—')[0].trim();
    // some buttons ASK before they open anything: the helper answers
    await clickTopBar(page, title);
    // The panel is up when the front tab has a body with a height; a dockview
    // panel kept behind is zero high and cannot be judged.
    await expect.poll(async () => (await visiblePanels(page))
      .some((p) => p.height > 0), { message: 'panel ' + name + ' comes to the front' })
      .toBe(true);
    await page.waitForTimeout(1500);

    const shown = (await visiblePanels(page)).filter((p) => p.height > 0);
    const content = shown.some((p) => p.text !== '' || p.canvases > 0);
    const best = shown[0] || { height: 0, text: '', canvases: 0 };
    note(name + ' — ' + best.height + ' px, ' + best.canvases + ' canvas, "'
      + best.text.slice(0, 48) + '"');
    if (!content) empty.push(name);
  }

  const tabs = await page.locator(M.dockTab).allInnerTexts();
  note('panels open: ' + tabs.map((t) => t.trim()).join(', '));
  expect(empty, 'panels that opened empty').toEqual([]);
});
