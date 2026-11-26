/*
 * Probe: the negative controls.
 *
 * A smoke test is worth something only if it fails when it must. This probe
 * produces, in the page the application serves, the four faults the harness
 * has to catch, and prints the signal each one gives. It changes no file:
 * the missing bundle is simulated by intercepting its request, the three
 * others by small Vue apps mounted with the page's own Vue.
 *
 *   node probes/signals.mjs [url]
 *
 * The URL defaults to FESPP_SMOKE_URL, then to the instance of
 * tests\browser\instance.ps1.
 */
import { chromium } from '@playwright/test';

const URL = process.argv[2] || process.env.FESPP_SMOKE_URL || 'http://localhost:8095/index.html';

// ---------------------------------------------------------------- control 1
// A widget's bundle never arrives (missing from www_modules, a Dockerfile
// glob forgotten, the widget's build not run again).
{
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext()).newPage();
  const vus = [];
  page.on('console', (m) => { if (m.type() === 'error') vus.push('console.error :: ' + m.text().slice(0, 200)); });
  page.on('pageerror', (e) => vus.push('pageerror :: ' + e.message.slice(0, 200)));
  await page.route('**/trame_fespp_tree.umd.js', (r) =>
    r.fulfill({ status: 200, contentType: 'application/javascript', body: '/* bundle vide */' }));
  await page.goto(URL);
  await page.waitForTimeout(9000);
  const s = await page.evaluate(() => ({
    texte: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 60),
    onglets: document.querySelectorAll('.dv-tab').length,
  }));
  console.log('TEMOIN 1 — bundle de widget manquant');
  console.log('  etat  :', JSON.stringify(s));
  console.log('  signal:', JSON.stringify([...new Set(vus)]));
  await browser.close();
}

// The next three share one healthy page.
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext()).newPage();
const vus = [];
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') vus.push('console.' + m.type() + ' :: ' + m.text().replace(/\s+/g, ' ').slice(0, 200)); });
page.on('pageerror', (e) => vus.push('pageerror :: ' + e.message.replace(/\s+/g, ' ').slice(0, 200)));
await page.goto(URL);
await page.waitForSelector('.dv-tab', { timeout: 90000 });
await page.waitForTimeout(1500);

// ---------------------------------------------------------------- control 2
// A rename leaves an undefined variable in a component's render.
{
  const avant = vus.length;
  const dom = await page.evaluate(() => {
    const hote = document.createElement('div');
    hote.id = 'temoin2';
    document.body.appendChild(hote);
    const Casse = { name: 'ArbreCasse', render() { return window.Vue.h('div', null, nodesRenamed.length); } };
    window.Vue.createApp({ components: { Casse }, template: '<div><Casse/></div>' }).mount(hote);
    return { html: hote.innerHTML.slice(0, 120), hauteur: hote.getBoundingClientRect().height };
  });
  await page.waitForTimeout(300);
  console.log('\nTEMOIN 2 — variable indefinie dans un composant');
  console.log('  dom   :', JSON.stringify(dom));
  console.log('  signal:', JSON.stringify(vus.slice(avant)));
}

// ---------------------------------------------------------------- control 3
// A list serialised as JSON puts double quotes inside a template attribute
// that is itself delimited by double quotes.
{
  const avant = vus.length;
  const leve = await page.evaluate(() => {
    const hote = document.createElement('div');
    hote.id = 'temoin3';
    document.body.appendChild(hote);
    window.Vue.createApp({ template: '<div :items="[{"key": "a"}]">contenu</div>' }).mount(hote);
    return null;
  }).catch((e) => String(e).replace(/\s+/g, ' ').slice(0, 200));
  await page.waitForTimeout(300);
  const dom = await page.evaluate(() => {
    const e = document.getElementById('temoin3');
    return { html: JSON.stringify(e.innerHTML), hauteur: e.getBoundingClientRect().height };
  });
  console.log('\nTEMOIN 3 — gabarit casse par un guillemet double');
  console.log('  dom   :', JSON.stringify(dom));
  console.log('  signal:', JSON.stringify(leve || vus.slice(avant)));
}

// ---------------------------------------------------------------- control 4
// A component Vue does not resolve: the production build served here gives
// no warning, the only signal is the tag left as is in the DOM.
{
  const avant = vus.length;
  const dom = await page.evaluate(() => {
    const hote = document.createElement('div');
    hote.id = 'temoin4';
    document.body.appendChild(hote);
    window.Vue.createApp({ template: '<div><data-explorer-tree-inconnu :a="1"/></div>' }).mount(hote);
    return {
      html: hote.innerHTML.slice(0, 120),
      tagsATiret: [...document.querySelectorAll('#temoin4 *')].map((e) => e.tagName.toLowerCase()).filter((t) => t.includes('-')),
    };
  });
  await page.waitForTimeout(300);
  console.log('\nTEMOIN 4 — composant non resolu');
  console.log('  dom   :', JSON.stringify(dom));
  console.log('  signal:', JSON.stringify(vus.slice(avant)), '(aucune console attendue : build de production)');
}

console.log('\nversion de Vue servie :', await page.evaluate(() => window.Vue.version));
await browser.close();
