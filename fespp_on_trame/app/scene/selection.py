"""The cells selected in the 3D views (overhaul slice 10, with the typed
context; decision Q3: one selection at a time, owned by the view that made
it).

ParaView gives the shared source ONE selection: `owner_vid` is the view it
belongs to, the only one that draws it ("" for none). Per view, the object
keeps:

- `cells` — what is highlighted in 3D ({flat index: [cell ids]}): what the
  Values card's "Selected cells only" keeps and what the tree rows' Keep /
  Remove act on. A pick, highlighted rows of the Values table, a value
  highlight asked of the Assistant or a cross-plot brush set it. The ids
  of a block listed in `points` are POINT ids: a point set, which FESPP
  draws as one poly-vertex cell holding every point, is selected by its
  points (ParaView's own point selection), never as that one cell;
- `last_pick` — what the Navigation card centres or frames on: a pick sets
  it with the cells, a right-click or a double-click (which highlight
  nothing) alone;
- `origin` — the id of the selection extract the cells were picked ON, so
  that its Keep / Remove works FROM it, or None;
- `inputs` — the proxies a pick gave a selection to besides the source (an
  isolate's crop or threshold tip, an extract), cleared with the selection
  (D9);
- `extracts` — the selection extracts made in the view (app/features/
  extracts writes them; they go with the view).

The methods are the only writers of the first four.
"""


class Selection:
    """The selection of the 3D views and what goes with it, per view."""

    def __init__(self):
        self.cells = {}
        self.last_pick = {}
        self.points = {}        # vid -> the flats of `cells` that hold point ids
        self.pick_points = {}   # vid -> the same for `last_pick`
        self.origin = {}
        self.inputs = {}
        self.extracts = {}
        self.owner_vid = ""

    # ------------------------------------------------------------------
    # The highlighted cells

    def hold(self, vid, by_flat, *, pick=False, origin=None, points=()):
        """View `vid` highlights `by_flat` ({flat: [ids]}, copied): cell
        ids, point ids for the flats in `points` (a point set's); a pick
        (`pick`) is also what the Navigation card acts on. `origin`: the
        selection extract the cells were picked on, if any."""
        vid = str(vid)
        self.cells[vid] = {f: list(c) for f, c in by_flat.items()}
        self.points[vid] = {f for f in points if f in by_flat}
        if pick:
            self.last_pick[vid] = {f: list(c) for f, c in by_flat.items()}
            self.pick_points[vid] = set(self.points[vid])
        self.origin[vid] = origin

    def drop(self, vid, *, pick=True):
        """View `vid` highlights nothing any more; with `pick`, the
        Navigation card's target goes too. True when the view held cells
        (or, with `pick`, a pick)."""
        vid = str(vid)
        had = bool(self.cells.get(vid) or (pick and self.last_pick.get(vid)))
        self.cells.pop(vid, None)
        self.points.pop(vid, None)
        self.origin.pop(vid, None)
        if pick:
            self.last_pick.pop(vid, None)
            self.pick_points.pop(vid, None)
        return had

    def points_of(self, vid, *, pick=False):
        """The flats whose held ids are points (a point set's), as a set."""
        return set((self.pick_points if pick else self.points).get(str(vid)) or ())

    def clear_origin(self, vid):
        """The cells are no longer counted as picked on an extract."""
        self.origin.pop(str(vid), None)

    # ------------------------------------------------------------------
    # What the Navigation card acts on, alone

    def set_pick(self, vid, by_flat):
        """A right-click or a double-click: the card's target, nothing
        highlighted."""
        self.last_pick[str(vid)] = {f: list(c) for f, c in by_flat.items()}
        self.pick_points.pop(str(vid), None)

    def drop_pick(self, vid):
        self.last_pick.pop(str(vid), None)
        self.pick_points.pop(str(vid), None)

    def forget_picks(self):
        """New data: no view's pick target survives (its cells may not
        exist any more)."""
        self.last_pick.clear()
        self.pick_points.clear()

    # ------------------------------------------------------------------
    # The view's own proxies given a selection

    def add_input(self, vid, proxy):
        self.inputs.setdefault(str(vid), []).append(proxy)

    def drop_inputs(self, vid):
        for sm in self.inputs.pop(str(vid), None) or ():
            try:
                sm.CleanSelectionInputs(0)
            except Exception as exc:
                print(f"[fespp] selection: input not cleared ({vid}):", exc, flush=True)

    # ------------------------------------------------------------------

    def close_view(self, vid):
        """A view closes: its cells, its pick and its selection extracts go
        (the extracts' displays are released by app/scene/displays)."""
        self.drop(vid, pick=True)
        self.extracts.pop(str(vid), None)
