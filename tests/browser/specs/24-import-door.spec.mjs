/*
 * The import door shows everything it can do, and what it already did.
 *
 * Both sources (this computer's files, OSDU / ETP) are on screen at once: a
 * door labelled "Import data" with the second source behind a tab reads as
 * "files only", and gives no reason to press the tab.
 *
 * The door also lists the files the session already read, although it is
 * rebuilt on every open. That matters more than it looks: the reader never
 * re-reads a path it was given once, so a name already in is a name a
 * second drop will not load.
 */
import { test, expect, M, state, ensureData, openImportDoor } from '../lib/app.mjs';

test('the import door shows both sources, and the files already read', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  const loaded = (await state(page, 'ui_loaded_files')) || [];
  expect(loaded.length, 'the session kept a record of what it read')
    .toBeGreaterThan(0);

  // reopened AFTER the load, so the door has files to list
  await openImportDoor(page);
  const sources = page.locator('.up-src');
  await expect(sources, 'both import sources are on screen at once').toHaveCount(2);
  const headings = (await page.locator('.up-src-h').allInnerTexts())
    .map((t) => t.trim());
  note('sources: ' + headings.join(' | '));
  expect(headings.some((h) => /computer/i.test(h)), 'one names this computer').toBe(true);
  expect(headings.some((h) => /osdu|etp/i.test(h)), 'the other names OSDU').toBe(true);

  const prior = page.locator('.uf-prior .uf-prior-line');
  await expect(prior, 'the door lists what was read before it was opened')
    .toHaveCount(loaded.length);
  const names = (await page.locator('.uf-prior .uf-name').allInnerTexts())
    .map((t) => t.trim());
  note('already read: ' + names.join(', '));
  for (const f of loaded) {
    expect(names, 'the door names ' + f.name).toContain(f.name);
  }

  await page.locator('.fp-dialog-head button[title="Close"]').click();
  await expect(page.locator('.up-sources'), 'the door closes').toHaveCount(0);
});
