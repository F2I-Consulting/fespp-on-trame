from trame_client.widgets.core import AbstractElement

from trame_fespp_tree import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["DataExplorerTree"]


class DataExplorerTree(HtmlElement):
    """Autonomous data-explorer tree over a **vtkDataAssembly**.

    The widget owns its interaction state (selection / visibility / expansion /
    active node / filter / tabs); the host feeds it one assembly and watches a
    few output **state variables** — no per-event callback wiring.

    Inputs (props)::

        assembly        : the vtkDataAssembly serialized to XML
                          (``assembly.SerializeToXML(vtkIndent())``). Per-node
                          data comes from node attributes: ``label`` (title),
                          ``type``, ``eye`` ('rep'|'array'), ``color``,
                          ``crs/dims/count/units/info`` (tooltip). Node identity
                          is its assembly path.
        tabs            : ``[{"name": str, "types": [type, ...]}]`` — each tab
                          shows the nodes whose ``type`` is in ``types`` OR
                          whose ``family`` attribute is the tab's name (with
                          their subtree + ancestors) — the second is how a
                          SYNTHETIC assembly, whose folders have no assembly
                          type, gets the same tabs (the Compare tree's rep
                          folders carry the family of the representation
                          they stand for). Defaults to Reservoir / Surface /
                          Well; pass ``[]`` for a single tree. The bar is
                          drawn only with more than one tab; a tab with
                          nothing in it says so. A tick on a container the
                          tab prunes acts on what the tab shows of it.
        initial_selected : optional path list to seed a session's selection;
                          the widget owns the selection afterwards.
        color_editing   : opt-in (default False) — show the solidColor swatch
                          of a representation.
        eye_paths       : optional state var holding the paths that MAY carry
                          an eye. Omit it and the checkbox is the gate, which
                          is what a tree whose tick means "load" wants; a tree
                          whose tick means something else (the Compare view's
                          means "in the comparison") names the displayable
                          paths here instead.
        kind_icons      : per-type MDI SVG-path overrides.
        select_groups   : bulk-select taxonomy override.
        bulk_select     : opt-out (default True) — show the "Select ▾" menu.
                          Offered in the DATA tree only: its "Select all (N)"
                          row ticks representations through the session's
                          load channel, which is a scene command, and a
                          panel's own tree has no business with the scene.
                          The panels' trees pass False, each saying so.
        context_actions : right-click menu items ``[{"key", "label", "types"?,
                          "when"?, "danger"?, "separatorBefore"?}]``.
                          ``types`` limits an action to those node types;
                          ``when`` limits it to one side of the checkbox
                          ("selected" / "unselected"), which is how a pair
                          of opposite actions (Add to / Remove from this
                          panel) shows only the one that would do
                          something.
        context_empty_label : the ONE disabled line the menu shows on a node
                          no declared action applies to. A right-click is
                          never silent: opening nothing there would read as
                          "this tree has no menu" one row under a node that
                          offers four. Each tree names its own reason.

    Outputs — the widget writes these **trame state variables**; the host reacts
    with ``@state.change(...)``. Pass a different name to rebind, or omit for the
    default. Adding a new output never breaks an existing caller::

        selected_paths  (list)            loaded paths (checkbox)
        eye_toggle      ({path,n})        an eye chip was clicked
        active_path     (str)             active node of the DISPLAYED tab
        active_by_tab   ({tab: path})     active node kept PER TAB (keys =
                                          lower-case tab names); switching
                                          tabs never loses a tab's active
        colour_request  ({path,kind,n})   solidColor swatch / colormap click
        context_action  ({action,path,n}) right-click menu choice

    Visibility is SERVER-OWNED: ``visible_paths`` is an INPUT the host writes
    (born-visible on load, born-hidden rules, and in response to
    ``eye_toggle``); the widget only renders it. It never writes an eye list —
    a client-written full list raced the host's edits and clobbered them.

    Example::

        tree = DataExplorerTree(
            assembly=("assembly_xml",),
            tabs=("tabs_config",),
            color_editing=True,
            context_actions=("ctx_actions",),
            # outputs default to these names; shown for clarity
            selected_paths="selected_paths",
            visible_paths="visible_paths",
            eye_toggle="eye_toggle",
        )

        @state.change("selected_paths")
        def _on_selected(selected_paths, **kw):
            ...   # load these paths

        @state.change("eye_toggle")
        def _on_eye_toggle(eye_toggle, **kw):
            ...   # flip eye_toggle["path"] in visible_paths
    """

    def __init__(
        self,
        selected_paths="selected_paths",
        visible_paths="visible_paths",
        eye_toggle="eye_toggle",
        active_path="active_path",
        active_by_tab="active_by_tab",
        colour_request="colour_request",
        context_action="context_action",
        **kwargs,
    ):
        # Mirror the component's outputs into trame state vars on the client
        # (string handler = client-side state mutation, like ``click="x += 1"``).
        # The host then just watches the vars with @state.change.
        # Selection is CONTROLLED (two-way); visibility is one-way (host ->
        # widget) with eye clicks reported as `eye_toggle` events.
        kwargs.setdefault("selected", (selected_paths,))
        kwargs.setdefault("selected_changed", f"{selected_paths} = $event")
        kwargs.setdefault("visible", (visible_paths,))
        kwargs.setdefault("eye_toggle", f"{eye_toggle} = $event")
        kwargs.setdefault("active_changed", f"{active_path} = $event")
        # controlled active: a host-side activation (render-view pick) is
        # revealed by the tree (tab / expand / highlight / scroll)
        kwargs.setdefault("active", (active_path,))
        kwargs.setdefault("active_by_tab", f"{active_by_tab} = $event")
        kwargs.setdefault("colour_request", f"{colour_request} = $event")
        kwargs.setdefault("context_action", f"{context_action} = $event")
        super().__init__("data-explorer-tree", **kwargs)
        self._attr_names += [
            "assembly", "tabs", "selected", "visible", "active",
            "initial_selected", ("eye_paths", "eyePaths"),
            "color_editing",
            "kind_icons", "select_groups", ("bulk_select", "bulkSelect"),
            "context_actions", ("context_empty_label", "contextEmptyLabel"),
            "layout",
        ]
        self._event_names += [
            "selected_changed", "eye_toggle", "active_changed", "active_by_tab",
            "colour_request", "context_action",
            ("layout_change", "layoutChange"),
        ]
