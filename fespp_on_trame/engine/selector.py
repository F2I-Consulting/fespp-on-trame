"""Tree selection to FESPP selectors, plus the companions some node kinds
need (a Wellhead per trajectory, a TimeSeries per tab)."""
from trame.app import get_server

from fespp_on_trame.engine.wellhead import Wellhead
from fespp_on_trame.engine.timeseries import TimeSeries
from fespp_on_trame.engine.tree import Tree

server = get_server()
state = server.state


class Selector:
    """Translates the per-tab `ui_select_node_*` checkbox lists into
    assembly paths and writes the concatenated result into
    `state.fespp_data_selectors`. Also creates / destroys companion
    objects (Wellhead, TimeSeries) tied to specific node kinds."""

    def __init__(self, tree: Tree):
        self._tree = tree

        self._selection_path_reservoir = []
        self._selection_path_surface = []
        self._selection_path_well = []

        self._wellheads = []
        # Per-tab TimeSeries companions: one slot per tree tab so a
        # selection change on one tab never destroys the companion
        # (LUT lock + time label) another tab still relies on.
        self._timeseries = {}

        state.setdefault("first_selection", True)

    def apply_z_scale(self, zscale, view_id=None):
        """Re-anchor the wellheads of a view (all when None) on its Z
        exaggeration.

        Wellheads are Text reps (flagpole + billboard): they carry no
        `Scale`, so the z-scale fan-out silently skips them and they would
        stay at the unscaled datum while their trajectory stretches away.
        See `Wellhead.apply_z_scale`."""
        for wellhead in self._wellheads:
            if view_id is not None and wellhead.view_id and str(wellhead.view_id) != str(view_id):
                continue
            try:
                wellhead.apply_z_scale(zscale)
            except Exception:
                continue

    def wellheads(self):
        return list(self._wellheads)

    def drop_view(self, view_id):
        """The wellheads drawn in a view that closes are deleted with it —
        else they would stay as dead proxies, and the next sync would keep
        them as if they were still drawn."""
        keep = []
        for wh in self._wellheads:
            if getattr(wh, "view_id", None) == view_id:
                try:
                    wh.delete()
                except Exception as exc:
                    print(f"[fespp] wellhead of a closed view ({view_id}):", exc, flush=True)
            else:
                keep.append(wh)
        self._wellheads = keep

    def sync_wellheads(self, node_ids, view=None, view_id=None):
        """Keep ONE Wellhead companion per checked Trajectory node id, for
        the session-wide selection (`selected_paths`), which never goes
        through the per-tab `select_node_well`. Synced incrementally — new
        ids get a companion, gone ids lose theirs, the rest are untouched:
        a field of a hundred wells must not be torn down and rebuilt on
        every selection change."""
        want = set(node_ids)
        keep = []
        for wh in self._wellheads:
            nid = getattr(wh, "node_id", None)
            if nid in want:
                keep.append(wh)
                want.discard(nid)
            else:
                wh.delete()
        for nid in want:
            keep.append(Wellhead(self._tree, nid, view=view, view_id=view_id))
        self._wellheads = keep

    def optimize_tree_selection(self, selected_items):
        """Identity in explicit-selection mode.

        With ExplicitSelection=1 (set at boot, see app.boot) the C++ side
        does not auto-load descendants of a parent path, so each checked
        node must be forwarded verbatim — collapsing to a parent path
        would silently drop the user's checked properties.

        UI-side dependency expansion (auto-check Trajectory when a
        Channel/Marker is checked, auto-check descendants of a
        grouping) happens in `app.ui.selection_deps` before this function runs,
        so `selected_items` is already the complete set."""
        return list(selected_items) if selected_items else []

    def _reset_timeseries(self, tab, node_ids):
        """Re-create THIS tab's TimeSeries companion from its selection;
        the other tabs keep theirs. When this tab ends up without one,
        the time label deleted alongside it is restored from any
        surviving companion."""
        old = self._timeseries.get(tab)
        if old is not None:
            old.delete()
            self._timeseries[tab] = None
        for node_id in node_ids:
            if self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries[tab] = TimeSeries(self._tree, node_id)
        if self._timeseries.get(tab) is None:
            for other in self._timeseries.values():
                if other is not None:
                    other.refresh_label()
                    break
