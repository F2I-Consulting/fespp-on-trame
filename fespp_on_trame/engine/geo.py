"""Geodesy for the Globe view — from the RESQML local CRS to the Earth.

FESPP already outputs every representation in the local CRS's *projected*
CRS (offsets / rotation applied, Z flipped to elevation), so all that is
left is projected (easting, northing, elevation) -> geographic -> ECEF
(Earth-centred, WGS84). The EPSG code of the projected CRS comes from the
local CRS objects as fesapi's typed accessors report them (the reader's
``ObjectFields`` query, engine/repo_query.py — the same over an EPC and
over ETP): the declared projected code, else the ``EPSG`` extra metadata,
else an ``EPSG:nnnn`` mention in the description — a file may declare an
"unknown" WKT CRS and carry the code in its extra metadata only.

Projection = pyproj (PROJ, any EPSG code) when installed; without it, a
built-in inverse UTM for the common UTM families (WGS84 / ED50 / ETRS89 /
NAD27 / NAD83 / WGS72) and the WGS84 ellipsoid ECEF.
"""
import math
import re
from pathlib import Path

import numpy as np

# WGS84
_A = 6378137.0
_F = 1.0 / 298.257223563
_E2 = _F * (2.0 - _F)
_B = _A * (1.0 - _F)

_EPSG_RE = re.compile(r"EPSG\s*:?\s*(\d{4,6})", re.IGNORECASE)

# EPSG UTM families: code = base + zone; (datum proj4, hemisphere)
_UTM_FAMILIES = (
    (32600, "+datum=WGS84", "N"), (32700, "+datum=WGS84", "S"),
    (23000, "+ellps=intl +towgs84=-87,-98,-121,0,0,0,0", "N"),      # ED50
    (25800, "+ellps=GRS80 +towgs84=0,0,0,0,0,0,0", "N"),           # ETRS89
    (26900, "+datum=NAD83", "N"), (26700, "+datum=NAD27", "N"),
    (32200, "+ellps=WGS72 +towgs84=0,0,4.5,0,0,0.554,0.2263", "N"),
    (32300, "+ellps=WGS72 +towgs84=0,0,4.5,0,0,0.554,0.2263", "S"),
)


# ---------------------------------------------------------------- CRS lookup
def crs_info_from_fields(fields):
    """{'epsg', 'title', 'depth', 'time', 'how', 'reason'} of one local 3D
    CRS from its ``ObjectFields`` lines (repo_query.object_fields), or None
    for an empty dict — an unknown uuid or a reference stub.

    ``epsg`` is None when no code can be found anywhere; ``reason`` is then
    what the file itself says about its projected CRS (fesapi's "unknown"
    reason), for the Globe card to quote rather than guess."""
    if not fields:
        return None
    epsg, how = None, None
    code = fields.get("epsg", "").strip()
    if code.isdigit():
        epsg, how = int(code), "ProjectedCrsEpsgCode"
    if epsg is None:
        extra = fields.get("extrametadata_epsg", "").strip()
        if extra.isdigit():
            epsg, how = int(extra), "ExtraMetadata"
    if epsg is None:
        m = _EPSG_RE.search(fields.get("description", ""))
        if m:
            epsg, how = int(m.group(1)), "Description"
    return {"epsg": epsg, "title": fields.get("title", ""),
            "depth": fields.get("depth_oriented") == "true",
            "time": fields.get("time_crs") == "true",
            # what the FILE calls its two horizontal ordinates
            # (ProjectedAxisOrder: "Easting Northing" and its seven
            # variants). The file's own word, not a guess from the code.
            "axis_order": fields.get("axis_order", ""),
            "projected_unit": fields.get("projected_unit", ""),
            "vertical_unit": fields.get("vertical_unit", ""),
            # a time CRS counts its vertical axis in this unit (ms, s)
            "time_unit": fields.get("time_unit", ""),
            "how": how, "reason": fields.get("projected_reason", "")}


# ------------------------------------------------------------ projections
def _utm_inverse(e, n, zone, south, a, f):
    """Transverse Mercator inverse (UTM, k0 = 0.9996) -> lon/lat in degrees;
    Snyder's series (sub-metre)."""
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x = np.asarray(e, dtype=float) - 500000.0
    y = np.asarray(n, dtype=float) - (10000000.0 if south else 0.0)
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * np.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * np.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * np.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * np.sin(8 * mu))
    sin1, cos1, tan1 = np.sin(phi1), np.cos(phi1), np.tan(phi1)
    n1 = a / np.sqrt(1 - e2 * sin1 ** 2)
    t1 = tan1 ** 2
    c1 = ep2 * cos1 ** 2
    r1 = a * (1 - e2) / (1 - e2 * sin1 ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * tan1 / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / cos1
    return np.degrees(lon), np.degrees(lat)


def _utm_family(epsg):
    for base, datum, hemi in _UTM_FAMILIES:
        zone = epsg - base
        if 1 <= zone <= 60:
            return zone, hemi == "S", datum
    return None


_AXES = {}


def axis_names_of(crs_info, epsg=None):
    """``(first, second, source)`` naming the two horizontal ordinates, in
    the order of authority the file deserves:

    1. what the FILE declares — RESQML's ``ProjectedAxisOrder``, carried by
       the CRS object and read through the query channel. The file's own
       word is what the data was written with;
    2. failing that, what the EPSG REGISTRY says of the code (pyproj), which
       is a sound guess but still a guess;
    3. failing both, ``("X", "Y", "")`` — the reader's own letters, and the
       caller says nothing more than it knows.

    `source` names which of the three answered, so the screen can say where
    the names come from instead of presenting all three as equal."""
    order = ((crs_info or {}).get("axis_order") or "").split()
    if len(order) == 2:
        return order[0], order[1], "the file"
    code = epsg if epsg is not None else (crs_info or {}).get("epsg")
    named = axis_names(code)
    if named:
        return named[0], named[1], "the EPSG registry"
    return "X", "Y", ""


def axes_labels(crs_info, epsg=None):
    """``(x, y, z)`` — the letters a 3D view's orientation axes carry: the
    initials of the horizontal ordinates as `axis_names_of` names them (the
    file's own order: "Easting Northing" gives E N, "Northing Easting" N E)
    and Z, the elevation (FESPP draws a depth CRS negated, so +Z is up) —
    T for a time CRS, its vertical a seismic time (the PO, 28/10). Each with
    the unit the CRS declares, short: "E (m)", "T (ms)" (the PO, 28/10: the
    unit on the arrow); none is guessed. Initials and not the words:
    ParaView draws the orientation axes in a small fixed corner, where a
    whole name such as "Northing" is cut off and, seen from above, the Z
    label overlaps the X one. The whole names are in the pick readout. X Y
    Z when no CRS names anything."""
    info = crs_info or {}
    first, second, source = axis_names_of(info, epsg)
    if not source or not first or not second:
        return "X", "Y", "Z"
    unit, vunit = _units(info, epsg, source)

    def lettered(name, u):
        return f"{name} ({u})" if u else name
    return (lettered(first[0].upper(), unit), lettered(second[0].upper(), unit),
            lettered("T" if info.get("time") else "Z", vunit))


# the registry's unit names, as a title writes them
_UNIT_SHORT = {"metre": "m", "meter": "m", "foot": "ft", "US survey foot": "ftUS",
               "kilometre": "km"}


def _units(info, epsg, source):
    """``(horizontal, vertical)`` units of a CRS, short, "" when it declares
    none: the horizontal one the file's (the registry's when the file gives
    the axis names from it), the vertical one its time unit for a time CRS,
    else its vertical unit."""
    unit = (info.get("projected_unit") or "").strip()
    if not unit and source == "the EPSG registry":
        named = axis_names(epsg if epsg is not None else info.get("epsg"))
        unit = _UNIT_SHORT.get((named or ("", "", ""))[2] or "", "")
    vunit = ((info.get("time_unit") if info.get("time") else "") or info.get("vertical_unit") or "").strip()
    return _UNIT_SHORT.get(unit, unit), _UNIT_SHORT.get(vunit, vunit)


def xy_unit(crs_info):
    """The short unit of the CRS's easting and northing ("m", "ft"), "" when
    it declares none."""
    return _units(crs_info or {}, None, "")[0]


def depth_unit(crs_info):
    """The short unit a DEPTH is counted in on this CRS's vertical axis
    ("m", "ft"), "" for a time CRS or one that declares none."""
    info = crs_info or {}
    if info.get("time"):
        return ""
    return _units(info, None, "")[1]


def axes_grid_titles(crs_info, epsg=None):
    """``(x, y, z)`` — the titles of a 3D view's axes grid: the horizontal
    ordinates as `axis_names_of` names them, with the unit the file declares
    (the registry's when the file declares none) — "Easting (m)",
    "Northing (m)" — and the vertical as the ELEVATION it is in VTK (FESPP
    draws a depth negated), or the time of a time CRS, with the vertical
    unit. Room is not the limit here as it is on the orientation axes
    (`axes_labels`): the grid runs along the scene. A name or a unit nobody
    declares is left out rather than guessed: "X", "Y", "Elevation"."""
    info = crs_info or {}
    first, second, source = axis_names_of(info, epsg)
    unit, vunit = _units(info, epsg, source)
    vertical = "Time" if info.get("time") else "Elevation"

    def titled(name, u):
        return f"{name} ({u})" if u else name
    return titled(first, unit), titled(second, unit), titled(vertical, vunit)


def axis_names(epsg):
    """``(first, second, unit)`` as the EPSG REGISTRY names the horizontal
    axes of a code — ``("Easting", "Northing", "metre")`` for a UTM zone —
    or None. Prefer `axis_names_of`, which asks the file first.

    Cached: building a CRS opens the PROJ database.

    None when pyproj is absent, the code is unknown, or the CRS declares
    fewer than two axes — the caller then keeps its own wording and says
    nothing false."""
    # no try for the conversion: an EPSG code is digits or it is not one
    text = str(epsg or "").strip()
    if not text.isdigit():
        return None
    code = int(text)
    if code in _AXES:
        return _AXES[code]
    out = None
    try:
        from pyproj import CRS
        axes = list(CRS.from_epsg(code).axis_info or [])
        if len(axes) >= 2:
            out = (axes[0].name, axes[1].name, axes[0].unit_name)
    except Exception as exc:
        print(f"[fespp] axis names of EPSG:{code}: {exc}", flush=True)
    _AXES[code] = out
    return out


_EPSG_CHECK = {}


def epsg_problem(epsg):
    """None when ``epsg`` is a projected CRS the projection can use, else a
    short reason (unknown code, geographic / vertical CRS, no pyproj and
    not a UTM code). Cached."""
    try:
        code = int(epsg)
    except (TypeError, ValueError):
        return "no EPSG code"
    if code in _EPSG_CHECK:
        return _EPSG_CHECK[code]
    problem = None
    try:
        from pyproj import CRS
        try:
            crs = CRS.from_epsg(code)
            if not crs.is_projected:
                kind = ("geographic" if crs.is_geographic else
                        "vertical" if crs.is_vertical else crs.type_name)
                problem = f"EPSG:{code} is a {kind} CRS, not a projected one"
        except Exception:
            problem = f"EPSG:{code} is not a CRS known to PROJ"
            if code == 5215:
                # the projected code written by fesapi's example writer —
                # in the EPSG registry it is the EVRF2007 vertical datum
                problem += " (5215 = a vertical datum; fesapi's sample placeholder)"
    except ImportError:
        if _utm_family(code) is None:
            problem = f"EPSG:{code}: not a UTM code (pyproj not installed)"
    _EPSG_CHECK[code] = problem
    return problem


_TRANSFORMERS = {}


def transformer(src_epsg, dst_epsg):
    """The pyproj Transformer from one EPSG code to another (x, y in that
    order whatever the codes' axis order), cached: building one opens the
    PROJ database, which costs more than the transform itself for anything
    under a few hundred thousand points, and a pipeline calls this once per
    partition. ImportError without pyproj."""
    key = (int(src_epsg), int(dst_epsg))
    t = _TRANSFORMERS.get(key)
    if t is None:
        from pyproj import Transformer
        t = Transformer.from_crs(f"EPSG:{key[0]}", f"EPSG:{key[1]}", always_xy=True)
        _TRANSFORMERS[key] = t
    return t


def geographic_of(epsg, x, y):
    """Projected (x, y) arrays of EPSG ``epsg`` -> (lon, lat) degrees."""
    try:
        lon, lat = transformer(epsg, 4326).transform(np.asarray(x, float), np.asarray(y, float))
        return np.asarray(lon, float), np.asarray(lat, float)
    except ImportError:
        fam = _utm_family(int(epsg))
        if fam is None:
            raise ValueError(f"EPSG:{epsg}: not a UTM code and pyproj is not installed")
        zone, south, datum = fam
        a, f = _A, _F
        if "intl" in datum:
            a, f = 6378388.0, 1.0 / 297.0
        elif "GRS80" in datum:
            a, f = 6378137.0, 1.0 / 298.257222101
        elif "NAD27" in datum:
            a, f = 6378206.4, 1.0 / 294.978698214
        elif "WGS72" in datum:
            a, f = 6378135.0, 1.0 / 298.26
        return _utm_inverse(x, y, zone, south, a, f)


def ecef_of(lon_deg, lat_deg, h):
    """Geographic -> WGS84 Earth-centred (x, y, z), metres."""
    lon = np.radians(np.asarray(lon_deg, float))
    lat = np.radians(np.asarray(lat_deg, float))
    h = np.asarray(h, float)
    s, c = np.sin(lat), np.cos(lat)
    n = _A / np.sqrt(1.0 - _E2 * s * s)
    return ((n + h) * c * np.cos(lon), (n + h) * c * np.sin(lon), (n * (1.0 - _E2) + h) * s)


def geodetic_of(x, y, z):
    """ECEF -> (lon, lat, h) degrees / metres (Bowring's closed form)."""
    x, y, z = float(x), float(y), float(z)
    lon = math.degrees(math.atan2(y, x))
    p = math.hypot(x, y)
    if p < 1e-9:
        return lon, (90.0 if z >= 0 else -90.0), abs(z) - _B
    theta = math.atan2(z * _A, p * _B)
    ep2 = (_A * _A - _B * _B) / (_B * _B)
    lat = math.atan2(z + ep2 * _B * math.sin(theta) ** 3,
                     p - _E2 * _A * math.cos(theta) ** 3)
    n = _A / math.sqrt(1.0 - _E2 * math.sin(lat) ** 2)
    return lon, math.degrees(lat), p / math.cos(lat) - n


def project_points(xyz, epsg, zscale=1.0):
    """(N, 3) projected easting / northing / elevation -> (N, 3) ECEF; the
    elevation is exaggerated by ``zscale`` BEFORE going round the Earth, so
    the exaggeration is radial."""
    xyz = np.asarray(xyz, dtype=float).reshape(-1, 3)
    if xyz.shape[0] == 0:
        return xyz
    lon, lat = geographic_of(epsg, xyz[:, 0], xyz[:, 1])
    x, y, z = ecef_of(lon, lat, xyz[:, 2] * float(zscale))
    return np.column_stack([x, y, z])


def map_pdc_points(inp, out, move):
    """Copy the partitioned dataset collection ``inp`` into ``out``
    (assembly and arrays shared), each leaf's points replaced by
    ``move(i, xyz)`` — ``i`` the partitioned dataset's index, ``xyz`` its
    (N, 3) points — as NEW double points when it returns an array, the leaf
    kept as it is when it returns None. The shared input is left untouched
    for the other views; an exception of ``move`` propagates. The one loop
    of the Globe's projection and of the reference CRS's reprojection."""
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.util.numpy_support import vtk_to_numpy, numpy_to_vtk
    out.ShallowCopy(inp)
    for i in range(inp.GetNumberOfPartitionedDataSets()):
        pds = inp.GetPartitionedDataSet(i)
        if pds is None:
            continue
        for j in range(pds.GetNumberOfPartitions()):
            ds = pds.GetPartition(j)
            if ds is None or not hasattr(ds, "GetPoints") or ds.GetPoints() is None:
                continue
            moved = move(i, vtk_to_numpy(ds.GetPoints().GetData()))
            if moved is None:
                continue
            copy = ds.NewInstance()
            copy.ShallowCopy(ds)
            pts = vtkPoints()
            pts.SetDataTypeToDouble()
            pts.SetData(numpy_to_vtk(np.ascontiguousarray(moved, dtype=float), deep=1))
            copy.SetPoints(pts)
            out.GetPartitionedDataSet(i).SetPartition(j, copy)


def project_pdc(inp, out, epsg, zscale=1.0):
    """ProgrammableFilter body: copy the partitioned dataset collection
    ``inp`` into ``out`` (assembly and arrays shared) with every leaf's
    points moved to ECEF as NEW double points — the shared input is left
    untouched for the other views."""
    if not epsg or epsg_problem(epsg):
        # unknown / unusable CRS: the structure (assembly) without any
        # geometry — un-projected coordinates must never reach the Earth
        # scene (a UTM northing read as ECEF floats 6 500 km out in space)
        out.CopyStructure(inp)
        return
    try:
        map_pdc_points(inp, out, lambda _i, xyz: project_points(xyz, epsg, zscale))
    except Exception as exc:  # noqa: BLE001 — any failure: no geometry on the Earth
        import sys
        print(f"[fespp] globe projection failed (EPSG:{epsg}): {exc!r}",
              file=sys.stderr, flush=True)
        out.CopyStructure(inp)


# ------------------------------------------------------- marks on the Earth
BOX_SAMPLES = 8         # per horizontal side, so an edge follows the curve
PIN_HEIGHT = 2000.0     # m above the ellipsoid — clear of the Earth mesh's sag


def _plan_ring(b, n):
    """(4n, 2) plan outline of a projected extent, n samples per side and no
    duplicated corner (so index 0, n, 2n, 3n are the four corners)."""
    t = np.arange(n, dtype=float) / n

    def side(ax, ay, bx, by):
        return np.column_stack([ax + (bx - ax) * t, ay + (by - ay) * t])

    x0, x1, y0, y1 = b[0], b[1], b[2], b[3]
    return np.vstack([side(x0, y0, x1, y0), side(x1, y0, x1, y1),
                      side(x1, y1, x0, y1), side(x0, y1, x0, y0)])


def pin_points(anchors, epsg):
    """(N, 3) ECEF of a pin above each projected-CRS plan centre ``(x, y)``.

    Deliberately NOT through ``project_points``: that multiplies elevation by
    the exaggeration, so the pin's height would grow with it (40 km up at
    x20). A fixed height above the ellipsoid instead — and above the Earth
    MESH, which is inscribed and sags below the true surface between its
    vertices, so anything at reservoir depth is sealed inside the opaque
    shell."""
    anchors = list(anchors or ())
    if not anchors or not epsg or epsg_problem(epsg):
        return np.zeros((0, 3))
    lon, lat = geographic_of(epsg, np.array([a[0] for a in anchors], float),
                             np.array([a[1] for a in anchors], float))
    x, y, z = ecef_of(lon, lat, np.full(len(anchors), PIN_HEIGHT))
    return np.column_stack([x, y, z])


def marks_polydata(marks, epsg, zscale=1.0, min_span=0.0):
    """Every Globe mark in ONE vtkPolyData, in ECEF.

    ``marks`` = iterable of ``(bounds, anchor)``: ``bounds`` is the object's
    extent IN THE PROJECTED CRS ``[x0, x1, y0, y1, z0, z1]`` (None for a well
    head, which has no footprint) and ``anchor`` its plan centre ``(x, y)``.

    Two regimes, and ``min_span`` — the smallest ground size worth drawing at
    the current zoom — decides which:

    * the object is BIGGER than ``min_span``: the twelve edges of its real
      extent, at its real depth. What you see is what the grid occupies.
    * it is smaller (you are far away): one flat ring of ``min_span`` on the
      ellipsoid. A 5 km field is a third of a pixel from space, so at that
      distance the mark is a LOCATOR and says only "here" — it is drawn on the
      surface because the Earth mesh is inscribed and sags below the true
      surface, which would swallow anything at reservoir depth.

    The two meet continuously: as the camera comes in, ``min_span`` shrinks
    until the real extent wins, and from then on the box IS the extent.

    Corners are taken in the PROJECTED CRS and pushed through the very
    transform the data takes, ``zscale`` included. Building the box from the
    already-projected ECEF bounds instead would align it to the Earth's axes,
    not to the local horizon: at high latitude a thin grid's box would draw
    many times its thickness and tilted far off the horizontal.
    """
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    from vtkmodules.util.numpy_support import numpy_to_vtk

    pd = vtkPolyData()
    marks = [m for m in (marks or ()) if m and m[1] is not None]
    # Same gate as project_pdc: on an unusable code no geometry reaches the
    # Earth scene, and a mark drawn from un-projected metres would sit
    # thousands of km out in space with every appearance of being right.
    if not marks or not epsg or epsg_problem(epsg):
        return pd

    n = BOX_SAMPLES
    m = 4 * n
    projected = []      # (points, is_flat_locator) batched through the transform
    lines = []

    for bounds, anchor in marks:
        base = sum(len(p) for p, _f in projected)
        span = 0.0 if bounds is None else max(bounds[1] - bounds[0],
                                              bounds[3] - bounds[2])
        if bounds is None or span < min_span:
            # locator: a flat ring of min_span on the ellipsoid
            half = max(min_span, span) / 2.0
            if half <= 0.0:
                continue
            box = [anchor[0] - half, anchor[0] + half,
                   anchor[1] - half, anchor[1] + half, 0.0, 0.0]
            ring = _plan_ring(box, n)
            projected.append((np.column_stack(
                [ring[:, 0], ring[:, 1], np.zeros(m)]), True))
            lines.append([base + i for i in range(m)] + [base])
            continue
        ring = _plan_ring(bounds, n)
        z0, z1 = float(bounds[4]), float(bounds[5])
        diag = float(np.hypot(bounds[1] - bounds[0], bounds[3] - bounds[2]))
        # A single-layer grid gives z0 == z1: two coincident rings and eight
        # zero-length verticals, i.e. pure z-fighting. One ring.
        flat = (z1 - z0) <= 1e-3 * max(diag, 1.0)
        projected.append((np.column_stack(
            [ring[:, 0], ring[:, 1], np.full(m, z0)]), False))
        lines.append([base + i for i in range(m)] + [base])
        if not flat:
            projected.append((np.column_stack(
                [ring[:, 0], ring[:, 1], np.full(m, z1)]), False))
            lines.append([base + m + i for i in range(m)] + [base + m])
            lines += [[base + i, base + m + i] for i in (0, n, 2 * n, 3 * n)]

    if not projected:
        return pd
    # The locator rings sit at a fixed height ABOVE the ellipsoid and must not
    # go through project_points: that multiplies elevation by the exaggeration,
    # so at x20 a ring would fly 40 km up. The extent boxes must go through it,
    # since they follow the data.
    chunks = []
    for pts, is_locator in projected:
        if is_locator:
            lon, lat = geographic_of(epsg, pts[:, 0], pts[:, 1])
            x, y, z = ecef_of(lon, lat, np.full(len(pts), PIN_HEIGHT))
            chunks.append(np.column_stack([x, y, z]))
        else:
            chunks.append(project_points(pts, epsg, zscale))
    allpts = np.vstack(chunks)

    pts = vtkPoints()
    pts.SetDataTypeToDouble()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(allpts), deep=1))
    pd.SetPoints(pts)

    cells = vtkCellArray()
    for ids in lines:
        cells.InsertNextCell(len(ids))
        for i in ids:
            cells.InsertCellPoint(int(i))
    pd.SetLines(cells)
    return pd


# ---------------------------------------------------------------- the Earth
# Equirectangular Earth textures, coarsest first. The numbers are what a
# texel covers at the equator — the reason the globe blurs as you come in.
# All four are the same NASA Blue Marble image (land + shallow topography,
# public domain), so switching quality changes the sharpness and nothing else.
# The memory figures are each level's first-load growth of the process's
# resident memory, and they are the reason the default is not the finest: a
# texture is decoded, kept as image data, uploaded to GL and mipmapped, so it
# costs far more than its file.
# Nothing is ever freed (see globe_scene._earth_texture_proxy), so a level
# costs this once, for the session, the first time it is chosen.
EARTH_TEXTURES = (
    ("2k", "earth-2k.jpg", "Low — 19.6 km/pixel (30 MB)", 30),
    ("4k", "earth-4k.jpg", "Medium — 9.8 km/pixel (70 MB)", 70),
    ("8k", "earth-8k.jpg", "High — 4.9 km/pixel (290 MB)", 290),
    ("16k", "earth-16k.jpg", "Very high — 2.4 km/pixel (1 GB, ~3 s)", 1066),
)
_ASSETS = Path(__file__).resolve().parents[1] / "assets"


def earth_textures_available():
    """[(key, label)] of the textures actually shipped, coarsest first. The
    package may carry any subset — the big ones are optional weight."""
    out = []
    for key, name, label, _mb in EARTH_TEXTURES:
        if (_ASSETS / name).is_file():
            # {value, label, title} — the ONE option shape the widgets'
            # select validates (widgets/_shared/components/options.js);
            # without `label` the select shows "[object Object]".
            out.append({"value": key, "label": label, "title": label})
    return out


EARTH_TEXTURE_DEFAULT = "4k"
# left free for the rest of the machine after a texture is granted
_MEMORY_FLOOR_MB = 1500.0


def earth_texture_path(quality=None):
    """File for ``quality``, else the closest coarser one present, else the
    unsuffixed ``earth.jpg``, else None. Never raises: a missing texture
    leaves an untextured globe, which still locates the data.

    An unknown or missing quality resolves to the DEFAULT, never to the
    finest: a stale setting must not silently pull the heaviest imagery."""
    keys = [k for k, _n, _l, _mb in EARTH_TEXTURES]
    if quality not in keys:
        quality = EARTH_TEXTURE_DEFAULT
    order = keys[:keys.index(quality) + 1][::-1]
    for key in order:
        name = dict((k, n) for k, n, _l, _mb in EARTH_TEXTURES)[key]
        f = _ASSETS / name
        if f.is_file():
            return str(f)
    legacy = _ASSETS / "earth.jpg"
    return str(legacy) if legacy.is_file() else None


def memory_available_mb():
    """Memory the machine can still hand out, or None where that cannot be
    read (not Linux). Read fresh: every session is its OWN pvpython process,
    so what matters is what the OTHER sessions have already taken."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def earth_texture_affordable(quality):
    """``(quality, note)`` — the requested level, or the finest one below it
    that still fits, with a note saying why it was stepped down.

    The launcher runs one process per session and caps neither their number
    nor their memory, so ten sessions on the finest imagery would want ~10 GB
    of textures alone. The Linux OOM killer then kills the FATTEST process,
    which is somebody else's session, not necessarily the one that asked.

    Honest limit: each session checks on its own, so several starting at the
    same instant can all see the same free memory and all be granted. This
    stops one session from eating a machine that is already tight; it is not
    a quota, and there is nowhere to put one without a shared broker."""
    keys = [k for k, _n, _l, _mb in EARTH_TEXTURES]
    cost = dict((k, mb) for k, _n, _l, mb in EARTH_TEXTURES)
    if quality not in keys:
        quality = EARTH_TEXTURE_DEFAULT
    free = memory_available_mb()
    if free is None:
        return quality, ""
    # Twice the cost, because the image is decoded, copied into VTK and
    # uploaded to GL — the peak during the load is well above the resting
    # figure — AND a floor left over, so a session cannot take the last
    # gigabyte and leave the next one to be killed for it.
    for key in keys[:keys.index(quality) + 1][::-1]:
        if free > 2.0 * cost[key] and (free - cost[key]) > _MEMORY_FLOOR_MB:
            if key == quality:
                return key, ""
            return key, (f"{quality} imagery needs ~{cost[quality]} MB and only "
                         f"{free:.0f} MB is free on the machine — using {key}")
    return keys[0], (f"only {free:.0f} MB is free on the machine — using the "
                     "lowest imagery")


def earth_polydata(n_lon=360, n_lat=180):
    """WGS84 ellipsoid as a quad mesh with equirectangular texture
    coordinates (u = lon, v = lat, origin bottom-left = the usual world
    image layout) and outward normals.

    1 deg quads = 111 km facets at the equator. Coarser facets show as
    polygon edges as soon as the camera leaves the whole-Earth framing, and
    stretch each texture tile linearly across the facet, which looks like a
    blurred texture when the mesh is to blame."""
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkPolyData, vtkCellArray
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
    lon = np.linspace(-180.0, 180.0, n_lon + 1)
    lat = np.linspace(-90.0, 90.0, n_lat + 1)
    LON, LAT = np.meshgrid(lon, lat)           # (n_lat+1, n_lon+1)
    x, y, z = ecef_of(LON.ravel(), LAT.ravel(), 0.0)
    xyz = np.column_stack([x, y, z])
    tc = np.column_stack([(LON.ravel() + 180.0) / 360.0, (LAT.ravel() + 90.0) / 180.0])
    # geodetic normal (up) — what a viewer expects on an ellipsoid
    lr, pr = np.radians(LON.ravel()), np.radians(LAT.ravel())
    nrm = np.column_stack([np.cos(pr) * np.cos(lr), np.cos(pr) * np.sin(lr), np.sin(pr)])
    quads = []
    w = n_lon + 1
    for r in range(n_lat):
        base = r * w
        idx = np.arange(n_lon)
        quads.append(np.column_stack([np.full(n_lon, 4), base + idx, base + idx + 1,
                                      base + w + idx + 1, base + w + idx]))
    cells = np.concatenate(quads).ravel().astype(np.int64)
    pd = vtkPolyData()
    pts = vtkPoints()
    pts.SetDataTypeToDouble()
    pts.SetData(numpy_to_vtk(xyz, deep=1))
    pd.SetPoints(pts)
    ca = vtkCellArray()
    ca.SetCells(n_lon * n_lat, numpy_to_vtkIdTypeArray(cells, deep=1))
    pd.SetPolys(ca)
    tca = numpy_to_vtk(tc, deep=1)
    tca.SetName("TCoords")
    pd.GetPointData().SetTCoords(tca)
    na = numpy_to_vtk(nrm, deep=1)
    na.SetName("Normals")
    pd.GetPointData().SetNormals(na)
    return pd


EARTH_SOURCE_SCRIPT = """
from fespp_on_trame.engine.geo import earth_polydata
output.ShallowCopy(earth_polydata())
"""

PROJECT_FILTER_SCRIPT = """
from fespp_on_trame.engine.geo import project_pdc
project_pdc(inputs[0].VTKObject, output.VTKObject, %(epsg)d, %(zscale)r)
"""


def ellipsoid_hit(origin, direction):
    """Where a ray meets the WGS84 ellipsoid, in ECEF, or None when it misses.

    The nearest intersection in front of the origin. Used by the crosshair on
    a Globe view, where asking ParaView for the surface under the pointer is
    not an option: `ConvertDisplayToPointOnSurface` runs a hardware surface
    selection there and NEVER RETURNS (with GPU and software rendering
    alike), and the depth buffer cannot be read back reliably outside a
    render. The ellipsoid, on the other hand, is known in closed form: the
    ray is unprojected from the camera and met with x^2/a^2 + y^2/a^2 +
    z^2/b^2 = 1, which is exact, costs a square root, and cannot hang.

    What the reader gets from it is the point ON THE GROUND under the
    pointer, not the point on the data drawn above or below it — so the
    caller must say so rather than report a height it did not measure.
    """
    ox, oy, oz = [float(v) for v in origin]
    dx, dy, dz = [float(v) for v in direction]
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n < 1e-12:
        return None
    dx, dy, dz = dx / n, dy / n, dz / n
    # the ellipsoid scaled to a unit sphere: divide each axis by its radius
    sa, sb = 1.0 / _A, 1.0 / _B
    ex, ey, ez = ox * sa, oy * sa, oz * sb
    fx, fy, fz = dx * sa, dy * sa, dz * sb
    a = fx * fx + fy * fy + fz * fz
    b = 2.0 * (ex * fx + ey * fy + ez * fz)
    c = ex * ex + ey * ey + ez * ez - 1.0
    if a <= 0.0:
        return None
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None            # the pointer is off the limb: a clean miss
    root = math.sqrt(disc)
    t1 = (-b - root) / (2.0 * a)
    t2 = (-b + root) / (2.0 * a)
    t = t1 if t1 > 0.0 else t2
    if t <= 0.0:
        return None            # the Earth is behind the eye
    return [ox + dx * t, oy + dy * t, oz + dz * t]
