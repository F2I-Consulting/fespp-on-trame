"""How the wells are drawn in a 3D view (the manager and the PO, 19-20/11).

Every log — continuous, discrete, categorical — is drawn one of three ways,
chosen in the right-click menu of its row in a tree or of the log itself in
a 3D view ("Show as filled graph", "Show as curve", "Show as tube"; one
choice per log for the session, ``ui_log_modes``, every view follows it):
a FILLED GRAPH standing on its hole by default (built by the plugin's
filter, see below: the trajectory is its zero, a positive value stands off
it on one side, a negative one on the other, the fill between the hole and
the curve in the value's colour, a log of codes coloured interval by
interval), its curve in
the colour the 2D log view gives that log (its chip on the log's row in the
trees, ``ui_tree_extra_chips``); a CURVE alone, in that colour; a TUBE. Where a log holds no value its hole is
drawn in the table's NaN colour. Every log wears the same diverging map
(engine/diverging_table): blue negative, white zero, red positive, over the
log's TRUE range — a log of positive values is drawn in reds only, its bar
from its least value to its largest; a log of codes is painted by code, each
code the colour of its value, its bar listing its codes. The Colormap card
changes it from then on, and a table a session wrote back keeps its colours.
The logs of one property kind a view shows are drawn to ONE scale, as the
tracks of the 2D log view are: the largest value in size among them stands
the graph's width off the hole, and their tables share their range. A log
drawn as a curve has no colour bar: its colour is its name's.

A log frame shows one log at a time, as anywhere else in the app.

The tubes are FESPP's. The reader makes a log's tube round in the data's
space, and a view's scale then stretches it that many times upwards; the
plugin's filter `EnergisticsWellSymbols` builds it again for a vertical
exaggeration, and the MARKERS too — their disks and spheres the same size
and as round whatever the exaggeration, ten times as large as the reader
makes them by default, larger or smaller on demand ("Larger markers",
"Smaller markers" in the right-click menus; one scale for the session,
``ui_marker_scale``), each painted by its NAME: one colour per marker name,
the same on every well — the 2D log view's when it shows that marker (the
reader's cell array ``MarkerNameId``, one id per name). Each view has ONE
such filter,
chained on its clone (engine/view_resources), told the view's exaggeration
and what it draws, and ONE composite representation of it, dressed block by
block as the scene's composite would dress them: the same selectors, the
view's table of each property. A change of exaggeration then costs those
symbols and nothing of the rest of the scene. With a plugin that has no such
filter, tubes and markers stay in the composite, as the reader made them.

The GRAPHS are FESPP's too: the same filter, told the logs drawn as graphs,
those of codes, the scale of each and the width, builds each one's strip,
curve and stretches without a value under the log's node, laid on the
trajectory's stations between two samples read far apart (by measured
depth: the graph follows the hole, not a chord) — drawing only: the filter
says on each point the sample it stands for (``LogSample``, -1 for a
station), and the cursor reads the log's own samples. Each log's graph is
drawn by a representation of its own (an ExtractBlock of the filter: the
representation's table paints its strip), flat: the colour is the value,
whatever the light.

What is drawn here leaves the scene's composite (`scene.isolated`, as a grid
drawn by its isolate does: its table and its bar stay). The cursor meets a
filter's block as the block it stands for (`ctx.block_stand_ins`) and reads
the log's value on a graph (`ctx.cursor_probes`, the nearest sample); a
click on either selects the block (`ctx.pick_twins`: the filter keeps the
reader's blocks at their places, cell for cell; a graph stands for its log).

A filled graph wears the view's table of its property, so the Colormap card
and the bar act on it as on the tube. What is drawn here
is settled before each frame the app asks for (the scheduler's flush): an
eye, a Z exaggeration, a domain switch, a tube asked for are all followed
there.

A graph's width is the scene's, one for the session (``ui_log_width``, as
drawn), the first one taken from the holes the first graphs stand on, wider
or narrower on demand ("Larger graphs", "Smaller graphs" in the right-click
menus). It stands in the well's curtain, the vertical surface between the
hole and its trace at Z = 0, fixed in the scene; the graph of a well plumb
all along faces the screen instead, as a wellhead's pictogram and name do:
before every render at rest of a view whose camera turned, the filter of the
view's graphs (`fesppWellGraphs_<view>`, apart from the one of its tubes and
markers, which a turn leaves as they are) is told the screen's right again
(the view proxy's StartEvent comes before its pipeline update, so the frame
drawn shows it). The frames of a drag keep the graphs as laid
(`frames.in_drag`, a button down, at any resolution), and the frame at release
lays them; so do the frames of a camera flight ("Center / Zoom the 3D view
on", `camera.FLIGHTS`), laid at the landing.

The flag at the head of each well (engine/wellhead) shows a pictogram
instead of the letter A: a glyph of the font `assets/wellhead.ttf` (U+E000 a
pumpjack, U+E001 a platform at sea), fixed on screen as the letter was. A
RESQML document does not say whether a well is on land or at sea: the
platform is drawn (the manager's choice, 19/11). It faces the screen and
gets smaller by steps as the view draws its well smaller (PICTOGRAM_STEPS),
checked with the camera as the sections are.

A marker's NAME is written beside it on demand ("Show name" / "Hide name" on a
marker, "Show names" / "Hide names" on a marker set, in the right-click menus
of the trees and of the 3D view; ``ui_marker_labels``, the markers named, for
the session), facing the screen, in the marker's colour.
"""
import math
import os

import numpy as np
from paraview import simple as pvsimple
from vtkmodules.util.numpy_support import vtk_to_numpy

from fespp_on_trame.app.views.camera import FLIGHTS
from fespp_on_trame.app.views.frames import drag_ratio, in_drag
from fespp_on_trame.engine import categorical_palette, diverging_table, log_track, view_resources, wellhead
from fespp_on_trame.engine import ranges as _ranges
from fespp_on_trame.engine.blockscope.pdc_scene import SENTINEL_NO_BLOCKS
from fespp_on_trame.engine.node_kinds import PROPERTY_KINDS
from fespp_on_trame.engine.state_defaults import z_scale_of
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.engine.utils.color_palette import DIVERGING_PRESET, color_for_index

PROBE = "log track"
WHITE = (1.0, 1.0, 1.0)
FILTER = "EnergisticsWellSymbols"
#: the font of the wellhead's pictograms, its two glyphs and the size they are drawn at
WELLHEAD_FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "assets", "wellhead.ttf")
PUMPJACK, PLATFORM = "", ""
PICTOGRAM_SIZE = 20
#: the pictogram's sizes as the view draws its well smaller: (the well's size on screen in pixels — the diagonal
#: of its trajectory's box — from which a size holds, that size), largest first
PICTOGRAM_STEPS = ((250.0, PICTOGRAM_SIZE), (80.0, 13), (0.0, 8))
#: how each log is drawn, for the session: {its row's path: TUBE | CURVE}, a filled graph when absent
MODES = "ui_log_modes"
GRAPH, CURVE, TUBE = "graph", "curve", "tube"
#: the entries a feature adds to the trees' right-click menu, and the colour chips to their rows
#: (app/views/widgets/data_tree)
TREE_EXTRAS, TREE_CHIPS = "ui_tree_extra_actions", "ui_tree_extra_chips"
AS = {GRAPH: "log-as-graph", CURVE: "log-as-curve", TUBE: "log-as-tube"}
#: how many times as large as the reader makes them the markers are drawn, for the session; its first value; how
#: much larger or smaller each step makes them, and how far
MARKER_SCALE, MARKER_SCALE_FIRST, MARKER_STEP, MARKER_RANGE = "ui_marker_scale", 2.5, 2.0, (0.5, 500.0)
LARGER, SMALLER = "markers-larger", "markers-smaller"
MARKER_KINDS = ("MarkerFrame", "Marker", "WellboreMarker")
#: what the reader writes on a marker: the id of its name (cell array, one per name whatever the well) and the
#: table of the names by id (field array)
MARKER_ID, MARKER_NAMES = "MarkerNameId", "MarkerNames"
#: the parts of a log's graph the plugin's filter makes, under the log's node; the field array of a graph facing the
#: screen; the point array saying the sample each point stands for (engine/log_track)
GRAPH_PARTS, FACES_SCREEN, LOG_SAMPLE = ("strip", "curve", "gaps", "rails", "scale"), "LogFacesScreen", log_track.LOG_SAMPLE
#: the scale of a graph (the filter's "scale" block): the value each of its points stands for; its labels' font size
#: and how far they stand from their point on screen
SCALE_VALUE, SCALE_FONT, SCALE_BESIDE = "ScaleValue", 13, (6, 2)
#: a sample held on a graph or a tube (a row of the Values view, a click in the log view): the 3D selection's
#: colour; the sample under the log view's pointer: blue, as its row in the Values view (geometry: engine/log_lit)
LIT_COLOUR = (1.0, 0.0, 1.0)
CURSOR_COLOUR = (0.082, 0.396, 0.753)
#: the rails' colour: the track's edges, as the 2D log view's tracks have
RAIL_COLOUR = (0.75, 0.75, 0.75)
#: the logs coloured interval by interval: their codes are no measure between two samples
CODE_KINDS = ("DiscreteProperty", "CategoricalProperty")
#: the graphs' width as drawn, for the session, and how much wider or narrower each step makes them
LOG_WIDTH, WIDTH_STEP = "ui_log_width", 1.5
GRAPHS_LARGER, GRAPHS_SMALLER = "graphs-larger", "graphs-smaller"
#: the markers whose name is written beside them, for the session (their rows' paths)
MARKER_LABELS = "ui_marker_labels"
#: a marker's name as written at rest: its font size, and how far it stands from the marker on screen
MARKER_NAME_FONT, MARKER_NAME_BESIDE = 18, (12, 4)
NAME_ON, NAME_OFF, NAMES_ON, NAMES_OFF = "marker-name-on", "marker-name-off", "marker-names-on", "marker-names-off"
LABELS = {AS[GRAPH]: "Show as filled graph", AS[CURVE]: "Show as curve", AS[TUBE]: "Show as tube",
          LARGER: "Larger markers", SMALLER: "Smaller markers", GRAPHS_LARGER: "Larger graphs", GRAPHS_SMALLER: "Smaller graphs",
          NAME_ON: "Show name", NAME_OFF: "Hide name", NAMES_ON: "Show names", NAMES_OFF: "Hide names"}


def register(core):
    ctx, state, scheduler, lifecycle, tree = core.ctx, core.state, core.scheduler, core.lifecycle, core.tree
    wellhead.PICTOGRAM = (WELLHEAD_FONT, PLATFORM, PICTOGRAM_SIZE)
    # vid -> the view's filter and its one representation: {"flt", "rep", "sels": the blocks it draws, "zs": the
    # exaggeration it was told, "worn": what its representation was last dressed for, "key", "blocks": its output
    # as last read}; None with a plugin that has no such filter
    pieces = {}
    # vid -> {selector: {"key": its data's stamp, "array", "title", "mode", "steps", "rings": the reader's samples
    # (what the cursor reads), "void"}} of the logs the view's filter draws as graphs
    held = {}
    off = {}        # vid -> the blocks this feature took off the scene's composite
    # (dataset's address, its mtime, array) -> its rings, None when the block is no log's tube
    read = {}
    # (view, array) -> what this feature last wrote in the table: {"points", "codes", "colours", "range"}; a table
    # that still holds it is the feature's to paint again
    painted = {}
    bars_off = {}   # vid -> the arrays whose bar this feature switched off (logs drawn as curves)
    # vid -> [(the object observed, its observer's tag, the callable VTK keeps no reference to)]: the view proxy's
    # renders, its size's changes
    watch = {}
    turned = {}     # vid -> the camera (_screen) its graphs were last laid for
    labels = {}     # vid -> {marker path: (text source, its representation, the name's position, unscaled)}
    shown_as = {}   # vid -> {selector: TUBE | CURVE | GRAPH}: how the view last drew each log it shows
    # vid -> the arrays whose stretches without a value a graph draws, in the NaN colour; hidden by default: the
    # hole there is the trajectory's own ("Hide NaN cells" in the Colormap card, unticked)
    nan_shown = {}
    said_arrays = {}    # vid -> the arrays of the logs it draws, as the Colormap card was last told
    scale_labels = {}   # vid -> {(selector, point): (text source, its representation, its position, unscaled)}
    # (vid, "lit" | "cursor") -> (the samples' source, its representation, {"lines", "rings"} drawn): the held
    # samples and the one under the log view's pointer, apart, each in its colour
    lit_marks = {}
    _NO_GRAPHS = []     # said once: a plugin whose filter draws no graph

    def _pv_view(vid):
        mv = core.mv()
        try:
            return mv.get_pv_view(vid) if mv is not None else None
        except Exception as exc:
            print(f"[fespp] log tracks ({vid}): no render view ({exc})", flush=True)
            return None

    def _modes():
        held_modes = getattr(state, MODES, None)
        return dict(held_modes) if isinstance(held_modes, dict) else {}

    def _curve_colours():
        """{log title: "#rrggbb"}: the colour the 2D log view gives each
        log's curve — read on its panel when one is open, else given by its
        rule (engine/welllog_dispatch: the colour of the log's rank among the
        logs ticked, in the tree's order) —, so that a 3D view draws a log's
        curve as the 2D view does."""
        out = {}
        mv = core.mv()
        for pid in (mv.panel_ids_of_kind("welllog") if mv is not None else ()):
            for well in (getattr(state, f"welllog_data__{pid}", None) or {}).get("wells") or ():
                for track in well.get("tracks") or ():
                    for curve in track.get("curves") or ():
                        if curve.get("name") and curve.get("color"):
                            out.setdefault(curve["name"], str(curve["color"])[:7])
        ticked = [p for p in (getattr(state, "ui_loaded_array_paths", None) or ()) if _is_channel(p)]
        rank = len(out)
        for p in sorted(ticked, key=lambda q: tree.find_node_id(q) or 0):
            title = tree.find_title(tree.find_node_id(p)) or ""
            if title and title not in out:
                out[title] = color_for_index(rank)[:7]
                rank += 1
        return out

    def _rgb(colour):
        return [int(colour[k:k + 2], 16) / 255.0 for k in (1, 3, 5)]

    def _log_title(sel):
        nid = tree.find_node_id(sel)
        return (tree.find_title(nid) if nid is not None else "") or ""

    def _marker_scale():
        held = getattr(state, MARKER_SCALE, None)
        return float(held) if isinstance(held, (int, float)) and held > 0 else MARKER_SCALE_FIRST

    def _is_channel(sel):
        """A log channel: a property leaf under a wellbore frame."""
        nid = tree.find_node_id(sel) if sel else None
        rid = tree.find_representation_node(nid) if nid is not None else None
        return rid is not None and rid != nid and (tree.find_type(rid) or "") == "Frame"

    def _title(sel):
        nid = tree.find_node_id(sel)
        well = tree.find_parent_node_id_with_type(nid, "Wellbore") if nid is not None else None
        name = (tree.find_title(nid) if nid is not None else "") or sel.rsplit("/", 1)[-1]
        return (f"wellbore {tree.find_title(well)}  ·  " if well is not None else "") + name

    def _rings(ds, array):
        key = (ds.GetAddressAsString("vtkDataObject"), ds.GetMTime(), array)
        if key not in read:
            read[key] = log_track.rings(ds, array)
        return key, read[key]

    def _shown_where(scene, kinds=None):
        """{selector: its entry} of the blocks the scene shows where they are
        — one of the other domain, drawn converted, stays the composite's,
        which moves it — that are log channels (`kinds` None) or rows of
        those kinds."""
        out = {}
        for sel in scene.shown_selectors():
            entry = scene.block_state.get(sel)
            if entry is None:
                continue
            if kinds is None:
                if not _is_channel(sel):
                    continue
            else:
                nid = tree.find_node_id(sel)
                if nid is None or (tree.find_type(nid) or "") not in kinds:
                    continue
            if scene.vdomain and scene.domain_of is not None and scene.domain_of(sel) not in (None, scene.vdomain):
                continue
            out[sel] = entry
        return out

    # ------------------------------------------------------------------
    # The tubes and the markers: the plugin's filter, one per view

    def _piece(vid, pvv):
        """The view's filter and its representation, made on first use; None
        with a plugin that has no such filter."""
        if vid in pieces:
            return pieces[vid]
        from fespp_on_trame.engine.sources import leaf_rep
        from fespp_on_trame.engine.sources.representation import _create_plugin_filter_proxy
        reg = view_resources.current()
        res = reg.get(vid) if reg is not None else None
        if res is None or res.clone is None:
            return None
        piece = None
        try:
            flt = _create_plugin_filter_proxy(proxy_class=FILTER, registration_name=f"fesppWellSymbols_{vid}",
                                              inputs={"Input": res.clone})
            if flt is None:
                print(f"[fespp] log tracks ({vid}): the plugin has no {FILTER} filter, tubes and markers stay the"
                      f" reader's", flush=True)
            else:
                flt.PassOtherBlocks = 0
                flt.Selectors = [SENTINEL_NO_BLOCKS]
                rep = leaf_rep.show_composite(flt, pvv)
                if rep is None:
                    pvsimple.Delete(flt)
                else:
                    piece = {"flt": flt, "rep": rep, "sels": (), "zs": None, "scale": None, "worn": None, "key": None,
                             "blocks": {}}
        except Exception as exc:
            print(f"[fespp] log tracks ({vid}): no {FILTER} filter ({exc!r})", flush=True)
        pieces[vid] = piece
        return piece

    def _graph_filter(vid, piece):
        """The filter the view's graphs are made by: the plugin's well symbols
        filter again, on the same input, drawing the graphs alone and shown
        by no representation of its own (each graph's extract draws it). Apart
        from the one of the tubes and the markers: a camera turned lays the
        graphs facing the screen again, which re-made every block of a shared
        filter and drew them all again (some 2 s with every log of Drogon).
        None when it cannot be made."""
        if piece.get("gflt") is not None:
            return piece["gflt"]
        from fespp_on_trame.engine.sources.representation import _create_plugin_filter_proxy
        reg = view_resources.current()
        res = reg.get(vid) if reg is not None else None
        if res is None or res.clone is None:
            return None
        try:
            gflt = _create_plugin_filter_proxy(proxy_class=FILTER, registration_name=f"fesppWellGraphs_{vid}",
                                               inputs={"Input": res.clone})
        except Exception as exc:
            print(f"[fespp] log tracks ({vid}): no filter for the graphs ({exc!r})", flush=True)
            return None
        if gflt is not None:
            gflt.PassOtherBlocks = 0
            gflt.Selectors = [SENTINEL_NO_BLOCKS]
            piece["gflt"] = gflt
        return gflt

    def _marker_colours(names):
        """{marker name: "#rrggbb"}: the colour the 2D log view gives each
        marker it shows, else the colour of the name's rank among `names`
        (in the order of their ids) after those."""
        out = {}
        mv = core.mv()
        for pid in (mv.panel_ids_of_kind("welllog") if mv is not None else ()):
            for mark in (getattr(state, f"welllog_data__{pid}", None) or {}).get("markers") or ():
                if mark.get("name") and mark.get("color"):
                    out.setdefault(mark["name"], str(mark["color"])[:7])
        rank = len(out)
        for name in names:
            if name not in out:
                out[name] = color_for_index(rank)[:7]
                rank += 1
        return out

    def _marker_table(scene, marks):
        """The view's table painting the markers of `marks` by name, each
        name its colour (`_marker_colours`); (table, what it holds, {marker
        row: its colour}) — (None, (), {}) when they carry no name."""
        index = getattr(ctx, "assembly_index", None)
        names, code_of = {}, {}
        sets = (lambda p: index.datasets(p)) if index is not None else (lambda _p: ())
        for sel in marks:
            # marker by marker, each row its colour; a set whose markers are no rows, as one
            blocks = ([(row, ds) for row in _marker_rows(sel) for ds, _flat in sets(row)]
                      or [(None, ds) for ds, _flat in sets(sel)])
            for row, ds in blocks:
                ids = ds.GetCellData().GetArray(MARKER_ID) if ds.GetCellData() is not None else None
                table = ds.GetFieldData().GetAbstractArray(MARKER_NAMES) if ds.GetFieldData() is not None else None
                if ids is None or table is None or not ids.GetNumberOfTuples():
                    continue
                code = int(ids.GetTuple1(0))
                if 0 <= code < table.GetNumberOfValues():
                    names[code] = str(table.GetValue(code))
                    if row is not None:
                        code_of[row] = code
        if not names:
            return None, (), {}
        codes = sorted(names)
        colours = _marker_colours([names[c] for c in codes])
        chips = {row: colours[names[c]] for row, c in code_of.items()}
        lut = scene.scoped_lut(MARKER_ID)
        if lut is None:
            return None, (), {}
        categorical_palette.apply(lut, [{"code": c, "label": names[c]} for c in codes])
        wanted = [v for c in codes for v in _rgb(colours[names[c]])]
        if categorical_palette.code_colours(lut)[:len(wanted)] != wanted:
            categorical_palette.set_code_colours(lut, wanted)
            lut.SMProxy.UpdateVTKObjects()
        return lut, tuple((c, names[c], colours[names[c]]) for c in codes), chips

    def _dress(scene, piece, drawn, zs):
        """The representation of the view's filter wears, block by block,
        what the scene's composite would: its blocks, each painted by its
        property with the view's table of it — a property of codes by the
        representation's own road, which alone applies an indexed table, a
        second one by its table of steps —, the composite's style, the
        view's scale."""
        rep = piece["rep"]
        sels = sorted(drawn)
        main = scene.main_rep if scene is not None else None
        held_style = main.SMProxy.GetProperty("Representation") if main is not None else None
        style = (held_style.GetElement(0) if held_style is not None and held_style.GetNumberOfElements() else "") or "Surface"
        marks = [s for s in sels if (tree.find_type(tree.find_node_id(s)) or "") in MARKER_KINDS]
        marker_lut, by_name, piece["marker_chips"] = _marker_table(scene, marks) if marks else (None, (), {})
        worn = (zs, style, by_name, tuple((s, drawn[s].color_array, drawn[s].assoc, repr(drawn[s].categories),
                                           drawn[s].solid_rgb, drawn[s].drawn_opacity()) for s in sels))
        if worn == piece["worn"]:
            return
        piece["worn"] = worn
        if rep.GetProperty("Assembly") is not None:
            rep.Assembly = "Assembly"
        rep.BlockSelectors = sels or [SENTINEL_NO_BLOCKS]
        rep.SMProxy.UpdateProperty("BlockSelectors", 1)
        named = set(marks) if marker_lut is not None else set()
        coloured = [(s, drawn[s]) for s in sels if drawn[s].color_array and s not in named]
        anchor = next((e for _s, e in coloured if e.categories), coloured[0][1] if coloured else None)
        # the markers' table is painted by code: it anchors the representation unless a log of codes does
        markers_anchor = bool(named) and (anchor is None or not anchor.categories)
        triplets, tables = [], []
        for sel, entry in coloured:
            lut = scene.scoped_lut(entry.color_array)
            if entry.categories and (markers_anchor or (entry.assoc, entry.color_array) != (anchor.assoc,
                                                                                              anchor.color_array)):
                lut = scene.stepped_table(entry.color_array, lut)
            triplets += [sel, "1" if entry.assoc == "CELLS" else "0", entry.color_array]
            tables.append(lut)
        for sel in sorted(named):
            triplets += [sel, "1", MARKER_ID]
            tables.append(marker_lut if markers_anchor else scene.stepped_table(MARKER_ID, marker_lut))
        if rep.GetProperty("BlockColorArrayNames") is not None:
            rep.BlockColorArrayNames = triplets
            rep.SMProxy.UpdateProperty("BlockColorArrayNames", 1)
        block_tables = rep.SMProxy.GetProperty("BlockLookupTables")
        if block_tables is not None:
            block_tables.RemoveAllProxies()
            for lut in tables:
                block_tables.AddProxy(lut.SMProxy)
            rep.SMProxy.UpdateProperty("BlockLookupTables", 1)
        if markers_anchor:
            rep.ColorArrayName = ["CELLS", MARKER_ID]
            rep.LookupTable = marker_lut
        elif coloured:
            rep.ColorArrayName = [anchor.assoc, anchor.color_array]
            rep.LookupTable = scene.scoped_lut(anchor.color_array)
        else:
            rep.ColorArrayName = ["POINTS", ""]
        if rep.GetProperty("BlockColors") is not None:
            quads = []
            for sel in sels:
                if drawn[sel].solid_rgb and not drawn[sel].color_array and sel not in named:
                    quads += [sel, *(str(c) for c in drawn[sel].solid_rgb)]
            rep.BlockColors = quads
        if rep.GetProperty("BlockOpacities") is not None:
            pairs = []
            for sel in sels:
                opacity = drawn[sel].drawn_opacity()
                if opacity is not None and opacity < 0.999:
                    pairs += [sel, str(float(opacity))]
            rep.BlockOpacities = pairs
        rep.Representation = style
        rep.Scale = [1.0, 1.0, zs]
        rep.Visibility = 1 if sels else 0
        rep.SMProxy.UpdateVTKObjects()

    def _settle_symbols(vid, scene, pvv, drawn, zs):
        """The view's filter is told the blocks it draws — the logs shown as
        tubes, the markers — and the view's exaggeration; the blocks it
        draws, none without a filter."""
        piece = _piece(vid, pvv) if drawn else pieces.get(vid)
        if piece is None:
            return set()
        sels, scale = tuple(sorted(drawn)), _marker_scale()
        if sels != piece["sels"]:
            piece["flt"].Selectors = list(sels) or [SENTINEL_NO_BLOCKS]
        if zs != piece["zs"]:
            piece["flt"].VerticalExaggeration = zs
        if scale != piece["scale"] and piece["flt"].GetProperty("MarkerScale") is not None:
            piece["flt"].MarkerScale = scale
        if (sels, zs, scale) != (piece["sels"], piece["zs"], piece["scale"]):
            # made now: what reads its blocks before the next frame (the cursor) finds those of this selection
            piece["flt"].UpdatePipeline()
        piece["sels"], piece["zs"], piece["scale"] = sels, zs, scale
        _dress(scene, piece, drawn, zs)
        return set(sels)

    def _made(vid):
        """{selector: the blocks the view's filter last made of it} — a
        log's tube, the markers of a marker frame."""
        piece = pieces.get(vid)
        if not piece or not piece["sels"]:
            return {}
        out = piece["flt"].GetClientSideObject().GetOutputDataObject(0)
        if out is None:
            return {}
        key = (out.GetMTime(), piece["sels"])
        if piece["key"] != key:
            asm = out.GetDataAssembly()
            piece["key"] = key
            piece["blocks"] = {sel: [out.GetPartition(index, 0)
                                     for node in (asm.SelectNodes([sel]) if asm is not None else ())
                                     for index in sorted(asm.GetDataSetIndices(node))
                                     if out.GetNumberOfPartitions(index) and out.GetPartition(index, 0) is not None]
                               for sel in piece["sels"]}
        return piece["blocks"]

    def _release_piece(vid):
        piece = pieces.pop(vid, None)
        if piece:
            _graph_reps_gone(piece)
        for proxy in (piece["rep"], piece["flt"], piece.get("gflt")) if piece else ():
            if proxy is None:
                continue
            try:
                pvsimple.Delete(proxy)
            except Exception as exc:
                print(f"[fespp] log tracks ({vid}): the filter not released ({exc})", flush=True)

    # ------------------------------------------------------------------
    # The graphs

    def _wanted(logs):
        """{selector: (stamp of its data, array, rings, of codes)} of the
        logs among `logs` that can be drawn as a graph: the reader's samples,
        what the scales, the ranges and the cursor read."""
        index = getattr(ctx, "assembly_index", None)
        out = {}
        if index is None:
            return out
        for sel, entry in logs.items():
            if not entry.color_array:
                continue
            nid = tree.find_node_id(sel)
            steps = (tree.find_type(nid) or "") in CODE_KINDS if nid is not None else False
            for ds, _flat in index.datasets(sel):
                key, rings = _rings(ds, entry.color_array)
                if rings is not None:
                    out[sel] = (key, entry.color_array, rings, steps)
                    break
        return out

    def _graph_width(wanted):
        """The graphs' width as drawn, for the session; the first one from
        the holes the first graphs stand on (engine/log_track.first_width)."""
        held_width = getattr(state, LOG_WIDTH, None)
        if isinstance(held_width, (int, float)) and held_width > 0:
            return float(held_width)
        if not wanted:
            return 1.0
        width = log_track.first_width([rings[0] for _key, _array, rings, _steps in wanted.values()])
        state[LOG_WIDTH] = width
        print(f"[fespp] journal log tracks: the graphs {numfmt.fmt(width)} wide, from the holes they stand on",
              flush=True)
        return width

    def _graph_rep(vid, pvv, piece, sel):
        """(extract, representation) the graph of the log `sel` is drawn by:
        its blocks of the view's filter, drawn flat — the colour is the
        value, whatever the light —; made on first use, None when it cannot
        be. One per log: the representation's own table paints its strip
        (a table per block of one shared representation crashed the render)."""
        reps = piece.setdefault("graphs", {})
        if sel not in reps:
            from fespp_on_trame.engine.sources import leaf_rep
            number = piece.get("graph_n", 0)
            piece["graph_n"] = number + 1
            ext = pvsimple.ExtractBlock(registrationName=f"fesppLogGraphs_{vid}_{number}", Input=piece["gflt"])
            ext.Assembly = "Assembly"
            ext.Selectors = [sel]
            rep = leaf_rep.show_composite(ext, pvv)
            if rep is None:
                pvsimple.Delete(ext)
                return None
            rep.Representation = "Surface"
            rep.Ambient, rep.Diffuse = 1.0, 0.0
            if rep.GetProperty("Assembly") is not None:
                rep.Assembly = "Assembly"
            reps[sel] = (ext, rep)
            piece.setdefault("graph_at", {})[sel] = _in_extract(ext, sel)
        return reps[sel]

    def _in_extract(ext, sel):
        """`sel` as the extract's output names it: its assembly has a root of
        its own in place of the filter's — a selector of the filter's names
        none of its blocks, and its representation draws nothing."""
        ext.UpdatePipeline()
        data = ext.GetClientSideObject().GetOutputDataObject(0)
        asm = data.GetDataAssembly() if data is not None and hasattr(data, "GetDataAssembly") else None
        root = asm.GetRootNodeName() if asm is not None else ""
        if not root or sel.count("/") < 2:
            return sel
        return "/" + root + "/" + sel.split("/", 2)[2]

    def _graph_reps_gone(piece, keep=()):
        """The representations of the graphs no longer drawn released."""
        reps = piece.get("graphs") or {}
        for sel in [s for s in reps if s not in keep]:
            ext, rep = reps.pop(sel)
            piece.get("graph_at", {}).pop(sel, None)
            for proxy in (rep, ext):
                try:
                    pvsimple.Delete(proxy)
                except Exception as exc:
                    print(f"[fespp] log tracks: a graph not released ({exc})", flush=True)

    def _graph_parts(vid):
        """{selector: {"strip", "curve", "gaps": the blocks the view's filter
        made of the log's graph, "faces": whether it faces the screen (a well
        plumb all along)}}."""
        piece = pieces.get(str(vid))
        sels = ((piece or {}).get("graph_set") or ((),))[0]
        if not piece or not sels or piece.get("gflt") is None:
            return {}
        out = piece["gflt"].GetClientSideObject().GetOutputDataObject(0)
        if out is None:
            return {}
        key = (out.GetMTime(), sels)
        if piece.get("parts_key") == key:
            return piece["parts"]
        asm = out.GetDataAssembly()
        parts = {}
        for sel in sels:
            mine = {}
            for name in GRAPH_PARTS:
                found = [index for node in (asm.SelectNodes([f"{sel}/{name}"]) if asm is not None else ())
                         for index in asm.GetDataSetIndices(node) if out.GetNumberOfPartitions(index)]
                mine[name] = out.GetPartition(found[0], 0) if found else None
            strip = mine.get("strip")
            mine["faces"] = bool(strip is not None and strip.GetFieldData().GetArray(FACES_SCREEN) is not None)
            parts[sel] = mine
        piece["parts_key"], piece["parts"] = key, parts
        return parts

    def _telling_table(vid, scene, array, low, high):
        """The view's table of a log on the diverging map over the TRUE range
        [`low`, `high`] of the logs of its kind (engine/diverging_table):
        blue negative, white zero, red positive, the bar from the least value
        to the largest; a log of codes painted by code, each code the colour
        of its value. Painted again when that range or those codes change, as
        long as the table still holds what this feature wrote: the Colormap
        card's edits stay, and a table a session wrote back keeps its."""
        lut = scene.scoped_lut(array)
        if lut is None or int(getattr(lut, "UseLogScale", 0) or 0):
            return
        key = (vid, array)
        mine = painted.get(key)
        if mine is None and key in getattr(ctx, "colormap_restored", {}):
            return
        if high <= low:
            # a constant log: its one value inside the bar
            low, high = _ranges.widen_for_bar(low, high)
        indexed = categorical_palette.is_indexed(lut)
        codes = list(categorical_palette.annotations_of(lut)) if indexed else []
        if mine is not None:
            if list(lut.RGBPoints or ()) != mine["points"]:
                return      # its ramp changed by hand
            if mine["range"] == (low, high) and mine["codes"] == codes:
                return
        try:
            if mine is None:
                # the map's NaN colour and the card's preset name, once; the
                # preset turns a table painted by code back to values
                lut.ApplyPreset(DIVERGING_PRESET, True)
                if indexed:
                    categorical_palette.set_indexed(lut, True)
                if getattr(ctx, "colormap_presets", None) is not None:
                    ctx.colormap_presets[key] = DIVERGING_PRESET
            pts, cols = diverging_table.paint(lut, low, high)
            # pinned: the scene's own rescale to the data's range would undo it
            lut.AutomaticRescaleRangeMode = "Never"
            painted[key] = {"points": list(lut.RGBPoints or ()), "codes": codes, "colours": cols,
                            "range": (low, high)}
            push = getattr(ctx, "colormap_push", None)
            if push is not None:
                push(vid)
        except Exception as exc:
            print(f"[fespp] log tracks ({vid}): the table of {array} not set ({exc!r})", flush=True)

    def _screen(pvv):
        """The camera's (right, direction), as drawn, rounded so that a turn
        of less than half a degree or so lays nothing again; None when the
        camera has no frame."""
        cam = pvv.GetActiveCamera()
        toward = np.asarray(cam.GetDirectionOfProjection(), float)
        right = np.cross(toward, np.asarray(cam.GetViewUp(), float))
        size = float(np.linalg.norm(right))
        if size < 1e-9:
            return None
        return (tuple(round(float(v), 2) for v in right / size),
                tuple(round(float(v), 2) for v in toward / max(float(np.linalg.norm(toward)), 1e-12)))

    def _turn(vid):
        """Before a render of `vid`: the graphs of its wells plumb all along
        laid again facing the screen when the camera turned (the filter's
        ScreenRight); its wellheads' pictograms sized for how large it draws
        their wells."""
        pvv = _pv_view(vid)
        if pvv is None:
            return
        try:
            screen = _screen(pvv)
            piece = pieces.get(vid)
            if (piece and piece.get("gflt") is not None
                    and log_track.faces_again(piece.get("faces"), turned.get(vid), screen,
                                              in_drag(pvv) or FLIGHTS.flying(vid))):
                turned[vid] = screen
                piece["gflt"].ScreenRight = list(screen[0])
                piece["gflt"].UpdatePipeline()
                if piece.get("graph_set"):
                    piece["graph_set"] = piece["graph_set"][:-1] + (screen,)
                # the scale's labels where the bars now stand
                _scale_settle(vid, pvv, sorted({k[0] for k in scale_labels.get(vid) or {}}), z_scale_of(state, vid))
            _sized(vid, pvv)
        except Exception as exc:
            print(f"[fespp] log tracks ({vid}): not turned with the camera ({exc!r})", flush=True)

    def _resized(vid):
        """The view about to draw at another size (trame shrinks it for the
        frames of a drag, grows it back on release): what it writes a fixed
        size on screen follows before that frame — a font changed once the
        render has begun only shows in the next one."""
        pvv = _pv_view(vid)
        if pvv is None:
            return
        try:
            _sized(vid, pvv)
        except Exception as exc:
            print(f"[fespp] log tracks ({vid}): names not sized for the frame ({exc!r})", flush=True)

    def _watched(vid, pvv):
        """The view's renders and size followed, from its first graph or
        wellhead on."""
        if vid in watch or pvv is None:
            return
        turn = lambda *_a, v=vid: _turn(v)        # noqa: E731
        size = lambda *_a, v=vid: _resized(v)     # noqa: E731
        prop = pvv.GetProperty("ViewSize").SMProperty
        watch[vid] = [(pvv.SMProxy, pvv.SMProxy.AddObserver("StartEvent", turn), turn),
                      (prop, prop.AddObserver("ModifiedEvent", size), size)]

    def _sized(vid, pvv):
        """The wellheads' pictograms and names and the markers' names of the
        view drawn their size on screen, whatever the share of the screen's
        resolution its frame has (`drag_ratio`)."""
        ratio = drag_ratio(pvv)
        _heads_sized(vid, pvv, ratio)
        _names_sized(vid, ratio)
        font = max(1, int(round(SCALE_FONT * ratio)))
        for _src, rep, _at, _text in (scale_labels.get(vid) or {}).values():
            if int(rep.FontSize) != font:
                rep.FontSize = font
                rep.DisplayOffset = [int(round(v * ratio)) for v in SCALE_BESIDE]

    def _names_sized(vid, ratio):
        """The markers' names written in the view at their size on screen,
        in a frame of `ratio` of the screen's resolution."""
        font = max(1, int(round(MARKER_NAME_FONT * ratio)))
        for _src, rep, _at in (labels.get(vid) or {}).values():
            if int(rep.FontSize) != font:
                rep.FontSize = font
                rep.DisplayOffset = [int(round(v * ratio)) for v in MARKER_NAME_BESIDE]

    def _heads_sized(vid, pvv, ratio):
        """Each wellhead of the view drawn the size its step gives: how large
        the view draws its well, the diagonal of its trajectory's box on
        screen at rest (PICTOGRAM_STEPS), in a frame of `ratio` of the
        screen's resolution."""
        heads = [wh for wh in core.selector.wellheads() if getattr(wh, "view_id", None) == vid]
        index = getattr(ctx, "assembly_index", None)
        if not heads or index is None:
            return
        cam = pvv.GetActiveCamera()
        high = max(1, int(round(pvv.ViewSize[1] / ratio)))
        zs = z_scale_of(state, vid)
        eye, sight = np.asarray(cam.GetPosition(), float), np.asarray(cam.GetDirectionOfProjection(), float)
        for wh in heads:
            at, path = wh.node_position, tree.find_path(wh.node_id)
            if at is None or not path:
                continue
            boxes = [ds.GetBounds() for ds, _flat in index.datasets(path)]
            if not boxes:
                continue
            low = np.min([[b[0], b[2], b[4] * zs] for b in boxes], axis=0)
            high_corner = np.max([[b[1], b[3], b[5] * zs] for b in boxes], axis=0)
            size = float(np.linalg.norm(high_corner - low))
            head = np.array([at[0], at[1], at[2] * zs])
            if cam.GetParallelProjection():
                pixel = 2.0 * float(cam.GetParallelScale()) / high
            else:
                ahead = max(float((head - eye) @ sight), 1e-6)
                pixel = 2.0 * math.tan(math.radians(float(cam.GetViewAngle())) / 2.0) * ahead / high
            seen = size / max(pixel, 1e-12)
            wh.set_size(next(px for floor, px in PICTOGRAM_STEPS if seen >= floor), ratio)

    def _settle_graphs(vid, scene, pvv, logs, modes, zs):
        """The logs among `logs` drawn as filled graphs or as curves
        (`modes`) by the view's filter (FESPP's well symbols filter: a graph
        in the well's curtain, laid on the trajectory's stations between two
        samples — drawing only); the selectors drawn."""
        mine = held.setdefault(vid, {})
        piece = _piece(vid, pvv) if logs else pieces.get(vid)
        if piece is None or piece["flt"].GetProperty("GraphSelectors") is None:
            if logs and not _NO_GRAPHS:
                _NO_GRAPHS.append(True)
                print(f"[fespp] log tracks ({vid}): the plugin's {FILTER} draws no graph — the logs stay tubes",
                      flush=True)
            mine.clear()
            return set()
        wanted = _wanted(logs)
        width = _graph_width(wanted)
        colours = _curve_colours() if wanted else {}
        # one scale and one range for the logs of one property kind: their least and largest values
        kind_of = getattr(ctx, "property_kind_of", None)
        kinds, spans = {}, {}
        for sel, (_key, _array, rings, _steps) in wanted.items():
            nid = tree.find_node_id(sel)
            kind = ((kind_of(nid) if kind_of is not None else tree.find_attribute_value(nid, "propertyKind"))
                    if nid is not None else "") or sel
            values, gap = rings[1], rings[2]
            kinds[sel] = kind
            if (~gap).any():
                low, high = float(values[~gap].min()), float(values[~gap].max())
                had = spans.get(kind)
                spans[kind] = (low, high) if had is None else (min(had[0], low), max(had[1], high))
        # a frame of a move (a drag, a camera flight) keeps the lay: laid again when it ends
        screen = log_track.lay_screen(_screen(pvv) if pvv is not None and wanted else None, turned.get(vid),
                                      pvv is not None and (in_drag(pvv) or FLIGHTS.flying(vid)))
        turned[vid] = screen
        sels = tuple(sorted(wanted))
        codes = tuple(s for s in sels if wanted[s][3])
        extents = tuple((s, max(abs(v) for v in spans.get(kinds[s], (0.0, 0.0)))) for s in sels)
        flt = _graph_filter(vid, piece)
        if flt is None:
            mine.clear()
            return set()
        settings = (sels, codes, extents, width, zs, tuple(wanted[s][0] for s in sels),
                    screen if piece.get("faces") else None)
        if settings != piece.get("graph_set"):
            flt.GraphSelectors = list(sels) or [SENTINEL_NO_BLOCKS]
            flt.CodeSelectors = list(codes) or [SENTINEL_NO_BLOCKS]
            flt.GraphExtents = [v for s, most in extents for v in (s, repr(float(most)))]
            flt.GraphWidth = width
            flt.VerticalExaggeration = zs
            if screen is not None:
                flt.ScreenRight = list(screen[0])
            flt.UpdatePipeline()
            piece["graph_set"] = settings
        parts = _graph_parts(vid)
        faces = any(p.get("faces") for p in parts.values())
        if faces and not piece.get("faces") and screen is not None:
            # a well plumb all along found: its graph follows the camera from now on
            flt.ScreenRight = list(screen[0])
            flt.UpdatePipeline()
            piece["graph_set"] = settings[:-1] + (screen,)
            parts = _graph_parts(vid)
        piece["faces"] = faces
        for sel in sels:
            _key, array, rings, steps = wanted[sel]
            values, gap = rings[1], rings[2]
            entry = mine.get(sel)
            mode = CURVE if modes.get(sel) == CURVE else GRAPH
            if entry is None or entry.get("key") != _key or entry.get("mode") != mode:
                strip = (parts.get(sel) or {}).get("strip")
                inserted = 0
                if strip is not None and strip.GetPointData().GetArray(LOG_SAMPLE) is not None:
                    said = vtk_to_numpy(strip.GetPointData().GetArray(LOG_SAMPLE))
                    inserted = int((said[: len(said) // 2] < 0).sum())
                least = float(values[~gap].min()) if (~gap).any() else None
                most = float(values[~gap].max()) if (~gap).any() else None
                told = ("no value: its hole in the NaN colour" if least is None else
                        f"{numfmt.fmt(least)} to {numfmt.fmt(most)}, {'coloured interval by interval, ' if steps else ''}"
                        f"{int(gap.sum())} sample(s) without a value")
                print(f"[fespp] journal log tracks ({vid}): {_title(sel)} drawn on its hole by the plugin ({mode},"
                      f" {told}; {inserted} station(s) of its trajectory between its samples, drawing only; the largest"
                      f" in size of its kind {numfmt.fmt(width)} off the hole)", flush=True)
            mine[sel] = {"key": _key, "array": array, "title": _title(sel), "mode": mode, "steps": steps,
                         "rings": rings, "void": not (~gap).any()}
        for sel in [s for s in mine if s not in sels]:
            mine.pop(sel)
        for sel in sels:
            if not mine[sel]["void"]:
                low, high = spans.get(kinds[sel], (0.0, 0.0))
                _telling_table(vid, scene, mine[sel]["array"], low, high)
        _graph_reps_gone(piece, keep=sels)
        for sel in sels:
            e = mine[sel]
            made = _graph_rep(vid, pvv, piece, sel)
            if made is None:
                continue
            _ext, rep = made
            at = piece["graph_at"][sel]
            lut = scene.scoped_lut(e["array"])
            shown = ([f"{at}/strip"] if e["mode"] != CURVE and not e["void"] else []) + [f"{at}/curve"]
            # the curve in the colour the 2D log view gives the log; the rails, the track's edges, in grey
            quads = [f"{at}/curve", *(str(c) for c in _rgb(colours.get(_log_title(sel)) or "#ffffff"))]
            if not e["void"]:
                shown += [f"{at}/rails", f"{at}/scale"]
                quads += [f"{at}/rails", *(str(c) for c in RAIL_COLOUR), f"{at}/scale", *(str(c) for c in RAIL_COLOUR)]
            if e["array"] in nan_shown.get(vid, ()):
                # where the log holds no value: its hole in the table's NaN colour
                shown.append(f"{at}/gaps")
                quads += [f"{at}/gaps", *(str(c) for c in (getattr(lut, "NanColor", None) or (1.0, 1.0, 0.0)))]
            rep.BlockSelectors = shown
            rep.SMProxy.UpdateProperty("BlockSelectors", 1)
            rep.ColorArrayName = ["CELLS" if e["steps"] else "POINTS", e["array"]]
            rep.LookupTable = lut
            if rep.GetProperty("BlockColors") is not None:
                rep.BlockColors = quads
            rep.LineWidth = 3.0 if e["mode"] == CURVE else 2.0
            rep.Scale = [1.0, 1.0, zs]
            rep.Visibility = 1
            rep.SMProxy.UpdateVTKObjects()
        _curves_unbarred(vid, scene, logs, modes)
        _scale_settle(vid, pvv, [s for s in sels if not mine[s]["void"]], zs)
        return set(sels)

    def _scale_settle(vid, pvv, sels, zs):
        """The labels of the graphs' scales (the filter's "scale" block, at the
        two ends of each log): "0" at the hole, the value a rail stands for
        with its unit at the rail, facing the screen in the rails' grey."""
        from fespp_on_trame.engine.sources import leaf_rep
        mine = scale_labels.setdefault(vid, {})
        wanted = {}
        parts = _graph_parts(vid) if sels else {}
        for sel in sels:
            ds = (parts.get(sel) or {}).get("scale")
            said = ds.GetPointData().GetArray(SCALE_VALUE) if ds is not None else None
            if said is None:
                continue
            nid = tree.find_node_id(sel)
            uom = (tree.find_attribute_value(nid, "uom") or "") if nid is not None else ""
            for k in range(ds.GetNumberOfPoints()):
                value = float(said.GetValue(k))
                text = "0" if value == 0.0 else numfmt.fmt(value) + (f" {uom}" if uom else "")
                wanted[(sel, k)] = (text, ds.GetPoint(k))
        for key in [k for k in mine if k not in wanted]:
            src, _rep, _at, _text = mine.pop(key)
            pvsimple.Delete(src)
        ratio = drag_ratio(pvv) if pvv is not None else 1.0
        for key, (text, at) in wanted.items():
            if key not in mine:
                src = pvsimple.Text(registrationName=f"fesppLogScale_{vid}_{len(mine)}_{key[1]}")
                rep = leaf_rep.show_composite(src, pvv)
                rep.TextPropMode = "Billboard 3D Text"
                rep.Justification = "Left"
                rep.Color = list(RAIL_COLOUR)
                mine[key] = (src, rep, None, None)
            src, rep, _at, said_text = mine[key]
            if said_text != text:
                src.Text = text
            rep.BillboardPosition = [at[0], at[1], at[2] * zs]
            rep.FontSize = max(1, int(round(SCALE_FONT * ratio)))
            rep.DisplayOffset = [int(round(v * ratio)) for v in SCALE_BESIDE]
            rep.Visibility = 1
            mine[key] = (src, rep, at, text)

    def _lit_settle(vid, pvv, zs):
        """The samples highlighted of the logs the view draws: those held (a
        row of the Values view, a click in the log view — what the 3D
        selection would light on a block of the source's) in the selection's
        colour, the one under the log view's pointer in blue."""
        _marks_settle(vid, pvv, zs, "lit", (getattr(ctx, "log_samples_lit", None) or {}).get(vid) or {},
                      LIT_COLOUR, f"fesppLogLit_{vid}")
        _marks_settle(vid, pvv, zs, "cursor", (getattr(ctx, "log_cursor_lit", None) or {}).get(vid) or {},
                      CURSOR_COLOUR, f"fesppLogCursor_{vid}")

    def _marks_settle(vid, pvv, zs, kind, lit, colour, name):
        """The samples `lit` ({log: [samples]}) of the logs the view draws, as
        ONE geometry in `colour`: on a graph a line from the hole to the
        curve and a dot on the curve, on a tube the sample's ring a little
        wider."""
        from fespp_on_trame.engine import log_lit
        drawn = held.get(vid) or {}
        parts = _graph_parts(vid) if lit and drawn else {}
        strips = {sel: (parts.get(sel) or {}).get("strip") for sel in lit if sel in drawn}
        data, counted = log_lit.geometry(lit, strips, _made(vid) if lit else {}, zs)
        points = data.GetPoints()
        mine = lit_marks.get((vid, kind))
        if mine is None and points.GetNumberOfPoints():
            from fespp_on_trame.engine.sources import leaf_rep
            src = pvsimple.TrivialProducer(registrationName=name)
            # its geometry first: no representation is made for a producer of nothing
            src.GetClientSideObject().SetOutput(data)
            src.UpdatePipeline()
            rep = leaf_rep.show_composite(src, pvv)
            rep.Representation = "Surface"
            rep.AmbientColor = rep.DiffuseColor = list(colour)
            rep.Ambient, rep.Diffuse = 1.0, 0.0
            rep.LineWidth, rep.PointSize = 3.0, 9.0
            if rep.GetProperty("RenderPointsAsSpheres") is not None:
                rep.RenderPointsAsSpheres = 1
            mine = lit_marks[(vid, kind)] = (src, rep, counted)
        if mine is None:
            return
        src, rep, _was = mine
        src.GetClientSideObject().SetOutput(data)
        src.SMProxy.MarkModified(src.SMProxy)
        src.UpdatePipeline()
        lit_marks[(vid, kind)] = (src, rep, counted)
        rep.Visibility = 1 if points.GetNumberOfPoints() else 0

    mds = {}            # (selector, its block's address, its mtime) -> the measured depth of each of its samples

    def _md_of(scene, sel):
        """The measured depth of each sample of the log `sel` (the reader's
        block, the plugin's "MD" field array), or None."""
        entry = scene.block_state.get(sel) if scene is not None else None
        index = getattr(ctx, "assembly_index", None)
        if entry is None or not entry.color_array or index is None:
            return None
        for ds, _flat in index.datasets(sel):
            key = (sel, ds.GetAddressAsString(""), ds.GetMTime())
            if key not in mds:
                got = log_track.samples(ds, entry.color_array)
                mds[key] = got[2] if got is not None else None
            if mds[key] is not None:
                return mds[key]
        return None

    def _cursor_lit(well, names, md):
        """The log view's cursor on the logs `names` of the wellbore `well` at
        the measured depth `md`: the sample nearest it lit on their graph or
        tube in every 3D view drawing them — the Values view open or not —,
        beside what the selection lights, which it leaves as it is."""
        lit_all = getattr(ctx, "log_cursor_lit", None)
        if lit_all is None:
            lit_all = ctx.log_cursor_lit = {}
        names = set(names or ())
        changed = []
        for vid, modes in list(shown_as.items()):
            scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
            mine = {}
            for sel in modes:
                nid = tree.find_node_id(sel)
                if nid is None or (tree.find_title(nid) or "") not in names:
                    continue
                wid = tree.find_parent_node_id_with_type(nid, "Wellbore")
                if wid is None or (tree.find_title(wid) or "") != well:
                    continue
                depth = _md_of(scene, sel)
                if depth is not None and len(depth) and not np.isnan(depth).all():
                    mine[sel] = [int(np.nanargmin(np.abs(depth - float(md))))]
            if mine != (lit_all.get(vid) or {}):
                if mine:
                    lit_all[vid] = mine
                else:
                    lit_all.pop(vid, None)
                changed.append(vid)
        for vid in changed:
            scheduler.mark_dirty(vid)
        if changed:
            scheduler.flush()

    ctx.welllog_cursor_lit = _cursor_lit

    def _lit_gone(vid):
        """The view's highlighted samples' geometries released."""
        for kind in ("lit", "cursor"):
            mine = lit_marks.pop((vid, kind), None)
            if mine is not None:
                try:
                    pvsimple.Delete(mine[0])
                except Exception as exc:
                    print(f"[fespp] log tracks ({vid}): a highlight not released ({exc})", flush=True)

    def _scale_gone(vid):
        """The labels of the view's scales released."""
        for src, _rep, _at, _text in (scale_labels.pop(vid, None) or {}).values():
            try:
                pvsimple.Delete(src)
            except Exception as exc:
                print(f"[fespp] log tracks ({vid}): a scale label not released ({exc})", flush=True)

    def _curves_unbarred(vid, scene, logs, modes):
        """The colour bar of a property whose logs this view shows are all
        curves goes: their colours are their names'. It comes back when one
        of them is drawn by value again; a bar switched off by hand stays."""
        if scene is None:
            return
        curves, valued = set(), set()
        for sel, entry in logs.items():
            if entry.color_array:
                (curves if modes.get(sel) == CURVE else valued).add(entry.color_array)
        mine = bars_off.setdefault(vid, set())
        for array in curves - valued:
            if array not in mine and scene.bar_visible(array):
                scene.set_bar_visible(array, False)
                mine.add(array)
        for array in [a for a in mine if a not in curves - valued]:
            scene.set_bar_visible(array, True)
            mine.discard(array)
        # the view's one bar moves to a property still drawn by value
        if mine and valued and (scene.bar_target or "") not in valued:
            scene.set_bar_target(sorted(valued)[0])

    # ------------------------------------------------------------------

    def _isolate(vid, scene, mine):
        """What this feature draws leaves the scene's composite; what it
        draws no more comes back."""
        was = off.get(vid, set())
        come, gone = mine - was, was - mine
        off[vid] = set(mine)
        if not (come or gone):
            return
        scene.isolated.update(come)
        scene.isolated.difference_update(gone)
        scene.reconcile()
        print(f"[fespp] journal log tracks ({vid}): {len(mine)} block(s) drawn here, off the composite"
              f" ({len(come)} left it, {len(gone)} back)", flush=True)

    def _drawn_as(logs, chosen):
        """{selector: TUBE | CURVE | GRAPH}: how each log of `logs` is drawn
        — the session's choice (`chosen`), a filled graph when there is
        none."""
        return {sel: chosen.get(sel) if chosen.get(sel) in (TUBE, CURVE, GRAPH) else GRAPH for sel in logs}

    def _mode_now(path, vid=None):
        """How the log `path` is drawn now: in the view `vid`, else in the
        first view showing it, else as the session chose (a filled graph
        when it did not)."""
        for v in ([vid] if vid is not None else list(shown_as)):
            if path in shown_as.get(v, {}):
                return shown_as[v][path]
        return _modes().get(path, GRAPH)

    def _named():
        held_names = getattr(state, MARKER_LABELS, None)
        return list(held_names) if isinstance(held_names, (list, tuple)) else []

    def _marker_rows(path):
        """The marker rows `path` stands for: itself, a marker; the markers of
        a marker set."""
        nid = tree.find_node_id(path) if path else None
        kind = (tree.find_type(nid) or "") if nid is not None else ""
        if kind in ("Marker", "WellboreMarker"):
            return [path]
        if kind == "MarkerFrame":
            return [tree.find_path(m) for m in tree.find_all_descendant_ids(nid)
                    if (tree.find_type(m) or "") in ("Marker", "WellboreMarker")]
        return []

    def _labels_settle(vid, pvv, markers, zs):
        """The names of the markers asked for (``ui_marker_labels``) written
        beside them where the view draws them, facing the screen, in their
        colour; the others taken off."""
        from fespp_on_trame.engine.sources import leaf_rep
        mine = labels.setdefault(vid, {})
        index = getattr(ctx, "assembly_index", None)
        drawn = set(markers)
        wanted = {}
        for path in _named():
            # drawn when its row, or its set's, is drawn in the view
            if index is None or not any(path == s or path.startswith(s.rstrip("/") + "/") for s in drawn):
                continue
            boxes = [ds.GetBounds() for ds, _flat in index.datasets(path)]
            if boxes:
                b = boxes[0]
                wanted[path] = [(b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0, (b[4] + b[5]) / 2.0]
        for path in [p for p in mine if p not in wanted]:
            src, _rep, _at = mine.pop(path)
            pvsimple.Delete(src)
        colours = _marker_colours([_log_title(p) for p in wanted]) if wanted else {}
        for path, at in wanted.items():
            if path not in mine:
                src = pvsimple.Text(registrationName=f"fesppMarkerName_{vid}_{len(mine)}")
                src.Text = _log_title(path)
                rep = leaf_rep.show_composite(src, pvv)
                rep.TextPropMode = "Billboard 3D Text"
                rep.Justification = "Left"
                rep.FontSize = MARKER_NAME_FONT
                rep.DisplayOffset = list(MARKER_NAME_BESIDE)
                mine[path] = (src, rep, at)
            src, rep, _at = mine[path]
            rep.BillboardPosition = [at[0], at[1], at[2] * zs]
            rep.Color = _rgb(colours.get(_log_title(path)) or "#ffffff")
            rep.Visibility = 1

    def _names_shown(path, on):
        """The names of the markers `path` stands for written (`on`) or not,
        in every view."""
        rows = _marker_rows(path)
        named = _named()
        now = ([p for p in named if p not in rows] + rows) if on else [p for p in named if p not in rows]
        if now == named:
            return
        state[MARKER_LABELS] = now
        print(f"[fespp] journal log tracks: {len(rows)} marker name(s) {'shown' if on else 'hidden'}"
              f" ({len(now)} named)", flush=True)
        scheduler.mark_all_dirty()
        scheduler.flush()

    def _settle_view(vid):
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        pvv = _pv_view(vid)
        # none of this round the Earth: a Globe scene draws in its own space
        on = scene is not None and pvv is not None and not getattr(scene, "epsg", None)
        logs = _shown_where(scene) if on else {}
        modes = shown_as[vid] = _drawn_as(logs, _modes())
        markers = _shown_where(scene, MARKER_KINDS) if on else {}
        zs = z_scale_of(state, vid)
        drawn = _settle_symbols(vid, scene, pvv,
                                {**{s: e for s, e in logs.items() if modes.get(s) == TUBE}, **markers}, zs)
        graphs = _settle_graphs(vid, scene, pvv, {s: e for s, e in logs.items() if modes.get(s) != TUBE},
                                modes, zs)
        if scene is not None:
            _isolate(vid, scene, drawn | graphs)
        if pvv is not None:
            _labels_settle(vid, pvv, markers, zs)
            _watched(vid, pvv)
            _sized(vid, pvv)
        if pvv is not None:
            _lit_settle(vid, pvv, zs)
        # the Colormap card says "Hide NaN cells" usable on a log drawn here: told again when they change
        arrays = tuple(sorted({e.get("array") or "" for e in (held.get(vid) or {}).values()}))
        if arrays != said_arrays.get(vid):
            said_arrays[vid] = arrays
            push = getattr(ctx, "colormap_push", None)
            if push is not None:
                push(vid)

    def _settle(view_ids):
        for vid in view_ids:
            try:
                _settle_view(str(vid))
            except Exception as exc:
                print(f"[fespp] log tracks ({vid}): not settled ({exc!r})", flush=True)
        _tree_entries()

    scheduler.add_flush_listener(_settle)

    def _logs_coloured(_pid, _payload):
        """The log view's payload changed: the curves the 3D views draw take
        its colours again."""
        if any(held.values()):
            scheduler.mark_all_dirty()
            scheduler.flush()

    ctx.welllog_listeners = list(getattr(ctx, "welllog_listeners", None) or []) + [_logs_coloured]

    # ------------------------------------------------------------------
    # Filled graph, curve or tube: the right-click menus

    def _as(path, mode):
        """The log `path` drawn as `mode`, in every view: the session's
        choice."""
        modes = _modes()
        if (_mode_now(path) == mode and modes.get(path) == mode) or not _is_channel(path):
            return
        modes[path] = mode
        state[MODES] = modes
        print(f"[fespp] journal log tracks: {_title(path)} drawn as a {'filled graph' if mode == GRAPH else mode}"
              f" ({sum(m == TUBE for m in modes.values())} tube(s), {sum(m == CURVE for m in modes.values())}"
              f" curve(s))", flush=True)
        scheduler.mark_all_dirty()
        scheduler.flush()

    def _markers_sized(step):
        """The markers `step` times as large, in every view."""
        low, high = MARKER_RANGE
        scale = min(high, max(low, _marker_scale() * step))
        if scale == _marker_scale():
            return
        state[MARKER_SCALE] = scale
        print(f"[fespp] journal log tracks: the markers drawn {numfmt.fmt(scale)} times as large as the reader makes"
              f" them", flush=True)
        scheduler.mark_all_dirty()
        scheduler.flush()

    def _widened(step):
        """The graphs `step` times as wide, in every view."""
        width = getattr(state, LOG_WIDTH, None)
        if not isinstance(width, (int, float)) or width <= 0:
            return
        state[LOG_WIDTH] = float(width) * step
        print(f"[fespp] journal log tracks: the graphs {numfmt.fmt(state[LOG_WIDTH])} wide", flush=True)
        scheduler.mark_all_dirty()
        scheduler.flush()

    ctx.context_actions_extra = {**(getattr(ctx, "context_actions_extra", None) or {}),
                                 **{key: (lambda path, *_, m=mode: _as(path, m)) for mode, key in AS.items()},
                                 LARGER: lambda *_: _markers_sized(MARKER_STEP),
                                 SMALLER: lambda *_: _markers_sized(1.0 / MARKER_STEP),
                                 GRAPHS_LARGER: lambda *_: _widened(WIDTH_STEP),
                                 GRAPHS_SMALLER: lambda *_: _widened(1.0 / WIDTH_STEP),
                                 NAME_ON: lambda path, *_: _names_shown(path, True),
                                 NAME_OFF: lambda path, *_: _names_shown(path, False),
                                 NAMES_ON: lambda path, *_: _names_shown(path, True),
                                 NAMES_OFF: lambda path, *_: _names_shown(path, False)}

    def _tree_entries(**_):
        """The trees' menu offers, on a log read, the two other ways to draw
        it, the graphs larger or smaller, and the markers larger or
        smaller."""
        channels = [p for p in (getattr(state, "ui_loaded_array_paths", None) or ()) if _is_channel(p)]
        now = {p: _mode_now(p) for p in channels}
        entries = [{"key": key, "label": LABELS[key], "types": list(PROPERTY_KINDS),
                    "rows": [p for p in channels if now[p] != mode]} for mode, key in AS.items()]
        graphs = [p for p in channels if now[p] != TUBE]
        entries += [{"key": GRAPHS_LARGER, "label": LABELS[GRAPHS_LARGER], "types": list(PROPERTY_KINDS), "rows": graphs},
                    {"key": GRAPHS_SMALLER, "label": LABELS[GRAPHS_SMALLER], "types": list(PROPERTY_KINDS),
                     "rows": graphs}]
        entries += [{"key": LARGER, "label": LABELS[LARGER], "types": list(MARKER_KINDS), "when": "loaded"},
                    {"key": SMALLER, "label": LABELS[SMALLER], "types": list(MARKER_KINDS), "when": "loaded"}]
        entries += _name_entries()
        if entries != getattr(state, TREE_EXTRAS, None):
            state[TREE_EXTRAS] = entries
        _chips()

    def _chips():
        """A log a view draws as a graph or a curve wears, on its row in the
        trees, the chip of its curve's colour: the 2D log view's; a marker
        drawn, the chip of its colour."""
        drawn = {sel for mine in held.values() for sel in mine}
        colours = _curve_colours() if drawn else {}
        chips = log_track.marker_chips(pieces)
        chips.update({p: colours[_log_title(p)] for p in drawn if colours.get(_log_title(p))})
        if chips != getattr(state, TREE_CHIPS, None):
            state[TREE_CHIPS] = chips

    def _name_entries():
        """The trees' entries writing or taking off the names of a marker, of
        the markers of a set — offered on the rows read."""
        named = set(_named())
        rows = [p for p in (getattr(state, "ui_loaded_rep_paths", None) or ()) if _marker_rows(p)]
        rows += [p for p in (getattr(state, "ui_loaded_array_paths", None) or ()) if _marker_rows(p)]
        marks, sets = set(), set()
        for p in rows:
            (marks if _marker_rows(p) == [p] else sets).add(p)
            if _marker_rows(p) != [p]:
                marks.update(_marker_rows(p))
        return [
            {"key": NAME_ON, "label": LABELS[NAME_ON], "types": ["Marker", "WellboreMarker"],
             "rows": sorted(p for p in marks if p not in named)},
            {"key": NAME_OFF, "label": LABELS[NAME_OFF], "types": ["Marker", "WellboreMarker"],
             "rows": sorted(p for p in marks if p in named)},
            {"key": NAMES_ON, "label": LABELS[NAMES_ON], "types": ["MarkerFrame"],
             "rows": sorted(p for p in sets if any(m not in named for m in _marker_rows(p)))},
            {"key": NAMES_OFF, "label": LABELS[NAMES_OFF], "types": ["MarkerFrame"],
             "rows": sorted(p for p in sets if any(m in named for m in _marker_rows(p)))},
        ]

    state.change("ui_loaded_array_paths", "ui_loaded_rep_paths", MODES, MARKER_LABELS)(_tree_entries)

    def _view_entries(vid, path):
        """The 3D view's menu on a log: the two other ways to draw it, the
        graphs larger or smaller; on a marker: larger, smaller."""
        nid = tree.find_node_id(path) if path else None
        if nid is not None and (tree.find_type(nid) or "") in MARKER_KINDS:
            rows, named = _marker_rows(path), set(_named())
            single = rows == [path]
            name = ([(NAME_OFF if path in named else NAME_ON, LABELS[NAME_OFF if path in named else NAME_ON])]
                    if single else
                    [(NAMES_ON, LABELS[NAMES_ON])] * any(m not in named for m in rows)
                    + [(NAMES_OFF, LABELS[NAMES_OFF])] * any(m in named for m in rows))
            return [(LARGER, LABELS[LARGER]), (SMALLER, LABELS[SMALLER])] + name
        if not path or not _is_channel(path):
            return []
        now = _mode_now(path, vid)
        wide = [(GRAPHS_LARGER, LABELS[GRAPHS_LARGER]), (GRAPHS_SMALLER, LABELS[GRAPHS_SMALLER])] if now != TUBE else []
        return [(key, LABELS[key]) for mode, key in AS.items() if mode != now] + wide

    ctx.view_menu_extras = list(getattr(ctx, "view_menu_extras", None) or []) + [_view_entries]

    def _nan_drawn(vid, array):
        """Whether `vid` draws a log of `array` as a graph or a curve: its
        stretches without a value are the Colormap card's "Hide NaN cells"."""
        return any(e.get("array") == array for e in (held.get(str(vid)) or {}).values())

    def _nan_hidden(vid, array):
        return array not in nan_shown.get(str(vid), ())

    def _nan_hide(vid, array, on):
        """The stretches without a value of the logs of `array` drawn in
        `vid` hidden (`on`: the trajectory's own colour there) or drawn in the
        NaN colour."""
        mine = nan_shown.setdefault(str(vid), set())
        if bool(on) == (array not in mine):
            return
        (mine.discard if on else mine.add)(array)
        print(f"[fespp] journal log tracks ({vid}): the stretches of {array} without a value"
              f" {'hidden' if on else 'drawn in the NaN colour'}", flush=True)
        scheduler.mark_dirty(str(vid))
        scheduler.flush()

    # the Colormap card's "Hide NaN cells" on a log drawn as a graph (app/features/colormap_card, colormap_edits)
    ctx.log_nan = (_nan_drawn, _nan_hidden, _nan_hide)
    # the blocks of the graphs the view's filter made, for the benches
    ctx.log_graph_parts = _graph_parts

    # ------------------------------------------------------------------

    @lifecycle.on("view_closed")
    def _forget(vid):
        vid = str(vid)
        held.pop(vid, None)
        _release_piece(vid)
        off.pop(vid, None)
        bars_off.pop(vid, None)
        shown_as.pop(vid, None)
        turned.pop(vid, None)
        nan_shown.pop(vid, None)
        for k in [k for k in painted if k[0] == vid]:
            painted.pop(k, None)
        for src, _rep, _at in (labels.pop(vid, None) or {}).values():
            pvsimple.Delete(src)
        _scale_gone(vid)
        _lit_gone(vid)
        for watched, tag, _fn in watch.pop(vid, None) or ():
            try:
                watched.RemoveObserver(tag)
            except Exception as exc:
                print(f"[fespp] log tracks ({vid}): renders still followed ({exc})", flush=True)

    @lifecycle.on("new_data")
    def _new_data():
        """Another assembly: the graphs of the last one go with its blocks,
        and the filters draw none of it until the views show logs again."""
        read.clear()
        held.clear()
        off.clear()
        for vid in list(labels):
            for src, _rep, _at in labels.pop(vid).values():
                pvsimple.Delete(src)
        for vid in list(scale_labels):
            _scale_gone(vid)
        for piece in pieces.values():
            if piece:
                piece["flt"].Selectors = [SENTINEL_NO_BLOCKS]
                if piece.get("gflt") is not None:
                    piece["gflt"].GraphSelectors = [SENTINEL_NO_BLOCKS]
                piece["rep"].Visibility = 0
                _graph_reps_gone(piece)
                piece.update(sels=(), worn=None, key=None, blocks={}, graph_set=None, parts_key=None, faces=False)
        # the logs and markers still shown are drawn again at the next frame of every view
        scheduler.mark_all_dirty()

    def _as_source(vid, gid, ids):
        """[flat, proc, cell, …] picked on what this feature draws, as the
        source's: the view's filter keeps the reader's places and cells; a
        graph stands for its log, one cell of it — ParaView hands a pick on a
        graph's extract back as the filter's, at the graph's block. None when
        `gid` is none of its."""
        vid = str(vid)
        piece = pieces.get(vid)
        index = getattr(ctx, "assembly_index", None)
        if piece and piece["flt"].SMProxy.GetGlobalIDAsString() == gid:
            return _graphs_as_logs(piece, list(ids), index)
        for sel, (ext, _rep) in ((piece or {}).get("graphs") or {}).items():
            if ext.SMProxy.GetGlobalIDAsString() == gid:
                flats = index.flat_indices(sel) if index is not None else []
                return [flats[0], ids[1] if len(ids) > 1 else 0, 0] if flats else []
        return None

    def _graphs_as_logs(piece, ids, index):
        """`ids` of the view's filter, a graph's block as its log's: the
        blocks the filter adds under a log are none of the reader's."""
        out_index = piece.get("out_index")
        if out_index is None:
            from fespp_on_trame.engine.blockscope.assembly_index import AssemblyIndex
            flt = piece["flt"]
            out_index = piece["out_index"] = AssemblyIndex(
                lambda: flt.GetClientSideObject().GetOutputDataObject(0))
        out = []
        for k in range(0, len(ids) - 2, 3):
            flat, proc, cell = ids[k:k + 3]
            node = out_index.selector_for_flat(flat) or ""
            log, _sep, part = node.rpartition("/")
            if part in GRAPH_PARTS:
                flats = index.flat_indices(log) if index is not None else []
                if not flats:
                    continue
                flat, cell = flats[0], 0
            if [flat, proc, cell] not in [out[j:j + 3] for j in range(0, len(out), 3)]:
                out += [flat, proc, cell]
        return out

    ctx.pick_twins = list(getattr(ctx, "pick_twins", None) or []) + [_as_source]

    def _stand_in(vid, sel):
        """The blocks the view's filter draws in the place of the block `sel`."""
        return _made(str(vid)).get(sel) or []

    ctx.block_stand_ins = list(getattr(ctx, "block_stand_ins", None) or []) + [_stand_in]

    def _probe_targets(vid):
        """A filled graph is met on its strip, a curve on its line, the
        stretches of hole without a value on themselves where they are
        drawn."""
        out = []
        mine = held.get(str(vid)) or {}
        for sel, parts in _graph_parts(vid).items():
            e = mine.get(sel) or {}
            part = parts.get("curve") if e.get("mode") == CURVE else (None if e.get("void") else parts.get("strip"))
            if part is not None:
                out.append((part, PROBE))
            if parts.get("gaps") is not None and e.get("array") in nan_shown.get(str(vid), ()):
                out.append((parts["gaps"], PROBE))
        return out

    def _sample_at(ds, point_id):
        """The sample of the log a point of a graph stands for (a station of
        the trajectory: the nearest sample's); None when the graph says none."""
        said = ds.GetPointData().GetArray(LOG_SAMPLE) if ds is not None else None
        point = log_track.real_point(ds, point_id) if said is not None and point_id is not None else None
        value = said.GetValue(point) if point is not None and 0 <= point < said.GetNumberOfTuples() else -1
        return int(value) if value >= 0 else None

    def _probe_line(vid, pt, hit):
        """What the cursor reads on a graph: the log, its value there — a
        code by its name —, read on the log's own samples (a station of the
        trajectory, drawing only, says the nearest sample's)."""
        if (hit or {}).get("title") != PROBE:
            return ""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(str(vid))
        mine = held.get(str(vid)) or {}
        for sel, parts in _graph_parts(vid).items():
            ds = hit.get("ds")
            if not any(parts.get(name) is ds for name in GRAPH_PARTS) or sel not in mine:
                continue
            e = mine[sel]
            if parts.get("gaps") is ds:
                return e["title"] + "   no value"
            sample = _sample_at(ds, ds.FindPoint(list(pt)))
            values, gap = e["rings"][1], e["rings"][2]
            if sample is None or sample >= len(values) or gap[sample]:
                return e["title"] + "   no value"
            value = float(values[sample])
            entry = scene.block_state.get(sel) if scene is not None else None
            names = {float(c.get("code")): c.get("label") for c in (getattr(entry, "categories", None) or ())
                     if isinstance(c, dict) and c.get("code") is not None}
            word = names.get(value)
            return e["title"] + (f"   {word} (code {numfmt.fmt_int(value)})" if word else f"   {numfmt.fmt(value)}")
        return ""

    ctx.cursor_probes = list(getattr(ctx, "cursor_probes", None) or []) + [(_probe_targets, _probe_line)]
