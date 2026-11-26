"""Per-view multi-realization dispatch — trame side.

Companion to the FESPP plugin's tree-driven realization model (see
RESQML.md for the contract): each MultiRealization / MultiRealization
TimeSeries node in the assembly carries one child per realization
index. Checking the parent (a grouping) propagates to every child so
every available realization gets loaded as a distinct suffixed VTK
array `<title>_real_<idx>`. Trame's per-view picker chooses which
suffixed array each view's ColorBy binds to, without sharing data
with other views.

This module owns the per-(view, array_path) realization choice in
`state.ui_active_realization_by_array_by_view`. No reconcile with
the plugin is needed — loading is handled by the tree selection
mechanism; the picker only drives ColorBy through
`source_resolver.apply_color_array(realization_idx=...)`.

Orthogonal to `active_array.py`: this module owns the realization
choice; active_array.py owns the property choice. They collaborate
at the eye-click handler, which consults this module when the
activated array is MR.
"""
from typing import Optional

from fespp_on_trame.engine import element_type


def is_multirealization_property(tree, array_path: str) -> bool:
    """True iff `array_path` points to an MR property node in the tree."""
    if not array_path:
        return False
    node_id = tree.find_node_id(array_path)
    if node_id is None:
        return False
    return element_type.for_kind(tree.find_type(node_id)).is_multi_realization()


def available_realization_indices(tree, array_path: str) -> list[int]:
    """Sorted list of realization indices available for the MR property
    at `array_path`, or [] when the path isn't MR or the attribute
    isn't set."""
    if not array_path:
        return []
    node_id = tree.find_node_id(array_path)
    if node_id is None:
        return []
    csv = tree.find_attribute_value(node_id, "realization_indices") or ""
    out: list[int] = []
    for piece in csv.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(int(piece))
        except ValueError:
            continue
    out.sort()
    return out


def default_realization_for(state, tree, array_path: str) -> Optional[int]:
    """Pick the realization index to use on first activation of an MR
    property in a view: the smallest available index."""
    available = available_realization_indices(tree, array_path)
    return available[0] if available else None


def set_active_realization_for_view(
    state, panel_id: str, array_path: str, idx: int,
) -> None:
    """Update `state.ui_active_realization_by_array_by_view[panel_id][array_path]
    = idx`, replacing any prior value."""
    by_view = dict(state.ui_active_realization_by_array_by_view or {})
    bucket = dict(by_view.get(panel_id, {}) or {})
    bucket[array_path] = int(idx)
    by_view[panel_id] = bucket
    state.ui_active_realization_by_array_by_view = by_view


def get_active_realization_for_view(
    state, panel_id: str, array_path: str,
) -> Optional[int]:
    """Look up the realization currently chosen by `panel_id` for the
    MR property `array_path`, or None when no choice is recorded."""
    by_view = state.ui_active_realization_by_array_by_view or {}
    bucket = by_view.get(panel_id) or {}
    val = bucket.get(array_path)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def suffixed_array_name(base_array_name: str, idx: int) -> str:
    """Apply the plugin's naming convention for per-realization arrays.
    Keep this in one place so the convention can evolve without
    hunting through callers."""
    return f"{base_array_name}_real_{idx}"

