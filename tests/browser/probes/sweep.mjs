/*
 * Probe: a sweep of the cards and the panels.
 *
 * It opens every card of the 3D view's toolbar, then every panel of the top
 * bar, and prints for each its size, its number of elements, its text and
 * the hyphenated tags left in the DOM: the raw material of a smoke test,
 * what "empty" means panel by panel, before it becomes an assertion.
 *
 *   node probes/sweep.mjs [url]
 *
 * The URL defaults to FESPP_SMOKE_URL, then to the instance of
 * tests\browser\instance.ps1, started with a file open (-Epc): without
 * data, half the cards are missing from the bar (they need an active grid).
 */
import { chromium } from '@playwright/test';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://localhost:8095/index.html';
const t0 = Date.now();
const ms = () => String(Date.now() - t0).padStart(6);

const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1800, height: 1100 } })).newPage();
const erreurs = [];
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') erreurs.push(ms() + ' ' + m.type() + ' :: ' + m.text().replace(/\s+/g, ' ').slice(0, 250)); });
page.on('pageerror', (e) => erreurs.push(ms() + ' pageerror :: ' + e.message.replace(/\s+/g, ' ').slice(0, 250)));

await page.goto(URL);
await page.waitForSelector('.dv-tab', { timeout: 90000 });
await page.waitForFunction(() => {
  const e = document.querySelector('.fdx');
  return e && e.querySelector('.tn-row');
}, null, { timeout: 120000 });
console.log(ms(), 'donnees chargees');

// Expand the tree, then tick a property (the tree's last row): several cards
// of the bar (Slicers, Volumetrics) only appear once a grid is active.
for (let i = 0; i < 12; i++) {
  const n = await page.evaluate(() => {
    const fermes = [...document.querySelectorAll('.tn-caret')].filter((e) => e.textContent.trim() === '▸');
    fermes.forEach((e) => e.click());
    return fermes.length;
  });
  if (!n) break;
  await page.waitForTimeout(500);
}
const propriete = page.locator('.tn-row').filter({ has: page.locator('.tn-title') }).last();
await propriete.locator('.tn-check').click();
await page.waitForTimeout(8000);
console.log(ms(), 'une propriete chargee, canvas =', await page.locator('canvas').count());

const cartes = () => page.evaluate(() => [...document.querySelectorAll('.fc')]
  .filter((c) => c.offsetParent !== null)
  .map((c) => {
    const corps = c.querySelector('.fc-body');
    const r = corps ? corps.getBoundingClientRect() : { height: 0 };
    return {
      titre: (c.querySelector('.fc-title') || {}).innerText || '',
      hauteur: Math.round(r.height),
      elements: corps ? corps.querySelectorAll('*').length : -1,
      texte: corps ? (corps.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60) : '',
    };
  }));

const tagsATiret = () => page.evaluate(() => [...new Set([...document.querySelectorAll('*')]
  .map((e) => e.tagName.toLowerCase()).filter((t) => t.includes('-')))]);

console.log('\n=== cartes de la barre d outils de la vue ===');
const outils = await page.evaluate(() => [...document.querySelectorAll('.tb .tb-btn')].map((e) => e.getAttribute('title')));
for (const titre of outils) {
  const bouton = page.locator(`.tb .tb-btn[title=${JSON.stringify(titre)}]`);
  if (await bouton.count() === 0) { console.log(ms(), 'DISPARU', JSON.stringify(titre)); continue; }
  await bouton.first().click();
  await page.waitForTimeout(1000);
  const ouverte = await page.evaluate((t) => {
    const b = document.querySelector(`.tb .tb-btn[title="${t.replace(/"/g, '\\"')}"]`);
    return !!(b && b.classList.contains('active'));
  }, titre);
  const t = await tagsATiret();
  console.log(ms(), ouverte ? 'OUVERT' : 'FERME ', JSON.stringify(titre).slice(0, 46),
    '|', JSON.stringify(await cartes()), t.length ? '| TAGS NON RESOLUS ' + JSON.stringify(t) : '');
}

console.log('\n=== panneaux de la barre du haut ===');
const boutons = await page.evaluate(() => [...document.querySelectorAll('header button[title]')]
  .map((e) => e.getAttribute('title')).filter((t) => !/Reload/.test(t)));
for (const titre of boutons) {
  await page.click(`header button[title=${JSON.stringify(titre)}]`);
  await page.waitForTimeout(2500);
  // A hidden dockview panel has zero height: only the ACTIVE panel can be
  // measured, so the one just brought to the front is the one read.
  const actif = await page.evaluate(() => [...document.querySelectorAll('.dv-vue-part')]
    .filter((e) => e.getBoundingClientRect().height > 0)
    .map((e) => ({
      hauteur: Math.round(e.getBoundingClientRect().height),
      elements: e.querySelectorAll('*').length,
      texte: (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 70),
    })));
  const t = await tagsATiret();
  console.log(ms(), JSON.stringify(titre.split('—')[0].trim()), '|', JSON.stringify(actif),
    t.length ? '| TAGS NON RESOLUS ' + JSON.stringify(t) : '');
}

console.log('\n--- console ---');
[...new Set(erreurs)].forEach((e) => console.log(e));
console.log('duree', ms(), 'ms');
await browser.close();
