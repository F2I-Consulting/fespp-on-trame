from trame.app import get_server
from paraview import simple as pvsimple

server = get_server()
state = server.state
controller = server.controller

EPC_COLLECTOR_GUI_NAME = "EPCCollector"


class Collector:
    """Thin wrapper around the FESPP EPCCollector ParaView source.

    Per-property multi-realization selection is driven through the assembly
    tree: each `MultiRealization` / `MultiRealizationTimeSeries` node carries
    one child per realization index. Checking the parent propagates to every
    realization child; checking a single child loads only that realization.
    Loaded realizations expose VTK arrays suffixed `<title>_real_<idx>` so
    multiple realizations of the same property co-exist on the partition,
    which is what lets each view's ColorBy pick a different suffixed array."""

    def __init__(self):
        self._collector = pvsimple.EPCCollector(registrationName=EPC_COLLECTOR_GUI_NAME)
        self._representationType = None
        self._scale_z = [1.0, 1.0, 1.0]

        self.show()

    @property
    def representationType(self):
        return self._representationType

    @representationType.setter
    def representationType(self, value):
        if value != self._representationType:
            self._representationType = value

    @property
    def scale_z(self):
        return self._scale_z

    @scale_z.setter
    def scale_z(self, scale):
        if scale != self._scale_z:
            self._scale_z = scale

    def get_source(self):
        return self._collector

    def get_representation(self):
        return pvsimple.GetRepresentation(proxy=self._collector, view=pvsimple.GetActiveView())

    def add_file(self, epc_file_path: str) -> bool:
        """Push a new EPC path into the Files property and re-parse the
        assembly into the Python tree.

        The C++ EPC parse catches its own FESAPI exceptions so a malformed
        EPC degrades to an empty/partial tree rather than terminating the
        process. This try/except turns any error the C++ surfaces into a
        user-facing `state.load_error`; it cannot catch a hard C++
        SIGABRT/SIGSEGV (the C++ guards are what prevent that)."""
        try:
            self._collector.SetPropertyWithName("Files", epc_file_path)
            self._collector.UpdatePipelineInformation()
            controller.update_data_information()
            try:
                _asm = self._collector.GetClientSideObject().GetOutputDataObject(0)
                _nnodes = _asm.GetDataAssembly().GetNumberOfChildren(0) if _asm and _asm.GetDataAssembly() else -1
            except Exception:
                _nnodes = "?"
            return True
        except Exception as exc:
            import os
            state.load_error = (
                f"Failed to load '{os.path.basename(epc_file_path)}': {exc}"
            )
            state.flush()
            return False

    def show(self):
        pvsimple.Show(proxy=self._collector, view=pvsimple.GetActiveView())
