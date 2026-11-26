"""Shared building blocks for the data-source representations.

The helpers that `ijkgrid.py` and `extract_block.py` both rely on."""
from paraview import servermanager as _sm

# `_sanitize` is re-exported for the modules that import it from here; its
# canonical home is `fespp_on_trame.engine.utils.naming`, which new code imports.
from fespp_on_trame.engine.utils.naming import sanitize_proxy_name as _sanitize  # noqa: F401


def _find_registered_proxy(reg_name: str):
    """Resolve a registration name to a pvsimple proxy.

    The C++ side registers the per-rep extract filter in the "filters" group
    via RegisterPipelineProxy, while pvsimple.FindSource only searches
    "sources". The lookup therefore tries "filters" first, then "sources" for
    proxies registered as producers."""
    if not reg_name:
        return None
    pm = _sm.ProxyManager()
    for group in ("filters", "sources"):
        sm_proxy = pm.GetProxy(group, reg_name)
        if sm_proxy is not None:
            try:
                return _sm._getPyProxy(sm_proxy)
            except Exception:
                return sm_proxy
    return None


def _create_plugin_filter_proxy(proxy_class: str, registration_name: str,
                                 inputs: dict | None = None):
    """Instantiate a plugin filter proxy, whichever namespace knows it.

    Returns a pvsimple-style wrapped proxy, or None when the definition does
    not exist server-side.

    Resolution order:

      1. `pvsimple.<proxy_class>`: fast path (wrapping + registration in
         one call). Often absent for plugin proxies on session-reuse paths.
      2. `paraview.servermanager.filters.<proxy_class>`: lower-level
         attribute access; same cache constraint as pvsimple's namespace.
      3. `vtkSMSessionProxyManager.NewProxy("filters", proxy_class)`:
         direct ProxyManager creation, bypassing the Python wrapper cache.
         Always sees freshly loaded plugin definitions (LoadPlugin updates
         the ProxyDefinitionManager even when the wrapper namespace is not
         refreshed). Registers the result and wraps it via `_getPyProxy`
         so callers can use the standard pvsimple API.

    `inputs` is an optional dict of property_name → upstream proxy. For the
    common case `{"Input": upstream}` it wires the input via the SM property
    API on the direct path. Pass None / empty for proxies with no inputs."""
    from paraview import simple as pvsimple
    from paraview import servermanager as _sm

    # 1 + 2: cached Python wrappers (preferred when available).
    ctor = getattr(pvsimple, proxy_class, None)
    if ctor is None:
        ctor = getattr(_sm.filters, proxy_class, None)
    if ctor is not None:
        kwargs = {"registrationName": registration_name}
        if inputs:
            kwargs.update(inputs)
        return ctor(**kwargs)

    # 3: SMProxyManager direct, sees definitions the wrapper namespace lacks.
    try:
        spm = _sm.vtkSMProxyManager.GetProxyManager().GetActiveSessionProxyManager()
        sm_proxy = spm.NewProxy("filters", proxy_class)
        if sm_proxy is None:
            return None
        # NewProxy hands over the reference of the creation, and the Python
        # wrapper takes one more: without this release the proxy outlives
        # every Delete, and with it the data its last execution holds (a
        # log's tube, three megabytes a tick)
        sm_proxy.UnRegister(None)
        for prop_name, upstream in (inputs or {}).items():
            if upstream is None:
                continue
            input_prop = sm_proxy.GetProperty(prop_name)
            if input_prop is None:
                continue
            sm_upstream = upstream.SMProxy if hasattr(upstream, "SMProxy") else upstream
            try:
                input_prop.SetInputConnection(0, sm_upstream, 0)
            except Exception as exc:
                pass
        sm_proxy.UpdateVTKObjects()
        spm.RegisterProxy("sources", registration_name, sm_proxy)
        return _sm._getPyProxy(sm_proxy)
    except Exception as exc:
        return None


def suppress_selection_labels(display):
    """Zero the per-representation label/selection overhead on a display.

    Every ParaView geometry representation eagerly builds a
    ``vtkSelectionRepresentation`` + ``vtkDataLabelRepresentation`` whose
    ``vtkLabeledDataMapper`` pre-allocates ``SelectionMaximumNumberOfLabels``
    (default 100) ``vtkTextMapper`` objects, each carrying a full VTK executive,
    even though this app never shows ParaView data labels and drives its own
    selection through the tree. With ONE representation per source / slicer /
    threshold (the deliberate N-source design, kept for type-specific filters),
    that overhead accumulates into tens of thousands of VTK objects and ends in
    a ``std::bad_alloc`` on mass loads (allocated along ``Show`` -> … ->
    ``vtkLabeledDataMapper::AllocateLabels``). Setting the label count to 0
    (and hiding the sub-reps) removes the overhead while keeping Surface
    rendering, ColorBy, LUTs and every filter intact. Idempotent; never raises.
    See also `leaf_rep`, which avoids the composite representation entirely.
    """
    if display is None:
        return
    try:
        known = set(display.ListProperties())
    except Exception:
        known = None
    for attr, val in (
        ("SelectionMaximumNumberOfLabels", 0),
        ("SelectionVisibility", 0),
        ("SelectionCellLabelVisibility", 0),
        ("SelectionPointLabelVisibility", 0),
    ):
        # Not every representation class carries every one of these.
        if known is not None and attr not in known:
            continue
        try:
            setattr(display, attr, val)
        except Exception:
            pass


def _apply_default_tint(display, color_hex):
    """Set DiffuseColor + AmbientColor (and Opacity if alpha is given)
    on a display from a ``#RRGGBB[AA]`` colour.

    Does NOT touch ColorArrayName, so a later ColorBy takes over while
    this tint stays the fallback when no array is bound."""
    if display is None:
        return
    suppress_selection_labels(display)
    if not color_hex:
        return
    h = color_hex.lstrip('#')
    if len(h) < 6:
        return
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        display.DiffuseColor = [r, g, b]
        display.AmbientColor = [r, g, b]
        if len(h) >= 8:
            display.Opacity = int(h[6:8], 16) / 255.0
    except Exception:
        pass


#: Display attributes copied from a parent onto a derived (threshold) proxy
#: so it mirrors its parent visually. The bool is "treat as a list/vector".
_DISPLAY_INHERIT_ATTRS = (
    ("Representation", False),
    ("Scale", True),
    ("ColorArrayName", True),
    ("LookupTable", False),
    ("DiffuseColor", True),
    ("AmbientColor", True),
    ("Opacity", False),
)


def arrays_from_source(src):
    """Return ``[(assoc, name), …]`` for a PV proxy's CellData / PointData
    arrays.

    Deduplicated, association = ``"CELLS"`` / ``"POINTS"``. Empty when
    `src` is None. Shared by every threshold/array UI path."""
    if src is None:
        return []
    out, seen = [], set()
    for store_attr, assoc in (("CellData", "CELLS"), ("PointData", "POINTS")):
        try:
            store = getattr(src, store_attr)
            for i in range(store.GetNumberOfArrays()):
                a = store.GetArray(i)
                if a is None:
                    continue
                name = a.Name
                key = (assoc, name)
                if name and key not in seen:
                    seen.add(key)
                    out.append(key)
        except Exception:
            pass
    return out


def array_range_from_source(src, array_name):
    """Return ``(min, max)`` for the named array on a PV proxy, or None."""
    if src is None or not array_name:
        return None
    for store_attr in ("CellData", "PointData"):
        try:
            store = getattr(src, store_attr)
            for i in range(store.GetNumberOfArrays()):
                a = store.GetArray(i)
                if a is not None and a.Name == array_name:
                    rng = a.GetRange()
                    return (float(rng[0]), float(rng[1]))
        except Exception:
            pass
    return None


def rep_type_for(state, rep_path):
    """Display type ("Surface" / "Wireframe" / …) chosen for ONE rep.

    The Attributes panel is strictly per-rep, never a broadcast.
    "Surface" for reps the user never touched."""
    try:
        by_rep = getattr(state, "ui_rep_type_by_rep", {}) or {}
        return by_rep.get(rep_path) or "Surface"
    except Exception:
        return "Surface"


def resolve_assoc(src, array_name):
    """Association (``"CELLS"`` / ``"POINTS"``) of the named array on `src`,
    or None. Convenience over `arrays_from_source`."""
    for assoc, name in arrays_from_source(src):
        if name == array_name:
            return assoc
    return None


def inherit_display(upstream, target_proxy, view):
    """Copy the display look of ``upstream`` onto ``target_proxy`` in ``view``.

    Copies Representation / Scale / ColorArrayName / LookupTable /
    Diffuse+Ambient color / Opacity, so a derived proxy (a threshold output)
    mirrors its parent the moment it appears, in both property-color mode
    (array + LUT) and SolidColor mode (Diffuse/Ambient).

    Single source of truth shared by the per-view (`RepInScene`),
    `ExtractBlockRepresentation` and `IjkGrid` threshold chains, which differ
    only in how they resolve ``view``. No-op on any missing piece; never
    raises."""
    if view is None:
        return
    try:
        from paraview import simple as pvsimple
        src_disp = pvsimple.GetDisplayProperties(upstream, view=view)
        dst_disp = pvsimple.GetRepresentation(proxy=target_proxy, view=view)
        if src_disp is None or dst_disp is None:
            return
        suppress_selection_labels(dst_disp)
        for attr, as_list in _DISPLAY_INHERIT_ATTRS:
            try:
                val = getattr(src_disp, attr)
                if as_list:
                    val = list(val)
                setattr(dst_disp, attr, val)
            except Exception:
                pass
    except Exception:
        pass
