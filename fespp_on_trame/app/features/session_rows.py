"""the session's own objects: selection extracts, derived rows
A grid with cells highlighted offers "+" on its tree row (the PO,
15/10): KEEP the selection (those cells only) or REMOVE it (every other
cell). Either is an ExtractSelection of the grid's block — the
collection's structure, its names and each cell's original id survive
it — shown in that view in place of the grid and listed under it in the
tree. The calculator's derived properties are listed there too. All
are made in the session and never written to the file: the tree draws
them in a colour of their own, "disposable".

(Moved out of app/boot, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine.state_defaults import z_scale_of


def register(core, *, _derived_forget, _derived_values, _live_render_vids,
             _path_for_flat_index, _pv_view_of, _rep_path_of):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_extract_colour, _extract_layout, _extract_seq, _pdc_flats, _publish_sel_counts, _publish_session_rows, _row_of_rep, occupancy)."""
    # the shared services (app/core/context.Core)
    state = core.state
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    scheduler = core.scheduler
    eyes = core.eyes
    displays = core.displays
    _sel_cells = core.selection.cells
    _extracts = core.selection.extracts
    # --- the session's own objects: selection extracts, derived rows -------
    # A grid with cells highlighted offers "+" on its tree row (the PO,
    # 15/10): KEEP the selection (those cells only) or REMOVE it (every other
    # cell). Either is an ExtractSelection of the grid's block — the
    # collection's structure, its names and each cell's original id survive
    # it — shown in that view in place of the grid and listed under it in the
    # tree. The calculator's derived properties are listed there too. All
    # are made in the session and never written to the file: the tree draws
    # them in a colour of their own, "disposable".
    # (`_extracts`, vid -> [entry], made by boot: the selection helpers
    # read it too)
    _extract_seq = [0]

    def _row_of_rep(rep_path):
        """The tree row standing for a representation: its GridContainer
        (the grid's own row, above "geometry" / "properties") when it has
        one, else the representation itself."""
        nid = tree.find_node_id(rep_path) if rep_path else None
        if nid is None:
            return rep_path
        cid = tree.find_parent_node_id_with_type(nid, "GridContainer")
        return (tree.find_path(cid) if cid is not None else None) or rep_path

    def _publish_sel_counts(vid):
        """{tree row: highlighted cells} of this view: the rows that offer
        "+" (keep / remove the selection)."""
        counts = {}
        for flat, cells in (_sel_cells.get(vid) or {}).items():
            try:
                p = _path_for_flat_index(flat)
                rep = (_rep_path_of(p) if p else None) or p
            except Exception as exc:
                print(f"[fespp] selection counts ({vid}):", exc, flush=True)
                rep = None
            if not rep:
                continue
            row = _row_of_rep(rep)
            counts[row] = counts.get(row, 0) + len(cells)
        state[f"ui_sel_counts__{vid}"] = counts
        _sync_selection_overlay(vid)

    # The highlight of a grid drawn by its isolate (a threshold, the slicer,
    # the NaN mask, a selection extract): ParaView draws a selection on the
    # composite's display, which has given the grid up, and the isolate's
    # displays draw none (the PO, 15/10: on a threshold no selection showed).
    # Its own overlay then: the selected cells, outlined in the selection's
    # pink, one per view.
    _sel_overlays = {}      # vid -> {"ex", "disp"}
    _OVERLAY_RGB = [1.0, 0.0, 1.0]

    def _drop_selection_overlay(vid):
        displays.remove(vid, "selection_overlay")
        ov = _sel_overlays.pop(vid, None)
        if not ov:
            return
        try:
            pvv = _pv_view_of(vid)
            if pvv is not None:
                pvsimple.Hide(ov["ex"], pvv)
            pvsimple.Delete(ov["ex"])
        except Exception as exc:
            print(f"[fespp] selection overlay drop ({vid}):", exc, flush=True)

    def _sync_selection_overlay(vid):
        """Draw (or redraw, or remove) this view's selection overlay: only
        for the selected cells whose grid the composite does not draw in
        this view; the composite's own highlight shows the others."""
        from paraview import servermanager as _svm
        _drop_selection_overlay(vid)
        sel = _sel_cells.get(vid) or {}
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        pvv = _pv_view_of(vid)
        if not sel or scene is None or pvv is None or not scene.isolated:
            return
        isolated = set(scene.isolated)
        ids = []
        for flat, cells in sel.items():
            try:
                p = _path_for_flat_index(flat)
                rep = (_rep_path_of(p) if p else None) or p
            except Exception as exc:
                print(f"[fespp] selection overlay: block ({vid}):", exc, flush=True)
                continue
            if rep in isolated:
                for c in cells:
                    ids += [flat, 0, int(c)]
        if not ids:
            return
        try:
            src = active_data_source.get_display_source()
            pysrc = src if hasattr(src, "SMProxy") else _svm._getPyProxy(src)
            idsrc = _svm.sources.CompositeDataIDSelectionSource(IDs=ids, FieldType="CELL")
            ex = pvsimple.ExtractSelection(registrationName=f"selection_highlight__{vid}",
                                           Input=pysrc, Selection=idsrc)
            disp = pvsimple.Show(ex, pvv)
            disp.Representation = "Wireframe"
            disp.ColorArrayName = ["POINTS", ""]
            disp.AmbientColor = list(_OVERLAY_RGB)
            disp.DiffuseColor = list(_OVERLAY_RGB)
            disp.LineWidth = 2.0
            disp.Pickable = 0
            disp.Scale = [1.0, 1.0, z_scale_of(state, vid)]
            _sel_overlays[vid] = {"ex": ex, "disp": disp}
            displays.add(vid, "selection_overlay", "selection", disp,
                         close=lambda v=vid: _drop_selection_overlay(v))
            scene.resync_bars()
        except Exception as exc:
            print(f"[fespp] selection overlay ({vid}):", exc, flush=True)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    def _pdc_flats(pdc, path, subtree=False):
        """The flat composite indices of the datasets the assembly node
        `path` owns in the collection `pdc`, in order — the numbering a
        selection's composite ids use (0 the collection, then each
        partitioned dataset followed by its partitions). Computed on the
        collection itself, the same way for the reader's output and for an
        extract of it."""
        asm = pdc.GetDataAssembly() if pdc is not None else None
        node = asm.GetFirstNodeByPath(path) if asm is not None else -1
        if (node is None or node < 0) and asm is not None and path.count("/") >= 2:
            # an extract's assembly keeps the hierarchy under another root
            # name ("assembly" where the reader says "data")
            node = asm.GetFirstNodeByPath("/" + asm.GetRootNodeName() + "/" + path.split("/", 2)[2])
        if node is None or node < 0:
            return []
        own = set(asm.GetDataSetIndices(node, bool(subtree)))
        out, flat = [], 1
        for i in range(pdc.GetNumberOfPartitionedDataSets()):
            pds = pdc.GetPartitionedDataSet(i)
            n = pds.GetNumberOfPartitions() if pds is not None else 0
            if i in own:
                out += [flat + 1 + j for j in range(n)]
            flat += 1 + n
        return out

    def _publish_session_rows(vid):
        """The rows the session adds to this view's tree: its extracts, and
        the calculator's derived properties under their grid's
        "properties"."""
        rows = []
        for e in _extracts.get(vid, []):
            rows.append({"path": e["path"], "parent": e["row"], "title": e["title"],
                         "kind": "extract", "type": "SelectionExtract",
                         "visible": e["visible"], "info": e["info"]})
        for d in (getattr(state, "ui_derived_props", None) or []):
            if d.get("stale") or d.get("error"):
                continue
            rep = d.get("rep_path") or ""
            parent = rep.rsplit("/", 1)[0] if rep else ""
            pid = tree.find_node_id(parent) if parent else None
            if pid is None or (tree.find_type(pid) or "") != "PropertiesFolder":
                parent = _row_of_rep(rep)
            rows.append({"path": d["path"], "parent": parent, "title": d.get("name") or "",
                         "kind": "derived", "type": "ContinuousProperty",
                         "visible": d["path"] in eyes.get(vid),
                         "info": "ƒ = " + (d.get("expression") or "")
                                 + " — computed in this session, not in the file"})
        state[f"ui_session_rows__{vid}"] = rows
        core.lifecycle.emit("session_rows", vid=vid)

    @state.change("ui_derived_props")
    def _on_derived_rows(**_):
        alive = {d.get("path") for d in (getattr(state, "ui_derived_props", None) or [])
                 if not d.get("stale") and not d.get("error")}
        # a shown formula follows its recipe: computed again (its values are
        # a snapshot), or its eye closes with the recipe
        for path in list(_derived_values):
            _derived_forget(path)
        for vid in _live_render_vids():
            cur = eyes.get(vid)
            keep = [p for p in cur if not derived_props.is_derived(p) or p in alive]
            if keep != cur:
                eyes.set(vid, keep)
            elif any(derived_props.is_derived(p) for p in cur):
                eyes.apply(vid)
            _publish_session_rows(vid)

    def _extract_colour(e):
        """The extract wears what its grid wears in that view: the same
        property and colour table, or its solid colour."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(e["vid"])
        entry = scene.block_state.get(e["selector"]) if scene is not None else None
        disp = e["disp"]
        try:
            if entry is not None and entry.color_array:
                vres = core.view_resources.get(e["vid"])
                lut = (vres.get_or_create_lut(entry.color_array) if vres is not None
                       else pvsimple.GetColorTransferFunction(entry.color_array))
                disp.ColorArrayName = [entry.assoc or "CELLS", entry.color_array]
                disp.LookupTable = lut
            else:
                disp.ColorArrayName = ["POINTS", ""]
                if entry is not None and entry.solid_rgb:
                    disp.DiffuseColor = list(entry.solid_rgb)
        except Exception as exc:
            print(f"[fespp] extract color ({e['vid']}):", exc, flush=True)

    def _replaced_in(vid, selector):
        """A visible extract of the grid is drawn in its place in `vid` (a
        formula only colours the grid: engine/derived_arrays)."""
        return any(x["visible"] and x["selector"] == selector for x in _extracts.get(vid, []))

    def _settled(vid, _rep_path):
        # who draws the grid changed: the selected cells' highlight follows
        # (the composite's own, or the overlay over an isolate) — D10 — and
        # what reads what the view draws
        _sync_selection_overlay(vid)
        core.lifecycle.emit("view_cuts", vid=vid)

    # who draws a grid in a view, decided in one place (app/scene/occupancy):
    # an extract, else its isolate while needed and seen, else the composite
    from fespp_on_trame.app.scene.occupancy import Occupancy
    occupancy = Occupancy(
        scene_of=lambda v: (getattr(ctx, "blockscope_scenes", None) or {}).get(v),
        isolate_of=lambda v, r: (getattr(ctx, "grid_isolates", None) or {}).get((v, r)),
        replaced=_replaced_in,
        on_settled=_settled)
    ctx.occupancy = occupancy

    def _extract_layout(vid, selector, rep_path):
        """The grid gives its place to a visible extract of it; with none
        visible it is drawn again, by the composite or by its isolate."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is None:
            return
        occupancy.settle(vid, rep_path, selector)
        scene.resync_bars()
        scheduler.mark_dirty(vid)
        scheduler.flush()
    return (_extract_colour, _extract_layout, _extract_seq, _pdc_flats, _publish_sel_counts, _publish_session_rows, _row_of_rep, occupancy)
