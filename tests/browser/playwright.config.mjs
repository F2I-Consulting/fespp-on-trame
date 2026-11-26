/*
 * One worker, no parallelism, file order: the scenarios share a single
 * application session (see lib/app.mjs) and each one leaves the application
 * where the next expects it. Retries would replay gestures on an application
 * already changed by the failed attempt, so there are none — a smoke test that
 * needs a second try has found something.
 *
 * The container and the URL are the launcher's business (test-browser.ps1);
 * FESPP_SMOKE_URL is how it says where the application is.
 */
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  testMatch: '**/*.spec.mjs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180000,
  expect: { timeout: 15000 },
  reporter: [['list', { printSteps: false }]],
  outputDir: './out/artifacts',
  use: {
    headless: !process.env.FESPP_SMOKE_HEADED,
    actionTimeout: 30000,
  },
});
