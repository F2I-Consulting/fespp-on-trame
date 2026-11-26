"""Symmetric per-view state lifecycle — the ONE inventory of per-view keys.

Contract
--------
Input:     the trame ``state`` + a view id.
Behaviour: ``seed(state, vid)`` marks the view LIVE, defaults its suffixed
           vars (all but the ones a panel declares itself, factory None) and
           makes sure every dict bucket exists; ``teardown(state,
           vid)`` marks it dead FIRST (so the never-unregistered ``@state.change``
           closures early-exit via ``is_live``), then nulls the suffixed vars,
           pops the view's entry from every bucket and forgets its first-frame
           flag. Every per-view key seeded anywhere in ``app.boot`` MUST be
           listed here — add to these tuples when adding a per-view var, and
           the close path stays symmetric for free.
Reads:     nothing beyond the given state.
Writes:    the suffixed vars + dict buckets below.

``FRAMED`` holds the view ids whose camera was already framed once on first
data; it is cleared on close so a reopened id frames again.
"""

# (prefix, default_factory) — full var name = prefix + view_id. A None
# factory marks a key that only a panel creates, under its own id: `seed`
# runs for render views alone and leaves it out, `teardown` clears it.
SUFFIXED_VARS = (
    ("visible_paths__", list),
    ("active_path__", str),
    ("active_by_tab__", dict),
    ("eye_toggle__", lambda: None),
    ("colour_request__", lambda: None),
    ("ui_colormap__", dict),
    # what each tool card acts on, by tool key — named in its title bar
    ("ui_tool_target__", dict),
    ("ui_tool_title__", dict),
    # the active object's own colour and opacity (app/features/object_look)
    ("ui_object_look__", dict),
    # what each tool card's panel is made with (app/views/view_panel)
    ("ui_card_specs__", None),
    # the object a slicer card was pointed at in its list, by tool key
    # (app/scene/activation.pin; 28/10), and the objects each card can take
    ("tool_pin__", dict),
    ("ui_tool_targets__", dict),
    ("ui_card_layout__", lambda: None),
    ("ui_card_reveal__", lambda: None),     # {id, n}: the card a button brings in front  # where the cards were left in the view's dock
    ("ui_card_geometry__", dict),   # where each tool card was left: {tool: {x, y, w, h, dock}}
    ("ui_cmap_colors__", list),
    ("ui_cmap_opacities__", list),
    # the Legends card: every table colouring the view, the one holding its
    # one colour bar marked (engine/legends)
    ("ui_legends__", dict),
    ("ui_timereal__", dict),
    # the Time & Realizations card as the shared slicer card (29/10)
    ("ui_timereal_card__", dict),
    ("ui_timereal_player__", dict),
    ("ui_pick_mode__", lambda: False),    # hand: click = cell, drag = cells ON the surface
    ("ui_frustum_mode__", lambda: False), # frustum: drag = cells THROUGH the volume
    ("ui_cursor_mode__", lambda: False),  # crosshair button: cursor position
    ("ui_cursor_pos__", str),
    ("values_folder__", list),            # the rows ticked last, the Values card reads them
    ("ui_values_node__", str),            # the node it reads there, "" the active node
    ("ui_pick_info__", str),               # last pick: node / cell / value
    ("ui_view_note__", str),               # a note under the view (app/core/notifier)
    # the wheel was refused because the next notch would have put the eye
    # inside the data (camera.WheelWall). Cleared by the first notch that
    # is not refused.
    ("ui_zoom_note__", str),
    ("ui_globe__", dict),                  # Globe card: crs / epsg / mode / opacity
    # the view's colours of the velocity model, for the time-depth card's
    # tracks (app/features/time_depth_pins)
    ("ui_time_depth_colors__", dict),
    ("ui_globe_mode__", lambda: False),    # this view is the Globe
    # the Globe's scene, built one turn after its view: its card says so
    ("ui_globe_busy__", lambda: False),
    # the title bar's interaction mode, "3D" or "2D" (2D locks the rotation).
    # Per view: one global value would let one view's button drive another.
    ("ui_interaction_mode__", lambda: "3D"),
    # the vertical domain the view draws, "depth" or "time" (the PO, 28/10;
    # app/features/view_domain)
    ("ui_vdomain__", lambda: "depth"),
    ("ui_scale_z__", lambda: 1.0),
    # the objects of the other domain drawn converted with the time-depth
    # law (the PO, 30/10; app/features/view_domain)
    ("converted_paths__", list),
    # the ticked objects of the other domain not drawn: no eye on their rows
    ("undrawn_paths__", list),
    # those of them the view never converts: their tag is no button
    ("fixed_paths__", list),
    # "Represent By" of THIS view's composite rep. BlockScope draws every
    # block through ONE rep, so the style is per VIEW, not per rep. Asserted
    # explicitly, never inherited from ParaView's Show() guess, which can
    # pick Outline (notably for ETP sources).
    ("ui_rep_style__", lambda: "Surface"),
    # the title bar's shading toggle: True = exact colours (no shading)
    ("ui_flat_colors__", lambda: False),
    # navigation card: a pick happened in this view (gates centre / zoom on
    # it), and this view's projection is parallel
    ("ui_nav_has_pick__", lambda: False),
    # the cells the selection holds, per tree row ({row path: count}): the
    # grid's row offers "+" (keep / remove the selection) while it has some
    ("ui_sel_counts__", dict),
    # the rows the SESSION adds to this view's tree (derived properties,
    # selection extracts): made here, never written to the file
    ("ui_session_rows__", list),
    ("ui_nav_parallel__", lambda: False),
    # the render's right-click menu: {open, x, y, title, path, items}
    ("ui_ctx_menu__", dict),
    # the tool cards' own state, created by each card under the view's id
    # (setdefault in tools_config / boot): declared with no factory, so a
    # closed view takes them along instead of leaving them for the session
    ("ui_slicers__", None),
    ("ui_thresholds__", None),
    # the two slicer cards and their players (app/features/geometry_slicer,
    # property_slicer; 28/10)
    ("ui_geometry_card__", None),
    ("ui_geometry_player__", None),
    ("ui_property_card__", None),
    ("ui_property_player__", None),
    ("ui_thresholds_note__", None),
    ("ui_volumetrics__", None),
    # the XML panel's own keys, under its panel id (app/views/xml_panel)
    ("xml_tabs__", None),
    ("xml_tab__", None),
    ("xml_xml__", None),
    ("xml_note__", None),
    ("xml_relations__", None),
    ("xml_hits__", None),
    ("xml_raws__", None),
    ("ui_nav_pivot_shown__", lambda: False),  # the centre-of-rotation cross
    ("ui_nav_axes_grid__", lambda: False),    # the graduated box (scale)
    ("ui_tree_layout__", lambda: "flat"),  # how this view's tree lays out the forest
    ("ui_view_busy__", lambda: False),     # this view is working (app/views/widgets/view_wait)
    ("pos_ev__", lambda: None),        # throttled mousemove [ox, oy, cw, ch]
    # the well-log panel: its payload is the biggest per-view value in the
    # session (hundreds of KB of curve samples), so a closed panel must not
    # keep it.
    ("welllog_data__", lambda: None),
    ("welllog_zoom__", lambda: 1.0),
    # the panels' own toggles: their docked trees and the well-log
    # zone-statistics table, reset on close like every other key here
    ("welllog_tree_open__", lambda: False),
    ("reconcile_tree_open__", list),       # the open family cards of its tree
    ("reconcile_card_layout__", lambda: None),  # where they were left in its dock
    ("welllog_zones_open__", lambda: False),
    ("welllog_cutoffs__", list),            # [{curve, op, value}] -> pay flag
    ("welllog_synth_open__", lambda: False),  # the "from grid" editor
    ("welllog_flatten__", lambda: None),    # marker name the panel is flattened on
    ("welllog_align__", lambda: "TVD"),     # the depth the wells are laid out on: TVD or MD
    ("welllog_markers_off__", list),        # the markers dimmed (a click on a name)
    ("welllog_card_layout__", lambda: None),  # where the zone statistics card was left
    # the read curves this log was told to leave out (unticked in its own
    # tree): a closed panel keeps no opinion about the next one's curves
    ("welllog_dropped__", list),
    # The docked trees of the panels. What each one holds (`selected`) is
    # rebuilt from the panel on its next opening; the eyes are republished
    # by `panel_tree_eyes`, and the sinks must come back declared or the
    # rebuilt tree writes into an undeclared key.
    ("welllog_tree_selected__", list),
    ("welllog_tree_eye__", list),
    ("welllog_tree_shown__", list),
    ("welllog_tree_toggle__", lambda: None),
    ("welllog_tree_ctx__", lambda: None),
    ("welllog_tree_active__", str),
    ("welllog_tree_active_by_tab__", dict),
    ("welllog_tree_colour__", lambda: None),
    ("welllog_tree_layout__", lambda: "flat"),
    # the active node of the log view's tree brought to its middle
    ("welllog_focus__", lambda: None),
    ("reconcile_tree_selected__", list),
    ("reconcile_tree_eye__", list),
    ("reconcile_tree_shown__", list),
    ("reconcile_tree_toggle__", lambda: None),
    ("reconcile_tree_ctx__", lambda: None),
    ("reconcile_tree_active__", str),
    ("reconcile_tree_active_by_tab__", dict),
    ("reconcile_tree_colour__", lambda: None),
    # Declared by their panel only (factory None, see above): the Statistics
    # panel's open family cards and where they were left, and its trees
    # (widgets/compare_tree), whose selection and eyes boot republishes when
    # the panel opens (`_ensure_compare_view`)
    ("compare_tree_open__", None),
    ("compare_card_layout__", None),
    ("compare_tree_selected__", None),
    ("compare_tree_loaded__", None),
    ("compare_tree_eyeable__", None),
    ("compare_tree_eye__", None),
    ("compare_tree_shown__", None),
    ("compare_tree_toggle__", None),
    ("compare_tree_ctx__", None),
    ("compare_tree_active__", None),
    ("compare_tree_active_by_tab__", None),
    ("compare_tree_colour__", None),
)

# state dicts keyed by view_id (seeded in app.boot / app state_defaults)
DICT_BUCKETS = (
    "ui_open_tools_by_view",
    "ui_active_node_by_view",
    "ui_node_xml_by_view",
    "ui_node_values_by_view",
    "ui_values_key_by_view",
    "ui_node_values_csv_by_view",
    "ui_color_arrays_by_view",
    "ui_active_array_by_view",
    "ui_active_colormap_by_view",
    "ui_hidden_rep_paths_by_view",
    "ui_visible_marker_paths_by_view",
    "ui_active_realization_by_array_by_view",
    "ui_active_array_by_rep_by_view",
)

FRAMED = set()   # view ids already camera-framed on first data
_LIVE = set()    # view ids between seed() and teardown()


def is_live(vid) -> bool:
    """Tell whether view ``vid`` is open (between ``seed`` and ``teardown``).

    The guard of the per-view ``@state.change`` closures: trame cannot
    unregister them, so they must no-op once their view is closed.
    """
    return str(vid) in _LIVE


def seed(state, vid) -> None:
    vid = str(vid)
    _LIVE.add(vid)
    for prefix, factory in SUFFIXED_VARS:
        if factory is None:
            continue   # a panel's own key: its panel declares it
        name = prefix + vid
        if getattr(state, name, None) is None:
            state[name] = factory()
    for key in DICT_BUCKETS:
        if getattr(state, key, None) is None:
            state[key] = {}


def drop_listeners(state, keys) -> int:
    """Forget every `@state.change` handler registered on `keys`.

    trame offers no way to unregister one, and a handler bound to a closed
    view or panel would otherwise stay in the table for the life of the
    session, called on every change of a var nothing writes any more. The
    keys of a view or panel are its own (suffixed by its id), so dropping a
    key's whole list is exact. Returns how many handlers were dropped.
    """
    table = getattr(state, "_change_callbacks", None)
    if not isinstance(table, dict):
        return 0
    gone = 0
    for key in keys:
        entry = table.pop(key, None)
        if entry:
            gone += len(entry)
    return gone


def teardown(state, vid) -> None:
    from fespp_on_trame.app.views.widgets import docked_tree

    vid = str(vid)
    _LIVE.discard(vid)   # first: the guards must already see the view as dead
    FRAMED.discard(vid)
    # the view's own change handlers go with it (the guards above keep a
    # late call harmless, but a session that opens and closes views all day
    # must not accumulate them)
    drop_listeners(state, [prefix + vid for prefix, _f in SUFFIXED_VARS])
    # whether this view's docked tree had already been given its opening
    # state: kept out of the state on purpose (the loop below nulls those),
    # so it is dropped here instead
    docked_tree.forget(vid)
    for prefix, _factory in SUFFIXED_VARS:
        name = prefix + vid
        if getattr(state, name, None) is not None:
            state[name] = None
    for key in DICT_BUCKETS:
        bucket = getattr(state, key, None) or {}
        if vid in bucket:
            bucket = dict(bucket)
            bucket.pop(vid, None)
            state[key] = bucket
