/*
 * Negative controls — the scenarios that make the others worth running.
 *
 * A smoke test drifts green: selectors stop matching, a detector stops
 * detecting, and the suite keeps passing over a broken application. So each of
 * the four failures this harness claims to catch is reproduced here, in pages
 * of its own, and the run fails if the detector stays quiet.
 *
 * Nothing here touches the application session: the controls run in a separate
 * browser context, and the three template failures are mounted in a page whose
 * only content is the application's Vue build. They do not take the session
 * fixture either, so a broken application fails the scenarios, not the controls.
 */
import { test, expect, APP_URL, M, faults, unresolvedComponents } from '../lib/app.mjs';

const note = (line) => process.stdout.write('    · ' + line + '\n');

const SANDBOX = new URL('smoke-controls.html', APP_URL).toString();
const SANDBOX_HTML = '<!doctype html><html><head>'
  + '<script src="vue.global.js"></script></head>'
  + '<body><div id="host"></div></body></html>';

async function controlPage(browser, messages) {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') {
      messages.push({ kind: 'console.' + m.type(), text: m.text().replace(/\s+/g, ' ') });
    }
  });
  page.on('pageerror', (e) => messages.push({ kind: 'uncaught', text: String(e.message) }));
  return { context, page };
}

test('a missing widget bundle is caught', async ({ browser }) => {
  const messages = [];
  const { context, page } = await controlPage(browser, messages);
  // The same failure as a widget left out of the www bake, or a stale build.
  await page.route('**/trame_fespp_tree.umd.js', (route) => route.fulfill({
    status: 200, contentType: 'application/javascript', body: '/* empty bundle */',
  }));
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });

  const gate = await page.locator(M.dockTab).first().waitFor({ timeout: 25000 })
    .then(() => 'opened').catch(() => 'never opened');
  const seen = faults(messages);
  note('gate: ' + gate + ' — ' + seen.map((m) => m.kind + ': '
    + m.text.slice(0, 60)).join(' | '));

  expect(gate, 'the boot gate must not open without the tree bundle')
    .toBe('never opened');
  expect(seen.some((m) => /is not defined/.test(m.text)),
    'the console names the missing bundle').toBe(true);
  await context.close();
});

test('an undefined variable in a component is caught', async ({ browser }) => {
  const messages = [];
  const { context, page } = await controlPage(browser, messages);
  await page.route(SANDBOX, (route) => route.fulfill({ contentType: 'text/html', body: SANDBOX_HTML }));
  await page.goto(SANDBOX);

  // A rename that leaves one reference to the old name: the component
  // throws on its first render and the data tree stays blank.
  const host = await page.evaluate(() => {
    const el = document.getElementById('host');
    const Broken = {
      name: 'BrokenTree',
      render() { return window.Vue.h('div', null, nodesRenamed.length); },
    };
    window.Vue.createApp({ components: { Broken }, template: '<div><Broken/></div>' }).mount(el);
    return { html: el.innerHTML, height: el.getBoundingClientRect().height };
  });
  await page.waitForTimeout(300);
  const seen = faults(messages);
  note('host: ' + JSON.stringify(host) + ' — ' + seen.map((m) => m.text.slice(0, 60)).join(' | '));

  expect(seen.some((m) => /nodesRenamed is not defined/.test(m.text)),
    'the console reports the undefined variable').toBe(true);
  expect(host.height, 'the broken subtree renders nothing').toBe(0);
  await context.close();
});

test('a double quote inside a template attribute is caught', async ({ browser }) => {
  const messages = [];
  const { context, page } = await controlPage(browser, messages);
  await page.route(SANDBOX, (route) => route.fulfill({ contentType: 'text/html', body: SANDBOX_HTML }));
  await page.goto(SANDBOX);

  // A list serialised to JSON inside a double-quoted attribute: the attribute
  // closes early and the template fails to compile.
  const thrown = await page.evaluate(() => {
    const el = document.getElementById('host');
    window.Vue.createApp({ template: '<div :items="[{"key": "a"}]">content</div>' }).mount(el);
    return null;
  }).then(() => null).catch((e) => String(e).replace(/\s+/g, ' ').slice(0, 120));
  const seen = faults(messages);
  note('thrown: ' + (thrown || '(nothing)') + ' — console: '
    + seen.map((m) => m.text.slice(0, 50)).join(' | '));

  expect(Boolean(thrown) || seen.length > 0,
    'the broken template surfaces as an error').toBe(true);
  await context.close();
});

test('a component Vue cannot resolve is caught', async ({ browser }) => {
  const messages = [];
  const { context, page } = await controlPage(browser, messages);
  await page.route(SANDBOX, (route) => route.fulfill({ contentType: 'text/html', body: SANDBOX_HTML }));
  await page.goto(SANDBOX);

  await page.evaluate(() => {
    const el = document.getElementById('host');
    window.Vue.createApp({ template: '<div><data-explorer-tree-unknown :a="1"/></div>' }).mount(el);
  });
  await page.waitForTimeout(300);

  const tags = await unresolvedComponents(page);
  note('hyphenated tags: ' + JSON.stringify(tags)
    + ' — console: ' + JSON.stringify(faults(messages).map((m) => m.text.slice(0, 40))));

  // The production build of Vue says nothing here: the DOM check is the only
  // detector, which is why every scenario ends with it.
  expect(tags, 'the unresolved tag is left in the DOM')
    .toContain('data-explorer-tree-unknown');
  await context.close();
});
