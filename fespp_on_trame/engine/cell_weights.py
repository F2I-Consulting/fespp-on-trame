"""The weight of a cell, for the statistics that are means of a product.

An arithmetic mean gives one vote per cell. On an IJK grid whose layers
are thin in the reservoir and thick above it, that is not the reservoir's
porosity: the cells must be weighed by what they hold. This module hands
the statistics two weights per representation, both index-aligned with
its property arrays:

  * the CELL VOLUME — `volumetrics_dispatch.cell_geometry`, the very same
    read the Volumetrics card cubes, so the two panels can never disagree
    about what a cell is worth;
  * the PORE VOLUME — volume x net-to-gross x porosity, the two terms
    picked by kind exactly as the Volumetrics card picks them.

Nothing is silent: when a weight cannot be produced, `note` says which
one and why, and the row says it.

Two caches, because the two halves of a weight live on different clocks:

  * the GEOMETRY (`geometry_for`): the volume and centre of every cell.
    Seconds of work on a million-cell grid, and a grid's cells do not
    change when a property is ticked beside them. Kept per representation for
    as long as the file is loaded; a hit is checked against the dataset's
    cell and point counts, so a rebuilt block with the same cells is
    served and a different one is not. `clear_geometry()` runs when a new
    assembly arrives (an import, an ETP connection).
  * the WEIGHTS (`weights_for`): geometry x the porosity and net-to-gross
    read at this moment. Milliseconds. `clear()` runs beside every
    `load_generation` bump and whenever the loaded arrays change, since a
    porosity arriving or leaving changes what a cell is worth.

Neither cache key carries a load generation: invalidation is explicit,
through the two clear functions above.
"""
from collections import OrderedDict

_CACHE = OrderedDict()
_CACHE_MAX = 4
_GEOMETRY = OrderedDict()
_GEOMETRY_MAX = 4


def clear():
    """Drop every cached weight; the geometry stays."""
    _CACHE.clear()


def clear_geometry():
    """Drop the cell geometry of every representation — a new file's cells
    are not the last file's."""
    _GEOMETRY.clear()


def geometry_for(rep_path, dataset):
    """``(volumes, centre_z)`` of every cell of `dataset`, index-aligned
    with its property arrays, computed once per representation and served
    from the cache while the dataset still has the same cell and point
    counts. The read itself is `volumetrics_dispatch.cell_geometry`."""
    from fespp_on_trame.engine import volumetrics_dispatch as vd
    try:
        n_cells = int(dataset.GetNumberOfCells())
        n_points = int(dataset.GetNumberOfPoints())
    except Exception:
        n_cells = n_points = -1
    hit = _GEOMETRY.get(rep_path) if rep_path else None
    if hit is not None and n_cells >= 0 and hit[0] == n_cells and hit[1] == n_points:
        _GEOMETRY.move_to_end(rep_path)
        return hit[2], hit[3]
    import time
    t0 = time.monotonic()
    vol, zc = vd.cell_geometry(dataset)
    dt = time.monotonic() - t0
    if dt > 1.0:
        # the one cost a grid pays once per session, said in the log so a
        # slow first row is not taken for a slow matrix
        print(f"[fespp] cell geometry of {rep_path or 'the dataset'}: {n_cells}"
              f" cells in {dt:.1f} s (once per grid, for the weighted means)",
              flush=True)
    if rep_path and n_cells >= 0:
        _GEOMETRY[rep_path] = (n_cells, n_points, vol, zc)
        while len(_GEOMETRY) > _GEOMETRY_MAX:
            _GEOMETRY.popitem(last=False)
    return vol, zc


def _numpy():
    import numpy as np
    return np


def _type_label(t):
    """`"TriangulatedSet"` -> `"triangulated set"` — the type as a sentence
    names it, for the note that refuses a weighted mean."""
    from fespp_on_trame.engine import volumetrics_dispatch as vd
    known = vd._KIND_LABEL.get(t)
    if known:
        return known
    out = []
    for ch in str(t or ""):
        if ch.isupper() and out and not out[-1].endswith(" "):
            out.append(" ")
        out.append(ch)
    return ("".join(out).strip().lower() or "representation")


def _title_of(tree, rep_path):
    from fespp_on_trame.engine import stats_dispatch
    try:
        return stats_dispatch._rep_title_for_array_path(tree, rep_path) or rep_path
    except Exception:
        return rep_path


def _empty(note, poro_title="", ntg_title=""):
    return {"volume": None, "pore": None, "n": 0, "poro_title": poro_title,
            "ntg_title": ntg_title, "poro_path": "", "ntg_path": "",
            "real_idx": None, "note": note}


def weights_for(state, tree, source_registry, rep_path):
    """``{"volume", "pore", "n", "poro_title", "ntg_title", "poro_path",
    "ntg_path", "real_idx", "note"}``.

    `volume` is the volume of EVERY cell of `rep_path`, NaN on a blanked
    or hidden one, index-aligned with the representation's property
    arrays; `pore` is volume x net-to-gross x porosity (a % property read
    as a fraction), None when no porosity is on the grid; `note` is the
    sentence the card shows when something is missing. `poro_path` /
    `ntg_path` name the two terms so a card ABOUT one of them can say the
    weight is the property itself, and `real_idx` the realization they were
    read at — one weight per representation, so a row pinned elsewhere is
    weighed by this one. Cached per `rep_path` until `clear()`."""
    if not rep_path:
        return _empty("")
    if rep_path in _CACHE:
        return _CACHE[rep_path]
    out = _compute(state, tree, source_registry, rep_path)
    _CACHE[rep_path] = out
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return out


def _compute(state, tree, source_registry, rep_path):
    from fespp_on_trame.engine import property_values, volumetrics_dispatch as vd
    np = _numpy()
    title = _title_of(tree, rep_path)
    try:
        nid = tree.find_node_id(rep_path) if tree is not None else None
    except Exception:
        nid = None
    if nid is None:
        return _empty(f"{title} is not in the tree: no weighted mean.")
    rep_type = ""
    try:
        rep_type = tree.find_type(nid) or ""
    except Exception:
        rep_type = ""
    if rep_type not in vd._GRIDS:
        return _empty(f"{title} is a {_type_label(rep_type)}: it has no cells"
                      " with a volume, so no weighted mean.")
    unreadable = (f"The cells of {title} could not be read: tick it in the"
                  " tree for a weighted mean.")
    try:
        props = vd.property_choices(state, tree, rep_path)
    except Exception:
        props = []
    by_path = {p["path"]: p for p in props}
    picks = vd.auto_pick(props) if props else {}
    anchor = next((picks.get(k) for k in ("poro", "ntg", "sw", "region")
                   if picks.get(k)), None) or next(iter(by_path), None)
    try:
        dataset = vd._block_of(state, tree, source_registry, rep_path, anchor)
    except Exception:
        dataset = None
    if dataset is None:
        return _empty(unreadable)
    try:
        vol = np.abs(geometry_for(rep_path, dataset)[0])
    except Exception:
        return _empty(unreadable)
    n = int(len(vol))
    if not n:
        return _empty(unreadable)

    notes = []

    from fespp_on_trame.engine import stats_dispatch
    reals = {}

    def _term(key):
        """(values|None, title, note) — a picked term read as a fraction.

        The realization is the session's default for that term and is
        recorded: the weight is built ONCE per representation, so a row
        pinned to another realization is weighed by this one's porosity and
        the card has to say so."""
        path = picks.get(key)
        if not path or path not in by_path:
            return None, "", ""
        t = by_path[path].get("title") or path
        try:
            reals[key] = stats_dispatch._default_real_idx(state, tree, path)
            v = property_values.values_for(state, tree, source_registry,
                                           path, rep_path,
                                           real_idx=reals[key])
        except Exception:
            v = None
        if v is None or len(v) != n:
            return None, t, (f"'{t}' does not index the cells of {title}"
                             f" ({0 if v is None else len(v)} values for"
                             f" {n} cells): the pore-volume-weighted mean is"
                             " not reported.")
        factor = vd.fraction_factor(by_path[path].get("unit"))
        return (np.asarray(v, float) * factor if factor != 1.0
                else np.asarray(v, float)), t, ""

    phi, poro_title, poro_note = _term("poro")
    ntg, ntg_title, ntg_note = _term("ntg")
    pore = None
    if phi is None:
        notes.append(poro_note or (f"No porosity property on {title}: the"
                                   " pore-volume-weighted mean is not"
                                   " reported."))
    elif ntg is None and ntg_note:
        notes.append(ntg_note)
    else:
        if ntg is None:
            notes.append(f"Net-to-gross taken as 1 on {title}: no"
                         " net-to-gross property.")
            ntg = np.ones(n)
        pore = vol * ntg * phi
    return {"volume": vol, "pore": pore, "n": n, "poro_title": poro_title,
            "ntg_title": ntg_title,
            # the two terms' own paths: a row ABOUT one of them would be
            # weighted by itself, which the card has to disclose
            "poro_path": picks.get("poro") or "", "ntg_path": picks.get("ntg") or "",
            "real_idx": reals.get("poro"), "note": " ".join(notes)}
