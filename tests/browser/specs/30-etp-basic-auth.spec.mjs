/*
 * The OSDU / ETP form offers two ways in: a Bearer token, or a user name and
 * a password (Basic). FESPP's ETP source takes both (ETPTokenType Bearer or
 * Basic, the header it sends is "<type> <token>"). The select swaps the token
 * field for the user and password fields, Connect waits for both, and the
 * failure message of a Basic connect names what to check: the user and the
 * password. The server targeted is a closed local port, so the connect runs
 * its full course and fails; 20-etp-wait covers the Bearer path.
 */
import { test, expect, state, ensureData, openImportDoor } from '../lib/app.mjs';

test('the ETP form connects with a user and a password (Basic)', async ({ app }) => {
  const { page, note } = app;
  await ensureData(app);
  await openImportDoor(page);
  const form = page.locator('.uo-form');
  const auth = form.locator('select.uo-inp');
  const connect = form.locator('button.uo-primary');
  await expect(auth, 'the authentication select is on the form').toHaveCount(1);
  await expect(auth, 'Bearer is the default').toHaveValue('Bearer');
  await expect(form.locator('input.uo-token'), 'Bearer asks for a token').toBeVisible();
  await expect(form.locator('input[type=password]'), 'Bearer: its masked token, no password field').toHaveCount(1);

  await form.locator('input.uo-inp').nth(0).fill('wss://127.0.0.1:9/');
  await form.locator('input.uo-inp').nth(1).fill('p');
  await auth.selectOption('Basic');
  await expect(form.locator('input.uo-token'), 'Basic has no token field').toHaveCount(0);
  const user = form.locator('input[autocomplete=username]');
  const password = form.locator('input[type=password]');
  await expect(user, 'Basic asks for a user').toBeVisible();
  await expect(password, 'Basic asks for a password').toBeVisible();

  await expect(connect, 'Connect waits for the user').toBeDisabled();
  await user.fill('reader');
  await expect(connect, 'Connect waits for the password').toBeDisabled();
  await password.fill('s3cret word');
  await expect(connect, 'user and password are enough').toBeEnabled();

  await connect.click();
  await expect.poll(async () => (await state(page, 'etp_status')) || '',
    { message: 'the connect starts', timeout: 15000 })
    .toMatch(/^Connecting to /);
  await expect.poll(async () => (await state(page, 'etp_status')) || '',
    { message: 'a refused Basic connect says what to check', timeout: 60000 })
    .toMatch(/^Connection failed[\s\S]*user and password\.$/);
  const status = await state(page, 'etp_status');
  note('status: ' + status);
  expect(status, 'the password never shows in the status').not.toContain('s3cret');

  // back to Bearer: the token field returns, the Basic fields leave
  await auth.selectOption('Bearer');
  await expect(form.locator('input.uo-token')).toBeVisible();
  await expect(form.locator('input[type=password]'), 'back to Bearer: its token, no password').toHaveCount(1);
});
