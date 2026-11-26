/*
 * A slider dragged LIVE, as fluid as the player (the PO's manager, 28/10:
 * "the range does not move fluidly"): a value goes at most every LIVE_MS,
 * the latest one — the server coalesces too (the last wins), so nothing
 * piles up behind the mouse and nothing waits for an answer (waiting for
 * the echo of each value was what made the drag slow). `end` closes the
 * drag: the release sends the exact last value itself.
 *
 * Shared by every slider that cuts the scene live (the slicer cards).
 */
export const LIVE_MS = 50;

export function liveSender() {
  let pending = null;
  let timer = null;
  let dragging = false;
  const tick = () => {
    timer = null;
    if (pending) {
      const fn = pending;
      pending = null;
      fn();
      timer = setTimeout(tick, LIVE_MS);
    }
  };
  return {
    get dragging() { return dragging; },
    send(fn) {
      dragging = true;
      pending = fn;
      if (!timer) tick();
    },
    // kept for the hosts that acknowledge: nothing waits any more
    ack() {},
    end() {
      dragging = false;
      pending = null;
      clearTimeout(timer);
      timer = null;
    },
    dispose() {
      clearTimeout(timer);
    },
  };
}
