"""The eye service of the 3D views (overhaul slice 4b: Q1, Q5, W1).

A view's eye set is `visible_paths__<vid>`: the paths it shows, in the order
their eyes opened. Its writers go through here:

- `apply(vid, paths)` runs the eye pass on `paths` now. The explicit
  callers use it (a load, a session, the assistant, the Globe's scene
  built, a realization), having written the set already; it always runs.
- `on_watch(vid, paths)` is the state watcher's door: the set CHANGED in
  the state, by a click in the browser or by a server write that relies on
  the watcher. It reads the set from the STATE, not from the watcher's
  argument: trame hands the watcher every queued value in turn, older ones
  included (measured 18/10: a load wrote 11 then 12 paths, the pass applied
  12, then the watcher was called with 11 — running it hid the new
  wellbore's head — and then with 12). It runs unless the set is the one
  the last pass left: a server write followed by `apply` reached the
  watcher again at the next flush, and the whole pass ran twice
  (04-verification W1).
- `set`, `toggle`, `inherit` and `show_everywhere` write the set, then
  apply it.

The pass itself (one colouring eye per grid, a property's grid shown with
it, the colours) stays boot's: it may rewrite the set, and what it leaves
is what is recorded as applied.

A read changes the world under the eyes (new blocks, wellheads, logs):
the load handlers `invalidate()` after their own passes, so the watcher's
pass at the end of that flush still runs — the one that sees the read
complete. With `skip_echoes` on, the watcher's echo of a set the last
pass left is skipped (one pass per gesture, 04-verification W1); off,
every watcher call runs the pass again (the behaviour before 17/10)."""


class Eyes:
    """The eye sets of the session's 3D views, one writer for all."""

    def __init__(self, state, run, is_live=None, skip_echoes=False):
        self._state = state
        self._run = run                      # run(vid, paths): the eye pass
        self._is_live = is_live or (lambda _vid: True)
        self.skip_echoes = skip_echoes
        self._applied = {}                   # vid -> the set the last pass left
        self.passes = {}                     # vid -> passes run (probes count them)
        self.echoes = {}                     # vid -> watcher calls found applied

    @staticmethod
    def var(vid):
        return f"visible_paths__{vid}"

    def get(self, vid):
        return list(getattr(self._state, self.var(vid), None) or [])

    def apply(self, vid, paths=None):
        """Run the eye pass of `vid` on `paths` (its current set when
        None). A view that is closing is left alone."""
        vid = str(vid)
        if not self._is_live(vid):
            return
        paths = self.get(vid) if paths is None else list(paths)
        self.passes[vid] = self.passes.get(vid, 0) + 1
        self._applied[vid] = tuple(paths)
        try:
            self._run(vid, paths)
        finally:
            # the pass may rewrite the set: the watcher will be handed THAT
            self._applied[vid] = tuple(self.get(vid))

    def on_watch(self, vid, paths=None):
        vid = str(vid)
        # the state's set, whatever value the watcher was handed (see the
        # module: a queued older value must not be applied over a newer one)
        cur = self.get(vid)
        if tuple(cur) == self._applied.get(vid):
            self.echoes[vid] = self.echoes.get(vid, 0) + 1
            if self.skip_echoes:
                return
        self.apply(vid, cur)

    def set(self, vid, paths):
        """Make `paths` the view's eye set and apply it."""
        vid = str(vid)
        paths = list(dict.fromkeys(p for p in (paths or ()) if p))
        self._state[self.var(vid)] = paths
        self.apply(vid, paths)

    def toggle(self, vid, path):
        cur = self.get(vid)
        self.set(vid, [p for p in cur if p != path] if path in cur else cur + [path])

    def inherit(self, vid, from_vid):
        """A view starts showing what `from_vid` shows (a view copied, the
        Globe opened beside it). False when there is nothing to inherit."""
        paths = self.get(from_vid)
        if not paths:
            return False
        self.set(vid, paths)
        return True

    def show_everywhere(self, vids, paths, show):
        """Show (or hide) `paths` in every view of `vids`: a panel's tree
        belongs to no view. Returns the views whose set changed."""
        drop = set(paths)
        changed = []
        for vid in vids:
            cur = self.get(vid)
            new = ([p for p in cur if p not in drop] if not show
                   else cur + [p for p in paths if p not in cur])
            if new != cur:
                self.set(vid, new)
                changed.append(str(vid))
        return changed

    def invalidate(self):
        """The world changed under every view's eyes (a read): the next
        watcher call runs the pass even for a set already applied."""
        self._applied.clear()

    def forget(self, vid):
        vid = str(vid)
        for d in (self._applied, self.passes, self.echoes):
            d.pop(vid, None)
