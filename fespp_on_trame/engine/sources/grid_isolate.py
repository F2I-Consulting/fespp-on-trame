"""The grid isolate: one grid cut in ONE 3D view (overhaul slice 7).

A view's composite representation (engine/blockscope) cannot crop or
threshold one block. When the Slicers or the Thresholds card acts on a grid
in a view, the app swaps the grid's block out of the composite and draws it
through a GridIsolate: the grid's cells extracted from the view's clone
(engine/view_resources), its I/J/K cuts or kept volumes, its threshold
chain, its own displays in that view only. `app/scene/occupancy` decides
whether it draws; `app/features/slicers` and `thresholds` edit it.

It is the per-view mode of `engine/sources/ijkgrid.IjkGrid`. The other mode,
one shared instance per grid drawn in the active view, serves the legacy
per-representation model and, under BlockScope, only reads data. When that
model is deleted (Q2 bis) its display code goes, and what is left of
`IjkGrid` is this class.

Read it through `snapshot()` (its slicing as plain data) and its public
methods; its private fields are its own.
"""
from fespp_on_trame.engine.sources.ijkgrid import IjkGrid


class GridIsolate(IjkGrid):
    """One grid of one 3D view, cut and filtered there."""

    def __init__(self, source, tree, *, view_id, clone, pv_view, lut_for, shown_by=None):
        """`source`: the active data source facade; `clone`, `lut_for`: the
        view's clone and colour tables (engine/view_resources); `pv_view`:
        the view's render view; `shown_by`: who decides whether it draws
        (app/scene/occupancy), called with the isolate."""
        if view_id is None:
            raise ValueError("a grid isolate belongs to one view: view_id is required")
        super().__init__(source, tree, view_id=view_id, clone=clone,
                         pv_view=pv_view, lut_for=lut_for)
        self.shown_by = shown_by
