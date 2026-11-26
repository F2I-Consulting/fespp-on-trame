/*
 * Where a pop-over of `width` x `height` px opens over the page, in fixed
 * coordinates: under `anchor`, above it when the page ends first, inside the
 * page. A host draws it on <body>, so no scrolling list or card clips it.
 */
const MARGIN = 8;
const GAP = 4;

export function popPlace(anchor, width, height) {
  const box = anchor.getBoundingClientRect();
  const fits = box.bottom + GAP + height + MARGIN <= window.innerHeight;
  const top = fits ? box.bottom + GAP : Math.max(MARGIN, box.top - GAP - height);
  const left = Math.max(MARGIN, Math.min(box.left, window.innerWidth - width - MARGIN));
  return { top: top + "px", left: left + "px", width: width + "px" };
}
