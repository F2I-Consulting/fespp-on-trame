"""Picking in a 3D view (`view_pick`): the cells under a click or a
rectangle — rays on the drawn leaves, a surface fallback, the picked ids
traced back to the source grid (through an extract when the pick hit
one) — and the readout of a picked cell: its IJK, nodes, values, the
title of the well it belongs to.

(Moved out of app/boot, overhaul slice 10.)"""
import sys
import time
from paraview import simple as pvsimple
from fespp_on_trame.app.scene import selection_sources
from fespp_on_trame.engine.blockscope import assembly_index
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.engine.node_kinds import is_ijk_grid


def register(core, *, _clear_extract_highlights, _clear_selection_of,
             _cmap_array_path, _display_title, _drop_block_highlight,
             _globe_scene, _leaf_dataset, _locator_for, _own_selection,
             _path_for_flat_index, _pdc_flats, _pick_region,
             _publish_sel_counts, _refresh_values, _rep_path_of,
             _selection_ids):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_cell_ijk, _cell_value_text, _extract_cells, _ids_to_source, _nothing_under, _surface_fallback, _wellbore_title)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    scheduler = core.scheduler
    activation = core.activation
    _mv = core.mv
    selection = core.selection
    _extracts = core.selection.extracts
    _drop_sel_inputs = core.selection.drop_inputs
    def _cell_ijk(ds, cell):
        """(i, j, k), 1-based as a reservoir engineer counts them, of a cell
        of a structured grid — FESPP maps an IjkGrid to a
        vtkExplicitStructuredGrid, a lattice one to a vtkStructuredGrid, whose
        extent says the counts; None on any other dataset (a wellbore, a
        surface: no IJK to speak of)."""
        try:
            if not is_ijk_grid(ds):
                return None
            from vtkmodules.vtkCommonDataModel import vtkStructuredData
            ext = list(ds.GetExtent())
            ijk = [0, 0, 0]
            vtkStructuredData.ComputeCellStructuredCoordsForExtent(int(cell), ext, ijk)
            return tuple(int(v) + 1 for v in ijk)
        except Exception:
            return None

    def _only_flats(ids, flats, keep=True):
        """The [flat, proc, id, …] triplets of `ids` whose flat is in
        `flats` (or, `keep` False, is not) — numpy: a frustum through a
        grid holds millions of them."""
        import numpy as np
        if not ids:
            return []
        a = np.asarray(ids, dtype=np.int64).reshape(-1, 3)
        m = np.isin(a[:, 0], np.fromiter(flats, dtype=np.int64, count=len(flats)))
        return a[m if keep else ~m].ravel().tolist()

    def _with_points(pvv, region, mode, vid, hits):
        """`hits` as (representation, selection, cell ids, point ids). A hit
        on a point set gives its POINTS under the gesture, not its one
        poly-vertex cell (app/scene/selection_sources; the PO, 20/10: a
        rectangle on part of a point set took all of it): the gesture is
        asked again of ParaView for points — on the surface, or through the
        volume — and each hit's point-set blocks take those, its other
        blocks keep their cells. A hit left with neither goes."""
        import numpy as np
        flats = set()
        for _r, _s, ids in hits:
            if ids:
                flats.update(np.unique(np.asarray(ids[0::3], dtype=np.int64)).tolist())
        clouds = set()
        for f in flats:
            try:
                if selection_sources.is_point_cloud(_leaf_dataset(f)):
                    clouds.add(f)
            except Exception as exc:
                print(f"[fespp] pick: block {f} ({vid}): {exc!r}", file=sys.stderr, flush=True)
        if not clouds:
            return [(r, s, ids, []) for r, s, ids in hits]
        if mode == "frustum":
            phits = _frustum_pick(pvv, region, vid, field="POINT", flats=clouds)
        else:
            from vtkmodules.vtkCommonCore import vtkCollection
            phits = []
            reps, srcs = vtkCollection(), vtkCollection()
            if pvv.SMProxy.SelectSurfacePoints(region, reps, srcs, False, 0, False):
                for i in range(min(reps.GetNumberOfItems(), srcs.GetNumberOfItems())):
                    s_i = srcs.GetItemAsObject(i)
                    phits.append((reps.GetItemAsObject(i), s_i, _selection_ids(s_i)))
        points_of = {}
        for r, _s, ids in phits:
            inp = r.GetProperty("Input").GetProxy(0)
            points_of.setdefault(inp.GetGlobalIDAsString(), []).extend(
                _only_flats(ids, clouds))
        out = []
        for r, s, ids in hits:
            gid = r.GetProperty("Input").GetProxy(0).GetGlobalIDAsString()
            cells = _only_flats(ids, clouds, keep=False)
            pts = points_of.pop(gid, [])
            if cells or pts:
                out.append((r, s, cells, pts))
        print(f"[fespp] pick ({vid}): {len(clouds)} point set(s) picked by their points",
              file=sys.stderr, flush=True)
        return out

    def _frustum_pick(pvv, region, vid="", field="CELL", flats=None):
        """[(representation, selection source, [flat, proc, cell, ...]), ...]
        of a pick THROUGH the volume: every representation it hits, [] for
        none; `field` "POINT" asks for the points instead (a point set's),
        `flats` keeps only those blocks' ids.

        Not ParaView's SelectFrustumCells: it builds the frustum in WORLD
        coordinates and tests it against each representation's DATA bounds,
        and the vertical exaggeration (the displays' Scale) sets the two
        apart — under Z x5 a grid lying far from the origin was never hit,
        "(no cell selected)" (the PO, 15/10). The frustum is built here in
        each representation's DATA coordinates (the world's divided by its
        Scale, less its Position), and every visible pickable
        representation is asked for the cells it holds; EACH that holds
        some is a hit — a grid's extract and the wellbore the composite
        still draws are picked together (the PO, 16/10: after a Keep on the
        grid, the volume selection could not reach the wellbore any more,
        the extract holding more cells won alone)."""
        from paraview import servermanager as _svm
        from paraview.modules.vtkRemotingViews import vtkSMSelectionHelper
        from vtkmodules.vtkCommonDataModel import vtkSelectionNode
        ren = pvv.GetRenderer()
        x0, y0, x1, y1 = region
        x1 = x1 if x1 > x0 else x0 + 1
        y1 = y1 if y1 > y0 else y0 + 1
        world = []
        # the corner order vtkFrustumSelector reads: near / far of lower
        # left, upper left, lower right, upper right
        for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
            for z in (0.0, 1.0):
                ren.SetDisplayPoint(x, y, z)
                ren.DisplayToWorld()
                w = list(ren.GetWorldPoint())
                h = w[3] or 1.0
                world.append((w[0] / h, w[1] / h, w[2] / h))

        def _vec(rep, name, default):
            p = rep.GetProperty(name)
            try:
                v = [float(p.GetElement(i)) for i in range(3)] if p is not None else default
            except Exception as exc:
                print(f"[fespp] frustum {name}:", exc, flush=True)
                v = default
            return v

        # the composite's cells count only in the blocks this view draws
        try:
            src_id = active_data_source.get_display_source().GetGlobalIDAsString()
            allowed = _visible_flats(vid)
            crop_tips = _crop_tips(vid)
        except Exception as exc:
            print(f"[fespp] frustum: visible blocks ({vid}):", exc, flush=True)
            src_id, allowed, crop_tips = None, set(), set()
        sources = {}    # (scale, position) -> the frustum source in those data coordinates
        done = set()    # inputs already asked, under one transform
        hits = []
        rp = pvv.SMProxy.GetProperty("Representations")
        for k in range(rp.GetNumberOfProxies()):
            r = rp.GetProxy(k)
            vis, pick, inp_p = (r.GetProperty("Visibility"), r.GetProperty("Pickable"),
                                r.GetProperty("Input"))
            if inp_p is None or inp_p.GetNumberOfProxies() == 0 or vis is None or not vis.GetElement(0):
                continue
            if pick is not None and not pick.GetElement(0):
                continue
            inp = inp_p.GetProxy(0)
            scale = tuple(v or 1.0 for v in _vec(r, "Scale", [1.0, 1.0, 1.0]))
            pos = tuple(_vec(r, "Position", [0.0, 0.0, 0.0]))
            key = (inp.GetGlobalIDAsString(), scale, pos)
            if key in done:
                continue
            done.add(key)
            fs = sources.get((scale, pos))
            if fs is None:
                pts = []
                for p in world:
                    pts += [(p[i] - pos[i]) / scale[i] for i in range(3)] + [1.0]
                fs = _svm.sources.FrustumSelectionSource(Frustum=pts, FieldType=field)
                fs.UpdateVTKObjects()
                sources[(scale, pos)] = fs
            conv = vtkSMSelectionHelper.ConvertSelectionSource(
                vtkSelectionNode.INDICES, fs.SMProxy, inp, 0)
            ids = _selection_ids(conv) if conv is not None else []
            if flats is not None:
                ids = _only_flats(ids, flats)
            sel_proxy = fs.SMProxy
            if src_id is not None and (inp.GetGlobalIDAsString() == src_id
                                       or inp.GetGlobalIDAsString() in crop_tips):
                # the composite holds EVERY block, the hidden ones too: only
                # the cells of the blocks this view draws are picked (the PO,
                # 15/10: through an extract, the whole grid behind it was)
                kept = [v for k in range(0, len(ids) - 2, 3) if ids[k] in allowed
                        for v in ids[k:k + 3]]
                if len(kept) != len(ids):
                    ids = kept
                    # the highlight too: the frustum would light the hidden
                    # blocks' cells
                    sel_proxy = (_svm.sources.CompositeDataIDSelectionSource(
                        IDs=ids, FieldType=field).SMProxy if ids else None)
            if ids and sel_proxy is not None:
                hits.append((r, sel_proxy, ids))
        return hits

    _RAYS_MAX = 10000   # rays cast at most for one rectangle

    def _drawn_leaves(pvv, vid):
        """[{rep, composite, scale, pos, leaves: [(flat, dataset)]}] of every
        display this view draws and lets a pick land on — of the shared
        source only the blocks the view draws (`_visible_flats`). Scale and
        Position are the display's, to bring a world ray back to the
        data."""
        from paraview import servermanager as _svm
        try:
            src_id = active_data_source.get_display_source().GetGlobalIDAsString()
            allowed = _visible_flats(vid)
            crop_tips = _crop_tips(vid)
        except Exception as exc:
            print(f"[fespp] surface pick: visible blocks ({vid}):", exc, flush=True)
            src_id, allowed, crop_tips = None, set(), set()

        def vec(rep, name, default):
            prop = rep.GetProperty(name)
            try:
                return [float(prop.GetElement(i)) for i in range(3)] if prop is not None else default
            except Exception as exc:
                print(f"[fespp] surface pick {name}:", exc, flush=True)
                return default

        out = []
        rp = pvv.SMProxy.GetProperty("Representations")
        for k in range(rp.GetNumberOfProxies()):
            r = rp.GetProxy(k)
            vis, pick, inp_p = (r.GetProperty("Visibility"), r.GetProperty("Pickable"),
                                r.GetProperty("Input"))
            if inp_p is None or inp_p.GetNumberOfProxies() == 0 or vis is None or not vis.GetElement(0):
                continue
            if pick is not None and not pick.GetElement(0):
                continue
            inp = inp_p.GetProxy(0)
            try:
                data = _svm._getPyProxy(inp).GetClientSideObject().GetOutputDataObject(0)
            except Exception as exc:
                print(f"[fespp] surface pick: display data ({vid}):", exc, flush=True)
                continue
            if data is None:
                continue
            composite = data.IsA("vtkCompositeDataSet")
            leaves = []
            if composite:
                # a cut scene keeps the source's blocks, the hidden ones too
                # (engine/blockscope/scene_crop)
                is_source = (inp.GetGlobalIDAsString() == src_id
                             or inp.GetGlobalIDAsString() in crop_tips)
                # the source's hidden blocks are not seen
                leaves = [(f, ds) for f, ds in assembly_index.leaves(data)
                          if (not is_source or f in allowed)
                          and ds.IsA("vtkDataSet") and ds.GetNumberOfCells()]
            elif data.IsA("vtkDataSet") and data.GetNumberOfCells():
                leaves.append((None, data))
            if not leaves:
                continue
            scale = [v or 1.0 for v in vec(r, "Scale", [1.0, 1.0, 1.0])]
            pos = vec(r, "Position", [0.0, 0.0, 0.0])
            out.append({"rep": r, "composite": composite, "scale": scale,
                        "pos": pos, "leaves": leaves})
        return out

    def _nothing_under(vid, pvv, region):
        """True when the click or the rectangle `region` (display pixels)
        covers nothing this view draws — known without a selection render or
        a walk through every cell of a grid (the manager, 16/10: a click in
        the void beside a big grid took 10 to 15 s, where the cursor's
        readout says at once that nothing is there). A click: the eye's ray
        through the pixel meets no cell (the cursor's cached locators) and
        passes no line or point within PICK_PX pixels. A rectangle: no drawn
        dataset's box reaches into it on screen. False whenever it cannot
        tell, so a doubt always goes to the real selection."""
        if _globe_scene(vid) is not None:
            return False
        from vtkmodules.vtkCommonCore import reference
        from fespp_on_trame.engine import ray_pick
        try:
            drawn = _drawn_leaves(pvv, vid)
            ren = pvv.GetRenderer()
        except Exception as exc:
            print(f"[fespp] pick pre-check ({vid}):", exc, flush=True)
            return False
        x0, y0, x1, y1 = region
        if x1 - x0 < 2 and y1 - y0 < 2:
            # the ray through the pixel, and the one through the next pixel:
            # how wide a pixel is, at any depth, for a line or a point
            rays = []
            for sx in (x0 + 0.5, x0 + 1.5):
                ends = []
                for z in (0.0, 1.0):
                    ren.SetDisplayPoint(sx, y0 + 0.5, z)
                    ren.DisplayToWorld()
                    w = list(ren.GetWorldPoint())
                    h = w[3] or 1.0
                    ends.append([w[0] / h, w[1] / h, w[2] / h])
                rays.append(ends)
            t, sub, cid = reference(0.0), reference(0), reference(-1)
            xpt, pc = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            for d in drawn:
                sc, pos = d["scale"], d["pos"]
                a, b, an, bn = ([(q[i] - pos[i]) / sc[i] for i in range(3)]
                                for q in (rays[0][0], rays[0][1], rays[1][0], rays[1][1]))
                u = [b[i] - a[i] for i in range(3)]
                px = ([an[i] - a[i] for i in range(3)],
                      [(bn[i] - an[i]) - u[i] for i in range(3)])
                for _f, ds in d["leaves"]:
                    if ray_pick.near_lines(ds, a, u, px, scale=sc) is not None:
                        return False
                    loc = _locator_for(ds, d["rep"].GetXMLName())
                    if loc is None or loc.IntersectWithLine(a, b, 1e-4, t, xpt, pc, sub, cid):
                        return False
            return True
        m = ray_pick.PICK_PX
        for d in drawn:
            sc, pos = d["scale"], d["pos"]
            for _f, ds in d["leaves"]:
                bb = ds.GetBounds()
                xs, ys = [], []
                for i in (0, 1):
                    for j in (2, 3):
                        for k in (4, 5):
                            ren.SetWorldPoint(bb[i] * sc[0] + pos[0], bb[j] * sc[1] + pos[1],
                                              bb[k] * sc[2] + pos[2], 1.0)
                            ren.WorldToDisplay()
                            dx, dy, dz = ren.GetDisplayPoint()
                            if not 0.0 <= dz <= 1.0:
                                # a corner outside the depth range (behind
                                # the eye): its box on screen means nothing
                                return False
                            xs.append(dx)
                            ys.append(dy)
                if (min(xs) - m <= x1 and max(xs) + m >= x0
                        and min(ys) - m <= y1 and max(ys) + m >= y0):
                    return False
        return True

    def _surface_fallback(pvv, region, vid):
        """(representation, selection source, ids) of a pick ON the visible
        surface, when the hardware selection gives nothing (the displays an
        isolate draws: the slicer's crops, a threshold, the NaN mask): rays
        are cast from the eye through the click, or through a grid of
        points over the rectangle (at most _RAYS_MAX), and each keeps the
        FIRST cell it meets among the displays the view draws — the cell
        the eye sees there (the cursor's cached cell locators, in each
        display's data coordinates: its Scale and Position undone)."""
        import math
        from paraview import servermanager as _svm
        from vtkmodules.vtkCommonCore import reference
        # the displays the view draws, each with its datasets and locators
        targets = []
        for d in _drawn_leaves(pvv, vid):
            r = d["rep"]
            locs = [(f, _locator_for(ds, r.GetXMLName())) for f, ds in d["leaves"]]
            targets.append({"rep": r, "composite": d["composite"], "scale": d["scale"],
                            "pos": d["pos"],
                            "locs": [(f, loc) for f, loc in locs if loc is not None],
                            "hits": set()})
        if not targets:
            return None, None, []

        x0, y0, x1, y1 = region
        if x1 - x0 < 2 and y1 - y0 < 2:
            samples = [(x0 + 0.5, y0 + 0.5)]
        else:
            step = max(1.0, math.sqrt(max(1, (x1 - x0) * (y1 - y0)) / _RAYS_MAX))
            xs = [x0 + 0.5 + i * step for i in range(int((x1 - x0) / step) + 1)]
            ys = [y0 + 0.5 + j * step for j in range(int((y1 - y0) / step) + 1)]
            samples = [(x, y) for x in xs for y in ys]
        ren = pvv.GetRenderer()
        t, sub, cid = reference(0.0), reference(0), reference(-1)
        xpt, pc = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        for sx, sy in samples:
            ends = []
            for z in (0.0, 1.0):
                ren.SetDisplayPoint(sx, sy, z)
                ren.DisplayToWorld()
                w = list(ren.GetWorldPoint())
                h = w[3] or 1.0
                ends.append([w[0] / h, w[1] / h, w[2] / h])
            best = None
            for tg in targets:
                a = [(ends[0][i] - tg["pos"][i]) / tg["scale"][i] for i in range(3)]
                b = [(ends[1][i] - tg["pos"][i]) / tg["scale"][i] for i in range(3)]
                for f, loc in tg["locs"]:
                    if loc.IntersectWithLine(a, b, 0.0, t, xpt, pc, sub, cid) and int(cid) >= 0:
                        # t runs along the same eye ray for every display
                        if best is None or float(t) < best[0]:
                            best = (float(t), tg, f, int(cid))
            if best is not None:
                best[1]["hits"].add((best[2], best[3]))
        tg = max(targets, key=lambda x: len(x["hits"]))
        if not tg["hits"]:
            return None, None, []
        kept = []
        for f, c in sorted(tg["hits"], key=lambda fc: (fc[0] or 0, fc[1])):
            kept += [f, 0, c] if tg["composite"] else [0, c]
        src = (_svm.sources.CompositeDataIDSelectionSource(IDs=kept, FieldType="CELL") if tg["composite"]
               else _svm.sources.IDSelectionSource(IDs=kept, FieldType="CELL"))
        return tg["rep"], src.SMProxy, kept

    def _visible_flats(vid):
        """The source's flat indices of the blocks this view DRAWS from the
        composite: visible, and not given up to an isolate or an extract."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is None:
            return set()
        out = set()
        for sel in scene.shown_selectors() - set(scene.isolated):
            out.update(ctx.assembly_index.flat_indices(sel))
        return out

    def _crop_tips(vid):
        """The global ids of what a cut scene draws in `vid` (the Geometry
        slicer on the scene, engine/blockscope/scene_crop): the source's
        blocks, cut — a pick there is a pick on the source."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        try:
            return scene.crop_tip_ids() if scene is not None else set()
        except Exception as exc:
            print(f"[fespp] pick: the scene's cut ({vid}):", exc, flush=True)
            return set()

    def _crop_to_source(vid, inp, ids):
        """[flat, proc, cell, …] picked on the cut scene, as the source's:
        each cut cell carries its source cell (vtkOriginalCellIds), the
        blocks keep the source's flat indices (SceneCrop.source_flat)."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        crop = getattr(scene, "crop", None)
        from paraview import servermanager as _svm
        try:
            data = _svm._getPyProxy(inp).GetClientSideObject().GetOutputDataObject(0)
        except Exception as exc:
            print("[fespp] pick on the cut scene:", exc, flush=True)
            return ids
        if data is None or not data.IsA("vtkCompositeDataSet"):
            return ids
        leaves = dict(assembly_index.leaves(data))
        out = []
        for k in range(0, len(ids) - 2, 3):
            f, c = ids[k], ids[k + 2]
            leaf = leaves.get(f)
            orig = leaf.GetCellData().GetArray("vtkOriginalCellIds") if leaf is not None else None
            sf = crop.source_flat(f, ctx.assembly_index) if crop is not None else None
            if orig is None or sf is None or not (0 <= c < orig.GetNumberOfTuples()):
                continue
            out += [sf, 0, int(orig.GetValue(c))]
        # a cell cut into pieces is picked once
        seen, uniq = set(), []
        for k in range(0, len(out), 3):
            key = (out[k], out[k + 2])
            if key not in seen:
                seen.add(key)
                uniq += out[k:k + 3]
        return uniq

    def _ids_to_source(vid, rep_sm, ids):
        """[flat, proc, cell, …] picked on a display's input, as the SOURCE's:
        a selection extract's cells are the grid's cells (vtkOriginalCellIds),
        so a pick on it selects, counts and offers "+" on the grid itself.
        Ids picked on the source itself come back as they are. Returns
        (ids, the extract they were picked on or None)."""
        inp = rep_sm.GetProperty("Input").GetProxy(0) if rep_sm is not None else None
        if inp is None or not ids:
            return ids, None
        gid = inp.GetGlobalIDAsString()
        try:
            if gid == active_data_source.get_display_source().GetGlobalIDAsString():
                return ids, None
        except Exception as exc:
            print(f"[fespp] pick: source id ({vid}):", exc, flush=True)
        if gid in _crop_tips(vid):
            return _crop_to_source(vid, inp, ids), None
        # what a feature draws in the place of the source's blocks says which
        # of the source's cells its own stand for (`ctx.pick_twins`: [(view,
        # the proxy's global id, ids) -> ids as the source's, None when the
        # proxy is not its])
        for as_source in getattr(ctx, "pick_twins", None) or ():
            mine = as_source(vid, gid, ids)
            if mine is not None:
                return mine, None
        e = next((x for elist in _extracts.values() for x in elist
                  if x.get("ex") is not None and x["ex"].SMProxy.GetGlobalIDAsString() == gid), None)
        if e is not None:
            return _extract_to_source(e, ids), e
        # a display of a grid's isolate (the slicer's crops, a threshold —
        # the assistant's "keep only these cells" —, the NaN mask): its
        # cells are renumbered, so each is found in the grid by where it is
        # (the PO, 15/10: after "keep only", picking selected nothing)
        return _ids_by_location(vid, inp, ids), None

    _LOCATE_CAP = 200000   # picked cells located one by one at most

    def _ids_by_location(vid, inp, ids):
        """[flat, proc, cell, …] of the source grid for cells picked on a
        display derived from it (crop, threshold, mask): each picked cell's
        centre is looked up in the grids isolated in this view (the
        cursor's cached cell locators). Ids found nowhere are dropped."""
        from paraview import servermanager as _svm
        from vtkmodules.util.numpy_support import vtk_to_numpy
        isos = [rp for (ivid, rp) in list((getattr(ctx, "grid_isolates", None) or {})) if ivid == vid]
        if not isos or not ids:
            return ids
        try:
            data = _svm._getPyProxy(inp).GetClientSideObject().GetOutputDataObject(0)
        except Exception as exc:
            print(f"[fespp] pick on a derived display ({vid}):", exc, flush=True)
            return ids
        if data is None:
            return ids
        picked = []
        if data.IsA("vtkCompositeDataSet"):
            leaves = dict(assembly_index.leaves(data, skip_empty=False))
            for k in range(0, len(ids) - 2, 3):
                ds = leaves.get(ids[k])
                if ds is not None:
                    picked.append((ds, ids[k + 2]))
        else:
            # a plain dataset's ids come as [process, cell] pairs
            for k in range(0, len(ids) - 1, 2):
                picked.append((data, ids[k + 1]))
        if len(picked) > _LOCATE_CAP:
            print(f"[fespp] pick: {len(picked)} cells, only the first {_LOCATE_CAP} located",
                  flush=True)
            picked = picked[:_LOCATE_CAP]
        for rp in isos:
            grids = [(f, g) for g, f in ctx.assembly_index.datasets(rp, subtree=False)]
            grids = [(f, g, _locator_for(g, rp)) for f, g in grids if g is not None]
            out = []
            for ds, c in picked:
                if not (0 <= c < ds.GetNumberOfCells()):
                    continue
                pts = ds.GetCell(int(c)).GetPoints()
                if pts is None or pts.GetNumberOfPoints() == 0:
                    continue
                centre = vtk_to_numpy(pts.GetData()).astype(float).mean(axis=0).tolist()
                for f, _g, loc in grids:
                    gc = loc.FindCell(centre) if loc is not None else -1
                    if gc >= 0:
                        out += [f, 0, int(gc)]
                        break
            if out:
                return out
        return []

    def _extract_leaves(e):
        """({extract flat: leaf}, {extract flat: source flat}) of an extract."""
        out_pdc = e["ex"].GetClientSideObject().GetOutputDataObject(0)
        ex_flats = _pdc_flats(out_pdc, e["rep_path"])
        src_flats = ctx.assembly_index.flat_indices(e["rep_path"], subtree=False)
        to_src = dict(zip(ex_flats, src_flats)) if len(ex_flats) == len(src_flats) else {}
        return dict(assembly_index.leaves(out_pdc, skip_empty=False)), to_src

    def _extract_cells(e):
        """{source flat: numpy array of the grid's cell ids} an extract
        holds — numpy, an extract can hold most of a large grid."""
        from vtkmodules.util.numpy_support import vtk_to_numpy
        leaves, to_src = _extract_leaves(e)
        out = {}
        for f, leaf in leaves.items():
            orig = leaf.GetCellData().GetArray("vtkOriginalCellIds") if leaf is not None else None
            sf = to_src.get(f)
            if orig is not None and sf is not None:
                out[sf] = vtk_to_numpy(orig).astype("int64")
        return out

    def _extract_to_source(e, ids):
        """An extract's [flat, proc, cell, …] as the source grid's."""
        leaves, to_src = _extract_leaves(e)
        out = []
        for k in range(0, len(ids) - 2, 3):
            f, c = ids[k], ids[k + 2]
            leaf, sf = leaves.get(f), to_src.get(f)
            orig = leaf.GetCellData().GetArray("vtkOriginalCellIds") if leaf is not None else None
            if orig is None or sf is None or not (0 <= c < orig.GetNumberOfTuples()):
                continue
            out += [sf, 0, int(orig.GetValue(c))]
        return out

    @controller.set("view_pick")
    def view_pick(ev, view_id, mode="surface"):
        """Hand / frustum modes: select the cells under a click or a rubber
        band — ON the visible surface (hand) or THROUGH the volume (frustum,
        hidden cells included) — keep them highlighted (selection on the
        source) and ACTIVATE the node holding most of them in this view's
        tree (Attributes / Colormap follow). Feedback text: node, cell id
        or count, value or range of the array colouring that node."""
        flag = "ui_frustum_mode__" if mode == "frustum" else "ui_pick_mode__"
        if not getattr(state, f"{flag}{view_id}", False) or _globe_scene(str(view_id)) is not None:
            return
        mv = _mv()
        pvv = mv.get_pv_view(view_id) if mv is not None else None
        if pvv is None or not ev or len(ev) < 6:
            return
        try:
            from vtkmodules.vtkCommonCore import vtkCollection
            from paraview import servermanager as _svm
            region = _pick_region(ev, pvv)
            # every representation the gesture hits: a rectangle can span a
            # grid's extract and the wellbore the composite draws
            hits = []
            t_pre = time.perf_counter()
            if _nothing_under(str(view_id), pvv, region):
                # nothing drawn there: said at once, without the selection
                # render or the walk through every cell that would find it out
                print(f"[fespp] pick view={view_id}: nothing under the pointer"
                      f" ({(time.perf_counter() - t_pre) * 1000:.0f} ms)",
                      file=sys.stderr, flush=True)
            elif mode == "frustum":
                hits = _frustum_pick(pvv, region, str(view_id))
            else:
                reps, srcs = vtkCollection(), vtkCollection()
                ok = pvv.SMProxy.SelectSurfaceCells(region, reps, srcs, False, 0, False)
                if ok:
                    for i in range(min(reps.GetNumberOfItems(), srcs.GetNumberOfItems())):
                        s_i = srcs.GetItemAsObject(i)
                        hits.append((reps.GetItemAsObject(i), s_i, _selection_ids(s_i)))
                if not hits:
                    # ParaView's hardware selection maps nothing back on the
                    # displays an isolate draws (the slicer's crops, a
                    # threshold, the NaN mask): picked through the volume,
                    # then only the cells the eye SEES are kept (the PO,
                    # 15/10: picking must work on thresholds, slices…)
                    r_f, s_f, ids_f = _surface_fallback(pvv, region, str(view_id))
                    if s_f is not None:
                        hits = [(r_f, s_f, ids_f)]
            # a point set is picked by its points, not as its one cell
            hits = _with_points(pvv, region, mode, str(view_id), hits)
            hit = bool(hits)
            print(f"[fespp] pick view={view_id} mode={mode} region={region} hit={hit}",
                  file=sys.stderr, flush=True)
            if not hit:
                # nothing hit: this view's selection goes, another view's stays
                if _clear_selection_of(str(view_id)):
                    _drop_block_highlight()
                # the navigation card must not keep offering "centre on the
                # pick" when the pick just became nothing
                selection.drop(str(view_id))
                _drop_sel_inputs(str(view_id))
                _clear_extract_highlights(str(view_id))
                _publish_sel_counts(str(view_id))
                state[f"ui_nav_has_pick__{view_id}"] = False
                state[f"ui_pick_info__{view_id}"] = "(no cell selected)"
                _refresh_values(str(view_id))
                scheduler.mark_dirty(view_id)
                scheduler.flush()
                return
            # highlight: each hit's selection source becomes its input's
            # selection (a previous one on the source or an extract goes)
            _drop_block_highlight()   # the pick owns the ONE selection channel
            _clear_extract_highlights(str(view_id))
            _drop_sel_inputs(str(view_id))
            src_gid = active_data_source.get_display_source().GetGlobalIDAsString()
            try:
                pvsimple.ClearSelection(_svm._getPyProxy(active_data_source.get_display_source()))
            except Exception as exc:
                print(f"[fespp] pick: clear the source's selection ({view_id}):", exc, flush=True)
            by_flat, origins, point_flats = {}, [], set()
            picked_on = {}    # rep path -> the name of the extract picked on
            for rep_i, sel_i, ids_i, pts_i in hits:
                inp_i = rep_i.GetProperty("Input").GetProxy(0)
                if pts_i:
                    # cells and a point set's points: ParaView's appended
                    # selection (app/scene/selection_sources)
                    selection_sources.set_on(inp_i, ids_i, pts_i)
                    for k in range(0, len(pts_i) - 2, 3):
                        by_flat.setdefault(pts_i[k], set()).add(pts_i[k + 2])
                        point_flats.add(pts_i[k])
                else:
                    inp_i.SetSelectionInput(0, sel_i, 0)
                # the view's own proxies only (an isolate's, an extract): the
                # shared source's selection has its owner (_own_selection)
                if inp_i.GetGlobalIDAsString() != src_gid:
                    selection.add_input(str(view_id), inp_i)
                # picked on a selection extract: the grid's own cells, and
                # the extract remembered (its Keep / Remove then works FROM it)
                ids_i, origin_i = _ids_to_source(str(view_id), rep_i, ids_i)
                if origin_i is not None:
                    origins.append((len(ids_i), origin_i["id"]))
                    picked_on[origin_i.get("rep_path")] = origin_i.get("title")
                for k in range(0, len(ids_i) - 2, 3):
                    by_flat.setdefault(ids_i[k], set()).add(ids_i[k + 2])
            # the selection is this view's now, drawn here only
            _own_selection(str(view_id))
            by_flat = {f: sorted(c) for f, c in by_flat.items()}
            rep_sm = hits[0][0]
            inp = rep_sm.GetProperty("Input").GetProxy(0)
            info = ""
            # remember it: the navigation card centres / frames on THIS
            selection.hold(str(view_id), by_flat, pick=True,
                           origin=max(origins)[1] if origins else None,
                           points=point_flats)
            _publish_sel_counts(str(view_id))
            state[f"ui_nav_has_pick__{view_id}"] = bool(by_flat)
            if by_flat:
                total = sum(len(c) for c in by_flat.values())
                flat = max(by_flat, key=lambda f: len(by_flat[f]))
                cells = by_flat[flat]
                path = _path_for_flat_index(flat)
                if path:
                    # tree activation = the rep node (properties are children)
                    rep_path = _rep_path_of(path) or path
                    activation.activate(view_id, rep_path)
                    # picked on an extract: the extract's name (the PO, 21/10)
                    title = picked_on.get(rep_path) or _display_title(
                        rep_path,
                        rep_path.split("/_propsfolder_", 1)[0].rsplit("/", 1)[-1])
                    # the readout follows the UI charter: the property by its
                    # display name (title, component, unit: the colour
                    # bar's own text, never the VTK array name), the cell by
                    # its index and, on an IJK grid, its I J K
                    ds = None
                    try:
                        ds = _leaf_dataset(flat)
                    except Exception:
                        ds = None
                    # a point set's ids are its points
                    word = "point" if flat in point_flats else "cell"
                    if total == 1:
                        info = f"{title}  {word} #{cells[0]}"
                        ijk = _cell_ijk(ds, cells[0]) if word == "cell" else None
                        if ijk:
                            info += f"  I {ijk[0]} J {ijk[1]} K {ijk[2]}"
                    else:
                        info = f"{title}  {len(cells)} {word}s"
                        if len(by_flat) > 1:
                            info += f"  ({total} in {len(by_flat)} blocks)"
                    try:
                        sel = rep_path
                        value = _cell_value_text(view_id, sel, ds, cells, path=path,
                                                 points=word == "point")
                        if value:
                            info += f"  {value}"
                    except Exception as exc:
                        print(f"[fespp] pick value ({view_id}):", exc, flush=True)
            else:
                # no ids to attribute: count the extracted cells
                n = inp.GetSelectionOutput(0).GetDataInformation().GetNumberOfCells()
                info = f"{numfmt.fmt_int(n)} cells selected"
            state[f"ui_pick_info__{view_id}"] = info
            print(f"[fespp] pick result ({view_id}): {info or '(no id)'} —"
                  f" {sum(len(c) for c in by_flat.values())} grid cell(s)"
                  f"{' via ' + rep_sm.GetXMLName() if rep_sm is not None else ''}",
                  file=sys.stderr, flush=True)
            # the Attributes card marks the selected rows, or keeps only them
            _refresh_values(str(view_id))
        except Exception as exc:
            print(f"[fespp] pick error ({view_id}): {exc!r}", file=sys.stderr, flush=True)
            return
        scheduler.mark_dirty(view_id)
        scheduler.flush()

    def _cell_nodes(ds, cells, near=None):
        """The nodes a NODE property is read at for `cells` of `ds`: the one
        nearest `near` (the point under the pointer, data space) when there
        is one cell and a point, every node of the cells otherwise."""
        from vtkmodules.vtkCommonCore import vtkIdList
        out = []
        idl = vtkIdList()
        for c in cells:
            ds.GetCellPoints(c, idl)
            out.extend(idl.GetId(k) for k in range(idl.GetNumberOfIds()))
        if near is not None and len(cells) == 1 and out:
            def _d2(i):
                p = ds.GetPoint(i)
                return sum((p[k] - near[k]) ** 2 for k in range(3))
            return [min(out, key=_d2)]
        return sorted(set(out))

    def _cell_value_text(view_id, sel, ds, cells, path="", near=None, points=False):
        """What the property colouring block `sel` in this view says on
        `cells` of `ds`: "Total Porosity = 0.231 m3/m3" for one cell, "… ∈
        [a, b] m3/m3" for several, the category's name for a categorical
        property; "" when the block is drawn in one colour.

        The property goes by the colour bar's own name, and the unit comes
        once, after the number it qualifies (never "Total Porosity (m3/m3)
        = 0.23 m3/m3"). A number without its unit is not a measurement: 0.23
        of what, 2150 in metres or in feet? The plugin sets `uom` on every
        non-partial property node, so it is one attribute away. A property
        on the NODES (a log along its frame, a surface's) is read at the
        node of the cell nearest `near`, or over every node of the cells.
        `points`: the ids are a point set's points, read as they are."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        entry = scene.block_state.get(sel) if scene is not None else None
        name = entry.color_array if entry is not None else ""
        if ds is None or not name:
            return ""
        n_ids = ds.GetNumberOfPoints() if points else ds.GetNumberOfCells()
        ids = [c for c in cells if 0 <= c < n_ids]
        arr = None if points else ds.GetCellData().GetArray(name)
        if arr is None:
            arr = ds.GetPointData().GetArray(name)
            if arr is None:
                return ""
            if not points:
                ids = _cell_nodes(ds, ids, near)
            # a log drawn by the plugin's filter: a station of its trajectory is drawing only, its nearest sample is read
            from fespp_on_trame.engine import log_track as _log_track
            ids = [_log_track.real_point(ds, i) for i in ids]
        n = arr.GetNumberOfTuples()
        ids = [i for i in ids if 0 <= i < n]
        if not ids:
            return ""
        from fespp_on_trame.engine import property_values as _pv
        array_path = _cmap_array_path(view_id, path or sel)
        label, uom = (_pv.name_and_unit(state, tree, array_path, fallback=name)
                      if array_path else ("", ""))
        label = label or entry.label or name
        unit = f" {uom}" if uom and uom != "Euc" else ""
        comp = 0
        if arr.GetNumberOfComponents() > 1:
            # the component the view reads, as the bar does
            c = _pv.component_choice(state, array_path)
            comp = int(c) if isinstance(c, int) and c >= 0 else -1

        def _val(i):
            if comp < 0:
                return float(sum(x * x for x in arr.GetTuple(i))) ** 0.5
            return arr.GetComponent(i, comp)

        vals = [_val(i) for i in ids]
        # a categorical property names its code, as its legend does
        names = {}
        for c in (entry.categories or []):
            try:
                names[float(c.get("code"))] = str(c.get("label") or "")
            except (TypeError, ValueError, AttributeError):
                continue
        if len(vals) == 1 or min(vals) == max(vals):
            v = vals[0]
            word = names.get(float(v))
            if word and word != numfmt.fmt_int(v):
                return f"{label} = {word} (code {numfmt.fmt_int(v)})"
            return f"{label} = {numfmt.fmt(v)}{unit}"
        return f"{label} ∈ [{numfmt.fmt(min(vals))}, {numfmt.fmt(max(vals))}]{unit}"

    def _wellbore_title(path):
        """The wellbore a trajectory, a log or a marker belongs to — its
        title in the tree — or "" for anything that is not a well's."""
        nid = tree.find_node_id(path) if path else None
        if nid is None:
            return ""
        wid = tree.find_parent_node_id_with_type(nid, "Wellbore")
        return (tree.find_title(wid) or "") if wid is not None else ""
    return (_cell_ijk, _cell_value_text, _extract_cells, _ids_to_source, _nothing_under, _surface_fallback, _wellbore_title)
