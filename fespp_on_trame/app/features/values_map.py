"""The Values card's Map (the PO, 03/11: "une visualisation en plus de
cells / points qui montre le tableau avec les valeurs et leur couleur de la
colormap"): one K layer of an IJK grid as a table — I across, J down as on
a map — each cell its value and its colour in the view's colour table, dressed
as its eye would dress it when no eye paints it: the active property, or on the
grid's own row the property that paints it. On the velocity model's grid
(app/features/time_depth_tree) a cell's value is edited: the model's cell
set by hand, the grid rewritten.

State:   ``ui_node_map_by_view[vid]`` = {array, k, nk, ni, nj, rows (nj rows
         of ni values, the last J first), colors (the same, "#rrggbb" | None),
         editable} | {error}.
Gestures: ``controller.node_values_map({k}, vid)``, ``controller.node_map_cell({i,
         j, k, v}, vid)``.
"""
MAX_CELLS = 40000      # cells of one layer the map shows at most


def register(core, *, _rep_path_of, _node_blocks):
    controller, ctx, state = core.controller, core.ctx, core.state
    tree, source_registry = core.tree, core.source_registry

    def _out(vid, d):
        maps = dict(getattr(state, "ui_node_map_by_view", None) or {})
        maps[vid] = d
        state.ui_node_map_by_view = maps

    def _hex(rgba):
        return "#%02x%02x%02x" % tuple(int(c) for c in rgba[:3])

    def _model_grid(rep_path):
        cur = getattr(ctx, "time_depth_tree_current", None)
        cur = cur() if cur is not None else None
        return bool(cur) and rep_path in (cur.get("grid"), cur.get("container"))

    def _table(scene, rep_path, path, name, vals):
        """The view's colour table of `name`. Painting nothing in this view,
        it is dressed as an eye would: by code when the property has codes,
        else on the range of its values."""
        import numpy as np
        from fespp_on_trame.engine import categorical_palette, ranges, source_resolver
        lut = scene.scoped_lut(name)
        if lut is None or any(e.color_array == name for e in scene.block_state.values()):
            return lut
        _assoc, _name, source = source_resolver.resolve_array_for_path(source_registry, tree, rep_path, path)
        cats, _why = categorical_palette.categories_for(tree, rep_path, name, source, "CELLS",
                                                        reader=source_registry.shared_source())
        if cats:
            categorical_palette.apply(lut, cats)
            return lut
        categorical_palette.tame(lut)
        finite = vals[np.isfinite(vals)]
        if finite.size and not scene.range_pinned(lut):
            lut.RescaleTransferFunction(*ranges.widen_for_bar(float(finite.min()), float(finite.max())))
        return lut

    def _layer(vid, k):
        """The map of layer `k` of the active node's grid in `vid`."""
        import numpy as np
        from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        path = core.activation.values_path(vid)
        rep_path = _rep_path_of(path) if path else ""
        if not rep_path:
            return {"error": "No grid for this node."}
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        entry = scene.block_state.get(rep_path) if scene is not None else None
        painting = entry.color_array if entry is not None and (entry.assoc or "CELLS") == "CELLS" else ""
        # the active property's own array, else what paints the grid
        _blocks, assoc, wanted, why = _node_blocks(vid)
        name = wanted[0] if path != rep_path and wanted and assoc == "CELLS" else painting
        if not name:
            return {"error": why or "The map reads a cell property: click one in the tree, or open its eye."}
        blocks = [ds for ds, _flat in (ctx.assembly_index.datasets(rep_path) or ()) if hasattr(ds, "GetExtent")]
        if not blocks:
            return {"error": "The map reads an IJK grid: this node has none loaded."}
        ds = blocks[0]
        ext = ds.GetExtent()
        ni, nj, nk = ext[1] - ext[0], ext[3] - ext[2], ext[5] - ext[4]
        if ni * nj > MAX_CELLS:
            return {"error": f"A layer of {ni} × {nj} cells is too wide for the map ({MAX_CELLS} at most)."}
        arr = ds.GetCellData().GetArray(name)
        if arr is None or arr.GetNumberOfTuples() != ni * nj * nk:
            return {"error": f"{name} is not one value per cell of the grid."}
        k = max(0, min(int(k), nk - 1))
        vals = np.asarray(vtk_to_numpy(arr), float)
        if vals.ndim > 1:
            vals = np.linalg.norm(vals, axis=1)
        layer = vals.reshape(nk, nj, ni)[k]
        lut = None if scene is None else (scene.scoped_lut(name) if name == painting
                                          else _table(scene, rep_path, path, name, vals))
        colors = None
        if lut is not None:
            flat = numpy_to_vtk(np.ascontiguousarray(layer.ravel()), deep=1)
            mapped = lut.GetClientSideObject().MapScalars(flat, 0, -1)
            rgba = vtk_to_numpy(mapped).reshape(nj, ni, -1)
            colors = [[_hex(rgba[j, i]) for i in range(ni)] for j in range(nj - 1, -1, -1)]
        rows = [[None if not np.isfinite(v) else round(float(v), 4) for v in layer[j]] for j in range(nj - 1, -1, -1)]
        return {"array": (entry.label if entry is not None and name == painting else "") or name,
                "k": k, "nk": nk, "ni": ni, "nj": nj, "rows": rows, "colors": colors,
                "editable": _model_grid(rep_path) and name in _velocity_titles()}

    def _velocity_titles():
        from fespp_on_trame.engine import resqml_epc
        return resqml_epc.TITLES

    @controller.set("node_values_map")
    def node_values_map(req, view_id):
        vid = str(view_id or "")
        try:
            _out(vid, _layer(vid, int((req or {}).get("k") or 0)))
        except Exception as exc:
            print(f"[fespp] values map error ({vid}):", exc, flush=True)
            _out(vid, {"error": f"Map unavailable: {exc}"})

    @controller.set("node_map_cell")
    def node_map_cell(edit, view_id):
        """A cell of the velocity model's grid set from the map: the model's
        cell set by hand (app/features/time_depth_law), the grid rewritten
        a second later (app/features/time_depth_tree)."""
        vid = str(view_id or "")
        edit = dict(edit or {})
        path = core.activation.values_path(vid)
        if not _model_grid(_rep_path_of(path) if path else ""):
            print(f"[fespp] values map ({vid}): a cell edited off the velocity model refused", flush=True)
            return
        controller.time_depth_law_edit({"op": "cell", "i": edit.get("i"), "j": edit.get("j"),
                                        "k": edit.get("k"), "v": edit.get("v")})
        node_values_map({"k": edit.get("k")}, vid)

    state.ui_node_map_by_view = {}
