"""What the cards and panels say about a tree node: its title on
screen, its rep, its blocks and their columns, the note when it
cannot be read, the arrays a card lists, the grid a card targets, the
active array's label; and `_say`, the one-line message to the reader.

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine.tree import _GRID_GEOMETRY_KINDS
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine.node_kinds import is_ijk_grid
from fespp_on_trame.engine import repo_query
from fespp_on_trame.engine import row_object
from fespp_on_trame.engine import source_resolver

#: the active node's errors when its block, or its array, is not read: the Values view offers to read it
NOT_READ = "Block not loaded."
ARRAY_NOT_READ = "Array not loaded (check it / open its eye)."


def register(core, *, _derived_array_name, _is_property_path, _real_idx_for):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_block_column, _blocks_for_rep, _display_title, _geometry_columns, _node_blocks, _node_title, _property_label, _property_or_note, _push_active_array_label, _push_card_arrays, _push_grid_targets, _rep_path_of, _say, _set_tool_target, _ticked_arrays, _cell_points)."""
    # the shared services (app/core/context.Core)
    state = core.state
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    notifier = core.notifier
    eyes = core.eyes
    activation = core.activation
    def _display_title(path, fallback=""):
        """The name to SHOW for a node: a grid's geometry leaf by its grid
        folder (engine/node_facts.display_title)."""
        return node_facts.display_title(tree, path, fallback)

    def _property_label(path):
        """THE name of a property on screen — the colour bar, the Colormap
        card, a card's title bar: property_values.display_label (RESQML
        title, component read, unit). "" when the tree knows no title."""
        from fespp_on_trame.engine import property_values
        return property_values.display_label(state, tree, path)

    def _push_active_array_label(vid):
        """The Attributes card's "Colored by": the display name of the array
        colouring this view's active rep (the same text as the colour bar),
        "" when it is solid-coloured."""
        path = getattr(state, f"active_path__{vid}", "") or ""
        rep_path = _rep_path_of(path) if path else ""
        active = ""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if node_facts.is_derived(path):
            # a formula colours its grid's block while its eye is open:
            # named as its colour bar is then, nothing otherwise
            if path in eyes.get(vid):
                active = _derived_array_name(path)
        elif scene is not None and rep_path:
            sel = rep_path
            entry = scene.block_state.get(sel)
            if entry is not None:
                active = entry.label or entry.color_array or ""
        act_b = dict(state.ui_active_array_by_view or {})
        if act_b.get(vid, "") != active:
            act_b[vid] = active
            state.ui_active_array_by_view = act_b

    def _set_tool_target(vid, key, text):
        """What a tool card of `vid` acts on, named in its title bar
        ("Slicers · Geogrid"): `ui_tool_target__<vid>[tool key]`. With two
        grids loaded, a card that cuts "the active grid" without naming it
        cuts one at random as far as the reader can tell."""
        var = f"ui_tool_target__{vid}"
        cur = dict(getattr(state, var, None) or {})
        if cur.get(key, "") == (text or ""):
            return
        cur[key] = text or ""
        state[var] = cur

    def _push_grid_targets(vid):
        # each grid-scoped card names the representation it acts on
        # (app/scene/activation): the Slicers an IJK grid, the Thresholds
        # any isolatable one — an unstructured grid, a sub-representation
        # (04-verification D14)
        for tool in ("slicers", "thresholds"):
            # the Geometry slicer cuts the whole scene when no object is
            # picked or active (app/features/geometry_slicer, 29/10)
            pick = getattr(ctx, "geometry_target", None) if tool == "slicers" else None
            grid_path = pick(vid) if pick is not None else activation.target_of(vid, tool)
            if grid_path == "@scene":
                _set_tool_target(vid, tool, "Whole scene")
                continue
            _set_tool_target(vid, tool, _display_title(grid_path) if grid_path else "")
        # and the objects each slicer card can take, for its list (28/10)
        var = f"ui_tool_targets__{vid}"
        lists = {tool: [{"value": p, "label": _display_title(p) or p}
                        for p in activation.targets(vid, tool)]
                 for tool in ("slicers", "thresholds")}
        if (getattr(state, var, None) or {}) != lists:
            state[var] = lists
        _tell_slicers(vid)

    def _tell_slicers(vid):
        """The cards that list an object's properties (the Property slicer,
        app/features/property_slicer) read them again: a property ticked,
        another object active or picked."""
        for listener in getattr(ctx, "slicer_listeners", None) or ():
            listener(vid)

    def _say(text):
        """The session-wide snackbar — what no panel is there to carry (a
        gesture whose effect landed somewhere else, a refusal at the level
        of the application) — app/core/notifier."""
        notifier.say(text)

    def _property_or_note(path, what):
        """True when `path` carries values; otherwise say through the
        snackbar why nothing opened. Every door reaches the panels through
        the controllers, so the refusal belongs there and not in a menu."""
        if _is_property_path(path):
            return True
        _say(
            f"{_refused_node_name(path)} is not a property — {what} needs one.")
        return False

    def _refused_node_name(path):
        """The node a refusal names, in the tree's own words: the properties
        folder and the geometry leaf of a grid are named as such, with their
        grid. `_display_title` alone would call both by the grid, and answer
        a click on the "properties" row with "Geogrid is not a property"."""
        nid = tree.find_node_id(path) if path else None
        if nid is None:
            return (path or "").rsplit("/", 1)[-1] or "That node"
        kind = tree.find_type(nid) or ""
        grid = _display_title(path, "")
        if kind == "PropertiesFolder":
            return (f"The properties folder of {grid}" if grid
                    else "The properties folder")
        if "/_propsfolder_" in (path or "") and kind in _GRID_GEOMETRY_KINDS:
            return f"The geometry of {grid}" if grid else "The geometry"
        return tree.find_title(nid) or grid or "That node"

    def _node_title(path):
        """The node's own title — a property's name (engine/node_facts).
        `_display_title` is for a grid's geometry leaf: it names any path
        under a properties folder by the grid."""
        return node_facts.title_of(tree, path)

    def _rep_path_of(node_path):
        """The representation of a path — a derived recipe's grid included —
        or None (engine/node_facts, the one answer)."""
        return node_facts.rep_path_for(tree, node_path) or None

    # XML of a tree node (Attributes card), read through the reader's query
    # channel. Cached per uuid, and cleared when the assembly tag changes (a
    # new file or dataspace).
    _xml_cache = {}


    def _node_xml_pretty(path):
        """The node's XML as fesapi holds it — through the reader's query
        channel, so it is the same over EPC and ETP, and a partial node
        renders its `<PartialObject>` marker instead of a blank card."""
        if not path:
            return ""
        # the object the row leads to: itself, the grid of a grid folder,
        # the TimeSeries of a series row, the completion of a perforation;
        # a realization group has none and the card shows no XML part.
        # NOT lower-cased: fesapi's lookup is an exact map find (the C++
        # case-folds itself); the zip fallback folds on its own side
        uuid = row_object.uuid_of(path.rsplit("/", 1)[-1])
        if not uuid:
            return ""
        src = active_data_source.get_source()
        try:
            t = repo_query.tag(src)
        except Exception:
            t = 0
        # one cache per assembly tag: a second dataspace or a new file must
        # not serve the previous session's XML for the same uuid
        if _xml_cache.get("__tag__") != t:
            _xml_cache.clear()
            _xml_cache["__tag__"] = t
        if uuid in _xml_cache:
            return _xml_cache[uuid]
        try:
            text = repo_query.object_xml(src, uuid, cache_tag=t)
        except repo_query.ChannelMissing:
            text = ""
        except Exception as exc:
            print("[fespp] object xml error:", exc, flush=True)
            text = ""
        _xml_cache[uuid] = text
        return text

    def _blocks_for_rep(rep_path):
        """The rep's block datasets on the client-side PDC of the active
        source, as (dataset, flat_index) pairs — the currency of a composite
        ID selection. [] when the block isn't loaded. Shared by the
        Attributes highlight AND the cross-plot lasso: both end in the same
        SelectCompositeDataIDs, so they must resolve blocks the same way —
        the assembly index (engine/blockscope/assembly_index)."""
        return ctx.assembly_index.datasets(rep_path)

    def _tree_backed_arrays(rep_path, arrays, checked_only=False):
        """Only the arrays the tree shows as properties of that rep: a
        property node's title as FESPP sanitises it, or the VTK name a
        synthetic MR/TS node carries in propTitle (a realization suffix
        on the array is stripped first). VTK's own arrays (vtkGhostType,
        connectivityFlags, SolidColor…) never reach the cards.
        `checked_only`: only the properties TICKED in the tree (their node in
        `ui_loaded_array_paths`) — an unticked property's array may stay on
        the block, and a card listing it would offer what the tree says is
        off (the manager, 15/10: the Thresholds list and the Attributes
        columns did not follow the tree)."""
        from fespp_on_trame.engine.utils.naming import strip_realization_suffix
        rid = tree.find_node_id(rep_path) if rep_path else None
        if rid is None:
            return []
        ticked = set(state.ui_loaded_array_paths or []) if checked_only else None
        names = {}     # array name -> the property node's path
        try:
            for nid in tree.find_all_descendant_ids(0):
                if not node_facts.is_property_kind(tree.find_type(nid) or ""):
                    continue
                if tree.find_representation_node(nid) != rid:
                    continue
                npath = tree.find_path(nid)
                if ticked is not None and npath not in ticked:
                    continue
                # the name the block's array carries (a multi-realization
                # property whose name holds a space was missed before)
                names[node_facts.vtk_base_name(tree, npath)] = npath
        except Exception as exc:
            print(f"[fespp] tree arrays ({rep_path}):", exc, flush=True)
            return [a for a in arrays
                    if not a["name"].startswith("vtk")
                    and a["name"] not in ("SolidColor", "connectivityFlags")]
        names.pop("", None)
        # each array keeps its property's path: the session's choices
        # (the component of a vector) are keyed by it
        return [dict(a, path=names[strip_realization_suffix(a["name"])]) for a in arrays
                if strip_realization_suffix(a["name"]) in names]

    def _rep_card_arrays(rep_path):
        """The arrays of `rep_path` a card can act on: its properties ticked
        in the tree ([{name, assoc, path}]) — what the Property slicer
        lists for the object it was pointed at (28/10)."""
        if not rep_path:
            return []
        try:
            arrays = [{"name": n, "assoc": a}
                      for a, n in (source_registry.available_arrays(rep_path) or [])]
        except Exception as exc:
            print(f"[fespp] card arrays ({rep_path}):", exc, flush=True)
            return []
        return _tree_backed_arrays(rep_path, arrays, checked_only=True)

    def _push_card_arrays(vid, path):
        """The properties THIS view's Thresholds card offers: the arrays of
        the active node's rep that are ticked in the tree. Called when the
        active node changes and when a property is ticked or unticked."""
        arrays = _rep_card_arrays(_rep_path_of(path) if path else "")
        buckets = dict(state.ui_color_arrays_by_view or {})
        if buckets.get(vid) != arrays:
            buckets[vid] = arrays
            state.ui_color_arrays_by_view = buckets
        _tell_slicers(vid)

    def _node_blocks(view_id):
        """The active node's block datasets on the client-side PDC of the
        active source (builtin mode) + the arrays the Attributes card
        shows: (blocks, assoc, wanted, error). A property node -> that
        array (this view's realization); a geometry node -> the cell arrays
        of its block whose property is ticked in the tree (first 8): an
        unticked property's column goes (the manager, 15/10). The node is
        the one the card reads (`activation.values_path`)."""
        path = core.activation.values_path(view_id)
        rep_path = _rep_path_of(path) if path else ""
        if not rep_path:
            return None, "CELLS", [], "No representation for this node."
        blocks = _blocks_for_rep(rep_path)
        if not blocks:
            return None, "CELLS", [], NOT_READ
        if node_facts.is_derived(path):
            # a recipe is no array of the blocks: its grid's blocks, its
            # values read through the seam by whoever needs them
            return blocks, "CELLS", [], ""
        assoc, wanted = "CELLS", []
        # a property reads its own array; any other node (the representation,
        # the grid's own row above "geometry" and "properties", a folder)
        # reads the geometry it belongs to
        if path != rep_path and _is_property_path(path):
            # a log not read: its frame read with other logs holds none of its values
            if node_facts.is_unread_log(tree, path, state.ui_loaded_array_paths):
                return None, "CELLS", [], ARRAY_NOT_READ
            a, n, _s = source_resolver.resolve_array_for_path(
                source_registry, tree, rep_path, path,
                realization_idx=_real_idx_for(view_id, path))
            if not n:
                return None, "CELLS", [], ARRAY_NOT_READ
            assoc, wanted = (a or "CELLS"), [n]
            # a property that is a block of its own — a well's log, one block
            # per log under its frame — is read on that block alone: the
            # frame's other logs are other blocks, without its array
            own = ctx.assembly_index.datasets(path)
            if own:
                blocks = own
        else:
            wanted = [a["name"] for a in _ticked_arrays(blocks, rep_path)]
        return blocks, assoc, wanted, ""

    def _ticked_arrays(blocks, rep_path, assoc="CELLS", limit=8):
        """[{name, assoc, path}] — the arrays of `assoc` on the node's
        first block whose property is ticked in the tree (the first
        `limit`), each with its property's path."""
        data = blocks[0][0].GetPointData() if assoc == "POINTS" else blocks[0][0].GetCellData()
        names = [data.GetArrayName(k) for k in range(data.GetNumberOfArrays())]
        return _tree_backed_arrays(
            rep_path, [{"name": n, "assoc": assoc} for n in names if n],
            checked_only=True)[:limit]

    def _geometry_columns(blocks, assoc):
        """[(name, numpy vector)] — where each row of a geometry node is,
        over its blocks in the Values table's index order: POINTS -> X, Y, Z
        (the file's coordinates: Z is not exaggerated), then the measured
        depth of the points of a well's trajectory, log or markers (the
        reader's "MD" point array); CELLS -> I, J, K
        (1-based) on an IJK grid, nothing on any other (the manager, 21/10:
        a cell's centre X Y Z said nothing, its id and I J K do)."""
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        if assoc == "POINTS":
            xyz = []
            for ds, _flat in blocks:
                pts = ds.GetPoints()
                n = ds.GetNumberOfPoints()
                xyz.append(vtk_to_numpy(pts.GetData()).astype(float).reshape(-1, 3)
                           if pts is not None and n else np.zeros((0, 3)))
            xyz = np.concatenate(xyz) if xyz else np.zeros((0, 3))
            out = [("X", xyz[:, 0]), ("Y", xyz[:, 1]), ("Z", xyz[:, 2])]
            mds = [ds.GetPointData().GetArray("MD") for ds, _flat in blocks]
            if mds and all(a is not None and a.GetNumberOfComponents() == 1
                           and a.GetNumberOfTuples() == ds.GetNumberOfPoints()
                           for a, (ds, _flat) in zip(mds, blocks)):
                out.insert(0, ("MD", np.concatenate([vtk_to_numpy(a).astype(float) for a in mds])))
            return out
        if not blocks or not all(is_ijk_grid(ds) for ds, _f in blocks):
            return []
        ijk = []
        for ds, _flat in blocks:
            n = ds.GetNumberOfCells()
            ext = list(ds.GetExtent())
            ni, nj = max(1, ext[1] - ext[0]), max(1, ext[3] - ext[2])
            c = np.arange(n, dtype=np.int64)
            ijk.append(np.stack([c % ni + ext[0] + 1, (c // ni) % nj + ext[2] + 1,
                                 c // (ni * nj) + ext[4] + 1], axis=1))
        ijk = np.concatenate(ijk)
        return [("I", ijk[:, 0]), ("J", ijk[:, 1]), ("K", ijk[:, 2])]

    def _cell_points(blocks, cells, xyz=True, cap=32):
        """{cell: {"ids", "xyz", "more"}} — the points of each of `cells`
        (global cell indices, blocks order) by their global ids (the Values
        table's point id, blocks order too) and, with `xyz`, their file
        coordinates; at most `cap` a cell (None: all), `more` the rest (a
        point set's one cell holds every point). One VTK lookup a cell: for
        a page, or an export's rows, never a whole grid at once."""
        import bisect
        from vtkmodules.vtkCommonCore import vtkIdList
        starts, pstarts, nc, npts = [], [], 0, 0
        for ds, _f in blocks:
            starts.append(nc)
            pstarts.append(npts)
            nc += ds.GetNumberOfCells()
            npts += ds.GetNumberOfPoints()
        ids, out = vtkIdList(), {}
        for gi in cells:
            gi = int(gi)
            if gi < 0 or gi >= nc or gi in out:
                continue
            b = bisect.bisect_right(starts, gi) - 1
            ds = blocks[b][0]
            ds.GetCellPoints(gi - starts[b], ids)
            n = ids.GetNumberOfIds()
            local = [ids.GetId(k) for k in range(n if cap is None else min(n, cap))]
            e = {"ids": [pstarts[b] + q for q in local], "more": n - len(local)}
            if xyz:
                e["xyz"] = [list(ds.GetPoint(q)) for q in local]
            out[gi] = e
        return out

    def _block_column(blocks, assoc, name, component=None, ghosts=True):
        """The whole array `name` over the node's blocks as ONE numpy vector
        (global index order = blocks order), read the way the colour reads
        it: a vector's chosen `component`, its magnitude when none is
        (property_values.reduce_components). With `ghosts`, the cells a
        block blanks (vtkGhostType: inactive cells carry a 0.0 fill) are
        NaN, as every value reader masks them."""
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        from fespp_on_trame.engine import property_values as _pv
        parts = []
        for ds, _f in blocks:
            n = ds.GetNumberOfPoints() if assoc == "POINTS" else ds.GetNumberOfCells()
            data = ds.GetPointData() if assoc == "POINTS" else ds.GetCellData()
            arr = data.GetArray(name)
            if arr is None:
                parts.append(np.full(n, np.nan))
                continue
            a = _pv.reduce_components(vtk_to_numpy(arr), component)
            ghost = data.GetArray("vtkGhostType") if ghosts else None
            if ghost is not None:
                gm = vtk_to_numpy(ghost).ravel()
                if gm.size == a.size:
                    a[gm != 0] = np.nan
            parts.append(a)
        return np.concatenate(parts) if parts else np.zeros(0)

    # ------------------------------------------------------------------
    return (_block_column, _blocks_for_rep, _display_title, _geometry_columns, _node_blocks, _node_title, _property_label, _property_or_note, _push_active_array_label, _push_card_arrays, _push_grid_targets, _rep_path_of, _say, _set_tool_target, _ticked_arrays, _cell_points, _rep_card_arrays)
