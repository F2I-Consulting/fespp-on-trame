"""Per-rep data source for non-IjkGrid representations.

One `ExtractBlockRepresentation` instance per loaded RESQML rep
(UnstructuredGrid, Trajectory, Grid2d, PointSet, Polyline, PolylineSet,
TriangulatedSet, …): one `EnergisticsExtractor` proxy chained on the
collector source, whose `ExtractPath` selects the rep's block. It is a DATA
source (array introspection, the values the statistics read): it is never
shown, each view's composite being the one visible representation
(engine/blockscope). Its threshold chain and display helpers were the
per-representation model's and went with it (overhaul, Q2 bis); a view's
thresholds live in its grid isolate.

`SourceRegistry` (in `source_registry.py`) holds a dict of instances."""
from paraview import simple as pvsimple
from paraview.servermanager import vtkSMPropertyHelper

from fespp_on_trame.engine.sources.representation import arrays_from_source


class ExtractBlockRepresentation:
    """One non-IjkGrid representation backed by an extractor filter on the
    FESPP collector."""

    def __init__(self, collector, tree, rep_path: str):
        self._collector = collector
        self._tree = tree
        self._rep_path = rep_path
        self._source = None  # set by _create_source()
        # the caller checks `self.source is None` and discards a half-built
        # instance
        self._create_source()

    @property
    def rep_path(self) -> str:
        return self._rep_path

    @property
    def source(self):
        """The rep's extractor proxy. None when creation failed."""
        return self._source

    def _create_source(self) -> bool:
        """Create the per-rep `EnergisticsExtractor` chained on the collector
        source; return False when the proxy cannot be created.

        Built via `_create_plugin_filter_proxy` rather than the collector's
        `ExtractRepPath` C++ command: its register-direct fallback
        (`spm->NewProxy + spm->RegisterProxy`) publishes the proxy on every
        call, including when a `rep_path` previously released via
        `pvsimple.Delete` is selected again. `LoadPlugin` does not always
        refresh the pvsimple wrapper namespace, so the plugin's proxies
        cannot be relied on as `pvsimple.<ProxyName>`."""
        from fespp_on_trame.engine.sources.representation import (
            _create_plugin_filter_proxy,
        )

        # anchored on the reader that holds the object, the file reader or the store
        reader_of = getattr(self._collector, "reader_of", None)
        collector_src = reader_of(self._rep_path) if reader_of is not None else self._collector.get_source()
        # Same `rep_<rep_path with / replaced by _>` naming as the C++ side,
        # so code that looks the proxy up by that name finds it.
        reg_name = "rep" + self._rep_path.replace("/", "_")
        ext = _create_plugin_filter_proxy(
            proxy_class="EnergisticsExtractor",
            registration_name=reg_name,
            inputs={"Input": collector_src},
        )
        if ext is None:
            return False
        vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(self._rep_path)
        ext.SMProxy.UpdateVTKObjects()
        try:
            ext.UpdatePipelineInformation()
        except Exception as exc:
            print(f"[fespp] extractor of {self._rep_path}: no pipeline information ({exc})",
                  flush=True)
        self._source = ext
        return True

    def delete(self):
        """Delete the extractor proxy. Idempotent."""
        src = self._source
        self._source = None
        if src is None:
            return
        try:
            pvsimple.Delete(src)
        except Exception as exc:
            print(f"[fespp] extractor of {self._rep_path}: not deleted ({exc})", flush=True)

    def available_arrays(self):
        """Return [(assoc, name), ...] for the rep's data arrays."""
        return arrays_from_source(self._source)
