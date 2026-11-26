"""A colour table on the DIVERGING map, over a property's TRUE range.

The diverging map (DIVERGING_PRESET: blue negative, white zero, red
positive) is laid symmetric about zero, from -M to M, M the largest value in
size of the range; the table keeps only the stretch of it the range covers.
A range from 4.6e6 to 8.1e6 is then drawn in reds only, from the red of 4.6e6
to the deep red of 8.1e6, and its bar says 4.6e6 to 8.1e6: the colour says
on which side of zero a value is and how far, the range stays the data's.

A table painted by code (indexed) gives each code the colour its value has on
the same map: its bar lists its codes.

The map's colours come from ParaView's own preset, interpolated in its colour
space (`ramp`); a table is written through its proxy's properties
(engine/categorical_palette's helpers), as every table of the app is."""
import json

from fespp_on_trame.engine import categorical_palette
from fespp_on_trame.engine.utils.color_palette import DIVERGING_PRESET

#: vtkColorTransferFunction's colour spaces, by the name a preset gives
SPACES = {"RGB": 0, "HSV": 1, "Lab": 2, "Diverging": 3, "Lab/CIEDE2000": 4, "Step": 5}

_ramps = {}


def ramp(preset=DIVERGING_PRESET):
    """(colour space name, [(t, r, g, b)] with t from -1 to 1) of `preset`,
    read once from ParaView's presets."""
    if preset not in _ramps:
        from paraview import servermanager
        presets = servermanager.vtkSMTransferFunctionPresets.GetInstance()
        found = next((i for i in range(presets.GetNumberOfPresets()) if presets.GetPresetName(i) == preset), None)
        if found is None:
            raise KeyError(f"no colour preset named {preset!r} in this ParaView")
        held = json.loads(presets.GetPresetAsString(found))
        pts = [float(v) for v in held["RGBPoints"]]
        low, high = pts[0], pts[-4]
        span = (high - low) or 1.0
        _ramps[preset] = (str(held.get("ColorSpace") or "RGB"),
                          [(2.0 * (pts[i] - low) / span - 1.0, pts[i + 1], pts[i + 2], pts[i + 3])
                           for i in range(0, len(pts), 4)])
    return _ramps[preset]


def reach(low, high):
    """M: the largest value in size of the range (1 for a range of zeros)."""
    return max(abs(float(low)), abs(float(high))) or 1.0


def _function(low, high, preset):
    """The map laid from -M to M, as a vtkColorTransferFunction."""
    from vtkmodules.vtkRenderingCore import vtkColorTransferFunction
    space, nodes = ramp(preset)
    big = reach(low, high)
    ctf = vtkColorTransferFunction()
    ctf.SetColorSpace(SPACES.get(space, 0))
    for t, r, g, b in nodes:
        ctf.AddRGBPoint(t * big, r, g, b)
    return ctf, space, nodes, big


def points(low, high, preset=DIVERGING_PRESET):
    """(RGBPoints [x, r, g, b, …], colour space) of the table over
    [`low`, `high`]: the map's colours at both ends and at each of its own
    nodes inside (zero among them), interpolated in the map's colour space —
    the stretch of the symmetric map the range covers."""
    low, high = float(low), float(high)
    ctf, space, nodes, big = _function(low, high, preset)
    xs = sorted({low, high} | {t * big for t, *_rgb in nodes if low < t * big < high})
    out = []
    for x in xs:
        out += [x, *ctf.GetColor(x)]
    return out, space


def colours(values, low, high, preset=DIVERGING_PRESET):
    """[r, g, b, …]: the colour of each value on the map of the range."""
    ctf = _function(low, high, preset)[0]
    out = []
    for v in values:
        out += list(ctf.GetColor(float(v)))
    return out


def paint(lut, low, high, preset=DIVERGING_PRESET):
    """`lut` on the map over [`low`, `high`]: its points and colour space; a
    table painted by code, its codes' colours too. (points, colours) written,
    to tell later whether anyone changed them."""
    pts, space = points(low, high, preset)
    lut.RGBPoints = pts
    try:
        lut.ColorSpace = space
    except AttributeError as exc:
        print(f"[fespp] diverging table: colour space {space} not set ({exc!r})", flush=True)
    codes = list(categorical_palette.annotations_of(lut)) if categorical_palette.is_indexed(lut) else []
    cols = colours(codes, low, high, preset) if codes else []
    if cols:
        categorical_palette.set_code_colours(lut, cols)
    lut.SMProxy.UpdateVTKObjects()
    return pts, cols
