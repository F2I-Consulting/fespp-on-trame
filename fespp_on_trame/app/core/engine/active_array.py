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
from fespp_on_trame.app.core import element_type


def _is_channel_rep(element_type_obj) -> bool:
    """A wellbore-frame CHANNEL container = a rep whose visibility policy
    is ONE_AT_A_TIME (only ChannelFrameRep)."""
    return element_type_obj.visibility_policy() == element_type.VisibilityPolicy.ONE_AT_A_TIME


def _show_channel_active_view(tree, rep_path, array_path, view):
    """If `array_path` is a wellbore-frame CHANNEL, SHOW it (exclusive,
    one-at-a-time) in `view` so a plain channel selection renders the
    log via its own per-channel extractor. No-op for non-channel arrays
    and when no RepInScene renders the frame in this view."""
    try:
        node_id = tree.find_node_id(array_path)
        r_id = tree.find_representation_node(node_id) if node_id is not None else None
        if r_id is None or r_id == node_id or not _is_channel_rep(element_type.for_kind(tree.find_type(r_id))):
            return
        rep_in_scene = source_resolver._scene_rep_for_view(rep_path, view)
        if rep_in_scene is not None:
            rep_in_scene.set_channel_visible(array_path, True)
    except Exception:
        pass


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
        # Wellbore-frame channel: SHOW it (exclusive) in the active view
        # BEFORE coloring — on a plain channel SELECTION (data_load
        # auto-activates frame→channel, no eye click) this is what renders
        # the log via its own per-channel extractor.
        if array_path and view is not None:
            _show_channel_active_view(tree, rep_path, array_path, view)
        source_resolver.apply_color_array(
            source_registry, tree, rep_path, array_path, view=view,
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
        # Re-assert slice / clip visibility — ColorBy doesn't touch the
        # rep's Show/Hide, but a freshly-coloured clip needs its `_apply`
        # to re-Show (its display might have been implicitly recreated by
        # `displays_for_rep_path`), and the rep source must stay hidden
        # when slice / clip is enabled. Slice/clip live on per-(rep, view)
        # RepInScene, so iterate scenes.
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
                        pass
        except Exception as exc:
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
            assoc, name, _ = source_resolver.resolve_array_for_path(
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
                    # Do NOT raw-write bar.Visibility = 1 here: visibility
                    # must go through display.SetScalarBarVisibility (done
                    # by apply_color_array above) so the
                    # vtkSMTransferFunctionManager keeps its bookkeeping;
                    # a raw write desyncs from the view's representation
                    # list under per-view LUT scope and surfaces a
                    # duplicate bar on other views. The Title / format
                    # writes below are appearance-only and safe.
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
            if element_type.for_kind(type_node).is_time_series():
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

    # Wellbore-frame channel detection: the toggled node is a channel iff
    # its rep ancestor is a ONE_AT_A_TIME frame (ChannelFrameRep) AND the
    # ancestor is not the node itself (a channel walks UP past its own
    # property kind to the Frame). MarkerFrame (MULTI) /
    # SeismicWellboreFrame have different policies so they never
    # false-positive. The channel leaf path == array_path.
    rep_kind = tree.find_type(r_id) if r_id is not None else None
    is_channel = _is_channel_rep(element_type.for_kind(rep_kind)) and r_id != node_id

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

    # This eye picks the COLOUR ARRAY and never touches visibility — showing
    # or hiding a rep is the geometry eye's job alone (see
    # `visibility.toggle_rep_visibility`). Colouring a hidden rep is a legal,
    # useful state: it is what lets a user hide the grid and keep its blocked
    # wellbores / channels coloured, and swap the array without the grid
    # popping back each time.
    #
    # This used to implicitly un-hide + Show ("the user expects show + color,
    # not color a hidden rep"), which broke that outright — and worse, it
    # replayed the show on the LEGACY `eb.source` while
    # `toggle_rep_visibility` hides whatever `sources_for_rep_path` returns.
    # The two disagreed, so a rep re-shown from here escaped the next hide and
    # lingered on screen in SolidColor.

    # Apply ColorBy on the target view's displays explicitly here
    # (rather than relying on @state.change of the global map) because
    # the per-view map mutation alone wouldn't trigger the active-view-
    # only handler for a non-active panel. For MR properties the per-view
    # realization choice threads through so the resolver picks the
    # suffixed VTK array name (`<title>_real_<idx>`).
    # Re-point the FRAME's per-view extractor at the chosen channel (one
    # log at a time) BEFORE coloring — apply_color_array re-reads the
    # channel's OWN extractor arrays via resolve_array_for_path, so the
    # SHOW (which materialises + exclusively shows that channel's
    # extractor) must happen first. Toggling the channel OFF (new_value
    # is None) just Hides that channel's extractor.
    if is_channel:
        try:
            rep_in_scene = source_resolver._scene_rep_for_view(r_path, view)
            if rep_in_scene is not None:
                rep_in_scene.set_channel_visible(
                    array_path, new_value is not None,
                )
        except Exception:
            pass
    resolved = source_resolver.apply_color_array(
        source_registry, tree, r_path, new_value, view=view,
        realization_idx=new_realization_idx, clear_on_empty=True,
    )
    # Make the COE follow the channel actually VIEWED. The editor is
    # driven by `active_color_array_name` (set by the activator's
    # active-NODE path), which an eye click does NOT update. Publish the
    # viewed channel as the COE's active array + path (the COE reads the
    # channel's OWN extractor via
    # `channel_extractor_for(active_color_array_path)`).
    if is_channel:
        if new_value is not None:
            ch_title = tree.find_title(node_id) or ""
            ch_kind = tree.find_type(node_id) or ""
            state.active_representation_path = r_path
            state.active_color_array_name = ch_title
            state.active_color_array_path = array_path
            state.active_property_kind = (
                ch_kind if ch_kind in (
                    "ContinuousProperty", "DiscreteProperty", "CategoricalProperty"
                ) else ""
            )
            try:
                controller.update_color_editor(ch_title)
            except Exception:
                pass
        else:
            # Channel hidden — leave colour-map mode (back to Solid).
            state.active_color_array_name = ""
            state.active_property_kind = ""
            state.active_color_array_path = ""
    # The user switched the eye to a property that resolves to NO
    # renderable array (a partial stub, a missing array, or — for a
    # wellbore frame — a log on a partition the extractor discards).
    # The colour was just cleared; tell the user why nothing painted
    # instead of leaving them guessing. (Generic: fires for ANY rep.)
    if new_value is not None and resolved is False:
        title = tree.find_title(node_id) or ""
        state.empty_color_snackbar_text = (
            f"“{title}”: no data to display on this representation"
        )
        # Reset then set so re-toggling the SAME property re-fires the
        # snackbar (the var change is what triggers it).
        state.empty_color_snackbar_visible = False
        state.empty_color_snackbar_visible = True
        # Roll the eye back to SolidColor: a property with no renderable data
        # must not stay "active" (an open array-eye on an empty property).
        # Drop it from the per-view + global active-array maps and release any
        # MR realization slot it just claimed — same end state as an eye-OFF
        # click, so the rep falls back to its own SolidColor representation.
        panel_map.pop(r_path, None)
        by_view[bucket_key] = panel_map
        state.ui_active_array_by_rep_by_view = by_view
        if active and active == bucket_key:
            mirror = dict(state.ui_active_array_by_rep or {})
            mirror.pop(r_path, None)
            state.ui_active_array_by_rep = mirror
        if new_is_mr:
            realization_dispatch.clear_active_realization_for_view(
                state, bucket_key, new_value,
            )
        if is_channel:
            state.active_color_array_name = ""
            state.active_property_kind = ""
            state.active_color_array_path = ""
        new_value = None  # treat as deactivated downstream
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
