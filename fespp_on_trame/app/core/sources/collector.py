from trame.app import get_server
from paraview import simple as pvsimple

server = get_server()
state = server.state
controller = server.controller

EPC_COLLECTOR_GUI_NAME = "EPCCollector"


class Collector:
    """Thin wrapper around the FESPP EPCCollector ParaView source.

    Per-property multi-realization selection is driven entirely through
    the assembly tree: each `MultiRealization` / `MultiRealizationTimeSeries`
    node carries one child per realization index (type=Properties or
    type=TimeSeries). Checking the parent (a grouping) propagates to
    every realization child; checking a single child loads only that
    realization. Loaded realizations expose VTK arrays suffixed
    `<title>_real_<idx>` so multiple realizations of the same property
    co-exist on the partition — that's what makes per-view divergence
    possible (each view's ColorBy picks a different suffixed array)."""

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

        Belt-and-suspenders: the C++ EPC parse now catches its own
        FESAPI exceptions (see vtkEPCCollector::GetAllFiles /
        ResqmlDataRepository...::addFile) so a malformed EPC degrades to
        an empty/partial tree instead of terminating the process. This
        try/except is the Python-side net for any error the C++ now
        surfaces (vs. silently dying) — it turns it into a user-facing
        `state.load_error` rather than an unhandled traceback. It CANNOT
        catch a hard C++ SIGABRT/SIGSEGV (the process would already be
        gone); the C++ guards are what prevent that."""
        try:
            print(f"[DIAG load] add_file ENTER {epc_file_path}", flush=True)
            self._collector.SetPropertyWithName("Files", epc_file_path)
            self._collector.UpdatePipelineInformation()
            print("[DIAG load] add_file: UpdatePipelineInformation done", flush=True)
            controller.update_data_information()
            try:
                _asm = self._collector.GetClientSideObject().GetOutputDataObject(0)
                _nnodes = _asm.GetDataAssembly().GetNumberOfChildren(0) if _asm and _asm.GetDataAssembly() else -1
            except Exception:
                _nnodes = "?"
            print(f"[DIAG load] add_file DONE — tree top-level children={_nnodes}", flush=True)
            return True
        except Exception as exc:
            import os
            import traceback
            traceback.print_exc()
            state.load_error = (
                f"Failed to load '{os.path.basename(epc_file_path)}': {exc}"
            )
            state.flush()
            return False

    def show(self):
        pvsimple.Show(proxy=self._collector, view=pvsimple.GetActiveView())
