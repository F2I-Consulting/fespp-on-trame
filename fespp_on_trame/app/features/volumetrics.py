"""volumetrics with fluid contacts (engine/volumetrics_dispatch)
a TOOL of a 3D view, like the slicers and the thresholds: it acts on the
grid active in THAT view and draws the contacts there — one state per
view (`ui_volumetrics__<vid>`), never a session panel

(Moved out of app/boot, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.engine import stats_dispatch
from fespp_on_trame.engine import welllog_dispatch
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import tree_grammar
from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.engine.state_defaults import z_scale_of


def register(core, *, _defer, _display_title, _globe_scene,
             _panel_tick_read, _push_card_arrays, _pv_view_of,
             _refresh_values, _say, _set_tool_target,
             _volumetrics_rep):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_push_volumetrics, _refresh_welllog, _volumetrics, _wellbore_of)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    scheduler = core.scheduler
    displays = core.displays
    _mv = core.mv
    # --- volumetrics with fluid contacts (engine/volumetrics_dispatch) -------
    # a TOOL of a 3D view, like the slicers and the thresholds: it acts on the
    # grid active in THAT view and draws the contacts there — one state per
    # view (`ui_volumetrics__<vid>`), never a session panel
    _volumetrics = {}

    def _vol(vid):
        return _volumetrics.setdefault(vid, {
            "params": {"grid": "", "poro": "", "ntg": "", "sw": "", "region": "",
                       "goc": None, "owc": None, "show_contacts": False,
                       # surface conditions, optional: the HCPV to STOIIP /
                       # GIIP and the recoverable part
                       "bo": None, "bg": None, "rf_oil": None, "rf_gas": None},
            "result": {},
            "planes": {},      # contact name -> the Plane proxy drawn in the view
        })

    def _volumetrics_sync_grid(vid, force=False):
        """The card follows the view's active grid: when the chosen grid is
        gone (or none was chosen, or `force`), the view's Reservoir grid
        takes its place and the terms are picked again from its kinds; a
        term the user set stays as long as its property is loaded."""
        from fespp_on_trame.engine import volumetrics_dispatch as vd
        v = _vol(vid)
        p = v["params"]
        before = p.get("grid")
        grids = {g["path"] for g in vd.grid_choices(state, tree)}
        changed = force or p.get("grid") not in grids
        if changed:
            # a grid the user picked stays; only a missing one is replaced
            if p.get("grid") not in grids:
                rep_path = _volumetrics_rep(vid)
                p["grid"] = rep_path if rep_path in grids else (sorted(grids)[0] if grids else "")
            for k in ("poro", "ntg", "sw", "region"):
                p[k] = ""
            v["result"] = {}
        props = vd.property_choices(state, tree, p.get("grid") or "")
        known = {x["path"] for x in props}
        picks = vd.auto_pick(props) if changed else {}
        for key in ("poro", "ntg", "sw", "region"):
            if changed:
                p[key] = picks.get(key) or ""
            elif p.get(key) and p.get(key) not in known:
                p[key] = ""
        # the contact planes belong to the grid: a grid that went (or was
        # replaced) takes them with it, as a grid picked in the card does
        if p.get("grid") != before and (v["planes"] or p.get("show_contacts")):
            _update_contact_planes(vid)
        return props

    def _push_volumetrics(vid):
        if not vid or not per_view_state.is_live(vid):
            return
        from fespp_on_trame.engine import volumetrics_dispatch as vd
        try:
            v = _vol(vid)
            props = _volumetrics_sync_grid(vid)
            out = {"grids": vd.grid_choices(state, tree), "props": props,
                   "params": dict(v["params"])}
            out.update(v["result"] or {})
            out["csv"] = vd.csv_payload(v["result"])
            # the percentile warning follows the CHOICE, not the last
            # compute: a term is flagged where it is picked, before the
            # table exists (the CSV header keeps the computed table's own)
            out["percentile_terms"] = vd.percentile_warnings(v["params"], props)
            state[f"ui_volumetrics__{vid}"] = out
            grid = v["params"].get("grid") or ""
            _set_tool_target(vid, "volumetrics",
                             _display_title(grid) if grid else "")
        except Exception as exc:
            print(f"[fespp] volumetrics error ({vid}):", exc, flush=True)

    def _update_contact_planes(vid):
        """The contacts as horizontal planes through the data in THIS view:
        orange for the GOC, blue for the OWC, at the view's Z scale."""
        v = _vol(vid)
        p = v["params"]
        mv = _mv()
        pv_view = mv.get_pv_view(vid) if mv is not None else None
        for name in list(v["planes"]):
            _drop_contact_plane(vid, name)
        v["planes"] = {}
        # the planes are drawn in the local CRS: none on the Earth (D8)
        if pv_view is None or _globe_scene(vid) is not None:
            return
        if not p.get("show_contacts") or not p.get("grid"):
            scheduler.mark_dirty(vid)
            scheduler.flush()
            return
        try:
            b = list(active_data_source.get_source().GetDataInformation().GetBounds())
        except Exception:
            b = None
        if not b or not all(abs(x) < 1e12 for x in b[:4]) or b[0] > b[1]:
            scheduler.mark_dirty(vid)
            scheduler.flush()
            return
        zs = z_scale_of(state, vid)
        pad = 0.05 * max(b[1] - b[0], b[3] - b[2], 1.0)
        x0, x1, y0, y1 = b[0] - pad, b[1] + pad, b[2] - pad, b[3] + pad
        for name, colour in (("goc", (1.0, 0.55, 0.1)), ("owc", (0.15, 0.45, 0.9))):
            depth = p.get(name)
            try:
                depth = float(depth) if depth not in (None, "") else None
            except (TypeError, ValueError):
                depth = None
            if depth is None:
                continue
            z = -depth
            try:
                plane = pvsimple.Plane(registrationName=f"contact_{name}__{vid}")
                plane.Origin = [x0, y0, z]
                plane.Point1 = [x1, y0, z]
                plane.Point2 = [x0, y1, z]
                disp = pvsimple.Show(plane, pv_view)
                disp.DiffuseColor = list(colour)
                disp.AmbientColor = list(colour)
                disp.Opacity = 0.35
                disp.Scale = [1.0, 1.0, zs]
                try:
                    disp.Pickable = 0
                except Exception:
                    pass
                v["planes"][name] = plane
                displays.add(vid, f"plane:{name}", "contact_plane", disp,
                             close=lambda v_=vid, n=name: _drop_contact_plane(v_, n))
            except Exception as exc:
                print(f"[fespp] contact plane {name} ({vid}):", exc, flush=True)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    def _drop_contact_plane(vid, name):
        """One contact plane of a view put away."""
        displays.remove(vid, f"plane:{name}")
        plane = (_volumetrics.get(vid) or {}).get("planes", {}).pop(name, None)
        if plane is None:
            return
        try:
            pv_view = _pv_view_of(vid)
            if pv_view is not None:
                pvsimple.Hide(plane, pv_view)
            pvsimple.Delete(plane)
        except Exception as exc:
            print(f"[fespp] contact plane {name} drop ({vid}):", exc, flush=True)

    @controller.set("volumetrics_refresh")
    def volumetrics_refresh(view_id):
        """The card just opened in this view: its choices and the view's
        grid."""
        _push_volumetrics(view_id)

    @controller.set("volumetrics_set")
    def volumetrics_set(key, value, view_id):
        v = _vol(view_id)
        p = v["params"]
        if key not in p:
            return
        if key in ("goc", "owc", "bo", "bg", "rf_oil", "rf_gas"):
            try:
                value = float(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                value = None
        elif key == "show_contacts":
            value = bool(value)
        else:
            value = value or ""
        if key == "grid":
            p["grid"] = value
            _volumetrics_sync_grid(view_id, force=True)
        else:
            p[key] = value
        if key in ("goc", "owc", "show_contacts", "grid"):
            _update_contact_planes(view_id)
        _push_volumetrics(view_id)

    @controller.set("volumetrics_compute")
    def volumetrics_compute(view_id):
        from fespp_on_trame.engine import volumetrics_dispatch as vd
        v = _vol(view_id)
        try:
            v["result"] = vd.compute(state, tree, source_registry, dict(v["params"]))
        except Exception as exc:
            print(f"[fespp] volumetrics compute error ({view_id}):", exc, flush=True)
            v["result"] = {"rows": [], "totals": [], "note": f"error: {exc}"}
        _push_volumetrics(view_id)
        return v["result"]

    @state.change("ui_loaded_array_paths", "ui_loaded_rep_paths")
    def _on_volumetrics_inputs(**_):
        # every live view re-reads its choices: the card is built (and asks
        # for its first refresh) BEFORE its view is wired live, so a view
        # registered only by that first refresh would otherwise never get one
        for vid in list(getattr(ctx, "blockscope_scenes", None) or {}):
            _push_volumetrics(vid)

    @state.change("ui_loaded_array_paths")
    def _on_ticked_arrays(**_):
        # a property ticked or unticked: the Thresholds card's list and the
        # Attributes card's columns follow the tree (the manager, 15/10: they
        # kept what was ticked when the node was activated)
        for vid in list(getattr(ctx, "blockscope_scenes", None) or {}):
            if not per_view_state.is_live(vid):
                continue
            try:
                _push_card_arrays(vid, getattr(state, f"active_path__{vid}", None) or "")
                _refresh_values(vid)
            except Exception as exc:
                print(f"[fespp] ticked arrays ({vid}):", exc, flush=True)

    def _wellbore_of(path):
        """The wellbore a node belongs to — itself when it is one."""
        nid = tree.find_node_id(path)
        if nid is None:
            return path
        if (tree.find_type(nid) or "") == "Wellbore":
            return path
        wid = tree.find_parent_node_id_with_type(nid, "Wellbore")
        return tree.find_path(wid) if wid is not None else path

    def _wellbores_of(path):
        """The wellbores a TICK stands for: the well the node belongs to, or
        every well under it when the tick is a folder above them — a folder
        stands for its subtree, in this tree as in every other."""
        nid = tree.find_node_id(path)
        if nid is None:
            return [path]
        if (tree.find_type(nid) or "") == "Wellbore":
            return [path]
        wid = tree.find_parent_node_id_with_type(nid, "Wellbore")
        if wid is not None:
            return [tree.find_path(wid)]
        out = []
        for did in tree.find_all_descendant_ids(nid):
            if (tree.find_type(did) or "") == "Wellbore":
                path_below = tree.find_path(did)
                if path_below:
                    out.append(path_below)
        return out

    def _is_curve(path):
        """A well's log: a curve the log view draws."""
        return node_facts.is_log(tree, path)

    def _well_curves(well):
        """Every log of the wellbore `well`."""
        wid = tree.find_node_id(well)
        if wid is None:
            return []
        paths = (tree.find_path(did) for did in tree.find_all_descendant_ids(wid))
        return [p for p in paths if p and node_facts.is_log(tree, p)]

    def _welllog_channels(vid):
        """What a log panel DRAWS: the read channels and markers of the wells
        it holds, less the ones its own tree has unticked. Unticking there
        means "out of this log" and never "unloaded" — a curve a 3D view is
        showing is not pulled out of the scene because a log dropped it."""
        out = set(getattr(state, f"welllog_dropped__{vid}", None) or [])
        return [p for p in (getattr(state, "selected_paths", None) or [])
                if p not in out]

    def _welllog_ticks(vid):
        """A log tree's checkboxes: the wells the log holds, and under each
        of them what the panel is drawing."""
        wells = list(getattr(state, "ui_welllog_wells", None) or [])
        if not wells:
            return []
        held = set(wells)
        return wells + [p for p in _welllog_channels(vid)
                        if p not in held and _wellbore_of(p) in held]

    # What the server last PUBLISHED as each log tree's checkbox set. An
    # untick is read against THIS and never against the session's selection:
    # a node the tree has never shown ticked cannot have been unticked, and
    # a panel opened on a log that already holds its wells would otherwise
    # read its own seed — the wellbores alone — as "the reader threw every
    # curve away".
    _welllog_published = {}

    @controller.set("welllog_tree_ticks")
    def welllog_tree_ticks(view_id):
        """Publish this log tree's checkbox set — the wells the panel holds
        and, under each of them, what it draws. Called by the tree as it is
        built, so its seed is the full set rather than the wells alone."""
        vid = str(view_id or "")
        ticks = _welllog_ticks(vid)
        _welllog_published[vid] = set(ticks)
        state[f"welllog_tree_selected__{vid}"] = ticks

    def _sync_welllog_trees():
        """Every open log tree's checkboxes ARE what the log holds: a well
        added by a right-click ticks its wellbore, a channel that arrives
        with it ticks itself."""
        mv = _mv()
        if mv is None:
            return
        live = set(mv.panel_ids_of_kind("welllog"))
        for dead in [v for v in _welllog_published if v not in live]:
            _welllog_published.pop(dead, None)
        for vid in live:
            var = f"welllog_tree_selected__{vid}"
            ticks = _welllog_ticks(vid)
            _welllog_published[vid] = set(ticks)
            if set(getattr(state, var, None) or []) != set(ticks):
                state[var] = ticks

    @controller.set("welllog_tree_wells")
    def welllog_tree_wells(view_id, paths, read=True):
        """The log view's own tree: ticking puts the wellbore IN THE LOG.

        One grammar (`engine/tree_grammar`): a tick in a panel's tree puts
        the object in that panel and reads it — the trajectory, the frames
        and the channels the curves are drawn from, through the one channel
        that loads, so the log fills with what was ticked instead of the
        wellbore landing in the 3D scene and the panel staying empty.
        Unticking takes the well out of the log and unloads nothing.

        The wells are what the tick names: whatever node was ticked resolves
        up to its wellbore, because the log correlates wellbores and ticking
        a trajectory or a marker frame means "this well", not "this array".
        Under a well the log already held, an unticked node has left THIS
        log — it is dropped from what the panel draws and stays loaded. What
        counts as "unticked" is read against the tick set the server last
        published for this view, never against the session's selection: a
        node this tree never showed was never the reader's to untick.
        """
        vid = str(view_id or "")
        incoming = {p for p in (paths or ()) if p}
        if vid in _welllog_published and incoming == _welllog_published[vid]:
            # the server's own rewrite coming back, not a gesture
            return
        before = list(getattr(state, "ui_welllog_wells", None) or [])
        dropped_var = f"welllog_dropped__{vid}"
        dropped_before = list(getattr(state, dropped_var, None) or [])
        ticked = [p for p in (paths or ()) if p]
        wells = tree_grammar.panel_wells(ticked, _wellbores_of)
        # a tick that stands for no wellbore at all would come off again with
        # no word said — the one thing this panel may not do
        for path in ticked:
            if not _wellbores_of(path):
                _say(f"{_display_title(path, 'That node')} holds no wellbore"
                     " — this log correlates wellbores.")
                break
        # What left the log without leaving the session: a node the tree WAS
        # showing ticked, under a well that STAYS, unticked by this gesture.
        # A well that has just arrived brings everything it has — nothing
        # under it has been refused yet — and a well that leaves takes its
        # refusals with it, so adding it back brings its curves back too.
        fresh = set(wells) - set(before)
        held, seen = set(wells), set(ticked)
        kept = held - fresh
        published = _welllog_published.get(vid, seen)
        gone = [p for p in published
                if p not in seen and p not in held and _wellbore_of(p) in kept]
        dropped = [p for p in dropped_before
                   if p not in seen and _wellbore_of(p) in kept]
        dropped += [p for p in gone if p not in dropped]
        # a well brought in by some of its curves alone brings those
        dropped += [p for p in tree_grammar.curves_alone(ticked, fresh, _wellbore_of, _is_curve, _well_curves)
                    if p not in dropped]
        def _hold():
            """What the log holds, once the read is going ahead. Taking the
            well in BEFORE the question would show a panel holding a wellbore
            with nothing in it while the dialog is still asking."""
            moved = wells != list(getattr(state, "ui_welllog_wells", None) or [])
            if moved:
                state.ui_welllog_wells = wells
            if set(dropped) != set(getattr(state, dropped_var, None) or []):
                # nothing else watches this: the session's selection has not
                # moved, only what THIS log makes of it
                state[dropped_var] = dropped
                _refresh_welllog()
            if not moved:
                # `_on_welllog_inputs` re-syncs the boxes whenever the wells
                # or the read move; when neither did (a curve unticked out of
                # this log) nothing else will, so it is done here. Writing
                # them in the same flush as the read instead would put a
                # stale echo — the wells alone — back through the tree's
                # watcher, against a baseline the read has already advanced,
                # and the log would drop every curve it has just been given.
                _sync_welllog_trees()

        def _cancel():
            # the boxes the reader ticked come off again, in sight
            _sync_welllog_trees()

        if not read:
            # an eye, a tick's take or an unload's prune (app/scene/
            # panel_trees): nothing to read — asking would read the wellbore
            # node, which the selection need not hold, and start a load
            _hold()
            return
        # the ticked nodes themselves: the selection cascade turns a wellbore
        # into its trajectory, its frames and its channels
        _panel_tick_read(ticked, _cancel, _hold)

    # the well-log in the one grammar (app/scene/panel_trees): the eye of its
    # tree is "drawn in this log" — a wellbore, or a curve under it
    def _welllog_vids():
        mv = _mv()
        return list(mv.panel_ids_of_kind("welllog")) if mv is not None else []

    core.panel_trees.add(
        "welllog", vids=_welllog_vids,
        held=lambda vid: list(_welllog_ticks(vid)),
        hold=lambda vid, paths: welllog_tree_wells(vid, paths, read=False),
        title=lambda vid: _mv().title_of(vid) if _mv() is not None else "Log view")

    @controller.set("welllog_tree_action")
    def welllog_tree_action(view_id, ev):
        """The right-click menu of the log tree: in or out of this view, and
        the one act that leaves it — lighting the well up in a 3D view.

        Membership goes through the very routing the checkbox uses, so the
        menu and the tick cannot mean two different things."""
        ev = ev if isinstance(ev, dict) else {}
        action, path = ev.get("action"), ev.get("path")
        if not action or not path:
            return
        # the WHOLE tick set, not just the wells: the routing reads what is
        # missing from it as "taken out of this log", and a menu that sent
        # the wells alone would drop every curve the panel is drawing
        ticks = _welllog_ticks(str(view_id or ""))
        if action == "welllog-add":
            welllog_tree_wells(view_id,
                               ticks + ([path] if path not in ticks else []))
        elif action == "welllog-remove":
            welllog_tree_wells(view_id, [p for p in ticks if p != path
                                         and _wellbore_of(p) != path])
        elif action == "highlight-3d":
            controller.highlight_rep(path)
        elif action == "highlight-off":
            controller.unselect_rep(path)

    def _refresh_welllog():
        _defer("welllog", _refresh_welllog_now)

    def _refresh_welllog_now():
        """Rebuild the correlation panel's payload from the CHECKED channels
        and markers of every wellbore the user sent to it.

        Reading a channel means fetching its block to the server, so this only
        runs when the panel actually exists — no panel, no cost."""
        mv = _mv()
        if mv is None:
            return
        panels = mv.panel_ids_of_kind("welllog")
        if not panels:
            return
        wells = list(getattr(state, "ui_welllog_wells", None) or [])
        if wells:
            # the band of the log needs the column: built now if stale
            controller.ensure_stratigraphy()
        # the "from grid" sampling is a preview: switched off, a session's
        # requests draw nothing the panel could take back out
        from fespp_on_trame.app.core import previews
        requests = (getattr(state, "ui_welllog_synth", None) or []
                    if previews.offered("log_sample") else [])
        try:
            from fespp_on_trame.engine import trajectory_sampling
            synth = trajectory_sampling.curves_for(
                state, tree, source_registry, requests)
        except Exception as exc:
            print("[fespp] well-log payload error:", exc, flush=True)
            return
        # the CRS the 3D views letter their Z with: a well's TVD unit when
        # its trajectory names no CRS that can be read
        try:
            depth_crs = controller.detect_crs("depth", True)
        except Exception as exc:
            print("[fespp] well-log depth CRS:", exc, flush=True)
            depth_crs = None
        for pid in panels:
            # Built per panel because the tree of each one says which of the
            # read channels it holds: unticking a curve takes it out of THIS
            # log and unloads nothing, so the panel cannot read the session's
            # selection as it is. The log view is a singleton, so this loop
            # runs once.
            try:
                payload = welllog_dispatch.build_payload(
                    tree, source_registry, wells, _welllog_channels(pid),
                    strati_columns=getattr(state, "ui_strati_columns", None),
                    synthetics=synth, depth_crs=depth_crs)
            except Exception as exc:
                print("[fespp] well-log payload error:", exc, flush=True)
                return
            # each panel has its own cutoffs, applied on its payload;
            # a NEW dict every time: the widget watches the reference
            rules = getattr(state, f"welllog_cutoffs__{pid}", None) or []
            own = (welllog_dispatch.with_cutoffs(payload, rules) if rules
                   else dict(payload))
            # the datum the user flattened on survives the rebuild
            own["flattenOn"] = getattr(state, f"welllog_flatten__{pid}", None)
            # the undecimated samples fed the statistics; the client draws
            # the decimated ones and must not carry both over the websocket
            own["wells"] = [{k: v for k, v in w.items() if k != "_full"}
                            for w in (own.get("wells") or [])]
            own["csv"] = welllog_dispatch.zones_csv_payload(own, rules)
            state[f"welllog_data__{pid}"] = own
            # what follows the log view (`ctx.welllog_listeners`: [(panel, payload) -> None]),
            # the 3D views drawing its curves in its colours
            for listen in getattr(ctx, "welllog_listeners", None) or ():
                listen(pid, own)

    # ui_strati_columns belongs here: the column can land AFTER a well is
    # already in the panel, and without a rebuild that well keeps the empty
    # stratigraphic band it was first drawn with.
    @state.change("ui_welllog_wells", "selected_paths", "ui_loaded_rep_paths",
                  "ui_strati_columns", "ui_welllog_synth")
    def _on_welllog_inputs(**_):
        _refresh_welllog()
        # the tree's ticks ARE what the log holds: the curves a tick has just
        # had read tick themselves, and unticking one afterwards drops that
        # one instead of everything the tree was not yet showing as held
        _sync_welllog_trees()

    @state.change("ui_welllog_wells", "ui_loaded_array_paths")
    def _on_welllog_synth_choices(**_):
        """What the panel's "from grid" editor can offer: the wellbores in
        the panel, and the loaded properties that live on a grid — a channel
        cannot be sampled along a trajectory, it IS one."""
        wells = []
        for p in list(getattr(state, "ui_welllog_wells", None) or []):
            nid = tree.find_node_id(p)
            wells.append({"title": (tree.find_title(nid) if nid is not None
                                    else None) or p, "value": p})
        props = []
        for p in list(getattr(state, "ui_loaded_array_paths", None) or []):
            rep_path = stats_dispatch._rep_path_for_array_path(tree, p)
            rid = tree.find_node_id(rep_path) if rep_path else None
            if rid is None or (tree.find_type(rid) or "") not in (
                    "IjkGrid", "UnstructuredGrid"):
                continue
            nid = tree.find_node_id(p)
            props.append({
                "title": stats_dispatch._title_and_kind(tree, p)[0] or p,
                "value": p,
                "unit": welllog_dispatch._attr(tree, nid, "uom"),
                "kind": welllog_dispatch._attr(tree, nid, "propertyKind"),
            })
        state.welllog_synth_choices = {"wells": wells, "props": props}

    # the cutoffs are per view, a name no decorator here can spell: the panel
    # registers its own change handler and calls back through this
    @controller.set("refresh_welllog")
    def refresh_welllog():
        _refresh_welllog()

    return (_push_volumetrics, _refresh_welllog, _volumetrics, _wellbore_of)
