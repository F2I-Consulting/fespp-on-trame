"""The refresh of a cross-plot: its charts read one by one and published as
they come, its axes following a new tree layout. The panel's controls are
app/features/crossplot_panel."""
import asyncio
from fespp_on_trame.engine import crossplot_dispatch
from fespp_on_trame.engine.vtk_log import capture_vtk_messages
from fespp_on_trame.app.core import state_registry


def register(core, *, _blocks_for_rep, _clear_extract_highlights,
             _clear_selection_of, _defer, _heavy, _nav_note,
             _own_selection, _path_for_flat_index,
             _publish_sel_counts, _record_selection,
             _refresh_values, _rep_path_of, _row_of_rep, _select_ids):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_CROSSPLOT_WATCHED, _crossplot_ys, _drop_block_highlight, _drop_crossplot, _drop_crossplot_figures, _hl_state, _refresh_crossplot, _register_crossplot)."""
    # the shared services (app/core/context.Core)
    state = core.state
    ctx = core.ctx
    tree = core.tree
    source_registry = core.source_registry
    _CROSSPLOT_KEYS = state_registry.CROSSPLOT.keys
    # what the toolbar widget may write — the keys also carry the
    # server-owned outputs, which a client must never set
    _CROSSPLOT_SETTABLE = state_registry.CROSSPLOT.settable
    # a write to one of these recomputes the charts: those, and the axes the
    # Statistics view writes
    _CROSSPLOT_WATCHED = state_registry.CROSSPLOT_AXES + _CROSSPLOT_SETTABLE

    # pinned snapshots per panel: frozen trace dicts, server-side only — a
    # pin survives any later change of the axes and the unload of its
    # properties, and never crosses the websocket twice
    _crossplot_pins = {}

    def _crossplot_ys(panel_id):
        return [crossplot_dispatch.y_entry(y) for y in
                (getattr(state, f"ui_crossplot_ys_{panel_id}", None) or [])]

    def _crossplot_view(panel_id):
        """The Statistics view a cross-plot's wait shows on: the panel of the
        chart it holds is "<its id>x"."""
        return panel_id[:-1]

    def _refresh_crossplot(panel_id):
        _defer(f"crossplot-plan:{panel_id}", lambda: _refresh_crossplot_now(panel_id),
               views=[_crossplot_view(panel_id)])

    def _refresh_crossplot_now(panel_id):
        if panel_id not in (getattr(state, "ui_crossplot_panels", None) or ()):
            return
        x = getattr(state, f"ui_crossplot_x_{panel_id}", None)
        ys = _crossplot_ys(panel_id)
        # the colour's choices follow X: it must share X's rep. Derived
        # recipes are candidates too — same_rep_choices filters them by rep
        # like any property.
        loaded = (list(getattr(state, "ui_loaded_array_paths", None) or [])
                  + ctx.derived_store.active_paths())
        state[f"ui_crossplot_choices_{panel_id}"] = (
            crossplot_dispatch.same_rep_choices(tree, loaded, x))
        # The charts one by one, the loop breathing between two: dozens of
        # charts read in one go would block the session for the whole of it
        # and arrive all at once. The X context is read now; every chart then
        # comes up with its loading mark and fills as its values are read.
        # A refresh asked while one runs takes over: the older run sees its
        # generation gone and stops.
        #
        # The figures ship after the 1st, 2nd, 4th, 8th… chart, then at the
        # end: a state var travels whole at every flush, so shipping the
        # growing list after EVERY chart would cross the socket n²/2 times
        # a figure; doubling keeps the total under twice the final list and
        # the first charts still appear at once. Every figure carries a
        # `rev`, unchanged from one shipment to the next, so the widget
        # redraws only the new ones.
        gen = _crossplot_gen[panel_id] = _crossplot_gen.get(panel_id, 0) + 1
        g = lambda k: getattr(state, f"ui_crossplot_{k}_{panel_id}", None)  # noqa: E731
        try:
            with capture_vtk_messages(state):
                plan = crossplot_dispatch.crossplot_plan(
                    state, tree, source_registry, x, ys, g("color"),
                    x_real=g("xreal"), x_ts=g("xts"),
                    log_x=bool(g("logx")), log_y=bool(g("logy")),
                    pins=_crossplot_pins.get(panel_id) or [],
                    focus=g("focus"))
        except Exception as exc:
            print(f"[fespp] crossplot error ({panel_id}):", exc, flush=True)
            _crossplot_publish(panel_id, [], [],
                               {"kept": 0, "total": 0, "nan": 0, "axes": {},
                                "drawn": [], "charts": [], "focus": None,
                                "note": "compute failed — see the server log"})
            _heavy[f"crossplot:{panel_id}"] = False
            ctx.view_busy(f"crossplot:{panel_id}", (), False)
            return
        # the figures of before stay published (and on screen, under the
        # loading marks) until the first shipment replaces them
        heads = plan["heads"]
        state[f"ui_crossplot_charts_{panel_id}"] = [
            crossplot_dispatch.chart_public(h) for h in heads]
        _heavy[f"crossplot:{panel_id}"] = True
        ctx.view_busy(f"crossplot:{panel_id}", [_crossplot_view(panel_id)], True)

        async def _run():
            from trame_plotly.widgets.plotly import Figure as _PlotlyFigure
            charts, figs, drawn = [], [], []

            def _figure(c):
                fig = crossplot_dispatch.crossplot_figure(plan, c)
                if fig is not None:
                    figs.append(dict(_PlotlyFigure.to_data(fig), key=c["key"],
                                     rev=f"{gen}:{c['key']}"))
                    drawn.append(c["key"])

            def _ship():
                # the charts read so far, whole, the rest still loading
                state[f"ui_crossplot_charts_{panel_id}"] = (
                    [crossplot_dispatch.chart_public(x) for x in charts]
                    + [crossplot_dispatch.chart_public(h)
                       for h in heads[len(charts):]])
                state[f"ui_crossplot_figures_{panel_id}"] = list(figs)
            try:
                shipped = 0
                for i in range(len(heads)):
                    if _crossplot_gen.get(panel_id) != gen or panel_id not in (
                            getattr(state, "ui_crossplot_panels", None) or ()):
                        return
                    with capture_vtk_messages(state):
                        c = crossplot_dispatch.crossplot_chart(
                            plan, i, state, tree, source_registry)
                    charts.append(c)
                    _figure(c)
                    if len(charts) >= max(1, 2 * shipped) and i + 1 < len(heads):
                        with state:
                            _ship()
                        shipped = len(charts)
                    await asyncio.sleep(0)
                if plan["focus"] and not drawn:
                    # the focused chart is not drawable (its row removed, its
                    # Y cleared or moved to another rep): the grid is drawn
                    # instead, and meta says so, so the focus var is cleared
                    plan["focus"] = None
                    plan["legend_seen"], plan["scale_shown"] = set(), False
                    for c in charts:
                        _figure(c)
                meta = crossplot_dispatch.crossplot_meta(plan, charts, drawn)
            except Exception as exc:
                print(f"[fespp] crossplot error ({panel_id}):", exc, flush=True)
                meta = {"kept": 0, "total": 0, "nan": 0, "axes": {},
                        "drawn": [], "focus": None,
                        "charts": [crossplot_dispatch.chart_public(c) for c in charts],
                        "note": "compute failed — see the server log"}
            finally:
                # only the CURRENT run says it is done: a run a newer refresh
                # replaced must not clear the flag the newer one set
                if _crossplot_gen.get(panel_id) == gen:
                    _heavy[f"crossplot:{panel_id}"] = False
            if _crossplot_gen.get(panel_id) != gen:
                return
            with state:
                _crossplot_publish(panel_id, figs, meta.pop("charts", []), meta)
                ctx.view_busy(f"crossplot:{panel_id}", (), False)

        from trame.app import asynchronous
        asynchronous.create_task(_run())

    # the run in progress per panel: a newer refresh bumps it
    _crossplot_gen = {}

    def _crossplot_publish(panel_id, figs, charts, meta):
        """What the panel shows: the figures (one per drawn chart, keyed),
        the caption list and the honest badge; the focus var cleared when the
        focused chart is not the one drawn."""
        meta.pop("drawn", None)
        state[f"ui_crossplot_charts_{panel_id}"] = charts
        state[f"ui_crossplot_figures_{panel_id}"] = figs
        state[f"ui_crossplot_meta_{panel_id}"] = meta
        focus_var = f"ui_crossplot_focus_{panel_id}"
        if getattr(state, focus_var, None) and meta.get("focus") is None:
            state[focus_var] = None

    # a representation highlighted from the tree (app/features/rep_highlight)
    from fespp_on_trame.app.features import rep_highlight as _feature_rep_highlight
    _drop_block_highlight, _hl_state = _feature_rep_highlight.register(
        core,
        _clear_extract_highlights=_clear_extract_highlights,
        _clear_selection_of=_clear_selection_of,
        _nav_note=_nav_note,
        _own_selection=_own_selection,
        _path_for_flat_index=_path_for_flat_index,
        _publish_sel_counts=_publish_sel_counts,
        _refresh_values=_refresh_values,
        _rep_path_of=_rep_path_of,
        _row_of_rep=_row_of_rep)

    # the cross-plot panel (app/features/crossplot_panel)
    from fespp_on_trame.app.features import crossplot_panel as _feature_crossplot_panel
    _drop_crossplot, _drop_crossplot_figures, _register_crossplot = _feature_crossplot_panel.register(
        core,
        _CROSSPLOT_KEYS=_CROSSPLOT_KEYS,
        _CROSSPLOT_SETTABLE=_CROSSPLOT_SETTABLE,
        _CROSSPLOT_WATCHED=_CROSSPLOT_WATCHED,
        _blocks_for_rep=_blocks_for_rep,
        _crossplot_gen=_crossplot_gen,
        _crossplot_pins=_crossplot_pins,
        _crossplot_ys=_crossplot_ys,
        _record_selection=_record_selection,
        _refresh_crossplot=_refresh_crossplot,
        _select_ids=_select_ids)

    return (_CROSSPLOT_WATCHED, _crossplot_ys, _drop_block_highlight, _drop_crossplot, _drop_crossplot_figures, _hl_state, _refresh_crossplot, _register_crossplot)
