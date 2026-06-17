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
import re

from paraview import servermanager as _sm


_NAME_INVALID_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def _sanitize(name: str) -> str:
    """Replace any character that VTK / ParaView would reject in a
    registration name. Used to derive deterministic proxy ids from
    arbitrary RESQML paths and property titles."""
    return _NAME_INVALID_RE.sub("_", name or "")


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
