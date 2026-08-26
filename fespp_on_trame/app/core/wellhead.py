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
        self._head = None
        self._label = None
        # UNSCALED md-datum position. The Z exaggeration is re-derived from
        # this baseline on every change (see `apply_z_scale`), so it must
        # never be overwritten with a scaled value.
        self._position = None

        title = tree.find_title(node_id) or "well"
        mddatum_position = tree.find_attribute_value(node_id, "mdDatumPosition")
        if mddatum_position is None:
            return

        position = [float(e.strip()) for e in mddatum_position.split(',')]
        self._position = position
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
        self._head = head
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
        self._label = label
        label.TextPropMode = 'Billboard 3D Text'
        label.BillboardPosition = position
        label.Justification = 'Left'
        label.DisplayOffset = [20, 8]
        if color is not None:
            label.Color = color

        # A wellhead created while a Z exaggeration is already active must
        # land on the SCALED trajectory, not at the raw datum.
        self.apply_z_scale(getattr(state, "ui_scale_z", 1.0))

    def apply_z_scale(self, zscale):
        """Follow the global Z exaggeration.

        A trajectory is real geometry, so the z-scale fan-out stretches it
        with `rep.Scale = [1, 1, zs]` and its head ends up at `z * zs`. The
        flagpole / billboard here CANNOT follow that way: a
        `TextSourceRepresentation` carries no `Scale` property at all (the
        fan-out's `except AttributeError: pass` silently skips it), and
        `BasePosition` / `TopPosition` / `BillboardPosition` are ABSOLUTE
        world coordinates that a rep transform does not move. Left alone the
        head stays at the raw datum while the trajectory travels to `z * zs`
        — they visibly drift apart. So re-derive the anchors from the
        unscaled baseline instead."""
        if self._position is None:
            return
        try:
            zs = float(zscale or 1.0)
        except (TypeError, ValueError):
            zs = 1.0
        x, y, z = self._position
        zz = z * zs
        try:
            if self._head is not None:
                self._head.BasePosition = [x, y, zz]
                self._head.TopPosition = [x, y, zz + 0.01]
        except Exception:
            pass
        try:
            if self._label is not None:
                self._label.BillboardPosition = [x, y, zz]
        except Exception:
            pass

    def delete(self):
        for source in (self._source, self._name_source):
            if source is not None:
                pvsimple.Delete(source)
        self._source = None
        self._name_source = None
        # Drop the rep handles too — they point at proxies just deleted.
        self._head = None
        self._label = None
