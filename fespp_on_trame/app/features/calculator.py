"""derived-property calculator (engine/derived_props)
The store holds RECIPES, not data: zero proxies, nothing for a FESPP
re-execution to wipe. Consumers read through property_values.values_for.

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine import stats_dispatch
from fespp_on_trame.engine import crossplot_dispatch
from fespp_on_trame.engine.vtk_log import capture_vtk_messages
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.app.core import state_registry


def register(core, *, _crossplot_ys, _defer, _node_title, _property_or_note,
             _rebuild_compare_tree, _refresh_crossplot, _say):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_CALC_KEYS, _derived_fanout, _refresh_calculator)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    source_registry = core.source_registry
    batcher = core.batcher
    _derived_store = core.derived_store
    _mv = core.mv
    # --- derived-property calculator (engine/derived_props) --------------
    # The store (made by boot) holds RECIPES, not data: zero proxies, nothing
    # for a FESPP re-execution to wipe. Consumers read through
    # property_values.values_for.
    from fespp_on_trame.engine import derived_props

    _CALC_KEYS = state_registry.CALCULATOR.keys

    def _calc_rep_choices():
        # loaded reps carrying >= 1 property; Frames excluded (channels
        # correlate in the well-log view, not in a cell calculator)
        seen = {}
        for p in list(getattr(state, "ui_loaded_array_paths", None) or []):
            rp = stats_dispatch._rep_path_for_array_path(tree, p)
            if not rp or rp in seen:
                continue
            nid = tree.find_node_id(rp)
            if nid is not None and (tree.find_type(nid) or "") == "Frame":
                continue
            seen[rp] = (stats_dispatch._rep_title_for_array_path(tree, p)
                        or rp.rsplit("/", 1)[-1])
        return [{"title": t, "value": rp} for rp, t in seen.items()]

    def _calc_prop_chips(rep_path):
        from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
        chips = []
        if not rep_path:
            return chips
        props = _derived_store.loaded_props_of_rep(state, tree, rep_path)
        for p, (title, kind) in sorted(props.items(),
                                       key=lambda kv: kv[1][0].lower()):
            badge = (" (MR)" if "MultiRealization" in kind
                     else (" (TS)" if "TimeSeries" in kind else ""))
            chips.append({"label": title + badge,
                          "ident": make_valid_vtk_name(title),
                          "uom": stats_dispatch._unit_for_array_path(tree, p),
                          "derived": False, "path": p})
        for d in _derived_store.defs_for_rep(rep_path):
            chips.append({"label": "ƒ " + d["name"], "ident": d["vtk_name"],
                          "uom": d["uom"], "derived": True,
                          "path": derived_props.path_for(rep_path, d["name"])})
        return chips

    def _calc_axes(chips):
        """{ident: {reals, ts}} of the chips that have an axis to pin — a
        multi-realization or time-series property — for the A − B row."""
        out = {}
        for c in chips:
            try:
                axes = crossplot_dispatch.axis_options(state, tree, c.get("path"))
            except Exception:
                continue
            if axes.get("reals") or axes.get("ts"):
                out[c["ident"]] = {"reals": axes.get("reals") or [],
                                   "ts": axes.get("ts") or []}
        return out

    def _calc_preview_figure(values, revision=""):
        """Small full-resolution histogram of the UNSAVED formula.
        `revision` names what is on the axes (the grid and the formula):
        while it holds, a refresh keeps the user's zoom."""
        import numpy as _np
        import plotly.graph_objects as go
        fin = values[_np.isfinite(values)]
        fig = go.Figure()
        if len(fin):
            counts, edges = _np.histogram(fin, bins=40)
            centers = (edges[:-1] + edges[1:]) / 2.0
            fig.add_trace(go.Bar(x=centers.tolist(), y=counts.tolist(),
                                 marker_color="#3949ab"))
        fig.update_layout(margin=dict(l=40, r=10, t=10, b=30),
                          bargap=0, showlegend=False, uirevision=revision)
        return fig

    def _refresh_calculator(panel_id):
        _defer(f"calculator:{panel_id}", lambda: _refresh_calculator_now(panel_id), views=[panel_id])

    def _refresh_calculator_now(panel_id):
        if panel_id not in (getattr(state, "ui_calc_panels", None) or ()):
            return
        rep = getattr(state, f"ui_calc_rep_{panel_id}", None)
        state[f"ui_calc_rep_choices_{panel_id}"] = _calc_rep_choices()
        chips = _calc_prop_chips(rep)
        state[f"ui_calc_prop_chips_{panel_id}"] = chips
        state[f"ui_calc_axes_{panel_id}"] = _calc_axes(chips)
        state[f"ui_calc_mr_props_{panel_id}"] = ([
            {"title": t, "value": p}
            for p, (t, k) in _derived_store.loaded_props_of_rep(
                state, tree, rep).items()
            if "MultiRealization" in k] if rep else [])
        exprs = (getattr(state, f"ui_calc_expr_{panel_id}", None) or "").strip()
        status = {"error": "", "ok": False, "summary": ""}
        empty_fig = {"data": [], "layout": {}}
        if not exprs or not rep:
            if exprs and not rep:
                status["error"] = "Pick a grid first."
            state[f"ui_calc_preview_{panel_id}"] = {}
            state[f"ui_calc_figure_{panel_id}"] = empty_fig
            state[f"ui_calc_status_{panel_id}"] = status
            return
        editing = getattr(state, f"ui_calc_editing_{panel_id}", None) or None
        try:
            with capture_vtk_messages(state):
                pv_stats, err = _derived_store.preview(
                    state, tree, source_registry, rep, exprs,
                    editing_name=editing)
        except Exception as exc:
            pv_stats, err = None, f"compute failed: {exc}"
        if err or pv_stats is None:
            status["error"] = err or "compute failed"
            state[f"ui_calc_preview_{panel_id}"] = {}
            state[f"ui_calc_figure_{panel_id}"] = empty_fig
            state[f"ui_calc_status_{panel_id}"] = status
            return
        values = pv_stats.pop("values", None)
        # raw values: the card formats them on screen with the shared rule
        disp = {k: (float(v) if isinstance(v, float) else v)
                for k, v in pv_stats.items()}
        status["ok"] = True
        status["summary"] = (f"{numfmt.fmt_int(pv_stats.get('n', 0))} cells · "
                             f"{numfmt.fmt_int(pv_stats.get('nan', 0))} NaN · ready")
        state[f"ui_calc_preview_{panel_id}"] = disp
        state[f"ui_calc_status_{panel_id}"] = status
        # ALWAYS push a figure: an all-NaN formula returns no values, and
        # leaving the previous one on screen would show the PREVIOUS
        # formula's distribution under the new formula's stats.
        import numpy as _np
        fig = _calc_preview_figure(
            values if values is not None else _np.array([], dtype=float),
            revision=f"{rep}|{exprs}")
        upd = getattr(controller, f"update_calc_figure_{panel_id}", None)
        try:
            if upd is None:
                raise RuntimeError("no widget yet")
            upd(fig)
        except Exception:
            state[f"ui_calc_figure_{panel_id}"] = fig.to_plotly_json()

    def _derived_fanout(scrub_paths=()):
        """A recipe was created / updated / deleted: every consumer that can
        hold a derived path refreshes; `scrub_paths` are dropped first."""
        scrub = set(scrub_paths or ())
        for pid2 in list(getattr(state, "ui_crossplot_panels", None) or []):
            for ax in ("x", "color"):
                if getattr(state, f"ui_crossplot_{ax}_{pid2}", None) in scrub:
                    state[f"ui_crossplot_{ax}_{pid2}"] = None
            # a Y row of a dropped recipe empties, it does not vanish; the
            # pinned snapshots are frozen and keep it on screen
            ys = _crossplot_ys(pid2)
            if any(y["path"] in scrub for y in ys):
                state[f"ui_crossplot_ys_{pid2}"] = [
                    dict(y, path=None) if y["path"] in scrub else y
                    for y in ys]
            _refresh_crossplot(pid2)
        # the Statistics view's rows with it, the recipe's item scrubbed
        _rebuild_compare_tree()

    @controller.set("open_calculator")
    def open_calculator(path=None):
        """Open (or focus) THE calculator.

        Two doors, one controller: the right-click "Derived property" passes a
        property and the panel comes up preseeded with its grid, while the
        toolbar button passes nothing and the panel comes up on its own grid
        select. Registering a second, argument-less controller under the same
        name would silently REPLACE this one."""
        mv = _mv()
        if mv is None:
            return
        if path and not _property_or_note(path, "a derived property"):
            return
        rep = None
        if path:
            nid = tree.find_node_id(path)
            rid = (tree.find_representation_node(nid)
                   if nid is not None else None)
            rep = tree.find_path(rid) if rid is not None else None
            if rid is not None and (tree.find_type(rid) or "") == "Frame":
                # a log channel is no grid property: the calculator works
                # per cell of a grid (_calc_rep_choices leaves frames out),
                # and opening it on some grid would drop the clicked log
                # without a word
                name = _node_title(path) or "That channel"
                _say(
                    f"{name} is a well-log channel — a derived property"
                    " needs a grid property: right-click one under a grid.")
                return
        try:
            panel_id = mv.add_view(kind="calculator")
        except Exception as exc:
            print("[fespp] open calculator error:", exc, flush=True)
            return
        panels = list(getattr(state, "ui_calc_panels", None) or [])
        if panel_id not in panels:
            state.ui_calc_panels = panels + [panel_id]
            seeds = {"rep": rep, "expr": "", "name": "", "uom": "",
                     "kind": "ContinuousProperty",
                     "status": {"error": "", "ok": False, "summary": ""},
                     "preview": {}, "figure": {"data": [], "layout": {}},
                     "rep_choices": [], "prop_chips": [], "editing": "",
                     "mr_props": [], "mr_pick": None}
            for k in _CALC_KEYS:
                state[f"ui_calc_{k}_{panel_id}"] = seeds[k]

            def _on_calc_input(**_kw):
                # DEBOUNCED: the preview reads its inputs at FULL resolution
                # (a whole grid's array per identifier), and the formula box
                # fires on every keystroke — without this, typing "log10("
                # is six full evaluations.
                batcher.schedule(f"calc:{panel_id}",
                                 lambda: _refresh_calculator(panel_id))
            try:
                state.change(f"ui_calc_rep_{panel_id}",
                             f"ui_calc_expr_{panel_id}")(_on_calc_input)
            except Exception:
                pass
        elif rep:
            state[f"ui_calc_rep_{panel_id}"] = rep
        _derived_store.publish(state)
        _refresh_calculator(panel_id)

    @controller.set("calc_diff")
    def calc_diff(panel_id, expr, name, uom):
        """The card's A − B row: the formula (pinned identifiers when a
        realization or a time step was picked), its name and unit, then
        the ordinary create."""
        state[f"ui_calc_expr_{panel_id}"] = expr or ""
        state[f"ui_calc_name_{panel_id}"] = name or ""
        state[f"ui_calc_uom_{panel_id}"] = uom or ""
        state[f"ui_calc_kind_{panel_id}"] = "ContinuousProperty"
        state[f"ui_calc_editing_{panel_id}"] = ""
        calc_create(panel_id, role="difference")

    @controller.set("calc_create")
    def calc_create(panel_id, role=""):
        rep = getattr(state, f"ui_calc_rep_{panel_id}", None)
        name = (getattr(state, f"ui_calc_name_{panel_id}", None) or "")
        exprs = (getattr(state, f"ui_calc_expr_{panel_id}", None) or "")
        uom = getattr(state, f"ui_calc_uom_{panel_id}", None) or ""
        kindv = (getattr(state, f"ui_calc_kind_{panel_id}", None)
                 or "ContinuousProperty")
        editing = getattr(state, f"ui_calc_editing_{panel_id}", None) or None
        err, _d = _derived_store.create(
            state, tree, rep, name, exprs, uom=uom, prop_kind=kindv,
            editing_name=editing, role=role)
        if err:
            st = dict(getattr(state, f"ui_calc_status_{panel_id}", None) or {})
            st["error"], st["ok"] = err, False
            state[f"ui_calc_status_{panel_id}"] = st
            return
        state[f"ui_calc_editing_{panel_id}"] = ""
        state[f"ui_calc_name_{panel_id}"] = ""
        _derived_store.publish(state)
        _refresh_calculator(panel_id)
        _derived_fanout()
    return (_CALC_KEYS, _derived_fanout, _refresh_calculator)
