from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.engine.tree import Tree

server = get_server()
state = server.state
ctrl = server.controller


class TimeSeries:
    """Companion of a TimeSeries tree node. Locks the LUT range to the
    series' (minvalue, maxvalue) attributes so the colormap stays
    comparable across timesteps, and refreshes ui_time_label from the
    current ParaView TimeKeeper value."""

    def __init__(self, tree: Tree, node_id):
        self._source = None
        self._tree = tree

        title = tree.find_title(node_id)
        min_value = tree.find_attribute_value(node_id, "minvalue")
        max_value = tree.find_attribute_value(node_id, "maxvalue")
        if min_value is not None and max_value is not None:
            timeSeriesPropertyLUT = pvsimple.GetColorTransferFunction(title)
            timeSeriesPropertyLUT.RescaleTransferFunction(float(min_value), float(max_value))

        self.refresh_label()

    def refresh_label(self):
        """Republish `ui_time_label` from the current TimeKeeper value.
        Also restores the label after ANOTHER tab's companion is deleted:
        the label must survive as long as one tab still has a checked
        TimeSeries (see Selector._reset_timeseries)."""
        index = state.time_index
        if index is not None:
            label = self._tree.find_attribute_value(0, f"time{pvsimple.GetTimeKeeper().TimestepValues[index]:.6f}")
            if label is not None:
                state.ui_time_label = label
            else:
                state.ui_time_label = f"time{pvsimple.GetTimeKeeper().TimestepValues[index]:.6f}"

    def delete(self):
        """Clear `ui_time_label`; a surviving companion republishes it."""
        state.ui_time_label = ""
