"""One cell locator per dataset the crosshair may hit, keyed by the
dataset's address: (mtime, locator). Built once, reused for every
sample, dropped when the dataset changes under it.

(Moved out of app/boot, overhaul slice 10.)"""
import time
from paraview import simple as pvsimple
from fespp_on_trame.engine.blockscope import assembly_index
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.engine.state_defaults import z_scale_of


def register(core, *, _cell_ijk, _cell_value_text, _display_title,
             _display_xy, _globe_scene, _rep_path_of, _wellbore_title):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_cursor_pos, _locator_for)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    lifecycle = core.lifecycle
    _mv = core.mv
    _extracts = core.selection.extracts
    # One cell locator per dataset the crosshair may hit, keyed by the
    # dataset's address: (mtime, locator). Built once, reused for every
    # sample, dropped when the dataset changes under it.
    ctx.cursor_locators = {}

    @lifecycle.on("new_data")
    def _new_data_locators():
        """A locator holds its dataset: kept past a new assembly, it would
        keep the last file's grids alive (02-carte M6)."""
        ctx.cursor_locators.clear()

    def _leaf_datasets(obj):
        """Every leaf dataset of `obj` — the object itself when it is one."""
        if obj is None:
            return
        if obj.IsA("vtkCompositeDataSet"):
            for _flat, ds in assembly_index.leaves(obj):
                yield ds
        elif obj.IsA("vtkDataSet"):
            yield obj

    def _locator_for(ds, what):
        """The cached vtkStaticCellLocator of `ds`, built on first use.

        Built once per dataset and kept: the build takes a fraction of a
        second on a grid of about a million cells, then a query costs
        microseconds, orders of magnitude below a hardware-selection
        render. The build is logged, once, so a first hover that hesitates
        is explained."""
        if ds is None or ds.GetNumberOfCells() == 0:
            return None
        key = ds.GetAddressAsString("vtkDataObject")
        mtime = ds.GetMTime()
        hit = ctx.cursor_locators.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        t0 = time.perf_counter()
        loc = _fresh_locator(ds)
        ctx.cursor_locators[key] = (mtime, loc)
        print(f"[fespp] cursor: cell locator built for {what}"
              f" ({ds.GetNumberOfCells()} cells) in"
              f" {(time.perf_counter() - t0) * 1000:.0f} ms", flush=True)
        return loc

    def _fresh_locator(ds):
        """A vtkStaticCellLocator of `ds`, built now and kept by no one."""
        from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator
        if ds is None or ds.GetNumberOfCells() == 0:
            return None
        loc = vtkStaticCellLocator()
        loc.SetDataSet(ds)
        loc.BuildLocator()
        return loc

    def _rep_path_of_selector(sel):
        """The loaded rep path whose selector is `sel`, or ""."""
        for p in (state.ui_loaded_rep_paths or []):
            if p == sel:
                return p
        return ""

    def _shown_datasets(view_id, pvv, scene):
        """[(dataset, block title, selector, rep path)] for everything this
        view draws.

        The composite's visible blocks, and for an isolated block the
        proxies its isolate has visible right now (crops, volumes, threshold
        tips) and its visible selection extracts, so the crosshair reports
        what is on screen and not a cell a threshold has hidden. The rep path is "" for a block that is no
        loaded rep (a log channel, its own block). A dataset several shown rows
        hold (a wellbore, its folder, the log itself) is listed once, under the
        deepest: the row that says what it is."""
        out = []
        if scene is None:
            return out
        isolated = set(getattr(scene, "isolated", ()) or ())
        for sel in sorted(scene.shown_selectors()):
            path = _rep_path_of_selector(sel)
            short = sel.rsplit("/", 1)[-1]
            title = _display_title(_rep_path_of(path) or path or sel, short)
            if sel in isolated:
                for (ivid, ipath), iso in list(
                        (getattr(ctx, "grid_isolates", None) or {}).items()):
                    if ivid != view_id:
                        continue
                    if ipath != sel:
                        continue
                    for proxy in iso.colourable_sources():
                        try:
                            disp = pvsimple.GetRepresentation(proxy=proxy, view=pvv)
                            if not int(getattr(disp, "Visibility", 0) or 0):
                                continue
                            for ds in _leaf_datasets(
                                    proxy.GetClientSideObject().GetOutputDataObject(0)):
                                out.append((ds, title, sel, path))
                        except Exception as exc:
                            print(f"[fespp] cursor: isolate display unreadable"
                                  f" ({view_id}):", exc, flush=True)
                # a visible selection extract drawn in the grid's place: the
                # crosshair reads its cells, not the grid hidden behind (D12)
                for e in list(_extracts.get(view_id) or []):
                    if not e.get("visible") or e.get("selector") != sel:
                        continue
                    try:
                        # named by its own name, not its grid's (the PO, 21/10)
                        for ds in _leaf_datasets(
                                e["ex"].GetClientSideObject().GetOutputDataObject(0)):
                            out.append((ds, e.get("title") or title, sel, path))
                    except Exception as exc:
                        print(f"[fespp] cursor: extract unreadable ({view_id}):",
                              exc, flush=True)
                # what a feature draws in the block's place (`ctx.
                # block_stand_ins`: [(view, selector) -> [dataset]]) is met
                # and worded as the block itself
                for stand_in in getattr(ctx, "block_stand_ins", None) or ():
                    for ds in stand_in(view_id, sel):
                        out.append((ds, title, sel, path))
                continue
            for ds, _flat in ctx.assembly_index.datasets(sel):
                out.append((ds, title, sel, path))
        deepest = {}
        for row in out:
            held = deepest.get(id(row[0]))
            if held is None or len(row[2]) > len(held[2]):
                deepest[id(row[0])] = row
        return list(deepest.values())

    @controller.set("cursor_hit")
    def cursor_hit(view_id, x, y):
        """The DATA-space point under display pixel (x, y) and the block it
        is on, as ((px, py, pz), title), or (None, "") over nothing."""
        hit = _cursor_target(view_id, x, y)
        return (hit["point"], hit["title"]) if hit else (None, "")

    def _cursor_target(view_id, x, y):
        """What is under display pixel (x, y): {point (DATA space), title,
        ds, cell, sel, path} of the nearest drawn block, or None.

        A camera ray met with cell locators, never a hardware selection.
        `ConvertDisplayToPointOnSurface` reads as a ray cast but runs a
        selection render, far too slow to run on every pointer move: the
        single-threaded server falls behind the client's samples and
        delivers no frame while it tries, so the crosshair stutters. The ray
        costs microseconds and touches no render.

        Data space, not world: the composite draws with Scale = [1, 1, zs],
        so the world ray is brought back by dividing its Z, and the hit is
        the data's own elevation with nothing left to divide."""
        from vtkmodules.vtkCommonCore import reference
        from fespp_on_trame.app.views import camera as _camera
        from fespp_on_trame.engine import ray_pick
        mv = _mv()
        pvv = mv.get_pv_view(view_id) if mv is not None else None
        if pvv is None:
            return None
        ray = _camera.view_ray(pvv, x, y)
        if not ray:
            return None
        zs = z_scale_of(state, view_id)
        near, d = ray
        p1 = [near[0], near[1], near[2] / zs]
        p2 = [near[0] + d[0], near[1] + d[1], (near[2] + d[2]) / zs]
        # the ray one pixel to the right: how wide a pixel is, at any depth,
        # for what has no width of its own (below)
        ray_b = _camera.view_ray(pvv, x + 1, y)
        px = None
        if ray_b:
            nb, db = ray_b
            px = ([nb[0] - near[0], nb[1] - near[1], (nb[2] - near[2]) / zs],
                  [db[0] - d[0], db[1] - d[1], (db[2] - d[2]) / zs])
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        t = reference(0.0)
        sub = reference(0)
        cid = reference(0)
        xh = [0.0, 0.0, 0.0]
        pc = [0.0, 0.0, 0.0]
        u = [p2[k] - p1[k] for k in range(3)]
        targets = list(_shown_datasets(view_id, pvv, scene))
        # what a feature draws on its own (the time-depth model's columns,
        # app/features/time_depth_pins): its geometry meets the ray too, and
        # its own line says what it is (`ctx.cursor_probes`: [(targets(vid)
        # -> [(dataset, title)], line(vid, point, hit) -> text)])
        for probe_targets, _line in getattr(ctx, "cursor_probes", None) or ():
            targets += [(ds, title, None, None) for ds, title in probe_targets(view_id)]
        # the nearest hit on the blocks, and on the features' own geometry
        near = {"block": [None, None], "feature": [None, None]}
        for ds, title, sel, path in targets:
            slot = near["block" if sel is not None else "feature"]
            # a feature's own geometry is made anew at each edit: located
            # afresh (a few thousand cells), never kept in the cache
            loc = _locator_for(ds, title) if sel is not None else _fresh_locator(ds)
            if loc is None:
                continue
            if loc.IntersectWithLine(p1, p2, 1e-4, t, xh, pc, sub, cid):
                tv = float(t.get())
                if slot[0] is None or tv < slot[0]:
                    slot[:] = [tv, {"point": list(xh), "title": title, "ds": ds,
                                    "cell": int(cid.get()), "sel": sel, "path": path}]
            # A trajectory has no width: it is drawn as lines, and a ray from
            # a pixel never meets a line within the locator's tolerance
            # (0.1 mm). Lines and points are met within PICK_PX pixels of
            # the pointer, measured at their own depth and as drawn, the Z
            # exaggeration in (engine/ray_pick).
            if px is not None:
                hit = ray_pick.near_lines(ds, p1, u, px, scale=(1.0, 1.0, zs))
                if hit is not None and (slot[0] is None or hit[0] < slot[0]):
                    slot[:] = [hit[0], {"point": hit[1], "title": title, "ds": ds,
                                        "cell": hit[2], "sel": sel, "path": path}]
        (bt, best), (ft, feat) = near["block"], near["feature"]
        # a feature's line behind a see-through block (the model's columns
        # inside its velocity model at a lowered opacity) is what the reader looks at
        if feat is not None and (best is None or ft <= bt or _see_through(scene, best.get("sel"))):
            return feat
        return best

    def _see_through(scene, sel):
        """The block `sel` is drawn below full opacity in the scene."""
        entry = scene.block_state.get(sel) if scene is not None and sel else None
        op = entry.drawn_opacity() if entry is not None else None
        return op is not None and float(op) < 0.999

    def _cursor_what(view_id, hit):
        """The second and third lines of the readout: what the pointer is on
        and what the property colouring it says there, with its unit.

        What it is on: the block; the wellbore of a trajectory, a log or a
        marker (a block title such as "Drilled trajectory" alone does not
        say which well); the cell and its I J K on a grid."""
        if hit.get("sel") is None:
            return ""       # a feature's own geometry: its probe line says it
        node_path = hit.get("path") or hit.get("sel") or ""
        what = hit.get("title") or ""
        well = _wellbore_title(node_path)
        if well:
            what = f"wellbore {well}" + (f"  ·  {what}" if what and what != well else "")
        ds, cell = hit.get("ds"), hit.get("cell")
        ijk = _cell_ijk(ds, cell) if (ds is not None and cell is not None) else None
        if ijk:
            what += f"   cell I {ijk[0]} J {ijk[1]} K {ijk[2]}"
        value = ""
        try:
            value = _cell_value_text(view_id, hit.get("sel") or node_path, ds,
                                     [cell] if cell is not None else [],
                                     path=hit.get("path") or "", near=hit.get("point"))
        except Exception as exc:
            print(f"[fespp] cursor value ({view_id}):", exc, flush=True)
        return "\n".join(x for x in (what, value) if x)

    def _cursor_pos(view_id, ev):
        """Crosshair mode: world position of the surface under the cursor,
        named with the axis names the FILE gives them, the vertical as the
        ELEVATION it is in VTK, and the block the pointer is on."""
        mv = _mv()
        pvv = mv.get_pv_view(view_id) if mv is not None else None
        if pvv is None or not ev:
            return ""
        try:
            from fespp_on_trame.app.views import camera as _camera
            from fespp_on_trame.engine import geo
            x, y = _display_xy(ev, pvv)
            if _globe_scene(view_id) is not None:
                # On the Earth, a ray and a closed form, never a pick.
                # `ConvertDisplayToPointOnSurface` reads as a ray cast, but in
                # ParaView it runs a hardware surface selection, and on a Globe
                # scene that call never returns (on the GPU and in software
                # alike): the crosshair would freeze the whole session, with
                # no readout, no frames, no state. The depth buffer is no way
                # out either: at these ranges it reads back crushed against
                # the far plane, and outside a render it is not even the
                # current frame.
                #
                # So the pixel is unprojected into a world ray from the camera
                # alone, and met with the WGS84 ellipsoid in closed form. It
                # cannot hang and it costs a square root. What it answers is
                # the point on the ground under the pointer, not the point on
                # the data drawn above or below it, and it says so rather
                # than print a height it did not measure.
                ray = _camera.view_ray(pvv, x, y)
                pt = geo.ellipsoid_hit(*ray) if ray else None
                if pt is None:      # off the limb: the pointer is on no Earth
                    return ""
                lon, lat, _h = geo.geodetic_of(*pt)
                return (f"lat {numfmt.fmt_fixed(lat, 5)}°   lon {numfmt.fmt_fixed(lon, 5)}°"
                        f"   on the WGS84 ellipsoid (ground, not the data)")
            # A plain 3D view: a camera ray met with the drawn blocks' cell
            # locators (`_cursor_target`), the point on the data and the
            # block in one query of a few microseconds. The point comes back
            # in data space: the Z exaggeration is undone on the ray, so the
            # elevation is the data's own and is not divided again.
            hit = _cursor_target(view_id, x, y)
            if hit is None:
                return ""       # the pointer is over nothing
            pt = hit["point"]
            # The ordinates carry the names the FILE gives them (RESQML's
            # ProjectedAxisOrder), the EPSG registry's second, X/Y last.
            # The vertical is an ELEVATION whatever the file calls it: VTK
            # has no other, so a depth was negated on the way in, and a bare
            # "Z" would leave the reader to guess which way it grows.
            # In a view switched to time (app/features/view_domain) the
            # vertical is the time of the time CRS, read the way the file
            # counts it (downwards: the plugin negated it on the way in).
            crs = ctx.view_crs(view_id)
            nx, ny, _src = geo.axis_names_of(crs)
            if crs and crs.get("time"):
                t = -pt[2] if crs.get("depth") else pt[2]
                unit = (crs.get("time_unit") or "").strip()
                vertical = f"time {numfmt.fmt_fixed(t, 2)}" + (f" {unit}" if unit else "")
            else:
                vertical = f"elevation {numfmt.fmt_fixed(pt[2], 2)}"
            where = (f"{nx} {numfmt.fmt_fixed(pt[0], 2)}   "
                     f"{ny} {numfmt.fmt_fixed(pt[1], 2)}   {vertical}")
            # what a feature reads at that point, told what was hit (a column
            # of the time-depth model: its name, its depth and time there)
            extra = [line(view_id, pt, hit) for _targets, line in getattr(ctx, "cursor_probes", None) or ()]
            return "\n".join(x for x in (where, _cursor_what(view_id, hit), *extra) if x)
        except Exception as exc:
            print(f"[fespp] cursor position ({view_id}):", exc, flush=True)
            return ""
    return (_cursor_pos, _locator_for)
