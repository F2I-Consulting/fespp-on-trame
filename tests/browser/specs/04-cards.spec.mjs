/*
 * Scenario (e): the tool cards of a 3D view's toolbar.
 *
 * The list of tools is not hard-coded here: the view publishes it (state
 * `view_tools_<id>`), which is also how the harness stays right when a tool is
 * added, removed, or dropped because the data does not allow it. The buttons
 * render that same list in order, so the nth button is the nth tool.
 *
 * A card that opens must SHOW something: a body with a height and some text.
 */
import {
  test, expect, M, DATASET,
  ensureProperty, focusRenderView, openCards, state, viewId,
} from '../lib/app.mjs';
import { MODE_KEYS } from '../lib/markers.mjs';

test('every tool card of the view opens with content', async ({ app }) => {
  const { page, note } = app;
  // A card such as Volumetrics is only offered once the view has something
  // with a volume in it, so the pass loads a property first.
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);

  const vid = await viewId(page);
  const tools = (await state(page, 'view_tools_' + vid)) || [];
  const cards = tools.filter((t) => !MODE_KEYS.includes(t.key));
  expect(cards.length, 'the view offers tools').toBeGreaterThan(3);
  note('tools offered: ' + tools.map((t) => t.key).join(', '));

  const openAtStart = (await state(page, 'ui_open_tools_by_view'))[vid] || [];
  const empty = [];

  for (const [index, tool] of tools.entries()) {
    if (MODE_KEYS.includes(tool.key)) continue;
    // greyed: its precondition fails and its title says why (27/10)
    if (tool.disabled) {
      note(tool.key + ' — greyed: ' + tool.title);
      continue;
    }
    const button = page.locator(M.toolButton).nth(index);
    const alreadyOpen = ((await state(page, 'ui_open_tools_by_view'))[vid] || [])
      .includes(tool.key);
    if (!alreadyOpen) await button.click();

    // The application acknowledges the open card...
    await expect.poll(async () => ((await state(page, 'ui_open_tools_by_view'))[vid] || [])
      .includes(tool.key), { message: 'card ' + tool.key + ' opens' }).toBe(true);

    // ...and the card itself carries content.
    const card = page.locator(M.card)
      .filter({ has: page.locator(M.cardTitle, { hasText: tool.title }) }).first();
    await card.locator(M.cardBody).first().waitFor({ timeout: 20000 });
    const shown = (await openCards(page)).find((c) => c.title === tool.title);
    note(tool.key + ' — ' + (shown ? shown.height + ' px, '
      + shown.controls + ' control(s), "' + shown.text.slice(0, 44) + '"'
      : 'NOT VISIBLE'));
    if (!shown || shown.height === 0 || (shown.text === '' && shown.controls === 0)) {
      empty.push(tool.key);
    }
    if (!openAtStart.includes(tool.key)) await button.click();
  }

  expect(empty, 'tool cards that opened empty').toEqual([]);
});
