"""Which threshold entries read a property: the lookup behind the unselect
guard (`app/ui/selection_deps.py`), which refuses to uncheck a property that
still feeds a threshold of a 3D view.

The thresholds themselves live in each view's grid isolate
(`ctx.grid_isolates`, driven by the `threshold_*` controllers of `boot.py`).
The add / delete / range / visible dispatch of the per-representation model
that used to sit here had no caller left and was removed on 16/10/2026.
"""
from fespp_on_trame.engine.utils.naming import make_valid_vtk_name


def chain_entries_for_property(state, tree, prop_node_id, isolates=None):
    """Threshold entries fed by the given PROPERTY node, across every
    view's chain of its grid: `[(view_id, entry_name), ...]`
    (`view_id=None` for the single-registry fallback provider). Matches
    the property's sanitized base array name and its MR `_real_<idx>`
    variants. Used by the unselect guard: unchecking the property that
    feeds a chain is refused while the entries exist.

    `isolates` is the live table of per-view grid isolates
    (`ctx.grid_isolates`, keyed `(view_id, rep_path)`): under BlockScope the
    chain lives there and nowhere else — the scene registry holds no rep on
    that path, so a lookup through it alone finds nothing."""
    from fespp_on_trame.engine.element_type import for_kind as _fk
    kind = tree.find_type(prop_node_id) or ""
    if not _fk(kind).is_property():
        return []
    rep_id = tree.find_representation_node(prop_node_id)
    rep_path = tree.find_path(rep_id) if rep_id is not None else None
    if not rep_path:
        return []
    title = tree.find_title(prop_node_id) or ""
    if _fk(kind).is_multi_realization():
        prop_title = tree.find_attribute_value(prop_node_id, "propTitle")
        if prop_title:
            title = prop_title
    base = make_valid_vtk_name(title)
    if not base:
        return []

    def _matches(arr):
        return arr == base or arr.startswith(base + "_real_")

    out = []
    for (vid, path), iso in (isolates or {}).items():
        if path != rep_path:
            continue
        try:
            chain = iso.get_chain()
        except Exception:
            continue
        for entry in chain or []:
            if _matches(entry.get("array") or ""):
                out.append((vid, entry["name"]))
    return out
