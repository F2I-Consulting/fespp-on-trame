/*
 * Scenario: a property, a camera drag, a SECOND property: the grid must
 * still be coloured.
 *
 * The failure this pins: after the drag, the second property leaves the grid
 * with no colour at all (not even the SolidColor colour) while the colour
 * legend is right, and further camera moves do not bring it back.
 *
 * The headless scenarios (tests/visual/scenarios/two_properties*.json) check
 * the still, interactive and decimated LOD frames the server renders for
 * that sequence. This one checks what no headless scenario can see: the
 * pixels the browser actually holds. The streamed frame is a blob `<img>`,
 * not the WebGL canvas beside it, which reads back empty.
 *
 * EARLY IN THE ORDER, on purpose: it wants one grid with two properties and
 * nothing else. Run late, several files are in and the tree holds more than
 * one row by that name, a failure that says nothing about colours.
 */
import {
  test, expect, DATASET, M, dataTree, ensureProperty, expandTree,
  focusRenderView, state, waitUntil,
} from '../lib/app.mjs';

/* The count of saturated pixels in the streamed frame (the render canvas when
   there is no frame image): what "coloured" means to an eye, counted the same
   way the headless probes count it. */
async function paint(page) {
  return page.evaluate(() => {
    const canvases = Array.from(document.querySelectorAll('canvas'))
      .filter((c) => c.width > 50 && c.height > 50);
    const imgs = Array.from(document.querySelectorAll('img'))
      .filter((i) => i.naturalWidth > 50 && i.naturalHeight > 50);
    const dump = {
      canvases: canvases.map((c) => ({
        w: c.width, h: c.height, cls: c.className,
        ctx: (() => { try { return c.getContext('webgl2') ? 'webgl2'
          : (c.getContext('webgl') ? 'webgl' : '2d'); } catch (e) { return '?'; } })(),
      })),
      imgs: imgs.map((i) => ({
        w: i.naturalWidth, h: i.naturalHeight, cls: i.className,
        src: String(i.src).slice(0, 24),
      })),
    };
    if (imgs.length) {
      const im = imgs.sort((a, b) => b.naturalWidth - a.naturalWidth)[0];
      const gi = document.createElement('canvas');
      gi.width = im.naturalWidth;
      gi.height = im.naturalHeight;
      const ci = gi.getContext('2d');
      ci.drawImage(im, 0, 0);
      let di;
      try {
        di = ci.getImageData(0, 0, gi.width, gi.height).data;
      } catch (e) {
        return { error: 'img tainted: ' + String(e), dump };
      }
      let coloured = 0;
      let white = 0;
      const n = di.length / 4;
      for (let i = 0; i < di.length; i += 4) {
        const mx = Math.max(di[i], di[i + 1], di[i + 2]);
        const mn = Math.min(di[i], di[i + 1], di[i + 2]);
        if (mx - mn > 40 && mx > 60) coloured += 1;
        if (mn > 225) white += 1;
      }
      // the DOM dump rides along only when there is nothing to report on,
      // so a failure says where it looked and not only what it found
      const shot = { from: 'img', w: gi.width, h: gi.height, coloured, white };
      return coloured ? shot : { ...shot, dump };
    }
    if (!canvases.length) return { error: 'no render canvas', dump };
    const c = canvases.sort((a, b) => b.width * b.height - a.width * a.height)[0];
    const g = document.createElement('canvas');
    g.width = c.width;
    g.height = c.height;
    const ctx = g.getContext('2d');
    ctx.drawImage(c, 0, 0);
    let d;
    try {
      d = ctx.getImageData(0, 0, g.width, g.height).data;
    } catch (e) {
      return { error: String(e) };
    }
    let coloured = 0;
    let white = 0;
    const n = d.length / 4;
    for (let i = 0; i < d.length; i += 4) {
      const mx = Math.max(d[i], d[i + 1], d[i + 2]);
      const mn = Math.min(d[i], d[i + 1], d[i + 2]);
      if (mx - mn > 40 && mx > 60) coloured += 1;
      if (mn > 225) white += 1;
    }
    const shot = { from: 'canvas', w: c.width, h: c.height, coloured, white };
    return coloured ? shot : { ...shot, dump };
  });
}

async function dragRender(page) {
  const box = await page.locator('canvas').first().boundingBox();
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 70, cy + 45, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(2500);
}

test('a second property still colours the grid after a camera drag', async ({ app }) => {
  const { page, note } = app;
  // what the session held before: this scenario runs EARLY, in the one
  // session the whole suite shares, so whatever it ticks it unticks again
  const before = (await state(page, 'ui_loaded_array_paths')) || [];
  await ensureProperty(app, DATASET.properties[0]);
  await focusRenderView(page);
  await page.waitForTimeout(2000);

  const first = await paint(page);
  note('after the first property: ' + JSON.stringify(first));
  expect(first.error, 'the render canvas could be read').toBeUndefined();
  expect(first.coloured, 'the first property colours the grid').toBeGreaterThan(200);

  await dragRender(page);
  const dragged = await paint(page);
  note('after the camera drag: ' + JSON.stringify(dragged));
  expect(dragged.coloured, 'the drag does not take the colours away')
    .toBeGreaterThan(200);

  await ensureProperty(app, DATASET.properties[1]);
  await page.waitForTimeout(3000);
  const second = await paint(page);
  note('after the second property: ' + JSON.stringify(second));
  note('loaded arrays: ' + JSON.stringify(await state(page, 'ui_loaded_array_paths')));
  expect(second.coloured,
    'the grid keeps its colours when a second property is picked after a drag')
    .toBeGreaterThan(200);

  // and the session goes back as it was found — the scenarios after this
  // one were written against the tree they inherit, not against this one's
  for (const path of ((await state(page, 'ui_loaded_array_paths')) || [])) {
    if (before.includes(path)) continue;
    const tree = dataTree(page);
    await expandTree(tree);
    const row = tree.locator('[data-path=' + JSON.stringify(path) + ']');
    if (!(await row.count())) continue;
    await row.locator(M.treeCheck).click();
    await waitUntil(app,
      async () => !((await state(page, 'ui_loaded_array_paths')) || []).includes(path),
      { what: 'the property this scenario added to be unticked again' });
  }
  note('session put back: ' + JSON.stringify(await state(page, 'ui_loaded_array_paths')));
});
