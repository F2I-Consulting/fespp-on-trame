"""Active-array dispatch — driving ColorBy from the per-rep / per-view
active-array maps and handling the tree's data-array eye toggles.

Extracted from `boot.initialize_fespp_engine`.

Three concerns covered:
  - `on_active_array_change(...)` — fires when the global map
    `state.ui_active_array_by_rep` is mutated; re-applies ColorBy on
    every loaded rep.
  - `on_active_array_by_view_change(...)` — derives the per-panel
    `panel_has_ts_by_id` flag from the per-view active-array map.
    A panel has TS iff at least one of its active arrays resolves
    to a TimeSeries / MultiRealizationTimeSeries node (or a
    descendant of one). Drives the per-view TimeControl visibility.
  - `toggle_dataarray_color(...)` — tree eye click on a data-array
    node: if this array is the active one of its rep *in the
    target view*, deactivate (SolidColor); otherwise activate it
    (the previous active array on the same rep in that view loses
    its eye)."""
from paraview import simple as pvsimple

from fespp_on_trame.app.core.engine import panel_resolver, source_resolver


def on_active_array_change(state, controller, source_registry, tree,
                           ui_active_array_by_rep):
    """Drive ColorBy on every loaded rep from the active-array map.

    Also enforces per-view visibility AFTER each ColorBy: sources
    that don't have a display in the active view yet (e.g. an
    IjkGrid pipeline created in another panel after this panel
    was instantiated) get lazily created by
    `displays_for_rep_path → GetDisplayProperties`, with PV's
    default `Vis=1 Rep='Outline'`. Without this enforcement they
    paint phantom outlines on top of an otherwise-empty / hidden
    panel."""
    view = pvsimple.GetActiveView()
    loaded = list(state.ui_loaded_rep_paths or [])
    active_map = ui_active_array_by_rep or {}
    hidden_set = set(state.ui_hidden_rep_paths or [])
    for rep_path in loaded:
        source_resolver.apply_color_array(
            source_registry, tree, rep_path, active_map.get(rep_path),
        )
        if rep_path in hidden_set and view is not None:
            displays = source_resolver.displays_for_rep_path(
                source_registry, rep_path, view=view,
            )
            for d in displays:
                try:
                    d.Visibility = 0
                    sm = getattr(d, "SMProxy", None)
                    if sm is not None:
                        sm.UpdateVTKObjects()
                except Exception:
                    pass
    if view is not None:
        pvsimple.Render(view=view)
    controller.view_update()


def apply_panel_coloring(state, source_registry, tree, panel_id, view):
    """Apply ColorBy on `view`'s displays from
    `state.ui_active_array_by_rep_by_view[panel_id]` AND show the
    matching scalar bar.

    Used right after a panel is created from a replicated reference:
    `_seed_per_view_hidden_state` copies the active-array bucket from
    the ref panel to the new panel, but copying the state alone
    doesn't trigger any handler that re-applies `ColorBy` on the new
    view's displays. The `_copy_display_props` step in
    `_replicate_visibility` does set `ColorArrayName` field-wise, but
    PV6 needs the full `pvsimple.ColorBy()` call to bind the lookup
    table + scalar mapping correctly — without it the display ends
    up in SolidColor visually even though the field looks right.

    `pvsimple.ColorBy` itself doesn't create / show the color bar in
    the target view, so we explicitly turn its visibility on per
    LUT once the array name is known."""
    by_view = state.ui_active_array_by_rep_by_view or {}
    panel_map = by_view.get(panel_id) or {}
    if not panel_map or view is None:
        return
    shown_bars: set = set()
    for rep_path, array_path in panel_map.items():
        if not rep_path or not array_path:
            continue
        source_resolver.apply_color_array(
            source_registry, tree, rep_path, array_path, view=view,
        )
        # Color bar: per-array (LUT is keyed by array name globally),
        # one visible bar per array per view. Skip dups when several
        # reps share the same array.
        try:
            assoc, name = source_resolver.resolve_array_for_path(
                source_registry, tree, rep_path, array_path,
            )
        except Exception:
            assoc, name = None, None
        if not name or name in shown_bars:
            continue
        shown_bars.add(name)
        try:
            lut = pvsimple.GetColorTransferFunction(name)
            if lut is not None:
                bar = pvsimple.GetScalarBar(lut, view)
                if bar is not None:
                    bar.Title = name
                    bar.Visibility = 1
                    bar.RangeLabelFormat = '%-#6.3g'
                    bar.Resizable = 1
        except Exception:
            pass
    try:
        pvsimple.Render(view=view)
    except Exception:
        pass


def on_active_array_by_view_change(state, tree, ui_active_array_by_rep_by_view):
    """Derive `state.panel_has_ts_by_id` from the per-view active-
    array map. Idempotent — only writes back when the result
    differs from the current value."""
    if tree is None:
        return
    by_view = ui_active_array_by_rep_by_view or {}
    out: dict = {}
    for panel_id, panel_map in by_view.items():
        has_ts = False
        for array_path in (panel_map or {}).values():
            if not array_path:
                continue
            node_id = tree.find_node_id(array_path)
            if node_id is None:
                continue
            type_node = tree.find_type(node_id)
            if type_node in ("TimeSeries", "MultiRealizationTimeSeries"):
                has_ts = True
                break
            if tree.find_parent_node_id_with_type(node_id, "TimeSeries") is not None:
                has_ts = True
                break
        out[panel_id] = has_ts
    if out != (state.panel_has_ts_by_id or {}):
        state.panel_has_ts_by_id = out


def toggle_dataarray_color(state, controller, server, source_registry, tree,
                           array_path, panel_id=None):
    """Tree eye on a data-array node.

    Two state writes happen on every click:
      - `ui_active_array_by_rep_by_view[panel_id][r_path]`: per-view
        map driving the tree's annotation rendering and the
        ColorBy application below.
      - `ui_active_array_by_rep[r_path]`: mirrored from the active
        panel's bucket; consumed by Activator / solid_color_panel
        which still read the flat map.
    ColorBy is applied on the target view's displays only — other
    panels keep their independent coloring."""
    if not array_path:
        return
    node_id = tree.find_node_id(array_path)
    if node_id is None:
        return
    r_id = tree.find_representation_node(node_id)
    r_path = tree.find_path(r_id) if r_id is not None else None
    if not r_path:
        return

    view, html_view = panel_resolver.resolve_view_and_html_view(server, panel_id)
    bucket_key = panel_id or panel_resolver.active_panel_id(server) or "_active"

    by_view = dict(state.ui_active_array_by_rep_by_view or {})
    panel_map = dict(by_view.get(bucket_key, {}) or {})
    if panel_map.get(r_path) == array_path:
        panel_map.pop(r_path, None)
        new_value = None
    else:
        panel_map[r_path] = array_path
        new_value = array_path
    by_view[bucket_key] = panel_map
    state.ui_active_array_by_rep_by_view = by_view

    # Mirror to legacy global iff this is the active panel.
    active = panel_resolver.active_panel_id(server)
    if active and active == bucket_key:
        mirror = dict(state.ui_active_array_by_rep or {})
        if new_value is None:
            mirror.pop(r_path, None)
        else:
            mirror[r_path] = new_value
        state.ui_active_array_by_rep = mirror

    # When activating a property in a view where the rep is currently
    # hidden (e.g. clicking the property eye on an empty render
    # panel), implicitly show the rep — the user expects
    # "show + color", not "color a hidden rep". Drop the rep from the
    # hidden bucket and replay the IjkGrid / ExtractBlock show in the
    # target view.
    if new_value is not None:
        hidden_by_view = dict(state.ui_hidden_rep_paths_by_view or {})
        hidden_bucket = list(hidden_by_view.get(bucket_key, []) or [])
        if r_path in hidden_bucket:
            hidden_bucket.remove(r_path)
            hidden_by_view[bucket_key] = hidden_bucket
            state.ui_hidden_rep_paths_by_view = hidden_by_view
            if active and active == bucket_key:
                state.ui_hidden_rep_paths = list(hidden_bucket)
            ijk = source_registry.get_ijk_grid(r_path)
            if ijk is not None:
                try:
                    ijk.show(view=view)
                except Exception:
                    pass
            else:
                eb = source_registry.get_extract_block(r_path)
                if eb is not None and eb.source is not None and view is not None:
                    try:
                        pvsimple.Show(eb.source, view=view)
                    except Exception:
                        pass

    # Apply ColorBy on the target view's displays. Do this
    # explicitly here (rather than relying on @state.change of the
    # global map) because the per-view map mutation alone wouldn't
    # trigger the legacy active-view-only handler for a non-active
    # panel.
    source_resolver.apply_color_array(
        source_registry, tree, r_path, new_value, view=view,
    )
    # When deactivating (new_value is None), the scalar bar for the
    # old array is orphaned in this view — sweep stale bars so the
    # legend goes away when the rep flips back to SolidColor.
    if new_value is None:
        source_resolver.hide_unused_scalar_bars(view=view)
    if view is not None:
        try:
            pvsimple.Render(view=view)
        except Exception:
            pass
    if html_view is not None:
        try:
            html_view.update()
        except Exception:
            pass
    else:
        try:
            controller.view_update()
        except Exception:
            pass
