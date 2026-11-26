"""DataTree — the per-view Data Explorer tree as a self-contained widget.

Contract
--------
Input:     ``server``, ``view_id``, and ``on_visible_change`` — an injected
           callable ``(view_id, visible_paths: list[str]) -> None`` fired on
           every eye edit in THIS view. Because the callback is injected, the
           widget is path-agnostic: the same widget serves the
           per-rep-visibility path and the BlockScope BlockSelectors path
           (``boot.on_eye_changed`` does the branching).
Behaviour: renders the ``DataExplorerTree`` bound to this view's suffixed
           state vars, seeds those vars if absent (idempotent with
           ``per_view_state.seed``), and owns this view's eye set: an eye
           click arrives as ``eye_toggle__<vid>`` {path, n}, is applied
           to ``visible_paths__<vid>`` HERE (server-side, the only
           writer), and forwarded to the injected callback. Selection (load)
           stays session-global; eye / active node / colour request are per
           view.
Reads:     ``assembly_xml`` (the collector's serialized vtkDataAssembly),
           ``selected_paths``, ``visible_paths__<vid>``, ``ui_tree_layout__<vid>``,
           ``active_path__<vid>``, ``eye_toggle__<vid>``.
Writes:    ``selected_paths`` (session load set),
           ``visible_paths__<vid>`` (this view's eye set — server-side),
           ``active_path__<vid>``, ``colour_request__<vid>``,
           ``context_action`` (session-global right-click dispatch),
           ``ui_tree_context_actions`` (the right-click menu, seeded once).
"""
from trame_fespp_tree.widgets.tree import DataExplorerTree

from fespp_on_trame.app.ui import action_icons
from fespp_on_trame.engine import tree_families
from fespp_on_trame.engine.node_kinds import ISOLATABLE_KINDS, LOG_FRAMES, PROPERTY_KINDS


# A right-click offers what the node clicked can actually do: the widget
# hides an action whose `types` do not list the node's type.
# Statistics and a formula input read VALUES — only a property leaf has any
# (`PROPERTY_KINDS`); on a folder, a grid, a well or a feature they would open
# a panel with no row. The
# controllers guard the same rule for the doors that do not come through
# this menu (`node_facts.is_property`).
#
# Highlighting selects a whole block, so it is offered wherever a click
# resolves to a representation: the reps themselves, the leaves that ride on
# one (a property colours it, a marker sits on its frame) and the grid's
# container, which stands for the grid. A pure grouping folder — a wellbore, a
# feature, an interpretation, a collection — has no rep under it; a layout
# folder (properties, SubRep, logs...) is not in the file, its row has no
# menu at all (the PO's users, 28/10: the tree widget's FOLDER_TYPES).
# Kinds an assembly may spell differently are all listed (the tree widget's
# own REP_KINDS carries the same aliases).
_REP_TYPES = ("IjkGrid", "UnstructuredGrid", "ExplicitStructuredGrid",
              "Sub", "SubRepresentation", "Grid2d", "Grid2dRepresentation",
              "TriangulatedSet", "Polyline", "PolylineSet", "PointSet",
              "BlockedWellbore", "Trajectory", "WellboreTrajectory",
              "Completion", "Perfo", "Perforation", "Frame",
              "SeismicWellboreFrame", "MarkerFrame", "GridContainer")
_HIGHLIGHT_TYPES = _REP_TYPES + PROPERTY_KINDS + ("Marker", "WellboreMarker")

# "Add to Well Log view" sends a WELLBORE to the correlation view with the
# logs of the node clicked (app/features/view_doors.add_to_welllog) — every
# log of a frame, read first; "Add selected to Well Log view" on a frame,
# those read already —, so the entry is offered on the folder itself and on
# every node kind that only ever sits under one. A log channel is a property
# leaf whose type a grid property shares: its entry goes by the rows of the
# log frames (`context_actions`).
_WELL_TYPES = ("Wellbore", "Trajectory", "WellboreTrajectory", "MarkerFrame",
               "Marker", "WellboreMarker",
               "Completion", "Perfo", "Perforation")

_CONTEXT_ACTIONS = [
    # Every entry but Info and a log frame's "Add to Well Log view" (it reads
    # every log of its own) asks for something LOADED (`when: loaded`, the row
    # or a row under it ticked): an unread row has nothing to select, show,
    # send to a well log or count. A whole property not read yet offers them
    # all the same: the entry reads it first, as its box would
    # (app/features/panels).
    # {title} is the row's name
    # where is it? the active 3D view turns to it, or comes closer too (the
    # PO, 20/10: a surface among many others could not be found); a
    # wellbore folder takes in all it holds
    {"key": "center-3d", "label": "Center the 3D view on {title}",
     "types": list(_HIGHLIGHT_TYPES) + ["Wellbore"], "when": "loaded"},
    {"key": "zoom-3d", "label": "Zoom the 3D view on {title}",
     "types": list(_HIGHLIGHT_TYPES) + ["Wellbore"], "when": "loaded"},
    {"key": "add-to-welllog", "label": "Add to Well Log view",
     "types": list(_WELL_TYPES), "when": "loaded"},
    # a log frame reads every log of its own: offered on it loaded or not
    {"key": "add-to-welllog", "label": "Add to Well Log view",
     "types": list(LOG_FRAMES)},
    {"key": "add-selected-to-welllog", "label": "Add selected to Well Log view",
     "types": list(LOG_FRAMES), "when": "loaded"},
    {"key": "calculator", "label": "Derived property",
     "types": list(PROPERTY_KINDS), "when": "loaded"},
    # the slicer cards of the active 3D view, on this object (the PO's
    # manager, 28/10; app/features/slicer_doors): a grid's container is the
    # grid, a property its object
    {"key": "geometry-slicer", "label": "Geometry slicer",
     "types": list(ISOLATABLE_KINDS) + ["GridContainer"], "when": "loaded"},
    {"key": "property-slicer", "label": "Property slicer",
     "types": list(ISOLATABLE_KINDS) + ["GridContainer"] + list(PROPERTY_KINDS),
     "when": "loaded"},
    # a grid read as the velocity model (the PO, 03/11: a velocity
    # model saved as RESQML, loaded again and edited on): its extent, its
    # cells, its layers, the velocities of this property, or of its
    # "velocity" one (app/features/time_depth_law). On the IJK grids whose
    # geometry is a lattice alone (`rows`: their containers, published as
    # `ui_cube_grid_rows` by the feature), what is under them included
    {"key": "use-as-cube", "label": "Use as velocity model",
     "types": ["GridContainer", "IjkGrid"] + list(PROPERTY_KINDS), "when": "loaded", "rows": []},
    # the velocity model's grid (app/features/time_depth_tree): its .epc and
    # its .h5 downloaded by the browser (`download`, the session's /export
    # route) — on that row and what is under it alone
    {"key": "save-epc", "label": "Save as EPC",
     "types": ["GridContainer", "IjkGrid"] + list(PROPERTY_KINDS), "rows": [], "download": []},
    # the property in the Statistics view (its distribution and cross-plot
    # are there, under its row)
    {"key": "add-to-stats", "label": "Stats",
     "types": list(PROPERTY_KINDS), "when": "loaded"},
    # every row: the object behind it in the XML explorer — a row with no
    # object of its own opens the explorer on a note saying so
    {"key": "xml", "label": "Info"},
]
# each entry with the icon the 3D view's menu shows for the same action, in
# the order of that menu
_CONTEXT_ACTIONS = action_icons.ordered(
    [{**a, "icon": action_icons.icon_of(a["key"])} for a in _CONTEXT_ACTIONS])


def context_actions(cube_rows, model=None, extras=None, log_frames=None):
    """The menu's entries: "Use as velocity model" on `cube_rows` (the
    lattice grids' containers) and what is under them — but the active
    model's own row, which is it already —, "Save as EPC" on a generated
    model's grid, one entry per model (`model`:
    app/features/time_depth_tree's ``ui_cube_tree``, {row, download, parked}),
    "Add to Well Log view" on the logs under `log_frames` too (the log
    frames' rows, ``ui_log_frame_rows``: a log's type is a grid property's,
    the type alone cannot offer it), and the entries features add (`extras`,
    ``ui_tree_extra_actions``), each with its icon, in the menu's order."""
    model = model or {}
    versions = [v for v in [model, *(model.get("parked") or ())] if v.get("row")]
    out = []
    for a in _CONTEXT_ACTIONS:
        if a["key"] == "use-as-cube":
            out.append(dict(a, rows=[r for r in (cube_rows or []) if r != model.get("row")]))
        elif a["key"] == "save-epc":
            out += ([dict(a, rows=[v["row"]], download=list(v.get("download") or [])) for v in versions]
                    or [dict(a, rows=[], download=[])])
        elif a["key"] == "add-to-welllog" and a.get("when"):
            out += [a, dict(a, types=list(PROPERTY_KINDS), rows=list(log_frames or []))]
        else:
            out.append(a)
    if extras:
        out = action_icons.ordered(out + [{**a, "icon": action_icons.icon_of(a["key"])} for a in extras])
    return out


_ROWS_WIRED = set()
# The menu travels to the widget through the STATE channel, never inside the
# markup: trame writes a literal prop value into a double-quoted HTML
# attribute as it is, so the quotes of a serialized list would close that
# attribute and the tree's template would no longer compile.
_CONTEXT_ACTIONS_VAR = "ui_tree_context_actions"
# the entries a feature adds to the menu ({key, label, types, rows…}), its
# dispatch in `ctx.context_actions_extra` (app/features/panels)
_EXTRA_ACTIONS_VAR = "ui_tree_extra_actions"
# the colour chips a feature adds to its rows ({path: "#rrggbb"}), beside
# the representations' own
_EXTRA_CHIPS_VAR = "ui_tree_extra_chips"

# trame @state.change handlers cannot be unregistered — remember which view ids
# already have an eye watcher so a rebuilt DataTree doesn't stack duplicates.
_EYE_WIRED = set()

# The trees' colour chips: {path: "#rrggbb"} of every loaded representation's
# solid colour (`solid_color_by_rep`, "#rrggbbaa", assigned at load), its grid
# folder wearing its geometry's — one session-wide variable, watched once.
_CHIPS_VAR = "ui_tree_solid_colors"
_CHIPS_WIRED = set()


def chip_colours(solid_by_rep, loaded=None):
    """{tree path: "#rrggbb"} of `solid_by_rep` ({rep path: "#rrggbbaa"}),
    only the representations in `loaded` when given (a colour stays
    reserved for an unloaded one, so that it comes back the same): a grid's
    geometry leaf lends its colour to its grid folder, the row the reader
    knows the grid by (the part before "/_propsfolder_")."""
    out = {}
    keep = set(loaded) if loaded is not None else None
    for rp, col in (solid_by_rep or {}).items():
        col = str(col or "")
        if not rp or not col.startswith("#") or len(col) < 7:
            continue
        if keep is not None and rp not in keep:
            continue
        out[rp] = col[:7]
        if "/_propsfolder_" in rp:
            out.setdefault(rp.split("/_propsfolder_", 1)[0], col[:7])
    return out


class DataTree:
    def __init__(self, server, view_id, on_visible_change=None, family=None):
        """`family`: the card key of the family this tree shows alone
        (engine/tree_families); None, every family."""
        self.server = server
        self.view_id = vid = str(view_id)
        vis_var = f"visible_paths__{vid}"
        toggle_var = f"eye_toggle__{vid}"
        state = server.state
        # self-seed (per_view_state.seed re-affirms right after wiring)
        for name, default in ((vis_var, []), (f"active_path__{vid}", ""),
                              (f"active_by_tab__{vid}", {}),
                              (toggle_var, None),
                              (f"ui_tree_layout__{vid}", "flat"),
                              ("ui_cube_grid_rows", []),
                              ("ui_log_frame_rows", []),
                              (_EXTRA_ACTIONS_VAR, []),
                              (_EXTRA_CHIPS_VAR, {}),
                              (_CONTEXT_ACTIONS_VAR,
                               context_actions(getattr(state, "ui_cube_grid_rows", None),
                                               getattr(state, "ui_cube_tree", None),
                                               getattr(state, _EXTRA_ACTIONS_VAR, None),
                                               getattr(state, "ui_log_frame_rows", None)))):
            if getattr(state, name, None) is None:
                state[name] = default
        # the lattice grids change with the data: the menu's entry follows
        on_change = getattr(state, "change", None)
        if callable(on_change) and id(state) not in _ROWS_WIRED:
            _ROWS_WIRED.add(id(state))

            @on_change("ui_cube_grid_rows", "ui_cube_tree", _EXTRA_ACTIONS_VAR, "ui_log_frame_rows")
            def _on_cube_rows(**_):
                state[_CONTEXT_ACTIONS_VAR] = context_actions(state.ui_cube_grid_rows, state.ui_cube_tree,
                                                              state[_EXTRA_ACTIONS_VAR], state.ui_log_frame_rows)

        DataExplorerTree(
            assembly=("assembly_xml", ""),
            **({"tabs": (repr(tree_families.tab_of(family)),)} if family else {}),
            color_editing=True,
            selected_paths="selected_paths",
            # one event per tick, saying which view it came from: an untick
            # that unloads what ANOTHER view uses asks first (the one
            # grammar, app/scene/panel_trees)
            selected_changed=f"tree_tick = {{vid: '{vid}', kind: 'render', paths: $event, t: Date.now()}}",
            visible_paths=vis_var,
            converted=(f"converted_paths__{vid} || []",),
            undrawn=(f"undrawn_paths__{vid} || []",),
            fixed=(f"fixed_paths__{vid} || []",),
            domain_toggle=(server.controller.view_domain_object, f"[$event.path, '{vid}']"),
            eye_toggle=toggle_var,
            active_path=f"active_path__{vid}",
            # the active row clicked: the Values card leaves the folder it
            # was reading (another row: the active node moving does it); a
            # family card's row still lit while another card's node is the
            # view's: it is the view's again
            active_again=f"values_folder__{vid} = []; active_path__{vid} = $event",
            # per-tab actives: the grid-scoped tools (slicers / thresholds)
            # follow the RESERVOIR tab's active grid whatever tab is shown
            active_by_tab=f"active_by_tab__{vid}",
            colour_request=f"colour_request__{vid}",
            context_actions=(_CONTEXT_ACTIONS_VAR,),
            context_action="context_action",
            # a folder, a feature, an interpretation: the menu opens on this
            # one disabled line rather than on nothing, so the reader who
            # learned the gesture on a property is told why it gives nothing
            # here instead of meeting silence
            context_empty_label="No action on this node — the acts here are"
                                " on a property, a representation or a"
                                " wellbore.",
            # this view's reading of the forest, drawn by the widget on the same paths
            layout=(f"ui_tree_layout__{vid}", "flat"),
            layout_change=(server.controller.tree_layout_set, f"[$event, '{vid}']"),
            # a node opened: what it holds is read from the store now if a
            # lazy ETP load left it there (boot.tree_node_open)
            node_open=(server.controller.tree_node_open, "[$event]"),
            # the session's own rows (selection extracts, derived
            # properties) and the "+" of a grid with highlighted cells
            # (boot.selection_extract / session_row_eye / session_row_remove)
            session_rows=(f"ui_session_rows__{vid} || []",),
            solid_colors=(f"Object.assign({{}}, {_CHIPS_VAR} || {{}}, {_EXTRA_CHIPS_VAR} || {{}})",),
            selection_counts=(f"ui_sel_counts__{vid} || {{}}",),
            # the lattice grids, the generated velocity models among them
            # (app/features/time_depth_models): their drawing, and their
            # family — the Seismic tab takes them, the Reservoir one leaves them
            lattice_rows=("ui_cube_grid_rows || []",),
            active_model=("ui_active_model_row || ''",),
            extract=(server.controller.selection_extract, f"[$event, '{vid}']"),
            session_eye=(server.controller.session_row_eye, f"[$event, '{vid}']"),
            session_remove=(server.controller.session_row_remove, f"[$event, '{vid}']"),
            session_rename=(server.controller.session_row_rename, f"[$event, '{vid}']"),
        )

        # watched by the 3D view's own tree (the one given an eye handler)
        if on_visible_change is not None and id(state) not in _CHIPS_WIRED:
            _CHIPS_WIRED.add(id(state))
            state[_CHIPS_VAR] = chip_colours(getattr(state, "solid_color_by_rep", None),
                                             getattr(state, "ui_loaded_rep_paths", None) or [])

            @state.change("solid_color_by_rep", "ui_loaded_rep_paths")
            def _on_solid_colours(**_):
                state[_CHIPS_VAR] = chip_colours(state.solid_color_by_rep,
                                                 state.ui_loaded_rep_paths or [])

        if on_visible_change is not None and vid not in _EYE_WIRED:
            _EYE_WIRED.add(vid)

            @state.change(toggle_var)
            def _on_eye_toggle(**kwargs):
                # The ONLY client-originated eye edit: flip one path in the
                # server-owned eye set. It does NOT dispatch — writing
                # `vis_var` is enough, because trame's flush loops over the
                # keys a handler dirties (`while self._pending_update`) and so
                # re-fires `_on_eye` within the same flush. Dispatching here
                # too would run the whole eye handler twice per click.
                ev = kwargs.get(toggle_var) or {}
                path = ev.get("path") if isinstance(ev, dict) else None
                if not path:
                    return
                cur = list(getattr(state, vis_var, None) or [])
                # A FOLDER eye arrives with the leaves it drives and the state
                # to put them in — one edit, one dispatch, whatever the size
                # of the subtree.
                paths = ev.get("paths") if isinstance(ev, dict) else None
                opens = ev.get("visible") if paths else path not in cur
                folder = bool(paths)
                paths = list(paths) if paths else [path]
                rest = [p for p in cur if p not in set(paths)]
                if folder and not opens:
                    # a folder's eye closed closes every row under it: the
                    # widget sends the deepest eyes, and a row whose eye holds
                    # others (a marker set) draws them all while it stays open
                    under = path.rstrip("/") + "/"
                    rest = [p for p in rest if p != path and not p.startswith(under)]
                state[vis_var] = rest + paths if opens else rest
                # the Statistics view's eyes, on the same objects (compare_tree)
                follow = getattr(server.context, "stats_follow_eyes", None)
                if follow is not None:
                    follow(paths if opens else (), () if opens else paths)

            @state.change(vis_var)
            def _on_eye(**kwargs):
                # The single dispatch point: whoever writes the eye set —
                # the toggle above, or a server-side born-visible / -hidden
                # write — reaches the scene through here.
                on_visible_change(vid, list(kwargs.get(vis_var) or []))
