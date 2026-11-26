/*
 * A press dragged on what scrolls moves it, as a hand moves paper: `y` the
 * element scrolled in depth, `x` the one scrolled sideways (either may be
 * absent, or both the same). A press that does not go past `threshold` px is
 * still a click; the click that ends a drag acts on nothing. `onMove()` runs
 * after each step (a drawn scrollbar kept in step from the gesture itself:
 * moved from the scroll event, Firefox reads it as a scroll-linked effect),
 * `onGrab(true | false)` as the drag starts and ends (a grabbing cursor).
 */
export function grabPan(e, { y, x, threshold = 4, onMove, onGrab } = {}) {
  const x0 = e.clientX;
  const y0 = e.clientY;
  const top = y ? y.scrollTop : 0;
  const left = x ? x.scrollLeft : 0;
  let moved = false;
  const move = (ev) => {
    const dx = ev.clientX - x0;
    const dy = ev.clientY - y0;
    if (!moved && Math.abs(dx) + Math.abs(dy) < threshold) return;
    if (!moved) {
      moved = true;
      if (onGrab) onGrab(true);
      const sel = window.getSelection();
      if (sel) sel.removeAllRanges();
    }
    if (y) y.scrollTop = top - dy;
    if (x) x.scrollLeft = left - dx;
    if (onMove) onMove();
  };
  const eat = (ev) => {
    ev.stopPropagation();
    ev.preventDefault();
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", up);
    if (!moved) return;
    if (onGrab) onGrab(false);
    window.addEventListener("click", eat, true);
    setTimeout(() => window.removeEventListener("click", eat, true), 0);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}
