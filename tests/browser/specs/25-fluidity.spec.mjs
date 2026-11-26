/*
 * Scenario: what a camera drag FEELS like, measured where the reader sits.
 *
 * Every server-side probe times a render, a readback, an encode. None of them
 * says how many images a second the browser really receives while the mouse
 * is down, how heavy they are, or how long after the release the sharp frame
 * lands — and that is the whole of "fluid" for the person dragging. This
 * hooks the one place every delivered frame goes through in the client
 * (URL.createObjectURL of an image blob), drags for a few seconds, and
 * reports: images a second during the drag, kilobytes and resolution of
 * those images, the megabits a second they add up to, and the delay before
 * the full-resolution still after the release.
 *
 * Numbers are printed, not gated: the machine, the backend (GPU or software)
 * and the file decide them. What IS gated: frames arrive while dragging, and
 * a still frame at the resting resolution follows the release — the
 * "stuck compressed after the mouse is released" defect class.
 *
 * Meant to be run against a GPU instance with a big grid open, for example
 * (the port and container name are any free pair):
 *   .\tests\browser\instance.ps1 -Gpu -Port 8096 -Name fespp_fluid `
 *       -Epc Volve_Demo_Reservoir_Grid_Depth.epc
 *   $env:FESPP_SMOKE_PROPS='Fluids'; .\test-browser.ps1 -Scenario fluidity -Reuse -Port 8096 -Name fespp_fluid
 * In the plain suite it runs LAST, on whatever the earlier scenarios left on
 * screen, and only checks the mechanics.
 */
import {
  test, expect, M, DATASET, dataTree, ensureData, ensureProperty, expandTree,
  focusRenderView, state, treeRow, waitUntil,
} from '../lib/app.mjs';

const DRAG_MS = 3000;
const RX = 120;
const RY = 80;

test('a camera drag streams frames, and the release brings the sharp one back', async ({ app }) => {
  const { page, note } = app;
  // an instance that opens a file at boot may still be reading it when this
  // starts: give it ninety seconds before falling back to the smoke import
  await waitUntil(app, () => state(page, 'ui_has_data'),
    { what: 'data at boot', timeout: 90000 }).catch(() => note('no data at boot'));
  await ensureData(app);
  await focusRenderView(page);
  // Late in the suite several files are in and the tree has more than one
  // row by the smoke property's name: then the view is dragged as it is.
  // Alone, or on an instance with one file open, the property is ticked so
  // that the drag moves a coloured grid.
  const title = DATASET.properties[0];
  const tree = dataTree(page);
  await expandTree(tree);
  const rows = await treeRow(tree, title).count();
  if (rows === 1) await ensureProperty(app, title);
  else note(rows + ' rows titled ' + title + ' — dragging the view as it is');
  await page.waitForTimeout(1500);

  // The streamed frame of the 3D view in front: the biggest <img> ON SCREEN.
  // A 3D view behind another tab keeps its <img> in the DOM, its box kept
  // and hidden (the dock's layer of a hidden panel), and naturalWidth alone
  // would pick it.
  await page.evaluate(() => {
    window.__frameImg = () => Array.from(document.querySelectorAll('img'))
      .filter((i) => i.naturalWidth > 50 && i.naturalHeight > 50)
      .filter((i) => getComputedStyle(i).visibility !== 'hidden')
      .map((i) => [i, i.getBoundingClientRect()])
      .filter(([, r]) => r.width > 50 && r.height > 50)
      .sort((a, b) => b[1].width * b[1].height - a[1].width * a[1].height)
      .map(([i]) => i)[0];
  });
  const before = await page.evaluate(() => {
    const im = window.__frameImg();
    return im ? { w: im.naturalWidth, h: im.naturalHeight } : null;
  });
  expect(before, 'a streamed frame is on screen before the drag').not.toBeNull();
  note('resting frame ' + before.w + 'x' + before.h);

  // Hook the frames: every image the client shows goes through createObjectURL.
  await page.evaluate(() => {
    const orig = URL.createObjectURL.bind(URL);
    window.__frames = { t: [], bytes: [], dims: new Set() };
    URL.createObjectURL = (b) => {
      if (b && b.type && String(b.type).startsWith('image/')) {
        window.__frames.t.push(performance.now());
        window.__frames.bytes.push(b.size);
      }
      return orig(b);
    };
    window.__sampler = setInterval(() => {
      const im = window.__frameImg();
      if (im) window.__frames.dims.add(im.naturalWidth + 'x' + im.naturalHeight);
    }, 30);
  });

  // A spot of the 3D view that no floating card covers, for the whole course
  // of the gesture (late in the suite, cards opened by earlier scenarios sit
  // over the middle of the view, and a drag that starts on a card selects
  // its text instead of turning the camera). What is under the pointer must
  // not be a card, a scrim, a toolbar or a tab row, at the centre and at the
  // four corners of the circle the hand will draw.
  const findSpot = () => page.evaluate(({ RX, RY }) => {
    const im = window.__frameImg();
    if (!im) return { covered: ['no frame image'] };
    const r = im.getBoundingClientRect();
    const seen = [];
    const free = (x, y) => {
      const el = document.elementFromPoint(x, y);
      const covered = !el
        || !!el.closest('.fc, .fp-scrim, .tb, .dv-tabs-and-actions-container, [role="dialog"]');
      if (covered) {
        seen.push(Math.round(x) + ',' + Math.round(y) + ': '
          + (el ? el.tagName + '.' + String(el.className).split(' ')[0] : 'nothing'));
      }
      return !covered;
    };
    const cands = [[0.5, 0.5], [0.5, 0.78], [0.7, 0.72], [0.3, 0.72], [0.72, 0.4], [0.28, 0.4], [0.5, 0.25]];
    for (const [fx, fy] of cands) {
      const x = r.left + r.width * fx;
      const y = r.top + r.height * fy;
      if ([[0, 0], [RX, RY], [-RX, RY], [RX, -RY], [-RX, -RY]].every(([dx, dy]) => free(x + dx, y + dy))) {
        return { x, y, at: Math.round(fx * 100) + '%,' + Math.round(fy * 100) + '% of the view' };
      }
    }
    return { covered: seen.slice(0, 12) };
  }, { RX, RY });
  let spot = await findSpot();
  // late in the suite the views are narrow and their trees stand over them: closed for the drag
  const trees = page.locator(M.card + ':visible').filter({ has: page.locator(M.cardTitle, { hasText: /^Reservoir$/ }) });
  const closedTrees = spot.x ? 0 : await trees.count();
  if (closedTrees) {
    for (let n = closedTrees; n > 0; n--) {
      await trees.first().locator('.fc-close').click();
      await expect(trees, 'the tree closed').toHaveCount(n - 1, { timeout: 15000 });
    }
    spot = await findSpot();
  }
  if (!spot.x) note('no free spot; under the pointer: ' + spot.covered.join(' | '));
  expect(spot.x, 'a spot of the 3D view free of floating cards').toBeTruthy();
  note('dragging at ' + spot.at);
  const cx = spot.x;
  const cy = spot.y;
  await page.mouse.move(cx, cy);
  const tDown = await page.evaluate(() => performance.now());
  await page.mouse.down();
  // a few seconds of a real hand: a slow circle, one event every ~16 ms
  const steps = Math.round(DRAG_MS / 16);
  for (let i = 1; i <= steps; i += 1) {
    const a = (i / steps) * Math.PI * 2;
    await page.mouse.move(cx + Math.cos(a) * RX, cy + Math.sin(a) * RY);
    await page.waitForTimeout(16);
  }
  const tUp = await page.evaluate(() => performance.now());
  await page.mouse.up();
  // wait for the stream to go quiet after the release
  await page.waitForFunction(() => {
    const t = window.__frames.t;
    return t.length && performance.now() - t[t.length - 1] > 800;
  }, null, { timeout: 8000 }).catch(() => {});

  const r = await page.evaluate(({ tDown, tUp }) => {
    clearInterval(window.__sampler);
    const f = window.__frames;
    const drag = []; const after = [];
    f.t.forEach((t, i) => {
      if (t >= tDown && t <= tUp) drag.push(f.bytes[i]);
      else if (t > tUp) after.push({ t, b: f.bytes[i] });
    });
    const sum = (a) => a.reduce((x, y) => x + y, 0);
    const im = window.__frameImg();
    return {
      dragFrames: drag.length,
      dragKb: drag.length ? sum(drag) / drag.length / 1024 : 0,
      dragMbps: sum(drag) * 8 / ((tUp - tDown) / 1000) / 1e6,
      dragSeconds: (tUp - tDown) / 1000,
      afterFrames: after.length,
      afterLastMs: after.length ? after[after.length - 1].t - tUp : null,
      afterLastKb: after.length ? after[after.length - 1].b / 1024 : null,
      dims: Array.from(f.dims),
      final: im ? { w: im.naturalWidth, h: im.naturalHeight } : null,
    };
  }, { tDown, tUp });

  note('drag ' + r.dragSeconds.toFixed(1) + ' s: ' + r.dragFrames + ' frames = '
    + (r.dragFrames / r.dragSeconds).toFixed(1) + ' images/s, '
    + r.dragKb.toFixed(0) + ' KB each, ' + r.dragMbps.toFixed(1) + ' Mbit/s');
  note('resolutions seen: ' + r.dims.join(', '));
  note('after the release: ' + r.afterFrames + ' frame(s), the last one '
    + (r.afterLastKb === null ? '-' : r.afterLastKb.toFixed(0)) + ' KB at +'
    + (r.afterLastMs === null ? '-' : r.afterLastMs.toFixed(0)) + ' ms; final '
    + (r.final ? r.final.w + 'x' + r.final.h : 'none'));

  expect(r.dragFrames, 'frames streamed while the mouse was down').toBeGreaterThanOrEqual(3);
  expect(r.afterFrames, 'a still frame after the release').toBeGreaterThanOrEqual(1);
  expect(r.final, 'the resting frame is back at its resolution').toEqual(before);
  const treeButtons = page.locator(M.toolButton + ':visible[title^="Reservoir"]');
  for (let i = 0; i < closedTrees; i++) await treeButtons.nth(i).click();
  if (closedTrees) await expect(trees, 'the trees back').toHaveCount(closedTrees, { timeout: 15000 });
});
