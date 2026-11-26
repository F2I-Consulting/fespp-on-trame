"""the title bar's hand and mouse (widgets/title3dview)
HAND: the scene moves — drag to rotate, wheel to zoom, right or middle
drag to pan. MOUSE: show position — the scene is FIXED (the view panel
stops every press and every wheel notch before vtk.js sees them) and
the pointer reads what is under it: position, block, wellbore, cell,
property value with its unit. Back to the hand to move the scene again.

(Moved out of app/boot, overhaul slice 10.)"""


def register(core, *, _codes_mask_sync, _eye_driven_colors, _hide_nan_grids, _hide_nan_set,
             _is_property_path, _property_label, _push_active_array_label,
             _real_idx_for, _refresh_compare, _refresh_crossplot,
             _refresh_welllog, _rep_path_of,
             _selection_off, _set_tool_target):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_apply_cmap_nodes, _cmap_apply_range, _cmap_array_path, _cmap_data_range, _cmap_done, _cmap_edges, _cmap_exp, _cmap_pushed, _cmap_target, _cmap_tfs, _cursor_mode_off, _hex, _lut_range, _presets, _push_colormap_state, _table_path, cmap_preset)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    cards = core.cards
    # --- the title bar's hand and mouse (widgets/title3dview) --------------
    # HAND: the scene moves — drag to rotate, wheel to zoom, right or middle
    # drag to pan. MOUSE: show position — the scene is FIXED (the view panel
    # stops every press and every wheel notch before vtk.js sees them) and
    # the pointer reads what is under it: position, block, wellbore, cell,
    # property value with its unit. Back to the hand to move the scene again.
    def _cursor_mode_off(view_id):
        vid = str(view_id or "")
        if getattr(state, f"ui_cursor_mode__{vid}", False):
            state[f"ui_cursor_mode__{vid}"] = False
            state[f"ui_cursor_pos__{vid}"] = ""

    @controller.set("view_cursor_mode")
    def view_cursor_mode(view_id, on):
        """True: the mouse (show position, scene fixed); False: the hand."""
        vid = str(view_id or "")
        if not on:
            _cursor_mode_off(vid)
            return
        state[f"ui_cursor_mode__{vid}"] = True
        # a selection mode wants the same left button: one at a time
        from fespp_on_trame.app.views.tools_config import MODE_TOOLS
        keys = {m["key"] for m in MODE_TOOLS}
        cur = cards.keys(vid)
        if any(k in keys for k in cur):
            cards.set(vid, [k for k in cur if k not in keys])
            cards.sync_modes(vid)
            # the selection tool went off: so do its cells
            _selection_off(vid)

    # There is no set_array: the colorBy is owned by the tree's property
    # eyes (on_eye_changed); the Attributes card only displays it.

    # the Colormap card: the view-scoped colour table of the active array (app/features/colormap_card)
    from fespp_on_trame.app.features import colormap_card as _feature_colormap_card
    _apply_pwf, _cmap_array_path, _cmap_components, _cmap_data_range, _cmap_done, _cmap_edges, _cmap_exp, _cmap_pushed, _cmap_target, _cmap_tfs, _core_opacity_nodes, _edges, _exp_remap, _find_scalar_bar, _hex, _lut_range, _node_positions, _presets, _push_colormap_state, _rgb, _set_node_positions, _table_path = _feature_colormap_card.register(
        core,
        _eye_driven_colors=_eye_driven_colors,
        _hide_nan_flagged=lambda *a, **k: _hide_nan_flagged(*a, **k),
        _hide_nan_grids=_hide_nan_grids,
        _is_property_path=_is_property_path,
        _property_label=_property_label,
        _real_idx_for=_real_idx_for,
        _rep_path_of=_rep_path_of,
        _set_tool_target=_set_tool_target)

    # the Colormap card's edits (app/features/colormap_edits)
    from fespp_on_trame.app.features import colormap_edits as _feature_colormap_edits
    _apply_cmap_nodes, _cmap_apply_range, _hide_nan_flagged, cmap_preset = _feature_colormap_edits.register(
        core,
        _apply_pwf=_apply_pwf,
        _codes_mask_sync=_codes_mask_sync,
        _cmap_array_path=_cmap_array_path,
        _cmap_components=_cmap_components,
        _cmap_data_range=_cmap_data_range,
        _cmap_done=_cmap_done,
        _cmap_exp=_cmap_exp,
        _cmap_target=_cmap_target,
        _cmap_tfs=_cmap_tfs,
        _core_opacity_nodes=_core_opacity_nodes,
        _edges=_edges,
        _exp_remap=_exp_remap,
        _find_scalar_bar=_find_scalar_bar,
        _hide_nan_grids=_hide_nan_grids,
        _hide_nan_set=_hide_nan_set,
        _lut_range=_lut_range,
        _node_positions=_node_positions,
        _presets=_presets,
        _property_label=_property_label,
        _push_active_array_label=_push_active_array_label,
        _push_colormap_state=_push_colormap_state,
        _refresh_compare=_refresh_compare,
        _refresh_crossplot=_refresh_crossplot,
        _refresh_welllog=_refresh_welllog,
        _rgb=_rgb,
        _set_node_positions=_set_node_positions)

    return (_apply_cmap_nodes, _cmap_apply_range, _cmap_array_path, _cmap_data_range, _cmap_done, _cmap_edges, _cmap_exp, _cmap_pushed, _cmap_target, _cmap_tfs, _cursor_mode_off, _hex, _lut_range, _presets, _push_colormap_state, _table_path, cmap_preset)
