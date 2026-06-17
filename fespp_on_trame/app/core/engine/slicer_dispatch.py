"""Slicer / range / volume / representation dispatch — extracted from
`boot.initialize_fespp_engine`.

Every function in this module receives its dependencies explicitly so
boot.py can keep the trame decorator registrations (`@state.change`,
`@controller.set`) as thin closure wrappers. The actual logic lives
here.

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
  - `propagate_representation` — push the active representation
    type (Surface / Wireframe / Points / …) onto every proxy in
    the scene."""
from paraview import simple as pvsimple


def _target_panel_id(state):
    """The Attributes drawer's target view (picker-driven), falling
    back to the active panel for the boot window."""
    return (
        getattr(state, "drawer_target_view_id", "") or ""
        or getattr(state, "fespp_active_panel_id", "") or ""
    )


def _target_pv_view(state, fallback_view):
    """Resolve the pv_view of the target panel via scene_registry,
    falling back to `fallback_view` (the engine-captured legacy
    `_view`) when nothing else applies — preserves the single-view
    behaviour during early boot."""
    target = _target_panel_id(state)
    if not target:
        return fallback_view
    try:
        from trame.app import get_server
        ctx = get_server().context
        scenes = getattr(ctx, "scene_registry", None)
        if scenes is not None:
            scene = scenes.get_scene(target)
            if scene is not None and getattr(scene, "pv_view", None) is not None:
                return scene.pv_view
    except Exception:
        pass
    return fallback_view


def _active_ijk_grid(state, source_registry):
    """Resolve the active IjkGrid for the currently-active panel.

    Phase 3b: prefer the active view's per-view IjkGrid (owned by
    `RepInScene._per_view_ijk` via the `scene_registry`). Falls back
    to the legacy shared IjkGrid when:
      - the scene_registry isn't reachable yet (early boot);
      - the active view's RepInScene hasn't been created;
      - the per-view IjkGrid hasn't been built yet (no property
        picked → fallback ensures Show()/extent init still happens
        on legacy and gets mirrored into per-view at next build).

    Routing through scene_registry makes slicer panel edits land on
    the target view's pipeline only — splitting the views diverges
    each view's slicer state from the panel switch onwards. The
    "target view" is the Attributes drawer's picker (Brique A),
    which follows the active panel unless pinned."""
    rep_path = state.active_representation_path
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
    """Server-render the target panel's pv_view, then push the frame
    to its vtk.js client AND to the legacy active panel's. The dual
    push covers both follow mode (target == active, single update)
    and pinned mode (target != active, both clients refreshed)."""
    pv_view = _target_pv_view(state, fallback_view)
    if pv_view is not None:
        try:
            pvsimple.Render(view=pv_view)
        except Exception:
            pass
    panel_id = _target_panel_id(state)
    try:
        controller.view_update_for(panel_id)
    except Exception:
        pass
    try:
        controller.view_update()
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
    if active is not None:
        active.apply_slice_positions(
            i_list or [],
            j_list or [],
            k_list or [],
        )
        active.show()
    _render_and_push(state, controller, view)


def update_slice_range(state, controller, source_registry, view,
                      range_i, range_j, range_k):
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_range(range_i, range_j, range_k)
        active.show()
    _render_and_push(state, controller, view)


def update_slice_mode(state, controller, source_registry, view, mode):
    """Mode flip (`slice` ↔ `range`) changes the set of "active
    sources" — IjkGrid re-attaches its threshold chain accordingly
    (rep_data + volume in range, rep_data + per-axis slicers in
    slice)."""
    active = _active_ijk_grid(state, source_registry)
    if active is not None:
        active.apply_mode(mode or 'slice')
        active.show()
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


def apply_z_scale(state, controller, source_registry, view, zscale):
    """Broadcast the global vertical exaggeration to every extracted
    rep source and to every IjkGrid slicer / volume proxy.

    `state` is used by `_render_and_push` to resolve the target view
    (Brique A drawer picker). Pre-Brique-A callers without `state`
    need to update their call sites — see boot.py."""
    try:
        zs = float(zscale or 1.0)
    except (TypeError, ValueError):
        zs = 1.0
    source_registry.apply_z_scale(zs)
    ijk_srcs = []
    for ijk in source_registry.ijk_grids():
        ijk_srcs.extend(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            ijk_srcs.append(ijk._src_slicer_volume)
    for src in ijk_srcs:
        rep = pvsimple.GetRepresentation(proxy=src, view=view)
        if rep is not None:
            rep.Scale = [1.0, 1.0, zs]
    _render_and_push(state, controller, view)


def _collect_scene_proxies(scene):
    """Per-(rep, view) proxies that may have a visible display in
    `scene.pv_view`: the rep's per-view EnergisticsExtractor + threshold
    chain + slice/clip outputs, plus the per-view IjkGrid pipeline
    (rep_data + slicer-volume + slice sources + threshold sources).

    Returns an empty list for scenes whose reps all still fall back
    to the legacy shared source (Phase 2 fallback) — the caller
    handles those via the legacy iteration."""
    out = []
    for _path, rep in scene.reps():
        if rep._extractor is not None:
            out.append(rep._extractor)
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
    """Legacy shared proxies (pre-Phase-3a fallback): sources +
    thresholds + IjkGrid pipeline. Used in scenes where the per-view
    extractor wasn't created (Phase 2 fallback) and as a backstop for
    proxies that still render via the shared pipeline."""
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


def propagate_representation(source_registry, scene_registry, controller, representation_active):
    """ptc.RepresentBy only sets `Representation` on a single display
    (active source × active view). With per-(rep, view) pipelines from
    Phase 3a, the visible displays live on the scene's per-view
    extractor / chain / slice / clip / per-view IjkGrid proxies, not
    on the legacy shared sources — so the ptc write lands on hidden
    displays and the view stays in its old Representation.

    Fan the new value out across **every scene's** visible proxies in
    that scene's `pv_view`, plus the legacy fallbacks for reps that
    still render through the shared source (Phase 2 fallback).

    `controller` is used to push a fresh vtk.js frame to every panel
    AFTER the per-view writes + Render. ptc.RepresentBy already calls
    `on_data_change` (which triggers `view_update_all`) but it fires
    *before* this handler — so the client receives a frame that
    still shows the old representation. Re-push at the end so the
    new state actually reaches the browser without a camera reset."""
    if not representation_active:
        return
    if scene_registry is None or not hasattr(scene_registry, "all_scenes"):
        # Legacy fallback (shouldn't happen post Phase 3a wiring)
        view = pvsimple.GetActiveView()
        if view is None:
            return
        for p in _collect_legacy_proxies(source_registry):
            try:
                disp = pvsimple.GetRepresentation(proxy=p, view=view)
                if disp is not None:
                    disp.Representation = representation_active
            except Exception:
                pass
        pvsimple.Render(view=view)
        _push_all_panels(controller)
        return
    # Per-scene fan-out: each scene gets its per-view proxies + the
    # legacy ones (legacy stay hidden in non-fallback scenes, but a
    # hidden display still accepts the property write at zero render
    # cost — keeps the behavior consistent if a rep ever switches
    # back to fallback).
    legacy = _collect_legacy_proxies(source_registry)
    for scene in scene_registry.all_scenes():
        view = scene.pv_view
        if view is None:
            continue
        for p in _collect_scene_proxies(scene) + legacy:
            try:
                disp = pvsimple.GetRepresentation(proxy=p, view=view)
                if disp is not None:
                    disp.Representation = representation_active
            except Exception:
                pass
        pvsimple.Render(view=view)
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
