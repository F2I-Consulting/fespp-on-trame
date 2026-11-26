/*
 * An upload stopped by its Cancel while its bytes go up: the file leaves the
 * dialog, and the server keeps nothing of it, so the same file sent again is
 * read as new, not "already imported" (engine/io/upload_endpoint removes what
 * a request cut off had written). The upload is slowed through Chromium's
 * network conditions, so there is time to press Cancel.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test, expect, M, state, ensureData, openImportDoor } from '../lib/app.mjs';

test('an upload cancelled while it goes up leaves nothing behind', async ({ app, browserName }) => {
  test.skip(browserName !== 'chromium', 'the upload is slowed through Chromium only');
  const { page, note } = app;
  await ensureData(app);
  // a side file alone: the server stores it and reads nothing
  const name = `fespp-cancel-${Date.now()}.h5`;
  const file = path.join(os.tmpdir(), name);
  fs.writeFileSync(file, Buffer.alloc(6 * 1024 * 1024));
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  const throttle = (bytesPerSecond) => cdp.send('Network.emulateNetworkConditions',
    { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: bytesPerSecond });
  try {
    await throttle(512 * 1024);
    await openImportDoor(page);
    await page.setInputFiles(M.fileInput, file);
    const cancel = page.locator('.uf-cancel');
    await expect(cancel, 'Cancel while the file goes up').toBeVisible({ timeout: 15000 });
    await expect.poll(async () => parseInt(await page.locator('.uf-state-sending').first().innerText(), 10) || 0,
      { message: 'part of it sent', timeout: 15000 }).toBeGreaterThan(0);
    await cancel.click();
    await expect(page.locator('.uf-file'), 'the file leaves the dialog').toHaveCount(0);
    await expect(cancel, 'Cancel goes with it').toHaveCount(0);
    await throttle(-1);
    await page.setInputFiles(M.fileInput, file);
    await expect(page.locator('.uf-file .uf-state-done'), 'sent again in full').toHaveCount(1, { timeout: 60000 });
    const said = (await state(page, 'empty_color_snackbar_text')) || '';
    note('after the second send: ' + said);
    expect(said, 'read as new: the server kept nothing of the cancelled one').not.toContain(name);
    await expect(page.locator('.up-sources'), 'the dialog closes by itself').toHaveCount(0, { timeout: 15000 });
  } finally {
    await throttle(-1).catch(() => {});
    fs.rmSync(file, { force: true });
  }
});
