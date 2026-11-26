"""Time-depth model — the session's columns, laws side by side, and the
velocity model they make (engine/time_depth `Model`, engine/velocity_model),
edited in a view of its own (app/views/time_depth_panel), kept in the session
document, read by the domain conversion (app/features/view_domain) through
the velocity model it registers (engine/blockscope/domain_convert.CUBES), put
into the tree as a grid by app/features/time_depth_tree.

No model to start with, and nothing converts: the view holds the inputs of
one to generate (its zone, its layers, its TDLaws — one to start with, on
the starting line at the zone's centre, as soon as there is a zone), and the
3D view in use shows what they would make, no row in the tree
(app/features/time_depth_pins).
`generate` makes "Velocity model N" of them once a TDLaw converts; from then
on every edit updates it (app/features/time_depth_models).

State:  ``ui_time_depth_law`` = {columns: [{name ("TDLaw<n>" unless named),
        x, y, rows ([{depth, twt, velocity}], the start first), problems,
        why (what keeps it from converting in a few words, "" when it
        converts), valid}], active (the column edited), generated (a model
        is active: the edits update it), can_generate (none is, and a TDLaw
        converts), axes ([x,
        y] as the CRS names them, with their unit), cube: {extent: the one
        set [x0, x1, y0, y1] | None (a draft while typed corner by corner),
        extent_from ("data" — the files' extent, nothing typed — | "typed" | "columns" —
        a square around them, nothing set — | None), extent_used (the
        extent the velocity model covers: the one set grown to the columns placed
        outside it | None), extent_grown (the indices of those columns), nx,
        ny, nz (the layers, the reader's number), trange ([t0, t1] the two-way
        time range the layers cut, ms), summary ({nx, ny, layers, cells,
        vmin, vmax, ttop, tmax, ztop, zmax, extent} | None), edited (how
        many cells were set by hand)}, problems: [str] (what stops the model as a
        whole), valid. ``ui_cube_grid_rows``: the containers of the tree's
        lattice IJK grids, the versions of the active model aside ("Use as
        velocity model" is offered on them).
        The models (app/features/time_depth_models): `models`
        [{value, label}], what the view's list offers — "new" (the inputs of
        one to generate), the session's, the lattice grids of the data —,
        `model` the active one's value ("new" with none), `refused` how many
        choices were refused (the list goes back to `model`).
Gesture: ``controller.time_depth_law_edit(edit)`` — on the active column's
        law: {op: set, index, depth?, twt?, velocity?} (index: a row, 0 the
        start; a velocity sets the interval above the row, its depth
        follows and the rows below shift), {op: add, depth?, twt?} (above
        the start: the new start), {op: del, index} (not the start), {op:
        reset}; on the model: {op: add_column, x?, y?, at?} (at: "centre" =
        the centre of the extent in use, or the nearest free place inside
        it; a column placed on a velocity model starts from the velocity model's own law there,
        on its layers — else from the first column's law), {op: set_column,
        index, x?, y?} (a column without a point takes the velocity model's law once
        placed), {op: name_column, index, name}, {op: del_column, index},
        {op: active, index}, {op: cube_set, x0?, x1?, y0?, y1?, nx?, ny?, nz?, t0?, t1?},
        {op: cube_auto} (a corner emptied: the files' extent again, following
        the files read until one is typed), {op: cell, i, j, k, v}
        (one
        cell set by hand — the Values card on the model's grid: kept while
        the velocity model keeps its shape), {op: clear_cells};
        {op: prefill, what: "wells" | "sonic" | "markers"} asks (the shared
        question box) then reads the files on the query channel, nothing
        loaded (engine/time_depth_prefill): one column per VERTICAL well
        (a deviated one is left out) with a time log, with a DT or Vp log
        integrated, or with markers read on the one 2D grid in time of
        their interpretation (an interpretation with several is left
        out). The state's `prefill.ready` says a file is read, `prefill.wells` /
        `prefill.sonic` / `prefill.markers` how many wells make a TDLaw from
        their time log, sonic log, markers, `prefill.wells_out` / `sonic_out` /
        `markers_out` how many carry one and are deviated (their trajectories
        read once each while the card is open, not on a store), `prefill.time_grids` /
        `prefill.depth_grids` how many 2D grids the tree holds in each
        domain, `prefill.done` the entry whose columns the model holds
        (ticked in the menu),
        `note` what the last pre-fill did (or could not).
Gesture too: {op: model_activate, value} (a value of `models`), {op:
        generate} (the inputs become "Velocity model N", active: refused, and
        said in `problems`, while no TDLaw converts or no zone can be told).
Hooks:  ``ctx.time_depth_law()`` the Model the view edits (the active model's, or the inputs
        of a new one); ``ctx.time_depth_cube()`` the cube built from the active model (None
        while it cannot, and while inputs are entered); ``ctx.time_depth_cube_key()`` /
        ``ctx.time_depth_convert_cube()`` the key and the cube the conversions read — the
        active model's, and while the inputs of a new one are entered those of the model left
        for them, which converts until another is generated or chosen;
        ``ctx.time_depth_preview()`` (cube, key) of what
        the inputs of a model not generated yet would make, (None, "") once
        one is active or while they make none; ``ctx.time_depth_ensure_zone()`` gives the model
        a zone when it has none; ``ctx.time_depth_active()``,
        ``ctx.time_depth_columns()`` (the placed, valid columns [(name, x,
        y, law)]); ``ctx.time_depth_law_doc()`` /
        ``ctx.time_depth_law_restore(doc)`` for the session (the active model,
        plus `extent_from`, `active`, `prefilled`, `touched`, `name`, `from`,
        `uuids` (its grid's in the tree, taken again when free);
        the parked ones, of the same form, under `others`); ``ctx.time_depth_law_listeners``
        called after a change.
"""
import types

from fespp_on_trame.app.features import time_depth_models, time_depth_prefills
from fespp_on_trame.app.features.time_depth_tree import VIEW
from fespp_on_trame.app.features.time_depth_models import NEW, Models, blank
from fespp_on_trame.engine import time_depth_prefill as prefill
from fespp_on_trame.engine.blockscope import domain_convert
from fespp_on_trame.engine.time_depth import Model
from fespp_on_trame.engine.utils import numfmt

STATE = "ui_time_depth_law"
PAD = 0.02      # the Auto extent, a little wider than the data
PREFILLED = ("wells", "sonic", "markers")   # the Pre-fills that read columns
# the kind set on a property of the data read as the card's type says
READ_AS = {"average": "avg seismic velocity", "interval": "interval velocity", "rms": "rms velocity"}


def _rows_of(law):
    """The law's rows for the view: the start first, each point with the
    velocity of the interval above it."""
    law.points.sort()          # a row's index is its depth order
    vel = law.velocities()
    return [{"depth": z, "twt": t, "velocity": (vel[i - 1] if i else None)}
            for i, (z, t) in enumerate(law.rows())]


def column_name(column, index):
    return column.name or f"TDLaw{index + 1}"


START_STEPS = 12          # even steps of a column added on a velocity model, when the columns give no times
MAX_START_POINTS = 40     # beyond as many times of the columns, even steps instead


def register(core, *, _data_bounds=None, _ask=None, _query=None, _channels=None, _markers=None,
             _grids=None, _axes=None, _defer=None, _trajectories=None):
    """`_data_bounds()`: [x0, x1, y0, y1, z0, z1] of everything loaded, or
    None — what the velocity model's Auto extent reads. `_ask(question, on_yes,
    on_no)`: the shared question box (app/features/tick_question) a
    pre-fill asks through. `_query()`: {index(), fields(uuid)} over the
    reader's query channel (engine/repo_query), `_channels()`: the log
    channels of the tree [(well, uuid, title, uom)]
    (engine/welllog_dispatch.log_channels), `_markers()` its marker frames
    [(well, uuid, title, [marker titles])] (welllog_dispatch.marker_frames),
    `_grids()` its 2D grids by domain {"depth": n, "time": n}
    (crs_reference.grids_by_domain);
    `_query()` also answers xml(uuids) and surface(uuid) (a 2D grid's
    elevations) when it can — all made from `core` when
    None. `_axes()`: the horizontal axes as the CRS names them, with their
    unit ("Easting (m)", "Northing (m)"). `_defer(name, fn, views)`: one turn
    later behind the bar of `views` (app/features/heavy), `_trajectories()` the
    wells' trajectories (welllog_dispatch.well_trajectories)."""
    controller, ctx, state = core.controller, core.ctx, core.state
    held = {**blank(), "rev": 0, "zone_read": None, "refused": 0, "refusal": ""}
    models = Models(held)

    def _default_query():
        from fespp_on_trame.engine import repo_query
        src = core.active_data_source.get_source()
        tag = repo_query.tag(src)
        return types.SimpleNamespace(
            index=lambda: repo_query.object_index(src, cache_tag=tag),
            fields=lambda uuid: repo_query.object_fields(src, uuid, cache_tag=tag),
            xml=lambda uuids: repo_query.object_xml(src, list(uuids), cache_tag=tag),
            surface=lambda uuid: repo_query.object_fields(src, uuid + "|surface", cache_tag=tag),
            # what a store (ETP) holds rather than a file: each read of one is a request
            store=lambda: repo_query.store_uuids(src))

    def _default_channels():
        from fespp_on_trame.engine import welllog_dispatch
        return welllog_dispatch.log_channels(getattr(core, "tree", None))

    def _default_markers():
        from fespp_on_trame.engine import welllog_dispatch
        return welllog_dispatch.marker_frames(getattr(core, "tree", None))

    def _default_trajectories():
        from fespp_on_trame.engine import welllog_dispatch
        return welllog_dispatch.well_trajectories(getattr(core, "tree", None))

    def _default_grids():
        from fespp_on_trame.engine import crs_reference
        return crs_reference.grids_by_domain(getattr(core, "tree", None))

    _query = _query or _default_query
    _channels = _channels or _default_channels
    _markers = _markers or _default_markers
    _grids = _grids or _default_grids
    _trajectories = _trajectories or _default_trajectories

    def model():
        return held["model"]

    def _active():
        """The column edited in cube mode, clamped to what there is."""
        cols = model().columns
        held["active"] = max(0, min(held["active"], len(cols) - 1)) if cols else 0
        return held["active"]

    def _edited():
        """The law the point gestures act on: the active column's."""
        m = model()
        if not m.columns:
            raise IndexError("no TDLaw to edit")
        return m.columns[_active()].law

    def _axis_names():
        """[x, y] as the CRS names them, "Easting" / "Northing" when it
        names nothing."""
        try:
            x, y = (_axes() if _axes is not None else ("X", "Y"))[:2]
        except Exception as exc:
            print(f"[fespp] time-depth model: the axes not named ({exc!r})", flush=True)
            x, y = "X", "Y"
        return ["Easting" if x == "X" else x, "Northing" if y == "Y" else y]

    def _columns():
        """The usable columns the views draw: [(name, x, y, law)]; none for
        a velocity model of the data, which has no law (the PO, 12/11)."""
        if held.get("data"):
            return []
        return [(column_name(c, i), c.x, c.y, c.law)
                for i, c in enumerate(model().columns) if c.usable()]

    def _active_drawn():
        """The index, among the drawn columns, of the active one (None
        when it is not drawn)."""
        cols = model().columns
        if not cols or held.get("data"):
            return None
        a = _active()
        if not cols[a].usable():
            return None
        return sum(1 for c in cols[:a] if c.usable())

    def _converting():
        """(key, cube, grid of the data or "", the row of its velocity there
        or "") of the model the conversions read: the active one; while the
        inputs of a new one are entered, the model left for them, until
        another is generated or chosen."""
        fields = held if models.current is not None else models.entry(models.serving)
        if not fields:
            return "", None, "", ""
        return (fields.get("key") or "", fields.get("cube"), fields.get("data") or "",
                (fields.get("velocity") or {}).get("path") or "")

    def _rebuild():
        """The velocity model the model makes now, registered for the stages under a
        new key (a stage is told by its key that the velocity model changed) — the
        same cube again keeps its key, so nothing is converted nor written
        again; the cells edited by hand let go, and said so, when the velocity model
        no longer has their shape. A grid of the data read as it is keeps
        its own cube (app/features/time_depth_models)."""
        held["preview"], held["preview_key"] = None, ""
        if held.get("data"):
            return
        m = model()
        cube = m.cube()
        if models.current is None:
            # the inputs of a model not generated yet convert nothing: what
            # they would make is shown, no more (app/features/time_depth_pins)
            if cube is not None:
                held["preview"], held["preview_key"] = cube, "preview:" + cube.signature()
            cube = None
        if m.cells_stale(cube):
            n = len(m.cells)
            m.cells.clear()
            m.cells_shape = None
            held["note"] = (f"the {numfmt.plural(n, 'cell', 'cells')} set by hand no longer"
                            " apply: the velocity model's cells changed")
        if cube is None:
            held["cube"], held["key"], held["sig"] = None, "", ""
            domain_convert.register_cube(*_converting()[:2])
            return
        sig = cube.signature()
        if held["key"] and sig == held["sig"]:
            return
        held["cube"], held["sig"] = cube, sig
        held["rev"] += 1
        held["key"] = f"tdl:{held['rev']}"
        domain_convert.register_cube(held["key"], cube)

    def _extent_from(m, auto):
        """Where the extent of `m` comes from: "data" (nothing typed, `auto`),
        "typed", "columns" (a square around them: nothing set), None."""
        if m.extent is not None:
            return "data" if auto else "typed"
        return "columns" if m.extent_in_use() is not None else None

    def publish():
        m = model()
        columns = []
        for i, c in enumerate(m.columns):
            why = m.why_left_out(c)
            problems = c.law.problems() + (["no position: enter its easting and northing"]
                                           if "not placed" in why else [])
            columns.append({"name": column_name(c, i), "x": c.x, "y": c.y, "rows": _rows_of(c.law),
                            "problems": problems, "why": why, "valid": not problems})
        problems = m.problems()
        generated = models.current is not None
        if generated and not held.get("data") and not m.has_law():
            problems = problems + ["no TDLaw converts: the velocity model is not updated, and nothing is"
                                   " converted, until one does"]
        cube = held["cube"]
        used = m.extent_in_use()
        state[STATE] = {"columns": columns, "active": _active(),
                        "generated": generated,
                        "can_generate": not generated and m.has_law() and not problems,
                        "axes": _axis_names(),
                        "cube": {"extent": list(m.extent) if m.extent else list(held["draft"]),
                                 "extent_from": _extent_from(m, held["extent_auto"]),
                                 "extent_used": list(used) if used else None,
                                 # the columns placed beyond the extent set, which grew it
                                 "extent_grown": m.outside_extent(),
                                 "nx": m.nx, "ny": m.ny, "nz": m.nz, "trange": list(m.trange),
                                 "summary": cube.summary() if cube is not None else None,
                                 "edited": len(m.cells)},
                        "prefill": {"ready": bool(getattr(state, "ui_has_data", False)),
                                    "done": _prefills_done(), **fills.counts()},
                        "note": held["note"],
                        # a grid of the data read as it is: the card shows no TDLaw,
                        # its velocity's kind and where its values stand instead
                        "data": bool(held.get("data")),
                        # where the velocity comes from: a property, the wells
                        # (a Pre-fill), TDLaws entered by hand
                        "source": (time_depth_models.PROPERTY if held.get("data")
                                   else held["prefilled"] or time_depth_models.BY_HAND),
                        "velocity": held.get("velocity") or None,
                        "models": choice.options(), "model": f"m{models.current}" if generated else NEW,
                        "refused": held["refused"],
                        # what an edit could not do comes with what keeps the model from being valid
                        "problems": ([held["refusal"]] if held["refusal"] else []) + problems,
                        "valid": not problems}

    def _prefills_done():
        """The Pre-fill entry whose columns the model holds."""
        return [held["prefilled"]] if held["prefilled"] else []

    def _place_lone():
        """The model's one column, unplaced, put at the centre of the
        extent once there is one: the column a model starts with stands
        in its velocity model."""
        m = model()
        if len(m.columns) == 1 and not m.columns[0].placed():
            spot = m.free_spot()
            if spot is not None:
                m.columns[0].x, m.columns[0].y = spot

    def _recentre_lone():
        """The model's one column, left outside the zone the ticks moved:
        back at its centre (alone, its law holds everywhere; outside, it
        would only stretch the velocity model towards where the zone was)."""
        m = model()
        if len(m.columns) != 1 or not m.columns[0].placed() or m.extent is None:
            return
        c = m.columns[0]
        x0, x1, y0, y1 = m.extent
        if not (x0 <= c.x <= x1 and y0 <= c.y <= y1):
            spot = m.free_spot()
            if spot is not None:
                c.x, c.y = spot

    def _first_column():
        """The inputs of a model not generated yet start with ONE TDLaw as
        soon as they have a zone: at its centre, on the starting line, to
        edit — the 3D view previews what it makes and Generate is offered.
        Given once: removed by its reader, it does not come back."""
        m = model()
        if m.columns:
            held["seeded"] = True
        if held.get("seeded") or models.current is not None or held.get("data") or m.extent_in_use() is None:
            return
        held["active"] = m.add_column(*(m.free_spot() or (None, None)))
        held["seeded"] = True

    def _changed():
        if not model().columns:
            held["prefilled"] = ""
        _auto_if_unset()
        _first_column()
        _place_lone()
        _rebuild()
        publish()
        for hook in list(getattr(ctx, "time_depth_law_listeners", None) or []):
            try:
                hook()
            except Exception as exc:
                print(f"[fespp] time-depth law listener: {exc!r}", flush=True)

    def _zone_of_files():
        """The field's extent read from what the session holds, the model's
        own versions aside, a little wider. Of the files: their 2D and 3D
        grids, the rest only when these say nothing. Of a store, which would
        be read object by object: its lattice IJK grids alone, their extent
        is in their XML. Read again only when either changes. None without
        one."""
        try:
            q = _query()
            own = ctx.time_depth_tree_grids() if getattr(ctx, "time_depth_tree_grids", None) else ()
            far = q.store()
            listed = getattr(ctx, "time_depth_lattice_uuids", None)
            lattices = [u for u in (listed() if far and listed is not None else ())
                        if u in far and u not in own]
            entries = [e for e in prefill.extent_entries(q.index()) if e[0] not in own and e[0] not in far]
            names = [e[0] for e in entries] + ["store", *lattices]
            if held["zone_read"] is not None and held["zone_read"][0] == names:
                return held["zone_read"][1]
            got = None
            quick = prefill.quick_entries(entries)
            for some in (quick, [e for e in entries if e not in quick]):
                got = prefill.union(prefill.extent_of(q.fields(uuid)) for uuid, _kind, _title in some)
                if got is not None:
                    break
            got = prefill.union([got, *(prefill.extent_of(q.fields(u)) for u in lattices)])
            zone = prefill.padded(got) if got is not None else None
            held["zone_read"] = (names, zone)
            return zone
        except Exception as exc:
            print(f"[fespp] time-depth model: the extent of the files not read ({exc!r})", flush=True)
        return None

    def _auto_extent():
        """The zone with none typed: the files' extent; where they cannot say
        (a remote store), the objects ticked, a little wider."""
        zone = _zone_of_files()
        if zone is not None:
            return zone
        b = _data_bounds() if _data_bounds is not None else None
        if not b or len(b) < 4:
            raise ValueError("nothing to take a zone from: tick an object, the extent reads what is loaded")
        x0, x1, y0, y1 = (float(v) for v in b[:4])
        px, py = (x1 - x0) * PAD, (y1 - y0) * PAD
        return (x0 - px, x1 + px, y0 - py, y1 + py)

    def _try_auto_extent():
        """The extent taken from the data when there is one to read; True
        when taken (nothing loaded: nothing said, the chip reads "none yet")."""
        b = _data_bounds() if _data_bounds is not None else None
        if not b or len(b) < 4:
            return False
        model().extent = _auto_extent()
        held["extent_auto"] = True
        return True

    def _ensure_zone():
        """The model given a zone when nothing gave it one (nothing ticked,
        no TDLaw placed, none typed)."""
        m = model()
        if m.extent_in_use() is not None or any(v is not None for v in held["draft"]):
            return
        try:
            m.extent = _auto_extent()
        except ValueError as exc:
            print(f"[fespp] time-depth model: no zone ({exc})", flush=True)
            return
        held["extent_auto"] = True
        _changed()

    def _column_times(cube):
        """The times a column added on `cube` gets its points at: those of
        the columns that make the velocity model, so it reads like them; with too few
        or too many of those, a dozen even steps over the velocity model's time range
        — never one point per layer, a hundred points in a track."""
        import numpy as np
        top, bottom = float(cube.t[0]), float(cube.t[-1])
        seen = sorted({round(float(t), 3) for c in model().usable_columns()
                       for _z, t in c.law.rows() if top <= t <= bottom})
        if 2 <= len(seen) <= MAX_START_POINTS + 1:
            return np.asarray(seen, float)
        return np.linspace(top, bottom, START_STEPS + 1)

    def _law_from_cube(x, y):
        """The velocity model's time-depth law at (x, y), at the times of
        `_column_times`: what a column added on a velocity model starts from (a
        column added on a pre-filled cube went astray when it started from
        the empty law): (start, points), None without a velocity model or a
        position."""
        cube = held["cube"]
        if cube is None or x is None or y is None or cube.layers < 1:
            return None
        import numpy as np
        times = _column_times(cube)
        depths = np.asarray(cube.to_depth(np.full(len(times), float(x)), np.full(len(times), float(y)), times), float)
        start = (float(depths[0]), float(times[0]))
        out, (zl, tl) = [], start
        for z, t in zip(depths[1:].tolist(), times[1:].tolist()):
            if z > zl and t > tl:
                out.append((float(z), float(t)))
                zl, tl = z, t
        return (start, out) if out else None

    def _start_from_cube(column, force=False):
        """`column`'s law set to the velocity model's at its position: always when
        `force` (a column just added), else only when it has no point."""
        if not column.placed() or (column.law.points and not force):
            return
        got = _law_from_cube(column.x, column.y)
        if got:
            column.law.start, column.law.points[:] = got

    def _auto_if_unset():
        """The loaded data's extent, taken when none is set nor being typed
        corner by corner: at every change, so a velocity model standing around its
        columns takes the data's once something is loaded."""
        m = model()
        if m.extent is None and all(v is None for v in held["draft"]):
            _try_auto_extent()

    def _refuse(why):
        held["refusal"] = why
        held["refused"] += 1
        publish()

    def _generate():
        """The inputs entered become a velocity model, the active one: a
        TDLaw converts, and there is a zone to stand on."""
        m = model()
        if models.current is not None:
            return
        if not m.has_law():
            _refuse("a velocity model needs a TDLaw: enter one by hand, or read the wells'")
            return
        if m.extent_in_use() is None:
            try:
                m.extent = _auto_extent()
                held["extent_auto"] = True
            except ValueError as exc:
                print(f"[fespp] time-depth model: not generated, no zone ({exc})", flush=True)
                _refuse("a velocity model needs a zone: enter its corners, place a TDLaw or tick an object")
                return
        if m.problems():
            _refuse(m.problems()[0])
            return
        models.generate()
        held["touched"] = True
        print(f"[fespp] journal time-depth law: {models.active()['name']} generated", flush=True)
        _changed()

    @controller.set("time_depth_law_edit")
    def time_depth_law_edit(edit):
        edit = dict(edit or {})
        op = edit.get("op") or ""
        held["refusal"] = ""
        if op == "model_activate":
            choice.pick(edit.get("value"))
            return
        if op == "generate":
            _generate()
            return
        m = model()
        vel = held.get("velocity") or {}
        if held.get("data") and op in ("velocity_kind", "velocity_at") and vel.get("path"):
            # the velocity of a model of the data: its kind and where its
            # values stand, set on the property (app/features/property_types)
            if op == "velocity_kind" and getattr(ctx, "property_type_set", None):
                kind = READ_AS.get(str(edit.get("reading") or ""), str(edit.get("kind") or ""))
                ctx.property_type_set(vel["path"], kind)
            elif op == "velocity_at" and getattr(ctx, "property_position_set", None):
                ctx.property_position_set(vel["path"], str(edit.get("at") or ""))
            publish()
            return
        if held.get("data") and op == "velocity_property":
            choice.pick_property(edit.get("path"))
            return
        if held.get("data"):
            _refuse("a grid of the data takes its velocity from one of its properties: choose New velocity"
                    " model to fill one from the wells or by hand")
            return
        held["note"] = ""
        try:
            if op == "source":
                what = str(edit.get("value") or "")
                if what in PREFILLED:
                    fills.prefill(what)
                    held["refused"] += 1        # the card shows the source again until the read ends
                    publish()
                elif what == time_depth_models.BY_HAND:
                    held["prefilled"] = ""
                    publish()
                else:
                    held["refusal"] = ("the session's own model holds no property: its TDLaws make its"
                                       " velocity — choose a grid of the data to read one of its properties")
                    held["refused"] += 1
                    publish()
                return
            if op == "prefill":
                fills.prefill(str(edit.get("what") or ""))
                return
            if op == "add_column":
                _auto_if_unset()              # the centre is the data's when there is some
                x, y = edit.get("x"), edit.get("y")
                if edit.get("at") == "centre":
                    x, y = m.free_spot() or (None, None)
                had = bool(m.columns)
                held["active"] = m.add_column(x, y)
                c = m.columns[held["active"]]
                c.name = str(edit.get("name") or "").strip()[:40] or None
                if had and not c.placed():
                    # among others, it takes the velocity model's law where it is placed
                    c.law.points.clear()
                _start_from_cube(c, force=True)
            elif op == "set_column":
                c = m.columns[int(edit["index"])]
                if edit.get("at") == "free":
                    # the Active row's "Place it": where "+ Column > at
                    # the centre" would put a new one
                    _auto_if_unset()
                    spot = m.free_spot()
                    if spot is None:
                        raise ValueError("no extent to place the TDLaw in")
                    c.x, c.y = spot
                if edit.get("x") is not None:
                    c.x = float(edit["x"])
                if edit.get("y") is not None:
                    c.y = float(edit["y"])
                _start_from_cube(c)
            elif op == "name_column":
                c = m.columns[int(edit["index"])]
                name = str(edit.get("name") or "").strip()
                c.name = name[:40] or None
            elif op == "del_column":
                del m.columns[int(edit["index"])]
            elif op == "active":
                i = int(edit["index"])
                if not 0 <= i < len(m.columns):
                    raise IndexError("no such column")
                held["active"] = i
            elif op == "cell":
                cube = held["cube"]
                if cube is None:
                    raise ValueError("no velocity model to edit")
                m.set_cell(edit["k"], edit["j"], edit["i"], edit["v"], cube.v.shape)
            elif op == "clear_cells":
                m.cells.clear()
                m.cells_shape = None
            elif op == "cube_set":
                # the four corners entered one by one: kept as a draft
                # until all four are there
                if any(edit.get(k) is not None for k in ("x0", "x1", "y0", "y1")):
                    ext = list(m.extent) if m.extent else list(held["draft"])
                    for k, name in enumerate(("x0", "x1", "y0", "y1")):
                        if edit.get(name) is not None:
                            ext[k] = float(edit[name])
                    held["draft"] = ext
                    m.extent = tuple(ext) if all(v is not None for v in ext) else None
                    held["extent_auto"] = False
                if edit.get("nx") is not None:
                    m.nx = max(1, min(200, int(edit["nx"])))
                if edit.get("ny") is not None:
                    m.ny = max(1, min(200, int(edit["ny"])))
                if edit.get("nz") is not None:
                    m.nz = max(1, min(200, int(edit["nz"])))
                if edit.get("t0") is not None or edit.get("t1") is not None:
                    t0 = float(edit["t0"]) if edit.get("t0") is not None else m.trange[0]
                    t1 = float(edit["t1"]) if edit.get("t1") is not None else m.trange[1]
                    if t1 <= t0:
                        raise ValueError("the time range ends later than it starts")
                    m.trange = (t0, t1)
            elif op == "cube_auto":
                m.extent = _auto_extent()
                held["extent_auto"] = True
            else:
                if op not in ("set", "add", "del", "reset"):
                    print(f"[fespp] time-depth law: gesture refused: {edit!r}", flush=True)
                    return
                if edit.get("column") is not None:
                    # a gesture on a track names its column: it becomes the active one
                    i = int(edit["column"])
                    if not 0 <= i < len(m.columns):
                        raise IndexError("no such column")
                    held["active"] = i
                law = _edited()
                if op == "set":
                    i = int(edit["index"])
                    if edit.get("velocity") is not None:
                        law.set_velocity(i, edit["velocity"])
                    elif i == 0:
                        law.set_start(depth=edit.get("depth"), twt=edit.get("twt"))
                    else:
                        law.set_point(i - 1, depth=edit.get("depth"), twt=edit.get("twt"))
                elif op == "add":
                    law.add_point(depth=edit.get("depth"), twt=edit.get("twt"))
                elif op == "del":
                    if int(edit["index"]) < 1:
                        raise IndexError("the start is moved, not deleted")
                    law.del_point(int(edit["index"]) - 1)
                elif op == "reset":
                    law.points.clear()
                else:
                    print(f"[fespp] time-depth law: gesture refused: {edit!r}", flush=True)
                    return
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            print(f"[fespp] time-depth law: gesture refused: {edit!r} ({exc})", flush=True)
            return
        print(f"[fespp] journal time-depth law: {edit}", flush=True)
        held["touched"] = True
        _changed()

    def _doc_of(fields, entry):
        """A model's fields as the session keeps them; `entry` None, the
        inputs of one not generated yet (`generated` false)."""
        if fields.get("data"):
            # a grid of the data read as it is: named, a restore reads it again
            return {"name": entry["name"], "from": entry["from"], "data": fields["data"],
                    "velocity": (fields.get("velocity") or {}).get("path") or ""}
        m = fields["model"]
        uuids = getattr(ctx, "time_depth_tree_uuids", lambda _mid: None)(entry["id"]) if entry else None
        return {**m.to_dict(), "extent_from": _extent_from(m, fields["extent_auto"]),
                "active": fields["active"], **({} if fields["touched"] else {"touched": False}),
                **({"name": entry["name"]} if entry else {"generated": False}),
                **({"uuids": uuids} if uuids else {}),
                **({"from": entry["from"]} if entry and entry["from"] else {}),
                **({"prefilled": fields["prefilled"]} if fields["prefilled"] else {})}

    def doc():
        """The active model as the session keeps it — with none, the inputs
        of the one to generate —, with where its zone comes from and the
        column edited, its name; the others under `others`."""
        others = [{**_doc_of(e, e), **({"converting": True} if e["id"] == models.serving else {})}
                  for e in models.parked()]
        return {**_doc_of(held, models.active()), **({"others": others} if others else {})}

    def _not_generated(one):
        """Whether `one` (a model of a document) holds the inputs of a model
        not generated. A document older than `generated` names its models
        but the default one: that one is a model when somebody touched it
        and its law converts."""
        if "generated" in one:
            return not one["generated"]
        if one.get("name"):
            return False
        return one.get("touched", True) is False or not Model.from_dict(one).has_law()

    def _read_doc(doc):
        """The active model is the one `doc` holds."""
        held["model"] = m = Model.from_dict(doc)
        try:
            held["active"] = max(0, min(int(doc.get("active") or 0), len(m.columns) - 1))
        except (TypeError, ValueError) as exc:
            print(f"[fespp] time-depth model: the active column not read ({exc})", flush=True)
            held["active"] = 0
        held["extent_auto"] = doc.get("extent_from") == "data"
        held["prefilled"] = doc.get("prefilled") if doc.get("prefilled") in PREFILLED else ""
        held["touched"] = doc.get("touched", True)
        # a document's TDLaws are its own: none is added to them
        held["seeded"] = True
        _rebuild()

    again = {"data": None}      # a restored session's active model of the data, to read again

    def restore(doc):
        """Every model of the session replaced by those of `doc`. A model of
        the data — a grid read as it is — holds nothing to put back: the
        active one is read again once the session's reads are in
        (`restore_data`), a parked one is chosen again in the card."""
        forget = getattr(ctx, "time_depth_tree_forget", None)
        if forget is not None:
            forget()
        models.reset()
        held.update(blank())
        again["data"] = None
        inputs, converting = None, None
        for one in [*(doc.get("others") or ()), doc]:
            if one.get("data"):
                if one is doc:
                    again["data"] = {k: one.get(k) for k in ("data", "velocity", "from")}
                continue
            if _not_generated(one):
                inputs = one if one is doc else inputs
                continue
            mid = models.add(str(one.get("name") or "") or None, str(one.get("from") or ""), one.get("uuids"))
            _read_doc(one)
            converting = mid if one.get("converting") else converting
        if inputs is not None:
            # the inputs the session was saved with, and the model that
            # converted meanwhile (the last one, in a document that names none)
            if converting is not None:
                models.switch(converting)
            models.to_draft()
            if inputs.get("touched", True):
                _read_doc(inputs)
        _changed()

    def restore_data():
        """The session's reads are in: its model of the data is read again
        (app/session_host calls this after them)."""
        saved, again["data"] = again["data"], None
        if saved:
            choice.again(saved)

    def _zone_follows_files(**_):
        """A file read or closed moves a zone nobody typed. True when it did."""
        if not held["extent_auto"]:
            return False
        zone = _zone_of_files()
        if zone is None or tuple(zone) == tuple(model().extent or ()):
            return False
        model().extent = zone
        _recentre_lone()
        _changed()
        return True

    on_change = getattr(state, "change", None)
    if callable(on_change):      # trame's state; a test's plain dict has none
        on_change("assembly_rev", "lazy_rev")(_zone_follows_files)

        @on_change("ui_has_data", "ui_loaded_rep_paths")
        def _data_read(**_):
            # the pre-fill menu opens once a file is read; the first object
            # ticked gives the model its zone, the column it starts with
            # standing in it. The ticks do not move it after that: a model
            # rewritten at each tick for nothing
            m = model()
            if m.extent is None and all(v is None for v in held["draft"]) and _try_auto_extent():
                _recentre_lone()
                _changed()
                return
            publish()

    ctx.time_depth_law = model
    ctx.time_depth_ensure_zone = _ensure_zone
    ctx.time_depth_cube = lambda: held["cube"]
    # of the model the conversions read: its key, its cube, and its grid of
    # the data read as it is with the row of its velocity ("" when the model
    # is the session's)
    ctx.time_depth_cube_key = lambda: _converting()[0]
    ctx.time_depth_convert_cube = lambda: _converting()[1]
    ctx.time_depth_data_grid = lambda: _converting()[2]
    ctx.time_depth_data_velocity = lambda: _converting()[3]
    ctx.time_depth_preview = lambda: (held.get("preview"), held.get("preview_key") or "")
    ctx.time_depth_active = _active_drawn
    ctx.time_depth_columns = _columns
    def _note(text):
        held["note"] = text
        publish()

    ctx.time_depth_law_note = _note
    ctx.time_depth_law_doc = doc
    ctx.time_depth_law_restore = restore
    ctx.time_depth_law_restore_data = restore_data
    ctx.time_depth_law_listeners = list(getattr(ctx, "time_depth_law_listeners", None) or [])
    def _card_views():
        mv = core.mv()
        return list(mv.panel_ids_of_kind(VIEW) or ()) if mv is not None else []

    fills = time_depth_prefills.register(held, _changed=_changed, publish=publish, _ask=_ask, _query=_query,
                                         _channels=_channels, _markers=_markers, _grids=_grids,
                                         _trajectories=_trajectories, _defer=_defer, _card_views=_card_views)
    ctx.time_depth_prefill_check = fills.check
    on_change = getattr(state, "change", None)
    if callable(on_change):
        on_change("ui_open_view_kinds", "assembly_rev")(lambda **_: fills.check())
    choice = time_depth_models.register(core, held, models, changed=_changed, publish=publish,
                                        zone_follows=_zone_follows_files, query=_query, xml_of=fills.xml_of)
    _rebuild()
    publish()
    return model
