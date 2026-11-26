"""One grammar for every tree (the PO, 18/10).

* the CHECKBOX is the session's load, common to every view: ticked in any
  tree = read into the session (`selected_paths`), unticked = unloaded from
  it — after a confirmation when another view is using the object;
* the EYE is "shown in THIS view": in a 3D view, drawn there; in a panel
  (Statistics, the well-log, Log <-> Grid), held by that panel — its property,
  its well, its row.

`PanelTrees` is what the panels register so that the tick routing and the
eyes stay generic: per panel kind, which panels are open (`vids`), what one
of them holds (`held`, in the paths its tree speaks), how to make it hold
another set (`hold`, the panel's own setter: what is added is taken in,
what is gone is let go, nothing is unloaded; a node is its well for the log),
what an eye opened makes it hold (`opens` — default: what it holds and the
paths) and, for a tree whose paths are not the assembly's (the Statistics
view's synthetic ones), the two conversions and how its panel follows an object
replaced by another (`moves`). The 3D views register who shows what
(`add_views`). From that the routing asks:

* `users(paths, exclude)` — the views using an object about to be unloaded,
  for the confirmation that names them;
* `eye(kind, vid, paths, on)` — an eye clicked in a panel's tree;
* `take(kind, vid, real_paths)` — a tick in a panel's tree: what it read
  goes in that panel, as a tick in the data tree shows what it read;
* `prune(real_paths)` — what was just unloaded leaves every panel;
* `move(moved)` — objects replaced by others: the panels follow.
"""
from fespp_on_trame.engine import node_facts


class PanelTrees:
    """The panels whose tree follows the one grammar, and the 3D views."""

    def __init__(self):
        self._kinds = {}
        self._views = []

    def add(self, kind, *, vids, held, hold, to_real=None,
            from_real=None, title=None, opens=None, moves=None):
        """Register a panel kind (see the module's docstring)."""
        self._kinds[kind] = {
            "vids": vids, "held": held, "hold": hold,
            "opens": opens, "moves": moves,
            "to_real": to_real or (lambda paths: list(paths)),
            "from_real": from_real or (lambda paths: list(paths)),
            "title": title or (lambda vid: kind),
        }

    def add_views(self, users):
        """`users(paths) -> [vid]`: the 3D views showing any of `paths`."""
        self._views.append(users)

    def kinds(self):
        return list(self._kinds)

    # ------------------------------------------------------------------

    def users(self, paths, exclude=None):
        """The views using any of `paths` (real assembly paths), `exclude`
        (the view the gesture came from) left out: the 3D views showing one,
        and the panels holding one — or holding something under one (a well
        whose trajectory is unloaded) or above one (a well whose channel
        is)."""
        paths = {p for p in (paths or ()) if p}
        out = []
        if not paths:
            return out
        for users in self._views:
            for vid in users(paths) or ():
                if vid != exclude and vid not in out:
                    out.append(vid)
        for k in self._kinds.values():
            for vid in k["vids"]() or ():
                if vid == exclude or vid in out:
                    continue
                held = k["to_real"](k["held"](vid) or [])
                if any(node_facts.is_under(h, paths) or node_facts.is_under(p, [h]) for h in held for p in paths):
                    out.append(vid)
        return out

    def title(self, kind, vid):
        k = self._kinds.get(kind)
        return k["title"](vid) if k else str(vid)

    def kind_of(self, vid):
        for kind, k in self._kinds.items():
            if vid in (k["vids"]() or ()):
                return kind
        return None

    # ------------------------------------------------------------------

    def eye(self, kind, vid, paths, on=None):
        """An eye of panel `vid`'s tree: `paths` (its tree's own paths, the
        loaded leaves a folder's eye stands for) taken in (`on`) or let go;
        `on=None` toggles one leaf. Nothing is read: an eye is only offered
        on what the session holds."""
        k = self._kinds.get(kind)
        if k is None:
            return
        held = list(k["held"](vid) or [])
        paths = [p for p in (paths or ()) if p]
        if on is None:
            on = not any(p in held for p in paths)
        if on and k["opens"] is not None:
            new = k["opens"](vid, paths)
        elif on:
            new = held + [p for p in paths if p not in held]
        else:
            new = [h for h in held if not node_facts.is_under(h, paths)]
        if new != held:
            k["hold"](vid, new)

    def take(self, kind, vid, real_paths):
        """A tick in panel `vid`'s tree read `real_paths`: they go in the
        panel, as a data-tree tick shows what it read in its view."""
        k = self._kinds.get(kind)
        if k is None or not real_paths:
            return
        self.eye(kind, vid, k["from_real"](real_paths), on=True)

    def move(self, moved):
        """Objects replaced by others (a new version of one): what a panel
        holds of them it holds of the new ones (`moved(path) -> path`). A tree
        speaking paths of its own knows no leaf of the new ones yet: its panel
        follows by itself (`moves`)."""
        for k in self._kinds.values():
            if k["moves"] is not None:
                k["moves"](moved)
                continue
            for vid in k["vids"]() or ():
                held = list(k["held"](vid) or [])
                new = [moved(h) for h in held]
                if new != held:
                    k["hold"](vid, new)

    def prune(self, real_paths):
        """`real_paths` were unloaded: every panel lets them go."""
        real_paths = [p for p in (real_paths or ()) if p]
        if not real_paths:
            return
        for k in self._kinds.values():
            gone = k["from_real"](real_paths)
            for vid in k["vids"]() or ():
                held = list(k["held"](vid) or [])
                new = [h for h in held
                       if not node_facts.is_under(h, gone) and not node_facts.is_under(h, real_paths)]
                if new != held:
                    k["hold"](vid, new)
