/*
 * An OSDU connection that does not answer keeps the session alive.
 *
 * The connector polls the ETP source for up to 30 s. The wait sleeps on the
 * server loop instead of blocking the server thread, so the "Connecting …"
 * status the controller writes first reaches the browser while the
 * connector still polls, and the websocket keeps its heartbeat; a blocking
 * wait would hold back every state push until the failure. The connect
 * targets a closed local port, so the poll runs its full course and ends in
 * the "Connection failed" status. What stays synchronous is fetpapi's own
 * reconnect loop inside the C++ Connect (ten retries, five seconds on a
 * refused port): the status shows up once it returns. wslink answers the
 * RPCs of ONE session in order, so another trigger of the same session
 * still waits for the poll to end; what the loop keeps free is the state
 * pushes and the other sessions of the process.
 */
import { test, expect, state, ensureData, openImportDoor, M } from '../lib/app.mjs';

test('a slow ETP connection blocks neither the state nor the other triggers', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  // the OSDU half of the Import door, filled with a server that will not
  // answer. No tab to press: both sources are on screen at once.
  await openImportDoor(page);
  await expect(page.locator('.up-src'), 'both import sources are on screen at once')
    .toHaveCount(2);
  await page.locator('.uo-form input.uo-inp').nth(0).fill('wss://127.0.0.1:9/');
  await page.locator('.uo-form input.uo-inp').nth(1).fill('p');
  await page.locator('.uo-form input.uo-token').fill('t');
  await page.locator('.uo-form button.uo-primary').click();
  // the in-flight status arrives while the connector still polls (after the
  // C++ reconnect loop's five seconds, well before the poll's thirty)
  await expect.poll(async () => (await state(page, 'etp_status')) || '',
    { message: 'the connecting status reaches the browser during the wait', timeout: 15000 })
    .toMatch(/^Connecting to /);
  expect(await state(page, 'etp_connecting'), 'the connect is still in flight').toBe(true);
  const seenAt = Date.now();
  // the wait ends the way a refused server should: said, not hung
  await expect.poll(async () => (await state(page, 'etp_status')) || '',
    { message: 'the connect ends with a failure status', timeout: 45000 })
    .toMatch(/^Connection failed/);
  const waited = Date.now() - seenAt;
  note('the in-flight status was on screen ' + waited + ' ms before the failure');
  expect(waited, 'the status reached the browser well before the poll ended').toBeGreaterThan(5000);
  expect(await state(page, 'etp_connecting')).toBe(false);
});
