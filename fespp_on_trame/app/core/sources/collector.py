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
        assembly into the Python tree."""
        self._collector.SetPropertyWithName("Files", epc_file_path)
        self._collector.UpdatePipelineInformation()
        controller.update_data_information()
        return True

    def show(self):
        pvsimple.Show(proxy=self._collector, view=pvsimple.GetActiveView())
