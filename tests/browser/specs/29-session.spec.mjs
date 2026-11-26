/*
 * Scenario (session): the Session door saves the state of the application
 * to a .fespp.json file on the reader's computer, and opens one to restore
 * it (widgets/session, app/session_host).
 *
 * In the browser: the top-bar door, Save gives a real download whose JSON
 * names the loaded file and the views; the same file dropped back says every
 * expected file is loaded, and Restore puts back a view whose eyes were
 * closed in between.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  test, expect, M, DATASET, APP_URL,
  closeImportDoor, ensureProperty, ensureVelocityModel, focusRenderView, state, viewId,
} from '../lib/app.mjs';

const status = async (page) => (await state(page, 'ui_session_status')) || {};

test('the Session door saves a file and restores the views from it', async ({ app }) => {
  const { page, note } = app;
  // a scenario run just before may have left the Import data door open
  // (20-etp-wait does): its scrim would take the clicks on the view
  await closeImportDoor(page);
  const propPath = await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  await expect.poll(async () => ((await state(page, 'visible_paths__' + vid)) || []).length,
    { message: 'the property is shown', timeout: 30000 }).toBeGreaterThan(0);
  const eyes = (await state(page, 'visible_paths__' + vid)) || [];

  // the door, and Save: a real download
  await closeImportDoor(page);
  await page.locator('[data-fp-session-launch]').click();
  const dialog = page.locator('.fse');
  await expect(dialog, 'the Session dialog opens').toBeVisible({ timeout: 15000 });
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 30000 }),
    dialog.locator('[data-fp-session-save] button', { hasText: /^Save session$/ }).click(),
  ]);
  const file = await download.path();
  const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
  note('saved ' + download.suggestedFilename() + ': ' + doc.views.length + ' view(s), '
    + (doc.sources.files || []).map((f) => f.name).join(', '));
  expect(download.suggestedFilename(), 'a .fespp.json file').toMatch(/\.fespp\.json$/);
  expect(doc.schema, 'the format number').toBe(1);
  expect((doc.sources.files || []).length, 'the loaded files are named').toBeGreaterThan(0);
  expect(doc.views.find((v) => v.id === vid).eyes, 'the view\'s eyes are saved').toEqual(eyes);
  expect(Object.keys(doc.objects || {}), 'what is read is fingerprinted').toContain(propPath);

  // the view disturbed: every eye closed
  await page.evaluate((v) => {
    const s = window.trame.state;
    s.set('visible_paths__' + v, []);
  }, vid);
  await expect.poll(async () => ((await state(page, 'visible_paths__' + vid)) || []).length,
    { message: 'the eyes are closed', timeout: 15000 }).toBe(0);

  // the file back through the door, under its own name (Playwright keeps a
  // download under a nameless path, and the door refuses a file that does
  // not end in .json): its files are all loaded, then Restore
  await dialog.locator('[data-fp-session-open] input[type="file"]').setInputFiles({
    name: download.suggestedFilename(), mimeType: 'application/json',
    buffer: fs.readFileSync(file),
  });
  await expect.poll(async () => (await status(page)).phase,
    { message: 'the session is ready to restore', timeout: 30000 }).toBe('ready');
  await dialog.locator('button', { hasText: /^Restore$/ }).click();
  await expect.poll(async () => (await status(page)).phase,
    { message: 'the session is restored', timeout: 60000 }).toBe('done');
  const report = (await status(page)).report || [];
  note('report: ' + report.map((r) => r.level + ' ' + r.text).join(' | '));
  expect(report.filter((r) => r.level === 'error'), 'nothing failed').toEqual([]);
  await expect.poll(async () => ((await state(page, 'visible_paths__' + vid)) || []).slice().sort(),
    { message: 'the view shows again what it showed', timeout: 30000 }).toEqual(eyes.slice().sort());

  // the AUTOSAVE: the browser keeps the last state by itself, what a crashed
  // server session leaves behind to come back to
  const stored = async () => page.evaluate(() => {
    try { return JSON.parse(window.localStorage.getItem('fespp-on-trame:session-autosave') || 'null'); }
    catch (e) { return null; }
  });
  // the autosave follows the state a moment behind: an autosave written
  // before the restore ended (the view there, its eyes not yet) is not the
  // one looked for — wait for the one that holds the restored view
  const keptEyes = async () => {
    const k = await stored();
    const v = k && JSON.parse(k.text).views.find((x) => x.id === vid);
    return v ? v.eyes.slice().sort() : null;
  };
  await expect.poll(keptEyes, { message: 'the autosave holds the restored view', timeout: 30000 })
    .toEqual(eyes.slice().sort());
  const kept = await stored();
  note('autosave kept by the browser: ' + kept.saved + ', ' + kept.views + ' view(s)');

  await dialog.locator('button', { hasText: /^Forget$/ }).first().click();
  await page.keyboard.press('Escape');
  await expect(dialog, 'Esc closes the dialog, even after Forget took the focus away').toBeHidden();
});

test('a velocity model restored over the session that saved it stays the model', async ({ app }) => {
  const { page, note } = app;
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  const vid = await viewId(page);
  const model = async () => (await state(page, 'ui_cube_tree')) || {};
  const ticked = async () => ((await state(page, 'selected_paths')) || []).includes((await model()).prop);
  if (!(await ticked())) await ensureVelocityModel(page);
  await expect.poll(ticked, { message: 'the model is in the tree, ticked', timeout: 90000 }).toBe(true);
  await page.waitForTimeout(2000);
  const before = await model();
  const save = async () => {
    await closeImportDoor(page);
    const door = page.locator('.fse');
    if (!(await door.isVisible())) await page.locator('[data-fp-session-launch]').click();
    await expect(door).toBeVisible({ timeout: 15000 });
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 30000 }),
      door.locator('[data-fp-session-save] button', { hasText: /^Save session$/ }).click(),
    ]);
    return fs.readFileSync(await download.path(), 'utf8');
  };
  const text = await save();
  const door = page.locator('.fse');
  await door.locator('[data-fp-session-open] input[type="file"]').setInputFiles({
    name: 'model.fespp.json', mimeType: 'application/json', buffer: Buffer.from(text),
  });
  await expect.poll(async () => ((await state(page, 'ui_session_status')) || {}).phase, { timeout: 30000 }).toBe('ready');
  await door.locator('button', { hasText: /^Restore$/ }).click();
  await expect.poll(async () => ((await state(page, 'ui_session_status')) || {}).phase, { timeout: 120000 }).toBe('done');
  const status = await state(page, 'ui_session_status');
  note('report: ' + (status.report || []).map((r) => r.level + ' ' + r.text).join(' | ').slice(0, 300));
  expect((status.report || []).filter((r) => r.level === 'error'), 'nothing failed').toEqual([]);
  const now = await model();
  note('model: ' + now.row);
  expect(now.prop, 'the tree still holds the model, the same version').toBe(before.prop);
  const selected = (await state(page, 'selected_paths')) || [];
  expect(selected, 'it is read under the uuids it has now').toContain(now.prop);
  const again = JSON.parse(await save());
  expect(Object.keys(again.objects).filter((p) => p.startsWith(now.row)), 'no row of the model among the file objects').toEqual([]);
  expect(now.row, 'the document knows the model by its grid').toContain(again.session.time_depth_law.uuids.grid);
  await door.locator('button', { hasText: /^Forget$/ }).first().click();
  await page.keyboard.press('Escape');
  await expect(door, 'the door closes').toBeHidden();
});

test('a new session offers to resume the last one, and brings its views back', async ({ app }) => {
  // what a crashed server session leaves: nothing on the server, the last
  // state in the browser. A new page behind the launcher is a new, EMPTY
  // session — exactly what the reader gets after a crash.
  const { page, note } = app;
  const kept = await page.evaluate(() => JSON.parse(
    window.localStorage.getItem('fespp-on-trame:session-autosave') || 'null'));
  test.skip(!kept, 'no autosave from the previous scenario');
  const saved = JSON.parse(kept.text);
  const savedView = saved.views.find((v) => v.kind === 'render' && (v.eyes || []).length);
  test.skip(!savedView, 'the autosave holds no 3D view with something shown');

  const fresh = await page.context().newPage();
  try {
    await fresh.goto(APP_URL);
    const dialog = fresh.locator('.fse');
    // the Session dialog never opens by itself at start: it is a click
    // away, and the last autosave is its first offer
    await expect(dialog, 'no Session dialog opens by itself on a fresh page').toHaveCount(0);
    await closeImportDoor(fresh, { expectOpen: true });
    await fresh.locator('[data-fp-session-launch]').click({ timeout: 60000 });
    await expect(dialog.locator('[data-fp-session-autosave]'),
      'the door opened on an empty session offers the last autosave first').toBeVisible({ timeout: 60000 });
    note('offered: ' + (await dialog.locator('[data-fp-session-autosave]').innerText()).replace(/\s+/g, ' ').slice(0, 120));
    await dialog.locator('[data-fp-session-autosave] button', { hasText: /^Resume$/ }).click();
    await expect.poll(async () => ((await state(fresh, 'ui_session_status')) || {}).phase,
      { message: 'the resumed session waits for its files', timeout: 30000 }).toBe('waiting');

    // the data again, dropped where the door asks for it: every file the
    // session names, found in the test data folder, with its .h5
    const root = path.dirname(DATASET.files[0]);
    const find = (dir, name) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name);
        if (e.isFile() && e.name === name) return p;
        if (e.isDirectory()) { const hit = find(p, name); if (hit) return hit; }
      }
      return null;
    };
    const drop = [];
    for (const f of saved.sources.files || []) {
      const epc = find(root, f.name);
      if (!epc) continue;
      drop.push(epc);
      const h5 = epc.replace(/.epc$/i, '.h5');
      if (fs.existsSync(h5)) drop.push(h5);
    }
    note('drop ' + drop.map((p) => path.basename(p)).join(', '));
    expect(drop.length, 'the expected files are in the test data').toBeGreaterThan(0);
    await dialog.locator('input[type="file"][accept*=".epc"]').setInputFiles(drop);
    await expect.poll(async () => ((await state(fresh, 'ui_session_status')) || {}).phase,
      { message: 'every expected file is loaded again', timeout: 120000 }).toBe('ready');
    await dialog.locator('button', { hasText: /^Restore$/ }).click();
    await expect.poll(async () => ((await state(fresh, 'ui_session_status')) || {}).phase,
      { message: 'the session is restored', timeout: 60000 }).toBe('done');
    const report = ((await state(fresh, 'ui_session_status')) || {}).report || [];
    note('report: ' + report.map((r) => r.level + ' ' + r.text).join(' | '));
    expect(report.filter((r) => r.level === 'error'), 'nothing failed').toEqual([]);

    // the same objects, the same paths — in a session that never saw them
    const vid = await viewId(fresh);
    await expect.poll(async () => ((await state(fresh, 'visible_paths__' + vid)) || []).slice().sort(),
      { message: 'the view shows what the crashed session showed', timeout: 30000 })
      .toEqual(savedView.eyes.slice().sort());
  } finally {
    await fresh.close();
  }
});

test('a session read from OSDU comes back with the connection prefilled, the token asked for', async ({ app }) => {
  // the file keeps the server, the partition and the dataspaces, never the
  // token: a credential must not be left lying around in a file
  const { page, note } = app;
  const doc = {
    schema: 1, meta: { app: 'test', saved: '2026-09-26T08:00:00Z', note: '' },
    sources: { files: [], etp: { url: 'wss://osdu.example/api/reservoir-ddms-etp/v2/',
      partition: 'opendes', dataspaces: ["eml:///dataspace('demo/Volve')"] } },
    session: { selected_paths: [] }, objects: {}, layout: null, views: [],
  };
  await closeImportDoor(page);
  await page.locator('[data-fp-session-launch]').click();
  const dialog = page.locator('.fse');
  await expect(dialog, 'the Session dialog opens').toBeVisible({ timeout: 15000 });
  await dialog.locator('[data-fp-session-open] input[type="file"]').first().setInputFiles({
    name: 'osdu.fespp.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(doc)),
  });
  await expect.poll(async () => ((await state(page, 'ui_session_status')) || {}).phase,
    { message: 'the session waits for its OSDU connection', timeout: 30000 }).toBe('waiting');
  const form = dialog.locator('[data-fp-session-etp-slot]');
  await expect(form, 'the connection form is in the door').toBeVisible();
  const fields = form.locator('input.uo-inp');
  await expect(fields.nth(0), 'the server URL is prefilled').toHaveValue(doc.sources.etp.url);
  await expect(fields.nth(1), 'the partition is prefilled').toHaveValue('opendes');
  await expect(form.locator('input.uo-token'), 'the token is NOT in the file').toHaveValue('');
  await expect(form.locator('[data-fp-osdu-prefill]'), 'and the door says so').toBeVisible();
  await expect(dialog.locator('[data-fp-dataspace-state="pending"]'), 'the dataspace is to load').toHaveCount(1);
  await expect(dialog.locator('button', { hasText: /^Restore$/ }), 'nothing to restore before the connection')
    .toBeDisabled();
  note('prefilled: ' + (await fields.nth(0).inputValue()) + ' / ' + (await fields.nth(1).inputValue()));
  await dialog.locator('button', { hasText: /^Forget$/ }).first().click();
  await page.keyboard.press('Escape');
  await expect(dialog, 'Esc closes the dialog, even after Forget took the focus away').toBeHidden();
});
