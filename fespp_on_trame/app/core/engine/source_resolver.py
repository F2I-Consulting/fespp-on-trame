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
    ijk = source_registry.get_ijk_grid(rep_path)
    if ijk is not None:
        out.extend(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            out.append(ijk._src_slicer_volume)
        try:
            out.extend(ijk.all_threshold_sources())
        except Exception:
            pass
        # Include the clip's output so ColorBy fan-out picks up its
        # display alongside the grid's other sources — the clip
        # inherits the rep's coloring only once at creation, so without
        # this it stays coloured by whatever property was active back
        # then. Slice's display is intentionally excluded (it's tinted
        # red so the cross-section stands out)."""
        clip_out = ijk.clip_output() if hasattr(ijk, "clip_output") else None
        if clip_out is not None:
            out.append(clip_out)
        return out, view
    eb = source_registry.get_extract_block(rep_path)
    if eb is not None:
        if eb.source is not None:
            out.append(eb.source)
        out.extend(source_registry.all_chain_proxies(rep_path))
        clip_out = eb.clip_output() if hasattr(eb, "clip_output") else None
        if clip_out is not None:
            out.append(clip_out)
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


def resolve_array_for_path(source_registry, tree, rep_path, array_path):
    """See module docstring."""
    node_id = tree.find_node_id(array_path)
    if node_id is None:
        return None, None
    title = tree.find_title(node_id) or ""
    # MultiRealization synthetic nodes carry the actual VTK array
    # name in propTitle, not title.
    kind = tree.find_type(node_id) or ""
    if kind in ("MultiRealization", "MultiRealizationTimeSeries"):
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


def apply_color_array(source_registry, tree, rep_path, array_path, view=None):
    """See module docstring."""
    displays = displays_for_rep_path(source_registry, rep_path, view=view)
    if not displays:
        return
    if not array_path:
        for d in displays:
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
    assoc, name = resolve_array_for_path(source_registry, tree, rep_path, array_path)
    if not assoc or not name:
        return
    for d in displays:
        try:
            pvsimple.ColorBy(d, (assoc, name))
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
    target_view = view if view is not None else pvsimple.GetActiveView()
    try:
        if target_view is not None:
            for d in displays:
                try:
                    d.SetScalarBarVisibility(target_view, True)
                    break
                except Exception:
                    continue
            lut = pvsimple.GetColorTransferFunction(name)
            if lut is not None:
                bar = pvsimple.GetScalarBar(lut, target_view)
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
