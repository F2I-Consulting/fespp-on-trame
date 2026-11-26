/*
 * Scenario: a page that embeds FesTrame drives it by postMessage with
 * session documents (S4, 21/10): the iframe says "ready", applies a
 * document ({reset: true} here, whose report is known), and answers the
 * state as one document.
 *
 * Last on purpose, hence its number: the shared page becomes the host page
 * (setContent), and the iframe starts a new server session.
 */
import { test, expect, APP_URL } from '../lib/app.mjs';

test('the embedding page applies a document and reads the state', async ({ app }) => {
  const { page, note } = app;
  await page.setContent(`<!doctype html><html><body>
    <iframe id="f" src="${APP_URL}" style="width:1200px;height:700px"></iframe>
    <script>
      window.__msgs = [];
      window.addEventListener('message', (e) => { if (e.data && e.data.festrame !== undefined) window.__msgs.push(e.data); });
    </script></body></html>`);
  const msgs = () => page.evaluate(() => window.__msgs);
  await expect.poll(async () => (await msgs()).some((m) => m.festrame === 'ready'),
    { message: 'the iframe says it is ready', timeout: 120000 }).toBe(true);
  const say = (m) => page.evaluate((msg) => document.getElementById('f').contentWindow.postMessage(msg, '*'), m);

  await say({ festrame: 'apply', document: { reset: true } });
  await expect.poll(async () => (await msgs()).some((m) => m.festrame === 'status' && m.status.phase === 'done'),
    { message: 'the door reports the applied document', timeout: 60000 }).toBe(true);
  const status = (await msgs()).filter((m) => m.festrame === 'status').pop().status;
  note('status: ' + JSON.stringify(status.report));
  expect(status.report.some((r) => /Session emptied/.test(r.text)), 'the reset is reported').toBe(true);

  await say({ festrame: 'state' });
  await expect.poll(async () => (await msgs()).some((m) => m.festrame === 'state'),
    { message: 'the state comes back', timeout: 30000 }).toBe(true);
  const state = (await msgs()).filter((m) => m.festrame === 'state').pop().state;
  note('state: schema ' + state.schema + ', views ' + (state.views || []).length);
  expect(state.schema, 'the document says its format').toBe(1);
  expect(Array.isArray(state.views), 'and its views').toBe(true);
});
