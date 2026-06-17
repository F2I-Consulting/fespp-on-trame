"""Source / display / color resolution helpers.

Free functions taking their dependencies (`source_registry`, `tree`)
explicitly — no module-level state.

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
from paraview import simple as pvsimple

from fespp_on_trame.app.utils.naming import make_valid_vtk_name


def _vtk_array_range_from_clientside(pv_src, name, assoc):
    """Return (min, max) of the named array read from `pv_src`'s
    CLIENT-SIDE VTK output — bypassing the SM proxy info cache, which
    PV's internal RescaleTransferFunctionToDataRange reads and which goes
    stale after an in-place re-extraction (a channel/marker ExtractPath
    retarget). Mirrors the activator's rescale-from-fresh-array path.
    Handles a single dataset or a composite (iterates leaves). Returns
    None when the array isn't present or has no valid range."""
    if pv_src is None or not name:
        return None
    try:
        cso = pv_src.GetClientSideObject()
        dobj = cso.GetOutputDataObject(0) if cso is not None else None
    except Exception:
        return None
    store_attr = "GetPointData" if assoc == "POINTS" else "GetCellData"

    def _from_dataset(ds):
        try:
            store = getattr(ds, store_attr, None)
            store = store() if store is not None else None
            arr = store.GetArray(name) if store is not None else None
            if arr is not None:
                rng = arr.GetRange()
                if rng and rng[0] < rng[1]:
                    return (float(rng[0]), float(rng[1]))
        except Exception:
            pass
        return None

    if dobj is None:
        return None
    direct = _from_dataset(dobj)
    if direct is not None:
        return direct
    # Composite — walk leaves.
    try:
        it = dobj.NewIterator()
        it.InitTraversal()
        while not it.IsDoneWithTraversal():
            leaf = it.GetCurrentDataObject()
            rng = _from_dataset(leaf) if leaf is not None else None
            if rng is not None:
                return rng
            it.GoToNextItem()
    except Exception:
        pass
    return None


def _scene_clip_output_for_view(rep_path: str, view):
    """Return the Clip proxy owned by the RepInScene whose owning view
    matches `view`, or None when no such RepInScene has clip enabled.
    Clip lives on per-(rep, view) RepInScene; this lookup lets the
    ColorBy fan-out find the right clip output."""
    rep = _scene_rep_for_view(rep_path, view)
    if rep is None:
        return None
    try:
        return rep.clip_output()
    except Exception:
        return None


def _scene_rep_for_view(rep_path: str, view):
    """Return the RepInScene for (view, rep_path), or None when no scene
    currently renders that rep in that view. Used by the ColorBy fan-out
    to find the per-view extractor + chain so coloring targets the
    per-view pipeline, not the shared source."""
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


def channel_source_for(channel_path):
    """The per-(channel, view) extractor for a wellbore-frame CHANNEL in
    the drawer-target view, MATERIALISED (hidden) if absent. Returns None
    when `channel_path` is not a channel or no frame RepInScene renders
    it. Each channel owns a PERSISTENT extractor (tube + point array), so
    the COE / stats read its data DIRECTLY even when a DIFFERENT channel
    of the frame is the one displayed — no retarget needed."""
    if not channel_path:
        return None
    try:
        from fespp_on_trame.app.core import engine as _engine_pkg
        tree = getattr(_engine_pkg, "_tree", None)
        if tree is None:
            return None
        node_id = tree.find_node_id(channel_path)
        r_id = tree.find_representation_node(node_id) if node_id is not None else None
        if r_id is None or r_id == node_id or (tree.find_type(r_id) or "") != "Frame":
            return None  # not a wellbore-frame channel
        rep_path = tree.find_path(r_id)
        pv_view, _panel = target_view_and_panel()
        ris = _scene_rep_for_view(rep_path, pv_view) if pv_view is not None else None
        if ris is None:
            return None
        return ris.channel_extractor_for(channel_path, create=True)
    except Exception:
        return None


def nondegenerate_range(lo, hi):
    """Widen `(lo, hi)` to a finite, NON-zero-width interval.

    A constant property — or an all-NaN log whose NaNs C++ maps to 0 —
    has `lo == hi`. The COE's CanvasGradient normalises stop positions as
    `(value - lo) / (hi - lo)`; a zero (or non-finite) width divides by
    zero and the client throws "addColorStop: non-finite double",
    blanking the editor. Returns a tiny relative widening (or a unit
    interval at 0) so the gradient renders a near-flat band instead."""
    import math
    try:
        lo = float(lo)
        hi = float(hi)
    except (TypeError, ValueError):
        return 0.0, 1.0
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return 0.0, 1.0
    if hi > lo:
        return lo, hi
    span = abs(lo) * 1e-6
    hi = lo + (span if span > 0.0 else 1.0)
    if hi <= lo:        # float-rounding safety for huge magnitudes
        hi = lo + 1.0
    return lo, hi


def _src_has_named_array(src, name):
    """True iff the PV source proxy `src` exposes a Cell- or Point-data
    array named exactly `name`."""
    if src is None or not name:
        return False
    try:
        for store_attr in ("GetCellDataInformation", "GetPointDataInformation"):
            getter = getattr(src, store_attr, None)
            di = getter() if getter is not None else None
            if di is not None and di.GetArray(name) is not None:
                return True
    except Exception:
        pass
    return False


def real_base_name(array_name, rep_path, view):
    """The ACTUAL VTK array base name as it exists on the rep's per-view
    source.

    A wellbore-frame CHANNEL names its POINT array with the RAW,
    UNSANITIZED title (C++ `ResqmlWellboreChannelToVtkPolyData` sets
    `getTitle()` verbatim), whereas grid / surface properties go through
    `MakeValidNodeName` (sanitized). The render path keys its per-view
    scoped LUT on whichever name ACTUALLY exists (via
    `resolve_array_for_path`), so the COE must resolve the SAME name —
    blindly sanitizing keys a DIFFERENT, never-rendered LUT for channels
    and makes `GetArrayInformation` miss, blanking the COE graph.

    Strategy: when the raw title differs from its sanitized form and the
    raw title is present on the per-view source, use the raw title
    (channel); otherwise the sanitized name (grids/surfaces, MR, or any
    clean title). Best-effort — defaults to sanitized."""
    sanitized = make_valid_vtk_name(array_name)
    if not array_name or array_name == sanitized:
        return sanitized
    try:
        if rep_path and view is not None:
            ris = _scene_rep_for_view(rep_path, view)
            src = ris.source() if ris is not None else None
            if src is not None and _src_has_named_array(src, array_name):
                return array_name
    except Exception:
        pass
    return sanitized


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
    # Per-view: the ElementType decides what this rep RENDERS into a view —
    # IJK slicers+volume+rep_data / the visible channel / the extractor with
    # the deepest visible chain leaf. None → fall through to the legacy
    # registry (no per-view pipeline built for this rep).
    rep_in_scene = _scene_rep_for_view(rep_path, view)
    if rep_in_scene is not None:
        rendered = rep_in_scene.element_type.rendered_sources(rep_in_scene)
        if rendered is not None:
            return rendered, view
    out = []
    # Legacy shared IjkGrid fallback.
    ijk = source_registry.get_ijk_grid(rep_path)
    if ijk is not None:
        deepest_leaf = ijk._deepest_visible_leaf()
        grid_sources = list(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            grid_sources.append(ijk._src_slicer_volume)
        # Include rep_data — visible in range mode at full extent; harmless
        # in the hide path when already hidden in slice mode.
        if ijk._src_extract_init is not None:
            grid_sources.append(ijk._src_extract_init)
        for s in grid_sources:
            proxy = None
            if deepest_leaf is not None:
                proxy = deepest_leaf.pv_proxies.get(id(s))
            out.append(proxy if proxy is not None else s)
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
    # Clip output is per-(rep, view) — look it up via the scene_registry
    # on server.context. Slice's display is intentionally excluded (it's
    # tinted red so the cross-section stands out against the rep).
    rep_in_scene_clip_out = _scene_clip_output_for_view(rep_path, view)
    rep_in_scene = _scene_rep_for_view(rep_path, view)

    # Per-view: the ElementType decides what ColorBy fans onto for this rep
    # — IJK slicers+volume+thresholds / the visible channel / the extractor
    # + chain proxies. None → fall through to the legacy registry. The clip
    # output (per-(rep,view)) is appended here in every case.
    if rep_in_scene is not None:
        colored = rep_in_scene.element_type.color_sources(rep_in_scene)
        if colored is not None:
            out = list(colored)
            if rep_in_scene_clip_out is not None:
                out.append(rep_in_scene_clip_out)
            return out, view

    # Legacy shared IjkGrid fallback.
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
                            realization_idx=None, view=None):
    """See module docstring.

    `realization_idx` (default None) — when set on a multi-realization
    `array_path`, the resolver looks up the suffixed VTK array name
    `<sanitized_title>_real_<realization_idx>` first. Falls back to
    the legacy unsuffixed name when not set or not found, preserving
    the single-realization global-cursor behaviour for non-MR
    properties and for MR properties without per-property selection.

    `view` (default None) — when supplied, the per-view EnergisticsExtractor
    is consulted FIRST as a candidate source. For a wellbore frame the
    CHANNEL's OWN per-channel extractor (array_path = the channel leaf) is
    the candidate — the only proxy carrying that channel's array."""
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
    # When a view is supplied, consult that view's PER-VIEW source FIRST.
    # For a wellbore frame the array lives on the CHANNEL's OWN extractor
    # (array_path is the channel leaf), materialised on demand so it
    # resolves even when hidden — the frame-pathed source never carries
    # it. Other reps use the primary extractor.
    if view is not None:
        try:
            rep_in_scene = _scene_rep_for_view(rep_path, view)
            if rep_in_scene is not None:
                # The ElementType decides which per-view source carries the
                # array: a channel frame → the channel's own extractor;
                # other reps → the primary extractor.
                cand = rep_in_scene.element_type.array_candidate_source(
                    rep_in_scene, array_path,
                )
                if cand is not None:
                    candidate_sources.append(cand)
        except Exception:
            pass
    src = source_registry.get(rep_path)
    if src is not None:
        candidate_sources.append(src)
    else:
        for sid, s in pvsimple.GetSources().items():
            name = sid[0]
            if name == "rep" + (rep_path or "").replace('/', '_'):
                candidate_sources.append(s)
                break
    sanitized = make_valid_vtk_name(title)

    # Per-property MR path: look up the suffixed array name first. Falls
    # through to the unsuffixed lookup when the suffixed array isn't
    # present (e.g. the plugin hasn't loaded it yet).
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
        pass


def swap_to_scene_tfs(displays, target_view, array_name):
    """Swap each display's `LookupTable` / `ScalarOpacityFunction` to
    the per-(scene, array) proxies, so a COE edit in one view doesn't
    bleed across views sharing PV's default singleton-per-name LUT.

    Returns `(scene_lut, scene_pwf)` for the caller's downstream use
    (typically scalar-bar binding). Returns `(None, None)` when no scene
    owns `target_view` (legacy callers, bootstrap) — displays stay bound
    to PV's singleton LUT in that case.

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
        target_panel = (
            getattr(state, "drawer_target_view_id", "") or ""
            or getattr(state, "fespp_active_panel_id", "") or ""
        )
        scene_registry = getattr(server.context, "scene_registry", None)
        scene = scene_registry.get_scene(target_panel) if (scene_registry and target_panel) else None
        pv_view = scene.pv_view if scene is not None else None
        rep_path = getattr(state, "active_representation_path", "") or ""
        # `array_name` is the UI title. The render path keys its scoped
        # LUT on whichever VTK array name ACTUALLY exists on the per-view
        # source: the make_valid_vtk_name-SANITIZED name for grid /
        # surface properties (FESPP strips chars), but the RAW title for
        # a wellbore CHANNEL (its POINT array is named with the verbatim
        # title). Probe the source so the COE keys the SAME LUT — keying
        # blindly on the sanitized name would edit a different,
        # never-rendered LUT for channels (empty COE graph).
        base = real_base_name(array_name, rep_path, pv_view)
        if tree is not None:
            active_nodes = state.ui_active_node_reservoir or []
            if active_nodes:
                try:
                    array_path = tree.find_path(active_nodes[0])
                except Exception:
                    array_path = None
                if array_path and realization_dispatch.is_multirealization_property(tree, array_path):
                    idx = realization_dispatch.get_active_realization_for_view(
                        state, target_panel, array_path,
                    )
                    if idx is None:
                        idx = realization_dispatch.default_realization_for(
                            state, tree, array_path,
                        )
                    if idx is not None:
                        # Suffix so MR matches the rendering path's
                        # "<sanitized_title>_real_<idx>".
                        base = realization_dispatch.suffixed_array_name(
                            base, int(idx),
                        )
        if scene is None:
            return base, None
        return base, scene.get_or_create_lut(base)
    except Exception as exc:
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


def _clear_coloring(displays, view):
    """Drop ColorBy to SolidColor and hide the stale scalar bar on
    every display. Shared by the deselect path (array_path falsy) and
    the eye-toggle-resolves-to-nothing path (clear_on_empty=True).
    Hide the bar via SetScalarBarVisibility BEFORE severing the LUT
    wire (SetScalarColoring('',0)) — the TransferFunctionManager only
    reaps bars whose LUT it still tracks as wired."""
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


def apply_color_array(source_registry, tree, rep_path, array_path, view=None,
                       realization_idx=None, clear_on_empty=False):
    """See module docstring.

    `realization_idx` — when `array_path` is a multi-realization
    property and a specific realization is selected for the target
    view, this is the integer index. Threaded through to
    `resolve_array_for_path` so the suffixed VTK array name
    "<title>_real_<idx>" is used for the ColorBy call. Defaults to
    None (legacy behaviour: resolver picks the unsuffixed name).

    `clear_on_empty` — when `array_path` is given but resolves to no
    VTK array (a partial property, missing/not-yet-materialized data),
    clear the previous ColorBy + scalar bar instead of leaving them.
    Only the user-driven eye-toggle passes True; the re-apply/restore
    callers stay False so a transient load-time miss doesn't flicker a
    correctly-coloured rep to SolidColor."""
    displays = displays_for_rep_path(source_registry, rep_path, view=view)
    if not displays:
        return True
    if not array_path:
        # Deselect path (tree eye unchecked).
        _clear_coloring(displays, view)
        return True
    assoc, name = resolve_array_for_path(
        source_registry, tree, rep_path, array_path,
        realization_idx=realization_idx, view=view,
    )
    if not assoc or not name:
        # array_path was given but resolves to NOTHING: partial stub,
        # missing array, or (for a wellbore frame) a log on a partition
        # the extractor discards. For a user-driven eye-toggle
        # (clear_on_empty=True), clear the stale ColorBy + hide the
        # previous colour bar. Re-apply/restore callers stay tolerant of
        # transient load-time misses (default False). Returns False so
        # the caller can surface a "no data to display" alert.
        if clear_on_empty:
            _clear_coloring(displays, view)
        return False
    for d in displays:
        try:
            pvsimple.ColorBy(d, (assoc, name))
        except Exception:
            pass
    target_view = view if view is not None else pvsimple.GetActiveView()
    scene_lut, scene_pwf = swap_to_scene_tfs(displays, target_view, name)
    # Force the LUT range from the freshly-resolved VTK array.
    # `pvsimple.ColorBy`'s internal RescaleTransferFunctionToDataRange
    # reads a STALE proxy info cache when the upstream just re-extracted
    # (a wellbore channel/marker pick re-points the per-view extractor's
    # ExtractPath to a single leaf partition), leaving the LUT at [0,1] so
    # the tube paints flat. Read the range from the fresh client-side
    # array instead. Best-effort; skipped for indexed (categorical) LUTs
    # whose annotations a numeric rescale would disturb.
    try:
        ris = _scene_rep_for_view(rep_path, target_view)
        pv_src = ris._ensure_extractor() if ris is not None else None
        rescale_lut = scene_lut if scene_lut is not None else pvsimple.GetColorTransferFunction(name)
        if (pv_src is not None and rescale_lut is not None
                and not getattr(rescale_lut, "IndexedLookup", 0)):
            rng = _vtk_array_range_from_clientside(pv_src, name, assoc)
            if rng is not None:
                rescale_lut.RescaleTransferFunction(rng[0], rng[1])
    except Exception:
        pass
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
    return True
