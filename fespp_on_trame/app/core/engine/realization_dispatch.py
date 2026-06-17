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

from fespp_on_trame.app.core import element_type


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


def clear_active_realization_for_view(
    state, panel_id: str, array_path: str,
) -> bool:
    """Drop the (panel_id, array_path) entry. Returns True when the
    entry existed."""
    by_view = dict(state.ui_active_realization_by_array_by_view or {})
    bucket = dict(by_view.get(panel_id, {}) or {})
    if array_path not in bucket:
        return False
    bucket.pop(array_path, None)
    if bucket:
        by_view[panel_id] = bucket
    else:
        by_view.pop(panel_id, None)
    state.ui_active_realization_by_array_by_view = by_view
    return True


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


def recompute_panel_has_mr(state) -> dict:
    """Derive `panel_has_mr_by_id` from the per-panel MR specs map.
    A panel has MR iff its spec list is non-empty. Returns the new
    map; caller decides whether to write it back."""
    specs_by_panel = state.ui_panel_active_mr_specs_by_id or {}
    return {pid: bool(specs) for pid, specs in specs_by_panel.items()}


def recompute_global_mr_specs(state) -> list:
    """Aggregate `ui_panel_active_mr_specs_by_id` into a single list of
    MR specs that drives the global RealizationPicker in the tools
    band. Each entry has the same shape as a per-panel spec plus a
    `mixed` flag set when the panels using this MR property don't all
    agree on the active index.

    Sorted alphabetically on title (like `recompute_panel_mr_specs`)
    so the global control row order matches the per-panel order."""
    specs_by_panel = state.ui_panel_active_mr_specs_by_id or {}
    if not specs_by_panel:
        return []

    by_path: dict = {}
    for _, panel_specs in specs_by_panel.items():
        for spec in panel_specs or []:
            path = spec.get("array_path") if isinstance(spec, dict) else None
            if not path:
                continue
            entry = by_path.setdefault(path, {
                "array_path": path,
                "title": spec.get("title", ""),
                "available_indices": list(spec.get("available_indices") or []),
                "current_indices": [],
            })
            # Different panels may report slightly different available
            # index sets (e.g. one panel just dropped an MR). Take the
            # union so the global widget can target every index any
            # panel could show.
            for idx in spec.get("available_indices") or []:
                if idx not in entry["available_indices"]:
                    entry["available_indices"].append(idx)
            try:
                entry["current_indices"].append(int(spec.get("current_idx")))
            except (TypeError, ValueError):
                pass

    out: list = []
    for path, entry in by_path.items():
        indices = sorted(set(entry["available_indices"]))
        currents = entry["current_indices"]
        # `current_idx` for the global widget is the mode (most common
        # value across panels). When panels diverge we surface the
        # `mixed` flag so the widget can render a "mixed" indicator —
        # but we still need to pick one for the dropdown / slider.
        if currents:
            mode = max(set(currents), key=currents.count)
        else:
            mode = indices[0] if indices else 0
        mixed = len(set(currents)) > 1
        out.append({
            "array_path": path,
            "title": entry["title"],
            "available_indices": indices,
            "current_idx": mode,
            "mixed": mixed,
        })
    out.sort(key=lambda s: s["title"])
    return out


def resolve_global_selected(state) -> tuple:
    """Resolve `(path, spec)` for the global RealizationPicker.

    Validates `ui_global_mr_selected_path` against the current
    `ui_global_mr_specs`. When the user-picked path is missing /
    stale, fall back to the first available spec so the widget never
    binds to a dead reference. Returns `("", None)` when there is no
    MR property available at all."""
    specs = state.ui_global_mr_specs or []
    if not specs:
        return ("", None)
    sel = state.ui_global_mr_selected_path or ""
    for s in specs:
        if s.get("array_path") == sel:
            return (sel, s)
    first = specs[0]
    return (first.get("array_path", ""), first)


def recompute_panel_mr_specs(state, tree) -> dict:
    """Build the per-panel list of active MR property specs that drives
    the per-view RealizationPicker widget. Returns the new map shape
    `{panel_id: [{array_path, title, available_indices, current_idx}]}`.

    Each spec entry exposes everything the Vue template needs to
    render its row — no per-row tree lookup, no domain refresh
    plumbing. The caller decides whether to write the result back to
    `state.ui_panel_active_mr_specs_by_id`."""
    out: dict = {}
    arrays_by_view = state.ui_active_array_by_rep_by_view or {}
    realizations_by_view = state.ui_active_realization_by_array_by_view or {}

    for panel_id, rep_to_array in arrays_by_view.items():
        if not rep_to_array:
            continue
        panel_realizations = realizations_by_view.get(panel_id) or {}
        specs: list = []
        seen_paths: set = set()
        for array_path in rep_to_array.values():
            if not array_path or array_path in seen_paths:
                continue
            if not is_multirealization_property(tree, array_path):
                continue
            seen_paths.add(array_path)

            available = available_realization_indices(tree, array_path)
            if not available:
                continue
            current = panel_realizations.get(array_path)
            try:
                current_int = int(current) if current is not None else available[0]
            except (TypeError, ValueError):
                current_int = available[0]

            # Resolve a human-friendly title from the tree. MR nodes
            # carry the property's actual title in `propTitle`; the
            # `title` attribute is the sanitized-for-VTK version.
            node_id = tree.find_node_id(array_path)
            title = ""
            if node_id is not None:
                title = (tree.find_attribute_value(node_id, "propTitle")
                         or tree.find_title(node_id)
                         or "")
            if not title:
                title = array_path.rsplit("/", 1)[-1]

            specs.append({
                "array_path": array_path,
                "title": title,
                "available_indices": list(available),
                "current_idx": current_int,
            })
        if specs:
            specs.sort(key=lambda s: s["title"])
            out[panel_id] = specs
    return out
