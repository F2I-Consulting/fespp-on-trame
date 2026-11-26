"""Volumetrics with fluid contacts — GRV → NRV → PV → HCPV, per region and
per fluid zone.

Anything made of cells that have a volume can be cubed: an IJK grid, an
unstructured grid, a sub-representation of cells (a region, a zone, a fault
block carved out of a grid) and a blocked wellbore (the cells the well
crosses — what the well drains, at first sight). A gas-oil contact and an
oil-water contact are two depths (positive down, the log view's
convention). A cell belongs to the fluid zone of its centre: the gas cap
above the GOC, the oil leg between the contacts, water below the OWC — one
contact alone splits above / below. Cell volumes come from VTK's
`vtkCellSizeFilter` on the representation's block as loaded; net-to-gross,
porosity and water saturation are its own properties, picked by kind (PWLS
ancestry, then words) and changeable; a % property is read as a fraction.
A region property — a discrete or categorical one: fault blocks, zones,
facies — splits the totals. Read-only; the approximation — whole cells
attributed by their centre, none split at a contact — is stated on the
table, and so are the cells without a volume (a sub-representation of
faces or edges) left out.
"""
import math

from fespp_on_trame.engine import pwls_kinds, stats_dispatch, welllog_dispatch
from fespp_on_trame.engine.utils import numfmt

# what has cells with a volume: the grids, a cell sub-representation, the
# blocked wellbore (its cells are the grid's, mirrored with the properties)
_GRIDS = ("IjkGrid", "UnstructuredGrid", "Sub", "BlockedWellbore")
_KIND_LABEL = {"IjkGrid": "IJK grid", "UnstructuredGrid": "unstructured grid",
               "Sub": "sub-representation", "BlockedWellbore": "blocked wellbore"}
_INTEGER_TYPES = ("DiscreteProperty", "CategoricalProperty")

# what to look for, by kind (PWLS ancestry) then by word in the kind or title
_TARGETS = {
    "poro": ("porosity", ("poro", "phi")),
    "ntg": ("net to gross ratio", ("ntg", "net to gross", "net_to_gross", "netgross", "net/gross")),
    "sw": ("water saturation", ("swat", "sw", "water sat")),
}
_REGION_WORDS = ("zone", "region", "fault", "block", "segment", "facies", "unit", "layer", "fluid")


def _numpy():
    import numpy as np
    return np


def fraction_factor(unit):
    """A property declared in a percentage unit (%, p.u.) is read as a
    fraction — node_kinds holds the vocabulary."""
    from fespp_on_trame.engine import node_kinds
    return node_kinds.percent_factor(unit)


# ---- what the session offers --------------------------------------------

def is_volume_rep(tree, rep_path):
    nid = tree.find_node_id(rep_path) if rep_path else None
    return nid is not None and (tree.find_type(nid) or "") in _GRIDS


def grid_choices(state, tree):
    """``[{path, title, type}]`` — the loaded representations that have
    cells with a volume: grids, cell sub-representations, blocked
    wellbores."""
    out = []
    for p in list(getattr(state, "ui_loaded_rep_paths", None) or []):
        nid = tree.find_node_id(p)
        if nid is None:
            continue
        t = tree.find_type(nid) or ""
        if t not in _GRIDS:
            continue
        # a grid's geometry leaf is titled "SolidColor": name the grid
        title = stats_dispatch._rep_title_for_array_path(tree, p) or p
        label = _KIND_LABEL.get(t, t)
        out.append({"path": p, "title": f"{title} ({label})" if t != "IjkGrid" else title,
                    "type": t})
    return out


def property_choices(state, tree, rep_path):
    """``[{path, title, kind, unit, type}]`` — the loaded properties of the
    grid, and the derived ones defined on it (a pay flag from the cutoffs
    is a net-to-gross)."""
    out = []
    for p in list(getattr(state, "ui_loaded_array_paths", None) or []):
        if stats_dispatch._rep_path_for_array_path(tree, p) != rep_path:
            continue
        nid = tree.find_node_id(p)
        if nid is None:
            continue
        out.append({
            "path": p,
            "title": stats_dispatch._title_and_kind(tree, p)[0] or p,
            "kind": welllog_dispatch._attr(tree, nid, "propertyKind"),
            "unit": welllog_dispatch._attr(tree, nid, "uom"),
            # the value type: the plugin's propType on synthetic nodes, the
            # node's own class (DiscreteProperty…) on a plain property
            "type": tree.find_prop_type(nid) or tree.find_type(nid) or "",
        })
    try:
        from fespp_on_trame.engine import derived_props
        store = derived_props.get_store()
        for d in (store._defs.values() if store is not None else []):
            if d.get("rep_path") != rep_path or d.get("stale"):
                continue
            out.append({
                "path": derived_props.path_for(d["rep_path"], d["name"]),
                "title": f"{d['name']} (derived)", "kind": "",
                "unit": d.get("uom") or "", "type": d.get("prop_kind") or "",
                # what the recipe IS: a per-cell percentile across the
                # realizations cannot be cubed into a percentile of the
                # volume, and the card has to say so
                "derived_type": d.get("type", "expr"),
                "quantile": d.get("quantile"),
            })
    except Exception:
        pass
    return out


def _matches(prop, target_kind, words):
    kind = prop.get("kind") or ""
    if kind:
        rel = pwls_kinds.relation(kind, target_kind)
        if rel is not None and rel[1] in ("same", "a under b"):
            return True
    hay = f"{kind} {prop.get('title') or ''}".lower()
    return any(w in hay for w in words)


def auto_pick(props):
    """``{poro, ntg, sw, region}`` — a path or None each, from the kinds
    first (a total porosity IS a porosity), the titles second."""
    picks = {}
    for key, (target_kind, words) in _TARGETS.items():
        picks[key] = next((p["path"] for p in props if _matches(p, target_kind, words)), None)
    picks["region"] = next(
        (p["path"] for p in props
         if (p.get("type") or "") in _INTEGER_TYPES
         and any(w in (p.get("title") or "").lower() for w in _REGION_WORDS)), None)
    return picks


# ---- a percentile term cannot be cubed --------------------------------------

# the terms that MULTIPLY into a volume; a region only splits the rows, so a
# percentile picked there says nothing wrong about the totals
_VOLUME_TERMS = ("poro", "ntg", "sw")


def _exceedance_label(q):
    """The reserves label of a numpy quantile: the calculator builds P90
    from the 10th percentile and P10 from the 90th (PRMS exceedance)."""
    return f"P{int(round(100.0 - float(q)))}"


def percentile_warnings(params, props):
    """``[{term, path, title, quantile, label, text}]`` — one entry per term
    of the card that names a per-cell percentile recipe. Per-cell
    percentiles do not add up: the volume computed from one is not the
    percentile of the volume. Pure: the card's params and its property
    list, nothing else."""
    by_path = {p.get("path"): p for p in (props or [])}
    out = []
    for term in _VOLUME_TERMS:
        path = (params or {}).get(term)
        p = by_path.get(path) if path else None
        if not p or (p.get("derived_type") or "") != "percentile":
            continue
        try:
            label = _exceedance_label(p.get("quantile"))
        except (TypeError, ValueError):
            label = "percentile"
        title = p.get("title") or path
        out.append({
            "term": term, "path": path, "title": title,
            "quantile": p.get("quantile"), "label": label,
            "text": (f"{title} is a per-cell percentile across realizations:"
                     f" the volume computed from it is not the {label} of the"
                     " volume — cube each realization and take the percentile"
                     " of the volumes."),
        })
    return out


# ---- the arithmetic, pure ----------------------------------------------------

def fluid_zones(depth, goc, owc):
    """Per-cell zone codes from the cell-centre depths: 0 = gas, 1 = oil,
    2 = water; with one contact only, 0 = above it, 2 = below."""
    np = _numpy()
    d = np.asarray(depth, float)
    zone = np.full(d.shape, 1, dtype=int)
    if goc is not None and owc is not None:
        zone[d < goc] = 0
        zone[d >= owc] = 2
    elif goc is not None:
        zone[d < goc] = 0
        zone[d >= goc] = 2
    elif owc is not None:
        zone[d < owc] = 0
        zone[d >= owc] = 2
    else:
        zone[:] = 1
    return zone


def zone_names(goc, owc, surface=None):
    """What each zone is called. One contact names its fluids too: an OWC
    is by definition the base of the oil, a GOC the top of it — so the
    surface volumes know which factor (Bo, Bg) a zone takes. The card has
    no gas-water contact field: a lone OWC with Bg alone given is read as
    one, and the zone above it is gas (`upper_fluid`). With no contact
    the grid names no fluid."""
    if goc is not None and owc is not None:
        return {0: "gas (above GOC)", 1: "oil (GOC–OWC)", 2: "water (below OWC)"}
    if goc is not None:
        return {0: "gas (above GOC)", 2: "oil (below GOC)"}
    if owc is not None:
        return {0: f"{upper_fluid(goc, owc, surface)} (above OWC)",
                2: "water (below OWC)"}
    return {1: "whole grid"}


def zone_fluids(goc, owc, surface=None):
    """{zone code: "gas" | "oil" | "water" | ""} — "" for the whole grid,
    which names no fluid (`surface_fluid` then decides from the factors)."""
    if goc is not None and owc is not None:
        return {0: "gas", 1: "oil", 2: "water"}
    if goc is not None:
        return {0: "gas", 2: "oil"}
    if owc is not None:
        return {0: upper_fluid(goc, owc, surface), 2: "water"}
    return {1: ""}


def upper_fluid(goc, owc, surface=None):
    """The fluid above a LONE OWC: oil, unless Bg alone is given — the
    only way the card is told the contact is a gas-water one."""
    sf = surface or {}
    if goc is None and owc is not None and sf.get("bg") and not sf.get("bo"):
        return "gas"
    return "oil"


def surface_terms(params):
    """The surface-condition factors of `params`, read as numbers or None:
    Bo and Bg (reservoir volume per surface volume, > 0), the recovery
    factors (a fraction; a value above 1 is read as a percentage, and the
    note says so; one still above 1 after that would recover more than is
    in place and is refused). Returns ({bo, bg, rf_oil, rf_gas}, [notes])."""
    out, notes = {}, []
    for key in ("bo", "bg", "rf_oil", "rf_gas"):
        raw = params.get(key)
        label = {"bo": "Bo", "bg": "Bg", "rf_oil": "RF oil", "rf_gas": "RF gas"}[key]
        try:
            v = float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            notes.append(f"{label} {raw!r} is not a number: ignored.")
            v = None
        if v is not None and not math.isfinite(v):
            notes.append(f"{label} {raw!r} is not a finite number: ignored.")
            v = None
        if v is not None and key in ("bo", "bg") and v <= 0:
            notes.append(f"{'Bo' if key == 'bo' else 'Bg'} must be positive:"
                         f" {raw} ignored.")
            v = None
        if v is not None and key.startswith("rf"):
            if v > 1.0:
                notes.append(f"RF {'oil' if key == 'rf_oil' else 'gas'} {raw}"
                             " read as a percentage.")
                v = v / 100.0
            if v < 0 or v > 1.0:
                # 150 read as 150 % would recover more than is in place
                notes.append(f"RF {'oil' if key == 'rf_oil' else 'gas'} must"
                             f" be between 0 and 1 (or 0 and 100 %): {raw}"
                             " ignored.")
                v = None
        out[key] = v
    return out, notes


def surface_fluid(goc, owc, surface):
    """Which fluid a grid with NO contact is taken to hold, for the surface
    volumes: the one whose factor is given; "" when none or both (the
    card then says it cannot choose)."""
    if goc is not None or owc is not None:
        return ""
    bo, bg = (surface or {}).get("bo"), (surface or {}).get("bg")
    if bo and not bg:
        return "oil"
    if bg and not bo:
        return "gas"
    return ""


def aggregate(vol, depth, goc=None, owc=None, phi=None, ntg=None, sw=None, region=None,
              region_labels=None, surface=None):
    """``{rows, totals, cells, active}`` — GRV, NRV, PV, HCPV per (region,
    fluid zone) and per zone. A cell counts where its terms are finite: an
    inactive cell (NaN porosity, NaN volume) is not reservoir; a missing
    net-to-gross means 1, a missing water saturation leaves HCPV empty.
    A row names its region by `region_labels` (``{code: name}``) when the
    file names it, by its code otherwise; the code rides along as
    ``region_code`` (None for the totals and the cells without one).

    `surface` = {bo, bg, rf_oil, rf_gas} takes the HCPV to surface
    conditions, per fluid: an oil zone gives `stoiip` = HCPV / Bo and
    `rec_oil` = STOIIP × RF oil, a gas zone `giip` = HCPV / Bg and
    `rec_gas`; a water zone none; a grid with no contact holds the fluid
    `surface_fluid` names. A factor not given leaves its column None."""
    from fespp_on_trame.engine.utils.categories import label_of
    np = _numpy()
    vol = np.abs(np.asarray(vol, float))
    n = len(vol)
    depth = np.asarray(depth, float)
    # a cell without a volume (a face, an edge — a sub-representation may
    # carry them) is no rock: left out, and counted so the table says so
    no_volume = int(np.sum(np.isfinite(vol) & (vol <= 0.0)))
    active = np.isfinite(vol) & (vol > 0.0) & np.isfinite(depth)
    phi_a = np.asarray(phi, float) if phi is not None else None
    if phi_a is not None:
        active &= np.isfinite(phi_a)
    ntg_a = np.asarray(ntg, float) if ntg is not None else np.ones(n)
    sw_a = np.asarray(sw, float) if sw is not None else None
    zone = fluid_zones(depth, goc, owc)
    sf = dict(surface or {})
    names = zone_names(goc, owc, sf)
    fluids = zone_fluids(goc, owc, sf)
    assumed = surface_fluid(goc, owc, sf)
    if region is not None:
        reg = np.asarray(region, float)
        reg_key = np.where(np.isfinite(reg), np.round(reg), np.nan)
    else:
        reg_key = np.full(n, np.nan)

    def _sum(mask, terms):
        m = mask.copy()
        acc = vol.copy()
        for t in terms:
            acc = acc * t
        m &= np.isfinite(acc)
        return float(acc[m].sum()) if m.any() else 0.0

    def _row(mask, label, zname, code=None, fluid=""):
        cells = int(mask.sum())
        grv = _sum(mask, [])
        nrv = _sum(mask, [ntg_a])
        row = {"region": label, "region_code": code, "fluid": zname, "cells": cells,
               "grv": grv, "nrv": nrv,
               "pv": _sum(mask, [ntg_a, phi_a]) if phi_a is not None else None,
               "hcpv": (_sum(mask, [ntg_a, phi_a, 1.0 - sw_a])
                        if (phi_a is not None and sw_a is not None) else None),
               "stoiip": None, "giip": None, "rec_oil": None, "rec_gas": None}
        hcpv = row["hcpv"]
        if hcpv is not None:
            if fluid == "oil" and sf.get("bo"):
                row["stoiip"] = hcpv / sf["bo"]
                if sf.get("rf_oil") is not None:
                    row["rec_oil"] = row["stoiip"] * sf["rf_oil"]
            if fluid == "gas" and sf.get("bg"):
                row["giip"] = hcpv / sf["bg"]
                if sf.get("rf_gas") is not None:
                    row["rec_gas"] = row["giip"] * sf["rf_gas"]
        return row

    def _summed(rows_, key):
        vals = [r[key] for r in rows_ if r.get(key) is not None]
        return float(sum(vals)) if vals else None

    rows, totals = [], []
    regions = sorted({float(v) for v in reg_key[np.isfinite(reg_key)]}) if region is not None else []
    region_groups = [(label_of(region_labels or {}, v), int(v), reg_key == v)
                     for v in regions]
    if region is not None and (~np.isfinite(reg_key) & active).any():
        region_groups.append(("(no region)", None, ~np.isfinite(reg_key)))
    for code in sorted(names):
        zmask = active & (zone == code)
        fluid = fluids.get(code) or assumed
        if region is not None:
            for label, rcode, rmask in region_groups:
                m = zmask & rmask
                if m.any():
                    rows.append(_row(m, label, names[code], rcode, fluid))
        if zmask.any() or region is None:
            totals.append(_row(zmask, "all", names[code], None, fluid))
    # the grand total mixes fluids: its surface volumes are the zones'
    # summed, each in its own factor
    grand = _row(active, "all", "total")
    for key in ("stoiip", "giip", "rec_oil", "rec_gas"):
        grand[key] = _summed(totals, key)
    totals.append(grand)
    return {"rows": rows, "totals": totals, "cells": n, "active": int(active.sum()),
            "no_volume": no_volume, "surface_fluid": assumed}


# ---- the grid --------------------------------------------------------------

def cell_geometry(dataset):
    """``(volumes, centre_z)`` of EVERY cell of the dataset, index-aligned
    with its property arrays — VTK's cell size filter for the volumes (a
    hexahedron's, with the cell's own orientation), the mean of each cell's
    points for the centre. Not `vtkCellCenters`: it drops the blanked cells,
    so its centres would not line up with the property arrays. A hidden
    cell (ghost bit 32) gets a NaN volume: it is no rock."""
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from vtkmodules.vtkFiltersVerdict import vtkCellSizeFilter
    np = _numpy()
    n = dataset.GetNumberOfCells()
    f = vtkCellSizeFilter()
    f.SetInputData(dataset)
    f.ComputeVolumeOn()
    f.ComputeAreaOff()
    f.ComputeLengthOff()
    f.ComputeVertexCountOff()
    f.Update()
    vol = np.array(vtk_to_numpy(f.GetOutput().GetCellData().GetArray("Volume")), float)
    if len(vol) != n:
        vol = np.full(n, np.nan)
    ghost = dataset.GetCellData().GetArray("vtkGhostType")
    if ghost is not None and ghost.GetNumberOfTuples() == n:
        hidden = (np.array(vtk_to_numpy(ghost)).astype(int) & 32) != 0
        vol = np.where(hidden, np.nan, vol)
    zc = np.full(n, np.nan)
    if dataset.IsA("vtkStructuredGrid"):
        # a lattice: a cell's centre is the mean of its eight corners, read
        # in the grid's own order (i fastest)
        e = dataset.GetExtent()
        ni, nj, nk = e[1] - e[0], e[3] - e[2], e[5] - e[4]
        z = np.array(vtk_to_numpy(dataset.GetPoints().GetData()), float)[:, 2]
        if ni > 0 and nj > 0 and nk > 0 and len(z) == (ni + 1) * (nj + 1) * (nk + 1):
            z = z.reshape(nk + 1, nj + 1, ni + 1)
            zc = sum(z[a:a + nk, b:b + nj, c:c + ni]
                     for a in (0, 1) for b in (0, 1) for c in (0, 1)).ravel() / 8.0
        return vol, zc
    try:
        cells = dataset.GetCells()
        conn = np.array(vtk_to_numpy(cells.GetConnectivityArray()), dtype=np.int64)
        offs = np.array(vtk_to_numpy(cells.GetOffsetsArray()), dtype=np.int64)
        zpts = np.array(vtk_to_numpy(dataset.GetPoints().GetData()), float)[:, 2]
        sizes = np.diff(offs)
        if len(sizes) == n and len(conn):
            sums = np.add.reduceat(zpts[conn], np.minimum(offs[:-1], len(conn) - 1))
            with np.errstate(invalid="ignore", divide="ignore"):
                zc = np.where(sizes > 0, sums / np.maximum(sizes, 1), np.nan)
    except Exception:
        pass
    return vol, zc


def _largest_block(shared_source, selector):
    """The biggest leaf (most cells) under `selector` on the reader's
    output. `welllog_dispatch._fetch_block` hands back the FIRST leaf with
    points, which under a grid's selector can be the few cells of a blocked
    wellbore rather than the grid's."""
    from paraview import servermanager as sm
    from paraview import simple as pvsimple
    eb, best = None, None
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
            return data if data.GetNumberOfCells() else None
        it.InitTraversal()
        while not it.IsDoneWithTraversal():
            leaf = it.GetCurrentDataObject()
            n = getattr(leaf, "GetNumberOfCells", lambda: 0)() if leaf is not None else 0
            if n and (best is None or n > best.GetNumberOfCells()):
                best = leaf
            it.GoToNextItem()
        return best
    except Exception:
        return None
    finally:
        if eb is not None:
            try:
                pvsimple.Delete(eb)
            except Exception:
                pass


def _block_of(state, tree, source_registry, rep_path, anchor):
    """The representation's cells: its own block on the reader's output (a
    grid, a sub-representation, a blocked wellbore — no property needed,
    GRV alone then), else the dataset one of its properties indexes. The
    block first: a property a blocked wellbore mirrors resolves, through
    the property route, to the wellbore's cells, not the grid's."""
    try:
        shared = source_registry.shared_source()
    except Exception:
        shared = None
    ds = _largest_block(shared, rep_path) if shared is not None else None
    if ds is not None and ds.GetNumberOfCells():
        return ds
    if anchor is None:
        return None
    from fespp_on_trame.engine import trajectory_sampling
    return trajectory_sampling._dataset_of(state, source_registry, tree, anchor, rep_path)


def compute(state, tree, source_registry, params):
    """The panel's payload for ``params = {grid, poro, ntg, sw, region, goc,
    owc}``: ``{grid_title, rows, totals, cells, active, no_volume, note,
    units, convention}``."""
    from fespp_on_trame.engine.property_values import values_for
    rep_path = params.get("grid") or ""
    empty = {"rows": [], "totals": [], "cells": 0, "active": 0, "no_volume": 0,
             "units": "m3",
             "convention": "depth positive down; a cell belongs to the zone of its center",
             "grid_title": "", "note": ""}
    nid = tree.find_node_id(rep_path) if rep_path else None
    if nid is None:
        empty["note"] = "Pick a loaded grid, sub-representation or blocked wellbore."
        return empty
    empty["grid_title"] = tree.find_rep_title(nid) or rep_path
    props = {p["path"]: p for p in property_choices(state, tree, rep_path)}
    anchor = next((params.get(k) for k in ("poro", "ntg", "sw", "region")
                   if params.get(k) in props), None) or next(iter(props), None)
    dataset = _block_of(state, tree, source_registry, rep_path, anchor)
    if dataset is None:
        empty["note"] = "Its cells could not be read: is it checked in the tree?"
        return empty
    # the same read the statistics weigh with, cached per representation
    # (engine/cell_weights): cubing a grid twice reads its cells once
    from fespp_on_trame.engine import cell_weights
    vol, zc = cell_weights.geometry_for(rep_path, dataset)
    n = len(vol)
    arrays = {}
    for key in ("poro", "ntg", "sw", "region"):
        path = params.get(key)
        if not path or path not in props:
            continue
        v = values_for(state, tree, source_registry, path, rep_path)
        if v is None or len(v) != n:
            empty["note"] = f"'{props[path]['title']}' does not index the grid's cells"
            return empty
        factor = fraction_factor(props[path].get("unit")) if key != "region" else 1.0
        arrays[key] = v * factor if factor != 1.0 else v

    def _depth(x):
        try:
            return float(x) if x not in (None, "") else None
        except (TypeError, ValueError):
            return None
    goc, owc = _depth(params.get("goc")), _depth(params.get("owc"))
    if goc is not None and owc is not None and goc > owc:
        goc, owc = owc, goc
    surface, surface_notes = surface_terms(params)
    region_labels = {}
    if "region" in arrays:
        from fespp_on_trame.engine.utils import categories
        try:
            shared = source_registry.shared_source()
        except Exception:
            shared = None
        region_labels = categories.labels_for(
            tree, params["region"],
            stats_dispatch._resolve_vtk_name(tree, params["region"])[2], shared)
        region_note = categories.labels_note(tree, params["region"], region_labels)
    else:
        region_note = ""
    out = aggregate(vol, -zc, goc, owc, arrays.get("poro"), arrays.get("ntg"),
                    arrays.get("sw"), arrays.get("region"), region_labels=region_labels,
                    surface=surface)
    out.update({"units": "m3", "grid_title": empty["grid_title"],
                "convention": empty["convention"], "note": "",
                "terms": {k: (props[params[k]]["title"] if params.get(k) in props else "")
                          for k in ("poro", "ntg", "sw", "region")},
                "term_units": {k: (props[params[k]].get("unit") or ""
                                   if params.get(k) in props else "")
                               for k in ("poro", "ntg", "sw", "region")},
                "term_types": {k: (props[params[k]].get("type") or ""
                                   if params.get(k) in props else "")
                               for k in ("poro", "ntg", "sw", "region")},
                "rep_type": _KIND_LABEL.get(tree.find_type(nid) or "", ""),
                "percentile_terms": percentile_warnings(params, list(props.values())),
                "goc": goc, "owc": owc, "surface": surface})
    notes = [w["text"] for w in out["percentile_terms"]] + surface_notes
    if any(surface.get(k) for k in ("bo", "bg")):
        if "sw" not in arrays or "poro" not in arrays:
            notes.append("Bo / Bg need an HCPV: pick a porosity and a water"
                         " saturation for the surface volumes.")
        elif upper_fluid(goc, owc, surface) == "gas":
            notes.append("Bg alone: the zone above the OWC is taken as gas"
                         " (a gas-water contact).")
        elif goc is None and owc is None:
            if out.get("surface_fluid"):
                notes.append(f"No contact: the whole grid is taken as"
                             f" {out['surface_fluid']}"
                             f" ({'Bo' if out['surface_fluid'] == 'oil' else 'Bg'} given).")
            else:
                notes.append("No contact: which fluid fills the grid? Set a"
                             " contact, or give Bo alone (oil) or Bg alone"
                             " (gas) — STOIIP and GIIP left empty.")
    if surface.get("rf_oil") is not None and not surface.get("bo"):
        notes.append("RF oil needs Bo: recoverable oil left empty.")
    if surface.get("rf_gas") is not None and not surface.get("bg"):
        notes.append("RF gas needs Bg: recoverable gas left empty.")
    if "poro" not in arrays:
        notes.append("No porosity picked: GRV and NRV only.")
    elif "sw" not in arrays:
        notes.append("No water saturation picked: HCPV left empty.")
    if out.get("no_volume"):
        notes.append(f"{numfmt.fmt_int(out['no_volume'])} cells without a volume"
                     " (faces or edges) left out.")
    if not out["active"]:
        notes.append("No cell with a volume: nothing to cube.")
    if not math.isfinite(sum(r["grv"] for r in out["totals"])):
        notes.append("The cell volumes are not finite — the geometry is degenerate.")
    if region_note:
        notes.append(f"Region: {region_note}.")
    out["note"] = " ".join(notes)
    return out


def csv_payload(result):
    """`{"name", "header"}` the panel's Copy CSV writes its rows under —
    the representation, the terms and their units, the contacts, the
    convention, the volume unit (raw cubic metres whatever the panel
    shows), the cell counts. Empty when there is nothing to export."""
    from fespp_on_trame.engine.utils import csv_export as ce
    r = result or {}
    if not (r.get("rows") or r.get("totals")):
        return dict(ce.EMPTY_PAYLOAD)
    terms = r.get("terms") or {}
    units = r.get("term_units") or {}
    types = r.get("term_types") or {}

    def _term(key, none):
        t = terms.get(key)
        if not t:
            return none
        u = units.get(key) or ""
        return f"{t} ({u})" if u else t

    contacts = []
    if r.get("goc") is not None:
        contacts.append(f"GOC {r['goc']}")
    if r.get("owc") is not None:
        contacts.append(f"OWC {r['owc']}")
    sf = r.get("surface") or {}
    surface = [f"{label} {sf[key]}" for key, label in
               (("bo", "Bo"), ("bg", "Bg"), ("rf_oil", "RF oil"), ("rf_gas", "RF gas"))
               if sf.get(key) is not None]
    rep = r.get("grid_title") or ""
    if r.get("rep_type"):
        rep = f"{rep} ({r['rep_type']})"
    fields = [
        ("representation", rep),
        ("porosity", _term("poro", "none: PV and HCPV not computed")),
        ("net to gross", _term("ntg", "none = 1")),
        ("water saturation", _term("sw", "none: HCPV not computed")),
        # ASCII, like the rest of this header: an em dash would not survive
        # every spreadsheet's import
        ("percentile terms",
         "; ".join(w["text"].replace("—", "-").rstrip(".")
                   for w in (r.get("percentile_terms") or [])) or None),
        ("region", (f"{terms['region']} ({types.get('region') or 'property'})"
                    if terms.get("region") else "none")),
        ("contacts", ((", ".join(contacts)
                       + " (depth positive down, in the grid's depth unit)")
                      if contacts else "none")),
        ("convention", (r.get("convention") or "")
         + "; whole cells, none split at a contact"),
        ("volumes", "cubic meters (m3), raw values - the panel's unit choice"
                    " is display only; rbbl = m3 x 6.28981"),
        ("surface", ((", ".join(surface) + " (Bo, Bg in reservoir m3 per"
                      " surface m3; RF a fraction)") if surface else "none")),
        ("surface volumes",
         ("standard cubic meters (sm3), raw: STOIIP = HCPV / Bo on the oil"
          " zones, GIIP = HCPV / Bg on the gas zones, recoverable = in place"
          " x RF; stb = sm3 x 6.28981, scf = sm3 x 35.3147"
          + (f"; no contact: the whole grid taken as {r['surface_fluid']}"
             if r.get("surface_fluid") else ""))
         if (sf.get("bo") or sf.get("bg")) else None),
        ("cells", f"{r.get('cells', 0)} total, {r.get('active', 0)} active,"
                  f" {r.get('no_volume', 0)} without a volume"),
    ]
    return ce.payload("volumetrics", fields, r.get("grid_title") or "")
