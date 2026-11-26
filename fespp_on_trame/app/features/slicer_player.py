"""The player of a slicer row — one row of a view's card stepped through its
values (value mode) or its kept range slid as one (range mode), shared by
the Property slicer (a threshold chain entry) and the Geometry slicer (an
I/J/K row). The PO, 27/10: "a player that shows only the current value and
hides everything else", "the movement must be fluid"; the manager, 28/10:
a player on every row, and the range mode stepping the whole range.

The player owns no filter: each step is handed to `apply(vid, row, low,
high)`, which moves what the row cuts (`GridIsolate.set_range` for a
threshold, the boxes for an I/J/K row); the steps come from
`engine/value_sweep`.

Fluid, measured on drogon with the GPU (spec 35-value-sweep, 27/10):
- a step asked while the previous one is still drawing is not queued: the
  last one asked wins (`step` yields once to the event loop, so the
  messages a fast drag piled up only update the wish, and one frame is
  drawn for all of them). A drag shows every value, ~11 images a second;
- the player leaves the server IDLE_S after each step. A frame is ~100 ms
  of render and read-back here, and its JPEG is encoded in the background
  (trame-vtk's image delivery): steps chained with no gap starve the
  encoder, and one image a second reached the browser at x20. With the gap
  the pace asked is a ceiling: the player goes as fast as the machine
  draws, every step on screen. Tried and dropped: ParaView Web's animation
  mode (its loop renders back to back and left the player 2.5 steps a
  second at x20) and a shorter stale-frame delay (each retry renders again).

Published, per view: ``<prefix><vid>`` = {speed, loop, rates} or {entry,
kind, index, count, label, low, high, moves, playing, speed, loop, width,
widths, rates} — `entry` the row played. The pace and the loop are the
view's, kept from one row to the next; with the loop off (the manager,
29/10) the player stops on the last step, and a play from there starts
again at the first.
"""
import time

from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.engine import value_sweep

# the time the player leaves the server after each step, for the frame to
# be encoded and sent
IDLE_S = 0.05
# how long after a play or a pause its state is said once more: two states
# sent a moment apart may reach the browser in the other order (a step's,
# then the pause's), and the button would stay on "playing"
SAID_AGAIN_S = 0.4


class Coalescer:
    """The last wins: a burst of live edits — a slider dragged, the player
    stepped by hand — runs once per turn of the event loop, the latest only.
    The messages a fast drag piled up only update the wish, and one frame is
    drawn for all of them: what makes the player fluid, and the hand on a
    slider as fluid as the player (the PO's manager, 28/10). Like the
    player, it leaves the server IDLE_S after each draw before the next one:
    a drag drawn back to back starved the frame encoder, the picture lagging
    the hand (the PO, 28/10: "the range of the Geometry slicer is slow")."""

    def __init__(self, state):
        self._state = state
        self._wish = {}
        self._pending = set()

    def request(self, key, fn):
        """Run `fn` as soon as the event loop is free, unless another
        request for `key` comes first (that one runs instead)."""
        self._wish[key] = fn
        if key in self._pending:
            return
        self._pending.add(key)
        state = self._state

        async def _run():
            import asyncio
            try:
                await asyncio.sleep(0)
                while True:
                    fn_ = self._wish.pop(key, None)
                    if fn_ is None:
                        break
                    with state:
                        fn_()
                    # the frame's turn to be encoded and sent; a wish made
                    # meanwhile is drawn after it, the latest only
                    await asyncio.sleep(IDLE_S)
            except Exception as exc:
                print(f"[fespp] live edit error ({key}):", exc, flush=True)
            finally:
                self._pending.discard(key)

        from trame.app import asynchronous
        asynchronous.create_task(_run())


class Player:
    """At most one row played per view, for one card."""

    def __init__(self, core, prefix, steps_of, apply):
        """`steps_of(vid, row, width)`: (steps, kind, current low) of the
        row as it stands, or None when it is gone; `apply(vid, row, low,
        high)`: show one step, False when the row is gone."""
        self._state = core.state
        self._scheduler = core.scheduler
        self._prefix = prefix
        self._steps_of = steps_of
        self._apply_step = apply
        self._runs = {}      # vid -> {entry, kind, steps, index, width, moves}
        self._tasks = {}     # vid -> asyncio task
        self._prefs = {}     # vid -> {speed, loop}: the view's, from row to row
        self._live = Coalescer(core.state)

    def _pref(self, vid):
        return self._prefs.setdefault(vid, {"speed": value_sweep.DEFAULT_RATE, "loop": True})

    def key(self, vid):
        return f"{self._prefix}{vid}"

    def row(self, vid):
        """The row played in `vid`, or None."""
        run = self._runs.get(vid)
        return run["entry"] if run is not None else None

    def publish(self, vid):
        run = self._runs.get(vid)
        pref = self._pref(vid)
        if run is None:
            self._state[self.key(vid)] = {"speed": pref["speed"], "loop": pref["loop"],
                                          "rates": list(value_sweep.RATES)}
            return
        i = run["index"]
        lo, hi, label = run["steps"][i] if run["steps"] else (None, None, "")
        self._state[self.key(vid)] = {
            "entry": run["entry"], "kind": run["kind"], "index": i,
            "count": len(run["steps"]), "label": label, "low": lo, "high": hi,
            # the steps shown so far: a pace a probe can read
            "moves": run.get("moves", 0),
            "playing": vid in self._tasks, "speed": pref["speed"], "loop": pref["loop"],
            "width": run["width"],
            "widths": list(value_sweep.WIDTHS), "rates": list(value_sweep.RATES),
        }

    def _stop_task(self, vid):
        task = self._tasks.pop(vid, None)
        if task is not None:
            task.cancel()

    def drop(self, vid, why=""):
        """Forget the player of `vid` (its row is gone, its view closed)."""
        self._stop_task(vid)
        if not per_view_state.is_live(vid):
            self._prefs.pop(vid, None)
        if self._runs.pop(vid, None) is not None and why:
            print(f"[fespp] slicer player ({vid}) stopped: {why}", flush=True)
        if per_view_state.is_live(vid):
            self.publish(vid)

    def _apply(self, vid, i):
        """Show step `i`; False when the player cannot go on."""
        run = self._runs.get(vid)
        if run is None or not run["steps"]:
            return False
        i = max(0, min(len(run["steps"]) - 1, int(i)))
        lo, hi, _label = run["steps"][i]
        if not self._apply_step(vid, run["entry"], lo, hi):
            self.drop(vid, "its row is gone")
            return False
        run["index"] = i
        run["moves"] = run.get("moves", 0) + 1
        self.publish(vid)
        self._scheduler.mark_dirty(vid)
        self._scheduler.flush()
        return True

    def start(self, vid, row, at=None):
        """Play `row` from the step at its current low end (or step `at`);
        a row played before in this view is let go where it stands."""
        old = self._runs.get(vid) or {}
        width = old.get("width", value_sweep.DEFAULT_WIDTH)
        found = self._steps_of(vid, row, width)
        if not found or not found[0]:
            print(f"[fespp] slicer player ({vid}): row {row!r} has nothing to step through",
                  flush=True)
            return False
        steps, kind, low = found
        if old and old.get("entry") != row:
            self._stop_task(vid)
        self._runs[vid] = {"entry": row, "kind": kind or "Continuous", "steps": steps,
                           "index": 0, "width": width}
        self._apply(vid, value_sweep.nearest_index(steps, low) if at is None else at)
        return True

    def stop(self, vid):
        """End the player: the row keeps the step it shows."""
        self._stop_task(vid)
        self._runs.pop(vid, None)
        self.publish(vid)

    def step(self, vid, i):
        """Step `i` as soon as the event loop is free; the last asked wins."""
        self._stop_task(vid)
        if vid in self._runs:
            self._live.request(("step", vid), lambda: self._apply(vid, i))

    def play_row(self, vid, row, on):
        """The player bar of `row` (always under its slider; the PO's
        manager, 28/10): play starts it on that row, from where the row
        stands, pause keeps it there."""
        if on and self.row(vid) != row and not self.start(vid, row):
            return
        self.play(vid, bool(on))

    def _said_again(self, vid):
        """The player's state sent once more a moment from now, the last."""
        import asyncio
        state = self._state

        def _again():
            if per_view_state.is_live(vid):
                with state:
                    self.publish(vid)
                    state.dirty(self.key(vid))
        try:
            asyncio.get_running_loop().call_later(SAID_AGAIN_S, _again)
        except RuntimeError as exc:
            print(f"[fespp] slicer player ({vid}): its state not said again ({exc})", flush=True)

    def play(self, vid, on):
        self._stop_task(vid)
        self._said_again(vid)
        if not on or vid not in self._runs:
            self.publish(vid)
            return
        state = self._state
        run = self._runs[vid]
        if len(run["steps"]) < 2:
            # one step: nothing would change, the bar stays on play
            self.publish(vid)
            return
        if not self._pref(vid)["loop"] and run["steps"] and run["index"] >= len(run["steps"]) - 1:
            # played to the end once: a play starts again from the first step
            self._apply(vid, 0)

        async def _loop():
            import asyncio
            due = time.monotonic()
            try:
                while True:
                    run = self._runs.get(vid)
                    if run is None or not per_view_state.is_live(vid):
                        break
                    await asyncio.sleep(max(0.0, due - time.monotonic()))
                    run = self._runs.get(vid)
                    if run is None or len(run["steps"]) < 2:
                        break     # one step left: nothing would change
                    pref = self._pref(vid)
                    nxt = run["index"] + 1
                    if nxt >= len(run["steps"]):
                        if not pref["loop"]:
                            break     # once: it stays on the last step
                        nxt = 0
                    with state:
                        if not self._apply(vid, nxt):
                            break
                    # the pace asked, never sooner than IDLE_S after the
                    # step was drawn: the frame's turn to be encoded and sent
                    due = max(due + 1.0 / max(0.1, float(pref["speed"])),
                              time.monotonic() + IDLE_S)
            # a stop cancels the task: CancelledError (a BaseException)
            # goes through, the `finally` below still runs
            except Exception as exc:
                print(f"[fespp] slicer player play error ({vid}):", exc, flush=True)
            finally:
                if self._tasks.get(vid) is asyncio.current_task():
                    # ended by itself (its row gone, its view closed)
                    self._tasks.pop(vid, None)
                    if per_view_state.is_live(vid):
                        self.publish(vid)

        from trame.app import asynchronous
        self._tasks[vid] = asynchronous.create_task(_loop())
        self.publish(vid)

    def speed(self, vid, value):
        self._pref(vid)["speed"] = max(0.1, float(value))
        self.publish(vid)

    def loop(self, vid, on):
        """Loop at the end, or stop on the last step (the manager, 29/10)."""
        self._pref(vid)["loop"] = bool(on)
        self.publish(vid)

    def width(self, vid, value):
        """A continuous value row's window (a fraction of its range): the
        steps are made again, the player staying where it was along them."""
        run = self._runs.get(vid)
        if run is None or run["kind"] != "Continuous":
            return
        frac = run["index"] / max(1, len(run["steps"]) - 1)
        run["width"] = float(value)
        found = self._steps_of(vid, run["entry"], run["width"])
        if found and found[0]:
            run["steps"] = found[0]
            self._apply(vid, round(frac * (len(run["steps"]) - 1)))

    def refresh(self, vid):
        """The row played changed under the player (its mode, its range
        typed in): its steps are made again from where it stands."""
        run = self._runs.get(vid)
        if run is None:
            return
        found = self._steps_of(vid, run["entry"], run["width"])
        if not found or not found[0]:
            self.drop(vid, "nothing left to step through")
            return
        run["steps"], run["kind"], low = found[0], found[1] or run["kind"], found[2]
        run["index"] = value_sweep.nearest_index(run["steps"], low)
        self.publish(vid)
