from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.app.core.sources import leaf_rep
from fespp_on_trame.app.core.sources.collector import Collector
from fespp_on_trame.app.core.tree import Tree

server = get_server()
state = server.state
ctrl = server.controller


class Wellhead:
    """Well-head decoration for a WellboreTrajectory, anchored at its MD
    datum. Two parts:
      - a flagpole MARKER at the head position (the 'A' flag);
      - a NAME label: a 'Billboard 3D Text' actor that always faces the
        camera, so the well stays identifiable from any viewpoint. It shows
        the parent WELL name and is nudged a few pixels to the right of the
        marker (screen space, zoom-independent) so it never overlaps it.
    Colour follows the parent wellbore's `colorRGB` attribute when present."""

    def __init__(self, tree: Tree, node_id):
        self._source = None
        self._name_source = None

        title = tree.find_title(node_id) or "well"
        mddatum_position = tree.find_attribute_value(node_id, "mdDatumPosition")
        if mddatum_position is None:
            return

        position = [float(e.strip()) for e in mddatum_position.split(',')]
        colorRGB_str = tree.find_parent_attribute_value(node_id, "colorRGB")
        color = (
            [int(e.strip()) / 255.0 for e in colorRGB_str.split(',')]
            if colorRGB_str is not None
            else None
        )
        view = pvsimple.GetActiveView()

        # Head marker: a small flagpole at the MD datum.
        self._source = pvsimple.Text(registrationName=title + "_mdDatum")
        self._source.Text = 'A'
        # Text/Flagpole reps need the full composite representation (TextPropMode
        # etc. are not on a leaf SurfaceRepresentation) — opt out of the global
        # leaf-rep patch here. See leaf_rep.show_composite.
        head = leaf_rep.show_composite(self._source, view)
        head.TextPropMode = 'Flagpole Actor'
        head.BasePosition = position
        head.TopPosition = [position[0], position[1], position[2] + 0.01]
        head.FlagSize = 1.5
        if color is not None:
            head.Color = color

        # Well name: the parent WellboreFeature name (kind 'Wellbore'),
        # falling back to the trajectory title. Billboard text (always faces
        # the camera) anchored at the MD datum, then nudged right in screen
        # space so it sits beside the 'A' rather than over it.
        well_name = tree.find_ancestor_title_of_kind(node_id, "Wellbore") or title
        self._name_source = pvsimple.Text(registrationName=title + "_name")
        self._name_source.Text = well_name
        # Billboard text rep — composite only (see the flagpole above).
        label = leaf_rep.show_composite(self._name_source, view)
        label.TextPropMode = 'Billboard 3D Text'
        label.BillboardPosition = position
        label.Justification = 'Left'
        label.DisplayOffset = [20, 8]
        if color is not None:
            label.Color = color

    def delete(self):
        for source in (self._source, self._name_source):
            if source is not None:
                pvsimple.Delete(source)
        self._source = None
        self._name_source = None
