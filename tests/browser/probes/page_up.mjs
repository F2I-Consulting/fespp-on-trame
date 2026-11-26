/*
 * Probe: the page comes up. Exit 0 when the client mounts, its views' dock
 * shows a tab and the top bar its buttons, with no error thrown by the page
 * along the way; exit 1 otherwise, saying what was missing. What
 * test-before-deploy.ps1 asks of an image before it is put on the public
 * server: a bundle that does not load leaves a blank page no scenario sees.
 *
 *   node probes/page_up.mjs [url]
 */
import { chromium } from '@playwright/test';
import { M } from '../lib/markers.mjs';

const url = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://localhost:8095/index.html';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const thrown = [];
page.on('pageerror', (e) => thrown.push(e.message.replace(/\s+/g, ' ').slice(0, 300)));
let why = '';
try {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.locator(M.dockTab).first().waitFor({ timeout: 120000 });
  await page.waitForTimeout(3000);
  const buttons = await page.locator(M.topBarButton).count();
  if (buttons < 5) why = `the top bar shows ${buttons} button(s)`;
  else if (thrown.length) why = `the page threw: ${thrown[0]}`;
} catch (exc) {
  why = `no view came up: ${String(exc.message || exc).split('\n')[0]}`;
}
await browser.close();
if (why) {
  console.log('page_up: FAIL —', why);
  process.exit(1);
}
console.log('page_up: ok');
