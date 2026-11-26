/*
 * Scenario (assistant): the application asked in plain words.
 *
 * The Assistant panel (widgets/assistant, app/assistant_host) takes one
 * sentence at a time, French or English, runs the ONE command it reads in
 * it and says what it did; an action can be undone from the reply.
 *
 * In the browser, on the default file (one grid `unknown`, properties
 * `poro`, `velocity`, `stress`): the top-bar door, the empty state and its
 * examples, a property shown and hidden by name, the hide undone, a mean
 * read into a table, the cells over a value highlighted and the highlight
 * taken off, a sentence that means nothing, and Clear.
 */
import path from 'node:path';
import {
  ownSession, holdVerdicts,
  test, expect, M, DATASET, ensureProperty, focusRenderView, state,
} from '../lib/app.mjs';

const conversation = async (page) => (await state(page, 'ui_assistant')) || {};
const messages = async (page) => (await conversation(page)).messages || [];

/* The 3D view the assistant acts on, resolved as its adapter resolves it
 * (engine/view_routing.resolve_active_render_panel): the active panel when
 * it is a 3D view — the Assistant's own tab is not — else the 3D view last
 * worked in, else the first one. */
async function targetView(page) {
  const ids = ((await state(page, 'fespp_render_panels')) || []).map((p) => p.id);
  const active = (await state(page, 'fespp_active_panel_id')) || '';
  if (ids.includes(active)) return active;
  const last = (await state(page, 'fespp_last_render_panel_id')) || '';
  return ids.includes(last) ? last : ids[0];
}

const shown = async (page, vid) => (await state(page, 'visible_paths__' + vid)) || [];

/* Say `sentence` (typed, then Send or Enter) and wait for the reply: the
 * conversation's last message, an assistant one newer than what was there. */
async function ask(app, panel, sentence, { enter = false } = {}) {
  const { page, note } = app;
  const before = await messages(page);
  const lastId = before.length ? before[before.length - 1].id : null;
  const input = panel.locator('[data-fp-assistant-input]');
  await input.fill(sentence);
  if (enter) await input.press('Enter');
  else await panel.locator('[data-fp-assistant-send]').click();
  let reply = null;
  await expect.poll(async () => {
    const c = await conversation(page);
    const all = c.messages || [];
    const last = all[all.length - 1];
    reply = last && !c.busy && last.role === 'assistant' && last.id !== lastId ? last : null;
    return Boolean(reply);
  }, { message: 'the assistant answers « ' + sentence + ' »', timeout: 60000 }).toBe(true);
  await expect(input, 'the input is emptied once the sentence is sent').toHaveValue('');
  note('« ' + sentence + ' » → [' + reply.level + '] ' + reply.text.replace(/\s+/g, ' ').slice(0, 120));
  return reply;
}

/* The last reply as the panel draws it. */
const lastReply = (panel) => panel.locator('[data-fp-assistant-msg][data-role="assistant"]').last();

test('the Assistant shows, hides, undoes, measures and highlights by name', async ({ app }) => {
  test.skip(path.basename(DATASET.files[0]) !== 'vector_props.epc',
    'the sentences name the properties of the default file (vector_props)');
  // what the scenarios before it left in their session would answer in its place
  const own = await ownSession(app, DATASET.files);
  const { page, note } = own;
  const poro = await ensureProperty(own, 'poro');
  await focusRenderView(page);

  // the door
  const door = page.locator(M.topBarButton + '[title^="Assistant"]');
  await expect(door, 'the top bar offers the Assistant').toHaveCount(1);
  await expect(door, 'with data loaded, its door is open').toBeEnabled();
  await door.click();
  const panel = page.locator('[data-fp-assistant]');
  await expect(panel, 'the Assistant panel opens').toBeVisible({ timeout: 30000 });
  await expect(page.locator(M.dockTab, { hasText: /^Assistant$/ }),
    'its tab wears the door\'s word, with no number').toHaveCount(1);
  const vid = await targetView(page);
  note('the assistant acts on ' + vid);

  // an empty conversation says what the panel does, with examples to click
  if ((await messages(page)).length) {
    await panel.locator('[data-fp-assistant-clear]').first().click();
    await expect.poll(async () => (await messages(page)).length,
      { message: 'the conversation left by an earlier pass is cleared' }).toBe(0);
  }
  await expect(panel.locator(M.empty), 'an empty conversation says what the panel does')
    .toBeVisible();
  const examples = await panel.locator('[data-fp-assistant-example]').allInnerTexts();
  note('examples: ' + examples.map((e) => e.trim()).join(' | '));
  expect(examples.length, 'the empty state offers examples').toBeGreaterThan(0);

  // a property shown by name — hidden first, or the eye would be open
  // before the command: ensureProperty ticks poro in this very view, where
  // a new read is born visible, and an earlier pass may have left it shown
  let r;
  if ((await shown(page, vid)).includes(poro)) {
    r = await ask(own, panel, 'cache poro');
    expect(r.level, 'poro is hidden before the show is asked').toBe('ok');
    await expect.poll(async () => (await shown(page, vid)).includes(poro),
      { message: 'poro is hidden before the show is asked', timeout: 30000 }).toBe(false);
  }
  expect((await shown(page, vid)).includes(poro), 'poro is not shown before « montre poro »')
    .toBe(false);
  r = await ask(own, panel, 'montre poro');
  expect(r.level, 'the show is done').toBe('ok');
  // an Olympus file read by an earlier scenario brings a grid `Sector`
  // with a `Porosity`: the title said exactly wins over one it begins
  expect(r.text, 'the show names poro, not a title that merely begins with it')
    .not.toMatch(/Porosity/);
  await expect(lastReply(panel), 'the reply is drawn as done').toHaveAttribute('data-level', 'ok');
  await expect.poll(async () => (await shown(page, vid)).includes(poro),
    { message: 'poro is shown in the 3D view', timeout: 60000 }).toBe(true);

  // hidden by name (Enter sends), then the hide undone from the reply
  r = await ask(own, panel, 'cache poro', { enter: true });
  expect(r.level, 'the hide is done').toBe('ok');
  expect(r.undoable, 'a hide can be undone').toBe(true);
  await expect.poll(async () => (await shown(page, vid)).includes(poro),
    { message: 'poro is no longer shown', timeout: 30000 }).toBe(false);
  const undo = panel.locator('[data-fp-assistant-undo]').last();
  await expect(undo, 'the reply offers its Undo').toBeVisible();
  const beforeUndo = (await messages(page)).length;
  await undo.click();
  await expect.poll(async () => {
    const all = await messages(page);
    const last = all[all.length - 1] || {};
    return all.length > beforeUndo && last.role === 'assistant' ? last.level : null;
  }, { message: 'the undo is answered', timeout: 30000 }).toBe('ok');
  await expect.poll(async () => (await shown(page, vid)).includes(poro),
    { message: 'the undo shows poro again', timeout: 30000 }).toBe(true);

  // a mean, read into the reply's table
  r = await ask(own, panel, 'quelle est la moyenne de poro ?');
  expect(r.level, 'the mean is read').toBe('ok');
  const labels = (r.rows || []).map((row) => String(row[0]));
  note('rows: ' + labels.join(', '));
  expect(labels.some((l) => /^(Mean|Moyenne)$/.test(l)), 'the table has a Mean row').toBe(true);
  await expect(lastReply(panel), 'the table is drawn in the reply').toContainText(/Mean|Moyenne/);

  // the cells over a value highlighted, every other cell kept; then taken off
  r = await ask(own, panel, 'surligne les mailles où poro dépasse 0,2');
  expect(r.level, 'the highlight is done').toBe('ok');
  await expect(lastReply(panel)).toHaveAttribute('data-level', 'ok');
  // ok says nothing of what was lit: a bound compared the wrong way, or a
  // mask that drops every cell, still replies ok, with a count of zero cells
  // the panel answers in English whatever the request's language (the PO,
  // 15/10); a host that keeps the sentence's language says "mailles sur"
  const lit = /^(\d[\d\s,]*) (?:mailles? sur|of) (\d[\d\s,]*) /.exec(r.text);
  expect(lit, 'the reply starts with the count of cells lit').not.toBeNull();
  const [n, total] = [lit[1], lit[2]].map((s) => Number(s.replace(/\D/g, '')));
  expect(n, 'some cells are lit (poro goes over 0,2 in 8 of the 24 cells)').toBeGreaterThan(0);
  expect(n, 'and not every one: the others are only kept in sight').toBeLessThan(total);
  r = await ask(own, panel, 'enlève la surbrillance');
  expect(r.level, 'the highlight is taken off').toBe('ok');

  // a sentence that means nothing is said so
  r = await ask(own, panel, 'xqzt');
  expect(r.level, 'nothing understood is an error, not a guess').toBe('error');
  await expect(lastReply(panel)).toHaveAttribute('data-level', 'error');

  // Clear empties the conversation, and the examples come back
  await panel.locator('[data-fp-assistant-clear]').first().click();
  await expect.poll(async () => (await messages(page)).length,
    { message: 'Clear empties the conversation' }).toBe(0);
  await expect(panel.locator('[data-fp-assistant-msg]'), 'no message is drawn').toHaveCount(0);
  await expect(panel.locator('[data-fp-assistant-example]').first(),
    'the examples are offered again').toBeVisible();

  // what this scenario opened, it closes
  const tab = page.locator(M.dockTab, { hasText: /^Assistant$/ });
  await tab.locator('.dv-default-tab-action').click();
  await expect(tab, 'the Assistant tab is closed').toHaveCount(0);
  await focusRenderView(page);
  await holdVerdicts(own);
});
