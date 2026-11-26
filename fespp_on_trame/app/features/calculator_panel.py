"""The calculator panel's controls: the percentiles of a multi-realization
property in one click, a recipe acted on, edited or deleted, and the
recipes of an unloaded grid kept and flagged stale.

(Split out of app/features/navigation, overhaul slice 10.)"""
from fespp_on_trame.engine import stats_dispatch


def register(core, *, _derived_fanout, _refresh_calculator):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    _derived_store = core.derived_store
    @controller.set("calc_make_percentiles")
    def calc_make_percentiles(panel_id, source_path):
        """One click = the three uncertainty deliverables of an MR property,
        in the PRMS EXCEEDANCE convention: P90 = conservative case = the
        10th numpy percentile across realizations, P10 = upside = the 90th.
        Existing names are skipped (re-click is idempotent)."""
        rep = getattr(state, f"ui_calc_rep_{panel_id}", None)
        if not rep or not source_path:
            return
        from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
        src_title = stats_dispatch._title_and_kind(tree, source_path)[0] or "p"
        base = make_valid_vtk_name(src_title)
        first_err = ""
        for label, q in (("P90", 10), ("P50", 50), ("P10", 90)):
            err, _d = _derived_store.create_percentile(
                state, tree, rep, source_path, q, name=f"{label}_{base}")
            if err and "collides" not in err and not first_err:
                first_err = err
        if first_err:
            st = dict(getattr(state, f"ui_calc_status_{panel_id}", None) or {})
            st["error"], st["ok"] = first_err, False
            state[f"ui_calc_status_{panel_id}"] = st
        _derived_store.publish(state)
        _refresh_calculator(panel_id)
        _derived_fanout()

    @controller.set("calc_act")
    def calc_act(what, path, panel_id):
        """One entry point for the recipe-row buttons — the widget says WHAT
        was clicked, the routing stays server-side."""
        if not path:
            return
        if what == "stats":
            controller.add_to_stats(path)
        elif what == "edit":
            controller.calc_edit(path, panel_id)
        elif what == "delete":
            controller.calc_delete(path, panel_id)

    @controller.set("calc_edit")
    def calc_edit(path, panel_id):
        d = _derived_store.get(path)
        if d is None:
            return
        if d.get("type") == "percentile":
            # its "expression" is prose; saved back through the formula box
            # it would replace the percentile with a broken formula
            st = dict(getattr(state, f"ui_calc_status_{panel_id}", None) or {})
            st["error"] = ("A percentile recipe has no formula to edit — delete"
                           " it and make it again from the P10 / P50 / P90 buttons")
            st["ok"] = False
            state[f"ui_calc_status_{panel_id}"] = st
            return
        state[f"ui_calc_rep_{panel_id}"] = d["rep_path"]
        state[f"ui_calc_expr_{panel_id}"] = d["expression"]
        state[f"ui_calc_name_{panel_id}"] = d["name"]
        state[f"ui_calc_uom_{panel_id}"] = d["uom"]
        state[f"ui_calc_kind_{panel_id}"] = d["prop_kind"]
        state[f"ui_calc_editing_{panel_id}"] = d["name"]
        _refresh_calculator(panel_id)

    @controller.set("calc_cancel_edit")
    def calc_cancel_edit(panel_id):
        state[f"ui_calc_editing_{panel_id}"] = ""
        state[f"ui_calc_name_{panel_id}"] = ""

    @controller.set("calc_delete")
    def calc_delete(path, panel_id):
        _derived_store.delete(path)
        _derived_store.publish(state)
        _refresh_calculator(panel_id)
        _derived_fanout(scrub_paths=[path])

    @state.change("ui_loaded_rep_paths")
    def _on_loaded_for_derived(**_):
        # Recipes of an unloaded grid are KEPT and flagged stale (its value
        # cache is evicted): the consumers fail soft with their usual notes,
        # and re-ticking the grid revives everything.
        _derived_store.mark_stale_for_loaded(
            getattr(state, "ui_loaded_rep_paths", None) or [])
        _derived_store.publish(state)
        for pid2 in list(getattr(state, "ui_calc_panels", None) or []):
            _refresh_calculator(pid2)
