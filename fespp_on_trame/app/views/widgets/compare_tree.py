"""CompareTree — the Statistics view's own selection tree, docked inside the
panel.

Contract
--------
Input:     ``server`` and ``view_id``.
Behaviour: renders a ``DataExplorerTree`` over the SYNTHETIC assembly boot
           builds from every property the file holds (kind ->
           representation -> property, ``ui_compare_tree_xml``), then, in a
           folder of their own, the parts of its grids: sub-representations
           and blocked wellbores as leaves (``ComparePart``), the 3D views'
           selection extracts as rows of the session
           (``ui_compare_session_rows``, each with its own eye:
           ``controller.compare_session_eye``). One tree per family card of
           the view (``family``: Reservoir, Surface, Well, or ``Other`` while
           the file has a rep outside the three): each rep folder carries the
           ``family`` the data tree would file it under, and the tree keeps
           the nodes whose family is its own — a kind folder shows in every
           card one of its reps belongs to, and ticking it there ticks only
           what that card shows; without ``family``, every family under the
           tabs ``ui_compare_tree_tabs``.
           The one grammar (``engine/tree_grammar``): a CHECKBOX is the
           session's load, common to every view; what a tick here reads
           comes born HIDDEN, in this panel and in no 3D view. A folder stands
           for its whole subtree; when that means reading more properties
           than one click can show, boot asks first and reads nothing until
           the answer. The EYE is "in this panel", offered on what is ticked:
           on a property, every property of its kind the session holds and no
           other kind; on a part, its rows under the items of its grid, all
           the rest staying.
           Laid out by kind by default (``ui_compare_tree_layout``), or by
           interpretation or feature, drawn by the widget as in a data tree.
           ``bulk_select=False``: the widget's "Select ▾" menu opens on a
           "Select all (N)" row, and a tick that loads must never stand for
           the whole file at once.
Reads:     ``ui_compare_tree_xml``, ``ui_compare_tree_tabs``,
           ``ui_compare_session_rows``, ``compare_tree_loaded__<vid>`` (the
           boxes, server-written: what the session reads),
           ``compare_tree_eyeable__<vid>`` (what may carry an eye: that, and
           the formulas, which have no box),
           ``compare_tree_selected__<vid>`` (the eyes, server-written).
Writes:    through ``compare_tick`` the session's load, and through
           ``controller.compare_tree_eye`` what the panel holds /
           ``controller.compare_session_eye`` an extract's rows /
           ``controller.compare_tree_action`` the right-click menu.
"""
from trame_fespp_tree.widgets.tree import DataExplorerTree

_LEAVES = ["CompareItem", "ComparePart"]
# What a right-click offers HERE: what the eye (in the panel or not) and the
# charts under the matrix do not already give. Reading what the file says about
# an object needs nothing held.
_CONTEXT_ACTIONS = [
    {"key": "compare-baseline", "label": "Set as baseline",
     "types": ["CompareItem"], "when": "shown"},
    {"key": "compare-health", "label": "Show in Data health",
     "types": _LEAVES, "separatorBefore": True},
]
# The menu travels through the STATE channel, never inside the markup: the
# quotes of a list serialized into an HTML attribute would close it.
_CONTEXT_ACTIONS_VAR = "ui_compare_tree_context_actions"

# trame @state.change handlers cannot be unregistered — remember which view
# ids are wired so reopening the panel doesn't stack duplicate watchers.
_WIRED = set()


class CompareTree:
    def __init__(self, server, view_id, family=None):
        self.server = server
        self.view_id = vid = str(view_id)
        state = server.state
        selected_var = f"compare_tree_selected__{vid}"
        # the one grammar: the checkbox shows the session's load, in this
        # tree's synthetic paths (server-written); the eye, what is compared
        loaded_var = f"compare_tree_loaded__{vid}"
        eyeable_var = f"compare_tree_eyeable__{vid}"
        eye_var = f"compare_tree_eye__{vid}"
        toggle_var = f"compare_tree_toggle__{vid}"
        # what the 3D views are showing, and what they COULD show — both
        # written by boot in the tree's synthetic paths
        shown_var = f"compare_tree_shown__{vid}"
        # the widget's remaining outputs, named PER VIEW: the session-wide
        # tree vars (active node, colour request, context action) must never
        # see a click made in a tree that is not the data tree. The context
        # one is read here (the menu below); the others are sinks.
        dummies = {
            eye_var: [],
            shown_var: [],
            toggle_var: None,
            f"compare_tree_active__{vid}": "",
            f"compare_tree_active_by_tab__{vid}": {},
            f"compare_tree_colour__{vid}": None,
            f"compare_tree_ctx__{vid}": None,
            _CONTEXT_ACTIONS_VAR: _CONTEXT_ACTIONS,
        }
        for var in (selected_var, loaded_var, eyeable_var):
            if getattr(state, var, None) is None:
                state[var] = []
        for name, default in dummies.items():
            if getattr(state, name, None) is None:
                state[name] = default

        DataExplorerTree(
            assembly=("ui_compare_tree_xml", ""),
            tabs=((repr([{"name": family, "types": []}]),) if family else ("ui_compare_tree_tabs",)),
            selected_paths=loaded_var,
            selected_changed=f"compare_tick = {{vid: '{vid}', paths: $event, t: Date.now()}}",
            visible_paths=selected_var,
            eye_paths=(eyeable_var,),
            eye_toggle=toggle_var,
            active_path=f"compare_tree_active__{vid}",
            active_by_tab=f"compare_tree_active_by_tab__{vid}",
            colour_request=f"compare_tree_colour__{vid}",
            context_actions=(_CONTEXT_ACTIONS_VAR,),
            context_action=f"compare_tree_ctx__{vid}",
            # a kind folder or a representation: the menu opens on this one
            # disabled line rather than on nothing, so the gesture is never
            # silent where it works one row below
            context_empty_label="No statistics action here — a statistic is"
                                " computed on a property.",
            select_groups=("[]",),
            bulk_select=False,
            layout=("ui_compare_tree_layout", "kind"),
            kind_built=True,
            layout_change=(server.controller.compare_tree_layout, "[$event]"),
            # every 3D view's extracts: an extract's eye adds its rows, deleting
            # it is its view's business (app/features/compare_parts)
            session_rows=("ui_compare_session_rows || []",),
            session_eye=(server.controller.compare_session_eye, f"[$event, '{vid}']"),
        )

        if vid in _WIRED:
            return
        _WIRED.add(vid)

        @state.change(f"compare_tree_active__{vid}")
        def _on_active(**kwargs):
            # the Values view reads the node made active last, whichever tree it was in
            server.controller.values_focus("compare", kwargs.get(f"compare_tree_active__{vid}") or "")

        @state.change(toggle_var)
        def _on_eye(**kwargs):
            # An eye click: in this panel, or not
            ev = kwargs.get(toggle_var) or {}
            if isinstance(ev, dict) and ev.get("path"):
                server.controller.compare_tree_eye(vid, ev)

        @state.change(f"compare_tree_ctx__{vid}")
        def _on_context(**kwargs):
            ev = kwargs.get(f"compare_tree_ctx__{vid}") or {}
            if isinstance(ev, dict) and ev.get("action"):
                server.controller.compare_tree_action(vid, ev)
