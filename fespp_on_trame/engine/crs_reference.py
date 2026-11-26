"""Each object's vertical domain and the session's reference CRS — pure,
over the tree (the PO's manager, 28/10).

Depth and time are two vertical references, never mixed in one view: the
FESPP plugin says which an object is (`vdomain`: "depth" or "time", from
the type of its local CRS) and in which local CRS it is placed (`crs`, the
CRS's uuid), on every representation and on its container; a property
takes its representation's.

Several CRS: the plugin already places every object in the PROJECTED CRS
of its local CRS, so two local CRS of the same EPSG code coincide. An
object of another code is reprojected into the session's reference on the
fly (geo.transformer, geo.map_pdc_points). The reference is by default
the CRS whose code carries the most objects — the least reprojection when
everything shows — and the reader may choose another (the CRS card). An
object whose CRS or code is unknown has no domain and is never moved: it
is drawn as the file says.
"""
from collections import Counter

DOMAINS = ("depth", "time")

# the factor from a unit to the metre (depth) or to the millisecond (time)
_TO_METRE = {"m": 1.0, "metre": 1.0, "meter": 1.0, "km": 1000.0,
             "ft": 0.3048, "foot": 0.3048, "ftus": 1200.0 / 3937.0, "us survey foot": 1200.0 / 3937.0}
_TO_MS = {"ms": 1.0, "millisecond": 1.0, "s": 1000.0, "second": 1000.0}


def domain_of(tree, node_id):
    """"depth", "time", or None: the nearest `vdomain` at or above the node
    (a property takes its representation's, a folder its object's); a
    container is the object it wraps — the plugin sets the domain on that
    representation, below it."""
    value = tree.find_parent_attribute_value(node_id, "vdomain")
    if value is None and node_id is not None and tree.find_type(node_id) == "GridContainer":
        value = _first_below(tree, node_id)
    return value if value in DOMAINS else None


def _first_below(tree, node_id):
    """The first `vdomain` found at or under the node, None without one."""
    for nid, _children in tree.iter_nodes(node_id):
        value = tree.find_attribute_value(nid, "vdomain")
        if value:
            return value
    return None


def domain_held(tree, node_id):
    """The domain of what the node's row draws: its own (`domain_of`), or —
    a wellbore, one of its folders, which carry none and stand for what they
    hold — the first one found under it."""
    value = domain_of(tree, node_id)
    if value is None and node_id is not None:
        value = _first_below(tree, node_id)
    return value if value in DOMAINS else None


# the fine types of a 2D grid's node
GRID2D_TYPES = ("Grid2d", "Grid2dRepresentation")


def grids_by_domain(tree):
    """{"depth": n, "time": n}: the 2D grids of the tree in each vertical
    domain (`domain_of`), each counted once, one of no known domain in
    neither — read on the tree alone, a stub left on an ETP store
    included."""
    out = dict.fromkeys(DOMAINS, 0)
    if tree is None or getattr(tree, "_data_assembly", None) is None:
        return out
    seen = set()
    for nid, _children in tree.iter_nodes():
        if tree.find_type(nid) not in GRID2D_TYPES:
            continue
        key = (tree.find_path(nid) or "").rsplit("/", 1)[-1] or nid
        domain = domain_of(tree, nid)
        if domain in out and key not in seen:
            seen.add(key)
            out[domain] += 1
    return out


def crs_of(tree, node_id):
    """The uuid of the local CRS the node is placed in, or None."""
    return tree.find_parent_attribute_value(node_id, "crs") or None


def objects_by_crs(tree):
    """{crs uuid: [node id, ...]}: the representations placed in each local
    CRS — the nodes carrying the attribute, a container counted through its
    geometry leaf only."""
    out = {}
    for nid, _children in tree.iter_nodes():
        uuid = tree.find_attribute_value(nid, "crs")
        if uuid and tree.find_type(nid) != "GridContainer":
            out.setdefault(uuid, []).append(nid)
    return out


def default_reference(counts, infos):
    """The local CRS the session refers to by default: among the CRS whose
    EPSG code is known, those of the code carrying the most objects, and of
    them the one carrying the most; ties broken by the smaller code, then
    the uuid, so a reload gives the same answer. None when no CRS knows its
    code. `counts`: {uuid: object count}; `infos`: {uuid: the
    geo.crs_info_from_fields of that CRS}."""
    by_code = Counter()
    for uuid, n in counts.items():
        code = (infos.get(uuid) or {}).get("epsg")
        if code:
            by_code[code] += n
    if not by_code:
        return None
    code = max(by_code.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    same_code = sorted(u for u in counts if (infos.get(u) or {}).get("epsg") == code)
    return max(same_code, key=lambda u: counts[u])


def _vertical_factor(info, reference):
    """The factor taking `info`'s vertical values into `reference`'s unit,
    1.0 when a unit is not known (nothing is guessed)."""
    table, key = (_TO_MS, "time_unit") if info.get("time") else (_TO_METRE, "vertical_unit")
    if bool(info.get("time")) != bool(reference.get("time")):
        return 1.0  # depth and time never meet: each view keeps its own
    src = table.get((info.get(key) or "").strip().lower())
    dst = table.get((reference.get(key) or "").strip().lower())
    return src / dst if src and dst else 1.0


def moves(infos, reference_uuid):
    """{crs uuid: (src epsg, dst epsg or None, z factor)} for every CRS
    whose objects must move to sit in the reference: another EPSG code
    (dst set: reprojected), another vertical unit (z scaled). A CRS
    already in the reference's code and unit, or whose code is unknown on
    either side, is absent — drawn as the plugin placed it."""
    reference = infos.get(reference_uuid) or {}
    ref_code = reference.get("epsg")
    out = {}
    for uuid, info in infos.items():
        if uuid == reference_uuid or not info:
            continue
        code = info.get("epsg")
        dst = ref_code if code and ref_code and code != ref_code else None
        factor = _vertical_factor(info, reference)
        if dst is not None or factor != 1.0:
            out[uuid] = (code, dst, factor)
    return out


def move_points(xyz, move):
    """(N, 3) points of one object moved by a `moves` entry: x, y
    reprojected to the reference's code (geo.transformer), z scaled."""
    import numpy as np
    from fespp_on_trame.engine import geo
    src, dst, factor = move
    xyz = np.array(xyz, dtype=float, copy=True).reshape(-1, 3)
    if dst is not None:
        x, y = geo.transformer(src, dst).transform(xyz[:, 0], xyz[:, 1])
        xyz[:, 0], xyz[:, 1] = x, y
    if factor != 1.0:
        xyz[:, 2] *= factor
    return xyz
