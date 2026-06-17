"""Shared building blocks for the data-source representations.

Today this module hosts only the helpers that both `ijkgrid.py` and
`extract_block.py` rely on. As the refactor described in
REFACTOR_PLAN.md progresses it will also gain:

  - a `Representation` base class encoding the common interface
    (set_node_id, show, hide, add_threshold, apply_z_scale, …);
  - a base `ChainEntry` dataclass with the fields shared by every
    chain implementation (name / parent / array / visibility /
    bounds), letting each subclass keep its own proxy-storage shape
    (a single Threshold for ExtractBlock, a per-upstream dict for
    the multi-slicer IjkGrid case).

For now: keep this module intentionally minimal."""
from paraview import servermanager as _sm

# Re-export under the legacy name so existing call sites
# (extract_block, ijkgrid, rep_in_scene, …) keep working without an
# import churn. The canonical home for both sanitizers is
# `fespp_on_trame.app.utils.naming`. New code should import from there.
from fespp_on_trame.app.utils.naming import sanitize_proxy_name as _sanitize  # noqa: F401


def _find_registered_proxy(reg_name: str):
    """Resolve a registration name to a pvsimple proxy. The C++ side
    registers the per-rep extract filter in the "filters" group via
    RegisterPipelineProxy; pvsimple.FindSource only searches "sources",
    so we widen the lookup to "filters" first, then fall back to
    "sources" for compatibility with the legacy producer registration."""
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
    """Robust plugin-proxy instantiation. Returns a pvsimple-style
    wrapped proxy, or None when the definition truly doesn't exist
    server-side.

    Resolution order:

      1. `pvsimple.<proxy_class>` — preferred fast path (handles
         wrapping + registration in one call). Often absent for
         plugin proxies on session-reuse paths.
      2. `paraview.servermanager.filters.<proxy_class>` — lower-level
         attribute access. Same cache constraint as pvsimple's
         namespace, but sometimes refreshed differently.
      3. `vtkSMSessionProxyManager.NewProxy("filters", proxy_class)` —
         direct ProxyManager creation, bypasses the Python wrapper
         cache entirely. Always sees freshly-loaded plugin
         definitions (the underlying ProxyDefinitionManager is
         updated by LoadPlugin even when the wrapper namespace
         isn't). Registers the result and wraps it via
         `_getPyProxy` so callers can use it with the standard
         pvsimple API (Show/Hide/GetDisplayProperties/etc.).

    `inputs` is an optional dict of property_name → upstream proxy.
    For the common case `{"Input": upstream}` it wires the input
    using the SM property API when the direct path is hit. Pass None
    or an empty dict for proxies that don't need inputs.

    PARAVIEW.md documents why this fallback is necessary
    ("LoadPlugin doesn't always refresh pvsimple namespace")."""
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

    # 3: SMProxyManager direct (most robust — sees definitions the
    # wrapper namespace missed).
    try:
        spm = _sm.vtkSMProxyManager.GetProxyManager().GetActiveSessionProxyManager()
        sm_proxy = spm.NewProxy("filters", proxy_class)
        if sm_proxy is None:
            return None
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
                print(f"[plugin proxy] SetInputConnection({prop_name}) on"
                      f" {proxy_class}: {exc}")
        sm_proxy.UpdateVTKObjects()
        spm.RegisterProxy("sources", registration_name, sm_proxy)
        return _sm._getPyProxy(sm_proxy)
    except Exception as exc:
        print(f"[plugin proxy] direct NewProxy({proxy_class!r}) failed: {exc}")
        return None


def _apply_default_tint(display, color_hex):
    """Set DiffuseColor + AmbientColor (and Opacity if alpha is given)
    on a display. Does NOT touch ColorArrayName, so a later ColorBy
    will take over while this stays the fallback when no array is
    bound."""
    if display is None or not color_hex:
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
