"""A panel closes (`on_panel_closed`): every family forgets it — its
per-view state, its listeners, its selection, its isolates — and the
right-click menu of the trees (`context_action`) dispatched by action.

(Moved out of app/boot, overhaul slice 10.)"""
import time

from fespp_on_trame.app.views import per_view_state

# how long an entry chosen on a property not read yet waits for its read
# (the question of a big read included) before it is forgotten
_READ_WAIT = 300.0


def register(core, *, _CALC_KEYS, _CROSSPLOT_WATCHED, _clear_selection_of,
             _close_compare_view, _derived_gc,
             _drop_block_highlight, _slicer_armed,
             _volumetrics, _wired_vids, _xml_open_from_path):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    lifecycle = core.lifecycle
    displays = core.displays
    selection = core.selection
    @controller.set("on_panel_closed")
    def on_panel_closed(panel_id):
        """A panel closes (the dockview's ×): every family forgets it
        (app/core/lifecycle, "view_closed")."""
        lifecycle.emit("view_closed", vid=str(panel_id))

    @lifecycle.on("view_closed")
    def _closed_panel(vid):
        """What the panel itself held: its displays, its extracts, formulas,
        selection, slicer, contact planes, its figure and its listeners."""
        panel_id = vid
        _close_compare_view(panel_id)
        # a render view's per-view grid isolates too (view_manager releases
        # the composite scene itself right after this), its selection
        # extracts and its selection
        # everything it drew outside its composite (app/scene/displays):
        # isolates, extracts, overlay, contact planes, wellheads
        displays.close_view(str(panel_id))
        # its cells, its pick target and its selection extracts
        selection.close_view(str(panel_id))
        # its formulas' arrays leave the blocks unless another view shows them
        _derived_gc(closing=str(panel_id))
        _volumetrics.pop(str(panel_id), None)
        marks = dict(getattr(state, "ui_strati_titles", None) or {})
        if marks.pop(str(panel_id), None) is not None:
            state.ui_strati_titles = marks
        _slicer_armed.difference_update(
            {k for k in _slicer_armed if k[0] == str(panel_id)})
        if selection.owner_vid == str(panel_id):
            try:
                _clear_selection_of(str(panel_id))
                _drop_block_highlight()
            except Exception as exc:
                print(f"[fespp] selection of a closed view ({panel_id}):", exc, flush=True)
        # the panel's change handlers (its cross-plot's settings, calculator
        # input) go with it — trame never unregisters
        per_view_state.drop_listeners(
            state,
            [f"ui_crossplot_{k}_{panel_id}x" for k in _CROSSPLOT_WATCHED]
            + [f"ui_calc_rep_{panel_id}", f"ui_calc_expr_{panel_id}"])
        _wired_vids.discard(str(panel_id))
        # calculator: the panel's vars die, the RECIPES survive (session
        # store) — reopening lists them again, as the Statistics view's
        # selection comes back with its panel.
        calcs = list(getattr(state, "ui_calc_panels", None) or [])
        if panel_id in calcs:
            state.ui_calc_panels = [p for p in calcs if p != panel_id]
            for k in _CALC_KEYS:
                # the figure var is member-accessed by a possibly still-
                # mounted plotly widget (second tab): empty, never None
                state[f"ui_calc_{k}_{panel_id}"] = (
                    {"data": [], "layout": {}} if k == "figure" else None)

    # entries chosen on a property not read yet: {path: (action, since)}
    _after_read = {}

    @state.change("context_action")
    def _on_context_action(context_action=None, **_):
        # right-click menu choice from any render tree -> dispatch by action.
        req = context_action or {}
        action, path = req.get("action"), req.get("path")
        if not action or not path:
            return
        if req.get("read") and path not in (getattr(state, "ui_loaded_array_paths", None) or ()):
            # its box ticked first, in the tree of the 3D view in use, as a
            # click on it would (the question of a big read included); the
            # entry runs once it is read
            _after_read[path] = (action, time.monotonic())
            sel = list(getattr(state, "selected_paths", None) or [])
            state.tree_tick = {"vid": str(getattr(state, "fespp_last_render_panel_id", "") or ""),
                               "kind": "render", "paths": sel + ([path] if path not in sel else []),
                               "t": time.time() * 1000}
            return
        _dispatch(action, path)

    @state.change("ui_loaded_array_paths")
    def _on_read(ui_loaded_array_paths=None, **_):
        loaded = set(ui_loaded_array_paths or ())
        now = time.monotonic()
        for path, (action, since) in list(_after_read.items()):
            if path in loaded or now - since > _READ_WAIT:
                _after_read.pop(path, None)
                if path in loaded:
                    _dispatch(action, path)

    def _dispatch(action, path):
        if action == "add-to-stats":
            controller.add_to_stats(path)
        elif action == "add-to-welllog":
            controller.add_to_welllog(path)
        elif action == "add-selected-to-welllog":
            controller.add_to_welllog(path, True)
        elif action == "calculator":
            controller.open_calculator(path)
        elif action in ("center-3d", "zoom-3d"):
            # the active 3D view turns to the object, or comes closer too
            controller.nav_frame_node(path, None, action == "zoom-3d")
        elif action in ("geometry-slicer", "property-slicer"):
            controller.open_slicer(action, path)
        elif action == "use-as-cube":
            controller.time_depth_from_grid(path)
        elif action in (getattr(core.ctx, "context_actions_extra", None) or {}):
            # an entry a feature added to the menu (data_tree's ``ui_tree_extra_actions``)
            core.ctx.context_actions_extra[action](path)
        elif action == "xml":
            _xml_open_from_path(path)
