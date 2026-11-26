"""Well-log correlation payload — turn checked channels into drawable curves.

The `welllog` panel (a singleton dockview tab, opened by the tree's right-click
"Add to Well Log view") draws whatever sits in ``state.welllog_data__<vid>``:

    {"wells": [{name, color, depthRef, depthUnit, tvdUnit, integrationRef,
                mdDatum: {ref, tvd} | None,   # the MD zero: MdReference, TVD
                depth: {min, max}, mdTvd: [[md, tvd], ...],   # drawn in MD
                tracks: [{kind, unit, logScale,
                          curves: [{name, color, unit, range, missing,
                                    samples: [[value|null, depth, tvd]]}]}],
                                    # tvd only on a well drawn in MD
                tops:   [{name, depth, tvd}],
                absent: {channel title: {kind, why}},
                pay:    [[top, bottom], ...],      # the DRAWING axis
                pay_tvd:[[top, bottom], ...],      # the same pay, vertical
                pay_na: [curve name, ...],
                pay_na_why: {curve name: why},
                tvd_up_hole: <metres of hole that comes back up>,
                summation: {phi, phi_candidates, phi_absent,
                            sw, sw_candidates, sw_absent},
                zones:  [{name, color, top, bottom, thickness, source,
                          top_tvd, bottom_tvd, thickness_tvd, tvd_na,
                          net, ntg, phih, hcph, pay_na,
                          curves: [{name, unit, n, mean, min, max,
                                    p10, p50, p90, n_pay, mean_pay}]}]}],
     "markers": [{name, color}],
     "flattenOn": <marker name> | None,
     "csv": {name, header}}      # the zones table's export (zones_csv_payload)

TWO AXES, NEVER MIXED. The DRAWING axis (`depthRef`) is the measured depth
when every curve sample and every top of the well carries one, the true
vertical depth otherwise — it is what `samples`, `depth`, `tops[].depth` and
the stratigraphic bands are expressed in, and what the panel plots — the
pay band too, hence `pay` drawn and `pay_tvd` vertical. The
INTEGRATION axis (`integrationRef`) is ALWAYS the true vertical depth: every
thickness, every ratio of thicknesses and every Φ·h sum is computed on it,
whatever is drawn. A thickness read along a hole inclined at 60° is twice the
rock it stands for. And the two axes being separate is what keeps the table
still when a synthetic log (which carries no measured depth) flips the
drawing axis.

`_full` — every sample of every curve, ``{name: [[value, draw, tvd]]}``: the
statistics read it, the client never sees it (the host strips it). A sample
of the fixture form ``[value, depth]`` means "the one depth IS the vertical".
`absent` — the channels the well logs that the panel does not carry, each
with its property kind and why: ``"unticked"`` (channels are ticked per
wellbore, so a log ticked on one well is unticked on the next) or
``"unreadable"`` (ticked, no sample could be read). A curve named nowhere
on the well is ``"unlogged"`` — see `absent_why`.
`zones` is the petrophysicist's question — "mean porosity in THIS formation,
well by well" — answered on the log samples. The intervals are the rock lane
the wellbore's marker frame states (`strati`, see `frame_bands`), or,
without one, each pair of consecutive marker picks. See `zone_stats`. `pay`,
`pay_na`, `pay_na_why`, `summation` and the net / ntg / *_pay fields exist
only under a panel's cutoffs — see `with_cutoffs`, applied per panel on the
shared payload. A rule on a curve the well does not carry makes the pay NOT
EVALUABLE on that well: `pay_na` names the curves, `pay_na_why` says why
each is not there, and every figure that rests on the pay is None rather
than a zero that would read as a sterile well. `summation` names the
porosity and water-saturation curves the Φ·h figures were read from, the
other curves that could have been taken, and the absent ones of the kind.

This module owns the pure computation; `boot` owns the watcher that calls it.

Where the numbers come from (see PARAVIEW.md)
--------------------------------------------
A log channel is a ``DiscreteProperty`` / ``ContinuousProperty`` LEAF under a
``Frame`` node — there is no "Channel" kind, and the Frame owns no dataset.
The application reads each channel as its polyline (the reader's LogTubes off,
engine/sources/reader_options): one point per frame node, one cell. A reader
left with its tubes builds a ``vtkTubeFilter`` tube of ``nSides`` points per
node, value AND Z constant across each ring, ``nSides == GetNumberOfCells()``.
Either way one sample per ring of ``GetNumberOfCells()`` points.

The depth axis is the TRUE measured depth when the plugin ships it (an "MD"
field array on every channel block and every marker block), and the
geometry's -Z (TVD) otherwise. ONE axis
per well, decided only after every curve and top has answered: mixing MD
curves with TVD tops would misplace one or the other on every deviated well,
so a single missing MD anywhere falls the whole well back to TVD.

Only CHECKED paths are used: the collector materialises a block's arrays only
once its path reaches the reader through ``selected_paths``. An unchecked
channel has no data to read, so it contributes no curve.
"""
import bisect
import math
import re

from paraview import simple as pvsimple
from paraview import servermanager as sm

from fespp_on_trame.engine.utils.color_palette import color_for_index
from fespp_on_trame.engine.utils.naming import make_valid_vtk_name

# What a node IS in the tree, asked by ROLE rather than by RESQML class.
# The role comes from the numeric code FESPP puts on the assembly, resolved
# through the enum table the plugin publishes (Tree.find_role) — so these are
# the plugin's own words, not names copied here and left to drift.
#
# The distinction matters here more than anywhere: a well-log channel and a
# grid property are BOTH "ContinuousProperty", and only the role tells them
# apart (role WellboreChannel against role Properties). Matching the class
# name alone is safe only because these walks are already scoped to a
# wellbore, which is why it serves as the fallback below.
_CHANNEL_ROLES = ("WellboreChannel",)
_TRAJECTORY_ROLES = ("WellboreTrajectory",)
_TRAJECTORY_KINDS = ("WellboreTrajectory", "Trajectory")
_FRAME_ROLES = ("WellboreFrame",)
_MARKER_ROLES = ("WellboreMarker",)

# The FESAPI-derived class names, kept as the fallback for a plugin too old to
# publish the enum table — Tree.find_role is None there.
_CHANNEL_KINDS = ("ContinuousProperty", "DiscreteProperty", "CategoricalProperty")
_FRAME_KINDS = ("Frame",)
_MARKER_KINDS = ("Marker",)

# A wellbore can carry thousands of samples per curve and the payload
# crosses the websocket on every rebuild. Curves are decimated to this
# many samples — plenty for a correlation track, ~20x smaller than the raw log.
MAX_SAMPLES = 2000


def _fetch_block(shared_source, selector):
    """The one PDC block at `selector`, fetched into the server process.

    Transient ExtractBlock — created, read, deleted. `Assembly` must name
    FESPP's custom assembly or a /data-selector matches nothing (the same
    trap as PdcScene.reconcile)."""
    eb = None
    try:
        eb = pvsimple.ExtractBlock(Input=shared_source)
        try:
            eb.Assembly = "Assembly"
        except Exception:
            pass
        eb.Selectors = [selector]
        eb.UpdatePipeline()
        data = sm.Fetch(eb)
        if data is None:
            return None
        it = data.NewIterator() if hasattr(data, "NewIterator") else None
        if it is None:
            return data
        it.InitTraversal()
        while not it.IsDoneWithTraversal():
            leaf = it.GetCurrentDataObject()
            if leaf is not None and getattr(leaf, "GetNumberOfPoints", lambda: 0)():
                return leaf
            it.GoToNextItem()
        return None
    except Exception:
        return None
    finally:
        if eb is not None:
            try:
                pvsimple.Delete(eb)
            except Exception:
                pass


def _ring_path(ds):
    """`[[md|None, tvd, x, y]]` — where the hole is at each frame node: the
    centres of a log tube's rings (see `_ring_samples`), any log of the well
    will do."""
    if ds is None or not hasattr(ds, "GetPoints"):
        return []
    n = ds.GetNumberOfPoints()
    sides = ds.GetNumberOfCells()
    if not n or not sides or n % sides:
        sides = 1
    fd = ds.GetFieldData()
    md = fd.GetArray("MD") if fd is not None else None
    if md is not None and md.GetNumberOfTuples() != n // sides:
        md = None
    try:
        from vtkmodules.util.numpy_support import vtk_to_numpy
        rings = vtk_to_numpy(ds.GetPoints().GetData()).astype(float).reshape(n // sides, sides, 3).mean(axis=1)
    except Exception as exc:
        print("[fespp] well-log: the hole's X and Y not read:", exc, flush=True)
        return []
    return [[float(md.GetTuple1(i)) if md is not None else None, -float(r[2]), float(r[0]), float(r[1])]
            for i, r in enumerate(rings)]


def _ring_samples(ds, array_name):
    """`[(value, tvd, md|None)]` — one entry per frame node, read off the tube.

    The tube repeats every frame node `nSides` times; `nSides` is derived from
    the cell count (each side is one strip running the full length) rather than
    hard-coded, so a change to SetNumberOfSides on the C++ side cannot silently
    decimate the log by an unknown factor.

    THE DEPTH IS THE RING'S MEAN Z, NOT ITS FIRST POINT. A ring's points sit
    on the tube SURFACE, at a radius the log value drives
    (VaryRadiusByScalar): on a deviated hole a ring spans tens of metres of
    Z, its first point sits far off the trajectory, and that offset moves
    with the value — a first-point "depth" goes back up while the hole goes
    down. The mean of a closed circular ring is its centre, so it IS the
    trajectory point (it agrees with the markers' own depth), and the
    vertical thicknesses are integrated on it.

    GAPS: a NaN sample cannot survive as NaN in that array — it drives the
    tube's VaryRadiusByScalar and a NaN radius destroys the geometry — so FESPP
    writes it as NEGATIVE ZERO. Numerically that is 0, which is why the 3D view
    is unaffected, but its sign recovers the gaps exactly, even on a discrete
    log whose 0 is a real value. The C++ also ships how many gaps it wrote: a
    negative zero is a gap only on a block that counted some (the one rule,
    engine/ranges.no_value), and the count is CHECKED rather than trusted — a
    pipeline that erased the sign leaves fewer gaps than declared, which is
    said."""
    from fespp_on_trame.engine import ranges
    if ds is None:
        return []
    n = ds.GetNumberOfPoints()
    sides = ds.GetNumberOfCells()
    if not n or not sides or n % sides:
        sides = 1                       # not a tube (or an unexpected shape)
    pd = ds.GetPointData()
    arr = pd.GetArray(array_name) if pd is not None else None
    if arr is None:
        return []
    declared = ranges.gap_count(ds, array_name)
    fd = ds.GetFieldData()

    # The TRUE measured depth, when the plugin ships it: an "MD" field array,
    # one value per frame node. Each sample carries BOTH depths — geometry
    # TVD (-Z) and MD (None when absent) — because the axis is chosen per
    # WELL, downstream, once every curve and top has answered: a well mixing
    # the two axes would be worse than either alone.
    md = fd.GetArray("MD") if fd is not None else None
    if md is not None and md.GetNumberOfTuples() != n // sides:
        md = None

    # The ring's Z column, read ONCE as an array instead of one GetPoint call
    # per point: the centreline costs `sides` reads per sample, hundreds of
    # thousands of calls for one channel, and this loop runs again for every
    # payload build and every value read through `property_values`. Widened
    # to double so the per-ring sum below adds exactly the doubles GetPoint
    # would have returned, in the same order — the same number, not merely a
    # close one, because the harness asserts the centreline is monotonic to
    # the last bit. None when the array cannot be had: the loop falls back.
    z_col = None
    try:
        from vtkmodules.util.numpy_support import vtk_to_numpy
        z_col = vtk_to_numpy(ds.GetPoints().GetData())[:, 2].astype(float)
        if len(z_col) != n:
            z_col = None
    except Exception:
        z_col = None

    out = []
    for i in range(n // sides):
        j = i * sides
        try:
            if arr.GetNumberOfComponents() > 1:
                # a vector log: its magnitude, the colouring's own default
                value = math.sqrt(sum(c * c for c in arr.GetTuple(j)))
            else:
                value = arr.GetTuple1(j)
            z = float(sum(z_col[j:j + sides]) / sides) if z_col is not None \
                else sum(ds.GetPoint(j + k)[2] for k in range(sides)) / sides
            mdv = float(md.GetTuple1(i)) if md is not None else None
        except Exception:
            continue
        out.append((float(value), -z, mdv))

    # A gap is KEPT, valueless: dropping the sample would let the renderer
    # join the samples either side with a straight segment across a stretch
    # that has no data at all. `None` reaches the client as JSON null and
    # d3.line().defined() breaks the curve there, which is the truth; the
    # statistics read it as NaN, a value missing.
    import numpy as np
    gap = ranges.no_value(np.fromiter((v for v, _d, _m in out), dtype=float, count=len(out)),
                          declared)
    out = [(None if g else v, d, m) for (v, d, m), g in zip(out, gap)]
    gaps = int(gap.sum())
    if declared and declared != gaps:
        print(f"[fespp] well-log: {array_name} declares {declared} gap(s) but "
              f"{gaps} survived the pipeline — curve may show gaps as zeros",
              flush=True)
    return out


def _decimate(samples, limit=MAX_SAMPLES):
    """Every k-th sample, keeping the last so the curve still reaches bottom."""
    n = len(samples)
    if n <= limit:
        return samples
    step = (n + limit - 1) // limit
    kept = samples[::step]
    if kept and kept[-1] != samples[-1]:
        kept.append(samples[-1])
    return kept


def _marker_depth(ds):
    """(tvd, md|None) — the disk/sphere is centred on its depth, so TVD is
    the middle of its Z bounds; the MD, when the plugin ships it, is a
    one-tuple "MD" field array. Both returned: the axis is a per-well
    decision made by the caller."""
    if ds is None:
        return None
    try:
        bounds = ds.GetBounds()
        tvd = -((bounds[4] + bounds[5]) / 2.0)
    except Exception:
        return None
    md = None
    try:
        fd = ds.GetFieldData()
        arr = fd.GetArray("MD") if fd is not None else None
        if arr is not None and arr.GetNumberOfTuples():
            md = float(arr.GetTuple1(0))
    except Exception:
        md = None
    return (tvd, md)


# Kinds whose values span orders of magnitude: a linear track shows one spike
# and a flat line. Matched on the kind title FESPP puts on the assembly.
_LOG_SCALE_KINDS = ("permeability", "resistivity", "conductivity")


def _wants_log_scale(kind):
    k = (kind or "").lower()
    return any(w in k for w in _LOG_SCALE_KINDS)


def _attr(tree, node_id, name):
    asm = tree._data_assembly
    if asm is None or node_id is None:
        return ""
    try:
        return asm.GetAttributeOrDefault(node_id, name, "") or ""
    except Exception:
        return ""


def _matches(tree, node_id, roles, kinds):
    """True when the node has one of `roles` — or, on a plugin that publishes
    no enum table, one of the class names in `kinds`."""
    role = tree.find_role(node_id)
    if role is not None:
        return role in roles
    return (tree.find_type(node_id) or "") in kinds


def _children_of_kinds(tree, node_id, roles, kinds):
    asm = tree._data_assembly
    if asm is None or node_id is None:
        return []
    return [cid for cid in asm.GetChildNodes(node_id)
            if _matches(tree, cid, roles, kinds)]


def _descendants_of_kinds(tree, node_id, roles, kinds):
    asm = tree._data_assembly
    if asm is None or node_id is None:
        return []
    out, stack, seen = [], [node_id], set()
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        if nid != node_id and _matches(tree, nid, roles, kinds):
            out.append(nid)
        stack.extend(asm.GetChildNodes(nid))
    return out


# ---- the marker frame's OWN stratigraphy: the band the file states -------
# A MARKER frame node of the tree (the plugin's role, or its class on a
# plugin without the enum table) — not the log frame of `_FRAME_ROLES`
_MARKER_FRAME_ROLES = ("WellboreMarkerFrame",)
_MARKER_FRAME_KINDS = ("WellboreMarkerFrameRepresentation", "WellboreMarkerFrame", "MarkerFrame")
_NO_COLOUR = "#c8c8c8"
_UNNAMED = "|UNNAMED|"       # the placeholder SKUA writes for an unnamed interpretation


def _frame_uuid(tree, node_id):
    """The uuid a frame node is named after ("_<uuid>")."""
    try:
        name = tree._data_assembly.GetNodeName(node_id) or ""
    except Exception as exc:
        print(f"[fespp] marker frame: no name for node {node_id}: {exc}", flush=True)
        return ""
    return name[1:] if name.startswith("_") else name


_MD_UOM_RE = re.compile(r"<(?:\w+:)?MdUom\b[^>]*>\s*([^<\s]+)\s*<")
# the reference to the local CRS the trajectory's geometry is written in, and
# the uuid inside it (UUID in RESQML 2.0.1, Uuid in 2.2)
_LOCAL_CRS_RE = re.compile(r"<(?:\w+:)?LocalCrs\b[^>]*>(.*?)</(?:\w+:)?LocalCrs>", re.S)
_REF_UUID_RE = re.compile(r"<(?:\w+:)?(?:UUID|Uuid)\b[^>]*>\s*([^<\s]+)\s*<")
# the MD datum a trajectory measures from (RESQML 2.0.1), then, in the
# datum's own XML, what it is ("kelly bushing", "rotary table"...) and the
# vertical coordinate of its location
_MD_DATUM_RE = re.compile(r"<(?:\w+:)?MdDatum\b[^>]*>(.*?)</(?:\w+:)?MdDatum>", re.S)
_MD_REFERENCE_RE = re.compile(r"<(?:\w+:)?MdReference\b[^>]*>\s*([^<]*?)\s*<")
_COORDINATE3_RE = re.compile(r"<(?:\w+:)?Coordinate3\b[^>]*>\s*([^<\s]+)\s*<")


def _md_datum(repo_query, shared, tag, trajectory_xml):
    """``{"ref", "tvd"}`` of the MD datum a trajectory measures from: its
    MdReference, and its true vertical depth counted as the samples' is —
    the global Z of its location, negated on an elevation CRS (the plugin
    negates a depth-oriented Z and a TVD is the drawn -Z). None when the
    trajectory names no readable datum, "tvd" None when the datum's CRS
    cannot be read."""
    ref = _MD_DATUM_RE.search(trajectory_xml)
    uuid = _REF_UUID_RE.search(ref.group(1)) if ref else None
    xml = (repo_query.object_xml(shared, uuid.group(1), cache_tag=tag) if uuid else "") or ""
    kind = _MD_REFERENCE_RE.search(xml)
    if not kind:
        return None
    z = _COORDINATE3_RE.search(xml)
    crs = _LOCAL_CRS_RE.search(xml)
    crs_uuid = _REF_UUID_RE.search(crs.group(1)) if crs else None
    fields = repo_query.object_fields(shared, crs_uuid.group(1), cache_tag=tag) if crs_uuid else {}
    tvd = None
    if z and fields.get("depth_oriented") in ("true", "false"):
        global_z = float(z.group(1)) + float(fields.get("origin_z") or 0.0)
        tvd = global_z if fields["depth_oriented"] == "true" else -global_z
    return {"ref": kind.group(1), "tvd": tvd}


def _depth_refs(shared, tree, wid, depth_crs=None):
    """``(md unit, tvd unit, md datum, xy unit)`` of a well, "" or None for what
    nothing states: its trajectory's MdUom, the vertical unit of the local
    CRS its geometry is written in — the TVD is the drawn geometry's depth,
    so it counts in that unit — and its MD datum (`_md_datum`). `depth_crs`
    (the depth CRS the 3D views letter their Z with) answers for the TVD
    when the trajectory names no readable CRS. Read over the plugin's query
    channel."""
    from fespp_on_trame.engine import geo
    md_unit, own_crs, datum = "", None, None
    try:
        from fespp_on_trame.engine import repo_query
        if shared is not None and repo_query.has_channel(shared):
            tag = repo_query.tag(shared)
            for tid in _descendants_of_kinds(tree, wid, _TRAJECTORY_ROLES, _TRAJECTORY_KINDS):
                uuid = _uuid_of(tree, tid)
                xml = (repo_query.object_xml(shared, uuid, cache_tag=tag) if uuid else "") or ""
                found = _MD_UOM_RE.search(xml)
                if found and not md_unit:
                    md_unit = found.group(1)
                ref = _LOCAL_CRS_RE.search(xml)
                crs = _REF_UUID_RE.search(ref.group(1)) if ref else None
                if crs and own_crs is None:
                    own_crs = geo.crs_info_from_fields(
                        repo_query.object_fields(shared, crs.group(1), cache_tag=tag))
                if datum is None:
                    datum = _md_datum(repo_query, shared, tag, xml)
                if md_unit and own_crs is not None and datum is not None:
                    break
    except Exception as exc:
        print(f"[fespp] well log: no depth unit or MD datum for node {wid}: {exc}", flush=True)
    # the trajectory's own CRS has the last word, even when it declares no unit
    crs = own_crs if own_crs is not None else depth_crs
    return md_unit, geo.depth_unit(crs), datum, geo.xy_unit(crs)


# the (MD, TVD) pairs a well's TVD column is drawn from, at most
MD_TVD_POINTS = 400


def md_tvd(full):
    """``[[md, tvd]]`` along the well, by increasing MD, from every sample of
    every curve (`_full`): what puts a TVD beside each MD of the drawn axis."""
    pairs = sorted({(d, tv) for samples in (full or {}).values()
                    for _v, d, tv in _triples(samples) if tv is not None})
    if len(pairs) > MD_TVD_POINTS:
        # one pair per stretch of MD, not one in k of the pairs: a log read
        # every half metre would leave a log read every fifteen metres higher
        # up without a single pair, and the table would cross that stretch
        # in a straight line (148 m off on Volve 15/9-19 A)
        lo, hi = pairs[0][0], pairs[-1][0]
        width = (hi - lo) / (MD_TVD_POINTS - 1) or 1.0
        kept, last = [], None
        for d, tv in pairs:
            stretch = int((d - lo) / width)
            if stretch != last:
                kept.append((d, tv))
                last = stretch
        if kept[-1] != pairs[-1]:
            kept.append(pairs[-1])
        pairs = kept
    return [[d, tv] for d, tv in pairs]


def frame_bands(fields, columns=None):
    """The stratigraphic bands a marker frame STATES, in measured depth —
    ``[{name, kind, parent, color, top, bottom, uuid}]`` — from the plugin's
    ObjectFields of the frame (repo_query.object_fields): ``md``, the MD of
    every marker of the frame, in its order; ``unit.<i>``, the units the
    frame's occurrence interpretation lists, by index; ``interval_units``,
    the unit index of each interval between two consecutive markers
    ("null" where the file says none). Nothing is read off the marker
    titles, and a frame without the assignment gives []: the band is what
    the file says or nothing. Consecutive intervals of one unit are one
    band. The colour is the loaded column's for an entity of the same
    title, else grey."""
    try:
        md = [float(v) for v in (fields.get("md") or "").split(";") if v != ""]
    except (TypeError, ValueError) as exc:
        print(f"[fespp] marker frame: the MD values are not numbers ({exc}): no band", flush=True)
        return []
    raw = fields.get("interval_units") or ""
    if len(md) < 2 or not raw:
        return []
    units = {}
    for key, value in fields.items():
        if key.startswith("unit.") and key[5:].isdigit():
            uuid, _, title = str(value).partition("|")
            units[int(key[5:])] = (uuid, title)
    picks = []
    for v in raw.split(";"):
        v = v.strip()
        picks.append(int(v) if v.isdigit() else None)     # "null", "", a non-index: no unit
    colours = {}
    for col in columns or ():
        for e in col.get("entities") or ():
            if e.get("color") and e.get("name"):
                colours.setdefault(str(e["name"]).strip().lower(), e["color"])
    bands = []
    for i in range(min(len(picks), len(md) - 1)):
        index = picks[i]
        if index is None or index not in units:
            continue
        top, bottom = md[i], md[i + 1]
        if not bottom > top:
            continue
        uuid, title = units[index]
        if bands and bands[-1]["uuid"] == uuid and bands[-1]["bottom"] == top:
            bands[-1]["bottom"] = bottom          # one unit across several intervals
            continue
        # SKUA titles unit interpretations "|UNNAMED|" and names the feature:
        # the plugin hands the feature's name in that case (markerFrameFields);
        # the placeholder itself, from an older plugin, is no name
        if title.strip() == _UNNAMED:
            title = ""
        name = title or uuid
        bands.append({"name": name, "kind": "unit", "parent": "", "uuid": uuid,
                      "color": colours.get(name.strip().lower(), _NO_COLOUR),
                      "top": top, "bottom": bottom})
    return bands


def _md_to_tvd(pairs, md):
    """Piecewise-linear MD -> TVD on the sorted (md, tvd) pairs of the
    well's markers, clamped at the ends."""
    if md <= pairs[0][0]:
        return pairs[0][1]
    if md >= pairs[-1][0]:
        return pairs[-1][1]
    i = bisect.bisect_right([p[0] for p in pairs], md)
    (m0, t0), (m1, t1) = pairs[i - 1], pairs[i]
    return t0 if m1 == m0 else t0 + (t1 - t0) * (md - m0) / (m1 - m0)


def _frame_strati(shared, tree, wid, well, raw_tops, columns):
    """``{"rock": [bands]}`` on the well's DRAWING axis, from the marker
    frames under the wellbore, or {} — the band the file states, or none.
    Each band also carries its two true vertical depths (what the
    thicknesses are summed on). A frame's bands are in MD: on a well drawn
    in TVD they are placed through its markers' own (md, tvd) pairs, and
    not at all when fewer than two markers carry an MD."""
    try:
        from fespp_on_trame.engine import repo_query
        if shared is None or not repo_query.has_channel(shared):
            return {}
        bands = []
        tag = repo_query.tag(shared)
        for fid in _descendants_of_kinds(tree, wid, _MARKER_FRAME_ROLES, _MARKER_FRAME_KINDS):
            uuid = _frame_uuid(tree, fid)
            if uuid:
                bands += frame_bands(repo_query.object_fields(shared, uuid, cache_tag=tag), columns)
        if not bands:
            return {}
        if well.get("depthRef") != "MD":
            pairs = sorted({(md, tvd) for tvd, md, _n in raw_tops if md is not None and tvd is not None})
            if len(pairs) < 2:
                print("[fespp] marker frame stratigraphy: the well is drawn in TVD and fewer than two"
                      " of its markers carry an MD: the band is not placed", flush=True)
                return {}
            bands = [dict(b, top=_md_to_tvd(pairs, b["top"]), bottom=_md_to_tvd(pairs, b["bottom"]))
                     for b in bands]
        to_tvd = _tvd_of_draw(well)
        for b in bands:
            b["top_tvd"] = to_tvd(b.get("top"))
            b["bottom_tvd"] = to_tvd(b.get("bottom"))
        return {"rock": bands}
    except Exception as exc:
        # never silently: a band that vanishes with no trace is unfindable
        print("[fespp] marker frame stratigraphy error:", exc, flush=True)
        return {}


def _strati_intervals(columns, tops, to_tvd=None):
    """The stratigraphic lanes laid onto a well's `tops`, or {} on failure.

    A stratigraphy failure must never cost the user their logs, so any
    error is printed and swallowed. The bands are laid onto the DRAWING
    axis, as the panel draws them; each
    also carries the true vertical depth of its two bounds, through `to_tvd`
    — that is what the thicknesses are summed on."""
    if not columns or not tops:
        return {}
    try:
        from fespp_on_trame.engine import stratigraphy
        lanes = stratigraphy.intervals_for_tops(columns, tops)
        if to_tvd is not None:
            for bands in lanes.values():
                for b in bands:
                    b["top_tvd"] = to_tvd(b.get("top"))
                    b["bottom_tvd"] = to_tvd(b.get("bottom"))
        return lanes
    except Exception as exc:
        # never silently: a band that vanishes with no trace is unfindable,
        # and the logs are the only place this can surface
        print("[fespp] stratigraphy band error:", exc, flush=True)
        return {}


def _percentile(sorted_values, q):
    """Nearest-rank percentile on an already sorted list; q in [0, 100].

    Ties go UP (a rank of 4.5 takes index 5), written out rather than left to
    ``round()``: Python rounds halves to the even neighbour, so P50 of ten
    values would silently be the lower one — defensible, but nobody expects
    it, and the number must not depend on a language convention."""
    n = len(sorted_values)
    if n == 0:
        return None
    k = int(q / 100.0 * (n - 1) + 0.5)
    return sorted_values[max(0, min(n - 1, k))]


def _triples(samples):
    """``[(value, draw, tvd|None)]`` over a curve's samples.

    A sample is ``[value, draw, tvd]``; one of length 2 is the fixture form,
    where the single depth IS the vertical. A sample with no drawing depth is
    dropped."""
    out = []
    for s in samples or []:
        if s is None or len(s) < 2:
            continue
        d = s[1]
        if d is None:
            continue
        t = s[2] if len(s) > 2 else d
        out.append((s[0], float(d), None if t is None else float(t)))
    return out


def _tvd_pairs(samples):
    """``[(value, tvd)]`` — the INTEGRATION axis of every sample that has
    one (see `_triples`). What every thickness is summed on."""
    return [(v, t) for v, _d, t in _triples(samples) if t is not None]


def _tvd_of_draw(well):
    """draw depth → true vertical depth on this well.

    A top's own pair of depths when the draw depth is one of the picks
    (every bound
    `stratigraphy.intervals_for_tops` returns is), else linear between the
    curve samples either side, else None — the zone then says it has no
    vertical thickness rather than inventing one."""
    exact = {}
    for tp in well.get("tops") or []:
        if tp.get("depth") is not None and tp.get("tvd") is not None:
            exact.setdefault(float(tp["depth"]), float(tp["tvd"]))
    pairs = sorted({(d, t) for pts in (well.get("_full") or {}).values()
                    for _v, d, t in _triples(pts) if t is not None})
    draws = [d for d, _t in pairs]

    def at(d):
        if d is None:
            return None
        d = float(d)
        if d in exact:
            return exact[d]
        if not pairs:
            return None
        i = bisect.bisect_left(draws, d)
        if i == 0:
            return pairs[0][1] if draws[0] == d else None
        if i >= len(pairs):
            return pairs[-1][1] if draws[-1] == d else None
        (d0, t0), (d1, t1) = pairs[i - 1], pairs[i]
        if d1 == d0:
            return t0
        return t0 + (t1 - t0) * (d - d0) / (d1 - d0)
    return at


def zone_intervals(well):
    """The depth intervals to aggregate over, as ``[{name, color, top,
    bottom, top_tvd, bottom_tvd}]``, and where they came from.

    The marker frame's own stratigraphy gives the ROCK lane (`frame_bands`:
    the unit of each interval between its markers, as the file states it),
    which is what "per zone" means to a petrophysicist. Without it the best
    available structure is the markers themselves: each pair of consecutive picks bounds a zone named
    after BOTH its picks ("TopA → TopB") — named after its top alone, it read
    as a formation, and silently grew past it when the next marker was
    unchecked. The payload says which source applies.

    Each interval carries FOUR bounds: `top` / `bottom` on the well's drawing
    axis (the band, the table's depth columns, the ordering) and `top_tvd` /
    `bottom_tvd` on the vertical (every thickness). On a payload of the
    fixture form, where a well carries one depth only, the two coincide."""
    rock = ((well.get("strati") or {}).get("rock")) or []
    if rock:
        return [{"name": r["name"], "color": r.get("color"),
                 "top": r["top"], "bottom": r["bottom"],
                 "top_tvd": r.get("top_tvd", r["top"]),
                 "bottom_tvd": r.get("bottom_tvd", r["bottom"])}
                for r in rock], "frame"
    picks = sorted([tp for tp in (well.get("tops") or [])
                    if tp.get("depth") is not None], key=lambda tp: tp["depth"])
    out = []
    for a, b in zip(picks, picks[1:]):
        if b["depth"] > a["depth"]:
            out.append({"name": f"{a['name']} → {b['name']}", "color": None,
                        "top": a["depth"], "bottom": b["depth"],
                        "top_tvd": a.get("tvd", a["depth"]),
                        "bottom_tvd": b.get("tvd", b["depth"])})
    return out, "markers"


def up_hole_tvd(samples):
    """The metres of hole whose true vertical depth DECREASES along it.

    A re-entry, or an upward horizontal stretch. Usually zero; non-zero, it
    must be disclosed, because a vertical thickness integrated over such a
    stretch subtracts instead of adding."""
    up, prev = 0.0, None
    for _v, _d, t in _triples(samples):
        if t is None:
            continue
        if prev is not None and t < prev:
            up += prev - t
        prev = t
    return up


# ---- cutoffs → pay flag → net-to-gross ------------------------------------
# A cutoff is `{curve, op, value}`; pay is where EVERY cutoff holds. The
# panel edits the rules, this side evaluates them on the samples.

# the two equalities are for the discrete logs — a facies code, a zone
# index — where "facies = 3" is the rule; on a continuous log they are of
# little use and the widget says so in the operator's tooltip
_OPS = {
    ">=": lambda v, t: v >= t, "<=": lambda v, t: v <= t,
    ">": lambda v, t: v > t, "<": lambda v, t: v < t,
    "=": lambda v, t: v == t, "≠": lambda v, t: v != t,
}


def _rules(cutoffs):
    """The usable rules of `cutoffs`: a curve name, a known operator and a
    numeric threshold. A half-typed rule is skipped, not an error — the
    editor sends the whole list whenever a field is completed."""
    out = []
    for r in cutoffs or []:
        try:
            out.append((str(r["curve"]), _OPS[str(r.get("op"))],
                        float(r["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _curves_of(well):
    """``{name: (kind, unit, samples)}`` over every track of the well."""
    out = {}
    full = well.get("_full") or {}
    for track in well.get("tracks") or []:
        for c in track.get("curves") or []:
            samples = full.get(c.get("name")) or c.get("samples")
            if samples:
                out[c.get("name")] = (track.get("kind") or "",
                                      c.get("unit") or "", samples)
    return out


def _step_hold(samples):
    """TRUE VERTICAL depth → the value of the last sample at or above it
    (None before the first sample, or when that sample is a gap).

    Sample-and-hold rather than interpolation: a cutoff is a threshold on
    what was MEASURED, and interpolating across a gap or a bed boundary
    manufactures values that were never logged."""
    pts = sorted(((d, v) for v, d in _tvd_pairs(samples)), key=lambda p: p[0])
    depths = [p[0] for p in pts]

    def at(d):
        i = bisect.bisect_right(depths, d) - 1
        if i < 0:
            return None
        v = pts[i][1]
        return None if v is None else float(v)
    return at


def _pay_spans(well, cutoffs):
    """``[(top_tvd, top_draw, bottom_tvd, bottom_draw)]`` — the pay
    stretches, each bound carrying BOTH of its depths.

    The flag is evaluated on the union of the rule curves' sample depths,
    each curve read sample-and-hold, on the TRUE VERTICAL axis — the one
    every thickness is summed on; the stretch from one depth to the next
    carries the flag of its top, so the last sample bounds the pay but adds
    no thickness. Every bound IS a sample depth, so the drawing depth of a
    bound is the one that sample already carries: read, never interpolated
    back. A rule on a curve the well lacks, or an undefined value (a gap,
    above the first sample), fails — pay is what every cutoff PROVES. The
    empty list of a missing curve is "not evaluable", not "no pay":
    `zone_stats` tells the two apart through `missing_rule_curves`."""
    rules = _rules(cutoffs)
    curves = _curves_of(well)
    if not rules or any(name not in curves for name, _op, _t in rules):
        return []
    readers = [(_step_hold(curves[name][2]), op, t) for name, op, t in rules]
    # vertical depth → the drawing depth of the sample sitting there. A well
    # that comes back up passes the same vertical depth twice and the first
    # one is kept; such a well is disclosed by `tvd_up_hole`.
    draw_of = {}
    for name, _op, _t in rules:
        for _v, d, t in _triples(curves[name][2]):
            if t is not None:
                draw_of.setdefault(t, d)
    depths = sorted(draw_of)
    out, start = [], None
    for d0 in depths[:-1]:
        ok = True
        for at, op, t in readers:
            v = at(d0)
            if v is None or not op(v, t):
                ok = False
                break
        if ok and start is None:
            start = d0
        elif not ok and start is not None:
            out.append((start, draw_of[start], d0, draw_of[d0]))
            start = None
    if start is not None:
        last = depths[-1]
        out.append((start, draw_of[start], last, draw_of[last]))
    return out


def pay_intervals(well, cutoffs):
    """The TRUE VERTICAL depth intervals where every rule holds, merged:
    ``[[top, bottom]]`` — what the net thickness is summed over. See
    `_pay_spans`; `pay_drawn` is the same pay on the drawing axis."""
    return [[a, b] for a, _da, b, _db in _pay_spans(well, cutoffs)]


def pay_drawn(well, cutoffs):
    """The same pay as `pay_intervals`, on the well's DRAWING axis:
    ``[[top, bottom]]`` — what the green band is shaded between.

    The band is scaled with `depth.min` / `depth.max`, which are drawing
    depths: shading it with the vertical intervals would put it hundreds of
    metres too shallow on a well drawn on measured depth, and clean off the
    track on a steeply deviated one. Every FIGURE stays vertical; only the
    drawing follows the drawing."""
    return [[da, db] for _a, da, _b, db in _pay_spans(well, cutoffs)]


def missing_rule_curves(well, cutoffs):
    """The rule curves ``well`` does not carry, in rule order — non-empty
    means the pay cannot be evaluated on this well: a multi-well panel
    offers every well's logs to the cutoff editor, and the well without the
    log must not read as a well without pay."""
    curves = _curves_of(well)
    out = []
    for name, _op, _t in _rules(cutoffs):
        if name not in curves and name not in out:
            out.append(name)
    return out


def absent_why(well, name):
    """Why ``name`` is not among the well's curves: ``"unticked"`` or
    ``"unreadable"`` when the well logs it (`build_payload` records both
    in ``absent``), else ``"unlogged"``. The panel words each: "not logged
    on this well" would be false for a channel that is merely unticked."""
    return ((well.get("absent") or {}).get(name) or {}).get("why") or "unlogged"


def _inside(pay):
    """true vertical depth → whether it falls in one of the (sorted,
    disjoint) pay intervals, top inclusive, bottom exclusive — the zone
    convention."""
    starts = [p[0] for p in pay]

    def inside(d):
        i = bisect.bisect_right(starts, d) - 1
        return i >= 0 and d < pay[i][1]
    return inside


def _kind_names(kind, words):
    """Whether a property kind names every word — "porosity", or "water" +
    "saturation". Kinds are FESPP's property-kind titles, so this is the
    RESQML semantics doing the work, not a mnemonic table."""
    k = (kind or "").lower()
    return all(w in k for w in words)


def _curves_of_kind(curves, *words):
    """Every curve whose track kind names every word, in track order, the
    FIRST being the one the summation reads."""
    return [name for name, (kind, _unit, _samples) in curves.items()
            if _kind_names(kind, words)]


def _absent_of_kind(absent, *words):
    """``{name: why}`` over the well's absent channels whose kind names
    every word — the porosity the panel would have read had it been ticked
    (or readable), which the report must name instead of "no porosity"."""
    return {name: a.get("why") for name, a in (absent or {}).items()
            if _kind_names(a.get("kind"), words)}


def summation_curves(well):
    """Which curves the summation report reads, and what else it could have
    taken: ``{phi, phi_candidates, phi_absent, sw, sw_candidates,
    sw_absent}`` — the porosity and water-saturation curve names (None when
    no kind names one), every curve whose kind matched, the pick first, and
    the absent channels of the kind with why (`absent_why`). A neutron
    porosity and an effective porosity both say "porosity", and the pick is
    the first in track order — so the report must SAY which one it took."""
    curves = _curves_of(well)
    absent = well.get("absent") or {}
    phi = _curves_of_kind(curves, "porosity")
    sw = _curves_of_kind(curves, "water", "saturation")
    return {"phi": phi[0] if phi else None, "phi_candidates": phi,
            "phi_absent": _absent_of_kind(absent, "porosity"),
            "sw": sw[0] if sw else None, "sw_candidates": sw,
            "sw_absent": _absent_of_kind(absent, "water", "saturation")}


def _fraction(unit):
    """v/v is the working unit; a curve declared in a percentage unit (%,
    p.u.) is scaled down — node_kinds holds the vocabulary."""
    from fespp_on_trame.engine import node_kinds
    return node_kinds.percent_factor(unit)


def _pore_thickness(curves, phi_name, sw_name, pay, top, bottom):
    """``(phi·h, phi·(1−Sw)·h)`` over the pay of ``[top, bottom)`` — the
    porosity-thickness and hydrocarbon pore thickness of the summation
    report — each None when its curve is not there. Piecewise on the sample
    depths, sample-and-hold like the flag itself. Every depth here is a TRUE
    VERTICAL one, `pay` and the bounds included: these are thicknesses of
    rock, not lengths of hole."""
    if phi_name is None:
        return None, None
    _k, u_phi, s_phi = curves[phi_name]
    phi_at, f_phi = _step_hold(s_phi), _fraction(u_phi)
    sw_at, f_sw = None, 1.0
    breaks = {d for _v, d in _tvd_pairs(s_phi)}
    if sw_name is not None:
        _k, u_sw, s_sw = curves[sw_name]
        sw_at, f_sw = _step_hold(s_sw), _fraction(u_sw)
        breaks |= {d for _v, d in _tvd_pairs(s_sw)}
    phih = 0.0
    hcph = 0.0 if sw_at is not None else None
    for a, b in pay:
        lo, hi = max(a, top), min(b, bottom)
        if hi <= lo:
            continue
        pts = sorted({lo, hi} | {d for d in breaks if lo < d < hi})
        for d0, d1 in zip(pts, pts[1:]):
            phi = phi_at(d0)
            if phi is None:
                continue
            phih += phi * f_phi * (d1 - d0)
            if sw_at is not None:
                sw = sw_at(d0)
                if sw is not None:
                    hcph += phi * f_phi * (1.0 - sw * f_sw) * (d1 - d0)
    return phih, hcph


def zone_stats(well, cutoffs=None):
    """Per-zone statistics of every curve of ``well``, on the samples whose
    TRUE VERTICAL depth falls in ``[top_tvd, bottom_tvd)``.

    Every thickness here is vertical: `thickness_tvd`, `net`, `phih` and
    `hcph` are metres of rock, `ntg` their ratio — never a length of hole,
    which on a deviated well overstates them by 1/cos(inclination). `top`
    and `bottom` stay on the drawing axis, for the band and the table.
    A zone whose two bounds have no usable vertical depth keeps its curves
    and says why in `tvd_na`, its thicknesses being None rather than wrong.

    Nearest-rank percentiles rather than interpolated ones: a zone can hold
    three samples, and an interpolated P10 of three values is a number
    nobody can defend. ``n`` is always there so the reader can weigh the rest.
    A curve with no sample in a zone is left out of that zone; a zone with no
    curve at all is kept, with its thickness — that is still information (and
    the net-to-gross work needs the gross).

    With ``cutoffs`` the zone also carries the summation report: ``net`` and
    ``ntg`` from the pay intervals, each curve's ``n_pay`` / ``mean_pay`` on
    the pay samples, and ``phih`` / ``hcph`` when a porosity — and a water
    saturation — curve can be told from its kind (`summation_curves`). A
    rule on a curve the well lacks makes every one of those None, with the
    missing names in ``pay_na``: not evaluable is not zero."""
    intervals, source = zone_intervals(well)
    missing = missing_rule_curves(well, cutoffs) if cutoffs else []
    pay = pay_intervals(well, cutoffs) if cutoffs else []
    in_pay = _inside(pay)
    curves_by_name = _curves_of(well)
    picks = summation_curves(well)
    phi_name, sw_name = picks["phi"], picks["sw"]
    zones = []
    for z in intervals:
        top, bottom = float(z["top"]), float(z["bottom"])
        top_tvd, bottom_tvd = z.get("top_tvd"), z.get("bottom_tvd")
        tvd_na = None
        if top_tvd is None or bottom_tvd is None:
            tvd_na = "the zone bounds have no true vertical depth on this well"
        elif float(bottom_tvd) - float(top_tvd) <= 0.0:
            tvd_na = ("the zone's two bounds sit at the same or an inverted"
                      " true vertical depth (a horizontal or re-entrant"
                      " section): no vertical thickness to sum")
        if tvd_na is None:
            top_tvd, bottom_tvd = float(top_tvd), float(bottom_tvd)
        curves = []
        for track in well.get("tracks") or []:
            for c in track.get("curves") or []:
                full_samples = (well.get("_full") or {}).get(c.get("name"))
                # the samples of the zone: selected on the VERTICAL, the
                # axis the zone is bounded on — or, when the zone has no
                # usable vertical bounds, on the axis it is drawn against,
                # so a horizontal section still reports its curves
                inz = [(float(v), d, t)
                       for v, d, t in _triples(full_samples or c.get("samples"))
                       if v is not None
                       and (top <= d < bottom if tvd_na
                            else (t is not None and top_tvd <= t < bottom_tvd))]
                if not inz:
                    continue
                vals = sorted(v for v, _d, _t in inz)
                n = len(vals)
                entry = {
                    "name": c.get("name"), "unit": c.get("unit"), "n": n,
                    "mean": sum(vals) / n, "min": vals[0], "max": vals[-1],
                    "p10": _percentile(vals, 10), "p50": _percentile(vals, 50),
                    "p90": _percentile(vals, 90),
                }
                if cutoffs and missing:
                    entry["n_pay"] = entry["mean_pay"] = None
                elif cutoffs:
                    pv = [v for v, _d, t in inz if t is not None and in_pay(t)]
                    entry["n_pay"] = len(pv)
                    entry["mean_pay"] = sum(pv) / len(pv) if pv else None
                curves.append(entry)
        zone = {
            "name": z["name"], "color": z.get("color"), "top": top,
            "bottom": bottom, "thickness": bottom - top, "source": source,
            "top_tvd": None if tvd_na else top_tvd,
            "bottom_tvd": None if tvd_na else bottom_tvd,
            "thickness_tvd": None if tvd_na else bottom_tvd - top_tvd,
            "tvd_na": tvd_na,
            "curves": curves,
        }
        if cutoffs:
            zone["pay_na"] = list(missing)
        if cutoffs and (missing or tvd_na):
            zone["net"] = zone["ntg"] = zone["phih"] = zone["hcph"] = None
        elif cutoffs:
            net = sum(max(0.0, min(b, bottom_tvd) - max(a, top_tvd))
                      for a, b in pay)
            zone["net"] = net
            zone["ntg"] = net / (bottom_tvd - top_tvd)
            zone["phih"], zone["hcph"] = _pore_thickness(
                curves_by_name, phi_name, sw_name, pay, top_tvd, bottom_tvd)
        zones.append(zone)
    return zones


def with_cutoffs(payload, cutoffs):
    """A NEW payload whose wells carry their pay and zones under `cutoffs`.

    Each well gets its pay intervals — ``pay`` on the DRAWING axis for the
    band, ``pay_tvd`` on the vertical for every figure — and zones rebuilt
    under ``cutoffs``, plus what the report must disclose: ``pay_na`` (the
    rule curves this well lacks — the pay band and every pay figure are not
    evaluable, see `zone_stats`), ``pay_na_why`` (each one's reason, see
    `absent_why`) and ``summation`` (the curves Φ·h and Φ(1−Sw)·h were read
    from, see `summation_curves`). The input is left untouched: it is built
    once from the checked channels and shared by every well-log panel, each
    with its own rules."""
    out = dict(payload)
    out["wells"] = []
    for w in payload.get("wells") or []:
        w2 = dict(w)
        # `pay` is DRAWN — the band lives on the drawing axis — and
        # `pay_tvd` is the very same pay on the axis the thicknesses are
        # summed on, for a reader who exports or probes the payload
        w2["pay"] = pay_drawn(w, cutoffs) if cutoffs else []
        w2["pay_tvd"] = pay_intervals(w, cutoffs) if cutoffs else []
        w2["zones"] = zone_stats(w, cutoffs)
        if cutoffs:
            w2["pay_na"] = missing_rule_curves(w, cutoffs)
            w2["pay_na_why"] = {n: absent_why(w, n) for n in w2["pay_na"]}
            w2["summation"] = summation_curves(w)
        out["wells"].append(w2)
    return out


_WELL_ROLES = ("Wellbore",)
_WELL_KINDS = ("Wellbore",)


def is_well(tree, node_id):
    """True when the node is a well's own row."""
    return _matches(tree, node_id, _WELL_ROLES, _WELL_KINDS)


def frame_channels(tree, node_id):
    """[(title, uom)] of the logs of the log frame at `node_id`, None when
    the node is no log frame."""
    if node_id is None or not _matches(tree, node_id, _FRAME_ROLES, _FRAME_KINDS):
        return None
    return [(tree.find_title(cid) or "", _attr(tree, cid, "uom") or "")
            for cid in _children_of_kinds(tree, node_id, _CHANNEL_ROLES, _CHANNEL_KINDS)]


def log_channels(tree):
    """Every log channel of the tree, by well: [(well title, channel uuid,
    channel title, uom)] — what the tree says of them (the plugin's "uom"
    attribute), nothing read. The time-depth model's pre-fill picks the
    time logs out of it (engine/time_depth_prefill)."""
    out = []
    if tree is None or getattr(tree, "_data_assembly", None) is None:
        return out
    for nid, _children in tree.iter_nodes():
        if not _matches(tree, nid, _WELL_ROLES, _WELL_KINDS):
            continue
        well = tree.find_title(nid) or ""
        for fid in _descendants_of_kinds(tree, nid, _FRAME_ROLES, _FRAME_KINDS):
            for cid in _children_of_kinds(tree, fid, _CHANNEL_ROLES, _CHANNEL_KINDS):
                uuid = _uuid_of(tree, cid)
                if uuid:
                    out.append((well, uuid, tree.find_title(cid) or "", _attr(tree, cid, "uom")))
    return out


def well_trajectories(tree):
    """Every well's trajectory in the tree: [(well title, trajectory uuid)],
    what the tree says of them, nothing read."""
    out = []
    if tree is None or getattr(tree, "_data_assembly", None) is None:
        return out
    for nid, _children in tree.iter_nodes():
        if not _matches(tree, nid, _WELL_ROLES, _WELL_KINDS):
            continue
        well = tree.find_title(nid) or ""
        for tid in _descendants_of_kinds(tree, nid, _TRAJECTORY_ROLES, _TRAJECTORY_KINDS):
            uuid = _uuid_of(tree, tid)
            if uuid:
                out.append((well, uuid))
                break
    return out


def marker_frames(tree):
    """Every marker frame of the tree, by well: [(well title, frame uuid,
    frame title, [marker titles])] — what the tree says of them, nothing
    read. The time-depth model's pre-fill reads their markers on the
    time horizons (engine/time_depth_prefill)."""
    out = []
    if tree is None or getattr(tree, "_data_assembly", None) is None:
        return out
    for nid, _children in tree.iter_nodes():
        if not _matches(tree, nid, _WELL_ROLES, _WELL_KINDS):
            continue
        well = tree.find_title(nid) or ""
        for fid in _descendants_of_kinds(tree, nid, _MARKER_FRAME_ROLES, _MARKER_FRAME_KINDS):
            uuid = _uuid_of(tree, fid)
            if uuid:
                titles = [tree.find_title(m) or "" for m in
                          _children_of_kinds(tree, fid, _MARKER_ROLES, _MARKER_KINDS)]
                out.append((well, uuid, tree.find_title(fid) or "", titles))
    return out


def _uuid_of(tree, node_id):
    """The uuid a node's path ends with ("_<uuid>"), "" for a folder."""
    leaf = (tree.find_path(node_id) or "").rsplit("/", 1)[-1]
    return leaf[1:] if leaf.startswith("_") else ""


def _read_lazy_channels(tree, shared, well_paths):
    """The frames and channels of these wells that a lazy ETP load left on
    the store ("lazy" = "1"), read in ONE request: an unticked channel is
    reported by its kind ("the porosity is not ticked"), and a kind the
    store has not sent yet would make it "not logged"."""
    if shared is None:
        return
    uuids = []
    for well_path in well_paths:
        wid = tree.find_node_id(well_path)
        if wid is None:
            continue
        for fid in _descendants_of_kinds(tree, wid, _FRAME_ROLES, _FRAME_KINDS):
            for nid in [fid] + list(_children_of_kinds(tree, fid, _CHANNEL_ROLES, _CHANNEL_KINDS)):
                if _attr(tree, nid, "lazy") != "1":
                    continue
                path = tree.find_path(nid) or ""
                leaf = path.rsplit("/", 1)[-1]
                if leaf.startswith("_"):
                    uuids.append(leaf[1:])
    if not uuids:
        return
    from fespp_on_trame.engine import repo_query
    try:
        repo_query.lazy_fetch(shared, 3000, 0, uuids)
    except Exception as exc:
        print("[fespp] well logs: the channels on the store could not be read:", exc, flush=True)


def build_payload(tree, source_registry, well_paths, selected_paths,
                  flatten_on=None, strati_columns=None, synthetics=None,
                  depth_crs=None):
    """`{wells, markers, flattenOn}` for the panel, or the empty payload.

    `well_paths`     — the wellbores sent to the panel (ui_welllog_wells).
    `selected_paths` — the CHECKED set; a channel outside it has no loaded data.
    `strati_columns` — the stratigraphic columns (engine/stratigraphy), for
        the COLOURS of the band only. The band itself (`strati`) is what the
        wellbore's marker frame states — the unit of each interval between
        its markers, read over the plugin's query channel (`frame_bands`) —
        or nothing: laying the column onto the checked markers' titles was a
        guess, and is gone.
    `synthetics`     — `{well_path: [{name, unit, kind, samples}]}`, grid
        properties sampled along the trajectory (engine/trajectory_sampling);
        admitted like channels, so each lands in the track of its kind, on the
        same value scale as the measured log it is compared with.
    `depth_crs`      — the CRS info (engine/geo) of the loaded data's depth
        domain: the unit of a well's TVD when its trajectory names no CRS
        that can be read (`_depth_refs`).
    """
    empty = {"wells": [], "markers": [], "flattenOn": None}
    if not well_paths:
        return empty
    try:
        shared = source_registry.shared_source()
    except Exception:
        shared = None
    if shared is None:
        return empty

    checked = set(selected_paths or [])
    wells, marker_names = [], []

    # ---- pass 1: read every well's checked channels --------------------
    # Comparing the SAME log across two wells is the whole point of the panel,
    # and it needs two things a per-well build cannot give: the log must sit in
    # the same COLUMN in every well, and it must be drawn against the same
    # VALUE SCALE — otherwise two identical logs have different shapes and two
    # different logs line up. So collect everything first, then emit.
    per_well, log_order, log_range = [], [], {}
    log_kind, log_unit = {}, {}          # log NAME -> its kind / its unit
    synthetic = set()                    # log NAMEs sampled from a grid
    _read_lazy_channels(tree, shared, well_paths)
    for well_path in well_paths:
        wid = tree.find_node_id(well_path)
        if wid is None:
            continue
        raw, full = {}, {}
        # The channels this well logs that yield no curve, by title, with
        # their kind and why — unticked, or ticked with no readable sample.
        # Channels are ticked per wellbore, so in a multi-well panel a log
        # ticked on one well is plainly unticked on the next: the report
        # must say "not ticked", never "not logged", and name the porosity
        # it would have read.
        absent = {}
        hole = []
        for fid in _descendants_of_kinds(tree, wid, _FRAME_ROLES, _FRAME_KINDS):
            for cid in _children_of_kinds(tree, fid, _CHANNEL_ROLES, _CHANNEL_KINDS):
                cpath = tree.find_path(cid)
                if not cpath:
                    continue
                title = tree.find_title(cid) or "channel"
                if cpath not in checked:
                    absent.setdefault(title, {
                        "kind": _attr(tree, cid, "propertyKind"),
                        "why": "unticked"})
                    continue
                block = _fetch_block(shared, cpath)
                samples = _ring_samples(block, make_valid_vtk_name(title))
                if samples and not hole:
                    hole = _decimate(_ring_path(block))
                if not samples:
                    absent.setdefault(title, {
                        "kind": _attr(tree, cid, "propertyKind"),
                        "why": "unreadable"})
                    continue
                # What FESPP reports about this log: its kind groups it
                # into a track with the logs of the same nature, its unit
                # labels that track. A file with neither still works — the log
                # lands in an "other" track under its own name.
                log_kind.setdefault(title, _attr(tree, cid, "propertyKind"))
                log_unit.setdefault(title, _attr(tree, cid, "uom"))
                # a gap keeps its depth but carries no value (JSON null);
                # each point rides with BOTH depths — [value, tvd, md|None] —
                # the axis is chosen per well once everything is read
                pts_full = [[None if v is None else float(v), float(d),
                             None if m is None else float(m)]
                            for v, d, m in samples]
                pts = _decimate(pts_full)
                real = [p[0] for p in pts if p[0] is not None]
                if not real:
                    # nothing but gaps — no curve to draw
                    absent.setdefault(title, {
                        "kind": _attr(tree, cid, "propertyKind"),
                        "why": "unreadable"})
                    continue
                raw[title] = pts
                full[title] = pts_full
                if title not in log_range:
                    log_order.append(title)
                    log_range[title] = [real[0], real[0]]
                r = log_range[title]
                for v in real:
                    if v < r[0]:
                        r[0] = v
                    if v > r[1]:
                        r[1] = v
        for sc in (synthetics or {}).get(well_path) or []:
            title = sc.get("name") or "grid"
            pts_full = [[None if v is None else float(v), float(d),
                         None if m is None else float(m)]
                        for v, d, m in sc.get("samples") or []]
            pts = _decimate(pts_full)
            real = [p[0] for p in pts if p[0] is not None]
            if not real:
                continue                # the hole never enters the grid
            raw[title] = pts
            full[title] = pts_full
            synthetic.add(title)
            log_kind.setdefault(title, sc.get("kind"))
            log_unit.setdefault(title, sc.get("unit"))
            if title not in log_range:
                log_order.append(title)
                log_range[title] = [min(real), max(real)]
            else:
                r = log_range[title]
                r[0], r[1] = min(r[0], min(real)), max(r[1], max(real))
        # a title read from one frame is not absent because another frame
        # of the same well carries it unticked
        absent = {t: a for t, a in absent.items() if t not in raw}
        per_well.append((wid, well_path, raw, full, absent))

    # a constant log keeps its true span ([v, v]) — the header says so; the
    # value scale is the TRACK's, widened below when every curve of the
    # track is flat, so D3 never meets a zero-width domain

    # Logs of the SAME kind share a track, the way a log display is laid out:
    # the two saturations together, the three impedances together. Track order
    # follows each kind's first appearance in the global log order, so it is
    # the same in every well. A log FESPP could not classify keeps a track of
    # its own rather than landing in a meaningless catch-all.
    track_order, track_logs = [], {}
    for title in log_order:
        key = log_kind.get(title) or title
        if key not in track_logs:
            track_order.append(key)
            track_logs[key] = []
        track_logs[key].append(title)

    # ---- pass 2: emit, the same tracks in the same order in every well ----
    for w_i, (wid, well_path, raw, full, absent) in enumerate(per_well):
        # --- tops first: the AXIS decision needs them ------------------------
        # (tvd, md|None, name) per checked marker under this wellbore
        raw_tops = []
        for mid in _descendants_of_kinds(tree, wid, _MARKER_ROLES, _MARKER_KINDS):
            mpath = tree.find_path(mid)
            if not mpath or mpath not in checked:
                continue
            got = _marker_depth(_fetch_block(shared, mpath))
            if got is None:
                continue
            raw_tops.append((got[0], got[1], tree.find_title(mid) or "marker"))

        # ONE depth axis per well: true MD if — and only if — every curve
        # sample AND every top carries one; otherwise everything stays on
        # geometry TVD. Mixing the two on one well would misplace either the
        # curves or the tops on every deviated trajectory.
        use_md = bool(raw) or bool(raw_tops)
        for pts in raw.values():
            if any(p[2] is None for p in pts):
                use_md = False
                break
        if use_md:
            use_md = all(t[1] is not None for t in raw_tops)
        di = 2 if use_md else 1          # which slot of [value, tvd, md]

        tracks, dmin, dmax = [], None, None
        for key in track_order:
            titles = track_logs[key]
            units = [log_unit.get(t) for t in titles if log_unit.get(t)]
            curves = []
            for title in titles:
                pts3 = raw.get(title)
                # drawn in MD, each sample also carries its TVD: the panel
                # can lay the well out on the vertical
                pts = ([[p[0], p[2], p[1]] if use_md else [p[0], p[1]] for p in pts3]
                       if pts3 else [])
                for s in pts:
                    d = s[1]
                    dmin = d if dmin is None else min(dmin, d)
                    dmax = d if dmax is None else max(dmax, d)
                curves.append({
                    "name": title,
                    "color": color_for_index(log_order.index(title)),
                    "unit": log_unit.get(title, ""),
                    "range": list(log_range[title]),
                    # A well that lacks this log keeps its slot in the track,
                    # empty: the header must still name it, and the curve
                    # colours must not shift from one well to the next.
                    "samples": pts,
                    "missing": not pts,
                    # sampled from a grid, not measured: drawn dashed
                    "synthetic": title in synthetic,
                })
            # ONE value scale per track: the span of every curve of the kind,
            # every well included (`log_range` is read across the wells). A
            # synthetic log sampled from the grid is then drawn on the very
            # scale of the measured log beside it, which is the point of
            # drawing it there; each curve keeps its own `range` for the
            # header to say what it spans.
            spans = [c["range"] for c in curves
                     if c["range"] and c["range"][0] is not None
                     and c["range"][1] is not None]
            track_range = ([min(r[0] for r in spans), max(r[1] for r in spans)]
                           if spans else [0.0, 1.0])
            if track_range[0] == track_range[1]:
                # every curve of the track is constant: a zero-width domain
                # maps every sample to NaN and the panel comes up blank
                track_range = [track_range[0] - 0.5, track_range[1] + 0.5]
            tracks.append({
                "kind": key,
                "unit": units[0] if units else "",
                "range": track_range,
                # a decade-spanning kind is unreadable on a linear axis, and a
                # non-positive sample cannot be placed on a log one
                "logScale": bool(_wants_log_scale(key)) and all(
                    s[0] > 0 for c in curves for s in c["samples"]
                    if s[0] is not None),
                "curves": curves,
            })

        tops = []
        for tvd, mdv, name in raw_tops:
            depth = mdv if use_md else tvd
            # both depths: `depth` places the pick on the drawn axis, `tvd`
            # bounds the zone on the axis the thicknesses are summed on
            tops.append({"name": name, "depth": depth, "tvd": tvd})
            if name not in marker_names:
                marker_names.append(name)
            dmin = depth if dmin is None else min(dmin, depth)
            dmax = depth if dmax is None else max(dmax, depth)

        # `tracks` is never empty once ANY well has a log — every well carries
        # the full track set. A well contributes only if it has real data.
        if not raw and not tops:
            continue                    # nothing checked for this well yet
        if not raw:
            tracks = []
        if dmin is not None and dmax is not None and dmin == dmax:
            dmax = dmin + 1.0           # a zero-height track draws nothing
        md_unit, tvd_unit, md_datum, xy_unit = _depth_refs(shared, tree, wid, depth_crs)
        # the wellhead: the shallowest point of the hole, its easting and
        # northing in the well's header (the manager, 12/11)
        top = min((p for p in hole if p[1] is not None), key=lambda p: p[1], default=None)
        well = {
            "name": tree.find_title(wid) or well_path.rsplit("/", 1)[-1],
            "color": color_for_index(w_i),
            "depthRef": "MD" if use_md else "TVD",
            # the unit of the drawn axis, and of the TVD whichever is drawn
            "depthUnit": md_unit if use_md else tvd_unit,
            "tvdUnit": tvd_unit,
            # where the measured depths count from: the tracks start there
            "mdDatum": md_datum,
            # where the hole is, [md|None, tvd, x, y]
            "hole": hole,
            # the wellhead's easting and northing, and their unit
            "head": [top[2], top[3]] if top is not None else None,
            "xyUnit": xy_unit,
            # the axis every thickness is summed on, whatever is drawn
            "integrationRef": "TVD",
            "depth": {"min": dmin if dmin is not None else 0.0,
                      "max": dmax if dmax is not None else 1.0},
            "tracks": tracks,
            "tops": tops,
            # the channels the panel does not carry, with why: what the
            # report says when a rule or the porosity names one of them
            "absent": absent,
            "strati": {},
            "pay": [],
            # every sample, for the statistics: the decimation above only
            # shrinks what is DRAWN, while a zone's n, its pay intervals and
            # its net must be read on every sample, not one in k. Each sample
            # keeps BOTH depths — drawn, then vertical. Stripped by the host
            # before the payload crosses the websocket.
            "_full": {t: [[p[0], p[di], p[1]] for p in pts3]
                      for t, pts3 in full.items()},
        }
        # a hole that comes back up: an upward stretch SUBTRACTS from a
        # vertical thickness, which is right and must be visible
        well["tvd_up_hole"] = max(
            [up_hole_tvd(pts) for pts in well["_full"].values()] or [0.0])
        # drawn in MD: its TVD in a column beside it
        if use_md:
            well["mdTvd"] = md_tvd(well["_full"])
        # The stratigraphic band is what the marker frame STATES (PO,
        # 2026-10-05: nothing inferred): the unit of each interval between
        # its markers, read through the plugin's query channel over EVERY
        # marker of the frame, whatever is checked — a box changes nothing.
        # The band laid from the checked markers' titles is gone: unchecking
        # a marker changed it, a guess shown as a fact. `strati_columns`
        # only lends its colours.
        well["strati"] = _frame_strati(shared, tree, wid, well, raw_tops, strati_columns)
        wells.append(well)
        # the zones need `strati` and `tracks`, so they come last
        try:
            well["zones"] = zone_stats(well)
        except Exception as exc:
            print("[fespp] zone stats error:", exc, flush=True)
            well["zones"] = []

    if not wells:
        return empty
    markers = [{"name": n, "color": color_for_index(i)}
               for i, n in enumerate(marker_names)]
    return {"wells": wells,
            "markers": markers,
            "flattenOn": flatten_on if flatten_on in marker_names else None}


def zones_csv_payload(payload, cutoffs=None):
    """`{"name", "header"}` the panel's zones table is written under: the
    wells, where the zones come from, the cutoffs in force, the porosity
    and water-saturation logs the summation read per well, and the depth
    convention. Empty when no well carries a zone."""
    from fespp_on_trame.engine.utils import csv_export as ce
    wells = [w for w in (payload or {}).get("wells") or [] if w.get("zones")]
    if not wells:
        return dict(ce.EMPTY_PAYLOAD)
    names = [w.get("name") or "" for w in wells]
    sources = sorted({z.get("source") or "" for w in wells for z in w["zones"]})
    rules = [f"{r.get('curve')} {r.get('op')} {r.get('value')}"
             for r in (cutoffs or []) if r.get("curve")]
    reads = []
    for w in wells:
        sm = w.get("summation") or {}
        if sm:
            reads.append(f"{w.get('name')}: porosity {sm.get('phi') or 'none'},"
                         f" water saturation {sm.get('sw') or 'none'}")
    fields = [
        ("wells", ", ".join(names)),
        ("zones source", ", ".join(s for s in sources if s) or "none"),
        ("cutoffs", "; ".join(rules) if rules else "none"),
        ("summation logs", "; ".join(reads) if reads else None),
        ("depths", "top and base in each well's own drawing axis, named by the"
                   " depth_axis column; top_tvd and base_tvd are true vertical"
                   " depth; all in the frame's own unit (not declared in the"
                   " file)"),
        ("thicknesses", "gross_tvd, net_tvd, phih_tvd and hcph_tvd are"
                        " integrated on TRUE VERTICAL DEPTH; gross"
                        " (depth_axis) is the along-hole interval the zone"
                        " band is drawn over, not a thickness of rock;"
                        " ntg = net_tvd /"
                        " gross_tvd, a fraction; a curve's statistics are in"
                        " its unit"),
    ]
    part = names[0] if len(names) == 1 else f"{len(names)}_wells"
    return ce.payload("zones", fields, part)
