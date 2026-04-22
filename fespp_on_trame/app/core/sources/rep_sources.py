"""Per-representation ParaView sources (lazy ExtractBlock pattern).

Each resqml representation is materialized as its own ExtractBlock proxy whose
input is the FESPP multiblock (EPCCollector / ETP). Arrays are shared by
pointer (VTK shallow copy), so this adds no memory duplication.

IjkGrid keeps its own extraction mechanism (plugin-level extract_block +
slicer sources) and is explicitly skipped here.
"""
from trame.app import get_server
from paraview import simple as pvsimple

server = get_server()
state = server.state


def _safe_name(path: str) -> str:
    return "rep" + path.replace("/", "_")


class RepSources:
    def __init__(self, collector, tree):
        self._collector = collector
        self._tree = tree
        self._sources: dict = {}  # rep_path -> ExtractBlock proxy

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------
    def _rep_path_for(self, selector_path: str):
        """Return the representation block path for a selector, or None if
        the selector maps to an IjkGrid (handled by IjkGrid class)."""
        node_id = self._tree.find_node_id(selector_path)
        if node_id is None:
            return None
        rep_node_id = self._tree.find_representation_node(node_id)
        if rep_node_id is None:
            return None
        if self._tree.find_type(rep_node_id) == "IjkGrid":
            return None
        return self._tree.find_path(rep_node_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def get_or_create(self, rep_path: str):
        if not rep_path:
            return None
        src = self._sources.get(rep_path)
        if src is not None:
            return src
        input_source = self._collector.get_source()
        src = pvsimple.ExtractBlock(
            registrationName=_safe_name(rep_path),
            Input=input_source,
        )
        src.Selectors = [rep_path]
        src.UpdatePipelineInformation()
        self._sources[rep_path] = src

        view = pvsimple.GetActiveView()
        if view is not None:
            rep = pvsimple.GetRepresentation(proxy=src, view=view)
            if rep is not None:
                rep.Representation = state.representation_active or "Surface"
                zs = self._current_z_scale()
                rep.Scale = [1.0, 1.0, zs]
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
