"""Per-representation ParaView sources (EnergisticsExtractor filter pattern).

Each resqml representation is materialized through an `EnergisticsExtractor`
filter chained on the FESPP collector (registered in the "filters" group).
The filter outputs a single-piece dataset of the partition's actual VTK type
(vtkPolyData / vtkUnstructuredGrid / vtkExplicitStructuredGrid). It does a
ShallowCopy in RequestData — no real data duplication — and the standard VTK
pipeline propagates upstream changes (selector add, realization swap,
property addDataArray) automatically.

This is the C++ "WithoutCopy" semantics, exposed programmatically via the
`ExtractRepPath` / `ExtractedRepProducerName` proxy properties on
vtkEPCCollector.

The previous incarnation was a detached `PVTrivialProducer` holding a shared
pointer to the partition data; it required explicit `Modified()` bumps from
Python to invalidate the proxy info cache after in-place data mutations.
Switching to a real filter removes that workaround.
"""
from trame.app import get_server
from paraview import simple as pvsimple
from paraview import servermanager as _sm
from paraview.servermanager import vtkSMPropertyHelper

server = get_server()
state = server.state


def _find_registered_proxy(reg_name: str):
    """Resolve a registration name to a pvsimple proxy. The C++ side registers
    the per-rep extract filter in the "filters" group via RegisterPipelineProxy
    (vtkEPCCollector::SetExtractRepPath). pvsimple.FindSource only searches
    "sources", so we widen the lookup to "filters" first, then fall back to
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
    """Set DiffuseColor + AmbientColor (+ Opacity if alpha provided) on a
    display. Does NOT touch ColorArrayName, so a later ColorBy call will
    take over while this stays as the fallback when no array is bound."""
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


class RepSources:
    def __init__(self, collector, tree):
        self._collector = collector
        self._tree = tree
        self._sources: dict = {}  # rep_path -> ExtractBlock proxy
        # Cache selector → rep_path | None (None = IjkGrid or unresolved).
        # Tree walks are stable for a given assembly; avoid re-walking on
        # every selector change when most selectors haven't moved.
        self._selector_cache: dict = {}

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------
    def _rep_path_for(self, selector_path: str):
        """Return the representation block path for a selector, or None if
        the selector maps to an IjkGrid (handled by IjkGrid class)."""
        if selector_path in self._selector_cache:
            return self._selector_cache[selector_path]
        node_id = self._tree.find_node_id(selector_path)
        if node_id is None:
            self._selector_cache[selector_path] = None
            return None
        rep_node_id = self._tree.find_representation_node(node_id)
        if rep_node_id is None:
            self._selector_cache[selector_path] = None
            return None
        if self._tree.find_type(rep_node_id) == "IjkGrid":
            self._selector_cache[selector_path] = None
            return None
        rp = self._tree.find_path(rep_node_id)
        self._selector_cache[selector_path] = rp
        return rp

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def get_or_create(self, rep_path: str):
        if not rep_path:
            return None
        src = self._sources.get(rep_path)
        if src is not None:
            return src
        # Trigger the FESPP-side extract via the proxy property mechanism.
        # `ExtractRepPath` is a string property whose command runs the C++
        # ExtractRepWithoutCopy logic and stores the resulting producer's
        # registration name; UpdatePropertyInformation refreshes the
        # information-only `ExtractedRepProducerName` so we can read it back.
        coll_proxy = self._collector.get_source().SMProxy
        vtkSMPropertyHelper(coll_proxy, "ExtractRepPath").Set(rep_path)
        coll_proxy.UpdateVTKObjects()
        coll_proxy.UpdatePropertyInformation()
        reg_name = vtkSMPropertyHelper(coll_proxy, "ExtractedRepProducerName").GetAsString()
        if not reg_name:
            return None
        src = _find_registered_proxy(reg_name)
        if src is None:
            return None
        self._sources[rep_path] = src

        view = pvsimple.GetActiveView()
        if view is not None:
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                rep.Representation = state.representation_active or "Surface"
                zs = self._current_z_scale()
                rep.Scale = [1.0, 1.0, zs]
                # Apply the assigned default solid color now so the rep is
                # visible in its unique color even if the user hasn't
                # activated it yet (a key affordance in manual apply mode
                # where many reps load at once without per-node activation).
                # Setting DiffuseColor is harmless even when ColorArrayName
                # gets set later — ParaView uses the array if non-empty,
                # otherwise falls back to DiffuseColor.
                _apply_default_tint(rep, (state.solid_color_by_rep or {}).get(rep_path))
            pvsimple.Show(proxy=src, view=view)
        return src

    def release(self, rep_path: str):
        src = self._sources.pop(rep_path, None)
        if src is None:
            return
        try:
            view = pvsimple.GetActiveView()
            if view is not None:
                pvsimple.Hide(proxy=src, view=view)
            pvsimple.Delete(src)
        except Exception:
            pass

    def release_all(self):
        for path in list(self._sources.keys()):
            self.release(path)

    def sync(self, selectors):
        """Ensure one extracted source exists per non-IjkGrid rep path present
        in selectors; drop sources whose rep path is no longer selected."""
        wanted = set()
        for sel in selectors or []:
            rp = self._rep_path_for(sel)
            if rp:
                wanted.add(rp)
        current = set(self._sources.keys())
        for gone in current - wanted:
            self.release(gone)
        for new_path in wanted - current:
            self.get_or_create(new_path)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get(self, rep_path: str):
        return self._sources.get(rep_path)

    def all_sources(self):
        return list(self._sources.values())

    def items(self):
        return list(self._sources.items())

    # ------------------------------------------------------------------
    # Broadcasts
    # ------------------------------------------------------------------
    def _current_z_scale(self) -> float:
        try:
            return float(getattr(state, "ui_scale_z", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0

    def apply_z_scale(self, zscale: float):
        view = pvsimple.GetActiveView()
        if view is None:
            return
        for src in self._sources.values():
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                rep.Scale = [1.0, 1.0, float(zscale)]

    def apply_representation(self, representation_type: str):
        view = pvsimple.GetActiveView()
        if view is None or not representation_type:
            return
        for src in self._sources.values():
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                try:
                    rep.Representation = representation_type
                except AttributeError:
                    pass
