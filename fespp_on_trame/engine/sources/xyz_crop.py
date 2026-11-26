"""The X / Y / Z crop of a representation that has no I/J/K: a surface, a
polyline set, a point set, an unstructured grid, a sub-representation —
the Geometry slicer in coordinates.

The scene cut's two filters (engine/blockscope/scene_cut_filters, the
plugin of 29/10) on the object alone: `FesppScenePrep` once, each cell's
extent along X, Y and Z computed in numpy (a polyline's segments and a point
set's points made cells of their own), then `FesppSceneCut` at each step,
the cells whose extent meets the box kept. A cell is kept when it meets the
box — whole cells, as the I/J/K crops keep them; a cut at one value
(low = high) keeps the cells the plane crosses; ≤ / ≥ cuts are ranges up to
the object's edge. One code for the scene and the object.

It replaced (30/10) a chain of ParaView Thresholds, one per axis the box
narrowed, with "Use Continuous Cell Range" on the points' coordinates: VTK
starts a cell's maximum at DBL_MIN, the smallest POSITIVE double, so on
negative values (every elevation of ALK) the lower bound was never applied
— the PO: "the min does not work" — and the chain was 4 to 5 times slower:
on ALK's 75 460 cells, a step 33–40 ms against 6–8 ms (scenario
`xyz_bench`, the same cells kept both ways), for 24–32 ms of preparation
once. The box filters (Extract Cells By Region, Clip in crinkle mode) keep a
cell when one of its POINTS is in the box: a range thinner than a cell keeps
almost nothing.

Values are the scene's: X, Y as the file has them, Z as ParaView draws it
— a depth CRS ("Z increasing downward") made negative by the plugin.
"""
import json

# a range narrower than the object by less than this part of its size is the
# whole object on that axis
_WHOLE = 1e-9


def narrows(box, bounds):
    """The axes (0, 1, 2) `box` ([[x0, x1], [y0, y1], [z0, z1]], a
    surface's I and J ranges before them read apart) narrows inside
    `bounds` ([x0, x1, y0, y1, z0, z1]); () for the whole object."""
    out = []
    for n, (lo, hi) in enumerate(box[-3:]):
        b0, b1 = float(bounds[2 * n]), float(bounds[2 * n + 1])
        tol = _WHOLE * max(1.0, abs(b1 - b0), abs(b0), abs(b1))
        if float(lo) > b0 + tol or float(hi) < b1 - tol:
            out.append(n)
    return tuple(out)


def boxes_text(box):
    """`box` as the cut filter's Boxes property: JSON of one box (its X, Y
    and Z: a surface's I and J ranges ahead of them are not the cut's)."""
    return json.dumps([[[float(lo), float(hi)] for lo, hi in box[-3:]]])


class CoordCrop:
    """One box of the X/Y/Z crop: the prep and cut filters on `upstream`;
    `tip` is what the isolate shows and chains on. A surface on a 2D grid
    (`ij`, its point extent) is first cut on its I and J by an
    ExtractSubset — its boxes are then [i, j, x, y, z]."""

    def __init__(self, upstream, name, ij=None):
        from fespp_on_trame.engine.blockscope.scene_crop import _load_filters
        prep_filter, cut_filter = _load_filters()
        self._name = name
        self._subset = None
        self._ij = list(ij) if ij else None
        if self._ij:
            from paraview import simple as pvsimple
            self._subset = pvsimple.ExtractSubset(registrationName=f"{name}_ij", Input=upstream)
            upstream = self._subset
        self._prep = prep_filter(registrationName=f"{name}_prep", Input=upstream)
        self._cut = cut_filter(registrationName=f"{name}_cut", Input=self._prep)
        self._text = None
        self._voi = None
        self.axes = ()        # the axes the box narrows (what the scenarios read)

    @property
    def tip(self):
        return self._cut

    def set_input(self, upstream):
        """What the crop cuts, again (the NaN cells hidden or shown)."""
        (self._subset or self._prep).Input = upstream

    def set_box(self, box, bounds=None):
        """The crop on `box` (the scene's coordinates, after a surface's I
        and J ranges); written only when it changes (a write re-executes
        the cut, not the preparation — an I or J range both)."""
        if self._subset is not None and len(box) == 5:
            self._put_ij(box[0], box[1])
        if bounds is not None:
            self.axes = narrows(box, bounds)
        text = boxes_text(box)
        if text != self._text:
            self._text = text
            self._cut.Boxes = text

    def _put_ij(self, ri, rj):
        """The I and J ranges on the subset: a cut at one index is the row
        of cells after it, as an I/J/K grid's crop draws it."""
        from fespp_on_trame.engine.sources.crop_extent import put_crop_extent
        ext = [int(ri[0]), int(ri[1]), int(rj[0]), int(rj[1]), self._ij[4], self._ij[5]]
        if ext != self._voi:
            self._voi = ext
            put_crop_extent(self._subset, ext, self._ij)

    def delete(self, view=None):
        """Every filter, downstream first."""
        from paraview import simple as pvsimple
        for proxy in (self._cut, self._prep, self._subset):
            if proxy is None:
                continue
            try:
                if view is not None:
                    pvsimple.Hide(proxy=proxy, view=view)
                pvsimple.Delete(proxy)
            except Exception as exc:
                print(f"[fespp] xyz crop {self._name}: teardown: {exc!r}", flush=True)
