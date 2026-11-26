"""Progressive loading: a large selection is read in growing steps, so what
is ticked appears as it arrives and the read can be stopped.

`fespp_data_selectors` is the only channel that loads, and ParaView reads
everything it names in ONE synchronous call. While that call runs the
server loop is blocked: nothing is drawn, and a click on Stop or "clear
all" waits for its end, which over an OSDU server can take minutes. Here
the same selection is written in growing steps instead, each one a load of
its own with its render; between two steps the server loop is free, so the
Stop button, a "clear all" or a new tick get through.

Every step costs a REDRAW of everything already loaded, on top of reading
its new objects, and that redraw grows with what is loaded, not with the
size of the step: many small steps cost far more than one load. Hence two
rules:

- a read from a FILE goes in one load (the file reads fast; steps would
  only multiply the redraws), unless ``FESPP_STEP_LOCAL=1``, which lets
  the tests drive the steps without a server;
- a read from a SERVER goes in steps (there the network wait dominates,
  and the progress must show and be stoppable). Each step is sized from
  the last one, split in two: its objects (the reader's own pass) and its
  redraw (the rest). A step is big enough that the redraws stay under a
  third of the time, and otherwise small enough that Stop acts within
  about :data:`STEP_MAX` seconds. One object first; never more than twice
  the last step, nor more than :data:`BATCH_MAX`.

The END state is the one-shot one: the last step writes the whole
selection, the folders included. A folder that `propagates_selection` is
held back until then, because FESPP loads everything under such a node at
once and would undo the steps; by then all its children are read, so it
reads nothing more. A stop keeps what is read: the caller unticks the
rest, in sight.

Nothing of trame or ParaView here: `run_steps` is driven through callbacks,
which lets its tests run with a fake clock."""
import asyncio
import math
import os
import time

#: A server read goes in steps from this many new objects on: over the
#: network every object is a wait of its own, worth showing as it arrives.
REMOTE_MIN = 2
#: A file read goes in one load, unless FESPP_STEP_LOCAL=1 (the tests),
#: and then in steps from this many new objects on.
LOCAL_MIN = 20
#: Stop should act within about STEP_MAX seconds...
STEP_MAX = 5.0
#: ...but the redraws never take more than 1 / (1 + REDRAW_RATIO) of the
#: time: a step spends at least REDRAW_RATIO times its redraw on reading
#: its objects. Four, not two, since 13/10: on ADME a grid property costs
#: 1.3 s to read and a redraw 3 to 5 s once fifty objects are loaded (the
#: view is handed everything loaded at each redraw), so steps of three or
#: four objects spent 45 % of a 44-property load redrawing; a fifth at
#: most now, at the price of a Stop that waits a longer step.
REDRAW_RATIO = 4.0
#: The seconds an object is supposed to take on a server whose pace this
#: process has not measured yet: the first step of a first read is sized on
#: it (three objects, not a whole lot of sixteen that would be ten seconds
#: of blank on a hosted store).
REMOTE_PACE_GUESS = 0.7
#: The most objects one step may ask for.
BATCH_MAX = 64
#: The pause between two steps, in seconds: long enough for the page to get
#: its frame and for a click to reach the server.
PAUSE = 0.05
#: A first step sized from a known pace reads about this many seconds...
FIRST_TARGET = 2.0
#: ...and never more than this many objects (nor does a first lot).
FIRST_MAX = 16
#: A first lot whose read is expected to take no more than this many
#: seconds (its objects times the known pace) goes in ONE step, whatever
#: FIRST_TARGET says: one read, one redraw, the lot shown whole (the PO,
#: 13/10: "récupérer l'ensemble d'un coup, puis un seul rendu"). A longer
#: lot still shows its first objects early.
ONE_SHOT_SECONDS = 5.0


def lots(leaves, owner_of):
    """Group `leaves` into LOTS, lists of paths that belong together and
    arrive together: ``owner_of(path)`` names the lot (a wellbore for its
    trajectory, frames, channels and markers; a grid for its properties;
    the path itself otherwise). The lots keep the order of first
    appearance, each lot the order of its leaves."""
    out, by_owner = [], {}
    for p in leaves:
        key = owner_of(p)
        lot = by_owner.get(key)
        if lot is None:
            lot = by_owner[key] = []
            out.append(lot)
        lot.append(p)
    return out


def first_batch(per_object):
    """How many objects the first step asks for when the pace of the last
    read of this source is known: FIRST_TARGET seconds of reading, one
    object at least, FIRST_MAX at most."""
    if not per_object or per_object <= 0:
        return 1
    return max(1, min(FIRST_MAX, int(FIRST_TARGET // per_object)))


def plan(fresh, holds_back):
    """Split the new paths `fresh` into ``(leaves, held)``.

    `leaves` are read one step after the other; `held` are the folders kept
    for the last step. `holds_back(path)` is True for a node whose tick
    selects its whole subtree in the reader."""
    leaves, held = [], []
    for p in fresh:
        (held if holds_back(p) else leaves).append(p)
    return leaves, held


def worth_stepping(leaves, remote, local_steps=None):
    """Tell whether this read goes in steps.

    A server read does from :data:`REMOTE_MIN` new objects on; a file read
    only when FESPP_STEP_LOCAL=1 (`local_steps` overrides the variable), and
    from :data:`LOCAL_MIN` new objects on."""
    if remote:
        return len(leaves) >= REMOTE_MIN
    if local_steps is None:
        local_steps = os.environ.get("FESPP_STEP_LOCAL") == "1"
    return bool(local_steps) and len(leaves) >= LOCAL_MIN


def next_batch(batch, seconds, size=None, redraw=0.0):
    """Size the next step from the last one.

    The last step asked for `batch` objects and read `size` of them (fewer
    on the last step) in `seconds`, of which `redraw` went to redrawing
    what was already loaded (the rest: reading the new objects)."""
    size = batch if size is None else max(1, size)
    redraw = min(max(0.0, redraw or 0.0), seconds)
    per_object = (seconds - redraw) / size
    grow = min(BATCH_MAX, batch * 2)
    if per_object <= 0:
        return grow
    # as many objects as fit in STEP_MAX beside the redraw...
    by_stop = int((STEP_MAX - redraw) // per_object) if STEP_MAX > redraw else 1
    # ...and never so few that the redraw takes more than
    # 1 / (1 + REDRAW_RATIO) of the step
    by_redraw = math.ceil(REDRAW_RATIO * redraw / per_object)
    return max(1, min(grow, max(by_stop, by_redraw)))


async def run_steps(base, leaves, final, apply, report, should_stop, is_current,
                    clock=time.monotonic, pause=asyncio.sleep, per_object=None, learned=None):
    """Write the selection in steps: `base` (what stays of the previous
    selection), then `leaves` a batch at a time, then `final` (the whole
    selection, its folders included).

    `leaves` is flat (one object a step at first, the steps growing), or
    grouped in LOTS (`lots`: a list of lists — a wellbore with its frames,
    channels and markers, the properties of one grid): a step takes whole
    lots, as many as its budget of objects allows, and splits a lot only
    when it is alone in the step and larger than the budget. The first
    step of a lotted read is one whole lot (FIRST_MAX objects at most);
    with `per_object`, the seconds one object took on the last read of
    this source, the first step reads FIRST_TARGET seconds' worth instead,
    and `learned(seconds)` is told the pace this read measured.

    `apply(selectors)` loads one step and returns once it is read, with the
    seconds of it that went to the redraw when it knows them (else None);
    `report(done, total)` says how far the read is; `should_stop()` reads
    the Stop button; `is_current()` is False once a newer selection has
    taken over. Returns ``(outcome, loaded)``: "done" with `final` read,
    "stopped" with the selectors read so far, or "superseded" (the newer
    selection owns the reader, nothing more is written)."""
    lotted = [list(x) if isinstance(x, (list, tuple)) else [x] for x in leaves]
    loaded = list(base)
    total = sum(len(lot) for lot in lotted)
    if per_object:
        batch = first_batch(per_object)
        # a first lot short enough at that pace is read whole: one step
        if lotted and per_object * len(lotted[0]) <= ONE_SHOT_SECONDS:
            batch = max(batch, min(BATCH_MAX, len(lotted[0])))
    else:
        batch = FIRST_MAX if lotted and len(lotted[0]) > 1 else 1
    i, pending = 0, []           # the next lot, the remainder of a split lot
    read_seconds, read_objects = 0.0, 0
    report(0, total)
    # the first step blocks the server loop for its whole read: without a
    # yield here the pill that announces it never reaches the browser
    await pause(PAUSE)
    while i < len(lotted) or pending:
        if not is_current():
            return "superseded", loaded
        if should_stop():
            return "stopped", loaded
        step = []
        if pending:
            step, pending = pending[:batch], pending[batch:]
        while not pending and i < len(lotted) and (not step or len(step) + len(lotted[i]) <= batch):
            lot = lotted[i]
            if not step and len(lot) > batch:
                step, pending = lot[:batch], lot[batch:]
            else:
                step = step + lot
            i += 1
        t0 = clock()
        redraw = apply(loaded + step)
        seconds = clock() - t0
        loaded = loaded + step
        read_seconds += max(0.0, seconds - (redraw or 0.0))
        read_objects += len(step)
        batch = next_batch(batch, seconds, len(step), redraw or 0.0)
        report(len(loaded) - len(base), total)
        await pause(PAUSE)
    if learned is not None and read_objects:
        learned(read_seconds / read_objects)
    if not is_current():
        return "superseded", loaded
    # every object is read: the folders complete the selection whatever
    # Stop says (they read nothing more), and a step that would write the
    # same set again is skipped, since it would render everything once more
    if set(final) != set(loaded):
        apply(list(final))
    return "done", list(final)
