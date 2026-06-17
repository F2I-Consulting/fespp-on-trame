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

from fespp_on_trame.app.core.engine import (
    panel_resolver, source_resolver, realization_dispatch,
)


def on_active_array_change(state, controller, source_registry, tree,
                           ui_active_array_by_rep, server=None):
    """Drive ColorBy on every loaded rep from the active-array map.

    Also enforces per-view visibility AFTER each ColorBy: sources
    that don't have a display in the active view yet (e.g. an
    IjkGrid pipeline created in another panel after this panel
    was instantiated) get lazily created by
    `displays_for_rep_path → GetDisplayProperties`, with PV's
    default `Vis=1 Rep='Outline'`. Without this enforcement they
    paint phantom outlines on top of an otherwise-empty / hidden
    panel.

    For MR properties, the realization choice is read from the
    active panel's `ui_active_realization_by_array_by_view` bucket
    (the legacy flat `ui_active_array_by_rep` map mirrors that panel,
    so reading from the active panel's realization bucket keeps the
    flat map and the per-view realization in sync). When `server` is
    not provided the realization lookup is skipped — the resolver
    falls back to the legacy unsuffixed VTK array name."""
    view = pvsimple.GetActiveView()
    loaded = list(state.ui_loaded_rep_paths or [])
    active_map = ui_active_array_by_rep or {}
    hidden_set = set(state.ui_hidden_rep_paths or [])

    active_panel_id = None
    panel_realizations: dict = {}
    if server is not None:
        active_panel_id = panel_resolver.active_panel_id(server)
        if active_panel_id is not None:
            by_view = state.ui_active_realization_by_array_by_view or {}
            panel_realizations = by_view.get(active_panel_id) or {}

    for rep_path in loaded:
        array_path = active_map.get(rep_path)
        realization_idx = panel_realizations.get(array_path) if array_path else None
        source_resolver.apply_color_array(
            source_registry, tree, rep_path, array_path,
            realization_idx=realization_idx,
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
        # Re-assert slice / clip visibility — ColorBy doesn't touch
        # the rep's Show/Hide, but a freshly-coloured clip needs its
        # `_apply` to re-Show (the clip's display might have been
        # implicitly recreated by `displays_for_rep_path`), and the
        # rep source must stay hidden when slice / clip is enabled.
        # Phase 1.b.1: slice/clip moved from the per-rep wrappers to
        # per-(rep, view) RepInScene; iterate scenes instead.
        try:
            from trame.app import get_server
            scenes = getattr(get_server().context, "scene_registry", None)
            if scenes is not None:
                for scene in scenes.all_scenes():
                    rep_in_scene = scene.get_rep(rep_path)
                    if rep_in_scene is None:
                        continue
                    try:
                        rep_in_scene.refresh_planes_after_property_change()
                    except Exception as exc:
                        print(f"[WARNING] refresh_planes {scene.view_id}/{rep_path}: {exc}")
        except Exception as exc:
            print(f"[WARNING] active_array scene refresh: {exc}")
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
    realizations_by_view = state.ui_active_realization_by_array_by_view or {}
    panel_realizations = realizations_by_view.get(panel_id) or {}
    shown_bars: set = set()
    for rep_path, array_path in panel_map.items():
        if not rep_path or not array_path:
            continue
        realization_idx = panel_realizations.get(array_path)
        source_resolver.apply_color_array(
            source_registry, tree, rep_path, array_path, view=view,
            realization_idx=realization_idx,
        )
        # Color bar: per-array (LUT is keyed by array name globally),
        # one visible bar per array per view. Skip dups when several
        # reps share the same array. For MR properties, the suffixed
        # name `<title>_real_<idx>` gives each realization its own
        # LUT — so view A on real 3 and view B on real 7 keep
        # independent color bars even when both color by "K".
        try:
            assoc, name = source_resolver.resolve_array_for_path(
                source_registry, tree, rep_path, array_path,
                realization_idx=realization_idx,
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
                    # NOTE: do NOT raw-write bar.Visibility = 1 here.
                    # apply_color_array above invoked
                    # display.SetScalarBarVisibility(view, True) which goes through
                    # vtkSMTransferFunctionManager. Raw writes bypass the manager's
                    # bookkeeping and desync from the view's representation list
                    # under per-view LUT scope, surfacing a duplicate bar on other
                    # views. The bug was visible when opening Stats / Distribution
                    # panels triggered apply_panel_coloring via the panel-state
                    # publish chain.
                    # (any Title / format writes BELOW stay — they are appearance.)
                    bar.Title = name
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
    panels keep their independent coloring.

    For multi-realization (`MultiRealization` /
    `MultiRealizationTimeSeries`) properties, a per-view realization
    choice is tracked in
    `state.ui_active_realization_by_array_by_view`. On first
    activation in a panel the choice defaults to the smallest
    available index. The plugin loads every realization that's
    materialised in the tree (parent selection propagates to all
    children), so each view's ColorBy just picks its own suffixed
    VTK array `<title>_real_<idx>` without sharing with other
    views."""
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
    # Remember the previous array (if any) so we can release its
    # realization slot when it's replaced or deactivated.
    prev_array_path = panel_map.get(r_path)
    if prev_array_path == array_path:
        panel_map.pop(r_path, None)
        new_value = None
    else:
        panel_map[r_path] = array_path
        new_value = array_path
    by_view[bucket_key] = panel_map
    state.ui_active_array_by_rep_by_view = by_view

    # MR bookkeeping — set / clear the per-view realization choice and
    # reconcile with the plugin when the (path, idx) union shifts.
    prev_is_mr_drop = (
        prev_array_path is not None
        and prev_array_path != new_value
        and realization_dispatch.is_multirealization_property(tree, prev_array_path)
    )
    if prev_is_mr_drop:
        realization_dispatch.clear_active_realization_for_view(
            state, bucket_key, prev_array_path,
        )

    new_realization_idx = None
    new_is_mr = (
        new_value is not None
        and realization_dispatch.is_multirealization_property(tree, new_value)
    )
    if new_is_mr:
        new_realization_idx = realization_dispatch.get_active_realization_for_view(
            state, bucket_key, new_value,
        )
        if new_realization_idx is None:
            new_realization_idx = realization_dispatch.default_realization_for(
                state, tree, new_value,
            )
            if new_realization_idx is not None:
                realization_dispatch.set_active_realization_for_view(
                    state, bucket_key, new_value, new_realization_idx,
                )

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
    # panel. For MR properties, the per-view realization choice
    # threads through so the resolver picks the suffixed VTK array
    # name (`<title>_real_<idx>`).
    source_resolver.apply_color_array(
        source_registry, tree, r_path, new_value, view=view,
        realization_idx=new_realization_idx,
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
