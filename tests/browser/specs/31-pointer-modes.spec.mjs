/*
 * Scenario (pointer modes): the HAND and the MOUSE of a 3D view's title bar.
 * The hand moves the scene; the mouse reads what is under the pointer —
 * position, object, cell, the colouring property's value with its unit — and
 * holds the scene still: a drag or a wheel notch brings no new frame, because
 * nothing moved. Back to the hand, a drag streams frames again.
 *
 * The view is the one whose title bar is clicked, found back in the state
 * by its mouse mode: late in the suite several 3D views are open. Frames
 * are counted where every delivered image goes through in the client
 * (URL.createObjectURL of an image blob), as 25-fluidity does.
 */
import {
  test, expect, M, DATASET, closeImportDoor, ensureShown, focusRenderView, holdVerdicts, ownSession,
  state,
} from '../lib/app.mjs';

/* The streamed frame of the view a title strip sits on: the visible <img>
 * under the strip's right end. Dockview draws the strips in an overlay of its
 * own, outside the view's group, so the DOM cannot lead from one to the
 * other — the screen can: a strip spans the top of its own view. Late in
 * the suite two groups stand side by side, and the biggest frame on screen
 * is then not necessarily this one. A view behind another tab keeps its
 * <img> with a 0x0 box. */
async function frameBox(page, strip) {
  const sb = await strip.boundingBox();
  return page.evaluate((x) => {
    const r = Array.from(document.querySelectorAll('img'))
      .filter((i) => i.naturalWidth > 50 && i.naturalHeight > 50)
      .map((i) => i.getBoundingClientRect())
      .filter((b) => b.width > 50 && b.height > 50 && b.left <= x && x <= b.right)
      .sort((a, b) => b.width * b.height - a.width * a.height)[0];
    return r ? { x: r.left, y: r.top, width: r.width, height: r.height } : null;
  }, sb.x + sb.width - 4);
}

/* Points of the frame where the view itself is on top — a card left open
 * by an earlier scenario covers a part of it — nearest the middle first.
 * On top of a free frame sits vtk.js's interaction canvas, a sibling of the
 * <img> in the view's own container. */
async function openPoints(page, box) {
  return page.evaluate((b) => {
    const im = Array.from(document.querySelectorAll('img')).find((i) => {
      const r = i.getBoundingClientRect();
      return Math.abs(r.left - b.x) < 1 && Math.abs(r.top - b.y) < 1 && r.width > 50;
    });
    const root = im && im.parentElement && im.parentElement.parentElement;
    const out = [];
    for (let j = 1; j < 10; j += 1) {
      for (let i = 1; i < 10; i += 1) {
        const x = b.x + (b.width * i) / 10;
        const y = b.y + (b.height * j) / 10;
        const el = document.elementFromPoint(x, y);
        if (el && root && root.contains(el) && (el.tagName === 'CANVAS' || el.tagName === 'IMG')) {
          out.push([x, y, Math.hypot(i - 5, j - 5)]);
        }
      }
    }
    return out.sort((p, q) => p[2] - q[2]).map(([x, y]) => [x, y]);
  }, box);
}

/* The share of a frame's pixels that are not the background (its corner). */
async function drawnShare(page, box) {
  return page.evaluate((b) => {
    const im = Array.from(document.querySelectorAll('img')).find((i) => {
      const r = i.getBoundingClientRect();
      return Math.abs(r.left - b.x) < 1 && Math.abs(r.top - b.y) < 1 && r.width > 50;
    });
    if (!im) return 0;
    const c = document.createElement('canvas');
    c.width = im.naturalWidth; c.height = im.naturalHeight;
    const g = c.getContext('2d');
    g.drawImage(im, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    const bg = [d[0], d[1], d[2]];
    let n = 0, all = 0;
    for (let k = 0; k < d.length; k += 4 * 7) {
      all += 1;
      if (Math.abs(d[k] - bg[0]) + Math.abs(d[k + 1] - bg[1]) + Math.abs(d[k + 2] - bg[2]) > 60) n += 1;
    }
    return all ? n / all : 0;
  }, box);
}

async function countFrames(page) {
  await page.evaluate(() => {
    if (window.__frameCount) { window.__frameCount.n = 0; return; }
    const orig = URL.createObjectURL.bind(URL);
    window.__frameCount = { n: 0 };
    URL.createObjectURL = (b) => {
      if (b && b.type && String(b.type).startsWith('image/')) window.__frameCount.n += 1;
      return orig(b);
    };
  });
}

const framesSince = (page) => page.evaluate(() => window.__frameCount.n);

/* The view whose mouse mode is on (there is one after the click). */
const cursorView = (page) => page.evaluate(() => {
  const s = window.trame.state;
  const all = s.state || s;
  const k = Object.keys(all).find((x) => /^ui_cursor_mode__/.test(x) && all[x] === true);
  return k ? k.replace('ui_cursor_mode__', '') : null;
});

/* A drag from (cx, cy), a point where the frame is on top. */
async function drag(page, [cx, cy]) {
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  for (let i = 1; i <= 12; i += 1) await page.mouse.move(cx + i * 10, cy + i * 4);
  await page.mouse.up();
}

test('the hand moves the scene; the mouse holds it still and reads the cell under the pointer', async ({ app }) => {
  // A session of its own: a file read by a scenario before, far from this one,
  // stretches the framing until nothing is under any pointer.
  const own = await ownSession(app, DATASET.files);
  const { page, note } = own;
  await closeImportDoor(page);
  await ensureShown(own, DATASET.properties[0]);
  await focusRenderView(page);
  // Each visible view is framed (the data in the middle, whatever the camera
  // went through) and the first with something drawn is the one.
  const strips = page.locator(M.titleStrip + ':visible');
  let strip = null;
  let box = null;
  for (let k = 0; k < await strips.count() && !strip; k += 1) {
    const s = strips.nth(k);
    await s.locator('[title="Frame everything in this view"]').click();
    await page.waitForTimeout(1500);
    const b = await frameBox(page, s);
    const share = b ? await drawnShare(page, b) : 0;
    note('view ' + (k + 1) + ': ' + Math.round(share * 100) + ' % of its frame drawn');
    if (share > 0.02) { strip = s; box = b; }
  }
  expect(strip, 'a 3D view on screen shows something').not.toBeNull();
  const hand = strip.locator('[data-t3-hand]');
  const mouse = strip.locator('[data-t3-mouse]');
  await expect(hand, 'the hand is on by default').toHaveAttribute('aria-checked', 'true');
  await expect(mouse).toHaveAttribute('aria-checked', 'false');

  // THE MOUSE: the readout under the pointer
  await mouse.click();
  await expect(mouse).toHaveAttribute('aria-checked', 'true');
  await expect.poll(() => cursorView(page), { message: 'the mouse mode is on in one view' })
    .not.toBeNull();
  const vid = await cursorView(page);
  let said = '';
  // the middle first, then around it, where no card covers the frame: the
  // data may not cover the very centre
  const points = (await openPoints(page, box)).slice(0, 8);
  expect(points.length, 'some of the frame is not covered').toBeGreaterThan(0);
  for (const [x, y] of points) {
    await page.mouse.move(x - 3, y - 3);
    await page.mouse.move(x, y);
    try {
      await expect.poll(async () => (await state(page, 'ui_cursor_pos__' + vid)) || '',
        { timeout: 6000 }).toMatch(/ = |∈/);
      said = await state(page, 'ui_cursor_pos__' + vid);
      break;
    } catch (e) {
      note('nothing coloured under ' + Math.round(x) + ', ' + Math.round(y));
    }
  }
  note('readout: ' + said.replace(/\n/g, ' | '));
  const lines = said.split('\n');
  expect(lines[0], 'the position under the pointer').toMatch(/elevation/);
  expect(lines.length, 'position, object, value: three lines').toBeGreaterThanOrEqual(3);
  expect(lines[lines.length - 1], 'the colouring property, its value and its unit')
    .toMatch(/ = |∈/);

  // ...and the scene does not move: a drag and a wheel notch bring no frame
  await countFrames(page);
  await drag(page, points[0]);
  await page.mouse.wheel(0, -240);
  await page.waitForTimeout(1500);
  const still = await framesSince(page);
  note('frames during a drag + a wheel notch in the mouse mode: ' + still);
  expect(still, 'the mouse mode holds the scene still').toBe(0);

  // THE HAND: the scene moves again
  await hand.click();
  await expect.poll(() => state(page, 'ui_cursor_mode__' + vid), { message: 'back to the hand' })
    .toBe(false);
  await expect.poll(async () => (await state(page, 'ui_cursor_pos__' + vid)) || '',
    { message: 'the readout goes with the mouse mode' }).toBe('');
  await countFrames(page);
  await drag(page, points[0]);
  await expect.poll(() => framesSince(page),
    { message: 'a drag with the hand streams frames', timeout: 15000 }).toBeGreaterThan(0);
  note('frames during a drag with the hand: ' + (await framesSince(page)));
  await holdVerdicts(own);
  await page.close();
});
