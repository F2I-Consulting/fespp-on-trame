"""The cross-plot of the Statistics view: a box or lasso selection sent back to
the 3D views, the settings and pins, the panel registered and dropped."""
from fespp_on_trame.engine import crossplot_dispatch
from fespp_on_trame.engine import view_routing
from fespp_on_trame.engine.vtk_log import capture_vtk_messages


def register(core, *, _CROSSPLOT_KEYS, _CROSSPLOT_SETTABLE, _CROSSPLOT_WATCHED,
             _blocks_for_rep, _crossplot_gen, _crossplot_pins,
             _crossplot_ys, _record_selection,
             _refresh_crossplot, _select_ids):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_drop_crossplot, _drop_crossplot_figures, _register_crossplot)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    source_registry = core.source_registry
    scheduler = core.scheduler
    _drop_sel_inputs = core.selection.drop_inputs
    @controller.set("crossplot_select")
    def crossplot_select(sel, panel_id):
        """Box / lasso on a cross-plot. The client sends the selection's
        GEOMETRY only ({range} or {lasso}, ~100 bytes) — shipping the selected
        points would cost megabytes, and would only cover the SUBSAMPLED
        cloud. The geometry is keyed by the subplot's axis
        ids, which name the chart — hence the Y it was drawn against. The
        full-resolution mask is recomputed here and lights every cell of the
        region, in every 3D view. None clears."""
        try:
            meta = dict(getattr(state, f"ui_crossplot_meta_{panel_id}", None)
                        or {})
            rep = meta.get("rep_path") or ""
            rid = tree.find_node_id(rep) if rep else None
            if rid is not None and (tree.find_type(rid) or "") == "Frame":
                # a channel's samples are frame nodes, not cells of one block:
                # the ring mapping is different and unwired — better no
                # highlight than the wrong cells lit, and the badge says so
                meta["selected"] = ("selection on a well log is not linked"
                                    " to the 3D view" if sel else "")
                state[f"ui_crossplot_meta_{panel_id}"] = meta
                return
            ids, note = [], ""
            if sel:
                key = crossplot_dispatch.chart_key_for_selection(
                    meta.get("axes"), sel)
                if key is None:
                    return
                if key.startswith("pin:"):
                    # a snapshot's cells belong to a past state of the axes:
                    # lighting them from today's arrays would lie
                    meta["selected"] = "pinned chart: selection off"
                    state[f"ui_crossplot_meta_{panel_id}"] = meta
                    return
                y = _crossplot_ys(panel_id)[int(key.split(":", 1)[1])]
                g = lambda k: getattr(state, f"ui_crossplot_{k}_{panel_id}",
                                      None)   # noqa: E731
                ids, note = crossplot_dispatch.selection_cell_ids(
                    state, tree, source_registry, g("x"), y["path"],
                    x_real=g("xreal"), x_ts=g("xts"),
                    y_real=y["real"], y_ts=y["ts"],
                    log_x=bool(g("logx")), log_y=bool(g("logy")), sel=sel)
            blocks = _blocks_for_rep(rep) if rep and ids else []
            # the 3D view one works in: a selection shows in one view, and
            # its cells are that view's selection — the grid's "+" keeps or
            # removes THEM, not a pick's from before (D9)
            lvid = view_routing.resolve_active_render_panel(state) or ""
            _select_ids(blocks, "CELLS", ids, lvid)
            if lvid:
                _drop_sel_inputs(lvid)
                _record_selection(lvid, blocks, "CELLS", ids)
            meta["selected"] = note
            state[f"ui_crossplot_meta_{panel_id}"] = meta
        except Exception as exc:
            print(f"[fespp] crossplot select error ({panel_id}):", exc,
                  flush=True)
            return
        scheduler.mark_all_dirty()
        scheduler.flush()

    def _crossplot_pin(panel_id, key):
        """The "pin" action: "live:i" freezes that chart as a new snapshot,
        "pin:n" drops snapshot n. The focus follows the renumbering (the
        snapshots sit first), or clears when it pointed at the dropped
        snapshot."""
        pins = list(_crossplot_pins.get(panel_id) or [])
        kind, _, idx = str(key or "").partition(":")
        if not idx.isdigit():
            return
        idx = int(idx)
        focus_var = f"ui_crossplot_focus_{panel_id}"
        if kind == "live":
            ys = _crossplot_ys(panel_id)
            if idx >= len(ys):
                return
            g = lambda k: getattr(state, f"ui_crossplot_{k}_{panel_id}",
                                  None)   # noqa: E731
            try:
                with capture_vtk_messages(state):
                    snap = crossplot_dispatch.snapshot_chart(
                        state, tree, source_registry, g("x"), ys[idx],
                        g("color"), x_real=g("xreal"), x_ts=g("xts"),
                        log_x=bool(g("logx")), log_y=bool(g("logy")))
            except Exception as exc:
                print(f"[fespp] crossplot pin error ({panel_id}):", exc,
                      flush=True)
                return
            if snap is None:
                return
            pins.append(snap)
        elif kind == "pin" and idx < len(pins):
            pins.pop(idx)
            # `pin:n` is POSITIONAL: the snapshots after the dropped one move
            # up, so the magnifier that names one by that key moves with them,
            # or it would quietly name another snapshot
            f_kind, _, f_idx = str(getattr(state, focus_var, None)
                                   or "").partition(":")
            if f_kind == "pin" and f_idx.isdigit():
                if int(f_idx) == idx:
                    state[focus_var] = None
                elif int(f_idx) > idx:
                    state[focus_var] = f"pin:{int(f_idx) - 1}"
        else:
            return
        _crossplot_pins[panel_id] = pins
        _refresh_crossplot(panel_id)

    @controller.set("crossplot_set")
    def crossplot_set(key, value, panel_id):
        """One entry point for the cross-plot toolbar: the widget names the
        control, the server writes the per-panel var (which the watcher
        registered in _register_crossplot turns into a refresh) — or performs
        the "pin" action."""
        # the WIDGET's contract, not the state-key list: the axes are the
        # Statistics view's, choices / meta / charts / figures are
        # server-owned, and `figures = None` is precisely the value that
        # blanks the panel
        if panel_id not in (getattr(state, "ui_crossplot_panels", None) or ()):
            return
        if key == "pin":
            _crossplot_pin(panel_id, value)
            return
        if key not in _CROSSPLOT_SETTABLE:
            return
        if key == "focus":
            kind, _, idx = str(value or "").partition(":")
            value = value if kind in ("live", "pin") and idx.isdigit() else None
        state[f"ui_crossplot_{key}_{panel_id}"] = value

    def _register_crossplot(panel_id):
        """The Statistics view's cross-plot (panel id = its view id + "x") was
        just mounted: registry entry, the per-panel vars seeded, the watchers
        that turn an axis edit into a refresh, and the first figure."""
        panels = list(getattr(state, "ui_crossplot_panels", None) or [])
        if panel_id not in panels:
            state.ui_crossplot_panels = panels + [panel_id]
        _crossplot_pins.pop(panel_id, None)
        # figures: ALWAYS a list, never None — the widget draws one plotly
        # figure per entry, and a None there throws in the Vue render and
        # blanks the whole panel.
        values = {"x": None, "xreal": None, "xts": None,
                  "ys": [{"path": None, "real": None, "ts": None}],
                  "color": None, "logx": False, "logy": False,
                  "choices": [], "meta": {}, "charts": [], "focus": None,
                  "figures": []}
        for k in _CROSSPLOT_KEYS:
            state[f"ui_crossplot_{k}_{panel_id}"] = values[k]

        def _on_opts(**_kw):
            _refresh_crossplot(panel_id)
        try:
            state.change(*(f"ui_crossplot_{k}_{panel_id}"
                           for k in _CROSSPLOT_WATCHED))(_on_opts)
        except Exception:
            pass
        _refresh_crossplot(panel_id)

    def _drop_crossplot_figures(panel_id):
        """The charts of a cross-plot panel go, its settings stay: what a
        failed reseed must not leave on screen as if it were fresh."""
        if panel_id in (getattr(state, "ui_crossplot_panels", None) or ()):
            _crossplot_gen[panel_id] = _crossplot_gen.get(panel_id, 0) + 1
            state[f"ui_crossplot_figures_{panel_id}"] = []
            state[f"ui_crossplot_charts_{panel_id}"] = []

    def _drop_crossplot(panel_id):
        """A closed cross-plot leaves the registry, or its watcher keeps
        recomputing a figure nobody shows (and crossplot_set keeps
        accepting writes for it)."""
        xps = list(getattr(state, "ui_crossplot_panels", None) or [])
        if panel_id in xps:
            state.ui_crossplot_panels = [p for p in xps if p != panel_id]
            for k in _CROSSPLOT_KEYS:
                # the figures are the heavy part and are `.length`-read by
                # a possibly still-mounted widget: empty, never None; the
                # chart list the same way
                state[f"ui_crossplot_{k}_{panel_id}"] = (
                    [] if k in ("figures", "charts") else None)
        _crossplot_pins.pop(panel_id, None)
    return (_drop_crossplot, _drop_crossplot_figures, _register_crossplot)
