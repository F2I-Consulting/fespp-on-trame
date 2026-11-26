"""ReconcileTree — the Log ↔ Grid panel's own tree, docked inside the panel.

Contract
--------
Input:     ``server`` and ``view_id``.
Behaviour: renders a ``DataExplorerTree`` showing one family, Reservoir or
           Well (``family``; both under their tabs without it), one card of
           the panel each, under the one grammar every tree of the
           application follows (``engine/tree_grammar``):

           * the CHECKBOX is the session's load, common to every view:
             ticked here = read, born hidden in the 3D views, and put in this
             table; unticked = unloaded from the session, after a
             confirmation when another view uses it.
           * the EYE is "in this table": a log channel (Well) or a grid
             property (Reservoir) — a wellbore, a frame, a grid or a
             folder stands for every channel or grid property under it.

           The table has two doors: this tree, and the log view's wells
           ("Add to Well Log view"); the two merge (``reconcile_dispatch.
           session_inputs``), so this tree shows ticked whatever the table
           reads, whichever door it came through.
Reads:     ``assembly_xml``, ``reconcile_tree_eye__<vid>`` /
           ``reconcile_tree_shown__<vid>`` (server-written).
Writes:    ``reconcile_tree_selected__<vid>`` (two-way: the reader ticks,
           the server rewrites it — and seeds it through
           ``controller.reconcile_tree_ticks`` — from what the table holds)
           and, through ``controller.reconcile_tree_paths``, that set;
           ``controller.panel_tree_eye`` for an eye;
           ``controller.reconcile_tree_action`` for the right-click menu.
"""
from trame_fespp_tree.widgets.tree import DataExplorerTree

from fespp_on_trame.engine import tree_families
from fespp_on_trame.engine.node_kinds import PROPERTY_KINDS

# In or out of this table on what it holds — a channel, a grid property, a
# wellbore (every channel under it) — and the one act that leaves it.
_HOLDABLE = list(PROPERTY_KINDS) + ["Wellbore"]
_CONTEXT_ACTIONS = [
    {"key": "reconcile-add", "label": "Add to this table",
     "types": _HOLDABLE, "when": "hidden"},
    {"key": "reconcile-remove", "label": "Remove from this table",
     "types": _HOLDABLE, "when": "shown"},
]
# The menu travels through the STATE channel, never inside the markup: the
# quotes of a list serialized into an HTML attribute would close it.
_CONTEXT_ACTIONS_VAR = "ui_reconcile_tree_context_actions"

# trame @state.change handlers cannot be unregistered — remember which view
# ids are wired so reopening the panel doesn't stack duplicate watchers.
_WIRED = set()


class ReconcileTree:
    def __init__(self, server, view_id, family=None):
        self.server = server
        self.view_id = vid = str(view_id)
        state = server.state
        sel_var = f"reconcile_tree_selected__{vid}"
        eye_var = f"reconcile_tree_eye__{vid}"
        shown_var = f"reconcile_tree_shown__{vid}"
        toggle_var = f"reconcile_tree_toggle__{vid}"
        ctx_var = f"reconcile_tree_ctx__{vid}"

        # Seeded from what the table ALREADY holds, so the first watcher call
        # is not read as a reader who just unticked all of it.
        server.controller.reconcile_tree_ticks(vid)
        # The widget's remaining outputs, sunk PER VIEW: a click in a panel's
        # tree must never reach the session-wide names the data tree uses.
        for name, default in ((eye_var, []), (shown_var, []),
                              (toggle_var, None), (ctx_var, None),
                              (f"reconcile_tree_active__{vid}", ""),
                              (f"reconcile_tree_active_by_tab__{vid}", {}),
                              (f"reconcile_tree_colour__{vid}", None),
                              (_CONTEXT_ACTIONS_VAR, _CONTEXT_ACTIONS)):
            if getattr(state, name, None) is None:
                state[name] = default

        DataExplorerTree(
            assembly=("assembly_xml", ""),
            tabs=(repr(tree_families.tab_named(family) if family
                       else [t for name in tree_families.LOG_GRID for t in tree_families.tab_named(name)]),),
            # the one grammar (app/scene/panel_trees): the CHECKBOX is the
            # session's load, the same in every tree (`tree_tick` says where
            # it came from); the EYE is "in this panel"
            selected_paths="selected_paths",
            selected_changed=f"tree_tick = {{vid: '{vid}', kind: 'reconcile', paths: $event, t: Date.now()}}",
            visible_paths=sel_var,
            eye_toggle=toggle_var,
            active_path=f"reconcile_tree_active__{vid}",
            active_by_tab=f"reconcile_tree_active_by_tab__{vid}",
            colour_request=f"reconcile_tree_colour__{vid}",
            context_actions=(_CONTEXT_ACTIONS_VAR,),
            context_action=ctx_var,
            context_empty_label="No table action here — this table sets log"
                                " channels against grid properties.",
            # No "Select ▾": its "Select all (N)" row ticks every
            # representation of the file through the session's load channel,
            # which puts them in the 3D scene — from a panel that has no
            # business with the scene.
            bulk_select=False,
        )

        if vid in _WIRED:
            return
        _WIRED.add(vid)

        @state.change(f"reconcile_tree_active__{vid}")
        def _on_active(**kwargs):
            # the Values view reads the node made active last, whichever tree it was in
            server.controller.values_focus("reconcile", kwargs.get(f"reconcile_tree_active__{vid}") or "")

        @state.change(toggle_var)
        def _on_eye(**kwargs):
            # an eye click: in this table, or not
            ev = kwargs.get(toggle_var) or {}
            if isinstance(ev, dict) and ev.get("path"):
                server.controller.panel_tree_eye(vid, ev, "reconcile")

        @state.change(ctx_var)
        def _on_context(**kwargs):
            ev = kwargs.get(ctx_var) or {}
            if isinstance(ev, dict) and ev.get("action"):
                server.controller.reconcile_tree_action(vid, ev)
