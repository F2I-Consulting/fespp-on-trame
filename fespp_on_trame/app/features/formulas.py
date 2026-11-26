"""a derived property seen in 3D (the PO, 15/10: "l'oeil n'est pas
possible"). Its eye is an eye like any property's: its derived:// path
sits in the view's eye set (app/scene/eyes), the one-colouring-eye-per
grid rule covers it, and the eye pass colours the grid's block by the
array the derived-arrays filter attaches (engine/derived_arrays,
decision Q12) — the grid's isolate and extracts follow the block. Its
values are computed when an eye first needs them and kept while one
shows them: a snapshot, computed again when the recipes change.

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine import derived_props
from fespp_on_trame.app.views import per_view_state


def register(core, *, _blocks_for_rep, _nav_note):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_derived_array_name, _derived_forget, _derived_gc, _derived_resolved, _derived_values, _live_render_vids)."""
    # the shared services (app/core/context.Core)
    state = core.state
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    lifecycle = core.lifecycle
    eyes = core.eyes
    # --- a derived property seen in 3D (the PO, 15/10: "l'oeil n'est pas
    # possible"). Its eye is an eye like any property's: its derived:// path
    # sits in the view's eye set (app/scene/eyes), the one-colouring-eye-per-
    # grid rule covers it, and the eye pass colours the grid's block by the
    # array the derived-arrays filter attaches (engine/derived_arrays,
    # decision Q12) — the grid's isolate and extracts follow the block. Its
    # values are computed when an eye first needs them and kept while one
    # shows them: a snapshot, computed again when the recipes change.
    _derived_values = {}    # derived path -> (values, assoc, array name)

    def _derived_array_name(path):
        """What a derived property is called on screen ("ƒ name")."""
        _rp, name = derived_props.parse_path(path)
        return "ƒ " + (name or "derived")

    def _derived_vtk_name(path):
        """Its array name on the grid's blocks: ASCII — ParaView does not
        colour by a name carrying "ƒ"."""
        from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
        _rp, name = derived_props.parse_path(path)
        return "derived__" + make_valid_vtk_name(name or "value")

    def _live_render_vids():
        return [v for v in list(getattr(ctx, "blockscope_scenes", None) or {})
                if per_view_state.is_live(v)]

    def _derived_forget(path):
        """The formula's values are dropped and its array leaves the grid's
        blocks."""
        if _derived_values.pop(path, None) is not None:
            rep_path, _n = derived_props.parse_path(path)
            active_data_source.derived.drop(_derived_vtk_name(path), rep_path)

    def _derived_gc(closing=""):
        """Every formula no view's eye shows any more is forgotten."""
        shown = set()
        for v in _live_render_vids():
            if v != closing:
                shown.update(p for p in eyes.get(v) if derived_props.is_derived(p))
        for path in [p for p in _derived_values if p not in shown]:
            _derived_forget(path)

    def _derived_compute(vid, path):
        """(values, assoc, array name) of the formula on its grid, or None —
        the reason in the view's note."""
        import numpy as np
        from fespp_on_trame.engine import property_values
        rep_path, _name = derived_props.parse_path(path)
        if not rep_path:
            return None
        vals = property_values.values_for(state, tree, source_registry, path, rep_path)
        blocks = _blocks_for_rep(rep_path) or []
        if vals is None or not blocks:
            why = property_values.last_error()
            _nav_note(vid, f"{_derived_array_name(path)} cannot be computed now"
                           + (f": {why}" if why else ""))
            return None
        vals = np.asarray(vals, dtype=float).ravel()
        n_cells = sum(ds.GetNumberOfCells() for ds, _f in blocks)
        n_pts = sum(ds.GetNumberOfPoints() for ds, _f in blocks)
        assoc = "CELLS" if vals.size == n_cells else ("POINTS" if vals.size == n_pts else "")
        if not assoc:
            _nav_note(vid, f"{_derived_array_name(path)}: {vals.size} values for"
                           f" {n_cells} cells — not drawn")
            return None
        return vals, assoc, _derived_vtk_name(path)

    def _derived_resolved(vid, path, just_opened=False):
        """(assoc, array name) of the formula on its grid's blocks, computed
        and attached on first need; None when it cannot be drawn."""
        hit = _derived_values.get(path)
        if hit is None:
            hit = _derived_compute(vid, path)
            if hit is None:
                return None
            _derived_values[path] = hit
            rep_path, _n = derived_props.parse_path(path)
            active_data_source.derived.put(hit[2], rep_path, hit[0], hit[1])
        if just_opened:
            _nav_note(vid, f"{_derived_array_name(path)} colors its grid"
                           " (computed in this session)")
        return hit[1], hit[2]

    @lifecycle.on("new_data")
    def _new_data_formulas():
        """A formula's values belong to the cells they were computed on."""
        for path in list(_derived_values):
            _derived_forget(path)
    return (_derived_array_name, _derived_forget, _derived_gc, _derived_resolved, _derived_values, _live_render_vids)
