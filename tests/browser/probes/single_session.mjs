/*
 * Probe: the pool's single-session mode (FESPP_POOL_SINGLE=1, the public
 * demo). Two tabs, then every tab closed and one opened again: the pool hands
 * the same session each time, and only one is ever taken.
 *
 *   docker run -d --name fespp_single -p 8096:80 -e FESPP_POOL=1 -e FESPP_POOL_SIZE=1 \
 *     -e FESPP_POOL_SINGLE=1 -e TRAME_URL_PREFIX=/fespp -e "TRAME_USE_HOST=ws://USE_HOST/fespp" <image>
 *   node probes/single_session.mjs http://localhost:8096/fespp/
 */
import { chromium } from '@playwright/test';

const BASE = process.argv[2] || 'http://localhost:8096/fespp/';
const API = BASE.replace(/\/$/, '') + '/paraview';
const say = (...a) => console.log(...a);
const sessions = async () => (await fetch(API + '/sessions')).json();
const pool = async () => (await fetch(API + '/pool')).json();

const browser = await chromium.launch({ headless: true });
const open = async () => {
  const page = await (await browser.newContext({ viewport: { width: 1300, height: 850 } })).newPage();
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.locator('.dv-tab').first().waitFor({ timeout: 120000 });
  return page;
};
let ok = true;
const check = (cond, what) => { say((cond ? 'ok   ' : 'FAIL ') + what); ok = ok && cond; };

const first = await open();
const s1 = await sessions();
say('after the first tab:', JSON.stringify(await pool()), s1.map((s) => s.id).join(','));
check(s1.length === 1, 'one session taken');
const second = await open();
const s2 = await sessions();
check(s2.length === 1 && s2[0].id === s1[0].id, 'a second tab gets the same session');
await first.context().close();
await second.context().close();
await new Promise((r) => setTimeout(r, 5000));
const third = await open();
const s3 = await sessions();
check(s3.length === 1 && s3[0].id === s1[0].id, 'every tab closed then one opened again: the same session');
const mounted = await third.evaluate(() => !!(window.trame && window.trame.state));
check(mounted, 'the page opened again is live');
say('pool at the end:', JSON.stringify(await pool()));
await browser.close();
process.exit(ok ? 0 : 1);
