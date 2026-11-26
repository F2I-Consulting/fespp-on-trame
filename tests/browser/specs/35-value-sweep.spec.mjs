/*
 * Scenario: the value player of the Thresholds card (the PO, 27/10: "a player
 * that shows only the current value and hides everything else", "the
 * movement must be fluid").
 *
 * Gated: "▶ Sweep" in the add row puts a threshold on the property and turns
 * it into a player; the shown value follows the slider WHILE it is dragged,
 * not only on release; play advances on its own; the entry's Sweep button
 * ends it and the entry gets its range back.
 * Printed: the images a second the browser receives while the slider is
 * dragged and while it plays — the machine and the grid decide them; on a
 * big grid run it with -Reuse on an instance that opened it (see
 * 25-fluidity for the recipe).
 */
import {
  test, expect, M, DATASET, ensureProperty, focusRenderView, openCards, state,
  viewId, waitUntil,
} from '../lib/app.mjs';

// The Thresholds card became the Property slicer on 29/10, its player the slicer's: to write again.
test.fixme('the value player shows one value at a time and follows the slider live', async ({ app }) => {
  const { page, note } = app;
  const prop = DATASET.properties[0];
  await ensureProperty(app, prop);
  await focusRenderView(page);
  const vid = await viewId(page);
  const key = 'ui_threshold_sweep__' + vid;
  const sweep = async () => (await state(page, key)) || {};

  const bar = page.locator(M.toolbar + ':visible').first();
  if (!(await openCards(page)).some((c) => c.title.startsWith('Thresholds'))) {
    await bar.locator('.tb-btn[title="Thresholds"]').click();
  }
  await waitUntil(app, async () => (await openCards(page)).some((c) => c.title.startsWith('Thresholds')),
    { what: 'the Thresholds card open' });
  const card = page.locator('.fth:visible').first();

  // the property in the add row, then the player at once
  const pick = card.locator('.fth-add select').first();
  const value = await pick.evaluate((el, n) => {
    const o = [...el.options].find((x) => x.value && (x.value === n || x.textContent.trim().startsWith(n)));
    return o ? o.value : null;
  }, prop);
  expect(value, 'the add row offers ' + prop).not.toBeNull();
  await pick.selectOption(value);
  await card.getByRole('button', { name: '▶ Sweep', exact: true }).click();
  await waitUntil(app, async () => !!(await sweep()).entry, { what: 'a swept entry' });
  const s0 = await sweep();
  note('swept: ' + s0.kind + ', ' + s0.count + ' steps, first ' + s0.label);
  expect(s0.count, 'the player has steps').toBeGreaterThan(1);
  const slider = card.locator('.fth-sweep .fp-transport-slider');
  await expect(slider, 'the player replaces the range row').toBeVisible();

  // every image the client shows goes through createObjectURL
  await page.evaluate(() => {
    const orig = URL.createObjectURL.bind(URL);
    window.__frames = [];
    URL.createObjectURL = (b) => {
      if (b && b.type && String(b.type).startsWith('image/')) window.__frames.push(performance.now());
      return orig(b);
    };
  });
  const framesSince = (t0) => page.evaluate((t) => window.__frames.filter((x) => x >= t).length, t0);

  // the slider dragged: input events only, the release at the end
  const t0 = await page.evaluate(() => performance.now());
  const seen = [];
  const n = 20;
  for (let i = 1; i <= n; i++) {
    const pos = Math.round(i * (s0.count - 1) / n);
    await slider.evaluate((el, v) => {
      el.value = String(v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }, pos);
    await page.waitForTimeout(60);
    seen.push((await sweep()).index);
  }
  const t1 = await page.evaluate(() => performance.now());
  const dragFrames = await framesSince(t0);
  note('drag: ' + n + ' positions in ' + Math.round(t1 - t0) + ' ms, ' + new Set(seen).size
       + ' distinct steps shown before the release, '
       + (dragFrames / ((t1 - t0) / 1000)).toFixed(1) + ' images/s');
  expect(new Set(seen).size, 'the shown value follows the slider while it is dragged').toBeGreaterThan(3);
  await slider.evaluate((el) => el.dispatchEvent(new Event('change', { bubbles: true })));
  await waitUntil(app, async () => (await sweep()).index === s0.count - 1,
    { what: 'the last step after the release', timeout: 10000 });

  // play: it advances by itself
  await card.locator('.fth-sweep button[title="Play the ' + (s0.kind === 'Continuous' ? 'positions'
    : s0.kind === 'Categorical' ? 'categories' : 'values') + ' in a loop"]').click();
  await waitUntil(app, async () => !!(await sweep()).playing, { what: 'playing', timeout: 5000 });
  const p0 = await page.evaluate(() => performance.now());
  const i0 = (await sweep()).index;
  await page.waitForTimeout(2000);
  const i1 = (await sweep()).index;
  const playFrames = await framesSince(p0);
  note('play: ' + playFrames / 2 + ' images/s at ×' + (await sweep()).speed + ', index ' + i0 + ' -> ' + i1);
  expect(i1, 'play advances').not.toBe(i0);
  // the fastest pace: what the machine and the grid really deliver
  const rates = (await sweep()).rates || [];
  if (rates.length) {
    const top = Math.max(...rates);
    await card.locator('.fth-sweep select.fp-transport-speed').selectOption(String(top));
    await waitUntil(app, async () => Number((await sweep()).speed) === top, { what: 'the top speed', timeout: 5000 });
    const q0 = await page.evaluate(() => performance.now());
    const m0 = (await sweep()).moves;
    await page.waitForTimeout(2000);
    const m1 = (await sweep()).moves;
    note('play: ' + (await framesSince(q0)) / 2 + ' images/s at ×' + top
         + ' (' + (m1 - m0) / 2 + ' steps/s on the server)');
  }
  await card.locator('.fth-sweep button[title="Stop playing"]').click();
  await waitUntil(app, async () => !(await sweep()).playing, { what: 'stopped', timeout: 5000 });

  // the entry's own Sweep button ends it: the range is the entry's again
  await card.getByRole('button', { name: 'Sweep', exact: true }).click();
  await waitUntil(app, async () => !(await sweep()).entry, { what: 'the sweep ended' });
  await expect(card.locator('.fth-sweep'), 'the range row is back').toHaveCount(0);
  await expect(card.locator('.fth-range').first()).toBeVisible();
});
