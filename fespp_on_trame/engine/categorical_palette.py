"""One colour per code for a discrete or categorical property.

A facies, a zone index, a region: a property whose values are CODES, not
quantities. Painted with a continuous ramp, five codes make a rainbow and
a reader cannot tell code 3 from a value between 2 and 4. This module
turns the view's LUT into an INDEXED lookup — one colour per code, the
code's name from the file's string lookup when the property has one
(`utils.categories`), else the code itself — and reads it back for the
Colormap card. The 3D colour bar then lists the codes instead of a scale.

What the caller gives: the tree (the property's kind), the datasets of the
block the property colours (the codes present in the data — every block is
part of ONE shared source, whose first block is seldom the one), the VTK
array name. What comes back:
the categories, or None with a reason when the property is not painted
this way — a continuous property, or more distinct values than the
palette can name (`MAX_CATEGORIES`, the cap the threshold slider uses),
which the card then says.

Pure numpy over the client-side array plus ParaView's LUT proxy; the
proxy properties are written through `SMProxy.GetProperty(...)` because
pvsimple's wrapper rejects `IndexedLookup` and its siblings as unknown
attributes on some builds.
"""
import colorsys
import re

from fespp_on_trame.engine.blockscope import assembly_index
from fespp_on_trame.engine.sources.chain_domain import (
    INT_NULL_SENTINELS, _MAX_DISCRETE_UNIQUES, _kind_from_tree, is_null_sentinel,
)

#: as many codes as the threshold slider names — beyond, a legend is
#: unreadable and the property is painted with the continuous ramp,
#: the card saying so
MAX_CATEGORIES = _MAX_DISCRETE_UNIQUES

#: a discrete property whose codes are (almost) one per cell — a cell
#: index, a layer number on a tiny grid — is an INDEX, not categories:
#: above this many codes, each code has to cover at least this many
#: values on average to be painted as a category
INDEX_MIN_CODES = 12
INDEX_MIN_VALUES_PER_CODE = 4

#: nine saturated colours a reader tells apart at a glance, the way a
#: facies is coloured in a geomodeller; ParaView's own KAAMS opens on
#: white, which reads as "no value" on a grey background
DEFAULT_PRESET = "Brewer Qualitative Set1"

#: the presets whose colours are made to be told apart, not ordered —
#: what the Colormap card offers on a categorical property
QUALITATIVE_PRESETS = (
    "Brewer Qualitative Set1",
    "KAAMS",
    "Brewer Qualitative Set3",
    "Brewer Qualitative Paired",
    "Brewer Qualitative Dark2",
    "Brewer Qualitative Set2",
    "Brewer Qualitative Accent",
    "Brewer Qualitative Pastel1",
    "Brewer Qualitative Pastel2",
    "Spectrum",
)


def kind_of(tree, rep_path, array_name):
    """``"Continuous"`` / ``"Discrete"`` / ``"Categorical"`` for the array
    that colours `rep_path`, as the tree types the property node."""
    return _kind_from_tree(tree, rep_path, array_name)


def _leaves(source_proxy):
    """Every leaf dataset of the source's client-side output."""
    try:
        out = source_proxy.GetClientSideObject().GetOutputDataObject(0)
    except Exception:
        return []
    if out is None:
        return []
    if not out.IsA("vtkCompositeDataSet"):
        return [out]
    return [ds for _flat, ds in assembly_index.leaves(out)]


def held_array(ds, array_name, assoc):
    """``(array, association)`` of `array_name` on the dataset `ds`: where
    `assoc` says, else where it is — a well log's channel holds its values
    on its points whatever a grid's property of the same name does;
    ``(None, assoc)`` when `ds` does not hold it."""
    order = ("POINTS", "CELLS") if assoc == "POINTS" else ("CELLS", "POINTS")
    for which in order:
        getter = getattr(ds, "GetPointData" if which == "POINTS" else "GetCellData", None)
        store = getter() if getter is not None else None
        arr = store.GetArray(array_name) if store is not None else None
        if arr is not None:
            return arr, which
    return None, assoc


def _gaps_are_its_only_zeros(ds, array_name, values):
    """Whether every 0 of a log's channel is a gap: the plugin writes a
    sample without a value as NEGATIVE zero (a NaN would break the tube
    drawn from it, engine/welllog_dispatch) and says how many it wrote."""
    import numpy as np
    from fespp_on_trame.engine import ranges
    if values.dtype.kind != "f" or not ranges.gap_count(ds, array_name):
        return False
    zeros = values == 0
    return bool(zeros.any()) and bool(np.signbit(values[zeros]).all())


def scan_codes(source_proxy, array_name, assoc, datasets=None):
    """``(codes, n_distinct, n_values)``: the distinct finite values of the
    array, sorted, without the integer NullValue sentinels nor a log's gaps;
    `n_distinct` counts them before the cap so the caller can say how many
    there were, `n_values` the finite values they were found in. Read on
    `datasets`, the leaf datasets of the block the array colours; without
    them, on every leaf of the source's output that holds the array.
    ``([], 0, 0)`` when the array cannot be read."""
    if not array_name:
        return [], 0, 0
    leaves = list(datasets or ()) or (_leaves(source_proxy) if source_proxy is not None else [])
    uniques, n_values = set(), 0
    try:
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        from fespp_on_trame.engine import ranges
        for ds in leaves:
            arr, _where = held_array(ds, array_name, assoc)
            if arr is None:
                continue
            values = vtk_to_numpy(arr)
            if values.ndim > 1:
                values = values[:, 0]
            # the one distinct-values rule (engine/ranges)
            found = set(ranges.distinct(arr))
            if _gaps_are_its_only_zeros(ds, array_name, values):
                found.discard(0.0)
            uniques |= found
            values = values[np.isfinite(values)] if values.dtype.kind == "f" \
                else values
            # the NullValue sentinels are inactive cells, not values
            n_values += int(values.size) - int(np.isin(
                values, list(INT_NULL_SENTINELS)).sum())
    except Exception as exc:
        print(f"[fespp] codes of {array_name!r}: not read ({exc!r})", flush=True)
        return [], 0, 0
    codes = sorted(v for v in uniques if not is_null_sentinel(v))
    return codes, len(codes), n_values


def categories_for(tree, rep_path, array_name, source_proxy, assoc,
                   reader=None, datasets=None):
    """``(categories, note)`` for the array colouring `rep_path` (`datasets`:
    the leaf datasets of the block it colours, see `scan_codes`):
    ``[{"code": 3.0, "label": "Sand"}, …]`` sorted by code for a discrete
    or categorical property, the label being the file's name for the
    code when it has one and the code written as an integer otherwise;
    ``(None, "")`` for a continuous property; ``(None, why)`` when the
    property is discrete but cannot be painted by code — too many
    distinct values, or none readable — so the card can say why the
    ramp is continuous."""
    kind = kind_of(tree, rep_path, array_name)
    if kind == "Continuous":
        return None, ""
    codes, n, n_values = scan_codes(source_proxy, array_name, assoc, datasets)
    if not codes:
        return None, (f"{kind.lower()} property, but its values could not"
                      " be read: painted with a continuous ramp")
    if n > MAX_CATEGORIES:
        return None, (f"{n} distinct values, more than the {MAX_CATEGORIES}"
                      " a legend can name: painted with a continuous ramp")
    if n > INDEX_MIN_CODES and n * INDEX_MIN_VALUES_PER_CODE > n_values:
        return None, (f"{n} distinct values over {n_values} cells, an index"
                      " rather than categories: painted with a continuous"
                      " ramp")
    labels = {}
    if kind == "Categorical":
        from fespp_on_trame.engine.utils import categories
        try:
            labels = categories.labels_for(
                tree,
                categories.array_path_for_vtk_name(tree, rep_path, array_name),
                array_name, reader) or {}
        except Exception:
            labels = {}
    return [{"code": c, "label": _label(labels, c)} for c in codes], ""


def _label(labels, code):
    for key in (code, int(code) if float(code).is_integer() else None):
        if key is not None and key in labels:
            return str(labels[key])
    return _code_text(code)


def _code_text(code):
    return str(int(code)) if float(code).is_integer() else str(code)


# ---- the LUT ----------------------------------------------------------------

def _prop(lut, name):
    try:
        return lut.SMProxy.GetProperty(name)
    except Exception:
        return None


def _set_int(lut, name, value):
    prop = _prop(lut, name)
    if prop is None:
        return False
    prop.SetElement(0, int(value))
    return True


def _set_doubles(lut, name, values):
    prop = _prop(lut, name)
    if prop is None:
        return False
    prop.SetNumberOfElements(len(values))
    for i, v in enumerate(values):
        prop.SetElement(i, float(v))
    return True


def _set_strings(lut, name, values):
    prop = _prop(lut, name)
    if prop is None:
        return False
    prop.SetNumberOfElements(len(values))
    for i, v in enumerate(values):
        prop.SetElement(i, str(v))
    return True


def _get_list(lut, name):
    prop = _prop(lut, name)
    if prop is None:
        return []
    return [prop.GetElement(i) for i in range(prop.GetNumberOfElements())]


def is_indexed(lut):
    """Whether the LUT paints by code (the wrapper hides the attribute:
    the proxy property is the one way to read it)."""
    prop = _prop(lut, "IndexedLookup")
    try:
        return bool(int(prop.GetElement(0))) if prop is not None else False
    except Exception:
        return False


def preset_colors(preset):
    """The ``[r, g, b, …]`` of an indexed preset, ``[]`` when this ParaView
    does not know it or it carries no indexed colours."""
    try:
        import json
        from paraview import servermanager
        pr = servermanager.vtkSMTransferFunctionPresets.GetInstance()
        # the presets are read by index: the name lookup only says yes or no
        for i in range(pr.GetNumberOfPresets()):
            if pr.GetPresetName(i) != preset:
                continue
            d = json.loads(pr.GetPresetAsString(i))
            cols = [float(v) for v in d.get("IndexedColors") or []]
            return cols if len(cols) >= 3 else []
    except Exception:
        pass
    return []


def _generated_color(i):
    """A colour a reader can tell from the previous ones, golden-ratio
    hues — for the codes beyond the preset's colours."""
    r, g, b = colorsys.hsv_to_rgb((i * 0.61803398875) % 1.0, 0.65, 0.85)
    return [r, g, b]


def palette(n, preset=DEFAULT_PRESET):
    """``(colors, from_preset)``: n colours flattened ``[r, g, b, …]``, the
    preset's first, generated ones after; `from_preset` says how many the
    preset gave (0 when this ParaView lacks it)."""
    cols = preset_colors(preset)
    from_preset = min(n, len(cols) // 3)
    out = cols[: from_preset * 3]
    for i in range(from_preset, n):
        out.extend(_generated_color(i))
    return out, from_preset


def apply_opacity_curve(lut, curve):
    """The Colormap card's opacity on a table painted by code: VTK ignores
    the opacity function of an indexed table and reads one opacity per
    annotated code (`IndexedOpacities`) — each code takes the curve's value
    at that code (`curve`: [[x, opacity], …], linear between its nodes).
    Returns whether a code is translucent; None when `lut` is not indexed."""
    if lut is None or not is_indexed(lut):
        return None
    pts = sorted((float(x), float(y)) for x, y in (curve or ()))

    def at(v):
        if not pts:
            return 1.0
        if v <= pts[0][0]:
            return pts[0][1]
        if v >= pts[-1][0]:
            return pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= v <= x1:
                return y0 if x1 == x0 else y0 + (y1 - y0) * (v - x0) / (x1 - x0)
        return 1.0

    ops = [max(0.0, min(1.0, at(code))) for code in annotations_of(lut)]
    _set_doubles(lut, "IndexedOpacities", ops)
    try:
        lut.SMProxy.UpdateVTKObjects()
    except Exception as exc:
        print(f"[fespp] categorical opacity: table not updated ({exc})", flush=True)
    return any(o < 0.999 for o in ops)


def annotations_of(lut):
    """``{code: label}`` as the LUT annotates it (``{}`` when none)."""
    ann = _get_list(lut, "Annotations")
    out = {}
    for i in range(0, len(ann) - 1, 2):
        try:
            out[float(ann[i])] = str(ann[i + 1])
        except (TypeError, ValueError):
            continue
    return out


# what names the stepped twin of an indexed table, after its array
STEPS = " (steps)"


def steps_from(twin, lut):
    """`twin` painted as `lut` paints by code, without the indexed lookup:
    each code's colour held from half-way to the code before to half-way to
    the next. What the composite's per-block road can apply, where it cannot
    apply an indexed table. True when written."""
    order = list(annotations_of(lut))
    colors = _get_list(lut, "IndexedColors")
    if not order or len(colors) < 3 * len(order):
        return False
    rgb = {code: [float(v) for v in colors[3 * i: 3 * i + 3]] for i, code in enumerate(order)}
    codes = sorted(rgb)
    points = []
    for k, code in enumerate(codes):
        lo = code - 0.5 if k == 0 else (codes[k - 1] + code) / 2.0
        hi = code + 0.5 if k == len(codes) - 1 else (code + codes[k + 1]) / 2.0
        points += [lo, *rgb[code], hi - 1e-9 * max(1.0, abs(hi)), *rgb[code]]
    _set_int(twin, "IndexedLookup", 0)
    _set_strings(twin, "Annotations", [])
    _set_doubles(twin, "RGBPoints", points)
    for name in ("NanColor", "NanOpacity"):
        held = _get_list(lut, name)
        if held:
            _set_doubles(twin, name, held)
    for name, value in (("ColorSpace", "RGB"), ("AutomaticRescaleRangeMode", "Never")):
        try:
            setattr(twin, name, value)
        except Exception as exc:
            print(f"[fespp] stepped table: {name} not set ({exc!r})", flush=True)
    twin.SMProxy.UpdateVTKObjects()
    return True


def apply(lut, categories, preset=DEFAULT_PRESET):
    """Paint `lut` by code: ``IndexedLookup`` on, one annotation per
    category, one colour each. Idempotent on the codes: a LUT already
    indexed on the same codes keeps its colours (the reader's edits
    survive every reconcile); new codes get the preset's colours, then
    generated ones. Returns the note the card shows when the preset ran
    short, ``""`` otherwise."""
    if lut is None or not categories:
        return ""
    codes = [float(c["code"]) for c in categories]
    wanted = [_code_text(c) for c in codes]
    current = annotations_of(lut)
    current_colors = _get_list(lut, "IndexedColors")
    same_codes = (is_indexed(lut) and list(current.keys()) == codes
                  and len(current_colors) >= 3 * len(codes))
    # the reader's opacities survive a reconcile as their colours do
    current_opacities = _get_list(lut, "IndexedOpacities")
    if same_codes:
        colors = current_colors[: 3 * len(codes)]
        short = 0
    else:
        colors, from_preset = palette(len(codes), preset)
        short = len(codes) - from_preset
    opacities = ([float(o) for o in current_opacities[: len(codes)]]
                 if same_codes and len(current_opacities) >= len(codes)
                 else [1.0] * len(codes))
    flat = []
    for c, text in zip(codes, wanted):
        flat.extend([text, next(x["label"] for x in categories
                                if float(x["code"]) == c)])
    _set_int(lut, "IndexedLookup", 1)
    _set_strings(lut, "Annotations", flat)
    _set_doubles(lut, "IndexedColors", colors)
    _set_doubles(lut, "IndexedOpacities", opacities)
    try:
        lut.SMProxy.UpdateVTKObjects()
    except Exception:
        pass
    if short and preset:
        return (f"{len(codes)} codes for the {len(codes) - short} colors of"
                f" {preset}: the other colors are generated")
    return ""


def file_coloured(lut):
    """Whether the codes of an indexed `lut` were coloured by the FILE (a
    RESQML 2.2 discrete colour map, which the plugin writes with each
    code as its own annotation) rather than named by a string lookup
    (names beside the codes)."""
    ann = annotations_of(lut)
    return bool(ann) and all(str(label) == _code_text(code) or str(label) == "null value"
                             for code, label in ann.items())


def tame(lut):
    """A table painted by code with more codes than a legend can name.

    The FESPP plugin puts a categorical property's WHOLE string lookup on
    its table, indexed: 5 373 dates for the `datetime` of decatur_events
    (ADME, 27/10), a colour bar of 5 373 labels laid out at every frame,
    and the session stuck in the render without an error. Beyond
    MAX_CATEGORIES the codes are painted with the continuous ramp and the
    names leave the table — the file's lookup still names them
    (`utils.categories.labels_for`) — UNLESS the file coloured the codes
    itself (`file_coloured`): its colours are the author's and stay; only
    the bar's labels go (`bars._size_for_codes`).

    Indexed or not: a view's table is a COPY of the plugin's, which keeps
    the annotations but not always the indexed mode — and a ramp's bar
    lays out every annotation all the same (the PO's session on 8082,
    27/10 evening: "c'est encore en catégorie", the render held again).

    Returns "ramp" (tamed), "file colours" (kept, labels off the bar) or
    "" (nothing to tame)."""
    if lut is None or len(annotations_of(lut)) <= MAX_CATEGORIES:
        return ""
    if file_coloured(lut):
        # the file's colours are by code: the table paints by code
        if not is_indexed(lut):
            _set_int(lut, "IndexedLookup", 1)
            try:
                lut.SMProxy.UpdateVTKObjects()
            except Exception as exc:
                print("[fespp] categorical table, file colours:", exc, flush=True)
        return "file colours"
    _set_int(lut, "IndexedLookup", 0)
    _set_strings(lut, "Annotations", [])
    try:
        lut.SMProxy.UpdateVTKObjects()
    except Exception as exc:
        print("[fespp] categorical table tamed, update:", exc, flush=True)
    return "ramp"


def recolor(lut, categories, preset):
    """Give the categories the colours of `preset` afresh (the reader
    chose it), keeping the codes and their names. Returns the note."""
    if lut is None or not categories:
        return ""
    colors, from_preset = palette(len(categories), preset)
    _set_int(lut, "IndexedLookup", 1)
    _set_doubles(lut, "IndexedColors", colors)
    try:
        lut.SMProxy.UpdateVTKObjects()
    except Exception:
        pass
    if from_preset == 0:
        return f"{preset} is not a preset of this ParaView: colors generated"
    if from_preset < len(categories):
        return (f"{len(categories)} codes for the {from_preset} colors of"
                f" {preset}: the other colors are generated")
    return ""


def code_colours(lut):
    """[r, g, b, …]: the colours of a table painted by code, in the order of
    its annotations."""
    return [float(v) for v in _get_list(lut, "IndexedColors")]


def set_code_colours(lut, colours):
    """Every code's colour at once, [r, g, b, …] in the order of the
    table's annotations."""
    return _set_doubles(lut, "IndexedColors", colours)


def set_indexed(lut, on):
    """The table painted by code (`on`) or by value; its annotations stay."""
    return _set_int(lut, "IndexedLookup", 1 if on else 0)


def set_code_color(lut, code, hex_color):
    """One code's colour, from the card's picker."""
    if lut is None:
        return False
    codes = list(annotations_of(lut).keys())
    try:
        idx = codes.index(float(code))
    except ValueError:
        return False
    colors = _get_list(lut, "IndexedColors")
    if len(colors) < 3 * len(codes):
        colors = colors + [0.5] * (3 * len(codes) - len(colors))
    colors[3 * idx: 3 * idx + 3] = hex_to_rgb(hex_color)
    _set_doubles(lut, "IndexedColors", colors)
    try:
        lut.SMProxy.UpdateVTKObjects()
    except Exception:
        pass
    return True


def set_code_opacity(lut, code, alpha):
    """One code's opacity from the card (`code` None: every code), written
    to `IndexedOpacities` — the one opacity an indexed table reads — with
    the opacity mapping on while a code is translucent. Returns whether a
    code is translucent; None when `lut` is not indexed or does not paint
    `code`."""
    if lut is None or not is_indexed(lut):
        return None
    codes = list(annotations_of(lut).keys())
    ops = [float(o) for o in _get_list(lut, "IndexedOpacities")]
    ops = (ops + [1.0] * len(codes))[: len(codes)]
    a = max(0.0, min(1.0, float(alpha)))
    if code is None:
        ops = [a] * len(codes)
    elif float(code) in codes:
        ops[codes.index(float(code))] = a
    else:
        return None
    translucent = any(o < 0.999 for o in ops)
    _set_doubles(lut, "IndexedOpacities", ops)
    _set_int(lut, "EnableOpacityMapping", 1 if translucent else 0)
    try:
        lut.SMProxy.UpdateVTKObjects()
    except Exception as exc:
        print(f"[fespp] categorical opacity: table not updated ({exc})", flush=True)
    return translucent


def hidden_codes(lut):
    """The codes the reader put at opacity 0, ``()`` when none or when
    `lut` is not indexed: their cells are taken out of the grid
    (engine/nan_mask), not left as a see-through hole."""
    if lut is None or not is_indexed(lut):
        return ()
    ops = _get_list(lut, "IndexedOpacities")
    return tuple(code for i, code in enumerate(annotations_of(lut))
                 if i < len(ops) and float(ops[i]) <= 1e-6)


def read(lut):
    """``[{"code", "label", "color": "#rrggbb", "opacity"}, …]`` as the LUT
    paints them, for the Colormap card; ``[]`` when the LUT is not
    indexed."""
    if lut is None or not is_indexed(lut):
        return []
    ann = annotations_of(lut)
    colors = _get_list(lut, "IndexedColors")
    ops = _get_list(lut, "IndexedOpacities")
    out = []
    for i, (code, label) in enumerate(ann.items()):
        rgb = colors[3 * i: 3 * i + 3] if len(colors) >= 3 * i + 3 else [0.5] * 3
        op = float(ops[i]) if i < len(ops) else 1.0
        out.append({"code": code, "label": label, "color": rgb_to_hex(rgb),
                    "opacity": op})
    return out


def rgb_to_hex(rgb):
    r, g, b = (max(0, min(255, int(round(float(v) * 255)))) for v in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(hex_color):
    h = re.sub(r"[^0-9a-fA-F]", "", str(hex_color or ""))
    if len(h) < 6:
        return [0.5, 0.5, 0.5]
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


# ---- the same colours in the graphs ------------------------------------------

def colors_by_code(codes, array_name, scenes=None):
    """``{code: "#rrggbb"}``: the colour each code is painted with in 3D,
    for a histogram bar or a cross-plot trace to wear the same — read off
    the first view whose LUT is indexed on `array_name` (the reader's
    edits included), else the default palette in code order, which is
    what a view would paint. `scenes` are the views' PdcScenes.

    The realizations of one property share one table in a view: a view
    painting realization 3 answers for a chart that read realization 0."""
    from fespp_on_trame.engine.utils.naming import strip_realization_suffix
    codes = [float(c) for c in codes]
    base = strip_realization_suffix(array_name or "")
    for scene in (scenes or []):
        try:
            entry = next((e for e in scene.block_state.values()
                          if e.categories
                          and strip_realization_suffix(e.color_array or "") == base), None)
            if entry is None:
                continue
            painted = {c["code"]: c["color"] for c in read(scene.scoped_lut(entry.color_array))}
        except Exception:
            continue
        if painted:
            fallback = _default_colors(codes)
            return {c: painted.get(c, fallback[c]) for c in codes}
    return _default_colors(codes)


def _default_colors(codes):
    flat, _n = palette(len(codes))
    return {c: rgb_to_hex(flat[3 * i: 3 * i + 3]) for i, c in enumerate(codes)}


def view_scenes():
    """The PdcScenes of the open views, ``[]`` outside a session."""
    try:
        from trame.app import get_server
        return list((getattr(get_server().context, "blockscope_scenes", None)
                     or {}).values())
    except Exception:
        return []
