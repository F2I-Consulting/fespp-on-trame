from trame_client.widgets.core import AbstractElement

from trame_fespp_tree import module


class HtmlElement(AbstractElement):
    """Base element that enables this package's Vue module on its server."""

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
                          data comes from node attributes: ``title`` (or
                          ``label``), ``type``, ``eye`` ('rep'|'array'|'marker',
                          derived from ``type`` when absent), ``color``,
                          ``crs/dims/count/units/info`` (tooltip), ``sortLast``
                          (after its siblings), ``noCheck`` (a folder with no box
                          nor menu). Node identity is its assembly path.
        tabs            : ``[{"name": str, "types": [type, ...]}]`` — each tab
                          shows the nodes whose ``type`` is in ``types`` OR
                          whose ``family`` attribute is the tab's name (with
                          their subtree + ancestors) — the second is how a
                          SYNTHETIC assembly, whose folders have no assembly
                          type, gets the same tabs (the Statistics tree's rep
                          folders carry the family of the representation
                          they stand for). A tab may add ``"lattice"``:
                          the rows of ``lattice_rows`` (the lattice IJK
                          grids, typed as any IJK grid) go to the tab that
                          says ``"take"`` with what they hold, and leave the
                          one that says ``"leave"`` (words, not booleans: the
                          list travels as a Python repr the browser reads as
                          JavaScript). Defaults to Reservoir / Surface /
                          Well / Seismic; pass ``[]`` for a single tree. The bar is
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
                          whose tick means something else names the displayable
                          paths here instead.
        kind_icons      : per-type icon overrides (SVG path strings).
        select_groups   : bulk-select taxonomy override.
        bulk_select     : opt-out (default True) — show the "Select ▾" menu.
                          Offered in the DATA tree only: its "Select all (N)"
                          row ticks representations through the session's
                          load channel, which is a scene command, and a
                          panel's own tree has no business with the scene.
                          Panel trees pass False.
        layout          : the forest layout in force ("flat",
                          "by_interpretation", "by_feature_and_interpretation");
                          omit it for no layout control. A pick fires the
                          ``layout_change`` event with the new value; the host
                          applies it and writes the value back.
        context_actions : right-click menu items ``[{"key", "label", "types"?,
                          "when"?, "danger"?, "separatorBefore"?}]``.
                          ``types`` limits an action to those node types;
                          ``when`` limits it to one side of the checkbox
                          ("selected" / "unselected"; "loaded": the row
                          or a row under it ticked), which is how a pair
                          of opposite actions (Add to / Remove from this
                          panel) shows only the one that would do
                          something. ``{title}`` in a label is the row's name.
        context_empty_label : the ONE disabled line the menu shows on a node
                          no declared action applies to. A right-click is
                          never silent: opening nothing would not tell a
                          node with no action from a tree with no menu.
                          Each tree names its own reason.

    Outputs — the widget writes these **trame state variables**; the host reacts
    with ``@state.change(...)``. Pass a different name to rebind, or omit for the
    default. Adding a new output never breaks an existing caller::

        selected_paths  (list)            loaded paths (checkbox); two-way —
                                          the host may write it too
        eye_toggle      ({path,n})        an eye chip was clicked; a folder
                                          eye adds ``paths`` (the leaves it
                                          drives) and ``visible`` (their new
                                          state)
        active_path     (str)             active node of the DISPLAYED tab;
                                          two-way — a host write reveals it
        active_by_tab   ({tab: path})     active node kept PER TAB (keys =
                                          lower-case tab names); switching
                                          tabs never loses a tab's active node
        colour_request  ({path,kind,n})   solidColor swatch / colormap click
        context_action  ({action,path,n}) right-click menu choice
        node_open       (path)            a node the user expanded

    ``n`` is a counter: a repeated click is still a new value, so
    ``@state.change`` fires every time.

    Visibility is SERVER-OWNED: ``visible_paths`` is an INPUT the host writes
    (born-visible on load, born-hidden rules, and in response to
    ``eye_toggle``); the widget only renders it. It never writes an eye list —
    a client-written full list would race the host's edits and overwrite them.

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
        # the server's "read the selection again" (the one grammar: it owns
        # the boxes, a refused tick leaves the list unchanged)
        kwargs.setdefault("boxes_nonce", ("tree_boxes_n", 0))
        # the velocity model's earlier versions: in no tree
        kwargs.setdefault("hidden_rows", ("ui_hidden_tree_rows || []",))
        kwargs.setdefault("visible", (visible_paths,))
        kwargs.setdefault("eye_toggle", f"{eye_toggle} = $event")
        kwargs.setdefault("active_changed", f"{active_path} = $event")
        # controlled active: a host-side activation (render-view pick) is
        # revealed by the tree (tab / expand / highlight / scroll)
        kwargs.setdefault("active", (active_path,))
        # each tree of a view (a family's card) says its own tabs': merged,
        # never one family's memory wiped by another's
        kwargs.setdefault("active_by_tab", f"{active_by_tab} = Object.assign({{}}, {active_by_tab}, $event)")
        kwargs.setdefault("colour_request", f"{colour_request} = $event")
        kwargs.setdefault("context_action", f"{context_action} = $event")
        super().__init__("data-explorer-tree", **kwargs)
        self._attr_names += [
            "assembly", "tabs", "selected", ("boxes_nonce", "boxesNonce"), "visible", "active",
            "converted", "undrawn", "fixed", "replaced",
            "initial_selected", ("eye_paths", "eyePaths"),
            "color_editing",
            "kind_icons", "select_groups", ("bulk_select", "bulkSelect"),
            "context_actions", ("context_empty_label", "contextEmptyLabel"),
            "layout",
            # the rows the session adds, and the rows offering "+" (the PO,
            # 15/10: keep / remove a highlighted selection)
            ("session_rows", "sessionRows"), ("selection_counts", "selectionCounts"),
            # {path: "#rrggbb…"}: a loaded representation's solid colour, its chip
            ("solid_colors", "solidColors"),
            # the rows of the lattice grids: they wear their own drawing
            ("lattice_rows", "latticeRows"),
            # the row of the velocity model in use: its title says so
            ("active_model", "activeModel"),
            # rows the tree does not show, nor what is under them
            ("hidden_rows", "hiddenRows"),
        ]
        self._event_names += [
            "selected_changed", "eye_toggle", "active_changed", "active_by_tab", ("active_again", "active-again"),
            "colour_request", "context_action",
            ("layout_change", "layoutChange"),
            # a node the user opened (its path): what it holds may be read now
            "node_open",
            # "+" of a highlighted grid: {path, mode}; the eye and the x of a
            # session row: {path}
            "extract", ("session_eye", "session-eye"), ("session_remove", "session-remove"),
            # the pencil of an extract's row: {path, title}
            ("session_rename", "session-rename"),
            ("domain_toggle", "domain-toggle"),
        ]
