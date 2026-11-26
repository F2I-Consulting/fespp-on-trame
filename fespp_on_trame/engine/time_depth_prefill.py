"""What pre-fills the time-depth model from the files without a tick (the
PO, 31/10: "à la demande, si on demande un pré-remplissage"): the extent
of the representations, and columns from the wells' time logs — pure,
over what the plugin's query channel answers to ObjectFieldsKey
(engine/repo_query.object_fields):

- a representation: ``extent_xy=x0;x1;y0;y1`` in the global CRS (a 2D
  grid from its lattice, XML alone; an IJK grid from its top and base
  interfaces; anything else from its points), ``extent_how``;
- a log channel on a wellbore frame: ``md``, ``xyz`` (the frame's nodes
  in the global CRS, as fesapi returns them), ``values``, ``uom``,
  ``depth_oriented`` (which way z counts), ``count``.

A time log is a channel whose unit is a time (s, ms): a checkshot table
(Volve: TWTIME, 10 to 192 points per well) is the measurement itself, a
(depth, two-way time) pair per sample. The columns it makes are sampled
on ONE depth step shared by every well, so the velocity model's layers (the union
of the columns' depths) stay few and the table readable: a column's time
at a shared depth is read on its own curve, linearly.
"""
import math
import re

# the fesapi XML tags of what has an extent of its own (a SubRepresentation
# has its support's, a property its representation's)
REPRESENTATION_TYPES = {
    "Grid2dRepresentation", "TriangulatedSetRepresentation", "PolylineSetRepresentation",
    "PolylineRepresentation", "PointSetRepresentation", "WellboreTrajectoryRepresentation",
    "IjkGridRepresentation", "TruncatedIjkGridRepresentation", "UnstructuredGridRepresentation",
}
# how the plugin reads each, for the question asked before it does
HOW_OF_TYPE = {
    "Grid2dRepresentation": "lattice",
    "IjkGridRepresentation": "top and base",
    "TruncatedIjkGridRepresentation": "points",
    "UnstructuredGridRepresentation": "points",
}
# a time unit and its factor to the millisecond
TIME_UOMS = {"s": 1000.0, "second": 1000.0, "ms": 1.0, "millisecond": 1.0, "us": 0.001}
PAD = 0.02          # the extent of the files, a little wider, as the Auto extent
STEPS = (50.0, 100.0, 200.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0)
LAYERS_WANTED = 12  # the shared depth step aims at about this many layers
NAME_MAX = 40       # a column's name (the feature's name_column keeps 40)
VERTICAL_TOL = 1.0  # m: the most a vertical well's samples stray from their mean position


def numbers(text):
    """The ";"-joined numbers of a field, NaN for "nan" or an unreadable one."""
    out, bad = [], 0
    for part in str(text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            # a number the plugin wrote that is none: NaN, said once per field
            out.append(math.nan)
            bad += 1
            if bad == 1:
                print(f"[fespp] time-depth pre-fill: an unreadable number in a field ({part!r})", flush=True)
    return out


# ------------------------------------------------------------------ extent
def extent_of(fields):
    """(x0, x1, y0, y1) of a representation's fields, None without a
    finite, non-empty one."""
    v = numbers((fields or {}).get("extent_xy"))
    if len(v) != 4 or any(math.isnan(x) for x in v):
        return None
    x0, x1, y0, y1 = v
    if x1 < x0 or y1 < y0:
        return None
    return (x0, x1, y0, y1)


def union(extents):
    """The extent holding every one of `extents` (None skipped), None when
    there is none."""
    got = [e for e in extents if e is not None]
    if not got:
        return None
    return (min(e[0] for e in got), max(e[1] for e in got),
            min(e[2] for e in got), max(e[3] for e in got))


def padded(extent, pad=PAD):
    """`extent` a little wider (`pad` of its width on each side), a flat
    one given a kilometre: a velocity model over a point is no velocity model."""
    x0, x1, y0, y1 = extent
    px, py = max((x1 - x0) * pad, 1.0), max((y1 - y0) * pad, 1.0)
    if x1 - x0 < 1.0:
        px = 500.0
    if y1 - y0 < 1.0:
        py = 500.0
    return (x0 - px, x1 + px, y0 - py, y1 + py)


def extent_entries(index):
    """The representations of the repository index ([{uuid, type, title,
    partial}]) the extent is read from: [(uuid, type, title)], stubs
    included — on a lean ETP load every representation is one until read,
    and the query channel fetches it; a stub no file holds answers
    nothing."""
    return [(e["uuid"], e["type"], e.get("title") or "") for e in index or ()
            if e.get("type") in REPRESENTATION_TYPES]


def quick_entries(entries):
    """Of `entries` [(uuid, type, title)], the 2D grids (their lattice) and
    the IJK grids (their top and base): the field's extent without reading
    the points of every well and surface — one request each on a store."""
    return [e for e in entries if HOW_OF_TYPE.get(e[1]) in ("lattice", "top and base")]


def describe_extent_read(entries):
    """What the extent read does, by how each kind is read: "12 horizons from
    their lattice (no data read), 8 surfaces and 13 wells from their
    points, 1 grid from its top and base"."""
    by = {}
    for _uuid, typ, _title in entries:
        by[HOW_OF_TYPE.get(typ, "points")] = by.get(HOW_OF_TYPE.get(typ, "points"), 0) + 1
    parts = []
    if by.get("lattice"):
        parts.append(f"{by['lattice']} from their lattice (no data read)")
    if by.get("top and base"):
        parts.append(f"{by['top and base']} from their top and base interfaces")
    if by.get("points"):
        parts.append(f"{by['points']} from their points")
    return ", ".join(parts)


# -------------------------------------------------------------- time logs
def time_factor(uom):
    """The factor of `uom` to the millisecond, None for a unit that is no
    time."""
    return TIME_UOMS.get(str(uom or "").strip().lower())


def is_time_log(title, uom):
    """A channel whose unit is a time — a two-way time table. The title
    does not decide (a "TIME" in µs/ft is a slowness); the unit does."""
    return time_factor(uom) is not None


def time_log_rank(title):
    """Which of a well's time logs makes its column: a two-way time by its
    name first ("TWT", "TWTIME"), a plain "TIME" next, the rest after; the
    smaller ranks first."""
    t = str(title or "").upper()
    if "TWT" in t:
        return 0
    if "TIME" in t:
        return 1
    return 2


def pick_time_logs(channels):
    """One time log per well out of `channels` [(well, uuid, title, uom)]:
    [(well, uuid, title, uom)], the wells in the order met."""
    best = {}
    order = []
    for well, uuid, title, uom in channels:
        if not is_time_log(title, uom):
            continue
        if well not in best:
            order.append(well)
            best[well] = (well, uuid, title, uom)
        elif time_log_rank(title) < time_log_rank(best[well][2]):
            best[well] = (well, uuid, title, uom)
    return [best[w] for w in order]


def channel_nodes(fields):
    """The (x, y, depth, value) nodes of a log channel's fields, by depth,
    a node dropped when any of its numbers is NaN; the depth counted
    downward (`positive_down`). [] without a position per value."""
    f = fields or {}
    values = numbers(f.get("values"))
    xyz = numbers(f.get("xyz"))
    if not values or len(xyz) != 3 * len(values):
        return []
    out = []
    for i, v in enumerate(values):
        x, y, z = xyz[3 * i], xyz[3 * i + 1], xyz[3 * i + 2]
        if any(math.isnan(n) for n in (v, x, y, z)):
            continue
        out.append((x, y, positive_down(z, f), v))
    out.sort(key=lambda s: s[2])
    return out


def log_samples(fields):
    """The (x, y, depth, twt_ms) samples of a log channel's fields, by
    depth, a sample dropped when any of its numbers is NaN or its node has
    no position; depth below the vertical zero, positive down (the global
    CRS z as it counts: `depth_oriented`); the time in ms whatever the
    unit. [] without values, a position per value, or a time unit."""
    factor = time_factor((fields or {}).get("uom"))
    if factor is None:
        return []
    return [(x, y, z, v * factor) for x, y, z, v in channel_nodes(fields)]


def nice_step(zmax, layers=LAYERS_WANTED):
    """The round depth step that cuts `zmax` into the number of layers
    closest to `layers` (3 100 m: 250 m makes 12.4 layers, 500 m makes 6)."""
    if not zmax or zmax <= 0:
        return STEPS[2]
    return min(STEPS, key=lambda s: abs(zmax / s - layers))


def _interp(z, zs, ts):
    """ts at z on the (zs, ts) curve, linear; None outside it."""
    if not zs or z < zs[0] or z > zs[-1]:
        return None
    for k in range(1, len(zs)):
        if zs[k] >= z:
            z0, z1, t0, t1 = zs[k - 1], zs[k], ts[k - 1], ts[k]
            if z1 == z0:
                return t1
            return t0 + (z - z0) * (t1 - t0) / (z1 - z0)
    return ts[-1]


def curve(samples, least=2):
    """The (depths, times) curve of a log's samples, from the zero (0 m,
    0 ms: the vertical datum, where every law starts); a sample not deeper
    AND later than the one before is dropped (the law refuses such a
    point). ([], []) under `least` usable samples: two for a log, one for
    a horizon pair or a marker."""
    zs, ts = [0.0], [0.0]
    for _x, _y, z, t in samples:
        if z <= zs[-1] or t <= ts[-1]:
            continue
        zs.append(z)
        ts.append(t)
    return (zs, ts) if len(zs) >= least + 1 else ([], [])


def column_points(samples, step, least=2):
    """A column out of a log's samples: ((x, y), [(depth, twt)]) — the
    position the mean of the samples' (a deviated well drifts: its column
    stands where the log is, on average), the points at every multiple of
    `step` the curve reaches, each time read on the curve (`curve`).
    ((None, None), []) under `least` usable samples."""
    zs, ts = curve(samples, least)
    if not zs:
        return ((None, None), [])
    x = sum(s[0] for s in samples) / len(samples)
    y = sum(s[1] for s in samples) / len(samples)
    points = []
    d = step
    while d <= zs[-1] + 1e-9:
        t = _interp(d, zs, ts)
        if t is not None and (not points or (d > points[-1][0] and t > points[-1][1])):
            points.append((d, t))
        d += step
    return ((x, y), points)


def vertical(samples, tol=VERTICAL_TOL):
    """The samples (x, y, depth, twt) stand on one vertical: none strays
    more than `tol` from their mean position (no sample: vertical)."""
    if not samples:
        return True
    x = sum(s[0] for s in samples) / len(samples)
    y = sum(s[1] for s in samples) / len(samples)
    return all(math.hypot(s[0] - x, s[1] - y) <= tol for s in samples)


def extent_vertical(fields, tol=VERTICAL_TOL):
    """A trajectory whose fields hold its extent stands on one vertical: none
    of its points strays more than `tol` from the extent's centre. True without
    an extent, nothing says otherwise."""
    extent = extent_of(fields)
    if extent is None:
        return True
    x0, x1, y0, y1 = extent
    return math.hypot(x1 - x0, y1 - y0) / 2.0 <= tol


def vertical_only(logs, tol=VERTICAL_TOL):
    """`logs` [(name, title, samples)] split into those of a vertical
    well and the names of the deviated ones: a column stands for ONE
    place, a deviated well is not made one."""
    kept, gone = [], []
    for log in logs:
        (kept if vertical(log[2], tol) else gone).append(log)
    return kept, [log[0] for log in gone]


def wells_columns(logs, step=None, least=2, describe=None):
    """The columns of `logs` [(name, title, samples)] — a well's time
    log, its integrated sonic, its markers, or a position over surface
    pairs: [(name, (x, y), points, source)], those without `least`
    usable samples left out; `step` the shared depth step, chosen from the
    deepest when None; `describe(title, samples)` the source said, "<title>,
    <n> samples" by default. Returns (columns, step)."""
    usable = [(w, title, s) for w, title, s in logs if curve(s, least)[0]]
    if not usable:
        return [], step or STEPS[2]
    if step is None:
        # the deepest USABLE depth: a sample out of order below it is no depth
        step = nice_step(max(curve(s, least)[0][-1] for _w, _t, s in usable))
    out = []
    for well, title, samples in usable:
        (x, y), points = column_points(samples, step, least)
        if not points:
            continue
        source = describe(title, samples) if describe else f"{title}, {len(samples)} samples"
        out.append((well, (x, y), points, source))
    return out, step


# ------------------------------------------------------------- sonic logs
# a sonic unit and its factor: to a slowness in s/m, or to a velocity in m/s
SLOWNESS_UOMS = {"us/ft": 1e-6 / 0.3048, "us/f": 1e-6 / 0.3048, "us/m": 1e-6, "ms/m": 1e-3, "s/m": 1.0}
VELOCITY_UOMS = {"m/s": 1.0, "ft/s": 0.3048, "km/s": 1000.0}
VP_RANGE = (1200.0, 7500.0)     # m/s: a compressional velocity in rock; outside, a spike or a gap
REPLACEMENT_V = 2000.0          # m/s, from the zero to a sonic log's top when no model converts there
# a shear sonic is no time-depth law
_SHEAR = re.compile(r"DTS|SHEAR|S[-_ ]?WAVE|S[-_ ]?VEL|\bVS\b", re.IGNORECASE)
_VELOCITY = re.compile(r"VEL|\bV(P|INT|RMS|AV)\b", re.IGNORECASE)


def is_velocity_title(title):
    """A property named as a compressional velocity."""
    return bool(_VELOCITY.search(title or "")) and not _SHEAR.search(title or "")


def sonic_kind(title, uom):
    """"slowness" (DT), "velocity" (Vp) or None: the unit decides, and a
    shear channel by its name is none."""
    if _SHEAR.search(str(title or "")):
        return None
    u = str(uom or "").strip().lower()
    if u in SLOWNESS_UOMS:
        return "slowness"
    if u in VELOCITY_UOMS:
        return "velocity"
    return None


def sonic_rank(title):
    """Which of a well's sonic logs makes its column, the smaller first: a
    log calibrated on the checkshots ("CKS"), then an edited or filtered
    one, then the rest."""
    t = str(title or "").upper()
    if "CKS" in t:
        return 0
    if "EDIT" in t or "FILTER" in t:
        return 1
    return 2


def pick_sonic_logs(channels):
    """One sonic log per well out of `channels` [(well, uuid, title, uom)]:
    [(well, uuid, title, uom)], the wells in the order met."""
    best = {}
    order = []
    for well, uuid, title, uom in channels:
        if sonic_kind(title, uom) is None:
            continue
        if well not in best:
            order.append(well)
            best[well] = (well, uuid, title, uom)
        elif sonic_rank(title) < sonic_rank(best[well][2]):
            best[well] = (well, uuid, title, uom)
    return [best[w] for w in order]


def sonic_velocity(value, uom):
    """The compressional velocity (m/s) a sonic value says, None outside
    VP_RANGE (a spike, a gap written as a number)."""
    u = str(uom or "").strip().lower()
    if u in SLOWNESS_UOMS:
        s = value * SLOWNESS_UOMS[u]
        v = 1.0 / s if s > 0 else math.nan
    elif u in VELOCITY_UOMS:
        v = value * VELOCITY_UOMS[u]
    else:
        return None
    return v if VP_RANGE[0] <= v <= VP_RANGE[1] else None


def sonic_samples(fields, top_twt):
    """(x, y, depth, twt_ms) samples of a sonic log: its velocities
    integrated down from its top (two-way: 2 dz / v), the time at the top
    being `top_twt(x, y, depth)`. [] under two usable values."""
    uom = (fields or {}).get("uom")
    nodes = []
    for x, y, z, value in channel_nodes(fields):
        v = sonic_velocity(value, uom)
        if v is not None:
            nodes.append((x, y, z, v))
    if len(nodes) < 2:
        return []
    x0, y0, z0, _v = nodes[0]
    t = float(top_twt(x0, y0, z0))
    out = [(x0, y0, z0, t)]
    for (_xa, _ya, za, va), (xb, yb, zb, vb) in zip(nodes, nodes[1:]):
        if zb <= za:
            continue
        t += 1000.0 * (zb - za) * (1.0 / va + 1.0 / vb)
        out.append((xb, yb, zb, t))
    return out


# --------------------------------------------- surfaces and their features
# words of a horizon's name that do not tell one horizon from another
# ("Hugin_Fm_Top" and "Hugin Fm_ Top" are one; "Base" is kept)
_NAME_NOISE = {"fm", "formation", "gp", "group", "top", "horizon", "surface", "mbr", "member"}
SURFACE_COLUMNS = 5             # columns along x and along y over a pair of surfaces


def pair_key(title):
    """A horizon's name as pairs are matched on: its words lower-cased,
    the noise of `_NAME_NOISE` dropped ("Hugin_Fm_Top" -> "hugin")."""
    words = [w for w in re.split(r"[^0-9a-z]+", str(title or "").lower()) if w]
    kept = [w for w in words if w not in _NAME_NOISE]
    return " ".join(kept or words)


def pairs_of(left, right):
    """One-to-one pairs of `left` and `right` [(feature uuid, title,
    payload)]: the same feature first, then the same name (`pair_key`).
    [(left item, right item)], in the order of `left`."""
    out, used = [], set()
    for how in ("feature", "name"):
        for item in left:
            if any(item is a for a, _b in out):
                continue
            for k, other in enumerate(right):
                if k in used:
                    continue
                if (how == "feature" and item[0] and item[0] == other[0]) or \
                        (how == "name" and pair_key(item[1]) and pair_key(item[1]) == pair_key(other[1])):
                    out.append((item, other))
                    used.add(k)
                    break
    order = {id(item): i for i, item in enumerate(left)}
    return sorted(out, key=lambda p: order[id(p[0])])


def _xml_root(text):
    import xml.etree.ElementTree as ET
    try:
        return ET.fromstring(text) if text and text.lstrip().startswith("<") else None
    except ET.ParseError as exc:
        print(f"[fespp] time-depth pre-fill: an object's XML not read ({exc})", flush=True)
        return None


def _first(el, name):
    """The first element under `el` whose local name is `name`."""
    if el is None:
        return None
    for c in el.iter():
        if c.tag.rsplit("}", 1)[-1] == name:
            return c
    return None


def _text(el, name):
    c = _first(el, name)
    return (c.text or "").strip() if c is not None else ""


def xml_refs(text, *names):
    """The uuid each reference `names` of an object's XML designates ("" for
    one it lacks), and its own title: (uuid, ..., title)."""
    root = _xml_root(text)
    refs = tuple(_text(_first(root, n), "UUID").lower() for n in names)
    return refs + (_text(_first(root, "Citation"), "Title"),)


def surface_reader(fields):
    """A 2D grid's elevation at (x, y) out of its "<uuid>|surface" fields
    (lattice, nodes, stride, z): ``(at, extent)`` — at(x, y) -> z, bilinear
    on the nodes kept, None outside or by a hole. None without them."""
    import numpy as np
    f = fields or {}
    lat, nodes, stride, z = (numbers(f.get(k)) for k in ("lattice", "nodes", "stride", "z"))
    if len(lat) != 6 or len(nodes) != 2 or not z:
        return None
    s = int(stride[0]) if stride and stride[0] >= 1 else 1
    ki, kj = (int(nodes[0]) + s - 1) // s, (int(nodes[1]) + s - 1) // s
    if ki < 2 or kj < 2 or len(z) != ki * kj:
        return None
    zz = np.asarray(z, float).reshape(kj, ki)
    ox, oy = lat[0], lat[1]
    ax, ay, bx, by = lat[2] * s, lat[3] * s, lat[4] * s, lat[5] * s
    det = ax * by - ay * bx
    if det == 0:
        return None

    def at(x, y):
        a = ((x - ox) * by - (y - oy) * bx) / det
        b = (ax * (y - oy) - ay * (x - ox)) / det
        if not (0.0 <= a <= ki - 1 and 0.0 <= b <= kj - 1):
            return None
        i, j = min(int(a), ki - 2), min(int(b), kj - 2)
        u, w = a - i, b - j
        v = ((1 - u) * (1 - w) * zz[j, i] + u * (1 - w) * zz[j, i + 1]
             + (1 - u) * w * zz[j + 1, i] + u * w * zz[j + 1, i + 1])
        return None if math.isnan(v) else float(v)

    xs = [ox, ox + ax * (ki - 1), ox + bx * (kj - 1), ox + ax * (ki - 1) + bx * (kj - 1)]
    ys = [oy, oy + ay * (ki - 1), oy + by * (kj - 1), oy + ay * (ki - 1) + by * (kj - 1)]
    return at, (min(xs), max(xs), min(ys), max(ys))


def positive_down(z, fields):
    """`z` as a depth or a time counted downward, as the object's CRS
    counts it (`depth_oriented`)."""
    down = str((fields or {}).get("depth_oriented", "true")).lower() != "false"
    return z if down else -z


def oriented(at, fields, factor=1.0):
    """`at` (a surface reader) answering a value counted downward
    (`positive_down`), times `factor` (a time unit to the millisecond)."""
    def read(x, y):
        z = at(x, y)
        return None if z is None else positive_down(z, fields) * factor
    return read


def overlap(a, b):
    """The extent two extents share, None when they share none."""
    x0, x1, y0, y1 = max(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3])
    return (x0, x1, y0, y1) if x1 > x0 and y1 > y0 else None


def marker_interpretations(text):
    """The uuid of the interpretation each marker of a marker frame's XML
    stands for, in the frame's order ("" for one without)."""
    root = _xml_root(text)
    if root is None:
        return []
    return [_text(_first(el, "Interpretation"), "UUID").lower()
            for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "WellboreMarker"]


def marker_points(fields, interps=None):
    """The markers of a marker frame's fields: [(feature uuid, feature
    title, x, y, depth)] for those standing somewhere with a feature; the
    depth counted downward. With `interps` (`marker_interpretations`), the
    first of each is its interpretation's uuid instead, a marker without
    one left out."""
    f = fields or {}
    xyz = numbers(f.get("xyz"))
    out = []
    for i in range(len(xyz) // 3):
        feature = f.get(f"marker_feature.{i}") or ""
        uuid, _sep, title = feature.partition("|")
        if interps is not None:
            uuid = interps[i] if i < len(interps) else ""
        x, y, z = xyz[3 * i], xyz[3 * i + 1], xyz[3 * i + 2]
        if not uuid or any(math.isnan(n) for n in (x, y, z)):
            continue
        out.append((uuid.lower(), title, x, y, positive_down(z, f)))
    return out


def marker_samples(markers, time_of):
    """(x, y, depth, twt_ms) of the markers [(feature uuid, title, x, y,
    depth)] a time horizon answers for: `time_of(feature uuid, title, x,
    y)` -> the two-way time there, or None."""
    out = []
    for uuid, title, x, y, depth in markers:
        t = time_of(uuid, title, x, y)
        if t is not None and t > 0 and depth > 0:
            out.append((x, y, depth, t))
    out.sort(key=lambda s: s[2])
    return out


def pair_samples(pairs, n=SURFACE_COLUMNS):
    """Columns from surface pairs [(time_at, depth_at, extent)] (each
    reader giving a two-way time in ms, a depth in m, counted downward):
    [(name, samples)] for the n × n positions over the pairs' extents where
    at least one pair answers, a sample per pair answering there; named S1,
    S2… in that order, from the south-west corner eastward, row by row
    northward, the positions where no pair answers skipped."""
    boxes = [e for _t, _d, e in pairs if e is not None]
    if not boxes:
        return []
    x0, x1 = min(b[0] for b in boxes), max(b[1] for b in boxes)
    y0, y1 = min(b[2] for b in boxes), max(b[3] for b in boxes)
    out = []
    for r in range(n):
        for c in range(n):
            x = x0 + (c + 0.5) * (x1 - x0) / n
            y = y0 + (r + 0.5) * (y1 - y0) / n
            samples = []
            for time_at, depth_at, _e in pairs:
                t, d = time_at(x, y), depth_at(x, y)
                if t is not None and d is not None and t > 0 and d > 0:
                    samples.append((x, y, d, t))
            if samples:
                samples.sort(key=lambda s: s[2])
                out.append((f"S{len(out) + 1}", samples))
    return out


# what some exporters put in front of a well's title ("well_feature_NO_15_9-F-5_B75BED"):
# the kind of the object, not its name
_WELL_PREFIX = re.compile(r"^(well(bore)?_(feature|trajectory|interpretation)_)", re.IGNORECASE)


def column_name(well):
    """A column's name out of a well's title: the title, less the object
    kind an exporter may write in front of it, at most NAME_MAX characters."""
    name = _WELL_PREFIX.sub("", str(well or "").strip()).strip()
    return name[:NAME_MAX] or None
