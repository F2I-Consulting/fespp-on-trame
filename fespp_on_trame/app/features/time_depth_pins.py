"""The columns of the time-depth model drawn in the 3D views that show
its grid (the Velocity model's eye open there, and drawn): each column as
the arrow of its track, in the view's domain (its points at their depth in
a depth view, at their two-way time in a time view). A model not generated
yet has no grid in the tree: what its inputs would make is drawn with them
in the 3D view in use while the model's view is open and that view is in
time — its outside, coloured by its velocity (`velocity_model.Cube.shell`) —,
converting nothing; a view in depth draws nothing of it; Generate
makes it a grid of the Seismic tree, drawn by the reader from then on.

Per view, three sources (TrivialProducers, as the Globe's marks) and the
labels: the lines — one segment per interval coloured by its interval
velocity, a cone below the last point (the last interval carried on); the
points — a sphere at every point; the halo — the active column in green;
a billboard label with each column's name above its zero. The colours are
the view's: the table painting the Velocity model's velocity there (its
scoped LUT), published as `ui_time_depth_colors__<vid>` = {lo, hi, stops,
log} for the card's tracks, so a column reads the same in the card, in the
view and on the grid; Viridis on the velocity model's range while the view paints
none, and the view's table starts on Viridis too. The columns have no colour bar of their own; a model not
generated yet has the view's one bar (engine/blockscope/bars) while no table of the scene holds it, titled and placed
as its grid's will be. Nothing is pickable (a pickable non-PDC
source resolves to the first loaded block — the Globe's lesson): the
cursor's ray meets them through `ctx.cursor_probes` instead, which reads a
column's name, depth, two-way time and interval velocity under the
pointer (and the depth on the Velocity model's grid in a time view).

Drawn again when the model changes, after every eye pass of a view
(eye_pass calls `refresh`), when the view switches domain (view_domain
does), when the vertical scale changes or a grid is ticked or unticked; the colours read again before every
frame (a render scheduler flush listener: the Colormap card edits them);
released with the view.

Hooks: ``ctx.time_depth_pins_refresh(vid=None)``.
"""
from paraview import simple as pvsimple

from fespp_on_trame.engine import crs_reference, geo, node_facts, view_routing
from fespp_on_trame.engine.utils import numfmt
from fespp_on_trame.engine.state_defaults import z_scale_of

TIME = crs_reference.DOMAINS[1]
ARRAY = "velocity"
PROBE = "TDLaw"         # the columns' geometry, as the cursor's ray meets it
LUT_NAME = "fesppVelocityPins"
PRESETS = ("Viridis", "Viridis (matplotlib)")   # ParaView 6's name, then ParaView 5's
COLORS = "ui_time_depth_colors__"               # + view id
BAR_TITLE = "Average velocity (m/s)"             # the bar of a model not generated yet
F2I_GREEN = (0.56, 0.76, 0.12)
WHITE = (1.0, 1.0, 1.0)


def register(core):
    ctx, state, scheduler, lifecycle = core.ctx, core.state, core.scheduler, core.lifecycle
    held = {}       # vid -> {"srcs": {name: (src, rep)}, "labels": {name: (text, trep)}, "drawn": stamp}
    preset = {"done": False}
    started = set()     # (view, array): the tables of a velocity that took their first preset

    def _view_lut(vid):
        """The table the view paints the Velocity model's velocity with,
        None while it paints it with none (not shown, a solid colour)."""
        cur = ctx.time_depth_tree_current() if getattr(ctx, "time_depth_tree_current", None) else None
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if not cur or scene is None:
            return None
        entry = scene.block_state.get(cur.get("grid") or "")
        if entry is None or not entry.color_array or (entry.assoc or "CELLS") != "CELLS":
            return None
        return scene.scoped_lut(entry.color_array)

    def _colors_of(lut):
        """{lo, hi, stops, log} of a continuous table, sampled as the
        Legends' swatches are."""
        from fespp_on_trame.engine import legends
        pts = list(lut.RGBPoints or [])
        if len(pts) < 8:
            return {}
        lo, hi = float(pts[0]), float(pts[-4])
        log = bool(int(getattr(lut, "UseLogScale", 0) or 0))
        ctf = lut.GetClientSideObject()
        stops = []
        for x in legends.sample_positions(lo, hi, legends.SWATCH_STOPS, log):
            rgb = [0.0, 0.0, 0.0]
            ctf.GetColor(x, rgb)
            stops.append("#%02x%02x%02x" % tuple(int(round(255 * max(0.0, min(1.0, c)))) for c in rgb))
        return {"lo": lo, "hi": hi, "stops": stops, "log": log}

    def _colors_of_the_view_in_use(**_):
        """The model's view paints its tracks as the 3D view in use does."""
        in_use = view_routing.model_view(state)
        colors = (getattr(state, COLORS + in_use, None) or {}) if in_use else {}
        if (getattr(state, "ui_time_depth_colors", None) or {}) != colors:
            state.ui_time_depth_colors = colors

    on_change = getattr(state, "change", None)
    if callable(on_change):
        on_change("fespp_last_render_panel_id")(_colors_of_the_view_in_use)

    def _publish_colors(vids):
        """Before a frame: the view's colours of the velocity to the card,
        and to the columns drawn there."""
        for vid in vids:
            try:
                _start_on_viridis(vid)
                lut = _view_lut(vid)
                colors = _colors_of(lut) if lut is not None else {}
                var = COLORS + str(vid)
                if (getattr(state, var, None) or {}) != colors:
                    state[var] = colors
                _colors_of_the_view_in_use()
                _preview_bar(vid)
                e = held.get(vid)
                got = e["srcs"].get("lines") if e is not None else None
                if got is not None and e["drawn"] is not None:
                    want = lut if lut is not None else e.get("cube_lut")
                    if want is not None and got[1].LookupTable != want:
                        got[1].LookupTable = want
            except Exception as exc:
                print(f"[fespp] time-depth columns ({vid}): colours not read ({exc!r})", flush=True)

    def _preview_bar(vid):
        """The view's one colour bar on the velocity of a model not generated
        yet, while its box is drawn there and no table of the scene has the
        bar; hidden otherwise. Looked up among the view's bars: asking
        ParaView for one makes it, visible."""
        e = held.get(vid)
        pvv = _pv_view(vid) if e is not None else None
        lut = e.get("cube_lut") if e is not None else None
        if pvv is None or lut is None:
            return
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        boxed = e["drawn"] is not None and bool(e["drawn"][-1])
        want = boxed and scene is not None and scene.bars.table() is None
        if want:
            from fespp_on_trame.engine.blockscope import bars as view_bars
            sb = pvsimple.GetScalarBar(lut, pvv)
            view_bars.dress(sb, e.get("bar_title") or BAR_TITLE)
            sb.Visibility = 1
            return
        for r in pvv.Representations:
            if (r.GetXMLName() == "ScalarBarWidgetRepresentation" and getattr(r, "LookupTable", None) == lut
                    and int(getattr(r, "Visibility", 0))):
                r.Visibility = 0

    def _shown_views():
        """The live 3D views showing the active model's grid: loaded, a row of
        one of its versions with its eye open there, and drawn (an object of
        the other domain the view does not convert is not)."""
        from fespp_on_trame.app.views import per_view_state
        rows = getattr(ctx, "time_depth_tree_active_rows", None)
        rows = tuple(rows()) if rows is not None else ()
        if not rows:
            return []

        def of_model(p):
            return node_facts.is_under(p, rows)

        if not any(of_model(p) for p in getattr(state, "ui_loaded_rep_paths", None) or ()):
            return []
        shown = []
        for v in getattr(ctx, "blockscope_scenes", None) or {}:
            if not per_view_state.is_live(v):
                continue
            undrawn = set(getattr(state, f"undrawn_paths__{v}", None) or ())
            if any(of_model(p) and p not in undrawn
                   for p in getattr(state, f"visible_paths__{v}", None) or ()):
                shown.append(v)
        return shown

    def _preview_views():
        """The live 3D views that show a model not generated yet: the one in
        use while the model's view is open, in time — a velocity model is in
        time, a view in depth draws nothing of it."""
        from fespp_on_trame.app.views import per_view_state
        views = getattr(ctx, "time_depth_card_views", None)
        domain_of = getattr(ctx, "view_domain_of", None)
        return [v for v in (views() if views is not None else ())
                if per_view_state.is_live(v) and domain_of is not None and domain_of(v) == TIME]

    def _pv_view(vid):
        mv = core.mv()
        try:
            return mv.get_pv_view(vid) if mv is not None else None
        except Exception as exc:
            print(f"[fespp] time-depth columns ({vid}): no render view ({exc})", flush=True)
            return None


    def _publish(src, data):
        """New geometry to the producer — the three calls, as the Globe's
        marks: the client-side swap alone leaves the ServerManager layer
        with the old bounds."""
        src.GetClientSideObject().SetOutput(data)
        src.MarkModified(src)
        src.UpdatePipeline()

    def _source(entry, name, vid, pvv, data):
        """The source `name` of the view, made on first use, fed `data`."""
        from fespp_on_trame.engine.sources import leaf_rep
        got = entry["srcs"].get(name)
        if got is None:
            src = pvsimple.TrivialProducer(registrationName=f"fesppTimeDepthPins_{name}_{vid}")
            _publish(src, data)
            rep = leaf_rep.show_composite(src, pvv)
            if rep is None:
                print(f"[fespp] time-depth columns ({vid}): no representation for {name}", flush=True)
                return None
            rep.Pickable = 0
            got = entry["srcs"][name] = (src, rep)
        else:
            _publish(got[0], data)
        return got[1]

    def _viridis(lut):
        """`lut` on Viridis, its range kept: the preset's name, "" when this
        ParaView has none."""
        for name in PRESETS:
            try:
                if lut.ApplyPreset(name, True):
                    return name
            except Exception as exc:
                print(f"[fespp] time-depth columns: no preset {name!r} ({exc})", flush=True)
        return ""

    def _start_on_viridis(vid):
        """The view's table of a model's velocity starts on Viridis, once, at
        the first frame painting with it: the colours the tracks fall back on
        and those of the model's preview, and no alarm in a model whose
        velocities sit at the top of their range. Each velocity has its table
        (a model made by hand, one read from the wells: two arrays). The
        Colormap card changes it from then on; a table a session wrote back
        keeps its colours."""
        lut = _view_lut(vid)
        if lut is None:
            return
        cur = ctx.time_depth_tree_current()
        array = ctx.blockscope_scenes[vid].block_state[cur["grid"]].color_array
        if (vid, array) in started or (vid, array) in ctx.colormap_restored:
            return
        started.add((vid, array))
        name = _viridis(lut)
        if name:
            ctx.colormap_presets[(vid, array)] = name
            # the card's nodes still pending would write the old colours back
            ctx.colormap_push(vid)

    def _lut(cube):
        """The colours of a model no view paints yet: Viridis on its range of
        velocities, as the table of its grid will start once generated — the
        same colours before and after Generate."""
        lut = pvsimple.GetColorTransferFunction(LUT_NAME)
        if not preset["done"]:
            _viridis(lut)
            preset["done"] = True
        s = cube.summary()
        lo, hi = float(s["vmin"]), float(s["vmax"])
        if hi <= lo:
            # one velocity everywhere: in the middle of the table, as a reader's grid is
            lo, hi = lo - 10.0, lo + 10.0
        lut.RescaleTransferFunction(lo, hi)
        return lut

    def _earth_code(vid):
        """The EPSG code `vid` draws round the Earth with: 0 there without one,
        None in a plain 3D view."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        return getattr(scene, "epsg", None)

    def _on_earth(pins, epsg, zs):
        """The columns round the Earth as the Globe draws the rest: in ECEF,
        the vertical scale inside it."""
        from vtkmodules.util import numpy_support
        for name in ("lines", "points", "halo", "box"):
            data = pins.get(name)
            if data is not None:
                xyz = numpy_support.vtk_to_numpy(data.GetPoints().GetData())
                data.GetPoints().SetData(numpy_support.numpy_to_vtk(geo.project_points(xyz, epsg, zs), deep=True))
        pins["labels"] = [(name, *geo.project_points([(x, y, z)], epsg, zs)[0]) for name, x, y, z in pins["labels"]]

    def _labels(entry, vid, pvv, labels, zs):
        """One billboard per column at its zero (the Globe marks' pattern)."""
        from fespp_on_trame.engine.sources import leaf_rep
        keep = set()
        for name, x, y, z in labels:
            keep.add(name)
            m = entry["labels"].get(name)
            if m is None:
                text = pvsimple.Text(Text=name)
                trep = leaf_rep.show_composite(text, pvv)
                trep.TextPropMode = "Billboard 3D Text"
                trep.Justification = "Left"
                trep.DisplayOffset = [12, 8]
                trep.Color = list(WHITE)
                trep.Bold = 1
                trep.FontSize = 14
                m = entry["labels"][name] = (text, trep)
            m[1].BillboardPosition = [float(x), float(y), float(z) * zs]
            m[1].Visibility = 1
        for name in [n for n in entry["labels"] if n not in keep]:
            _release(vid, entry["labels"].pop(name))

    def _release(vid, pair):
        for proxy in reversed(pair):
            try:
                pvsimple.Delete(proxy)
            except Exception as exc:
                print(f"[fespp] time-depth columns ({vid}): not released ({exc})", flush=True)

    def _hide(vid):
        e = held.get(vid)
        if e is None or e["drawn"] is None:
            return
        for _src, rep in e["srcs"].values():
            rep.Visibility = 0
        for _text, trep in e["labels"].values():
            trep.Visibility = 0
        e["drawn"] = None
        _preview_bar(vid)
        scheduler.mark_dirty(vid)

    def _dress_lines(rep, cube, vid=None):
        rep.Representation = "Surface"
        rep.ColorArrayName = ["CELLS", ARRAY]
        own = _lut(cube)
        if vid in held:
            held[vid]["cube_lut"] = own
        rep.LookupTable = _view_lut(vid) or own
        rep.RenderLinesAsTubes = 1
        rep.LineWidth = 7.0
        rep.Opacity = 1.0

    def _dress_box(rep, cube, vid=None):
        rep.Representation = "Surface"
        rep.ColorArrayName = ["CELLS", ARRAY]
        rep.LookupTable = _view_lut(vid) or _lut(cube)
        rep.Opacity = 1.0

    def _dress_points(rep, _cube, _vid=None):
        rep.Representation = "Points"
        rep.ColorArrayName = ["POINTS", ""]
        rep.DiffuseColor = list(WHITE)
        rep.AmbientColor = list(WHITE)
        rep.Ambient = 0.3
        rep.RenderPointsAsSpheres = 1
        rep.PointSize = 13.0

    def _dress_halo(rep, _cube, _vid=None):
        rep.Representation = "Surface"
        rep.ColorArrayName = ["POINTS", ""]
        rep.DiffuseColor = list(F2I_GREEN)
        rep.AmbientColor = list(F2I_GREEN)
        rep.Ambient = 0.5
        rep.RenderLinesAsTubes = 1
        rep.LineWidth = 18.0
        rep.Opacity = 0.35

    def _draw(vid, cube, key, domain, columns, active, box=False):
        pvv = _pv_view(vid)
        if pvv is None:
            return
        e = held.setdefault(vid, {"srcs": {}, "labels": {}, "drawn": None})
        zs = z_scale_of(state, vid)
        epsg = _earth_code(vid)
        stamp = (key, domain, active, tuple(name for name, *_ in columns), zs, epsg, box)
        if e["drawn"] == stamp:
            return
        pins = cube.pins(domain, columns, active)
        pins["box"] = cube.shell(domain) if box else None
        if epsg:
            _on_earth(pins, epsg, zs)
        drawn_z = 1.0 if epsg else zs
        for name, data, dress in (("box", pins["box"], _dress_box),
                                  ("lines", pins["lines"], _dress_lines),
                                  ("points", pins["points"], _dress_points),
                                  ("halo", pins["halo"], _dress_halo)):
            if data is None or data.GetNumberOfPoints() == 0:
                got = e["srcs"].get(name)
                if got is not None:
                    got[1].Visibility = 0
                continue
            rep = _source(e, name, vid, pvv, data)
            if rep is not None:
                dress(rep, cube, vid)
                rep.Scale = [1.0, 1.0, drawn_z]
                rep.Visibility = 1
        _labels(e, vid, pvv, pins["labels"], drawn_z)
        e["drawn"] = stamp
        summary = cube.summary()
        e["bar_title"] = BAR_TITLE + (f" — constant {numfmt.fmt(summary['vmin'])}"
                                      if summary["vmax"] <= summary["vmin"] else "")
        scheduler.mark_dirty(vid)
        if box and not epsg:
            # the model alone in its view: nothing else frames it
            from fespp_on_trame.app.views import per_view_state
            from fespp_on_trame.app.views.camera import reset_camera_centered
            if vid not in per_view_state.FRAMED and reset_camera_centered(pvv):
                per_view_state.FRAMED.add(vid)

    def refresh(vid=None):
        """The columns in `vid` (every view when None) as the model says
        now: drawn where its grid is shown, hidden elsewhere."""
        cube = ctx.time_depth_cube() if getattr(ctx, "time_depth_cube", None) else None
        key = ctx.time_depth_cube_key() if getattr(ctx, "time_depth_cube_key", None) else ""
        columns = ctx.time_depth_columns() if getattr(ctx, "time_depth_columns", None) else []
        active = ctx.time_depth_active() if getattr(ctx, "time_depth_active", None) else None
        law = getattr(ctx, "time_depth_law", None)
        model = law() if law is not None else None
        boxed = set()
        if cube is None and getattr(ctx, "time_depth_preview", None):
            # no model yet: what its inputs would make, drawn from itself
            cube, key = ctx.time_depth_preview()
            boxed = set(_preview_views()) if cube is not None else set()
        # the default law over nothing is not a thing to draw
        if model is not None and model.extent_in_use() is None:
            cube = None
        drawn = set(_shown_views()) | boxed
        views = set(held) | drawn
        if vid is not None:
            views = {str(vid)} & views
        for v in views:
            try:
                if v not in drawn or cube is None or not columns or _earth_code(v) == 0:
                    _hide(v)
                    continue
                domain_of = getattr(ctx, "view_domain_of", None)
                domain = domain_of(v) if domain_of is not None else "depth"
                _draw(v, cube, key, domain, columns, active, v in boxed)
            except Exception as exc:
                print(f"[fespp] time-depth columns ({v}): not drawn ({exc!r})", flush=True)
        scheduler.flush()

    scheduler.add_flush_listener(_publish_colors)

    @lifecycle.on("view_closed")
    def _forget(vid):
        started.difference_update({k for k in started if k[0] == str(vid)})
        e = held.pop(str(vid), None)
        if e is None:
            return
        for pair in list(e["srcs"].values()) + list(e["labels"].values()):
            _release(vid, pair)

    def _changed(**_):
        refresh()

    on_change = getattr(state, "change", None)
    if callable(on_change):
        # a grid ticked or unticked
        on_change("ui_loaded_rep_paths")(_changed)

    def _probe_targets(vid):
        """The columns drawn in `vid`, met by the cursor's ray: their
        segments, cones and points."""
        e = held.get(str(vid))
        if e is None or e["drawn"] is None:
            return []
        out = []
        for name in ("lines", "points"):
            got = e["srcs"].get(name)
            ds = got[0].GetClientSideObject().GetOutputDataObject(0) if got is not None else None
            if ds is not None and ds.GetNumberOfPoints():
                out.append((ds, PROBE))
        return out

    def _grid_line(pt, path):
        """On the Velocity model's grid: the depth it gives at `pt`, in a
        time view; "" off the grid."""
        rows = tuple(ctx.time_depth_tree_active_rows()) if getattr(ctx, "time_depth_tree_active_rows", None) else ()
        cube = ctx.time_depth_cube() if getattr(ctx, "time_depth_cube", None) else None
        if cube is None or not node_facts.is_under(path or "", rows):
            return ""
        depth = float(cube.to_depth([pt[0]], [pt[1]], [-float(pt[2])])[0])
        return f"depth {numfmt.fmt_fixed(depth, 1)} m on the velocity model"

    def _column_line(pt, in_time):
        """On a column: its name, the depth and the two-way time at `pt`, the
        interval velocity there (the last interval carried on below)."""
        columns = ctx.time_depth_columns() if getattr(ctx, "time_depth_columns", None) else []
        if not columns:
            return ""
        name, _x, _y, law = min(columns, key=lambda c: (c[1] - pt[0]) ** 2 + (c[2] - pt[1]) ** 2)
        vertical = -float(pt[2])
        depth, twt = (law.to_depth(vertical), vertical) if in_time else (vertical, law.to_time(vertical))
        velocities = law.velocities()
        interval = min(sum(1 for _z, t in law.rows()[1:-1] if t <= twt), len(velocities) - 1)
        return (f"{name}   depth {numfmt.fmt_fixed(depth, 1)} m   TWT {numfmt.fmt_fixed(twt, 1)} ms"
                f"   interval {numfmt.fmt_int(velocities[interval])} m/s")

    def _probe_line(vid, pt, hit):
        """What the cursor reads on a column; on the Velocity model's grid,
        in a time view, the depth."""
        hit = hit or {}
        domain_of = getattr(ctx, "view_domain_of", None)
        in_time = (domain_of(vid) if domain_of is not None else "depth") == "time"
        if hit.get("title") == PROBE:
            return _column_line(pt, in_time)
        return _grid_line(pt, hit.get("path")) if in_time else ""

    ctx.cursor_probes = list(getattr(ctx, "cursor_probes", None) or []) + [(_probe_targets, _probe_line)]
    ctx.time_depth_pins_refresh = refresh
    ctx.time_depth_law_listeners = list(getattr(ctx, "time_depth_law_listeners", None) or []) + [refresh]
    return refresh
