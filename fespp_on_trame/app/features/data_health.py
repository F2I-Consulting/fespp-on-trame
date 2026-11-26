"""data health (engine/health_dispatch)

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.app.scene.tree_reveal import show_in_tree
from fespp_on_trame.engine import view_routing
from fespp_on_trame.engine.utils import csv_export


def register(core, *, _any_usable_crs, _defer, _display_title, _node_title):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    active_data_source = core.active_data_source
    activation = core.activation
    cards = core.cards
    _mv = core.mv
    # --- data health (engine/health_dispatch) ---------------------------------
    def _compute_health():
        from fespp_on_trame.engine import health_dispatch
        bounds = None
        try:
            bounds = list(active_data_source.get_source().GetDataInformation().GetBounds())
        except Exception:
            bounds = None
        res = health_dispatch.compute(state, tree, crs_probe=_any_usable_crs,
                                      bounds=bounds, far=active_data_source.store_paths)
        res["csv"] = health_dispatch.csv_payload(res)
        return res

    # how many times the table has been asked to focus on an object: the
    # same object twice in a row must still reach the panel
    _health_focus = {"n": 0}

    def _refresh_health():
        _defer("health", _refresh_health_now)

    def _refresh_health_now():
        mv = _mv()
        if mv is None or not mv.panel_ids_of_kind("health"):
            return
        try:
            state.ui_health = _compute_health()
        except Exception as exc:
            print("[fespp] health error:", exc, flush=True)
            state.ui_health = {"summary": {}, "findings": [], "note": f"error: {exc}",
                               "csv": dict(csv_export.EMPTY_PAYLOAD)}

    @controller.set("health_compute")
    def health_compute():
        """The table without a panel — the harness probe reads it."""
        return _compute_health()

    @controller.set("open_health")
    def open_health():
        """Open (or focus) the Data health table — session-level."""
        mv = _mv()
        if mv is None:
            return
        try:
            mv.add_view(kind="health")      # singleton -> opens or focuses
        except Exception as exc:
            print("[fespp] open health view error:", exc, flush=True)
        if not state.ui_health:
            state.ui_health = {"note": "Reading the loaded data…"}
        _refresh_health()

    @controller.set("health_refresh")
    def health_refresh(*_a):
        _refresh_health()

    @controller.set("health_focus")
    def health_focus(path):
        """Open Data health on ONE object — the right-click of a panel tree.

        The table is the session's, so the object is named in its filter
        rather than in a table of its own; the filter counts its rows, and
        says when a healthy object has none. The nonce is what makes the
        same object asked for twice arrive twice."""
        name = _node_title(path) or _display_title(path, "") or (
            (path or "").rsplit("/", 1)[-1])
        _health_focus["n"] += 1
        state.ui_health_focus = {"text": name, "n": _health_focus["n"]}
        open_health()

    @controller.set("health_activate")
    def health_activate(path):
        """A row's object becomes the active tree node of a 3D view — the
        one the reader last worked in, else the first — and that view comes
        to the front, its tree opened on the node: an activation made behind
        the health panel, with nothing changing on screen, would read as a
        click that did nothing."""
        if not path:
            return
        mv = _mv()
        if mv is None:
            return
        vids = list(mv.view_ids() or [])
        vid = view_routing.resolve_active_render_panel(state)
        if vid not in vids:
            vid = vids[0] if vids else ""
        if not vid:
            return
        try:
            mv.active_panel(vid)
        except Exception:
            pass
        show_in_tree(activation, cards, state, vid, path)

    @state.change("assembly_rev", "lazy_rev", "vtk_log_messages", "ui_invalid_node_errors", "ui_empty_geometry")
    def _on_health_inputs(**_):
        _refresh_health()
