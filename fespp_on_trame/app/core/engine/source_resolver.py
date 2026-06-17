"""Source / display / color resolution helpers.

These were closures inside `initialize_fespp_engine` (in `boot.py`);
extracted here as free functions so boot.py shrinks toward a pure
orchestration shell. Each function takes its dependencies
(`source_registry`, `tree`) explicitly — no module-level state.

Functions:
  - `sources_for_rep_path(source_registry, rep_path, view=None)` →
    list of *rendered* source proxies for a rep. When a threshold
    chain has a visible leaf, returns that leaf in place of each
    upstream so visibility toggles paint the right output.
  - `color_sources_for_rep_path(source_registry, rep_path, view=None)`
    → like the above but returns EVERY chain proxy (visible or not)
    in addition to the rep source. Used for ColorBy / LUT fan-out
    so a hidden chain entry stays in sync if it becomes visible
    later.
  - `displays_for_rep_path(source_registry, rep_path, view=None)` →
    display proxies for every source from `color_sources_for_rep_path`.
  - `resolve_array_for_path(source_registry, tree, rep_path,
    array_path)` → `(assoc, vtk_array_name)` tuple, retrying with the
    sanitized title when the raw title misses (FESPP strips chars
    outside `[-.0-9A-Z_a-z]` from VTK array names).
  - `apply_color_array(source_registry, tree, rep_path, array_path,
    view=None)` → run ColorBy / SolidColor on every display.
    Workaround for PV6: `pvsimple.ColorBy(display, None)` raises
    "invalid association string NONE", so SolidColor clears via
    SMProxy.SetScalarColoring."""
import re

from paraview import simple as pvsimple


_NAME_INVALID_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def _scene_clip_output_for_view(rep_path: str, view):
    """Return the Clip proxy owned by the RepInScene whose owning view
    matches `view`, or None when no such RepInScene has clip
    enabled. Phase 1.b.1: clip moved from the per-rep wrappers to
    per-(rep, view) RepInScene; this lookup lets the ColorBy fan-out
    still find the right clip output."""
    rep = _scene_rep_for_view(rep_path, view)
    if rep is None:
        return None
    try:
        return rep.clip_output()
    except Exception:
        return None


def _scene_rep_for_view(rep_path: str, view):
    """Return the RepInScene for (view, rep_path), or None when no
    scene currently renders that rep in that view. Used by the
    ColorBy fan-out to find the per-view extractor + chain (Phase
    3a) so coloring targets the per-view pipeline, not the shared
    legacy source."""
    try:
        from trame.app import get_server
        scenes = getattr(get_server().context, "scene_registry", None)
        if scenes is None:
            return None
        for scene in scenes.all_scenes():
            if scene.pv_view is view:
                return scene.get_rep(rep_path)
    except Exception:
        return None
    return None


def sources_for_rep_path(source_registry, rep_path, view=None):
    """See module docstring. Returns `(sources, view)` so callers can
    chain Render(view=...) without re-resolving the active view.

    Priority is the same as `color_sources_for_rep_path` — IjkGrid is
    checked FIRST and returns slicers + volume + rep_data (every proxy
    this grid can render into a view). Returning only `rep_data` here
    would cause `toggle_rep_visibility` to Hide just the upstream
    extractor (already hidden by IjkGrid), leaving the slicers visible
    in the target view despite the eye chip saying hidden."""
    if view is None:
        view = pvsimple.GetActiveView()
    if view is None:
        return [], None
    out = []
    # Phase 3b: prefer the per-view IjkGrid for IJK reps in this view
    # so visibility toggles operate on the per-view pipeline (not on
    # the now-hidden legacy IjkGrid).
    rep_in_scene = _scene_rep_for_view(rep_path, view)
    if rep_in_scene is not None and rep_in_scene._is_ijk_grid():
        per_view_ijk = rep_in_scene._ensure_per_view_ijk()
        if per_view_ijk is not None and per_view_ijk.source is not None:
            deepest_leaf = per_view_ijk._deepest_visible_leaf()
            grid_sources = list(per_view_ijk._all_slice_sources())
            if per_view_ijk._src_slicer_volume is not None:
                grid_sources.append(per_view_ijk._src_slicer_volume)
            if per_view_ijk._src_extract_init is not None:
                grid_sources.append(per_view_ijk._src_extract_init)
            for s in grid_sources:
                proxy = None
                if deepest_leaf is not None:
                    proxy = deepest_leaf.pv_proxies.get(id(s))
                out.append(proxy if proxy is not None else s)
            return out, view

    ijk = source_registry.get_ijk_grid(rep_path)
    if ijk is not None:
        deepest_leaf = ijk._deepest_visible_leaf()
        grid_sources = list(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            grid_sources.append(ijk._src_slicer_volume)
        # Include rep_data — it's the visible source in range mode at
        # full extent, and including it in the hide path is harmless
        # when already hidden in slice mode.
        if ijk._src_extract_init is not None:
            grid_sources.append(ijk._src_extract_init)
        for s in grid_sources:
            proxy = None
            if deepest_leaf is not None:
                proxy = deepest_leaf.pv_proxies.get(id(s))
            out.append(proxy if proxy is not None else s)
        return out, view

    # Phase 3a: non-IjkGrid reps own a per-view extractor + per-view
    # chain. Substitute the per-view deepest visible chain leaf for
    # the per-view extractor when the chain is active.
    if rep_in_scene is not None:
        per_view_src = None
        try:
            per_view_src = rep_in_scene._ensure_extractor()
        except Exception:
            per_view_src = None
        if per_view_src is not None:
            try:
                visibles = rep_in_scene.all_visible_thresholds()
            except Exception:
                visibles = []
            out.append(visibles[-1] if visibles else per_view_src)
            return out, view

    eb = source_registry.get_extract_block(rep_path)
    if eb is not None:
        # ExtractBlock side: substitute the deepest visible chain leaf
        # for the source when a threshold chain is active.
        visibles = source_registry.all_visible_thresholds(rep_path)
        if visibles:
            out.append(visibles[-1])
        elif eb.source is not None:
            out.append(eb.source)
        return out, view

    # Legacy fallback: match by registered name.
    expected_rep_filter = "rep" + (rep_path or "").replace('/', '_')
    for sid, s in pvsimple.GetSources().items():
        if sid[0] == expected_rep_filter:
            out.append(s)
    return out, view


def color_sources_for_rep_path(source_registry, rep_path, view=None):
    """See module docstring.

    Priority — IjkGrid is checked FIRST: for an IjkGrid the colorable
    proxies are the slicers (+ volume crop + threshold leaves), not
    the rep_data extractor. The extractor is upstream of every slicer
    and is explicitly `Hide()`n by `IjkGrid` so it never renders in
    its native view. If we returned it here, callers that also use
    this function in a *new* view (e.g. after a scene replicate) would
    call `GetDisplayProperties(rep_data, view=new_view)` which lazily
    creates a default display proxy with `Visibility=1, Representation
    ='Outline'`. The subsequent `ColorBy` then makes that outline
    render — visible in the new view as a phantom outline overlay on
    top of the actual slicers."""
    if view is None:
        view = pvsimple.GetActiveView()
    if view is None:
        return [], None
    out = []
    # Clip output is per-(rep, view) since Phase 1.b.1 — look it up
    # via the scene_registry on server.context. Slice's display is
    # intentionally excluded (it's tinted red so the cross-section
    # stands out against the underlying rep).
    rep_in_scene_clip_out = _scene_clip_output_for_view(rep_path, view)
    rep_in_scene = _scene_rep_for_view(rep_path, view)

    # Phase 3b: IJK reps now own a per-view IjkGrid pipeline. Fan
    # ColorBy onto the per-view slicers / volume / chain in THIS
    # view's pipeline, NOT onto the legacy shared IjkGrid (which is
    # hidden in this view by `_hide_legacy_ijk_in_scene_view`).
    if rep_in_scene is not None and rep_in_scene._is_ijk_grid():
        per_view_ijk = rep_in_scene._ensure_per_view_ijk()
        if per_view_ijk is not None and per_view_ijk.source is not None:
            out.extend(per_view_ijk._all_slice_sources())
            if per_view_ijk._src_slicer_volume is not None:
                out.append(per_view_ijk._src_slicer_volume)
            try:
                out.extend(per_view_ijk.all_threshold_sources())
            except Exception:
                pass
            if rep_in_scene_clip_out is not None:
                out.append(rep_in_scene_clip_out)
            return out, view

    ijk = source_registry.get_ijk_grid(rep_path)
    if ijk is not None:
        out.extend(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            out.append(ijk._src_slicer_volume)
        try:
            out.extend(ijk.all_threshold_sources())
        except Exception:
            pass
        if rep_in_scene_clip_out is not None:
            out.append(rep_in_scene_clip_out)
        return out, view
    # Phase 3a: non-IjkGrid reps own a per-view EnergisticsExtractor +
    # per-view threshold chain. Fan ColorBy onto those (per-view), not
    # onto the legacy shared ExtractBlock + shared chain.
    rep_in_scene = _scene_rep_for_view(rep_path, view)
    if rep_in_scene is not None:
        per_view_src = None
        try:
            per_view_src = rep_in_scene._ensure_extractor()
        except Exception:
            per_view_src = None
        if per_view_src is not None:
            out.append(per_view_src)
            try:
                out.extend(rep_in_scene.all_chain_proxies())
            except Exception:
                pass
            if rep_in_scene_clip_out is not None:
                out.append(rep_in_scene_clip_out)
            return out, view

    eb = source_registry.get_extract_block(rep_path)
    if eb is not None:
        if eb.source is not None:
            out.append(eb.source)
        out.extend(source_registry.all_chain_proxies(rep_path))
        if rep_in_scene_clip_out is not None:
            out.append(rep_in_scene_clip_out)
        return out, view
    # Legacy fallback: match by registered name.
    expected_rep_filter = "rep" + (rep_path or "").replace('/', '_')
    for sid, s in pvsimple.GetSources().items():
        if sid[0] == expected_rep_filter:
            out.append(s)
    return out, view


def displays_for_rep_path(source_registry, rep_path, view=None):
    """See module docstring."""
    srcs, view = color_sources_for_rep_path(source_registry, rep_path, view=view)
    if view is None:
        return []
    out = []
    for s in srcs:
        d = pvsimple.GetDisplayProperties(s, view=view)
        if d is not None:
            out.append(d)
    return out


def resolve_array_for_path(source_registry, tree, rep_path, array_path,
                            realization_idx=None):
    """See module docstring.

    `realization_idx` (default None) — when set on a multi-realization
    `array_path`, the resolver looks up the suffixed VTK array name
    `<sanitized_title>_real_<realization_idx>` first. Falls back to
    the legacy unsuffixed name when not set or not found, preserving
    the single-realization global-cursor behaviour for non-MR
    properties and for MR properties without per-property selection."""
    node_id = tree.find_node_id(array_path)
    if node_id is None:
        return None, None
    title = tree.find_title(node_id) or ""
    # MultiRealization synthetic nodes carry the actual VTK array
    # name in propTitle, not title.
    kind = tree.find_type(node_id) or ""
    is_mr = kind in ("MultiRealization", "MultiRealizationTimeSeries")
    if is_mr:
        pt = tree.find_attribute_value(node_id, "propTitle")
        if pt:
            title = pt
    if not title:
        return None, None
    candidate_sources = []
    src = source_registry.get(rep_path)
    if src is not None:
        candidate_sources.append(src)
    else:
        for sid, s in pvsimple.GetSources().items():
            name = sid[0]
            if name == "rep" + (rep_path or "").replace('/', '_'):
                candidate_sources.append(s)
                break
    sanitized = _NAME_INVALID_RE.sub("", title)

    # Per-property MR path: look up the suffixed array name first.
    # Falls through to the legacy lookup when the suffixed array
    # isn't present (e.g. the plugin hasn't loaded it yet, or this
    # build lacks Phase 2/3 of the contract).
    if is_mr and realization_idx is not None:
        suffixed = f"{sanitized}_real_{int(realization_idx)}"
        for s in candidate_sources:
            try:
                cell_info = s.GetCellDataInformation()
                if cell_info and cell_info.GetArray(suffixed):
                    return "CELLS", suffixed
                point_info = s.GetPointDataInformation()
                if point_info and point_info.GetArray(suffixed):
                    return "POINTS", suffixed
            except Exception:
                pass

    for s in candidate_sources:
        try:
            cell_info = s.GetCellDataInformation()
            point_info = s.GetPointDataInformation()
            for nm in (title, sanitized):
                if nm and cell_info and cell_info.GetArray(nm):
                    return "CELLS", nm
                if nm and point_info and point_info.GetArray(nm):
                    return "POINTS", nm
        except Exception:
            pass
    return None, None


def hide_unused_scalar_bars(view=None):
    """Hide every scalar bar in `view` whose LUT is no longer
    referenced by a visible display. Defaults to the active view.

    Called after a coloring change to keep the on-screen legend in
    sync with what's actually colored — e.g. switching a rep to
    SolidColor or hiding the rep entirely leaves a stale bar in the
    view otherwise. PV's TransferFunctionManager exposes the
    canonical "hide unused" sweep via `UpdateScalarBars(view, 1)`."""
    if view is None:
        view = pvsimple.GetActiveView()
    if view is None:
        return
    try:
        from paraview.servermanager import vtkSMTransferFunctionManager
        mgr = vtkSMTransferFunctionManager()
        mgr.UpdateScalarBars(view.SMProxy, 1)
    except Exception as exc:
        print(f"[WARNING] hide_unused_scalar_bars: {exc}")


def swap_to_scene_tfs(displays, target_view, array_name):
    """Swap each display's `LookupTable` / `ScalarOpacityFunction` to
    the per-(scene, array) proxies, so a COE edit in one view doesn't
    bleed across views sharing PV's default singleton-per-name LUT.

    Returns `(scene_lut, scene_pwf)` for the caller's downstream use
    (typically scalar-bar binding). Returns `(None, None)` when no
    scene owns `target_view` (legacy / pre-Phase-1 callers, bootstrap)
    — displays stay bound to PV's singleton LUT in that case.

    The actual scope name (`f"{array_name}__{view_id}"`) is generated
    by `ViewScene._scoped_tf_name` so the scope only lives in
    `view_scene.py`."""
    if not displays or not array_name:
        return None, None
    try:
        from trame.app import get_server
        scene_registry = getattr(get_server().context, "scene_registry", None)
        if scene_registry is None:
            return None, None
        scene = scene_registry.scene_for_pv_view(target_view)
        if scene is None:
            return None, None
        scene_lut = scene.get_or_create_lut(array_name)
        scene_pwf = scene.get_or_create_pwf(array_name)
        for d in displays:
            try:
                if scene_lut is not None:
                    d.LookupTable = scene_lut
                if scene_pwf is not None:
                    d.ScalarOpacityFunction = scene_pwf
            except Exception:
                pass
        return scene_lut, scene_pwf
    except Exception as _exc:
        print(f"[WARNING] swap_to_scene_tfs failed for {array_name!r}: {_exc}")
        return None, None


def resolve_target_scoped_lut(array_name):
    """Resolve `array_name` (UI base name — title for MR, raw
    otherwise) into the per-(target scene, MR-suffixed base) LUT
    proxy for the drawer's currently-targeted view. Used by COE-style
    edit panels (solid_color_panel, categorical_color_editor, …) so
    a user write goes to the per-view LUT and doesn't bleed across
    views.

    Returns `(base, scene_lut)`:
      - `base` : MR-suffixed-if-applicable base array name (what
        `ColorArrayName` carries on the displays).
      - `scene_lut`: the per-(scene, base) LUT proxy, or None when
        no scene owns the drawer target (legacy / bootstrap caller).
    """
    if not array_name:
        return array_name, None
    try:
        from trame.app import get_server
        from fespp_on_trame.app.core import engine as _engine_pkg
        from fespp_on_trame.app.core.engine import realization_dispatch
        server = get_server()
        state = server.state
        tree = getattr(_engine_pkg, "_tree", None)
        base = array_name
        if tree is not None:
            active_nodes = state.ui_active_node_reservoir or []
            if active_nodes:
                try:
                    array_path = tree.find_path(active_nodes[0])
                except Exception:
                    array_path = None
                if array_path and realization_dispatch.is_multirealization_property(tree, array_path):
                    panel_id = (
                        getattr(state, "drawer_target_view_id", "") or ""
                        or getattr(state, "fespp_active_panel_id", "") or ""
                    )
                    idx = realization_dispatch.get_active_realization_for_view(
                        state, panel_id, array_path,
                    )
                    if idx is None:
                        idx = realization_dispatch.default_realization_for(
                            state, tree, array_path,
                        )
                    if idx is not None:
                        base = realization_dispatch.suffixed_array_name(
                            array_name, int(idx),
                        )
        target_panel = (
            getattr(state, "drawer_target_view_id", "") or ""
            or getattr(state, "fespp_active_panel_id", "") or ""
        )
        scene_registry = getattr(server.context, "scene_registry", None)
        if scene_registry is None or not target_panel:
            return base, None
        scene = scene_registry.get_scene(target_panel)
        if scene is None:
            return base, None
        return base, scene.get_or_create_lut(base)
    except Exception as exc:
        print(f"[WARNING] resolve_target_scoped_lut({array_name!r}): {exc}")
        return array_name, None


def target_view_and_panel():
    """Resolve the drawer target's `(pv_view, panel_id)` pair.

    Used by edit panels (COE, categorical, …) so a write goes to the
    pinned target view's render — not the focused panel's. Falls back
    to the active panel when no drawer target is set (initial boot
    window, no pin)."""
    try:
        from trame.app import get_server
        server = get_server()
        state = server.state
        panel_id = (
            getattr(state, "drawer_target_view_id", "") or ""
            or getattr(state, "fespp_active_panel_id", "") or ""
        )
        if not panel_id:
            return None, ""
        scene_registry = getattr(server.context, "scene_registry", None)
        if scene_registry is None:
            return None, panel_id
        scene = scene_registry.get_scene(panel_id)
        if scene is None:
            return None, panel_id
        return scene.pv_view, panel_id
    except Exception:
        return None, ""


def render_and_push_target(controller):
    """Render the drawer target's pv_view and push a fresh vtk.js
    frame to its panel — used by edit handlers that mutate a per-
    view proxy (LUT / PWF / display.Representation / …) and need the
    target's browser to actually show the new state.

    Bypasses `controller.view_update()` (which only refreshes the
    active panel) in favour of `view_update_for(panel_id)`. Falls
    back to `view_update()` when the per-panel hook isn't wired."""
    pv_view, panel_id = target_view_and_panel()
    if pv_view is not None:
        try:
            pvsimple.Render(view=pv_view)
        except Exception:
            pass
    if controller is None:
        return
    update_for = getattr(controller, "view_update_for", None)
    if update_for is not None and panel_id:
        try:
            update_for(panel_id)
            return
        except Exception:
            pass
    try:
        controller.view_update()
    except Exception:
        pass


def scene_lut_for_view(view, array_name):
    """Lookup helper for callers that already know a `view` and need
    the scene-scoped LUT (e.g. the activator's scalar bar binding).
    Returns the per-view LUT when one exists for `(scene, array)`,
    else the global singleton LUT (PV default). Never returns None
    unless `array_name` is empty."""
    if not array_name:
        return None
    try:
        from trame.app import get_server
        scene_registry = getattr(get_server().context, "scene_registry", None)
        if scene_registry is not None and view is not None:
            scene = scene_registry.scene_for_pv_view(view)
            if scene is not None:
                cached = scene.get_lut(array_name)
                if cached is not None:
                    return cached
    except Exception:
        pass
    return pvsimple.GetColorTransferFunction(array_name)


def apply_color_array(source_registry, tree, rep_path, array_path, view=None,
                       realization_idx=None):
    """See module docstring.

    `realization_idx` — when `array_path` is a multi-realization
    property and a specific realization is selected for the target
    view, this is the integer index. Threaded through to
    `resolve_array_for_path` so the suffixed VTK array name
    "<title>_real_<idx>" is used for the ColorBy call. Defaults to
    None (legacy behaviour: resolver picks the unsuffixed name)."""
    displays = displays_for_rep_path(source_registry, rep_path, view=view)
    if not displays:
        return
    if not array_path:
        # Deselect path (tree eye unchecked). Hide the previous
        # scalar bar through display.SetScalarBarVisibility BEFORE
        # clearing SetScalarColoring — otherwise the LUT reference
        # is severed first and vtkSMTransferFunctionManager's
        # bookkeeping leaves the bar widget visible on the view
        # until a downstream sweep happens to reap it. With per-
        # view LUT scope the timing matters: the manager only
        # hides bars whose LUT it currently tracks as wired, so
        # we must tell it BEFORE the wire goes away.
        for d in displays:
            try:
                if d.LookupTable is not None and view is not None:
                    d.SetScalarBarVisibility(view, False)
            except Exception:
                pass
            try:
                sm = getattr(d, "SMProxy", None)
                if sm is not None:
                    sm.SetScalarColoring("", 0)
                    sm.UpdateVTKObjects()
                else:
                    d.ColorArrayName = ['', '']
            except Exception:
                pass
        return
    assoc, name = resolve_array_for_path(
        source_registry, tree, rep_path, array_path,
        realization_idx=realization_idx,
    )
    if not assoc or not name:
        return
    for d in displays:
        try:
            pvsimple.ColorBy(d, (assoc, name))
        except Exception:
            pass
    target_view = view if view is not None else pvsimple.GetActiveView()
    scene_lut, scene_pwf = swap_to_scene_tfs(displays, target_view, name)
    # `pvsimple.ColorBy` doesn't show the scalar bar — and a prior
    # `hide_unused_scalar_bars` sweep may have unbound the bar from
    # the view's representation list, in which case a raw
    # `Visibility = 1` on the bar proxy is a no-op (the bar isn't
    # attached). Use the canonical PV path:
    # `display.SetScalarBarVisibility` drives the
    # TransferFunctionManager which re-attaches the bar to the view
    # if needed. Tweak the bar's cosmetics after it's wired in.
    try:
        if target_view is not None:
            for d in displays:
                try:
                    d.SetScalarBarVisibility(target_view, True)
                    break
                except Exception:
                    continue
            # Use the scoped LUT when we have one so the scalar bar
            # follows the per-view gradient. Fall back to the global
            # LUT otherwise (legacy / pre-scene callers).
            bar_lut = scene_lut if scene_lut is not None else pvsimple.GetColorTransferFunction(name)
            if bar_lut is not None:
                bar = pvsimple.GetScalarBar(bar_lut, target_view)
                if bar is not None:
                    bar.Title = name
                    bar.RangeLabelFormat = '%-#6.3g'
                    bar.Resizable = 1
    except Exception:
        pass
    # Sweep orphan bars in this view so stale legends from a previous
    # property don't linger alongside the new one. The TransferFunction
    # Manager only hides bars whose LUT is unreferenced by any visible
    # display, so our freshly-shown bar (bound via ColorBy above)
    # survives the sweep.
    if target_view is not None:
        hide_unused_scalar_bars(view=target_view)
