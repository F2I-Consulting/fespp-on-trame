"""What the loaded data holds, in the few facts that say which panel can
act — pure, over the tree.

The PO, 28/10: "si pas utilisable rien à faire en enabled". A panel of the
top bar opened on data it cannot read only shows an empty state; its
button is greyed instead, its tooltip saying why (app/views/top_gates).
The facts are counts, published as `ui_data_facts` at every load
(app/features/data_facts); a fact the app could not learn is left out, and
a button is never greyed on a fact it does not have.
"""
from fespp_on_trame.engine import node_facts

GRID_KINDS = ("IjkGrid", "UnstructuredGrid")
# the parents of a log channel: a property under one of them is a log
LOG_PARENTS = ("Frame", "WellboreFrame", "SeismicWellboreFrame")


def _walk(asm, nid):
    try:
        n = asm.GetNumberOfChildren(nid)
    except Exception as exc:  # noqa: BLE001 — a node gone mid-walk
        print("[fespp] data facts: walk stopped:", exc, flush=True)
        return
    for i in range(n):
        child = asm.GetChild(nid, i)
        yield child
        yield from _walk(asm, child)


def facts(tree):
    """``{properties, wells, logs, grid_properties}`` — counts over the
    tree: every property, every wellbore, the properties that are log
    channels (under a frame), the properties of a grid."""
    out = {"properties": 0, "wells": 0, "logs": 0, "grid_properties": 0}
    asm = getattr(tree, "_data_assembly", None)
    if asm is None:
        return out
    for nid in _walk(asm, 0):
        kind = tree.find_type(nid) or ""
        if kind == "Wellbore":
            out["wells"] += 1
            continue
        if not node_facts.is_property_kind(kind):
            continue
        out["properties"] += 1
        if any(tree.find_parent_node_id_with_type(nid, k) is not None for k in LOG_PARENTS):
            out["logs"] += 1
            continue
        rep = tree.find_representation_node(nid)
        if rep is not None and (tree.find_type(rep) or "") in GRID_KINDS:
            out["grid_properties"] += 1
    return out
