"""The doors of the views: a new 3D view, the Globe, the Explorer, the
Stratigraphy and the log view (a wellbore sent to it from a right-click), the
camera links between views, and the layout of a view's tree."""
from fespp_on_trame.engine import node_facts, view_routing
from fespp_on_trame.engine.node_kinds import LOG_FRAMES
from fespp_on_trame.engine.state_defaults import z_scale_of


TREE_LAYOUTS = ("flat", "by_interpretation", "by_feature_and_interpretation", "kind")


def register(core, *, _panel_tick_read, _refresh_welllog, _xml_open_from_path):
    """Wire the section's controllers and watchers; the rest of the app calls
    nothing of it directly."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    activation = core.activation
    _mv = core.mv

    def _of_well(path, wid):
        """Whether the node `path` lies under the wellbore `wid`."""
        nid = tree.find_node_id(path)
        return nid is not None and tree.find_parent_node_id_with_type(nid, "Wellbore") == wid

    @state.change("assembly_xml")
    def _log_frame_rows(**_):
        """The log frames' rows: the trees offer "Add to Well Log view" on the
        logs under them (app/views/widgets/data_tree)."""
        rows = [tree.find_path(nid) for nid, _kids in tree.iter_nodes()
                if (tree.find_type(nid) or "") in LOG_FRAMES]
        rows = [r for r in rows if r]
        if rows != list(getattr(state, "ui_log_frame_rows", None) or []):
            state.ui_log_frame_rows = rows

    @controller.set("add_to_welllog")
    def add_to_welllog(path, selected=False):
        """Right-click "Add to Well Log view": the wellbore goes in the
        correlation panel (opened or focused) with the logs of the node
        right-clicked — a log; EVERY log of a frame, read first ("Add
        selected to Well Log view", `selected`: the frame's logs read
        already); the logs read of a wellbore."""
        if not path:
            return
        # the wellbore is what correlates, whatever node was right-clicked
        nid = tree.find_node_id(path)
        wid = (tree.find_parent_node_id_with_type(nid, "Wellbore")
               if nid is not None else None)
        well_path = tree.find_path(wid) if wid is not None else path
        mv = _mv()
        if mv is not None:
            try:
                mv.add_view(kind="welllog")   # singleton -> opens or focuses
            except Exception as exc:
                print("[fespp] open well-log view error:", exc, flush=True)

        def _logs_of_the_well():
            return [p for p in (getattr(state, "selected_paths", None) or ())
                    if _of_well(p, wid) and node_facts.is_property_kind(tree.find_type(tree.find_node_id(p)) or "")]

        def _add():
            wells = list(getattr(state, "ui_welllog_wells", None) or [])
            new = bool(well_path) and well_path not in wells
            if new:
                state.ui_welllog_wells = wells + [well_path]
            if wid is not None:
                # the logs under the node, in the log; a well new to it brings
                # those alone — the well's other logs read stay out of it
                under = path.rstrip("/") + "/"
                logs = _logs_of_the_well()
                mine = set(logs) if path == well_path else {p for p in logs if p == path or p.startswith(under)}
                for pid in (mv.panel_ids_of_kind("welllog") if mv is not None else ()):
                    var = f"welllog_dropped__{pid}"
                    dropped = set(getattr(state, var, None) or ())
                    if new:
                        dropped |= set(logs) - mine
                    dropped -= mine
                    if dropped != set(getattr(state, var, None) or ()):
                        state[var] = sorted(dropped)
                        # the log's own tree ticks what it now holds
                        controller.welllog_tree_ticks(pid)
            # the node sent, found in the log's own tree: unfolded to, lit
            for pid in (mv.panel_ids_of_kind("welllog") if mv is not None else ()):
                state[f"welllog_tree_active__{pid}"] = path
            _refresh_welllog()

        # one grammar: what a panel shows is loaded (the checkbox, common to
        # every view) — the node is read, hidden in the 3D views, and joins
        # the log once the read goes ahead; a frame's every log read with it
        every = [] if selected else node_facts.frame_logs(tree, path)
        _panel_tick_read([path] + every, None, _add)
        # the ui_welllog_wells watcher already fired — but on the FIRST
        # add the panel did not exist yet, so it found nothing to fill.
        _refresh_welllog()

    @controller.set("camlink_toggle")
    def camlink_toggle(view_id, other_id):
        """The Synchronize camera card's tick: synchronize this view with
        `other_id`, or stop, symmetrically. A closed or Globe view is
        refused."""
        from fespp_on_trame.app.views.widgets.view_link_menu import toggle_link
        live = {p.get("id") for p in (state.fespp_link_panels or [])
                if not p.get("globe")}
        if other_id not in live:
            print(f"[fespp] camera link refused ({view_id}): {other_id!r} is"
                  " not an open 3D view", flush=True)
            return
        toggle_link(state, str(view_id), str(other_id))
        mv = _mv()
        if mv is None:
            return
        mv.apply_camera_links()
        # a view just linked starts where the card's view stands, instead of
        # waiting for whichever of the two renders first
        if str(other_id) in ((state.view_links or {}).get(str(view_id)) or []):
            controller.set_zscale_now(z_scale_of(state, view_id), view_id)
            mv.copy_camera(str(view_id), str(other_id))

    @controller.set("camlink_follow")
    def camlink_follow(view_id):
        """The title-bar link of a view drawing one thing on its own (the
        Stratigraphy panel's 3D, which has no cards): linked with the last
        3D view of the data used, from where that view stands; linked
        already, unlinked from every view."""
        from fespp_on_trame.app.views.widgets.view_link_menu import toggle_link
        vid = str(view_id)
        mine = list((state.view_links or {}).get(vid) or [])
        other = ""
        if mine:
            for linked in mine:
                toggle_link(state, vid, linked)
        else:
            live = [p.get("id") for p in (state.fespp_render_panels or []) if not p.get("globe")]
            other = getattr(state, "fespp_last_render_panel_id", None) or ""
            if other not in live:
                other = live[0] if live else ""
            if not other:
                print(f"[fespp] camera link refused ({vid}): no 3D view of the data", flush=True)
                return
            toggle_link(state, vid, other)
        mv = _mv()
        if mv is None:
            return
        mv.apply_camera_links()
        if other:
            controller.set_zscale_now(z_scale_of(state, other), other)
            mv.copy_camera(other, vid)

    @controller.set("view_focus")
    def view_focus(view_id):
        """A tile of the top bar's 3D views door: that 3D view the active
        one, its tab in front — shown again first when it was hidden."""
        mv = _mv()
        vid = str(view_id or "")
        if mv is None or mv.kind_of(vid) != "render":
            return
        mv.focus_panel(vid)
        print(f"[fespp] journal views: {mv.title_of(vid)} active", flush=True)

    @controller.set("view_hidden_toggle")
    def view_hidden_toggle(view_id):
        """The eye of a tile of the top bar's 3D views door: that 3D view
        hidden (out of the screen, its objects, camera and cards kept) or
        shown again where it was."""
        mv = _mv()
        vid = str(view_id or "")
        if mv is None or mv.kind_of(vid) != "render":
            return
        hidden = vid in mv.hidden()
        (mv.show_panel if hidden else mv.hide_panel)(vid)
        print(f"[fespp] journal views: {mv.title_of(vid)} {'shown again' if hidden else 'hidden'}", flush=True)

    @controller.set("ask_new_render_view")
    def ask_new_render_view():
        """Open the dialog asking what the new view starts from.

        The top bar's button asks instead of deciding: a copy of the current
        view suits the same data side by side, a blank view suits building
        something else, and only the reader knows which. With no 3D view
        open there is nothing to copy: the view opens empty, nothing asked."""
        mv = _mv()
        if mv is not None and not [v for v in (mv.view_ids() or []) if mv.kind_of(v) == "render"]:
            open_render_view(None)
            return
        state.ui_newview_open = True

    @controller.set("open_render_view")
    def open_render_view(source_id=None):
        """Add a 3D view.

        One button in the app toolbar rather than one in every panel's title
        bar: adding a view is an application action, not a per-view one.

        `source_id` names an existing render view to COPY — its eyes, its
        camera and its exaggeration, so the second view starts where the
        first one is, without eyes to reopen one by one. Empty or unknown
        opens a blank view, which is also what the first view of a session
        is.

        It does NOT synchronize the two cameras. A copy is a starting point:
        a second view is often there to look at the same data ANOTHER way,
        and a view that dragged its neighbour along from the first click
        would take that away. Synchronizing is one tick in the view's own
        card, and it stays where the reader puts it."""
        state.ui_newview_open = False
        mv = _mv()
        if mv is None:
            return
        ref = str(source_id or "")
        if ref not in (mv.view_ids() or []) or mv.kind_of(ref) != "render":
            ref = ""
        # a tab of its own, as every view but the T→D model
        try:
            vid = mv.add_view(kind="render", reference_panel_id=ref or None)
        except Exception as exc:
            print("[fespp] open render view error:", exc, flush=True)
            return
        if not ref or not vid:
            return
        try:
            controller.set_zscale_now(z_scale_of(state, ref), vid)
            controller.inherit_eyes(vid, ref)
            mv.copy_camera(ref, vid)
        except Exception as exc:
            print(f"[fespp] second view setup error ({vid} from {ref}):",
                  exc, flush=True)

    @controller.set("open_globe")
    def open_globe():
        """The Globe, a tab showing what the 3D view in use shows; its camera
        then goes its own way. The one Globe of the session, open already,
        comes to the front."""
        mv = _mv()
        if mv is None:
            return
        renders = [v for v in (mv.view_ids() or []) if mv.kind_of(v) == "render"]
        ref = getattr(state, "fespp_last_render_panel_id", "") or ""
        if ref not in renders:
            ref = renders[0] if renders else ""
        try:
            mv.add_view(kind="globe", reference_panel_id=ref or None)
        except Exception as exc:
            print("[fespp] open globe view error:", exc, flush=True)

    # the views a button of the top bar opens and closes, by what opens them
    _DOORS = {"globe": "open_globe", "values": "open_values", "timedepth": "open_time_depth", "xml": "open_xml_explorer",
              "compare": "open_compare", "calculator": "open_calculator", "stratigraphy": "open_stratigraphy",
              "welllog": "open_welllog", "reconcile": "open_reconcile", "health": "open_health"}

    @controller.set("view_door")
    def view_door(kind):
        """A view's button in the top bar: it opens the view, or brings it to
        the front from behind another tab; in sight, it closes it."""
        mv = _mv()
        panels = list(mv.panel_ids_of_kind(kind) or ()) if mv is not None else []
        if any(mv.on_screen(p) for p in panels):
            mv.remove_panel(panels[0])
        elif kind in _DOORS:
            getattr(controller, _DOORS[kind])()

    @controller.set("view_float")
    def view_float(view_id, room_w, room_h, left=None, top=None):
        """A view's detach button in its tab row: detached from the dock, or
        anchored again. Its tab dropped where nothing docks it (`left`, `top`:
        the drop point in the dock): detached there."""
        mv = _mv()
        if mv is None:
            return
        if left is not None and top is not None:
            mv.detach_panel(view_id, room_w, room_h, left, top)
        elif view_id in (getattr(state, "ui_floating_views", None) or ()):
            mv.anchor_panel(view_id)
        else:
            mv.detach_panel(view_id, room_w, room_h)

    @controller.set("view_fill")
    def view_fill(title):
        """A double click on the tab row of a detached view: it fills the dock
        with the other views as its tabs, or lets go."""
        mv = _mv()
        if mv is not None:
            mv.fill.toggle(title)

    @controller.set("open_time_depth")
    def open_time_depth():
        """The model's view, along the bottom; the model comes with it in the
        3D view in use (app/features/time_depth_tree)."""
        mv = _mv()
        if mv is None:
            return
        mv.add_view(kind="timedepth")
        in_use = view_routing.model_view(state)
        # the velocity model is in time: the 3D view in use goes there (the
        # manager, 12/11)
        to_time = getattr(core.ctx, "view_domain_set", None)
        print(f"[fespp] journal view: the time-depth model's view opened, 3D view in use {in_use or 'none'}",
              flush=True)
        if in_use and to_time is not None:
            to_time(in_use, "time")
        show = getattr(core.ctx, "time_depth_show", None)
        if in_use and show is not None:
            show(in_use)

    @controller.set("open_values")
    def open_values():
        """The Values view, beside the 3D view it reads: a tab would hide the
        scene whose row is clicked."""
        mv = _mv()
        if mv is None:
            return
        beside = getattr(state, "fespp_last_render_panel_id", "") or None
        with mv.placed("right", beside):
            mv.add_view(kind="values")

    @controller.set("tree_layout_set")
    def tree_layout_set(mode, view_id=None):
        """How a view's tree lays out the forest. Its widget draws it on the same
        paths: nothing is unticked, read again or moved."""
        if view_id and mode in TREE_LAYOUTS:
            state[f"ui_tree_layout__{view_id}"] = mode

    @controller.set("open_xml_explorer")
    def open_xml_explorer():
        """Open the XML explorer on whatever node is active in the active
        render view — the object the Attributes card is showing. With nothing
        active it still opens, and says where to start."""
        mv = _mv()
        if mv is None:
            return
        # the last 3D view, not the focused panel: a Statistics panel just
        # opened has the focus and no active node (D21)
        vid = view_routing.resolve_active_render_panel(state)
        _xml_open_from_path(activation.path(vid) if vid else "")

    @controller.set("open_stratigraphy")
    def open_stratigraphy():
        """Open a stratigraphic column panel. Like the log view, it needs no
        selection: the column comes from the loaded files, not from a scene."""
        mv = _mv()
        if mv is None:
            return
        try:
            mv.add_view(kind="stratigraphy")
        except Exception as exc:
            print("[fespp] open stratigraphy view error:", exc, flush=True)
            return
        controller.ensure_stratigraphy()

    @controller.set("open_welllog")
    def open_welllog():
        """Open (or focus) the log view, with no context at all.

        Session-level like the data import: WHICH wells the view holds is
        chosen in the view's own tree, so the button needs nothing selected
        and belongs in the layout toolbar rather than in a right-click.
        """
        mv = _mv()
        if mv is None:
            return
        try:
            mv.add_view(kind="welllog")   # singleton -> opens or focuses
        except Exception as exc:
            print("[fespp] open well-log view error:", exc, flush=True)
