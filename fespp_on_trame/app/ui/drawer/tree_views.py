from trame.app import get_server
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify3

_server = get_server()
_state = _server.state

# Node `kind` values that are pure groupings (no VTK object behind
# them, just organize children). Mirror of C++ `isGroupingType` in
# enum.h. When the user checks one of these, the UI auto-checks all
# descendants too — `select_strategy="independent"` on the VTreeview
# means Vuetify itself does no propagation, so we do it manually here.
# 'Frame' (WellboreFrame logs) and 'MarkerFrame' (marker set) are
# folders FOR SELECTION: checking one bulk-selects its child logs /
# markers, and it shows a tri-state checkbox + no eye of its own. They
# still own a per-view source (the rendering anchor) — see tree.py
# is_grouping note — so this list governs only tree selection / tri-state,
# never source creation (the C++ MapperSet classification is independent).
from fespp_on_trame.app.core.node_kinds import GROUPING_KINDS as _GROUPING_KINDS

# Domain-level dependency: a WellboreChannel or WellboreMarker requires
# its Wellbore's Trajectory (the geometry that anchors per-depth log
# values or marker positions). When the user checks one of these, we
# auto-check the Wellbore's Trajectory child too. The trigger is
# STRUCTURAL — "an element of a frame" — not leaf-kind-based: a well log
# carries a plain property kind ("ContinuousProperty"/"DiscreteProperty"
# under a Frame; the `kind` attribute is the RESQML XML tag, never the
# "Wellbore…"-prefixed enum names the original kind list assumed, which
# made this auto-check a silent no-op since day one). The kinds below
# scope the rule: an element of one of these (or the container itself,
# whose check cascades to its elements) pulls the trajectory in. The
# completions belong here too: a perforation is COMPUTED from the
# trajectory (the C++ mapper converts its MD values to XYZ along it —
# WitsmlWellboreCompletionPerforationToVtkPolyData), so it renders
# nonsensically without the well path. Both tag and legacy spellings.
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

# The "Select / unselect ▾" menu, per tab: (label, kinds acted on,
# kinds COUNTED for the "(N)" badge). The two differ when the action
# targets a grouping folder: "All blocked wellbores" selects the ONE
# BlockedWellboreFolder (its check cascades) but the user reads the
# number of WELLBORES.
_BULK_ACTIONS = {
    "reservoir": [
        ("All grids", ["IjkGrid", "UnstructuredGrid"],
         ["IjkGrid", "UnstructuredGrid"]),
        ("All blocked wellbores", ["BlockedWellboreFolder"],
         ["BlockedWellbore"]),
    ],
    "surface": [
        ("All surfaces",
         ["Grid2d", "TriangulatedSet", "PointSet", "Polyline", "PolylineSet"],
         ["Grid2d", "TriangulatedSet", "PointSet", "Polyline", "PolylineSet"]),
    ],
    "well": [
        ("All trajectories", ["Trajectory", "WellboreTrajectory"],
         ["Trajectory", "WellboreTrajectory"]),
        ("All markers", ["Marker", "WellboreMarker"],
         ["Marker", "WellboreMarker"]),
    ],
}


def _count_kinds(items, wanted):
    """Recursive count of subtree items whose type is in `wanted`."""
    n = 0
    for it in items or []:
        if it.get("type") in wanted:
            n += 1
        n += _count_kinds(it.get("children"), wanted)
    return n


_state.setdefault("ui_bulk_counts", {})


@_state.change("ui_subtree_reservoir", "ui_subtree_surface", "ui_subtree_well")
def _recompute_bulk_counts(**_):
    """Refresh the "(N)" badges of the Select / unselect menu whenever a
    tab's subtree is (re)published — import, hierarchy-mode switch."""
    counts = {}
    for tab, actions in _BULK_ACTIONS.items():
        items = getattr(_state, f"ui_subtree_{tab}", []) or []
        for label, _sel_kinds, count_kinds in actions:
            counts[f"{tab}|{label}"] = _count_kinds(items, set(count_kinds))
    _state.ui_bulk_counts = counts


def _expand_selection_with_deps(curr_ids, prev_ids, tree):
    """Return the selection adjusted for implicit dependencies.

    Additions (newly checked relative to `prev_ids`):
      - Adding a grouping (Wellbore, Collection, Partial, Feature,
        Interpretation) → all its descendants.
      - Adding a WellboreChannel / WellboreMarker → the Wellbore's
        WellboreTrajectory (sibling, not ancestor).
      - Adding any node living under a representation → that
        representation. A property without its rep has no geometry to
        bind to; FESPP would drop the property silently.

    Removals (was in `prev_ids`, no longer in `curr_ids`):
      - Removing a representation → every descendant of that rep
        (properties / sub-frames / markers / …). The geometry is
        gone so anything depending on it has to go too.
      - Removing a grouping (Collection / Wellbore / Partial /
        Feature / Interpretation) → every descendant. Symmetric with
        the addition rule above: a grouping is the bulk-select
        affordance for its subtree, so unchecking it bulk-deselects
        the same subtree.

    Ordering: implicit additions are inserted BEFORE `curr_ids` so the
    user's last explicit click stays at the tail of the resulting
    list — `_wire_select_to_active` reads `new_ones[-1]` and would
    otherwise pick an implicit ancestor as the new active node."""
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
        # elements). Deliberately NOT any-node-under-a-Wellbore, to leave
        # future wellbore children without this coupling unless decided.
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
        # NOTE: a BlockedWellbore also force-displays its referenced trajectory,
        # but that trajectory lives in the WELL tab (a different per-tab
        # selection var) while the blocked well is in the RESERVOIR tab — it
        # can't be added here, which only expands the current tab. The cross-tab
        # add is done by _wire_blocked_well_trajectory.
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
        # rep), but unchecking the marker never removed it — the stale, empty
        # frame then counted as a "dependent" and wrongly vetoed a bulk
        # trajectory unselect right after select-all + unselect-all markers.
        empty_shells = set()
        for x in result:
            if (tree.find_type(x) or "") not in _FRAME_CONTAINER_KINDS:
                continue
            if not any(d in seen for d in tree.find_all_descendant_ids(x)):
                empty_shells.add(x)
        if empty_shells:
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
    return result


def _wire_select_to_active(select_var: str, active_var: str, prev_var: str):
    """When a new node is checked in `select_var`, set `active_var` to
    that newly-added id. When the currently-active node is unchecked,
    fall back to any remaining selected node. Activating via label
    click does NOT alter selection (Vuetify's separate
    update_activated callback handles that)."""
    @_state.change(select_var)
    def _on_change(**_):
        curr = list(getattr(_state, select_var) or [])
        prev = list(getattr(_state, prev_var, []) or [])
        prev_set = set(prev)
        new_ones = [x for x in curr if x not in prev_set]
        if new_ones:
            setattr(_state, active_var, [new_ones[-1]])
        else:
            active = getattr(_state, active_var) or []
            if active and active[0] not in curr:
                setattr(_state, active_var, [curr[0]] if curr else [])
        setattr(_state, prev_var, curr)


# Track the active node value as seen by `_wire_dependency_expansion`
# on the previous tick. Vuetify emits both `update_activated` and
# `update_selected` from a single label click — to tell the
# label-click case (re-add the activated node) apart from a real
# checkbox uncheck (keep the removal), we need to know whether
# `active` *just* changed inside this very tick. Trame doesn't expose
# the pre-flush snapshot, so we track it ourselves, keyed by the
# active_var name.
_prev_active_seen: dict = {}


def _wire_dependency_expansion(select_var: str, prev_var: str,
                               active_var: str, tree):
    """Single handler watching BOTH `select_var` and `active_var`.

    Responsibilities:
      1. Detect Vuetify's label-click quirk — clicking a node's label
         silently drops the node from `selected`, even though label
         click should only activate. Symptom: `active` changed AND
         the new active was in prev select but isn't in curr select.
         We re-add it.
      2. Otherwise, drive `_expand_selection_with_deps` over the
         actual selection delta (additions + removals cascade).

    We listen to active_var too (alongside select_var) so the
    `_prev_active_seen` cache stays accurate even when the user
    label-clicks a node that wasn't selected (active changes, select
    doesn't) — that case returns early without any cascade work."""
    @_state.change(select_var, active_var)
    def _on_change(**_):
        curr_select = list(getattr(_state, select_var) or [])
        prev_select = list(getattr(_state, prev_var, []) or [])
        curr_active = list(getattr(_state, active_var, []) or [])
        prev_active = list(_prev_active_seen.get(active_var, []))
        _prev_active_seen[active_var] = list(curr_active)

        select_changed = (curr_select != prev_select)
        active_changed = (curr_active != prev_active)

        if not select_changed:
            return

        # Defensive guard for the Vuetify label-click case where both
        # `update_activated` and `update_selected` fire and the
        # newly-activated node would be dropped from select. The custom
        # checkbox below makes this unreachable in practice (label click
        # no longer fires update_selected), but the guard is cheap.
        if (active_changed and curr_active
            and curr_active[0] in prev_select and curr_active[0] not in curr_select):
            new_curr = list(curr_select) + [curr_active[0]]
            setattr(_state, select_var, new_curr)
            return

        if not curr_select and not prev_select:
            return
        expanded = _expand_selection_with_deps(curr_select, prev_select, tree)
        if set(expanded) != set(curr_select):
            setattr(_state, select_var, expanded)
            # Force the client resync even when the re-expanded value
            # equals the var's PREVIOUS server value (trame collapses
            # same-value writes): under rapid clicking the checkbox
            # model could otherwise stay desynced — box unchecked
            # while the vetoed trajectory still renders.
            try:
                _state.dirty(select_var)
            except Exception:
                pass


def _wire_grid_geometry_on_property(tree):
    """SolidColor variant: when a grid PROPERTY is checked, also check its
    grid's geometry rep (the "SolidColor" leaf under the PropertiesFolder) so
    the geometry's own checkbox reflects that it renders and — being ADD-ONLY —
    the geometry PERSISTS when the property is later unchecked (a property
    without its geometry makes no business sense; the geometry leaves only when
    nothing references it). FESPP also autoloads the geometry server-side
    (selectNodeId); this keeps the reservoir selection / checkbox in sync."""
    @_state.change("ui_select_node_reservoir")
    def _on_change(**_):
        reservoir = list(getattr(_state, "ui_select_node_reservoir", []) or [])
        added = False
        for node_id in list(reservoir):
            # The geometry rep lives under the props folder too — skip it; only
            # real property leaves (with a PropertiesFolder ancestor) pull it in.
            if tree.find_type(node_id) in ("IjkGrid", "UnstructuredGrid"):
                continue
            folder = tree.find_parent_node_id_with_type(node_id, "PropertiesFolder")
            if folder is None:
                continue
            geom = tree.find_first_child_of_type(folder, "IjkGrid") \
                or tree.find_first_child_of_type(folder, "UnstructuredGrid")
            if geom is not None and geom not in reservoir:
                reservoir.append(geom)
                added = True
        if added:
            _state.ui_select_node_reservoir = reservoir


def _wire_blocked_well_trajectory(tree):
    """Force a BlockedWellbore's referenced WellboreTrajectory checked.

    The blocked well lives in the RESERVOIR tab (under its supporting grid),
    but the trajectory lives in the WELL tab — a different per-tab selection
    var. Both the trajectory's checkbox AND its rendering are driven by
    `ui_select_node_well` (the per-tab selectors are merged downstream), so the
    trajectory must be written into the WELL selection, not the reservoir one.
    Add-only: unchecking the blocked well keeps the trajectory selected, per the
    feature spec."""
    @_state.change("ui_select_node_reservoir")
    def _on_change(**_):
        reservoir = list(getattr(_state, "ui_select_node_reservoir", []) or [])
        well = list(getattr(_state, "ui_select_node_well", []) or [])
        added = False
        for node_id in reservoir:
            if tree.find_type(node_id) != "BlockedWellbore":
                continue
            traj_uuid = tree.find_attribute_value(node_id, "trajectoryUuid")
            traj = tree.find_node_id_by_uuid(traj_uuid) if traj_uuid else None
            if traj is not None and traj not in well:
                well.append(traj)
                added = True
        if added:
            _state.ui_select_node_well = well


# --- Custom row checkbox -------------------------------------------------
# Vuetify 3 VTreeview with `selectable=True` makes the WHOLE row click
# toggle selection — including the label area, with no way to opt out
# (and `activatable=True` alongside doesn't override that). So a user
# clicking a node's label to "activate" it ends up unchecking the node,
# and our cascade then drops every descendant. To preserve the natural
# affordance (label click = activate only; checkbox click = toggle
# select), we disable Vuetify's built-in checkbox (`selectable=False`)
# and render our own icon in the prepend slot, wired to a controller
# method that toggles `ui_select_node_*` directly.
#
# For grouping kinds (Collection / Wellbore / Feature / Interpretation
# — `item.is_grouping`) the icon is tri-state: marked when ALL
# descendants are selected, mdi-minus-box when only SOME are, blank
# otherwise. For everything else (leaves, reps) the icon is binary on
# the node's own id. Partial nodes (`item.disabled`) get no checkbox
# at all — partials are reference-only and shouldn't be checked.
def _select_checkbox_icon(select_var: str) -> str:
    """Vue expression resolving to the checkbox icon name. Tri-state
    on groupings, binary otherwise."""
    sel = f"({select_var} || [])"
    return (
        "(item.is_grouping && item.descendant_ids && item.descendant_ids.length > 0)"
        f"  ? (item.descendant_ids.every(d => {sel}.indexOf(d) !== -1)"
        "      ? 'mdi-checkbox-marked'"
        f"      : (item.descendant_ids.some(d => {sel}.indexOf(d) !== -1)"
        "          ? 'mdi-minus-box'"
        "          : 'mdi-checkbox-blank-outline'))"
        f"  : ({sel}.indexOf(item.id) !== -1"
        "      ? 'mdi-checkbox-marked'"
        "      : 'mdi-checkbox-blank-outline')"
    )


def _select_checkbox_color(select_var: str) -> str:
    """Companion to `_select_checkbox_icon` — `primary` when the icon
    is non-empty (marked or minus-box), muted grey when blank."""
    sel = f"({select_var} || [])"
    return (
        "(item.is_grouping && item.descendant_ids && item.descendant_ids.length > 0)"
        f"  ? (item.descendant_ids.some(d => {sel}.indexOf(d) !== -1)"
        "      ? 'primary'"
        "      : 'grey-darken-1')"
        f"  : ({sel}.indexOf(item.id) !== -1"
        "      ? 'primary'"
        "      : 'grey-darken-1')"
    )


# Inline rainbow gradient for the "Property" chip — rendered on rep
# nodes whose rep is currently coloured by a data array.
_RAINBOW_STYLE = (
    "width:10px;height:10px;border-radius:50%;display:inline-block;"
    "margin-left:4px;vertical-align:middle;"
    "background:linear-gradient(90deg,"
    "#ff0000,#ff8000,#ffff00,#00ff00,#00ffff,#0000ff,#8000ff);"
)

# Conic (pie) gradient for the "Multicolor" chip — rendered on a
# MarkerFrame whose child markers carry 2+ distinct solid colours.
_MULTICOLOR_STYLE = (
    "width:10px;height:10px;border-radius:50%;display:inline-block;"
    "margin-left:4px;vertical-align:middle;"
    "background:conic-gradient("
    "#ff0000,#ffff00,#00ff00,#00ffff,#0000ff,#ff00ff,#ff0000);"
)


# JS predicate: node auto-deselected because its data is unreadable
# (see vtk_log._flag_invalid_nodes). Invalid nodes carry NOTHING but
# the ⚠ badge — no colour chip, no eyes, and a blocked checkbox — so
# nothing invites the user to re-select them.
_INVALID_NODE_EXPR = "(ui_invalid_node_ids || []).includes(item.id)"


def _chip_slot():
    """Color chip rendered next to a tree node label.

    - No chip when the rep_path has no entry in
      tree_chip_color_by_path (rep not loaded yet) — or when the node
      is INVALID (unreadable data).
    - Rainbow gradient when the entry is the sentinel "PROPERTY"
      (a dataArray is the active eye on the rep).
    - Conic gradient when the entry is the sentinel "MULTICOLOR"
      (a MarkerFrame whose child markers have 2+ distinct colours).
    - Solid mdi-circle in the assigned colour otherwise."""
    _valid = f"!({_INVALID_NODE_EXPR}) && "
    is_property = _valid + (
        "tree_chip_color_by_path && tree_chip_color_by_path[item.path] === 'PROPERTY'"
    )
    is_multicolor = _valid + (
        "tree_chip_color_by_path && tree_chip_color_by_path[item.path] === 'MULTICOLOR'"
    )
    is_solid = _valid + (
        "tree_chip_color_by_path && tree_chip_color_by_path[item.path]"
        " && tree_chip_color_by_path[item.path] !== 'PROPERTY'"
        " && tree_chip_color_by_path[item.path] !== 'MULTICOLOR'"
    )
    html.Div(v_if=is_property, style=_RAINBOW_STYLE)
    html.Div(v_else_if=is_multicolor, style=_MULTICOLOR_STYLE)
    vuetify3.VIcon(
        "mdi-circle",
        v_else_if=is_solid,
        size="x-small",
        color=("tree_chip_color_by_path[item.path]",),
        classes="ml-1",
    )


_PROPERTY_TYPES_JS = (
    "['ContinuousProperty','DiscreteProperty','CategoricalProperty',"
    "'TimeSeries','MultiRealization','MultiRealizationTimeSeries']"
)


def _stats_slot(controller, select_var):
    """`mdi-chart-box-outline` toggle next to each property node —
    adds / removes the property from the singleton Stats dockview
    tab's pinned list.

    Visible only on property nodes (type in `_PROPERTY_TYPES_JS`)
    that are **currently checked** in this tree (i.e. node `id` is
    in `select_var`, the per-tree selection list — one of
    `ui_select_node_reservoir` / `_surface` / `_well`). Stats on an
    unchecked property would compute against data the user hasn't
    asked to load, so the toggle is suppressed until they tick the
    checkbox.

    The icon flips to `mdi-chart-box` when the property is currently
    pinned (path is in `ui_stats_pinned_paths`). Click fires
    `controller.toggle_stats_display(item.path)`.

    Placed in the row's append slot, BEFORE `_eye_slot` — keeps the
    stats toggle structurally distinct from the per-view eye chips
    (one is about computing tabular stats, the other about per-view
    visibility / coloring)."""
    is_property = (
        f"({_PROPERTY_TYPES_JS}).indexOf(item.type) !== -1"
    )
    is_selected = (
        f"({select_var} || []).indexOf(item.id) !== -1"
    )
    visible = (f"!({_INVALID_NODE_EXPR}) && ({is_property})"
               f" && ({is_selected})")
    is_pinned = (
        "ui_stats_pinned_paths"
        " && ui_stats_pinned_paths.indexOf(item.path) !== -1"
    )
    with html.Div(
        v_if=visible,
        classes="d-inline-flex align-center mr-1",
        title=(
            f"({is_pinned})"
            " ? ('Stop showing stats for ' + item.title)"
            " : ('Show stats for ' + item.title + ' in the Stats panel')",
        ),
    ):
        vuetify3.VIcon(
            icon=(f"({is_pinned}) ? 'mdi-chart-box' : 'mdi-chart-box-outline'",),
            size="small",
            color=(f"({is_pinned}) ? 'teal-darken-2' : 'grey-lighten-1'",),
            style="cursor: pointer;",
            click=(controller.toggle_stats_display, "[item.path]"),
        )


def _eye_slot(controller):
    """Per-view eye chips on a tree node, rendered in the
    v_slot_append slot.

    Each render panel has one chip on every loaded rep node and one
    chip on every loaded array node — so the toggle affordance is
    always reachable. Visual states:

      - Rep chip: bright blue `mdi-eye` when the panel shows the rep
        and is in SolidColor. Grey `mdi-eye-closed` when hidden.
        Lighter when the panel has moved its V annotation onto an
        array (chip stays as an affordance to flip back to
        visibility / SolidColor).
      - Array chip: bright purple `mdi-eye` when the panel colours
        the parent rep by this array. Outline grey when this array
        isn't the active one for the panel. Click swaps the panel's
        coloring to this array (or back to SolidColor if it was
        already the active one).

    Collapsed mode (>1 panel only): when every panel uniformly hides
    the rep (or has the array inactive), the per-panel row is folded
    into a single unlabelled chip — labels are pure redundancy in
    that state. A click on the folded chip targets the currently
    active panel so the user can break uniformity in one go."""
    # A Frame (log set) / MarkerFrame (marker set) is a CONTAINER — it
    # carries no rep eye of its own; each child log gets a data-array eye
    # and each child marker gets a visibility eye (the blocks below).
    # `item.eye` is the per-node eye token computed server-side from
    # element_type.eye_descriptor() (tree.py): 'rep' on renderable reps,
    # 'array' on property leaves, 'marker' on marker leaves, absent on the
    # Frame/MarkerFrame folders + groupings. Each block below is gated on
    # its eye token.
    _valid = f"!({_INVALID_NODE_EXPR}) && "
    is_loaded_rep = _valid + (
        "ui_loaded_rep_paths && ui_loaded_rep_paths.indexOf(item.path) !== -1"
        " && item.eye === 'rep'"
    )
    is_loaded_array = _valid + (
        "ui_loaded_array_paths && ui_loaded_array_paths.indexOf(item.path) !== -1"
        " && item.eye === 'array'"
    )
    # Marker leaves (WellboreMarker, runtime kind 'Marker') — MULTI-select
    # visibility, each independently toggleable per panel.
    is_loaded_marker = _valid + (
        "ui_loaded_marker_paths && ui_loaded_marker_paths.indexOf(item.path) !== -1"
        " && item.eye === 'marker'"
    )
    marker_visible_in_panel = (
        "ui_visible_marker_paths_by_view"
        " && ui_visible_marker_paths_by_view[panel.id]"
        " && ui_visible_marker_paths_by_view[panel.id].indexOf(item.path) !== -1"
    )
    marker_all_hidden = (
        "(fespp_render_panels || []).length > 1"
        " && (fespp_render_panels || []).every(p => "
        "!(ui_visible_marker_paths_by_view"
        " && ui_visible_marker_paths_by_view[p.id]"
        " && ui_visible_marker_paths_by_view[p.id].indexOf(item.path) !== -1)"
        ")"
    )

    # JS booleans evaluated per (panel, item) inside the v-for scope.
    # The expressions assume `panel.id`, `item.path`, `item.rep_path`
    # are available (the last is set server-side on every tree item
    # by tree.add_subtreeview_data).
    is_hidden_in_panel = (
        "ui_hidden_rep_paths_by_view"
        " && ui_hidden_rep_paths_by_view[panel.id]"
        " && ui_hidden_rep_paths_by_view[panel.id].indexOf(item.path) !== -1"
    )
    has_active_array_in_panel = (
        "ui_active_array_by_rep_by_view"
        " && ui_active_array_by_rep_by_view[panel.id]"
        " && ui_active_array_by_rep_by_view[panel.id][item.path]"
    )
    array_is_active_in_panel = (
        "ui_active_array_by_rep_by_view"
        " && ui_active_array_by_rep_by_view[panel.id]"
        " && ui_active_array_by_rep_by_view[panel.id][item.rep_path] === item.path"
    )

    # Collapse triggers (only when >1 panels — with a single panel the
    # label is useful and there's nothing to deduplicate).
    rep_all_hidden = (
        "(fespp_render_panels || []).length > 1"
        " && (fespp_render_panels || []).every(p => "
        "ui_hidden_rep_paths_by_view"
        " && ui_hidden_rep_paths_by_view[p.id]"
        " && ui_hidden_rep_paths_by_view[p.id].indexOf(item.path) !== -1"
        ")"
    )
    array_none_active = (
        "(fespp_render_panels || []).length > 1"
        " && (fespp_render_panels || []).every(p => "
        "!(ui_active_array_by_rep_by_view"
        " && ui_active_array_by_rep_by_view[p.id]"
        " && ui_active_array_by_rep_by_view[p.id][item.rep_path] === item.path)"
        ")"
    )

    # ---- Rep node ----
    with html.Div(v_if=is_loaded_rep, classes="d-inline-flex align-center"):
        # Collapsed: rep is hidden in every panel. One unlabelled
        # closed eye; click targets the active panel.
        with html.Div(
            v_if=rep_all_hidden,
            classes="d-inline-flex align-center ml-1",
            title=("'Hidden in every view — click to show in the active view'",),
        ):
            vuetify3.VIcon(
                icon="mdi-eye-closed",
                size="small",
                color="grey-darken-1",
                style="cursor: pointer;",
                click=(controller.toggle_rep_visibility, "[item.path]"),
            )
        # Per-panel chip row (the common case).
        with html.Div(
            v_if=f"!({rep_all_hidden})",
            classes="d-inline-flex align-center",
        ):
            with html.Div(
                v_for="panel in (fespp_render_panels || [])",
                key="'rep-' + panel.id",
                classes="d-inline-flex align-center",
                style="gap: 1px; margin-left: 4px;",
                title=("'Toggle visibility of ' + item.title + ' in ' + panel.title",),
            ):
                html.Span(
                    "{{ panel.title }}",
                    classes="text-caption",
                    style=(
                        "{ fontSize: '9px', lineHeight: 1,"
                        f" color: !({has_active_array_in_panel}) ? '#616161' : '#bdbdbd',"
                        f" fontWeight: !({has_active_array_in_panel}) ? '700' : '400' }}"
                        ,
                    ),
                )
                # Blue when shown, grey when hidden — ALWAYS, whether or not a
                # property is colouring the rep. It used to dim to
                # `grey-lighten-1` under an active array, back when this eye's
                # first click meant "give up the colouring" and it really was
                # secondary. It is now the ONLY visibility control (colouring
                # belongs to the array eye below), so dimming it misread as
                # disabled exactly when it matters most: hiding a coloured rep.
                vuetify3.VIcon(
                    icon=(f"({is_hidden_in_panel}) ? 'mdi-eye-closed' : 'mdi-eye'",),
                    size="small",
                    color=(
                        f"({is_hidden_in_panel}) ? 'grey-darken-1' : 'blue-darken-1'",
                    ),
                    style="cursor: pointer;",
                    click=(controller.toggle_rep_visibility, "[item.path, panel.id]"),
                )

    # ---- Array node ----
    with html.Div(v_if=is_loaded_array, classes="d-inline-flex align-center"):
        # Collapsed: no panel colours by this array. One unlabelled
        # outline eye; click activates on the active panel.
        with html.Div(
            v_if=array_none_active,
            classes="d-inline-flex align-center ml-1",
            title=("'Not active in any view — click to set as the colour array in the active view'",),
        ):
            vuetify3.VIcon(
                icon="mdi-eye-outline",
                size="small",
                color="grey-darken-1",
                style="cursor: pointer;",
                click=(controller.toggle_dataarray_color, "[item.path]"),
            )
        with html.Div(
            v_if=f"!({array_none_active})",
            classes="d-inline-flex align-center",
        ):
            with html.Div(
                v_for="panel in (fespp_render_panels || [])",
                key="'arr-' + panel.id",
                classes="d-inline-flex align-center",
                style="gap: 1px; margin-left: 4px;",
                title=(
                    "(" + array_is_active_in_panel + ")"
                    " ? (panel.title + ' is colouring by ' + item.title + ' — click for SolidColor')"
                    " : ('Set ' + item.title + ' as the colour array in ' + panel.title)",
                ),
            ):
                html.Span(
                    "{{ panel.title }}",
                    classes="text-caption",
                    style=(
                        "{ fontSize: '9px', lineHeight: 1,"
                        f" color: ({array_is_active_in_panel}) ? '#6a1b9a' : '#bdbdbd',"
                        f" fontWeight: ({array_is_active_in_panel}) ? '700' : '400' }}"
                        ,
                    ),
                )
                vuetify3.VIcon(
                    icon=(f"({array_is_active_in_panel}) ? 'mdi-eye' : 'mdi-eye-outline'",),
                    size="small",
                    color=(
                        f"({array_is_active_in_panel}) ? 'purple-darken-1' : 'grey-lighten-1'",
                    ),
                    style="cursor: pointer;",
                    click=(controller.toggle_dataarray_color, "[item.path, panel.id]"),
                )

    # ---- Marker node (multi-select visibility) ----
    with html.Div(v_if=is_loaded_marker, classes="d-inline-flex align-center"):
        # Collapsed: marker shown in no panel → one unlabelled outline
        # eye; click shows it in the active view.
        with html.Div(
            v_if=marker_all_hidden,
            classes="d-inline-flex align-center ml-1",
            title=("'Hidden in every view — click to show in the active view'",),
        ):
            vuetify3.VIcon(
                icon="mdi-eye-outline",
                size="small",
                color="grey-darken-1",
                style="cursor: pointer;",
                click=(controller.toggle_marker_visibility, "[item.path]"),
            )
        with html.Div(
            v_if=f"!({marker_all_hidden})",
            classes="d-inline-flex align-center",
        ):
            with html.Div(
                v_for="panel in (fespp_render_panels || [])",
                key="'mrk-' + panel.id",
                classes="d-inline-flex align-center",
                style="gap: 1px; margin-left: 4px;",
                title=("'Toggle ' + item.title + ' in ' + panel.title",),
            ):
                html.Span(
                    "{{ panel.title }}",
                    classes="text-caption",
                    style=(
                        "{ fontSize: '9px', lineHeight: 1,"
                        f" color: ({marker_visible_in_panel}) ? '#e65100' : '#bdbdbd',"
                        f" fontWeight: ({marker_visible_in_panel}) ? '700' : '400' }}"
                        ,
                    ),
                )
                vuetify3.VIcon(
                    icon=(f"({marker_visible_in_panel}) ? 'mdi-eye' : 'mdi-eye-outline'",),
                    size="small",
                    color=(
                        f"({marker_visible_in_panel}) ? 'deep-orange-darken-1' : 'grey-lighten-1'",
                    ),
                    style="cursor: pointer;",
                    click=(controller.toggle_marker_visibility, "[item.path, panel.id]"),
                )


class TreeViews:
    """Owns the three VTreeviews (reservoir / surface / well). Wires
    the dependency-expansion + select-to-active handlers and exposes
    one render method per tab."""

    def __init__(self, controller, state, tree=None):
        self.controller = controller
        self.state = state
        self._tree = tree

        @controller.set("tree_toggle_select")
        def tree_toggle_select(node_id, select_var):
            """Custom checkbox click handler.

            - Partial nodes (reference-only) are no-ops; the prepend
              slot also hides the checkbox icon for them, so this
              branch is just belt-and-braces.
            - Grouping nodes (Collection / Wellbore / Feature /
              Interpretation) cycle "empty/some → all" then "all →
              empty": click adds grouping + every descendant when
              not all are in, removes them all when all are in.
              Matches the tri-state visual rendered by
              `_select_checkbox_icon`.
            - Leaves and reps: plain toggle. The selection-cascade
              in `_wire_dependency_expansion` adds rep ancestors
              and drops rep descendants symmetrically."""
            if node_id is None or self._tree is None:
                return
            kind = self._tree.find_type(node_id)
            if kind in ("partial", "Partial"):
                return
            curr = list(getattr(state, select_var, []) or [])
            # Reference the module-level set (minus Partial, already
            # short-circuited above) so this never drifts from the
            # additive/removal cascade in _expand_selection_with_deps.
            is_grouping = kind in _GROUPING_KINDS
            if is_grouping:
                # Selectable-only: a bulk grouping click must never pull a
                # partial stub into the selection (it has no checkbox and
                # can't be loaded), and the all_in tri-state test then
                # ranges over real children only so it can reach "all".
                descendants = self._tree.find_all_selectable_descendant_ids(node_id)
                if descendants:
                    curr_set = set(curr)
                    all_in = all(d in curr_set for d in descendants)
                    if all_in:
                        to_drop = set(descendants)
                        to_drop.add(node_id)
                        new_curr = [x for x in curr if x not in to_drop]
                    else:
                        new_curr = list(curr)
                        if node_id not in curr_set:
                            new_curr.append(node_id)
                            curr_set.add(node_id)
                        for d in descendants:
                            if d not in curr_set:
                                new_curr.append(d)
                                curr_set.add(d)
                    setattr(state, select_var, new_curr)
                    return
            if node_id in curr:
                new_curr = [x for x in curr if x != node_id]
            else:
                new_curr = list(curr) + [node_id]
            setattr(state, select_var, new_curr)

        @controller.set("tree_select_kinds")
        def tree_select_kinds(tab, kinds, mode="add"):
            """Bulk select / unselect every node whose kind is in `kinds`,
            in `tab`. `mode="add"` unions them with the current selection
            (LOAD); `mode="remove"` drops them — and, for grouping kinds,
            their whole subtree — from it (UNLOAD).

            Walks `find_all_descendant_ids` (NOT the selectable-only variant)
            so GROUPING folder kinds — e.g. `BlockedWellboreFolder` for the
            "All blocked wellbores" entry — are matchable: partials carry the
            kind `"partial"` and are never in a dropdown's `kinds`, so the
            wider walk stays safe. Selecting a folder lets
            `_expand_selection_with_deps` cascade to its children, so the
            folder's tri-state cleanly loads / unloads the whole group.

            Writes the FULLY dependency-expanded selection into
            `ui_select_node_<tab>` in one shot. Pre-expanding here makes
            the reactive `_wire_dependency_expansion` handler a no-op (it
            already sees a fixed point), so the data load runs exactly
            ONCE for the whole bulk instead of twice (raw set, then the
            handler re-writing it with the rep ancestors)."""
            if self._tree is None or not tab:
                return
            wanted = set(kinds or [])
            if not wanted:
                return
            select_var = f"ui_select_node_{tab}"
            roots = getattr(state, f"ui_subtree_{tab}", []) or []
            prev = list(getattr(state, select_var, []) or [])
            matched = []
            matched_set = set()
            for root in roots:
                rid = root.get("id")
                if rid is None:
                    continue
                for nid in [rid] + self._tree.find_all_descendant_ids(rid):
                    if nid in matched_set:
                        continue
                    if self._tree.find_type(nid) in wanted:
                        matched.append(nid)
                        matched_set.add(nid)
            if mode == "remove":
                # A grouping's uncheck must take its subtree along, exactly
                # like unchecking the folder by hand — the removal cascade of
                # `_expand_selection_with_deps` keys off the DELTA, so build
                # the removal set explicitly here.
                to_drop = set(matched_set)
                for nid in matched:
                    if (self._tree.find_type(nid) or "") in _GROUPING_KINDS:
                        to_drop.update(self._tree.find_all_descendant_ids(nid))
                # No trajectory guard here: `_expand_selection_with_deps`
                # below owns the veto (+ snackbar), so the bulk unselect and
                # a unitary uncheck behave identically — and it first
                # garbage-collects stale empty frames, which this local
                # guard used to count as "dependents".
                raw = [x for x in prev if x not in to_drop]
            else:
                raw = prev + [n for n in matched if n not in set(prev)]
            if len(raw) == len(prev):
                return  # nothing to change
            expanded = _expand_selection_with_deps(raw, prev, self._tree)
            # Pre-seed the shared `_prev_select_<tab>` tracker with the final
            # set. BOTH reactive handlers key off it, and a bulk select adds a
            # whole folder + all its leaves in one shot:
            #   - `_wire_dependency_expansion` sees a fixed point (as the
            #     docstring above relies on) — now explicitly, not by luck;
            #   - `_wire_select_to_active` would otherwise activate
            #     `new_ones[-1]`, an ARBITRARY node of the bulk — typically the
            #     grouping folder (e.g. BlockedWellboreFolder). Activating a
            #     non-property node makes the activator clear
            #     `active_color_array_name`, which greys the threshold
            #     union / intersect buttons even though the user never touched
            #     the active node.
            # With prev == curr it sees no new ids and leaves the active node
            # alone — while still falling back correctly if that node is not in
            # the new selection.
            setattr(state, f"_prev_select_{tab}", list(expanded))
            setattr(state, select_var, expanded)

        @controller.set("init_opened_nodes")
        def init_opened_nodes(tree_data):
            """Return the ids of the first-level (root) nodes only —
            used to seed the trees with their top entries expanded."""
            return [node["id"] for node in tree_data if node.get("parent_id") == 0 or "parent_id" not in node]

        try:
            state.ui_opened_reservoir = controller.init_opened_nodes(state.ui_subtree_reservoir)
        except Exception:
            state.ui_opened_reservoir = []
        try:
            state.ui_opened_surface = controller.init_opened_nodes(state.ui_subtree_surface)
        except Exception:
            state.ui_opened_surface = []
        try:
            state.ui_opened_well = controller.init_opened_nodes(state.ui_subtree_well)
        except Exception:
            state.ui_opened_well = []

        self._init_grid_selections()

        _wire_dependency_expansion(
            "ui_select_node_reservoir", "_prev_select_reservoir",
            "ui_active_node_reservoir", self._tree,
        )
        _wire_dependency_expansion(
            "ui_select_node_surface", "_prev_select_surface",
            "ui_active_node_surface", self._tree,
        )
        _wire_dependency_expansion(
            "ui_select_node_well", "_prev_select_well",
            "ui_active_node_well", self._tree,
        )

        # Cross-tab: a BlockedWellbore (reservoir tab) force-checks its
        # referenced trajectory in the WELL tab.
        _wire_blocked_well_trajectory(self._tree)

        # SolidColor variant: checking a grid property force-checks its grid
        # geometry (a property without its geometry makes no business sense).
        _wire_grid_geometry_on_property(self._tree)

        # update_selected from Vuetify gives the FULL selected array,
        # so writing `active = $event` would always pick array[0]
        # (the first ever selected), not the last clicked. The Python
        # handler below sets active to the newly-added node instead,
        # with a sensible fallback on removal.
        _wire_select_to_active(
            "ui_select_node_reservoir", "ui_active_node_reservoir",
            "_prev_select_reservoir",
        )
        _wire_select_to_active(
            "ui_select_node_surface", "ui_active_node_surface",
            "_prev_select_surface",
        )
        _wire_select_to_active(
            "ui_select_node_well", "ui_active_node_well",
            "_prev_select_well",
        )

    def _init_grid_selections(self):
        """For each top-level reservoir grid, ensure a per-grid
        selection state variable `ui_selected_grid_<id>` exists. Used
        when a per-grid single-leaf selection mode is needed on top of
        the global checkbox state."""
        if not hasattr(self.state, "ui_subtree_reservoir"):
            return

        for grid in self.state.ui_subtree_reservoir:
            grid_id = grid.get("id")
            if grid_id is not None:
                state_key = f"ui_selected_grid_{grid_id}"
                if not hasattr(self.state, state_key):
                    setattr(self.state, state_key, [])

    def _select_toolbar(self, tab, actions):
        """A 'Select / unselect ▾' dropdown above a tree tab. Each entry in
        `actions` is a `_BULK_ACTIONS` triple `(label, select_kinds,
        count_kinds)` and offers BOTH bulk actions on every node of the
        select kinds: a check-all button (load) and an uncheck-all button
        (unload), with a live "(N)" object count from `ui_bulk_counts`.
        Drives node SELECTION (data load), independent of the per-view
        eyes."""
        with html.Div(classes="px-1 pb-1"):
            with vuetify3.VMenu(location="bottom start", close_on_content_click=False):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        "Select / unselect",
                        v_bind="props",
                        size="small",
                        variant="tonal",
                        density="comfortable",
                        append_icon="mdi-menu-down",
                    )
                with vuetify3.VList(density="compact", min_width="260"):
                    for label, sel_kinds, _count_kinds in actions:
                        # SINGLE-quoted JS array: trame wraps the HTML
                        # attribute in double quotes, so a json.dumps here
                        # (double-quoted strings) breaks the attribute and
                        # Vue fails to compile the WHOLE page (blank app).
                        kinds = "[" + ",".join("'%s'" % k for k in sel_kinds) + "]"
                        count_key = f"{tab}|{label}"
                        with vuetify3.VListItem(
                            title=(
                                f"'{label} ('"
                                f" + (((ui_bulk_counts || {{}})['{count_key}']) || 0)"
                                " + ')'",
                            ),
                        ):
                            with vuetify3.Template(v_slot_append=True):
                                # icon=True + explicit VIcon child: Vuetify 3
                                # drops the `icon="mdi-…"` glyph as soon as the
                                # default slot has content (the tooltip here),
                                # leaving an invisible hover-only circle.
                                with vuetify3.VBtn(
                                    icon=True,
                                    size="x-small",
                                    variant="text",
                                    color="primary",
                                    classes="ml-2",
                                    click=(self.controller.tree_select_kinds,
                                           f"['{tab}', {kinds}, 'add']"),
                                ):
                                    vuetify3.VIcon("mdi-check-all")
                                    vuetify3.VTooltip(
                                        "Select all", activator="parent",
                                        location="bottom",
                                    )
                                with vuetify3.VBtn(
                                    icon=True,
                                    size="x-small",
                                    variant="text",
                                    color="grey-darken-1",
                                    click=(self.controller.tree_select_kinds,
                                           f"['{tab}', {kinds}, 'remove']"),
                                ):
                                    # MDI has no bare "double cross" in
                                    # mdi-check-all's style, so this is a
                                    # hand-drawn SVG: two red crosses on
                                    # one baseline, the FRONT one cutting
                                    # the back one out through an SVG
                                    # mask (same knockout check-all's
                                    # glyph uses) — clean separation on
                                    # any background, hover included.
                                    # Single quotes ONLY inside the
                                    # template literal: trame wraps HTML
                                    # attributes in double quotes.
                                    html.Div(
                                        v_html=(
                                            "`<svg xmlns='http://www.w3.org/2000/svg'"
                                            " viewBox='0 0 24 24' width='24' height='24'>"
                                            "<defs><mask id='fespp-unsel-cut'>"
                                            "<rect width='24' height='24' fill='white'/>"
                                            "<path d='M10.6 7.4 L19.8 16.6 M10.6 16.6 L19.8 7.4'"
                                            " stroke='black' stroke-width='5.2'"
                                            " stroke-linecap='round' fill='none'/>"
                                            "</mask></defs>"
                                            "<path d='M4.2 7.4 L13.4 16.6 M4.2 16.6 L13.4 7.4'"
                                            " stroke='#E53935' stroke-width='2.2'"
                                            " stroke-linecap='round' fill='none'"
                                            " mask='url(#fespp-unsel-cut)'/>"
                                            "<path d='M10.6 7.4 L19.8 16.6 M10.6 16.6 L19.8 7.4'"
                                            " stroke='#E53935' stroke-width='2.2'"
                                            " stroke-linecap='round' fill='none'/>"
                                            "</svg>`",
                                        ),
                                        style="width:24px; height:24px;",
                                    )
                                    vuetify3.VTooltip(
                                        "Unselect all", activator="parent",
                                        location="bottom",
                                    )

    def reservoir_tree(self):
        """Render the Reservoir tab's tree (IjkGrid / UnstructuredGrid
        roots and their property descendants)."""
        self._select_toolbar("reservoir", _BULK_ACTIONS["reservoir"])
        with vuetify3.VTreeview(
            slim=True,
            density="comfortable",
            opened=("ui_opened_reservoir", []),
            line="connected",
            item_value="id",
            # 'props': collapsed children are NOT mounted (default 'render'
            # mounts every item at once — measured as the client half of the
            # "no tree for 2-3 s" import stall and the bulk of the ~6000-DOM-
            # node reflow behind the slow tab switch). Needs Vuetify >= 3.10
            # (trame-vuetify >= 3.2.2, pinned in setup).
            items_registration="props",
            items=("ui_subtree_reservoir", []),
            activated=("ui_active_node_reservoir", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_reservoir = $event",
            color="primary",
            open_on_click=False,
            selectable=False,
            item_props=True,
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon(
                    v_if="!item.disabled && !((ui_invalid_node_ids || []).includes(item.id))",
                    icon=(_select_checkbox_icon("ui_select_node_reservoir"),),
                    size="small",
                    color=(_select_checkbox_color("ui_select_node_reservoir"),),
                    style="cursor: pointer; margin-right: 4px;",
                    click=(self.controller.tree_toggle_select, "[item.id, 'ui_select_node_reservoir']"),
                )
                # Blocked checkbox stand-in on INVALID nodes (unreadable
                # data): not clickable, visibly interdicted.
                vuetify3.VIcon(
                    "mdi-cancel",
                    v_if="!item.disabled && ((ui_invalid_node_ids || []).includes(item.id))",
                    size="small",
                    color="grey-lighten-1",
                    style="margin-right: 4px; cursor: not-allowed;",
                )
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
                # Unreadable-data badge (see vtk_log._flag_invalid_nodes).
                vuetify3.VIcon(
                    "mdi-alert",
                    size="small",
                    color="orange-darken-2",
                    v_if="(ui_invalid_node_ids || []).includes(item.id)",
                    classes="ml-1",
                )
                # Secondary badges for synthetic nodes — TimeSeries
                # (clock) and MultiRealization ("MR" chip) — combined
                # for MRTS leaves to stack up to 3 icons total
                # (primary property kind + TS + MR).
                vuetify3.VIcon(
                    "mdi-timeline-clock",
                    v_if="item.is_ts",
                    size="x-small",
                    color="purple",
                    classes="ml-1",
                )
                vuetify3.VChip(
                    "MR",
                    v_if="item.is_mr",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="ml-1",
                )
                _chip_slot()
            with vuetify3.Template(v_slot_append="{ item }"):
                _stats_slot(self.controller, "ui_select_node_reservoir")
                _eye_slot(self.controller)

    def surface_tree(self):
        self._select_toolbar("surface", _BULK_ACTIONS["surface"])
        with vuetify3.VTreeview(
            slim=True,
            density="compact",
            opened=("ui_opened_surface", []),
            line="connected",
            item_value="id",
            # 'props': collapsed children are NOT mounted (default 'render'
            # mounts every item at once — measured as the client half of the
            # "no tree for 2-3 s" import stall and the bulk of the ~6000-DOM-
            # node reflow behind the slow tab switch). Needs Vuetify >= 3.10
            # (trame-vuetify >= 3.2.2, pinned in setup).
            items_registration="props",
            items=("ui_subtree_surface", []),
            activated=("ui_active_node_surface", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_surface = $event",
            color="primary",
            open_on_click=False,
            selectable=False,
            # Pass item.disabled through so Vuetify greys partial nodes —
            # matches the reservoir tree (without it, a partial loses its
            # checkbox but the row text stays un-dimmed).
            item_props=True,
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon(
                    v_if="!item.disabled && !((ui_invalid_node_ids || []).includes(item.id))",
                    icon=(_select_checkbox_icon("ui_select_node_surface"),),
                    size="small",
                    color=(_select_checkbox_color("ui_select_node_surface"),),
                    style="cursor: pointer; margin-right: 4px;",
                    click=(self.controller.tree_toggle_select, "[item.id, 'ui_select_node_surface']"),
                )
                vuetify3.VIcon(
                    "mdi-cancel",
                    v_if="!item.disabled && ((ui_invalid_node_ids || []).includes(item.id))",
                    size="small",
                    color="grey-lighten-1",
                    style="margin-right: 4px; cursor: not-allowed;",
                )
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
                # Unreadable-data badge (see vtk_log._flag_invalid_nodes).
                vuetify3.VIcon(
                    "mdi-alert",
                    size="small",
                    color="orange-darken-2",
                    v_if="(ui_invalid_node_ids || []).includes(item.id)",
                    classes="ml-1",
                )
                vuetify3.VIcon(
                    "mdi-timeline-clock",
                    v_if="item.is_ts",
                    size="x-small",
                    color="purple",
                    classes="ml-1",
                )
                vuetify3.VChip(
                    "MR",
                    v_if="item.is_mr",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="ml-1",
                )
                _chip_slot()
            with vuetify3.Template(v_slot_append="{ item }"):
                _stats_slot(self.controller, "ui_select_node_surface")
                _eye_slot(self.controller)

    def well_tree(self):
        self._select_toolbar("well", _BULK_ACTIONS["well"])
        with vuetify3.VTreeview(
            slim=True,
            density="compact",
            opened=("ui_opened_well", []),
            line="connected",
            item_value="id",
            # 'props': collapsed children are NOT mounted (default 'render'
            # mounts every item at once — measured as the client half of the
            # "no tree for 2-3 s" import stall and the bulk of the ~6000-DOM-
            # node reflow behind the slow tab switch). Needs Vuetify >= 3.10
            # (trame-vuetify >= 3.2.2, pinned in setup).
            items_registration="props",
            items=("ui_subtree_well", []),
            activated=("ui_active_node_well", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_well = $event",
            color="primary",
            open_on_click=False,
            selectable=False,
            # Pass item.disabled through so Vuetify greys partial nodes —
            # matches the reservoir tree (without it, a partial loses its
            # checkbox but the row text stays un-dimmed).
            item_props=True,
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon(
                    v_if="!item.disabled && !((ui_invalid_node_ids || []).includes(item.id))",
                    icon=(_select_checkbox_icon("ui_select_node_well"),),
                    size="small",
                    color=(_select_checkbox_color("ui_select_node_well"),),
                    style="cursor: pointer; margin-right: 4px;",
                    click=(self.controller.tree_toggle_select, "[item.id, 'ui_select_node_well']"),
                )
                vuetify3.VIcon(
                    "mdi-cancel",
                    v_if="!item.disabled && ((ui_invalid_node_ids || []).includes(item.id))",
                    size="small",
                    color="grey-lighten-1",
                    style="margin-right: 4px; cursor: not-allowed;",
                )
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
                # Unreadable-data badge (see vtk_log._flag_invalid_nodes).
                vuetify3.VIcon(
                    "mdi-alert",
                    size="small",
                    color="orange-darken-2",
                    v_if="(ui_invalid_node_ids || []).includes(item.id)",
                    classes="ml-1",
                )
                vuetify3.VIcon(
                    "mdi-timeline-clock",
                    v_if="item.is_ts",
                    size="x-small",
                    color="purple",
                    classes="ml-1",
                )
                vuetify3.VChip(
                    "MR",
                    v_if="item.is_mr",
                    size="x-small",
                    variant="tonal",
                    color="purple",
                    classes="ml-1",
                )
                _chip_slot()
            with vuetify3.Template(v_slot_append="{ item }"):
                _stats_slot(self.controller, "ui_select_node_well")
                _eye_slot(self.controller)
