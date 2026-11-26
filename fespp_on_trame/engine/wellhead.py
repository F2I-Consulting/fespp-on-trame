from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.engine.sources import leaf_rep
from fespp_on_trame.engine.state_defaults import z_scale_of
from fespp_on_trame.engine.tree import Tree

server = get_server()
state = server.state
ctrl = server.controller

#: what the flag shows instead of the letter 'A': (font file, the glyph's
#: character, its size) — a picture of a font, drawn as the letter was, the
#: same size on screen whatever the distance; None keeps the letter
PICTOGRAM = None


def _beside(size):
    """Where the name stands from a pictogram of `size`, on screen."""
    return [int(size) + 6, 8]


class Wellhead:
    """Well-head decoration for a WellboreTrajectory, anchored at its MD
    datum. Two parts:
      - a flagpole MARKER at the head position (the 'A' flag);
      - a NAME label: a 'Billboard 3D Text' actor that always faces the
        camera, so the well stays identifiable from any viewpoint. It shows
        the parent WELL name and is nudged a few pixels to the right of the
        marker (screen space, zoom-independent) so it never overlaps it.
    Colour follows the parent wellbore's `colorRGB` attribute when present.
    Without an `mdDatumPosition` attribute nothing is drawn."""

    def __init__(self, tree: Tree, node_id, view=None, view_id=None):
        self._source = None
        self._name_source = None
        self._head = None
        self._label = None
        # Identity for the incremental sync (Selector.sync_wellheads) and
        # the per-view eye follow: the trajectory node and the view it
        # decorates.
        self.node_id = node_id
        self.view_id = view_id
        # UNSCALED md-datum position. The Z exaggeration is re-derived from
        # this baseline on every change (see `apply_z_scale`), so it must
        # never be overwritten with a scaled value.
        self._position = None
        # Original (head, label) colours while highlighted; None = not lit.
        self._saved_colors = None
        # the pictogram's size on screen, when it shows one, and the share of
        # the screen's resolution the view draws at (`set_size`)
        self._size = PICTOGRAM[2] if PICTOGRAM is not None else None
        self._ratio = 1.0

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
        view = view or pvsimple.GetActiveView()

        # Head marker: a small flagpole at the MD datum.
        self._source = pvsimple.Text(registrationName=title + "_mdDatum")
        self._source.Text = 'A'
        # Text/Flagpole reps need the full composite representation (TextPropMode
        # etc. are not on a leaf SurfaceRepresentation): opt out of the global
        # leaf-rep patch here. See leaf_rep.show_composite.
        head = leaf_rep.show_composite(self._source, view)
        self._head = head
        head.TextPropMode = 'Flagpole Actor'
        head.BasePosition = position
        head.TopPosition = [position[0], position[1], position[2] + 0.01]
        head.FlagSize = 1.5
        if PICTOGRAM is not None:
            font, glyph, size = PICTOGRAM
            self._source.Text = glyph
            head.FontFamily = "File"
            head.FontFile = font
            head.FontSize = size
        if color is not None:
            head.Color = color

        # Well name: the parent WellboreFeature name (kind 'Wellbore'),
        # falling back to the trajectory title. Billboard text (always faces
        # the camera) anchored at the MD datum, then nudged right in screen
        # space so it sits beside the 'A' rather than over it.
        well_name = tree.find_ancestor_title_of_kind(node_id, "Wellbore") or title
        self._name_source = pvsimple.Text(registrationName=title + "_name")
        self._name_source.Text = well_name
        # Billboard text rep: composite only (see the flagpole above).
        label = leaf_rep.show_composite(self._name_source, view)
        self._label = label
        label.TextPropMode = 'Billboard 3D Text'
        label.BillboardPosition = position
        label.Justification = 'Left'
        # beside the flag, clear of the picture when it shows one
        label.DisplayOffset = _beside(self._size) if PICTOGRAM is not None else [20, 8]
        # the name's size beside a pictogram at its first size: both get smaller together (`set_size`)
        self._label_size = int(label.FontSize or 18)
        if color is not None:
            label.Color = color

        # A wellhead created while a Z exaggeration is already active must
        # land on the SCALED trajectory, not at the raw datum.
        self.apply_z_scale(z_scale_of(state, self.view_id))

    def apply_z_scale(self, zscale):
        """Follow the Z exaggeration of the view.

        A trajectory is real geometry, so the z-scale fan-out stretches it
        with `rep.Scale = [1, 1, zs]` and its head ends up at `z * zs`. The
        flagpole / billboard here CANNOT follow that way: a
        `TextSourceRepresentation` carries no `Scale` property at all (the
        fan-out's `except AttributeError: pass` silently skips it), and
        `BasePosition` / `TopPosition` / `BillboardPosition` are ABSOLUTE
        world coordinates that a rep transform does not move. Left alone, the
        head would stay at the raw datum while the trajectory moves to
        `z * zs`, so the anchors are re-derived from the unscaled baseline."""
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

    def set_size(self, size, ratio=1.0):
        """The pictogram drawn `size` on screen (when the flag shows one),
        the name beside it, smaller or larger with it; `ratio`: the share of
        the screen's resolution the view draws at (below 1 in a drag's
        frames, which the browser stretches back to the screen's)."""
        if PICTOGRAM is None or self._head is None or (size, ratio) == (self._size, self._ratio):
            return
        self._size, self._ratio = size, ratio
        self._head.FontSize = max(1, int(round(size * ratio)))
        if self._label is not None:
            self._label.DisplayOffset = [int(round(v * ratio)) for v in _beside(size)]
            name = max(6, int(round(self._label_size * float(size) / float(PICTOGRAM[2]))))
            self._label.FontSize = max(1, int(round(name * ratio)))

    @property
    def size(self):
        return self._size

    @property
    def node_position(self):
        """The head, unscaled (data space); None without one."""
        return list(self._position) if self._position is not None else None

    # ParaView's own selection pink, so the wellhead reads as PART of the
    # highlighted trajectory rather than a different annotation.
    _HL_COLOR = (1.0, 0.0, 1.0)

    def set_highlight(self, on):
        """Tint the flag + name in the selection colour (and back). The
        wellhead is a COMPANION text rep, not a block of the PDC, so the
        composite block selection can never reach it: this is how a
        highlighted trajectory keeps its name lit too. Saved colours live on
        SELF: proxy wrappers refuse new attributes."""
        if on:
            if self._saved_colors is None:
                self._saved_colors = tuple(
                    tuple(rep.Color) if rep is not None else None
                    for rep in (self._head, self._label))
            for rep in (self._head, self._label):
                if rep is not None:
                    try:
                        rep.Color = list(self._HL_COLOR)
                    except Exception:
                        pass
        elif self._saved_colors is not None:
            for rep, col in zip((self._head, self._label), self._saved_colors):
                if rep is not None and col is not None:
                    try:
                        rep.Color = list(col)
                    except Exception:
                        pass
            self._saved_colors = None

    def set_visible(self, on):
        """Follow the trajectory's eye: head + name show/hide together."""
        for rep in (self._head, self._label):
            if rep is None:
                continue
            try:
                rep.Visibility = 1 if on else 0
            except Exception:
                pass

    def delete(self):
        """Delete both text sources; the wellhead is inert afterwards."""
        for source in (self._source, self._name_source):
            if source is not None:
                pvsimple.Delete(source)
        self._source = None
        self._name_source = None
        # Drop the rep handles too: they point at proxies just deleted.
        self._head = None
        self._label = None
