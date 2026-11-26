"""the Log ↔ Grid panel's OWN tree
A view that chooses its own content (the principle the Statistics and
well-log panels follow): its tree holds LOG CHANNELS (Well
tab) and GRID PROPERTIES (Reservoir tab). A tick puts the object in
this table and reads it, born hidden (`_panel_tick_read`); an untick
takes it out of the table and unloads nothing. The log view's wells
also feed it ("Add to Well Log view"): the two doors merge.

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine import stats_dispatch
from fespp_on_trame.engine import tree_grammar


def register(core, *, _display_title, _is_property_path, _panel_tick_read,
             _reconcile_inputs, _refresh_reconcile, _say, _wellbore_of):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    _mv = core.mv
    # --- the Log ↔ Grid panel's OWN tree -----------------------------------
    # A view that chooses its own content (the principle the Statistics and
    # well-log panels follow): its tree holds LOG CHANNELS (Well
    # tab) and GRID PROPERTIES (Reservoir tab). A tick puts the object in
    # this table and reads it, born hidden (`_panel_tick_read`); an untick
    # takes it out of the table and unloads nothing. The log view's wells
    # also feed it ("Add to Well Log view"): the two doors merge.

    def _is_channel_path(path):
        """A log channel: a property under a wellbore."""
        if not _is_property_path(path):
            return False
        nid = tree.find_node_id(path)
        return (nid is not None
                and tree.find_parent_node_id_with_type(nid, "Wellbore") is not None)

    def _is_grid_prop_path(path):
        """A property the table can sample along a well: on an IJK or an
        unstructured grid (`reconcile_dispatch.grid_properties`' test)."""
        if not _is_property_path(path) or _is_channel_path(path):
            return False
        rep_path = stats_dispatch._rep_path_for_array_path(tree, path)
        rid = tree.find_node_id(rep_path) if rep_path else None
        return rid is not None and (tree.find_type(rid) or "") in (
            "IjkGrid", "UnstructuredGrid")

    def _reconcile_leaf(path):
        return _is_channel_path(path) or _is_grid_prop_path(path)

    def _reconcile_leaves(paths):
        """What a tick set stands for in this table: a channel or a grid
        property is itself; a wellbore, a frame, a grid, a folder every
        channel and grid property under it (the cascade is the server's, in
        every tree)."""
        def _descendants(path):
            nid = tree.find_node_id(path)
            if nid is None:
                return []
            return [p for p in (tree.find_path(d)
                                for d in tree.find_all_descendant_ids(nid))
                    if p and _reconcile_leaf(p)]
        return tree_grammar.expand(paths, _reconcile_leaf, _descendants)

    def _reconcile_ticks():
        """The panel tree's checkboxes ARE what the table holds: the channels
        it reads and the grid properties it can set them against."""
        wells, selected = _reconcile_inputs()
        held_wells = set(wells)
        chans = [p for p in selected
                 if _is_channel_path(p) and _wellbore_of(p) in held_wells]
        out = set(getattr(state, "ui_reconcile_dropped", None) or [])
        props = [p for p in (getattr(state, "ui_loaded_array_paths", None) or [])
                 if p not in out and _is_grid_prop_path(p)]
        return chans + props

    # the tick set last PUBLISHED per view: an untick is read against it,
    # never against the session's selection (the well-log tree's rule, for
    # the same reason — the server's own rewrite coming back is no gesture)
    _reconcile_published = {}

    @controller.set("reconcile_tree_ticks")
    def reconcile_tree_ticks(view_id):
        vid = str(view_id or "")
        ticks = _reconcile_ticks()
        _reconcile_published[vid] = set(ticks)
        state[f"reconcile_tree_selected__{vid}"] = ticks

    def _sync_reconcile_trees():
        mv = _mv()
        if mv is None:
            return
        live = set(mv.panel_ids_of_kind("reconcile"))
        for dead in [v for v in _reconcile_published if v not in live]:
            _reconcile_published.pop(dead, None)
        if not live:
            return
        ticks = _reconcile_ticks()
        for vid in live:
            var = f"reconcile_tree_selected__{vid}"
            _reconcile_published[vid] = set(ticks)
            if set(getattr(state, var, None) or []) != set(ticks):
                state[var] = ticks

    @controller.set("reconcile_tree_paths")
    def reconcile_tree_paths(view_id, paths, read=True):
        """The Log ↔ Grid panel's own tree: a tick puts the channel or the
        grid property IN THIS TABLE and reads it, hidden; an untick takes it
        out of the table and unloads nothing. A wellbore, a frame, a grid or
        a folder stands for every channel or grid property under it."""
        vid = str(view_id or "")
        incoming = {p for p in (paths or ()) if p}
        if vid in _reconcile_published and incoming == _reconcile_published[vid]:
            return   # the server's own rewrite coming back, not a gesture
        published = _reconcile_published.get(vid, set())
        leaves = set(_reconcile_leaves(sorted(incoming)))
        gained = [p for p in sorted(leaves) if p not in published]
        lost = [p for p in published if p not in leaves]
        # a tick that stands for nothing this table reads would come off
        # again with no word said
        for path in sorted(incoming - published):
            if not _reconcile_leaves([path]):
                _say(f"{_display_title(path, 'That node')} holds no log channel"
                     " and no grid property — this table sets logs against"
                     " grid properties.")
                break
        own = list(getattr(state, "ui_reconcile_logs", None) or [])
        dropped = list(getattr(state, "ui_reconcile_dropped", None) or [])
        new_own = [p for p in own if p not in lost]
        new_own += [p for p in gained if _is_channel_path(p) and p not in new_own]
        new_dropped = [p for p in dropped if p not in gained]
        new_dropped += [p for p in lost if p not in new_dropped]
        # what to read: the leaves just ticked, and a ticked wellbore itself,
        # whose cascade also brings its trajectory and its markers — the
        # zones the table is cut into
        wellbores = [p for p in sorted(incoming - published)
                     if (tree.find_type(tree.find_node_id(p)) or "") == "Wellbore"]
        sel = set(getattr(state, "selected_paths", None) or [])
        # an eye, a tick's take or an unload's prune (app/scene/panel_trees)
        # reads nothing
        reading = [p for p in gained + wellbores if p not in sel] if read else []

        def _hold():
            moved = False
            if new_own != list(getattr(state, "ui_reconcile_logs", None) or []):
                state.ui_reconcile_logs = new_own
                moved = True
            if set(new_dropped) != set(getattr(state, "ui_reconcile_dropped", None) or []):
                state.ui_reconcile_dropped = new_dropped
                moved = True
            if not moved and not reading:
                # `_on_reconcile_inputs` re-syncs the boxes whenever what the
                # table holds or the read moves; when neither did, nothing
                # else will. Syncing HERE while a read goes ahead would run
                # before `_apply_selection` writes `selected_paths`: the boxes
                # would be published without the channel just ticked, then
                # with it, and the browser's echo of the first write would
                # come back as an untick, landing the log in
                # `ui_reconcile_dropped`.
                _sync_reconcile_trees()

        def _cancel():
            _sync_reconcile_trees()

        if not read:
            _hold()
            return
        _panel_tick_read(gained + wellbores, _cancel, _hold)

    # Log <-> Grid in the one grammar (app/scene/panel_trees): the eye of its
    # tree is "in this table"
    def _reconcile_vids():
        mv = core.mv()
        return list(mv.panel_ids_of_kind("reconcile")) if mv is not None else []

    core.panel_trees.add(
        "reconcile", vids=_reconcile_vids,
        held=lambda vid: list(_reconcile_ticks()),
        hold=lambda vid, paths: reconcile_tree_paths(vid, paths, read=False),
        title=lambda vid: (core.mv().title_of(vid) if core.mv() is not None
                           else "Log ↔ Grid"))

    @controller.set("reconcile_tree_action")
    def reconcile_tree_action(view_id, ev):
        """The panel tree's right-click menu: in or out of this table, and
        lighting the object up in a 3D view — through the routing the
        checkbox uses, so the menu and the tick cannot mean two things."""
        ev = ev if isinstance(ev, dict) else {}
        action, path = ev.get("action"), ev.get("path")
        if not action or not path:
            return
        ticks = _reconcile_ticks()
        if action == "reconcile-add":
            reconcile_tree_paths(view_id, ticks + ([path] if path not in ticks else []))
        elif action == "reconcile-remove":
            under = set(_reconcile_leaves([path]))
            reconcile_tree_paths(view_id, [p for p in ticks if p not in under])

    @state.change("ui_welllog_wells", "selected_paths", "ui_loaded_array_paths",
                  "ui_strati_columns", "ui_reconcile_logs", "ui_reconcile_dropped",
                  "ui_loaded_rep_paths")
    def _on_reconcile_inputs(**_):
        _refresh_reconcile()
        _sync_reconcile_trees()
