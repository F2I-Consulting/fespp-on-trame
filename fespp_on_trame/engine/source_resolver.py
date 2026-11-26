"""Which array a property is, on which source; what an IjkGrid draws.

Free functions taking their dependencies (`source_registry`, `tree`)
explicitly:

  - `resolve_array_for_path(source_registry, tree, rep_path, array_path,
    realization_idx=None)` → `(assoc, vtk_array_name, source)`, retrying
    with the sanitized title when the raw title misses (FESPP strips chars
    outside `[-.0-9A-Z_a-z]` from VTK array names), the suffixed name of a
    multi-realization property first.
  - `ijk_rendered_sources(ijk)` → every proxy an IjkGrid (a view's isolate)
    can render.

The ColorBy / colour-bar / per-view display helpers of the per-
representation model lived here; they went with it (overhaul, Q2 bis): a
view's colours are its composite's (engine/blockscope).
"""
from paraview import simple as pvsimple

from fespp_on_trame.engine.utils.naming import make_valid_vtk_name


def ijk_rendered_sources(ijk):
    """Every proxy an IjkGrid (shared or a view's isolate) can render: per
    cut or kept volume, and per what the whole grid is drawn from (the cell
    mask when one is on, else the extractor, visible in full mode and in range
    mode at full extent), the tips of its threshold chain on it, else the
    source itself."""
    out = []
    tips = ijk.visible_leaf_tips()
    grid_sources = list(ijk._all_slice_sources())
    grid_sources.extend(ijk._src_volumes)
    root = ijk.render_root()
    if root is not None:
        grid_sources.append(root)
    for s in grid_sources:
        tip_proxies = [
            p for p in (t.pv_proxies.get(id(s)) for t in tips)
            if p is not None
        ]
        out.extend(tip_proxies if tip_proxies else [s])
    return out


def resolve_array_for_path(source_registry, tree, rep_path, array_path,
                           realization_idx=None):
    """`(assoc, name, source)` of the property at `array_path`.

    `realization_idx` (default None) — when set on a multi-realization
    `array_path`, the resolver looks up the suffixed VTK array name
    `<sanitized_title>_real_<realization_idx>` first. Falls back to
    the unsuffixed name when not set or not found: the array read at
    the global realization cursor, for non-MR properties and for MR
    properties without a per-property selection.

    `source` is the candidate proxy the array was actually found on, so the
    caller can read the array's data range from the SAME source. `(None,
    None, None)` when unresolved."""
    node_id = tree.find_node_id(array_path)
    if node_id is None:
        return None, None, None
    # the property's name in the file (a series node carries it in
    # propTitle): engine/node_facts, the one rule
    from fespp_on_trame.engine import element_type, node_facts
    title = node_facts.property_title(tree, array_path)
    if not title:
        return None, None, None
    # a multi-realization node is read per realization below
    is_mr = element_type.for_kind(tree.find_type(node_id) or "").is_multi_realization()
    candidate_sources = []
    src = source_registry.get(rep_path)
    if src is not None:
        candidate_sources.append(src)
    else:
        for sid, s in pvsimple.GetSources().items():
            name = sid[0]
            if name == "rep" + (rep_path or "").replace('/', '_'):
                candidate_sources.append(s)
                break
    # Last resort — the ONE shared source every rep is a block of: the
    # shared PDC reports the UNION of every block's arrays, a weaker match,
    # so it comes after a per-rep source
    try:
        shared = source_registry.shared_source()
    except AttributeError:
        shared = None
    if shared is not None and shared not in candidate_sources:
        candidate_sources.append(shared)

    sanitized = make_valid_vtk_name(title)

    # Per-property MR path: look up the suffixed array name first. Falls
    # through to the unsuffixed lookup when the suffixed array isn't
    # present (e.g. the plugin hasn't loaded it yet).
    if is_mr and realization_idx is not None:
        suffixed = f"{sanitized}_real_{int(realization_idx)}"
        for s in candidate_sources:
            try:
                cell_info = s.GetCellDataInformation()
                if cell_info and cell_info.GetArray(suffixed):
                    return "CELLS", suffixed, s
                point_info = s.GetPointDataInformation()
                if point_info and point_info.GetArray(suffixed):
                    return "POINTS", suffixed, s
            except Exception:
                pass

    for s in candidate_sources:
        try:
            cell_info = s.GetCellDataInformation()
            point_info = s.GetPointDataInformation()
            for nm in (title, sanitized):
                if nm and cell_info and cell_info.GetArray(nm):
                    return "CELLS", nm, s
                if nm and point_info and point_info.GetArray(nm):
                    return "POINTS", nm, s
        except Exception:
            pass
    return None, None, None
