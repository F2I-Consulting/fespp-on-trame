/*
 * Probe: the shared components, mounted on their own.
 *
 * It opens the bench (tests/browser/fixtures) outside the application,
 * exercises every component in each of its states, writes one screenshot per
 * component to tests/browser/out/components/ and prints what it found. A
 * component nobody has seen rendered is not shipped.
 *
 *   node fixtures/build.mjs && node probes/components.mjs
 *
 * The bench is served over http on 127.0.0.1 (port FESPP_BENCH_PORT, 8099 by
 * default; its development build on the next port) rather than opened as
 * file://: the clipboard exists only in a secure context, and the export
 * goes through it.
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, '..', 'out');
const site = path.join(out, 'fixture');
const shots = path.join(out, 'components');
const PORT = Number(process.env.FESPP_BENCH_PORT || 8099);

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' };

function serve(dir, port) {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split('?')[0]);
    const file = path.join(dir, rel === '/' ? 'index.html' : rel);
    fs.readFile(file, (err, body) => {
      if (err) { res.writeHead(404); res.end('not found'); return; }
      res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
      res.end(body);
    });
  });
  return new Promise((ok) => server.listen(port, '127.0.0.1', () => ok(server)));
}

// ---------------------------------------------------------------- the journal
const results = [];
function check(what, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  results.push({ ok, what, got, want });
  console.log((ok ? '  ok   ' : '  FAIL ') + what
    + (ok ? '' : '\n         attendu ' + JSON.stringify(want) + '\n         obtenu  ' + JSON.stringify(got)));
  return ok;
}
function note(line) { console.log('  ·    ' + line); }

const cell = (bench, state) => '[data-bench="' + bench + '"] [data-state="' + state + '"]';
const readout = (name) => '[data-readout="' + name + '"]';

async function typeInto(page, selector, text) {
  const field = page.locator(selector);
  await field.fill(text);
  await field.blur();
  await page.waitForTimeout(120);
}

// ------------------------------------------------------------------- the run
const server = await serve(site, PORT);
fs.mkdirSync(shots, { recursive: true });
const browser = await chromium.launch({ headless: !process.env.FESPP_BENCH_HEADED });
const context = await browser.newContext({ viewport: { width: 1500, height: 1000 } });
await context.grantPermissions(['clipboard-read', 'clipboard-write']);
const page = await context.newPage();
const said = [];
page.on('console', (m) => {
  if (m.type() === 'error' || m.type() === 'warning') said.push(m.type() + ': ' + m.text());
});
page.on('pageerror', (e) => said.push('uncaught: ' + e.message));

await page.goto('http://127.0.0.1:' + PORT + '/index.html', { waitUntil: 'load' });
await page.locator('[data-bench="FpPanel"]').waitFor();

console.log('\n--- le banc est monte ------------------------------------------');
const benches = await page.locator('[data-bench]').evaluateAll(
  (els) => els.map((e) => e.getAttribute('data-bench')));
check('les quatorze composants sont sur le banc', benches.length, 14);
note(benches.join(', '));

// A component Vue could not resolve leaves its tag in the DOM verbatim.
const tags = await page.evaluate(() => [...new Set([...document.querySelectorAll('*')]
  .map((e) => e.tagName.toLowerCase()).filter((t) => t.includes('-')))]);
check('aucun tag a tiret dans le DOM (tout est resolu)', tags, []);

console.log('\n--- les defauts voulus, et eux seuls ---------------------------');
const flagged = await page.locator('[data-fp-incomplete]').evaluateAll((els) => els.map((e) => {
  const c = e.closest('[data-state]');
  const b = e.closest('[data-bench]');
  return (b ? b.getAttribute('data-bench') : '?') + '/' + (c ? c.getAttribute('data-state') : '?');
}));
check('data-fp-incomplete porte exactement sur les cellules marquees defect',
  [...new Set(flagged)].sort(),
  ['FpBtn/lower-case', 'FpBtn/no-title', 'FpBtn/title-omitted',
    'FpChip/clickable', 'FpChip/long-warn', 'FpChip/no-title',
    'FpEmpty/gesture-omitted', 'FpEmpty/mute',
    'FpExport/lower-case',
    // an icon name with no drawing behind it, and an mdi NAME, which only
    // the host's v-icon can resolve: both draw the unknown mark and say so
    'FpIcon/mdi-name', 'FpIcon/unknown-name',
    'FpMenu/disabled-mute', 'FpMenu/empty-mute',
    'FpNote/error-mute', 'FpNote/info', 'FpNum/no-title',
    'FpPanel/no-title', 'FpPanel/note-in-controls', 'FpPanel/title-omitted',
    'FpSeg/one', 'FpSelect/disabled-mute', 'FpSelect/wrong-shape',
    'FpTransport/no-unit']);
note('accusation visible, FpEmpty/mute : "'
  + (await page.locator(cell('FpEmpty', 'mute') + ' .fp-empty').innerText()).trim() + '"');
note('accusation visible, FpPanel/no-title : "'
  + (await page.locator(cell('FpPanel', 'no-title') + ' .fp-title').innerText()).trim() + '"');
note('accusation en infobulle, FpBtn/no-title : "'
  + (await page.locator(cell('FpBtn', 'no-title') + ' .fp-btn').getAttribute('title')) + '"');

console.log('\n--- les invariants du harnais, sur le banc ---------------------');
const mute = await page.locator('.fp-btn').evaluateAll((els) => els
  .filter((e) => !(e.getAttribute('title') || '').trim())
  .map((e) => e.textContent.trim()));
check('tout .fp-btn porte une infobulle, desactive compris', mute, []);

const lower = await page.locator('.fp-btn').evaluateAll((els) => els
  .map((e) => e.textContent.trim())
  .filter((t) => t && /^[a-z]/.test(t)));
check('tout libelle de .fp-btn est en Title case (sauf le defect voulu)',
  lower, ['refresh', 'copy csv']);

const empties = await page.locator('.fp-empty').evaluateAll((els) => els.map((e) => ({
  shows: !!(e.getAttribute('data-fp-shows') || '').trim(),
  gesture: !!(e.getAttribute('data-fp-gesture') || '').trim(),
})));
check('tout .fp-empty dit ce qu-il montrerait et le geste (sauf les defects voulus)',
  empties.filter((e) => !e.shows || !e.gesture).length, 2);

const notes = await page.locator('.fp-note').evaluateAll((els) => els.map((e) => ({
  severity: e.getAttribute('data-fp-severity'),
  cross: !!e.querySelector('.fp-chip-btn'),
  next: (e.getAttribute('data-fp-next') || '').trim().length > 0,
})));
check('chaque bande porte sa severite', notes.map((n) => n.severity),
  ['warning', 'error', 'error', 'info', 'warning', 'warning', 'error']);
check('une bande d-erreur nomme la suite a donner (sauf le defect voulu)',
  notes.filter((n) => n.severity === 'error').map((n) => n.next),
  [true, false, true]);
// R10: a band lasts until its cause disappears OR the reader closes it, so
// there is no such thing as a band without a cross.
check('toute bande porte une croix', notes.map((n) => n.cross),
  [true, true, true, true, true, true, true]);

// R16: the one right-click menu stays in its frame (the corner one flips
// back), and a disabled entry keeps a tooltip — its reason, or the
// accusation where the host gave none
const menus = await page.locator('[data-bench="FpMenu"] .fp-menu').evaluateAll((els) => els.map((e) => {
  const f = e.closest('.bench-menu-frame').getBoundingClientRect();
  const r = e.getBoundingClientRect();
  return {
    inside: r.left >= f.left - 1 && r.top >= f.top - 1 && r.right <= f.right + 1 && r.bottom <= f.bottom + 1,
    mute: [...e.querySelectorAll('.fp-menu-item[aria-disabled="true"]')]
      .filter((b) => !(b.getAttribute('title') || '').trim()).length,
  };
}));
check('tout menu reste dans son cadre, celui du coin compris', menus.map((m) => m.inside),
  [true, true, true, true, true]);
check('toute entree desactivee garde une infobulle', menus.map((m) => m.mute), [0, 0, 0, 0, 0]);
const menuItem = (state, label) => page.locator(cell('FpMenu', state) + ' .fp-menu-item', { hasText: label });
// aria-disabled: Playwright waits for it to be enabled; a reader can click it
await menuItem('open', 'Cross-plot').click({ force: true });
check('une entree desactivee ne choisit rien', await page.locator(readout('menu-picks')).innerText(), '0');
await menuItem('open', 'Show distribution').click();
check('une entree choisie est rendue a l-hote',
  [await page.locator(readout('menu-picks')).innerText(), await page.locator(readout('menu-last')).innerText()],
  ['1', 'dist']);
await page.keyboard.press('Escape');
check('Echap demande a chaque menu ouvert de se fermer',
  await page.locator(readout('menu-closes')).innerText(), '5');

// one transport: a step that is off says why, a step moves one position and
// the count follows
const offWhy = await page.locator(cell('FpTransport', 'first') + ' .fp-btn[disabled]').evaluateAll(
  (els) => els.map((e) => e.getAttribute('title')));
check('un pas desactive dit pourquoi', offWhy,
  ['Already at the first realization', 'Already at the first realization']);
await page.locator(cell('FpTransport', 'time') + ' .fp-btn[title="Next time step"]').click();
check('un pas en avant avance d-une position', await page.locator(readout('t-index')).innerText(), '5');
check('le compte suit',
  (await page.locator(cell('FpTransport', 'time') + ' .fp-transport-count').innerText()).trim(), '6 / 12');
// one double slider: two thumbs each, one tick per category, the kept ones lit
check('deux poignees par double curseur',
  await page.locator('[data-bench="FpRange"] .fp-range').evaluateAll(
    (els) => els.map((e) => e.querySelectorAll('input[type=range]').length)), [2, 2]);
check('les categories gardees sont allumees',
  await page.locator(cell('FpRange', 'ticked') + ' .fp-range-tick.fp-range-kept').count(), 2);

const segs = await page.locator('.fp-seg').evaluateAll(
  (els) => els.map((e) => e.querySelectorAll('.fp-segbtn').length));
check('aucun segment de moins de deux lectures (sauf le defect voulu)',
  segs, [2, 4, 1, 2, 3, 3, 3, 3]);

const numbers = await page.locator('input[type=number]').count();
check('aucun input[type=number] sur le banc', numbers, 0);

const right = await page.locator('[data-bench="FpPanel"] .fp-right').evaluateAll(
  (els) => els.map((e) => ({
    first: e.firstElementChild ? e.firstElementChild.className : null,
    last: e.lastElementChild ? e.lastElementChild.textContent.trim() : null,
  })));
check('le resume ouvre le groupe de droite, le bouton d-arbre le ferme',
  right, [{ first: 'fp-chip fp-chip-warn', last: 'T' },
    { first: 'fp-sum', last: 'Refresh' },
    { first: 'fp-btn fp-primary', last: 'Refresh' },
    { first: 'fp-sum', last: 'Copy CSV' }]);

// R10: a band in the row of controls pushes the buttons about. The frame
// cannot refuse what it is handed, but it READS it and says so.
const inBar = await page.locator('[data-bench="FpPanel"] .fp-bar .fp-note').count();
check('une note posee dans la rangee des controles y est bien (le defect voulu)',
  inBar, 1);
const accused = await page.locator(cell('FpPanel', 'note-in-controls')
  + ' .fp-note[data-fp-incomplete]').innerText();
check('et le cadre l-accuse en toutes lettres', /row of controls/.test(accused), true);
note('accusation du cadre : "' + accused.replace(/\s+/g, ' ').trim() + '"');

console.log('\n--- le champ decimal (la raison d-etre de FpNum) ---------------');
await typeInto(page, cell('FpNum', 'plain') + ' .fp-num', '0,25');
check('une virgule tapee est le point decimal',
  (await page.locator(readout('num')).innerText()).trim(), '0.25 - number');
await typeInto(page, cell('FpNum', 'plain') + ' .fp-num', 'abc');
check('ce qui n-est pas un nombre revient a la valeur en vigueur',
  (await page.locator(readout('num')).innerText()).trim(), '0.25 - number');
await typeInto(page, cell('FpNum', 'clamped') + ' .fp-num', '999');
check('la valeur est bornee a la remise',
  (await page.locator(readout('numClamp')).innerText()).trim(), '100 - number');
await typeInto(page, cell('FpNum', 'integer') + ' .fp-num', '3,7');
check('un champ entier arrondit a la remise',
  (await page.locator(readout('numInt')).innerText()).trim(), '4 - number');
await typeInto(page, cell('FpNum', 'nullable') + ' .fp-num', '');
check('un champ vide qui accepte le vide dit "aucun"',
  (await page.locator(readout('numNull')).innerText()).trim(), 'null');
await page.locator(cell('FpNum', 'stepper') + ' .fp-btn').last().click();
await page.waitForTimeout(80);
check('le pas monte d-un cran',
  (await page.locator(readout('numStep')).innerText()).trim(), '6 - number');
const atMax = await page.locator(cell('FpNum', 'stepper-at-max') + ' .fp-btn')
  .evaluateAll((els) => els.map((e) => e.disabled));
check('a la borne, le pas qui la depasserait est inerte', atMax, [false, true]);
const shownWidth = await page.locator(cell('FpNum', 'disabled') + ' .fp-num')
  .evaluate((e) => e.value);
check('un champ desactive montre quand meme sa valeur', shownWidth, '12');

console.log('\n--- le select rend le type qu-on lui a donne -------------------');
await page.locator(cell('FpSelect', 'labelled') + ' .fp-sel').selectOption('50');
await page.waitForTimeout(80);
check('une option numerique revient en Number',
  (await page.locator(readout('selNum')).innerText()).trim(), '50 - number');
const mandatory = await page.locator(cell('FpSelect', 'mandatory') + ' option')
  .evaluateAll((els) => els.map((e) => e.disabled));
check('le placeholder obligatoire ne peut pas etre rechoisi', mandatory,
  [true, false, false, false]);
note('infobulle du select desactive avec motif : "'
  + await page.locator(cell('FpSelect', 'disabled') + ' .fp-sel').getAttribute('title') + '"');
note('infobulle du select desactive sans motif : "'
  + await page.locator(cell('FpSelect', 'disabled-mute') + ' .fp-sel').getAttribute('title') + '"');
const perOption = await page.locator(cell('FpSelect', 'disabled-option') + ' option')
  .evaluateAll((els) => els.map((e) => ({
    label: e.textContent.trim(), off: e.disabled, why: e.getAttribute('title') })));
check('une option marquee disabled ne peut pas etre choisie', perOption.map((o) => o.off),
  [false, false, true]);
check('et elle dit pourquoi', perOption[2].why, 'IjkGrid is not loaded in this view');
const blank = await page.locator(cell('FpSelect', 'wrong-shape') + ' option')
  .evaluateAll((els) => els.map((e) => e.textContent.trim()));
check('la forme d-option de <fp-seg> ne rend plus des lignes vides',
  [...new Set(blank)], ['(this option has no words — a defect)']);

console.log('\n--- le segment ------------------------------------------------');
await page.locator(cell('FpSeg', 'four') + ' .fp-segbtn').nth(2).click();
await page.waitForTimeout(80);
check('cliquer une lecture la choisit',
  (await page.locator(readout('seg4')).innerText()).trim(), 'p90');
const on = await page.locator(cell('FpSeg', 'four') + ' .fp-segbtn.fp-on').innerText();
check('et elle est la seule allumee', on.trim(), 'P90');

console.log('\n--- la note ne s-evapore pas ----------------------------------');
await page.locator(cell('FpNote', 'warning') + ' .fp-chip-btn').click();
await page.waitForTimeout(80);
check('la croix ferme la bande',
  await page.locator(cell('FpNote', 'warning') + ' .fp-note').count(), 0);
check('et le fermeture est dite a l-hote',
  (await page.locator(readout('closed')).innerText()).trim(), '1');
await page.locator('[data-bench="FpNote"] .bench-note .fp-btn').click();
await page.waitForTimeout(80);
check('un texte nouveau est une note nouvelle : elle revient',
  await page.locator(cell('FpNote', 'warning') + ' .fp-note').count(), 1);

console.log('\n--- un seul formulaire d-histogramme --------------------------');
const histFull = cell('FpHistOptions', 'full');
const histCompact = cell('FpHistOptions', 'compact');
const histCounts = async (state) => [
  await page.locator(state + ' .fp-seg').count(), await page.locator(state + ' select').count()];
check('la forme pleine : deux segments, aucune liste', await histCounts(histFull), [2, 0]);
check('la forme compacte : deux listes, aucun segment', await histCounts(histCompact), [0, 2]);
const histWords = async (state) => (await page.locator(state + ' label').allInnerTexts()).map((t) => t.trim());
check('le slot de l-hote se tient entre Log Y et Cumulative', await histWords(histFull),
  ['Bins', 'Log Y', 'Stats', 'Cumulative']);
check('les memes mots dans la forme compacte', await histWords(histCompact), ['Bins', 'Log Y', 'Cumulative']);
const histTips = async (state) => [...new Set(await page.locator(state + ' [title]').evaluateAll(
  (els) => els.map((e) => e.getAttribute('title'))))].filter((t) => !/only this host/.test(t)).sort();
const histOptionTips = async (state) => [...new Set(await page.locator(state + ' .fp-segbtn, ' + state + ' option')
  .evaluateAll((els) => els.map((e) => e.getAttribute('title'))))].sort();
check('les memes infobulles sur les choix des deux formes',
  await histOptionTips(histFull), await histOptionTips(histCompact));
note('infobulles de la forme pleine : ' + (await histTips(histFull)).join(' | '));
check('sans valeurs : les defauts, jamais un champ vide',
  await page.locator(cell('FpHistOptions', 'empty') + ' .fp-num').inputValue(), '50');
await page.locator(histFull + ' .fp-segbtn', { hasText: /^Line$/ }).click();
await page.waitForTimeout(80);
check('un choix est rendu a l-hote par set [nom, valeur]',
  (await page.locator(readout('hist-last')).innerText()).trim(), 'mode=line');
check('et l-autre forme le lit', await page.locator(histCompact + ' select').first().inputValue(), 'line');
await page.locator(histCompact + ' select').last().selectOption('density');
await page.waitForTimeout(80);
check('la forme compacte rend le meme evenement',
  (await page.locator(readout('hist-last')).innerText()).trim(), 'norm=density');
await typeInto(page, histFull + ' .fp-num', '999');
check('les classes sont bornees a 500',
  (await page.locator(readout('hist-last')).innerText()).trim(), 'nbins=500');
await page.locator(histFull + ' label', { hasText: 'Stats' }).locator('input').click();
await page.waitForTimeout(80);
check('l-option de l-hote reste la sienne',
  (await page.locator(readout('hist-last')).innerText()).trim(), 'show_stats=true');

console.log('\n--- l-export dit lequel des deux il a fait ---------------------');
const ready = page.locator(cell('FpExport', 'ready') + ' .fp-btn');
check('au repos, le mot de la charte', (await ready.innerText()).trim(), 'Copy CSV');
await ready.click();
await page.waitForTimeout(200);
const outcome = (await ready.innerText()).trim();
check('apres le clic, il dit ce qu-il a fait', ['Copied', 'Downloaded'].includes(outcome), true);
note('il a dit : ' + outcome);
const clip = await page.evaluate(() => navigator.clipboard.readText()).catch(() => '');
note('presse-papiers : ' + JSON.stringify(clip.split('\n')[0] + ' | ' + (clip.split('\n')[1] || '')));
await page.locator('[data-bench="FpExport"]').screenshot(
  { path: path.join(shots, 'FpExport-said.png') });
const failing = page.locator(cell('FpExport', 'failing') + ' .fp-btn');
await failing.click();
await page.waitForTimeout(200);
check('un echec est dit, pas avale',
  (await failing.innerText()).trim(), 'Export failed — the table could not be written');
await page.waitForTimeout(2200);
check('le mot revient apres coup', (await ready.innerText()).trim(), 'Copy CSV');

console.log('\n--- l-etat occupe ---------------------------------------------');
const busyBtn = page.locator(cell('FpBtn', 'busy') + ' .fp-btn');
check('un bouton occupe est desactive', await busyBtn.isDisabled(), true);
const busyMarked = await page.locator('[data-fp-busy]').evaluateAll(
  (els) => els.map((e) => e.textContent.trim() + (e.disabled ? ' (inerte)' : '')));
check('et il porte data-fp-busy, que le harnais relit apres coup',
  busyMarked, ['Refresh (inerte)', 'Refresh (inerte)']);
check('et garde le mot sur lequel on a clique', (await busyBtn.innerText()).trim(), 'Refresh');
const busyPanel = page.locator('[data-bench="FpPanel"] [data-state="busy"]');
check('le panneau occupe porte la barre du kit',
  await busyPanel.locator('.fp-busy').count(), 1);
check('le resume le dit',
  (await busyPanel.locator('.fp-sum').innerText()).trim(), '8 of 11 zones · recomputing…');
check('et le corps garde ce qu-il montrait',
  await busyPanel.locator('.fp-table tbody tr').count(), 3);

console.log('\n--- la puce n-est pas un bouton -------------------------------');
const before = (await page.locator(readout('clicks')).innerText()).trim();
await page.locator(cell('FpChip', 'clickable') + ' .fp-chip').click();
await page.waitForTimeout(80);
check('un @click pose sur une puce n-est pas lie',
  (await page.locator(readout('clicks')).innerText()).trim(), before);
note('infobulle : "'
  + await page.locator(cell('FpChip', 'clickable') + ' .fp-chip').getAttribute('title') + '"');

console.log('\n--- la puce ellipsee garde son texte entier --------------------');
const chip = page.locator(cell('FpChip', 'ellipsed') + ' .fp-chip');
const geom = await chip.locator('.fp-chip-text').evaluate(
  (e) => ({ scroll: e.scrollWidth, client: e.clientWidth }));
check('elle est bien coupee a l-ecran', geom.scroll > geom.client, true);
const full = await chip.getAttribute('title');
check('et le texte entier est dans l-infobulle', full.length > 40, true);
note('infobulle : "' + full + '"');

console.log('\n--- les captures ----------------------------------------------');
for (const b of benches) {
  await page.locator('[data-bench="' + b + '"]').screenshot({ path: path.join(shots, b + '.png') });
  console.log('  ecrit ' + path.join(shots, b + '.png'));
}
await page.screenshot({ path: path.join(shots, 'bench.png'), fullPage: true });
console.log('  ecrit ' + path.join(shots, 'bench.png'));

console.log('\n--- ce que la console a dit -----------------------------------');
check('la console est restee muette (build de production)', said, []);

/*
 * The same bench, built with the development Vue, where the prop validators
 * run. It is the first of the three holds of the "required prop" rule (the
 * declaration, the data-fp-* attribute, the harness assertion): the one the
 * served page, a production build, cannot show.
 */
console.log('\n--- ce que les validateurs disent en build de developpement ----');
const devSite = path.join(out, 'fixture-dev');
const devServer = await serve(devSite, PORT + 1);
const devPage = await context.newPage();
const dev = [];
devPage.on('console', (m) => { if (m.type() === 'warning' || m.type() === 'error') dev.push(m.text()); });
await devPage.goto('http://127.0.0.1:' + (PORT + 1) + '/index.html', { waitUntil: 'load' });
await devPage.locator('[data-bench="FpPanel"]').waitFor();
await devPage.waitForTimeout(500);
const kinds = [...new Set(dev.map((t) => (t.split('\n')[0] || '').trim()))];
kinds.forEach((k) => console.log('  ·    ' + k.slice(0, 160)));
const omitted = [...new Set(kinds.filter((k) => /Missing required prop/.test(k))
  .map((k) => (k.match(/"([^"]+)"/) || [])[1]))].sort();
note('validateurs : ' + kinds.filter((k) => /custom validator/.test(k)).length
  + ' prop(s) refusee(s) par un validateur');
check('une prop requise OMISE est refusee par la declaration', omitted,
  ['gesture', 'title', 'unit']);
await devPage.close();
devServer.close();

// ------------------------------------------------------------------ verdict
await context.close();
await browser.close();
server.close();

const bad = results.filter((r) => !r.ok);
console.log('\n=== ' + (results.length - bad.length) + ' / ' + results.length
  + ' constats tenus, captures dans ' + shots);
if (bad.length) {
  bad.forEach((r) => console.log('  FAIL ' + r.what));
  process.exitCode = 1;
}
