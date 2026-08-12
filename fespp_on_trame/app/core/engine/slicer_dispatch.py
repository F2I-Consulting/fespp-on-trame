"""Slicer / range / volume / representation dispatch.

Every function receives its dependencies explicitly so boot.py can keep
the trame decorator registrations (`@state.change`, `@controller.set`)
as thin closure wrappers.

Handlers covered:
  - `set_slider_value` — write the first slice position for an axis
    into the corresponding `ui_slices_{i,j,k}_list`.
  - `update_slice_positions` — slicer position lists per axis.
  - `update_slice_range` — slicer range bounds per axis.
  - `update_slice_mode` — slice vs range mode toggle.
  - `update_volume_visible` — show/hide the volume crop.
  - `update_slice_visibility` — per-axis per-slicer visibility.
  - `apply_z_scale` — fan out the global Z exaggeration to every
    rep + IjkGrid slicer / volume.
  - `apply_representation_type` — push a representation
    type (Surface / Wireframe / Points / …) onto ONE rep's
    displays in the drawer-target view (strictly per-rep)."""
from paraview import simple as pvsimple

from fespp_on_trame.app.core.engine import view_routing


def _target_panel_id(state):
    """The Attributes drawer's target view (picker-driven), falling
    back to the active panel for the boot window."""
    return view_routing.target_panel_id(state)


def _target_pv_view(state, fallback_view):
    """Resolve the pv_view of the target panel via scene_registry,
    falling back to `fallback_view` (the engine-captured `_view`)
    during early boot."""
    from trame.app import get_server
    scenes = getattr(get_server().context, "scene_registry", None)
    return view_routing.scene_pv_view(scenes, _target_panel_id(state), fallback_view)


def _active_ijk_grid(state, source_registry):
    """Resolve the active IjkGrid for the currently-active panel.

    Prefer the active view's per-view IjkGrid (owned by
    `RepInScene._per_view_ijk` via the `scene_registry`). Falls back
    to the shared IjkGrid when:
      - the scene_registry isn't reachable yet (early boot);
      - the active view's RepInScene hasn't been created;
      - the per-view IjkGrid hasn't been built yet (no property
        picked).

    Routing through scene_registry keeps slicer panel edits on the
    target view's pipeline only, so each view's slicer state can
    diverge. The "target view" is the Attributes drawer's picker,
    which follows the active panel unless pinned."""
    # Resolve through the RESERVOIR-tab rep path, NOT the global
    # `active_representation_path`: the latter follows wellbore / surface
    # selections and eye-click channel activations, which would point the
    # IJK slicer at a non-grid rep so every slider edit resolves to None.
    # `ui_active_node_reservoir_rep_path` tracks the reservoir tab's active
    # grid (set / cleared only by `_handle_reservoir_change`).
    rep_path = getattr(state, "ui_active_node_reservoir_rep_path", "") or ""
    if not rep_path:
        return None
    try:
        from trame.app import get_server
        ctx = get_server().context
        scenes = getattr(ctx, "scene_registry", None)
        active = _target_panel_id(state)
        if scenes is not None and active:
            rep = scenes.get_rep(active, rep_path)
            if rep is not None:
                ijk = getattr(rep, "_per_view_ijk", None)
                if ijk is None and hasattr(rep, "_ensure_per_view_ijk"):
                    try:
                        ijk = rep._ensure_per_view_ijk()
                    except Exception:
                        ijk = None
                if ijk is not None:
                    return ijk
    except Exception:
        pass
    return source_registry.get_ijk_grid(rep_path)


def _render_and_push(state, controller, fallback_view):
    """Server-render the target panel's pv_view, then dual-push to its
    vtk.js client AND the active panel's (follow + pinned modes)."""
    view_routing.render_and_push(
        controller, _target_pv_view(state, fallback_view), _target_panel_id(state),
    )


def _recolor_active_grid(state, source_registry, fallback_view):
    """Re-apply the active array's ColorBy to the active grid's per-view
    sources via the authoritative eye/active-array path. Freshly-created
    slicers would otherwise inherit the IjkGrid's stale `_title` (the eye
    path changes the displayed property without touching it), so a new
    slicer ends up colored by the wrong property."""
    rep_path = getattr(state, "ui_active_node_reservoir_rep_path", "") or ""
    if not rep_path:
        return
    panel = _target_panel_id(state)
    by_view = (getattr(state, "ui_active_array_by_rep_by_view", {}) or {}).get(panel, {}) or {}
    array_path = by_view.get(rep_path) or (getattr(state, "ui_active_array_by_rep", {}) or {}).get(rep_path)
    if not array_path:
        return
    real_by_view = (getattr(state, "ui_active_realization_by_array_by_view", {}) or {}).get(panel, {}) or {}
    realization_idx = real_by_view.get(array_path)
    from fespp_on_trame.app.core import engine as _eng
    tree = getattr(_eng, "_tree", None)
    if tree is None:
        return
    from fespp_on_trame.app.core.engine import source_resolver
    try:
        source_resolver.apply_color_array(
            source_registry, tree, rep_path, array_path,
            view=_target_pv_view(state, fallback_view), realization_idx=realization_idx,
        )
    except Exception:
        pass


def set_slider_value(state, index, value):
    """Set the first slice position for the given axis ('i', 'j', or
    'k'). Value-only entry point used by the slice slider widgets —
    avoids them having to know about the per-axis list shape."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return
    list_var = f"ui_slices_{index}_list"
    current = list(getattr(state, list_var, [0]))
    if current:
        current[0] = value
    else:
        current = [value]
    setattr(state, list_var, current)


def update_slice_positions(state, controller, source_registry, view,
                           i_list, j_list, k_list):
    """Sync per-slicer visibility lists with the slice lists, then
    push positions to the active IjkGrid. New slicers default to
    visible."""
    for axis, lst in (('i', i_list), ('j', j_list), ('k', k_list)):
        vis_var = f"ui_slices_{axis}_visible_list"
        lst = lst or []
        vis_list = list(getattr(state, vis_var, []) or [])
        while len(vis_list) < len(lst):
            vis_list.append(True)
        while len(vis_list) > len(lst):
            vis_list.pop()
        setattr(state, vis_var, vis_list)

    active = _active_ijk_grid(state, source_registry)
    added = False
    if active is not None:
        before = (len(active._slices_i_list or []) + len(active._slices_j_list or [])
                  + len(active._slices_k_list or []))
        active.apply_slice_positions(
            i_list or [],
            j_list or [],
            k_list or [],
        )
        after = len((i_list or [])) + len((j_list or [])) + len((k_list or []))
        added = after > before
        active.show()
    # A newly-added slicer would inherit the IjkGrid's stale `_title`; re-fire
    # the active-array ColorBy so it paints the current property. Only on add
    # (not on every drag-move) to avoid recolouring on each slider tick.
    if added:
        _recolor_active_grid(state, source_registry, view)
    _render_and_push(state, controller, view)


def update_slice_range(state, controller, source_registry, view,
                      range_i, range_j, range_k):
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_range(range_i, range_j, range_k)
        active.show()
    _render_and_push(state, controller, view)


def update_slice_mode(state, controller, source_registry, view, mode):
    """Mode flip (`slice` ↔ `range`) changes the set of active
    sources — IjkGrid re-attaches its threshold chain accordingly
    (rep_data + volume in range, rep_data + per-axis slicers in
    slice)."""
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_mode(mode or 'full')
        active.show()
        # The flip swaps which sources render (rep_data / slicers /
        # volume). Re-fire the active-array ColorBy on the NEW set —
        # a freshly-shown source may never have been coloured (grid
        # loaded in full mode, property activated there, then flipped
        # to slice) — and re-assert the colour bar that the orphan
        # sweep reaps when every bound display is hidden mid-flip.
        _recolor_active_grid(state, source_registry, view)
        try:
            from fespp_on_trame.app.core.engine import source_resolver
            source_resolver.reassert_active_scalar_bars(
                state, source_registry,
                view=_target_pv_view(state, view),
            )
        except Exception:
            pass
    _render_and_push(state, controller, view)


def update_volume_visible(state, controller, source_registry, view, visible):
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_volume_visible(visible)
        active.show()
    _render_and_push(state, controller, view)


def update_slice_visibility(state, controller, source_registry, view,
                            vis_i, vis_j, vis_k):
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_slice_visibility(
            vis_i or [],
            vis_j or [],
            vis_k or [],
        )
        active.show()
    _render_and_push(state, controller, view)


def _set_scale_preserving_color(disp, scale):
    """Write `disp.Scale` while saving / restoring ColorArrayName +
    LookupTable — the Scale write can reset the active coloring on some
    PV builds."""
    saved_color = None
    saved_lut = None
    try:
        saved_color = disp.ColorArrayName
    except Exception:
        pass
    try:
        saved_lut = disp.LookupTable
    except Exception:
        pass
    disp.Scale = scale
    if saved_color is not None:
        try:
            if disp.ColorArrayName != saved_color:
                disp.ColorArrayName = saved_color
        except Exception:
            pass
    if saved_lut is not None:
        try:
            if disp.LookupTable != saved_lut:
                disp.LookupTable = saved_lut
        except Exception:
            pass


def apply_z_scale(state, controller, source_registry, view, zscale):
    """Broadcast the global vertical exaggeration to every extracted
    rep source and to every IjkGrid slicer / volume proxy.

    `state` is used by `_render_and_push` to resolve the target view
    (drawer picker)."""
    try:
        zs = float(zscale or 1.0)
    except (TypeError, ValueError):
        zs = 1.0
    source_registry.apply_z_scale(zs)
    # Per-scene fan-out — the visible displays live on the per-(rep, view)
    # proxies (extractor + chain + slice/clip + per-view IjkGrid + per-child
    # marker/channel extractors), not on the shared sources.
    from trame.app import get_server
    scene_registry = getattr(get_server().context, "scene_registry", None)
    scenes = []
    if scene_registry is not None:
        try:
            scenes = list(scene_registry.all_scenes())
        except Exception:
            scenes = []
    if scenes:
        legacy = _collect_legacy_proxies(source_registry)
        from fespp_on_trame.app.core.engine import marker_dispatch
        for scene in scenes:
            v = scene.pv_view
            if v is None:
                continue
            for p in _collect_scene_proxies(scene) + legacy:
                try:
                    disp = pvsimple.GetRepresentation(proxy=p, view=v)
                    if disp is not None:
                        # Markers (mrk_*) TRANSLATE Z (stay round); everything
                        # else SCALES. Name-based so it works even when the
                        # scene registry didn't track the marker extractor.
                        if marker_dispatch.is_marker_proxy(p):
                            marker_dispatch.apply_marker_z(disp, p, zs)
                        else:
                            _set_scale_preserving_color(disp, [1.0, 1.0, zs])
                except Exception:
                    pass
            # Markers are SYMBOLIC — TRANSLATE Z (keep the sphere round)
            # instead of scaling, so a high z-scale doesn't stretch them.
            for _path, rep in scene.reps():
                markers = getattr(rep, "_marker_extractors", None)
                if not markers:
                    continue
                for ext in markers.values():
                    if ext is None:
                        continue
                    try:
                        disp = pvsimple.GetRepresentation(proxy=ext, view=v)
                        marker_dispatch.apply_marker_z(disp, ext, zs)
                    except Exception:
                        pass
            pvsimple.Render(view=v)
        _push_all_panels(controller)
        return

    # Fallback when no per-view scenes exist yet.
    ijk_srcs = []
    for ijk in source_registry.ijk_grids():
        ijk_srcs.extend(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            ijk_srcs.append(ijk._src_slicer_volume)
    for src in ijk_srcs:
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        if rep is not None:
            _set_scale_preserving_color(rep, [1.0, 1.0, zs])
    _render_and_push(state, controller, view)


def _collect_scene_proxies(scene):
    """Per-(rep, view) proxies that may have a visible display in
    `scene.pv_view`: the rep's per-view EnergisticsExtractor + threshold
    chain + slice/clip outputs, plus the per-view IjkGrid pipeline
    (rep_data + slicer-volume + slice sources + threshold sources).

    Returns an empty list for scenes whose reps all fall back to the
    shared source — the caller handles those via the legacy
    iteration."""
    out = []
    for _path, rep in scene.reps():
        if rep._extractor is not None:
            out.append(rep._extractor)
        # Channel (log-tube) extractors are real geometry → scale Z like any
        # rep. MARKER extractors are SYMBOLIC (sphere/disk) → NOT collected
        # here; apply_z_scale TRANSLATES their Z instead (keeps the shape).
        _ch = getattr(rep, "_channel_extractors", None)
        if _ch:
            out.extend(e for e in _ch.values() if e is not None)
        for entry in rep._chain:
            if getattr(entry, "proxy", None) is not None:
                out.append(entry.proxy)
        sp = rep._slice_plane
        if sp is not None and getattr(sp, "_proxy", None) is not None:
            out.append(sp._proxy)
        cp = rep._clip_plane
        if cp is not None and getattr(cp, "_proxy", None) is not None:
            out.append(cp._proxy)
        ijk = rep._per_view_ijk
        if ijk is not None:
            if ijk.source is not None:
                out.append(ijk.source)
            if getattr(ijk, "_src_extract_init", None) is not None:
                out.append(ijk._src_extract_init)
            if getattr(ijk, "_src_slicer_volume", None) is not None:
                out.append(ijk._src_slicer_volume)
            try:
                out.extend(ijk._all_slice_sources())
            except Exception:
                pass
            try:
                out.extend(ijk.all_threshold_sources())
            except Exception:
                pass
    return out


def _collect_legacy_proxies(source_registry):
    """Shared proxies: sources + thresholds + IjkGrid pipeline. Used
    in scenes where the per-view extractor wasn't created, and as a
    backstop for proxies that still render via the shared pipeline."""
    out = []
    try:
        out.extend(source_registry.all_sources())
    except Exception:
        pass
    try:
        out.extend(thr for _, thr in source_registry.all_thresholds())
    except Exception:
        pass
    try:
        for ijk in source_registry.ijk_grids():
            if ijk._src_extract_init is not None:
                out.append(ijk._src_extract_init)
            if ijk._src_slicer_volume is not None:
                out.append(ijk._src_slicer_volume)
            out.extend(ijk._all_slice_sources())
            out.extend(ijk.all_threshold_sources())
    except Exception:
        pass
    return out


def apply_representation_type(state, controller, source_registry, rep_path, rep_type,
                              marker_path=None):
    """Apply a display type to ONE rep — its extractor, chain, slice /
    clip and per-view IjkGrid displays — in the drawer-target view.

    The Attributes panel is strictly per-rep: the previous
    implementation broadcast `Representation` across every proxy of
    every scene, so toggling Wireframe on one grid restyled the whole
    scene. `displays_for_rep_path` resolves exactly the displays the
    rep renders through (visible or not), same targeting as ColorBy.

    `controller` re-pushes a fresh vtk.js frame AFTER the writes +
    Render: ptc.RepresentBy's own `on_data_change` fires *before*
    this handler, so the client would otherwise keep the old
    representation. Re-pushing avoids a camera reset."""
    if not rep_path or not rep_type:
        return
    from fespp_on_trame.app.core.engine import source_resolver
    view, _panel = source_resolver.target_view_and_panel()
    if marker_path:
        # Single-marker scope: touch ONLY that marker's glyph extractor
        # (a marker frame shares one rep — writing the rep's displays
        # would restyle every sibling marker).
        try:
            ris = source_resolver._scene_rep_for_view(rep_path, view)
            ext = (getattr(ris, "_marker_extractors", {}) or {}).get(marker_path)
            if ext is not None:
                d = pvsimple.GetDisplayProperties(ext, view=view)
                if d is not None:
                    d.Representation = rep_type
        except Exception:
            pass
    else:
        for disp in source_resolver.displays_for_rep_path(
                source_registry, rep_path, view=view):
            try:
                disp.Representation = rep_type
            except Exception:
                pass
    if view is None:
        view = pvsimple.GetActiveView()
    if view is not None:
        try:
            pvsimple.Render(view=view)
        except Exception:
            pass
    _push_all_panels(controller)


def _push_all_panels(controller):
    """Request a fresh vtk.js frame on every panel. Prefer
    `view_update_all` (multi-view aware); fall back to `view_update`
    (active panel only) when the multi-view isn't wired."""
    if controller is None:
        return
    update_all = getattr(controller, "view_update_all", None)
    if update_all is not None:
        try:
            update_all()
            return
        except Exception:
            pass
    try:
        controller.view_update()
    except Exception:
        pass
