/*
 * The harness: one browser, one page, one application session for the whole
 * pass, plus the two verdicts every scenario is held to.
 *
 * ONE page, deliberately: each page opened against the application starts a
 * ParaView session on the server that outlives the page, so a `goto` per test
 * would leave a pile of processes behind and cost several seconds each. The
 * page is a worker fixture; the scenarios run in file order and each leaves the
 * application usable by the next (the `ensure*` helpers make every scenario
 * runnable on its own all the same).
 *
 * The two verdicts, applied after EVERY scenario without it asking:
 *   - the console said nothing: no error, no warning of the application's own,
 *     no uncaught exception, no failed request;
 *   - the DOM holds no hyphenated tag, i.e. no component Vue failed to resolve
 *     (the page serves the production build of Vue, which prints no warning for
 *     that — the tag left verbatim is the only trace).
 */
import fs from 'node:fs';
import path from 'node:path';
import { test as base, expect } from '@playwright/test';

import { M, CONSOLE_NOISE } from './markers.mjs';
import { DATASET } from './dataset.mjs';

export { expect, M, DATASET };

export const APP_URL = process.env.FESPP_SMOKE_URL
  || 'http://localhost:8095/index.html';
export const OUT_DIR = process.env.FESPP_SMOKE_OUT
  || path.resolve(import.meta.dirname, '..', 'out');

const BOOT_TIMEOUT = 120000;
const LOAD_TIMEOUT = 120000;

// --------------------------------------------------------------- collectors
function collect(page, messages) {
  // A page being left (a reload, a new address) is no fault of the next one:
  // what its client says while it is torn down, its connection closed under
  // it, is not kept — from the navigation's request until the next document
  // is committed, whose own faults all count.
  let leaving = false;
  page.on('request', (r) => {
    if (r.isNavigationRequest() && r.frame() === page.mainFrame()) leaving = true;
  });
  page.on('framenavigated', (f) => { if (f === page.mainFrame()) leaving = false; });
  const push = (kind, text) => leaving || messages.push({
    kind, text: text.replace(/\s+/g, ' '),
    // Set by the session fixture once the client is up: what the console said
    // BEFORE that is a boot-time fault and is reported with that label.
    phase: messages.booted ? 'scenario' : 'boot',
  });
  page.on('console', (m) => {
    const type = m.type();
    if (type !== 'error' && type !== 'warning') return;
    push('console.' + type, m.text());
  });
  page.on('pageerror', (e) => push('uncaught', String(e.message)));
  page.on('requestfailed', (r) => {
    const why = (r.failure() || {}).errorText;
    // a frame of a view, replaced by the next one before it was drawn
    if (r.url().startsWith('blob:') && why === 'net::ERR_ABORTED') return;
    // an upload stopped by the import dialog's Cancel
    if (/\/upload$/.test(r.url()) && /ERR_ABORTED|NS_BINDING_ABORTED/.test(why || '')) return;
    push('request', r.url() + ' — ' + why);
  });
}

/*
 * A fault as the log prints it. The production build of Vue compiles a
 * template with `new Function` and reports a failure as a bare SyntaxError
 * naming no component: that shape is called out for what it is.
 */
export function describeFault(m) {
  const hint = /SyntaxError: .* at Function \(<anonymous>\) .*vue\.global\.js/.test(m.text)
    ? ' [a Vue template did not compile — typically a serialised value inside'
      + ' a double-quoted attribute; the widget whose template it is renders nothing]'
    : '';
  return (m.phase === 'boot' ? '(at boot) ' : '') + m.kind + ': ' + m.text + hint;
}

/*
 * Wait for `predicate` (evaluated in Node) to hold, but stop at once if the
 * console reports a fault meanwhile: a component that just threw will not
 * produce what is being waited for, and a two-minute timeout says nothing —
 * the error does.
 */
export async function waitUntil(app, predicate, { what, timeout = LOAD_TIMEOUT }) {
  const { session } = app;
  const start = Date.now();
  for (;;) {
    if (await predicate()) return;
    const seen = faults(session.messages.slice(app.cursor));
    if (seen.length) {
      throw new Error('gave up waiting for ' + what + ': the browser console reported — '
        + describeFault(seen[0]));
    }
    if (Date.now() - start > timeout) {
      throw new Error(what + ': not seen within ' + Math.round(timeout / 1000) + ' s');
    }
    await session.page.waitForTimeout(250);
  }
}

/* The messages that count as faults: all of them but a console warning on
   the known-noise list (markers.CONSOLE_NOISE). */
export function faults(messages) {
  return messages.filter((m) => !(m.kind === 'console.warning'
    && CONSOLE_NOISE.some((re) => re.test(m.text))));
}

/* The hyphenated tag names left in the DOM: each one is a component Vue did
   not resolve. */
export async function unresolvedComponents(page) {
  return page.evaluate(() => [...new Set([...document.querySelectorAll('*')]
    .map((e) => e.tagName.toLowerCase())
    .filter((t) => t.includes('-')))]);
}

// ------------------------------------------------------------ state reading
/* The application's own state, as the client holds it. */
export function state(page, key) {
  return page.evaluate((k) => {
    const s = window.trame && window.trame.state;
    if (!s) return null;
    const v = s.get ? s.get(k) : (s.state || {})[k];
    return v === undefined ? null : JSON.parse(JSON.stringify(v));
  }, key);
}

/* The id of the 3D view the layout opens with. */
export async function viewId(page) {
  return page.evaluate(() => {
    const s = window.trame.state;
    const all = s.state || s;
    const k = Object.keys(all).find((x) => /^view_tools_/.test(x));
    return k ? k.replace('view_tools_', '') : null;
  });
}

// ----------------------------------------------------------------- gestures
/* The row of the tree in `scope` whose title is exactly `title`. */
export function treeRow(scope, title) {
  return scope.locator(M.treeRow)
    .filter({ has: scope.page().locator(M.treeTitle, { hasText: new RegExp('^' + title + '$') }) })
    .first();
}

/*
 * The data tree — the one inside the 3D view on screen, told apart from the
 * Statistics view's own docked tree by the panel it lives in (the one that
 * renders). The DOM does not follow the tabs once a layout has been restored.
 */
export function dataTree(page) {
  return page.locator(M.dockPart + ':visible').filter({ has: page.locator('[id^="fc-rb-"]') })
    .locator(M.tree).first();
}

/* The tree card of a family (Reservoir, Surface, Well, Seismic) of the 3D view on
   screen, opened by its toolbar button when it is not in sight. */
export async function familyTree(page, name) {
  const view = page.locator(M.dockPart + ':visible').filter({ has: page.locator('[id^="fc-rb-"]') }).first();
  return familyCardTree(page, view, name);
}

/* The tree card of a family in the view `part` (a 3D or Statistics view),
   opened by its toolbar button when it is not in sight. */
export async function familyCardTree(page, part, name) {
  const card = part.locator(M.card + ':visible')
    .filter({ has: page.locator(M.cardTitle, { hasText: new RegExp('^' + name + '$') }) }).first();
  if (!(await card.count())) {
    await part.locator(M.toolButton + ':visible[title^="' + name + '"]').first().click();
    await expect(card, 'the ' + name + ' tree card').toBeVisible({ timeout: 15000 });
  }
  return card.locator(M.tree).first();
}

/* Every family card of the view `part` closed by its toolbar button. */
export async function closeFamilyCards(part) {
  const on = part.locator(M.toolButton + '.active:visible');
  for (let n = await on.count(); n > 0; n--) await on.first().click();
  await expect(part.locator(M.tree + ':visible'), 'every tree card closed').toHaveCount(0, { timeout: 10000 });
}

/* The part of the views' dock holding the 3D view `vid`: its toolbar, its
   render and its cards, floating, docked or in panels. Found by the view's
   rubber band (view_panel `fc-rb-<vid>`), which every 3D view draws. */
export function viewPart(page, vid) {
  return page.locator(M.dockPart).filter({ has: page.locator('#fc-rb-' + vid) }).first();
}

/* The button `action` (left, right, top, bottom, float, close) of the tab row
   right above `part`, a view's panel: dockview draws a panel apart from its
   group, so the row is found by its place. */
export async function viewButton(page, part, action) {
  await part.waitFor({ state: 'visible', timeout: 30000 });
  const box = await part.boundingBox();
  const rows = page.locator(M.dockRow + ':visible');
  for (let i = 0; i < (await rows.count()); i++) {
    const row = await rows.nth(i).boundingBox();
    if (row && Math.abs(row.y + row.height - box.y) <= 3 && box.x >= row.x - 3
        && box.x + box.width <= row.x + row.width + 3) {
      return rows.nth(i).locator(M.dockAction + '[data-fp-action="' + action + '"]');
    }
  }
  throw new Error('no tab row above the panel');
}

/* The anchor button of the detached view (its window's detach button). */
export function anchorButton(page) {
  return page.locator(M.dockWindow).locator(M.dockAction + '[data-fp-action="float"]:visible').first();
}

/*
 * The Statistics view (`compare` in the code), with its docked tree OPEN.
 *
 * Every panel that carries a tree mounts it behind a `v-show`, closed by
 * default; it opens by itself only on the first opening of a panel with
 * nothing in it, the one case where the tree is the only door. So the tree
 * may be in the DOM yet invisible, and a spec that only waited for `.fdx`
 * would click a hidden checkbox for ever: the header button (the same button
 * in Statistics, Well log and Log <-> Grid) is pressed here when it is needed.
 */
/* Close the view of kind `kind` by its top-bar button: a click brings an open
   view to the front, the next one closes it. Each click waits for its effect,
   or a second click sent while the first is still on its way reopens it. */
export async function closeView(page, title, kind) {
  const now = async () => JSON.stringify([(await state(page, 'ui_open_view_kinds')) || [],
    await state(page, 'fespp_active_panel_id')]);
  for (let k = 0; k < 3 && ((await state(page, 'ui_open_view_kinds')) || []).includes(kind); k++) {
    const before = await now();
    await page.locator(M.topBarButton + '[title^=' + JSON.stringify(title) + ']').click();
    await expect.poll(now, { message: 'the ' + title + ' button answered', timeout: 15000 }).not.toBe(before);
  }
}

/* A view brought on screen by its button of the top bar, which closes it when
   it is in sight already. `widget`: what it draws. */
export async function showView(page, title, widget) {
  if (!(await widget.first().isVisible().catch(() => false))) {
    await page.locator(M.topBarButton + '[title^=' + JSON.stringify(title) + ']').click();
  }
  await widget.first().waitFor({ state: 'visible', timeout: 60000 });
}

/* The Time-depth model view in sight and a velocity model active: generated
   here when none is — a TDLaw placed at the centre of the zone (an object is
   read: the zone is the data's), a point added on its track by its
   right-click, Generate. */
export async function ensureVelocityModel(page) {
  await showView(page, 'Time-depth', page.locator('.tdp'));
  const law = async () => (await state(page, 'ui_time_depth_law')) || {};
  if ((await law()).generated) return;
  if (!(await law()).can_generate) {
    if (!((await law()).columns || []).length) {
      await page.locator('.tdl-add button', { hasText: /^Place$/ }).click();
      await expect.poll(async () => ((await law()).columns || []).length, { message: 'a TDLaw placed' })
        .toBeGreaterThan(0);
    }
    const band = await page.locator('.tls .tls-hit').first().boundingBox();
    await page.mouse.click(band.x + band.width / 2, band.y + band.height * 0.6, { button: 'right' });
    await page.locator('.fp-menu [role="menuitem"]', { hasText: /^Add a point here/ }).click();
    await expect.poll(async () => (await law()).can_generate, { message: 'a TDLaw that converts' }).toBe(true);
  }
  await page.locator('.tdl button', { hasText: /^Generate$/ }).click();
  await expect.poll(async () => (await law()).generated,
    { message: 'the velocity model generated', timeout: 60000 }).toBe(true);
}

export async function openCompare(page) {
  await showView(page, 'Statistics', page.locator(M.compare));
  const panel = page.locator(M.dockPart).filter({ has: page.locator(M.compare) }).first();
  await panel.locator(M.compare).waitFor({ timeout: 60000 });
  const tree = panel.locator(M.tree).first();
  if (!(await tree.isVisible())) {
    // the card of the first family the file holds, by the view's toolbar
    const held = (await state(page, 'ui_compare_tree_families')) || [];
    await familyCardTree(page, panel, held[0] || 'Reservoir');
  }
  return panel;
}

/* The Statistics view's selection as the application holds it — one entry per
   item, its path, its title and its kind (the server's per-item facts). The
   matrix draws the items of the current kind tab only, and the rows that follow
   them, so a count of what the view HOLDS reads the state, not the DOM. */
export async function compareItems(page) {
  return (await state(page, 'ui_compare_chips')) || [];
}

/* The rows of the matrix of the current kind tab: the items and what follows
   them. A row following an item says what it is read on in `support`. */
export async function compareRows(page) {
  return Object.entries((await state(page, 'ui_compare_rows')) || {})
    .map(([id, row]) => ({ id, ...row }));
}

/* Whether the view holds the property at `nodePath`, whatever its tab. */
export async function statsHold(page, nodePath) {
  return ((await state(page, 'ui_compare_items')) || []).some((it) => it.path === nodePath);
}

/* "Add to stats" on a row of the data tree, unless the view holds it already.
   Either way its tab comes to the front of the view, and its row has its
   figures in `ui_compare_rows` when this returns. Returns the view's panel, its
   docked tree open. */
export async function addToStats(app, title, nodePath) {
  const { page } = app;
  if (!(await statsHold(page, nodePath))) {
    await focusRenderView(page);
    const tree = dataTree(page);
    await expandTree(tree);
    await treeRow(tree, title).click({ button: 'right' });
    await page.locator(M.ctxMenu).waitFor({ timeout: 10000 });
    await page.locator(M.ctxItem, { hasText: /^Stats$/ }).click();
    await expect.poll(() => statsHold(page, nodePath),
      { message: title + ' joins the statistics', timeout: 30000 }).toBe(true);
  }
  const panel = await openCompare(page);
  await expect.poll(async () => (await compareItems(page)).some((c) => c.path === nodePath),
    { message: title + ' has its entry in the view', timeout: 30000 }).toBe(true);
  const { kind } = (await compareItems(page)).find((c) => c.path === nodePath);
  await panel.locator(M.compareTab, { hasText: kind }).first().click();
  await expect(panel.locator(M.compareTabOn), 'the tab of ' + title).toContainText(kind);
  await expect.poll(async () => (await compareRows(page))
    .some((r) => r.path === nodePath && Object.keys(r.metrics || {}).length > 0),
  { message: title + ' has its figures', timeout: 60000 }).toBe(true);
  return panel;
}

/* The parts of a grid the docked tree lists, read or not: their title and what
   they are. */
export async function comparePartsListed(page) {
  const xml = (await state(page, 'ui_compare_tree_xml')) || '';
  return page.evaluate((doc) => {
    const root = new DOMParser().parseFromString(doc, 'application/xml');
    return [...root.querySelectorAll('[type="ComparePart"]')]
      .map((e) => ({ title: e.getAttribute('title'), kind: e.getAttribute('propType') }));
  }, xml);
}

/* Open every collapsed node: the tree ships only its roots at first. */
export async function expandTree(scope) {
  const page = scope.page();
  for (let i = 0; i < 12; i += 1) {
    const clicked = await scope.evaluate((root, caret) => {
      const closed = [...root.querySelectorAll('.tn-caret')]
        .filter((e) => e.textContent.trim() === caret);
      closed.forEach((e) => e.click());
      return closed.length;
    }, M.caretCollapsed);
    if (!clicked) return;
    await page.waitForTimeout(400);
  }
}

/* Close the Import data door when it is open: an empty session opens it by
   itself on mount, and its scrim then takes every click of the page. */
export async function closeImportDoor(page, { expectOpen = false } = {}) {
  const door = page.locator('.up-dialog');
  // a page just opened on an empty session: the door comes up once the
  // client has mounted and heard the state, so wait for it before closing
  if (expectOpen) await expect(door, 'an empty session opens the Import data door').toBeVisible({ timeout: 60000 });
  if (!(await door.isVisible().catch(() => false))) return;
  await door.locator('.fp-dialog-head button[title="Close"]').click();
  await expect(door, 'the Import data door closes').toBeHidden({ timeout: 15000 });
}

/*
 * Open the Import data door, unless it is ALREADY open.
 *
 * An empty session opens it by itself (UploadData.mounted): there is nothing
 * else to do until something is in. Pressing the toolbar button on top of it
 * hits the dialog's own scrim, not the button, and the click never lands.
 * Every scenario that reaches the door goes through here.
 */
export async function openImportDoor(page) {
  const sources = page.locator('.up-sources');
  if (await sources.isVisible().catch(() => false)) return;
  await page.locator(M.topBarButton, { hasText: /import data/i }).first().click();
  await expect(sources, 'the Import data door opens').toBeVisible({ timeout: 15000 });
}

/* The end of an import: the dialog closes ITSELF once every file is read
 * (the manager, 15/10), after a beat in which its Close button can still be
 * pressed. Either way the dialog must end up gone; a failed file keeps it
 * open, and this says so. */
export async function closeImport(page) {
  const dialog = page.locator('.up-dialog');
  const close = page.locator(M.importClose);
  await Promise.race([
    close.waitFor({ state: 'visible', timeout: 180000 }),
    dialog.waitFor({ state: 'detached', timeout: 180000 }),
  ]).catch(() => {});
  if (await close.isVisible().catch(() => false)) {
    await close.click({ timeout: 3000 }).catch(() => {});
  }
  await expect(dialog, 'the import dialog closes once every file is read').toHaveCount(0,
    { timeout: 15000 });
}

/* `files` through the Import data door. */
async function importFiles(app, files) {
  const { page, note } = app;
  note('import ' + files.map((f) => path.basename(f)).join(' + '));
  await openImportDoor(page);
  await page.setInputFiles(M.fileInput, files);
  // no button: the files go as soon as the drop has settled, and the dialog
  // closes itself once they are read
  await waitUntil(app, () => state(page, 'ui_has_data'),
    { what: 'the application to report the file as loaded (ui_has_data)' });
  await closeImport(page);
  await waitUntil(app, () => page.locator(M.treeRow).count(),
    { what: 'a first row in the data tree' });
  note('loaded — ' + (await page.locator(M.treeRow).count()) + ' tree row(s)');
}

/* Load the test file through the Import data door, unless data is already in. */
export async function ensureData(app) {
  if (await state(app.page, 'ui_has_data')) return;
  expect(DATASET.missing, 'test file not found: ' + DATASET.missing).toBeNull();
  await importFiles(app, DATASET.files);
}

/*
 * A session of its own on `files`, in a page of its own, for a scenario whose
 * file would change what every later scenario finds in the shared session. It
 * has the shape of `app` (the helpers take it as they take `app`), and the
 * scenario holds it to the two verdicts itself, with `holdVerdicts`.
 */
export async function ownSession(app, files) {
  const page = await app.page.context().newPage();
  const messages = [];
  collect(page, messages);
  const own = { page, note: app.note, session: { page, messages }, cursor: 0 };
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });
  await page.locator(M.dockTab).first().waitFor({ timeout: BOOT_TIMEOUT });
  messages.booted = true;
  // an empty session opens the door by itself: a click on the bar would land
  // on its scrim
  await expect(page.locator('.up-sources'), 'an empty session opens the Import data door')
    .toBeVisible({ timeout: 60000 });
  await importFiles(own, files);
  return own;
}

/* The two verdicts on a session of its own. */
export async function holdVerdicts(own) {
  expect(faults(own.session.messages).map(describeFault), 'the browser console must stay silent').toEqual([]);
  expect(await unresolvedComponents(own.page), 'components Vue could not resolve').toEqual([]);
}

/*
 * Tick a property of the data tree and wait for the application to say it is
 * loaded. Returns the row's path — the identity the state speaks in, read off
 * the row found by its visible title.
 */
export async function ensureProperty(app, title) {
  const { page, note } = app;
  await ensureData(app);
  // A panel opened by an earlier scenario may be covering the view: the tree
  // is only clickable once its own panel is back in front.
  await focusRenderView(page);
  const tree = dataTree(page);
  await expandTree(tree);
  const row = treeRow(tree, title);
  // the tree may be on another family tab: an earlier scenario read a well
  const tabs = tree.locator('.fdx-tab');
  for (let i = 0; !(await row.count()) && i < await tabs.count(); i += 1) {
    await tabs.nth(i).click();
    await expandTree(tree);
  }
  await expect(row, 'the data tree shows a row titled ' + title)
    .toHaveCount(1, { timeout: 15000 });
  const nodePath = await row.getAttribute('data-path');
  const loaded = (await state(page, 'ui_loaded_array_paths')) || [];
  if (loaded.includes(nodePath)) return nodePath;
  note('tick ' + title);
  await row.locator(M.treeCheck).click();
  await waitUntil(app,
    async () => ((await state(page, 'ui_loaded_array_paths')) || []).includes(nodePath),
    { what: 'the application to report ' + title + ' as loaded' });
  note(title + ' is loaded');
  return nodePath;
}

/* The first 3D view back in depth. The time-depth model's view turns the 3D
   view in use to time, where what is in depth is not drawn and its rows carry
   no eye: a scenario before may have left it there. */
export async function depthView(page) {
  const vid = await viewId(page);
  const domain = () => state(page, 'ui_vdomain__' + vid);
  if ((await domain()) !== 'time') return;
  await page.locator('[data-t3-domain]:visible').first().click();
  await expect.poll(domain, { message: 'the view back in depth', timeout: 30000 }).toBe('depth');
}

/* Read, and shown in the 3D view on screen, in depth: a scenario before may have
   closed its eye, and a read does not open it again. */
export async function ensureShown(app, title) {
  const { page } = app;
  const nodePath = await ensureProperty(app, title);
  await focusRenderView(page);
  await depthView(page);
  const vid = await viewId(page);
  const shown = async () => ((await state(page, 'visible_paths__' + vid)) || []).includes(nodePath);
  if (!(await shown())) {
    const tree = dataTree(page);
    await expandTree(tree);
    await treeRow(tree, title).locator(M.treeEye).click();
  }
  await expect.poll(shown, { message: 'the view shows ' + title, timeout: 30000 }).toBe(true);
  return nodePath;
}

/*
 * Press a top-bar button, and answer the question some of them ask.
 *
 * The 3D views door opens its tiles: its "+" tile asks what a new view
 * starts from, empty or a copy of an open view. A sweep of the bar therefore
 * goes through the "+" tile and ANSWERS, or the pop-over's or the dialog's
 * scrim stays over the page and swallows every later click. `answer` is the
 * reading to pick; "Empty view" is the cheapest, it copies nothing.
 */
export async function clickTopBar(page, title, answer = 'Empty view') {
  await page.locator(M.topBarButton + '[title=' + JSON.stringify(title) + ']').click();
  if (/^3D views/.test(title)) await page.locator(M.viewsDoorPop + ' ' + M.viewsDoorAdd).click();
  const dialog = page.locator(M.newViewDialog);
  await dialog.waitFor({ state: 'visible', timeout: 2500 }).catch(() => {});
  if (!(await dialog.isVisible().catch(() => false))) return;
  await dialog.locator('.fp-segbtn', { hasText: answer }).click();
  await dialog.locator('button', { hasText: /^Open$/ }).click();
  await expect(dialog, 'the new-view question closes once answered')
    .toBeHidden({ timeout: 15000 });
}

/* Open the tool card `key` of the view on screen unless it is open already;
   returns a closer, for that view on screen too. */
export async function openTool(page, vid, key) {
  const tools = (await state(page, 'view_tools_' + vid)) || [];
  const index = tools.findIndex((t) => t.key === key);
  expect(index, 'the view offers the ' + key + ' card').toBeGreaterThan(-1);
  const button = page.locator(M.toolButton + ':visible').nth(index);
  const wasOpen = ((await state(page, 'ui_open_tools_by_view'))[vid] || []).includes(key);
  if (!wasOpen) await button.click();
  await expect.poll(async () => ((await state(page, 'ui_open_tools_by_view'))[vid] || [])
    .includes(key), { message: 'card ' + key + ' opens' }).toBe(true);
  return async () => { if (!wasOpen) await button.click(); };
}

/*
 * The Property slicer of the first 3D view emptied by its ⟲. The card opened
 * on an active property makes a box with it, and a property a box reads
 * cannot be unticked: a scenario that unloads starts from no box.
 */
export async function emptyPropertySlicer(page) {
  const vid = await viewId(page);
  const held = async () => ((await state(page, 'ui_thresholds__' + vid)) || []).length;
  if (!(await held())) return;
  await focusRenderView(page);
  const close = await openTool(page, vid, 'thresholds');
  const card = page.locator(M.card)
    .filter({ has: page.locator(M.cardTitle, { hasText: /^Property slicer/ }) }).locator('.fsl').first();
  await card.locator('.fsl-reset').dispatchEvent('click');
  await expect.poll(held, { message: 'the Property slicer holds no box', timeout: 20000 }).toBe(0);
  await close();
}

/* Move a range input the way a hand does: value, input, then change on release. */
export async function slide(locator, value) {
  await locator.evaluate((el, v) => {
    el.value = String(v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

/* Bring the 3D view back to the front (a panel may have opened over it, an
   import door left open would take the click). */
export async function focusRenderView(page) {
  await closeImportDoor(page);
  const tab = page.locator(M.dockTab, { hasText: /^3D view \d+$/ }).first();
  if (await tab.count()) await tab.click();
  await page.locator(M.toolbar + ':visible').first().waitFor({ timeout: 15000 });
}

/* Right-click a tree row, read its menu, close it. */
export async function readContextMenu(scope, title) {
  const page = scope.page();
  await treeRow(scope, title).click({ button: 'right' });
  await expect(page.locator(M.ctxMenu), 'no context menu appeared on a right-click of ' + title)
    .toHaveCount(1, { timeout: 10000 });
  const menu = await page.evaluate((m) => ({
    title: ((document.querySelector(m.ctxTitle) || {}).innerText || '').trim(),
    items: [...document.querySelectorAll(m.ctxItem)].map((e) => e.innerText.trim()),
  }), M);
  // Closing is not what is under test: the click goes straight to the
  // backdrop element rather than through its on-screen box.
  await page.locator(M.backdrop).first().dispatchEvent('click');
  await expect(page.locator(M.ctxMenu), 'the context menu of ' + title + ' did not close')
    .toHaveCount(0, { timeout: 10000 });
  return menu;
}

/* Dockview panels actually on screen (an inactive one is zero high). */
export function visiblePanels(page) {
  return page.evaluate((m) => [...document.querySelectorAll(m.dockPart)]
    .filter((e) => e.getBoundingClientRect().height > 0)
    .map((e) => ({
      height: Math.round(e.getBoundingClientRect().height),
      text: (e.innerText || '').replace(/\s+/g, ' ').trim(),
      canvases: e.querySelectorAll('canvas').length,
    })), M);
}

/* Tool cards currently open, by title (a closed card is display:none). A card
   in a panel names its target after its title, as its tab does: the title is
   the part before. */
export function openCards(page) {
  return page.evaluate((m) => [...document.querySelectorAll(m.card)]
    .filter((c) => c.offsetParent !== null)
    .map((c) => {
      const body = c.querySelector(m.cardBody);
      const head = ((c.querySelector(m.cardTitle) || {}).innerText || '').trim();
      return {
        title: c.matches(m.cardInPanel) ? head.split(' · ')[0] : head,
        height: body ? Math.round(body.getBoundingClientRect().height) : 0,
        text: body ? (body.innerText || '').replace(/\s+/g, ' ').trim() : '',
        // A card can be legitimately wordless — the Colormap card is a
        // gradient and a few handles — so controls count as content too.
        controls: body
          ? body.querySelectorAll('button, input, select, textarea, canvas, svg').length
          : 0,
      };
    }), M);
}

// ----------------------------------------------------------------- fixtures
/* The cards a scenario left open stand over the tree and the view of the next
   one, in every view of the session: each starts with its tree cards alone. */
async function closeLeftCards(page) {
  // a closed card stays in the page, undisplayed; one in a view behind a tab is
  // still displayed, in a part that is not. A floating card closes by its own
  // cross, a card in a panel by the cross of the tab wearing its title.
  const left = (close) => page.evaluate(([m, closing]) => {
    const title = (c) => ((c.querySelector(m.cardTitle) || {}).textContent || '').trim();
    const cross = (c) => {
      const own = c.querySelector(m.cardClose);
      if (own) return own;
      const dock = c.closest(m.cardDock);
      const tab = dock && [...dock.querySelectorAll('.dv-tab')]
        .find((t) => t.textContent.trim() === title(c));
      return tab ? tab.querySelector(m.dockTabClose) : null;
    };
    const cards = [...document.querySelectorAll(m.card)].filter((c) => c.style.display !== 'none'
      && !/^(Reservoir|Surface|Well|Seismic)$/.test(title(c)));
    if (closing) cards.forEach((c) => { const x = cross(c); if (x) x.click(); });
    return cards.length;
  }, [M, close]);
  if (!(await left(false))) return;
  // a scenario's own close may be on its way: a click now would toggle the card open again
  await page.waitForTimeout(1500);
  for (let round = 0; round < 3 && await left(true); round++) {
    await expect.poll(() => left(false), { timeout: 5000 }).toBe(0).catch(() => {});
  }
}

export const test = base.extend({
  /* One application session for the whole pass. */
  session: [async ({ browser }, use) => {
    const context = await browser.newContext({ viewport: { width: 1800, height: 1100 } });
    const page = await context.newPage();
    const messages = [];
    collect(page, messages);
    process.stdout.write('\n  session: ' + APP_URL + '\n');
    await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });
    // The gate: a dockview tab means the server pushed its layout. A widget
    // bundle that never arrives leaves the page on "Loading…" and times out
    // here — which is one of the failures this harness exists to catch.
    await page.locator(M.dockTab).first().waitFor({ timeout: BOOT_TIMEOUT })
      .catch(() => {
        throw new Error('the client never came up (no panel within '
          + Math.round(BOOT_TIMEOUT / 1000) + ' s); the browser console said: '
          + (faults(messages).map(describeFault).join(' | ') || 'nothing'));
      });
    messages.booted = true;
    // What the console said during boot belongs to the first scenario run in
    // this session: the cursor starts at zero and each scenario moves it on.
    await use({ page, messages, context, cursor: 0 });
    await context.close();
  }, { scope: 'worker' }],

  /* Per scenario: a journal, and the two verdicts. */
  app: async ({ session }, use, testInfo) => {
    const { page, messages } = session;
    const first = session.cursor;
    const journal = [];
    const note = (line) => {
      journal.push(line);
      process.stdout.write('    · ' + line + '\n');
    };
    await closeLeftCards(page);
    await use({ page, note, session, cursor: first });

    session.cursor = messages.length;
    const seen = faults(messages.slice(first));
    const tags = page.isClosed() ? [] : await unresolvedComponents(page);
    const failed = testInfo.status !== testInfo.expectedStatus
      || seen.length > 0 || tags.length > 0;

    fs.mkdirSync(OUT_DIR, { recursive: true });
    const slug = path.basename(testInfo.file, '.spec.mjs');
    const why = (testInfo.errors || [])
      .map((e) => (e.message || '').replace(/\[[0-9;]*m/g, '').split('\n')
        .find((l) => l.trim()) || '')
      .filter(Boolean);
    fs.appendFileSync(path.join(OUT_DIR, slug + '.log'),
      ['=== ' + testInfo.title + ' - ' + (failed ? 'FAIL' : 'PASS'),
        ...journal.map((l) => '    ' + l),
        ...why.map((l) => '    FAILED: ' + l.trim()),
        ...seen.map((m) => '    CONSOLE ' + describeFault(m)),
        ...tags.map((t) => '    UNRESOLVED COMPONENT <' + t + '>'),
        ''].join('\n'), 'utf8');
    if (failed && !page.isClosed()) {
      const shot = path.join(OUT_DIR, slug + '-'
        + testInfo.title.replace(/[^a-z0-9]+/gi, '-').toLowerCase() + '.png');
      await page.screenshot({ path: shot }).catch(() => {});
      process.stdout.write('    screenshot: ' + shot + '\n');
    }
    expect(seen.map(describeFault), 'the browser console must stay silent').toEqual([]);
    expect(tags, 'components Vue could not resolve').toEqual([]);
  },
});
