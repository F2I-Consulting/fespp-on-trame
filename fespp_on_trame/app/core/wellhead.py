from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.tree import Tree

server = get_server()
state = server.state
ctrl = server.controller


class Wellhead:
    """Flagpole label rendered at the MD datum of a WellboreTrajectory.
    Picks up the trajectory's `mdDatumPosition` attribute and the
    wellbore's parent colorRGB attribute when available; otherwise
    leaves the default ParaView colour."""

    def __init__(self, tree: Tree, node_id):
        self._source = None

        title = tree.find_title(node_id)
        mddatum_position = tree.find_attribute_value(node_id, "mdDatumPosition")
        if mddatum_position is not None:
            self._source = pvsimple.Text(registrationName=title + "_mdDatum")
            self._source.Text = 'A'
            display = pvsimple.Show(proxy=self._source, view=pvsimple.GetActiveView())
            display.TextPropMode = 'Flagpole Actor'
            display.BasePosition = [float(element.strip()) for element in mddatum_position.split(',')]
            display.TopPosition = [float(element.strip()) for element in mddatum_position.split(',')]
            display.TopPosition[2] = display.TopPosition[2] + 0.01
            display.FlagSize = 1.5
            colorRGB_str = tree.find_parent_attribute_value(node_id, "colorRGB")

            if colorRGB_str is not None:
                color_255 = [int(element.strip()) for element in colorRGB_str.split(',')]
                display.Color = [c / 255.0 for c in color_255]

            pvsimple.Show(proxy=self._source, view=pvsimple.GetActiveView())

    def delete(self):
        if self._source is not None:
            pvsimple.Delete(self._source)
