"""The application's events, each with ONE list of subscribers.

What must happen when a view closes or when new data arrives used to be
written as one long function per event, each listing the structures it
remembered — and forgetting others: a closed view left its eye memories, its
colour-map memories, its time cursor and play task, its camera flight and its
cursor's cell locators behind (02-carte M6).

Here a family subscribes its own clean-up where it keeps its state, and the
event is emitted once. A subscriber that fails is said with its name and the
others still run. Slice 2b of the overhaul.

Events and their keyword arguments:

- ``view_closed(vid)`` — a panel closes (a 3D view or another kind);
- ``new_data()`` — a new assembly: what was read from the last one is stale;
- ``session_rows(vid)`` — the rows the session adds to a 3D view's tree
  changed (an extract made, shown or deleted; a formula): the panels'
  trees that list them follow;
- ``view_cuts(vid)`` — what a 3D view draws of its grids may have moved (a
  slicer, a threshold, a mask, an eye), a burst of them while a slider is
  dragged: what reads it weighs whether it did.
"""

EVENTS = ("view_closed", "new_data", "session_rows", "view_cuts")


class Lifecycle:
    """Subscribers per event, run in the order they subscribed."""

    def __init__(self, log=None):
        self._subs = {e: [] for e in EVENTS}
        self._log = log or (lambda text: print(text, flush=True))

    def on(self, event, fn=None, name=None):
        """Subscribe `fn` to `event`; usable as a decorator
        (``@lifecycle.on("view_closed")``). Returns `fn`."""
        if event not in self._subs:
            raise ValueError(f"unknown event {event!r} (known: {', '.join(EVENTS)})")

        def register(f):
            self._subs[event].append((name or getattr(f, "__name__", "subscriber"), f))
            return f
        return register(fn) if fn is not None else register

    def emit(self, event, **kwargs):
        """Run every subscriber of `event`; a failure is said, not raised."""
        for name, fn in list(self._subs.get(event, ())):
            try:
                fn(**kwargs)
            except Exception as exc:
                self._log(f"[fespp] {event}: {name}: {exc!r}")

    def subscribers(self, event):
        """The names subscribed to `event`, in order."""
        return [name for name, _fn in self._subs.get(event, ())]
