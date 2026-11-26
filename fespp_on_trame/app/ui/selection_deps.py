"""What a tick in the tree implies: the selection adjusted for its
dependencies, with the reasons a tick was refused said in the snackbar.

The tree widget writes the checked paths; before they reach the reader,
`_expand_selection_with_deps` adds what a tick implies (a grouping brings
its descendants, an element of a well frame its trajectory, a property
its representation) and removes what an untick takes away (a
representation takes every descendant, a grouping its subtree), drops the
empty shells, vetoes the untick of a trajectory a blocked well still needs
and of a property a threshold chain still reads — each veto written to
the snackbar, never silent — and returns the previous list verbatim when
the change was wholly vetoed, so downstream sees a strict no-op.
Called from `app.boot` on every change of `selected_paths`; the unit
tests live in `tests/unit/test_uncheck_veto.py`.
"""
from trame.app import get_server

_server = get_server()
_state = _server.state

# Node `kind` values that are groupings (they organize children) — the C++
# `isGroupingType` of enum.h. Checking one checks all its descendants: the
# tree widget does no propagation of its own, the cascade is computed here.
# 'Frame' (WellboreFrame logs) and 'MarkerFrame' (marker set) are folders
# FOR SELECTION: checking one bulk-selects its child logs / markers. They
# still own a per-view source (the rendering anchor; see the is_grouping
# note in engine/tree.py), so this list governs only the selection
# cascade, never source creation (the C++ MapperSet classification is
# independent).
from fespp_on_trame.engine import node_kinds
from fespp_on_trame.engine.node_kinds import GROUPING_KINDS as _GROUPING_KINDS

# Domain-level dependency: a well log or a well marker needs its wellbore's
# trajectory (the geometry that places per-depth log values and marker
# positions), so checking one checks the wellbore's Trajectory child too.
# The trigger is STRUCTURAL — "an element of a frame" — not the leaf kind:
# a well log carries a plain property kind ("ContinuousProperty" /
# "DiscreteProperty" under a Frame), since the node `kind` is the RESQML
# XML tag, never a "Wellbore…"-prefixed name. The kinds below scope the
# rule: an element of one of these (or the container itself, whose check
# cascades to its elements) pulls the trajectory in. The completions
# belong here too: a perforation is COMPUTED from the trajectory (the C++
# mapper WitsmlWellboreCompletionPerforationToVtkPolyData converts its MD
# values to XYZ along it), so it is meaningless without the well path.
# Every spelling a kind may carry in the tree is listed.
_FRAME_KINDS = ("Frame", "MarkerFrame", "SeismicWellboreFrame",
                "WellboreFrame", "WellboreMarkerFrame",
                "WellboreCompletion", "Completion",
                "Perforation", "Perfo")
# The CONTAINER subset of the above — the only kinds the empty-shell
# garbage collection may drop. A Perforation is an ELEMENT: it has no
# descendants and must never be collected as an "empty container".
_FRAME_CONTAINER_KINDS = ("Frame", "MarkerFrame", "SeismicWellboreFrame",
                          "WellboreFrame", "WellboreMarkerFrame",
                          "WellboreCompletion", "Completion")


def _expand_selection_with_deps(curr_ids, prev_ids, tree):
    """Return the selection adjusted for implicit dependencies.

    Additions (in `curr_ids`, not in `prev_ids`):
      - Adding a grouping (`GROUPING_KINDS`: Wellbore, Collection,
        Feature, Interpretation, the frame and grid folders…) → all its
        selectable descendants.
      - Adding a node in frame scope (`_FRAME_KINDS`: a log, a marker, a
        perforation, or their container) → its wellbore's trajectory (a
        sibling, not an ancestor).
      - Adding any node living under a representation → that
        representation. A property without its rep has no geometry to
        bind to; FESPP would drop the property silently.

    Removals (in `prev_ids`, not in `curr_ids`):
      - Removing a representation → every descendant of that rep
        (properties / sub-frames / markers / …). The geometry is
        gone so anything depending on it has to go too.
      - Removing a grouping → every descendant. Symmetric with the
        addition rule above: a grouping is the bulk-select affordance
        for its subtree, so unchecking it bulk-deselects the same
        subtree.
      - Removing a grid geometry → its sibling properties in the same
        PropertiesFolder.
    After a removal, the shells left empty are dropped — a frame container,
    and any grouping with rows to tick of which none is ticked any more —,
    then the trajectory and threshold vetoes run (see the module docstring).

    Ordering: implicit additions are inserted BEFORE `curr_ids` so the
    last explicit click stays at the tail of the resulting list —
    `_wire_select_to_active` reads `new_ones[-1]` and would otherwise
    pick an implicit ancestor as the new active node."""
    if tree is None:
        return list(curr_ids or [])
    curr_list = list(curr_ids or [])
    curr_set = set(curr_list)
    prev_set = set(prev_ids or [])
    added = [n for n in curr_list if n not in prev_set]
    removed = [n for n in (prev_ids or []) if n not in curr_set]

    # --- Additions -----------------------------------------------------
    # Track implicit additions separately so we can put them first in
    # the result (see ordering note above).
    implicit_order = []
    implicit_seen = set()

    def _add_implicit(node_id):
        if node_id is None or node_id in curr_set or node_id in implicit_seen:
            return
        implicit_seen.add(node_id)
        implicit_order.append(node_id)

    for node_id in added:
        kind = tree.find_type(node_id)
        if not kind:
            continue
        if kind in _GROUPING_KINDS:
            # Selectable-only: implicit grouping expansion must never add a
            # partial stub (no checkbox, can't load) to the selection.
            for desc in tree.find_all_selectable_descendant_ids(node_id):
                _add_implicit(desc)
        # Trajectory dependency, scoped by _FRAME_KINDS: logs, markers and
        # perforations all render ALONG (or are computed FROM) the well's
        # trajectory, so checking one pulls the trajectory in. The frame /
        # completion container triggers too (its check cascades to its
        # elements). Deliberately NOT any node under a Wellbore: a new kind
        # of wellbore child gets this coupling only once it is listed in
        # _FRAME_KINDS.
        in_frame_scope = kind in _FRAME_KINDS or any(
            tree.find_parent_node_id_with_type(node_id, fk) is not None
            for fk in _FRAME_KINDS
        )
        if in_frame_scope:
            wb = tree.find_parent_node_id_with_type(node_id, "Wellbore")
            if wb is not None:
                traj = (tree.find_first_child_of_type(wb, "Trajectory")
                        or tree.find_first_child_of_type(wb, "WellboreTrajectory"))
                if traj is not None and traj != node_id:
                    _add_implicit(traj)
        # A BlockedWellbore also force-displays its referenced trajectory,
        # but that trajectory lives in the WELL tab (a different per-tab
        # selection var) while the blocked well is in the RESERVOIR tab: it
        # cannot be added here, which only expands the current tab. The
        # cross-tab add is done by _wire_blocked_well_trajectory.
        # Property → its rep ancestor. `find_representation_node`
        # returns node_id itself when it's already a rep, so a rep
        # being added is a no-op here.
        rep_ancestor = tree.find_representation_node(node_id)
        if rep_ancestor is not None and rep_ancestor != node_id:
            _add_implicit(rep_ancestor)

    # --- Removals: rep or grouping gone → every descendant has to go ---
    descendants_to_drop = set()
    for node_id in removed:
        kind = tree.find_type(node_id)
        is_rep = tree.find_representation_node(node_id) == node_id
        if is_rep or (kind in _GROUPING_KINDS):
            descendants_to_drop.update(tree.find_all_descendant_ids(node_id))
        # SolidColor layout: a grid geometry's dependents are its SIBLING
        # properties (same PropertiesFolder), not descendants. Unchecking
        # the geometry deselects them all in the same move: a property
        # cannot render without its geometry. Blocked wellbores live in
        # their own folder and KEEP their selection — losing the grid's
        # properties reverts their coloring to solid.
        if kind in node_kinds.CONTAINED_KINDS:
            folder = tree.find_parent_node_id_with_type(
                node_id, "PropertiesFolder")
            if folder is not None:
                descendants_to_drop.update(
                    d for d in tree.find_all_descendant_ids(folder)
                    if d != node_id)

    result = []
    seen = set()
    for x in implicit_order:
        if x not in descendants_to_drop and x not in seen:
            result.append(x)
            seen.add(x)
    for x in curr_list:
        if x not in descendants_to_drop and x not in seen:
            result.append(x)
            seen.add(x)

    if removed:
        # Garbage-collect frame / completion containers left with NO selected
        # descendant. Checking a marker implicitly adds its MarkerFrame (the
        # rep), and unchecking the marker does not remove it: left in place,
        # the empty frame would count as a "dependent" and veto a later
        # trajectory unselect (select all markers, unselect them all, then
        # unselect the trajectories).
        # So is any other grouping (a wellbore's "logs" folder, a grid's
        # container) that has rows to tick and none ticked any more: left in
        # place, its own row stays ticked over unticked children, and the
        # reader keeps read and drawn what the tree says is not. One level
        # emptied may empty the one above: until none is left.
        while True:
            empty_shells = set()
            for x in result:
                kind = tree.find_type(x) or ""
                if kind not in _FRAME_CONTAINER_KINDS and not (
                        kind in _GROUPING_KINDS and tree.find_all_selectable_descendant_ids(x)):
                    continue
                if not any(d in seen for d in tree.find_all_descendant_ids(x)):
                    empty_shells.add(x)
            if not empty_shells:
                break
            result = [x for x in result if x not in empty_shells]
            seen -= empty_shells

        # Trajectory veto — the ONE place it lives, so the unitary uncheck
        # and the bulk unselect behave identically: a trajectory cannot
        # leave while its well still has selected frame-scope nodes (logs,
        # markers, perforations render along / are computed from it).
        kept_wells = []
        for node_id in removed:
            if (tree.find_type(node_id) or "") not in (
                    "Trajectory", "WellboreTrajectory"):
                continue
            if node_id in seen:
                continue  # already retained (e.g. re-added implicitly)
            wb = tree.find_parent_node_id_with_type(node_id, "Wellbore")
            if wb is None:
                continue
            if any(d in seen for d in tree.find_all_descendant_ids(wb)
                   if d != node_id):
                result.append(node_id)
                seen.add(node_id)
                kept_wells.append(tree.find_title(wb) or "?")
        if kept_wells:
            # The app's amber warning snackbar (free-text body).
            _state.empty_color_snackbar_text = (
                "Trajectory kept for: " + ", ".join(sorted(set(kept_wells)))
                + " — selected logs/markers depend on it. Unselect them"
                " first, or just close the eye on the trajectory to"
                " hide it."
            )
            _state.empty_color_snackbar_visible = False
            _state.empty_color_snackbar_visible = True

        # Threshold guard: unchecking THE property that feeds threshold
        # entries would silently retarget or kill the chain. The unitary
        # uncheck is vetoed and the snackbar says what still reads the
        # property; once those entries are deleted in the Property slicer,
        # the uncheck passes. Bulk unselects are not guarded.
        if len(removed) == 1 and removed[0] not in seen:
            _guard_id = removed[0]
            _refs = _threshold_refs_for(tree, _guard_id)
            if _refs:
                result.append(_guard_id)
                seen.add(_guard_id)
                n = len(_refs)
                # the card to open is the one of the view holding the
                # chain: with two render views, named by their tab titles
                views = sorted({t for t in (_view_title(v) for v, _e in _refs)
                                if t})
                where = (f" of {', '.join(views)}" if views else "")
                _state.empty_color_snackbar_text = (
                    f"{tree.find_title(_guard_id) or '?'} stays checked:"
                    f" {n} entr{'y' if n == 1 else 'ies'} of the Property slicer{where}"
                    f" still read{'s' if n == 1 else ''} it. Delete"
                    f" {'it' if n == 1 else 'them'} there,"
                    " then uncheck the property."
                )
                _state.empty_color_snackbar_visible = False
                _state.empty_color_snackbar_visible = True

    if set(result) == set(prev_ids or []):
        # Fully-vetoed change: the effective selection is what it
        # already was — return the PREVIOUS list verbatim so downstream
        # (selectors → C++ → data_load) sees a strict no-op instead of
        # a reordered list. A mere reorder would re-run the load path and
        # re-colour the grid through the continuous colour table, losing
        # a categorical colouring.
        return list(prev_ids or [])
    return result


def _threshold_refs_for(tree, node_id):
    """Threshold entries fed by this property node (every LIVE view), or
    []. An isolate of a closed view has no card left to delete its entries
    in: it must not hold the property."""
    try:
        from trame.app import get_server
        from fespp_on_trame.engine import threshold_dispatch
        from fespp_on_trame.app.views import per_view_state
        ctx = get_server().context
        isolates = {k: v for k, v in
                    (getattr(ctx, "grid_isolates", None) or {}).items()
                    if per_view_state.is_live(k[0])}
        return threshold_dispatch.chain_entries_for_property(
            _state,
            tree, node_id,
            isolates=isolates,
        )
    except Exception:
        return []


def _view_title(view_id):
    """The title a view carries on its tab ("3D view 2"), never its id."""
    for p in getattr(_state, "fespp_render_panels", None) or []:
        if isinstance(p, dict) and str(p.get("id")) == str(view_id):
            return p.get("title") or ""
    return ""


