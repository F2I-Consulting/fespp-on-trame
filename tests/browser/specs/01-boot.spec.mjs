/* Scenario (a): the application comes up on an empty session. */
import { test, expect, M, state, visiblePanels } from '../lib/app.mjs';

test('the shell mounts and the session is empty', async ({ app }) => {
  const { page, note } = app;

  // Vue is mounted, not a page stuck on "Loading…".
  const mounted = await page.evaluate(() => {
    const el = document.getElementById('app');
    return !!(el && el.__vue_app__);
  });
  expect(mounted, 'Vue mounted on #app').toBe(true);
  note('Vue mounted');

  const tabs = await page.locator(M.dockTab).allInnerTexts();
  expect(tabs.length, 'at least one dockview panel').toBeGreaterThan(0);
  note('dockview tabs: ' + tabs.map((t) => t.trim()).join(', '));

  // The top bar: the Import data button plus the panel buttons, each one a
  // component that had to resolve and render.
  const importDoor = page.locator(M.topBarButton, { hasText: /import data/i });
  await expect(importDoor, 'the Import data button').toHaveCount(1);
  const titles = await page.locator(M.topBarButton + '[title]').evaluateAll(
    (els) => els.map((e) => e.getAttribute('title')));
  expect(titles.length, 'panel buttons in the top bar').toBeGreaterThan(3);
  note('top bar: ' + titles.map((t) => t.split('—')[0].trim()).join(', '));

  // The 3D view is there and painting: a canvas, and a panel with a size. A
  // view whose template failed to compile is a panel with nothing in it.
  await expect.poll(async () => (await visiblePanels(page)).length,
    { message: 'no panel is visible under the tabs' }).toBeGreaterThan(0);
  await expect.poll(async () => (await visiblePanels(page)).some((p) => p.canvases > 0),
    { message: 'the 3D view panel is blank: it holds no canvas', timeout: 20000 })
    .toBe(true);
  const panels = await visiblePanels(page);
  note('visible panel: ' + panels[0].height + ' px, '
    + panels[0].canvases + ' canvas');

  // The data tree rendered: a component that threw while rendering leaves no
  // root element behind, and that is a blank tree card.
  await expect(page.locator(M.tree).first(),
    'the data tree rendered nothing (no tree component in the view)')
    .toHaveCount(1, { timeout: 10000 });

  // An empty start (the launcher opens no file): the tree says so rather than
  // showing nothing at all.
  if (!(await state(page, 'ui_has_data'))) {
    // An empty session opens the import dialog by itself (UploadData.mounted):
    // with nothing loaded every panel button is disabled, so importing is the
    // only thing to do. It opens on mount only and only while empty, so it
    // never comes back on its own once closed.
    await expect(page.locator('.up-sources'),
      'an empty session opens the import door by itself')
      .toBeVisible({ timeout: 15000 });
    note('the import door opened on the empty session');
    await page.locator('.fp-dialog-head button[title="Close"]').click();
    await expect(page.locator('.up-sources'), 'and it closes').toHaveCount(0);

    const tree = await page.locator(M.tree).first().innerText();
    expect(tree.trim(), 'the empty tree states its emptiness').not.toBe('');
    expect(tree).toMatch(/no data/i);
    note('empty session: "' + tree.replace(/\s+/g, ' ').trim().slice(-16) + '"');
    // The panel buttons of the top bar are disabled, each saying why: a
    // button that would open an empty panel is not offered. Reload, Import,
    // Session and the 3D views door (it goes from view to view, opens an
    // empty one) are not panels of the data and stay enabled.
    const gated = await page.locator(M.topBarButton + '[title]').evaluateAll(
      (els) => els.filter((e) => !/^(reload|import|session|about|3D views)/i.test(e.getAttribute('title')))
        .map((e) => ({ title: e.getAttribute('title'), disabled: e.disabled || e.hasAttribute('disabled') })));
    note('gated: ' + gated.filter((g) => g.disabled).length + ' of ' + gated.length);
    expect(gated.every((g) => g.disabled), 'every panel button is disabled without data').toBe(true);
    expect(gated.every((g) => /import a file first$/.test(g.title)), 'each one says why').toBe(true);
  }
});
