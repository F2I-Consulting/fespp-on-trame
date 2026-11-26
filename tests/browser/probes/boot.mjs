/*
 * Probe: the client-side startup sequence, timed.
 *
 * It asserts nothing: it prints what the browser actually does, so that the
 * smoke test rests on observed markers rather than assumed ones: what the
 * application asks the network for, when the websocket opens, when Vue
 * mounts, when the first 3D view exists, and whether the console says
 * anything along the way.
 *
 *   node probes/boot.mjs [url]
 *
 * The URL defaults to FESPP_SMOKE_URL, then to the instance of
 * tests\browser\instance.ps1.
 */
import { chromium } from '@playwright/test';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://localhost:8095/index.html';
const t0 = Date.now();
const ms = () => String(Date.now() - t0).padStart(6);

const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();

page.on('console', (m) => {
  if (m.type() === 'error' || m.type() === 'warning') {
    console.log(ms(), 'CONSOLE', m.type(), m.text().replace(/\s+/g, ' ').slice(0, 300));
  }
});
page.on('pageerror', (e) => console.log(ms(), 'PAGEERROR', e.message.replace(/\s+/g, ' ').slice(0, 300)));
page.on('requestfailed', (r) => console.log(ms(), 'REQUETE ECHOUEE', r.url().slice(0, 120)));
page.on('request', (r) => {
  // the widget bundles are many and all alike: only the requests that shape
  // the startup are traced
  const u = r.url();
  if (/index\.html|loading\.tpl|\/paraview\/|vue\.global/.test(u)) console.log(ms(), 'REQ ', r.method(), u.slice(0, 100));
});
page.on('websocket', (ws) => console.log(ms(), 'WEBSOCKET', ws.url().slice(0, 110)));

await page.goto(URL, { waitUntil: 'domcontentloaded' });
console.log(ms(), 'domcontentloaded');

const etat = () => page.evaluate(() => {
  const app = document.getElementById('app');
  return {
    vueMonte: !!(app && app.__vue_app__),
    texte: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 90),
    onglets: [...document.querySelectorAll('.dv-tab')].map((e) => e.innerText.trim()),
    canvas: document.querySelectorAll('canvas').length,
    arbre: document.querySelectorAll('.fdx').length,
    // a component Vue could not resolve leaves its tag as is in the DOM: in
    // this application no hyphenated tag may remain
    tagsATiret: [...new Set([...document.querySelectorAll('*')]
      .map((e) => e.tagName.toLowerCase()).filter((t) => t.includes('-')))],
  };
});

let precedent = '';
for (let i = 0; i < 40; i++) {
  const s = await etat();
  const cle = JSON.stringify(s);
  if (cle !== precedent) { console.log(ms(), 'DOM', cle); precedent = cle; }
  await page.waitForTimeout(400);
}

await browser.close();
