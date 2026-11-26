"""WellLogTree — the log view's own well tree, docked inside the panel.

Contract
--------
Input:     ``server`` and ``view_id``.
Behaviour: renders a ``DataExplorerTree`` showing ONLY the Well tab, under
           the one grammar every tree of the application follows
           (``engine/tree_grammar``):

           * the CHECKBOX puts the wellbore IN THE LOG and reads it — its
             trajectory, its frames and its channels — so the panel fills
             with the curves of what was ticked. Unticking takes the well
             out of the log and unloads nothing.
           * the EYE is the 3D eye: shown in a 3D view, nothing else. It is
             offered on what a view could show (``eye_paths``), never gated
             on this panel's ticks.

           Any node below a wellbore resolves up to it, because the log
           view's unit is the wellbore whatever node was ticked.
Reads:     ``assembly_xml``, ``ui_welllog_wells``,
           ``welllog_tree_eye__<vid>`` / ``welllog_tree_shown__<vid>`` (the
           3D visibility and what may carry an eye, both server-written).
Writes:    ``welllog_tree_selected__<vid>`` (two-way: the reader ticks, the
           server rewrites it — and seeds it, through
           ``controller.welllog_tree_ticks`` — from what the log draws) and,
           through ``controller.welllog_tree_wells``, that set;
           ``controller.panel_tree_eye`` for an eye;
           ``controller.welllog_tree_action`` for the right-click menu.

Same split as ``DataTree``: the widget owns its outputs, the branching lives
in the controller it calls — the tree stays path-agnostic.
"""
from trame_fespp_tree.widgets.tree import DataExplorerTree

from fespp_on_trame.app.scene.activation import well_node_to_open

# The Well tab's node types, as the full explorer declares them. Only this tab:
# a log view has nothing to say about a grid or a surface.
_WELL_TYPES = ("Wellbore", "Trajectory", "WellboreTrajectory", "MarkerFrame")
_WELL_TAB = ("[{name:'Well',types:['Wellbore','Trajectory',"
             "'WellboreTrajectory','MarkerFrame']}]")

# What a right-click offers HERE: the two acts of THIS panel. Membership is
# the WELLBORE's — the log's unit — so the pair is offered on the wellbore
# and nowhere else.
_CONTEXT_ACTIONS = [
    {"key": "welllog-add", "label": "Add to this view",
     "types": ["Wellbore"], "when": "hidden"},
    {"key": "welllog-remove", "label": "Remove from this view",
     "types": ["Wellbore"], "when": "shown"},
]
# The menu travels through the STATE channel, never inside the markup: the
# quotes of a list serialized into an HTML attribute would close it.
_CONTEXT_ACTIONS_VAR = "ui_welllog_tree_context_actions"

# trame @state.change handlers cannot be unregistered — remember which view
# ids are wired so reopening the panel doesn't stack duplicate watchers.
_WIRED = set()


class WellLogTree:
    def __init__(self, server, view_id):
        self.server = server
        self.view_id = vid = str(view_id)
        state = server.state
        sel_var = f"welllog_tree_selected__{vid}"
        eye_var = f"welllog_tree_eye__{vid}"
        shown_var = f"welllog_tree_shown__{vid}"
        toggle_var = f"welllog_tree_toggle__{vid}"
        ctx_var = f"welllog_tree_ctx__{vid}"
        layout_var = f"welllog_tree_layout__{vid}"

        # Seeded from what the panel ALREADY draws — the wells AND the
        # curves, frames and trajectory under them, which is what the
        # controller publishes here. Seeding the wells alone would make the
        # first watcher call read as every curve of a full log just unticked,
        # and the panel would empty itself.
        server.controller.welllog_tree_ticks(vid)
        # Opened on the node the gesture that opened it named; else on the
        # node lit in the Well card of the 3D view used last, unfolded to
        act_var = f"welllog_tree_active__{vid}"
        if not getattr(state, act_var, None):
            state[act_var] = well_node_to_open(state)
        # The widget's remaining outputs, sunk PER VIEW: a click in a panel's
        # tree must never reach the session-wide names the data tree uses.
        for name, default in ((eye_var, []), (shown_var, []),
                              (toggle_var, None), (ctx_var, None),
                              (f"welllog_tree_active__{vid}", ""),
                              (f"welllog_tree_active_by_tab__{vid}", {}),
                              (f"welllog_tree_colour__{vid}", None),
                              (layout_var, "flat"),
                              (_CONTEXT_ACTIONS_VAR, _CONTEXT_ACTIONS)):
            if getattr(state, name, None) is None:
                state[name] = default

        DataExplorerTree(
            assembly=("assembly_xml", ""),
            tabs=(_WELL_TAB,),
            # the one grammar (app/scene/panel_trees): the CHECKBOX is the
            # session's load, the same in every tree (`tree_tick` says where
            # it came from); the EYE is "in this panel"
            selected_paths="selected_paths",
            selected_changed=f"tree_tick = {{vid: '{vid}', kind: 'welllog', paths: $event, t: Date.now()}}",
            visible_paths=sel_var,
            eye_toggle=toggle_var,
            active_path=f"welllog_tree_active__{vid}",
            active_by_tab=f"welllog_tree_active_by_tab__{vid}",
            colour_request=f"welllog_tree_colour__{vid}",
            context_actions=(_CONTEXT_ACTIONS_VAR,),
            context_action=ctx_var,
            # by representation or by property kind, as the data tree's
            # Well tab: the rows change place, nothing is unticked
            layout=(layout_var, "flat"),
            layout_change=f"{layout_var} = $event",
            # A right-click on a trajectory, a marker frame or a channel:
            # the menu opens on this one disabled line rather than on
            # nothing — the acts of this panel are the wellbore's.
            context_empty_label="No log action here — this log correlates"
                                " wellbores, so its acts are on a wellbore.",
            # No "Select ▾" here: its "Select all (N)" row ticks every
            # representation of the file through the session's load channel,
            # which puts them in the 3D scene — from a panel that has no
            # business with the scene. The data tree is the one tree whose
            # tick is an assumed scene command, so it keeps the menu.
            bulk_select=False,
        )

        if vid in _WIRED:
            return
        _WIRED.add(vid)

        @state.change(f"welllog_tree_active__{vid}")
        def _on_active(**kwargs):
            path = kwargs.get(f"welllog_tree_active__{vid}") or ""
            # the Values view reads the node made active last, whichever tree it was in
            server.controller.values_focus("welllog", path)
            # and the log view brings its graph to its middle
            server.controller.welllog_focus(vid, path)

        @state.change(toggle_var)
        def _on_eye(**kwargs):
            # An eye click: in this log, or not
            ev = kwargs.get(toggle_var) or {}
            if isinstance(ev, dict) and ev.get("path"):
                server.controller.panel_tree_eye(vid, ev, "welllog")

        @state.change(ctx_var)
        def _on_context(**kwargs):
            ev = kwargs.get(ctx_var) or {}
            if isinstance(ev, dict) and ev.get("action"):
                server.controller.welllog_tree_action(vid, ev)
