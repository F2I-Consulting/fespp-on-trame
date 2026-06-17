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
_GROUPING_KINDS = (
    "Collection",
    "Wellbore",
    "Partial",
    "Feature",
    "Interpretation",
    "Frame",
    "MarkerFrame",
)

# Domain-level dependency: a WellboreChannel or WellboreMarker requires
# its Wellbore's Trajectory (the geometry that anchors per-depth log
# values or marker positions). When the user checks one of these, we
# auto-check the Wellbore's Trajectory child too.
_WELLBORE_LEAF_KINDS_NEEDING_TRAJECTORY = ("WellboreChannel", "WellboreMarker")


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
        if kind in _WELLBORE_LEAF_KINDS_NEEDING_TRAJECTORY:
            wb = tree.find_parent_node_id_with_type(node_id, "Wellbore")
            if wb is not None:
                traj = tree.find_first_child_of_type(wb, "WellboreTrajectory")
                _add_implicit(traj)
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

        # Defensive safety net for a Vuetify label-click case where
        # both `update_activated` and `update_selected` fire and the
        # newly-activated node would be dropped from select (the
        # tree's custom checkbox below makes this unreachable in
        # practice, since label click no longer fires update_selected
        # — but keeping the guard costs nothing).
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


def _chip_slot():
    """Color chip rendered next to a tree node label.

    - No chip when the rep_path has no entry in
      tree_chip_color_by_path (rep not loaded yet).
    - Rainbow gradient when the entry is the sentinel "PROPERTY"
      (a dataArray is the active eye on the rep).
    - Conic gradient when the entry is the sentinel "MULTICOLOR"
      (a MarkerFrame whose child markers have 2+ distinct colours).
    - Solid mdi-circle in the assigned colour otherwise."""
    is_property = (
        "tree_chip_color_by_path && tree_chip_color_by_path[item.path] === 'PROPERTY'"
    )
    is_multicolor = (
        "tree_chip_color_by_path && tree_chip_color_by_path[item.path] === 'MULTICOLOR'"
    )
    is_solid = (
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
    visible = f"({is_property}) && ({is_selected})"
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
    # Exclude both frame kinds from the rep-eye gate.
    is_loaded_rep = (
        "ui_loaded_rep_paths && ui_loaded_rep_paths.indexOf(item.path) !== -1"
        " && item.type !== 'MarkerFrame' && item.type !== 'Frame'"
    )
    is_loaded_array = (
        "ui_loaded_array_paths && ui_loaded_array_paths.indexOf(item.path) !== -1"
    )
    # Marker leaves (WellboreMarker, runtime kind 'Marker') — MULTI-select
    # visibility, each independently toggleable per panel.
    is_loaded_marker = (
        "ui_loaded_marker_paths && ui_loaded_marker_paths.indexOf(item.path) !== -1"
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
                vuetify3.VIcon(
                    icon=(f"({is_hidden_in_panel}) ? 'mdi-eye-closed' : 'mdi-eye'",),
                    size="small",
                    color=(
                        f"!({has_active_array_in_panel})"
                        f" ? (({is_hidden_in_panel}) ? 'grey-darken-1' : 'blue-darken-1')"
                        " : 'grey-lighten-1'",
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

    def reservoir_tree(self):
        """Render the Reservoir tab's tree (IjkGrid / UnstructuredGrid
        roots and their property descendants)."""
        with vuetify3.VTreeview(
            slim=True,
            density="comfortable",
            opened=("ui_opened_reservoir", []),
            line="connected",
            item_value="id",
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
                    v_if="!item.disabled",
                    icon=(_select_checkbox_icon("ui_select_node_reservoir"),),
                    size="small",
                    color=(_select_checkbox_color("ui_select_node_reservoir"),),
                    style="cursor: pointer; margin-right: 4px;",
                    click=(self.controller.tree_toggle_select, "[item.id, 'ui_select_node_reservoir']"),
                )
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
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
        with vuetify3.VTreeview(
            slim=True,
            density="compact",
            opened=("ui_opened_surface", []),
            line="connected",
            item_value="id",
            items=("ui_subtree_surface", []),
            activated=("ui_active_node_surface", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_surface = $event",
            color="primary",
            open_on_click=False,
            selectable=False,
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon(
                    v_if="!item.disabled",
                    icon=(_select_checkbox_icon("ui_select_node_surface"),),
                    size="small",
                    color=(_select_checkbox_color("ui_select_node_surface"),),
                    style="cursor: pointer; margin-right: 4px;",
                    click=(self.controller.tree_toggle_select, "[item.id, 'ui_select_node_surface']"),
                )
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
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
        with vuetify3.VTreeview(
            slim=True,
            density="compact",
            opened=("ui_opened_well", []),
            line="connected",
            item_value="id",
            items=("ui_subtree_well", []),
            activated=("ui_active_node_well", []),
            activatable=True,
            active_strategy="single-independent",
            update_activated="ui_active_node_well = $event",
            color="primary",
            open_on_click=False,
            selectable=False,
            indent_lines="default",
            separate_roots=True,
        ):
            with vuetify3.Template(v_slot_prepend="{ item }"):
                vuetify3.VIcon(
                    v_if="!item.disabled",
                    icon=(_select_checkbox_icon("ui_select_node_well"),),
                    size="small",
                    color=(_select_checkbox_color("ui_select_node_well"),),
                    style="cursor: pointer; margin-right: 4px;",
                    click=(self.controller.tree_toggle_select, "[item.id, 'ui_select_node_well']"),
                )
                vuetify3.VIcon("{{item.icon}}", size="small", color="green-darken-1")
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
