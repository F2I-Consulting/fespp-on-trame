"""Globe views (engine/blockscope/globe_scene.py): the projected CRS of
the data, the card's state and its controllers.
The Earth texture ships INSIDE the package (assets/, declared in
setup.cfg package_data): in the container the code runs from the venv
site-packages, so a repo-relative path would resolve to nothing and the
Globe would silently lose its texture.
Earth imagery: several resolutions ship side by side and the Globe card
picks one. A whole-Earth texture can never be sharp at reservoir scale
(even 16k is 2.4 km per pixel), so this buys the regional zooms, which is
where the context is actually read.

(Moved out of app/boot, overhaul slice 10.)"""
import sys
from fespp_on_trame.engine import repo_query
from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.engine.utils import numfmt


def register(core):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_any_usable_crs, _detect_crs, _etp_on, _frame_first, _globe_refresh_marks, _globe_scene, _loaded_content, _publish_globe_availability, _push_globe_state)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    etp_connector = core.etp_connector
    active_data_source = core.active_data_source
    scheduler = core.scheduler
    batcher = core.batcher
    eyes = core.eyes
    _mv = core.mv
    # Globe views (engine/blockscope/globe_scene.py): the projected CRS of
    # the data, the card's state and its controllers.
    # The Earth texture ships INSIDE the package (assets/, declared in
    # setup.cfg package_data): in the container the code runs from the venv
    # site-packages, so a repo-relative path would resolve to nothing and the
    # Globe would silently lose its texture.
    # Earth imagery: several resolutions ship side by side and the Globe card
    # picks one. A whole-Earth texture can never be sharp at reservoir scale
    # (even 16k is 2.4 km per pixel), so this buys the regional zooms, which is
    # where the context is actually read.
    from fespp_on_trame.engine import geo as _geo_assets
    state.ui_globe_textures = _geo_assets.earth_textures_available()
    state.setdefault("ui_globe_texture", _geo_assets.EARTH_TEXTURE_DEFAULT)
    state.setdefault("ui_globe_texture_note", "")
    _crs_cache = {}

    def _loaded_content():
        """What the reader holds, as a hashable key: whether a server is
        read, how many files the EPC collector was given, their names, the
        dataspaces loaded. A selection changes none of it, so what depends
        on the objects' definitions alone (a CRS, an array's name and codes)
        is kept under this key, never under the reader's AssemblyTag, which
        every step of a stepped read bumps."""
        src = active_data_source.get_source()
        # (the EPC collector's file list; the ETP source has no such property
        # and GetProperty answers None)
        files_prop = src.GetProperty("Files") if hasattr(src, "GetProperty") else None
        n_files = files_prop.GetNumberOfElements() if files_prop is not None else -1
        return (bool(etp_connector.is_connected), n_files,
                tuple(sorted(str(f.get("name")) for f in (state.ui_loaded_files or []) if isinstance(f, dict))),
                tuple(state.ui_etp_loaded_dataspaces or []))

    def _globe_scene(view_id):
        from fespp_on_trame.engine.blockscope.globe_scene import GlobeScene
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        return scene if isinstance(scene, GlobeScene) else None

    def _etp_on():
        try:
            v = getattr(etp_connector, "is_connected", False)
            return bool(v() if callable(v) else v)
        except Exception:
            return False

    @controller.set("detect_crs")
    def _detect_crs(prefer="depth", codeless=False):
        """Projected EPSG of the loaded data (engine/geo.py), cached per CRS
        object set; `prefer` the vertical domain whose CRS answers when the
        data holds both ("time": a view switched to time names its axes
        after the time CRS, app/features/view_domain). Read through the reader query channel — fesapi's typed
        CRS accessors, not the part's XML — so it answers the same over a
        local EPC and over ETP, where there is no zip to look in. None —
        never an error — when no CRS object carries a code: the Globe card
        then asks for it. `codeless`: a CRS without a code answers too when
        none has one — what names the axes and their units needs no code
        (the PO, 29/10: drogon on ADME carries no EPSG, its axes went back
        to X Y Z while the file gives E (m) N (m))."""
        from fespp_on_trame.engine import geo
        src = active_data_source.get_source()
        # The CRS objects come with the FILES and DATASPACES read, never with
        # a selection: the answer is kept by that content (`_loaded_content`),
        # not by the reader's AssemblyTag, which every step of a stepped
        # read bumps — asking the channel for the CRS uuids again cost
        # 0.45 s a step on drogon (measured 12/10, the `step_cost` bench).
        want_time = prefer == "time"
        content = _loaded_content() if not want_time else (_loaded_content(), "time")
        if codeless:
            content = (content, "codeless")
        held = _crs_cache.get(content)
        if held is not None:
            # a CRS of the domain asked stands for this content; one of the
            # other domain, taken for want of it, only while the reader holds
            # what it held: asked while a file was being read, it was the
            # answer of the files before it
            known, read_at = held
            try:
                still = read_at is None or read_at == repo_query.tag(src)
            except Exception as exc:
                print(f"[fespp] crs: what the reader holds could not be asked ({exc!r})", flush=True)
                still = True
            if still:
                return known
        try:
            tag = repo_query.tag(src)
            uuids = tuple(repo_query.object_uuids(
                src, "AbstractLocal3dCrs", cache_tag=tag))
        except Exception:
            return None
        if not uuids:
            return None
        key = content
        info = None
        try:
            # A file can carry BOTH a depth and a time CRS, both answering
            # with the same code. Taking whichever came first would make the
            # answer depend on load order, and a time CRS puts TIME on the
            # vertical axis: the data would be placed on the Earth with a
            # height in milliseconds. Prefer depth; fall back to a time CRS
            # only when there is nothing else, so the card can still warn —
            # unless the time one is asked for.
            fallback = None
            no_code = None      # the first codeless CRS of the domain asked
            for uuid in uuids:
                found = geo.crs_info_from_fields(
                    repo_query.object_fields(src, uuid, cache_tag=tag))
                if not found:
                    continue
                if found.get("epsg") is None:
                    if codeless and no_code is None and bool(found.get("time")) == want_time:
                        no_code = found
                    continue
                if bool(found.get("time")) == want_time:
                    info = found
                    break
                fallback = fallback or found
            own = info or no_code
            info = own or fallback
        except Exception:
            return None
        _crs_cache[key] = (info, None if own is not None else tag)
        return info

    # sticky: has ANY file loaded this session carried a usable projected CRS?
    _globe_crs_seen = [False]

    def _any_usable_crs():
        """(usable, first_info, n_crs, reason) over EVERY CRS object the
        reader holds. ``_detect_crs`` stops at the first one carrying ANY
        code, so on its own a bad code would mask a good one loaded beside
        it. ``reason`` is the first projected-CRS "unknown" reason fesapi
        reports, for the card to quote when no code is found at all.

        Enumerated by fesapi TYPE, not by part name: the RESQML 2.2 CRS is a
        LocalEngineeringCompoundCrs, whose name carries no "3dCrs" at all, so
        a filename match would never see it."""
        from fespp_on_trame.engine import geo as _geo
        src = active_data_source.get_source()
        try:
            tag = repo_query.tag(src)
            uuids = list(repo_query.object_uuids(
                src, "AbstractLocal3dCrs", cache_tag=tag))
        except repo_query.ChannelMissing:
            # not "no CRS": the CRS could not be READ. The card must say
            # so, or the reader concludes the file has none.
            return False, None, 0, _CRS_NO_CHANNEL
        except Exception:
            return False, None, 0, ""
        if not uuids:
            return False, None, 0, ""
        first, reason = None, ""
        try:
            for uuid in uuids:
                info = _geo.crs_info_from_fields(
                    repo_query.object_fields(src, uuid, cache_tag=tag))
                if not info:
                    continue
                reason = reason or info.get("reason") or ""
                if info.get("epsg") is None:
                    continue
                if first is None:
                    first = info
                if not _geo.epsg_problem(info.get("epsg")) and not info.get("time"):
                    return True, info, len(uuids), reason
        except repo_query.ChannelMissing:
            return False, None, 0, _CRS_NO_CHANNEL
        except Exception:
            return False, None, 0, ""
        return False, first, len(uuids), reason

    # the one reason that is not the data's: the reader cannot be asked
    _CRS_NO_CHANNEL = ("the CRS could not be read: this FESPP build has no"
                       " object query channel — rebuild the plugin")

    def _crs_reason_text(reason):
        """The parenthesis the Globe card adds after 'CRS: unknown': the
        data's own reason, or the fact that it could not be asked."""
        if not reason:
            return ""
        if reason == _CRS_NO_CHANNEL:
            return f" ({reason})"
        return f" (the data's CRS says: {reason})"

    def _publish_globe_availability():
        """Can the loaded data be put on the Earth at all? The Globe is only
        offered when the answer is yes:

        - a projected CRS the projection accepts -> offer it
        - anything else (no CRS part, the fesapi 5215 placeholder, a
          geographic or vertical code)           -> hide it, with the reason
        - EXCEPT under ETP, kept offered: a dataspace is fetched without its
          secondary targets, so its CRS may still be a reference stub the
          reader cannot read, and the card is then the only place to supply
          the code

        A Globe view on unprojectable data can only ever come up empty, and
        silently — not offering it is the honest affordance.

        The question is asked of the WHOLE session, not of the last file: the
        collector's ``Files`` property only ever holds the most recent path, so
        looking there alone would make the answer depend on load ORDER — a bad
        CRS loaded after a good one would hide the Globe for data that
        projects fine."""
        from fespp_on_trame.engine import geo as _geo
        usable, info, n_crs, reason = _any_usable_crs()
        if usable or n_crs == 0 or _etp_on():
            # Nothing LOCAL to judge — an ETP session (no CRS part is
            # reachable, the card asks for the code) or an empty one. Keyed on
            # the absence of CRS objects rather than on _etp_on() alone: that
            # flag reads False while the connector is re-dialling, which would
            # make the button blink out mid-session.
            why = None
        elif not info:
            # what the data says about it, when it says anything — fesapi's
            # projected-CRS "unknown" reason, verbatim
            why = ("no projected EPSG code in the loaded data"
                   + _crs_reason_text(reason))
        else:
            # A file whose ONLY CRS is a time one lands here with a perfectly
            # valid code: the Globe stays offered (the horizontal projection is
            # right, it is the vertical axis that is time) and the card's hint
            # is what says so. Deliberate — hiding the view would tell the user
            # less than showing it with the warning.
            why = _geo.epsg_problem(info.get("epsg"))
        if not why:
            _globe_crs_seen[0] = True
        elif _globe_crs_seen[0]:
            # something already loaded DOES project — keep offering the Globe
            why = None
        state.ui_globe_ok = not why
        state.ui_globe_why = why or ""

    def _push_globe_state(view_id):
        scene = _globe_scene(view_id)
        if scene is None:
            return
        crs = _detect_crs()
        d = {"epsg": scene.epsg or "", "mode": scene.mode,
             "opacity": scene.earth_opacity, "where": "", "from_data": False}
        if scene.epsg:
            from_data = bool(crs) and crs.get("epsg") == scene.epsg
            # the card shows a declared code, and only opens the field when
            # the data carries none: a code the file states is not the
            # reader's to guess at
            d["from_data"] = from_data
            d["crs"] = f"CRS: EPSG:{scene.epsg}"
            if from_data and crs.get("title"):
                d["crs"] += f" — {crs['title']}"
            d["crs"] += " (from the data)" if from_data else " (typed)"
        else:
            d["crs"] = ("CRS: unknown — enter the projected EPSG code"
                        + _crs_reason_text(_any_usable_crs()[3]))
        # diagnostics a geoscientist can read: the extent as FESPP delivers
        # it (projected CRS) and where that lands — local (un-offset)
        # coordinates or a Z that is not in metres show up immediately
        hints = []
        from fespp_on_trame.engine import geo
        problem = geo.epsg_problem(scene.epsg) if scene.epsg else None
        if problem:
            hints.append(problem + " — nothing is placed on the Earth until a "
                         "projected code is entered")
        if crs and crs.get("time") and scene.epsg == crs.get("epsg"):
            hints.append("time CRS: the vertical axis is time, not depth")
        pb = scene.projected_bounds()
        if pb is not None:
            # "to" rather than an arrow, and the unit said: a projected
            # CRS is metric, and the hints below are written on that very
            # assumption ("Z is not in metres") — so the reader must see it
            def _r(lo, hi):
                return (f"{numfmt.fmt_fixed(lo, 0)} to "
                        f"{numfmt.fmt_fixed(hi, 0)} m")
            # What the two horizontal ordinates are CALLED — "Easting" /
            # "Northing" and not "X" / "Y", which are only the reader's
            # guess. The FILE is asked first (RESQML's ProjectedAxisOrder),
            # the EPSG registry second, and X/Y is what is left when neither
            # answers: a wrong name is worse than a vague one, and where the
            # name comes from is said on screen rather than assumed.
            nx, ny, src_of = geo.axis_names_of(crs, scene.epsg)
            d["axes"] = f"{nx} / {ny} — named by {src_of}" if src_of else ""
            # Z is an ELEVATION here, whatever the file calls it: VTK has no
            # other vertical, so a depth has been negated on the way in.
            d["extent"] = (f"{nx} {_r(pb[0], pb[1])}\n{ny} {_r(pb[2], pb[3])}"
                           f"\nElevation {_r(pb[4], pb[5])}")
            # ... and the SAME box read on the globe. X and Y in metres look
            # wrong to anyone expecting a position on the Earth, and they are
            # not: a projected CRS measures the ground in metres from its own
            # origin, which is exactly why it can be mapped. The degrees are
            # the reading the question asks for, so both are shown — and the
            # pair is also the check: metric X/Y that land on the wrong
            # continent name their EPSG as the culprit.
            if scene.epsg and not problem:
                try:
                    lon, lat = geo.geographic_of(
                        scene.epsg, [pb[0], pb[1], pb[0], pb[1]],
                        [pb[2], pb[2], pb[3], pb[3]])
                    d["geo_extent"] = (
                        f"lon {numfmt.fmt_fixed(min(lon), 3)} to "
                        f"{numfmt.fmt_fixed(max(lon), 3)}°   "
                        f"lat {numfmt.fmt_fixed(min(lat), 3)} to "
                        f"{numfmt.fmt_fixed(max(lat), 3)}°")
                except Exception as exc:
                    hints.append(f"the corners do not convert to lon/lat ({exc})")
                    print(f"[fespp] globe {view_id}: geographic extent:",
                          exc, file=sys.stderr, flush=True)
            if max(abs(pb[0]), abs(pb[1])) < 50000 and max(abs(pb[2]), abs(pb[3])) < 50000:
                hints.append(f"{nx}/{ny} look LOCAL (not projected): the local"
                             " CRS offsets are not applied or are zero")
        ll = scene.geographic_center()
        if ll is not None:
            # The height is not an altitude: it is the height above the
            # WGS84 ELLIPSOID, what the ECEF -> geodetic conversion yields.
            # The difference with a height above sea level is the geoid
            # undulation — some 40 m in the North Sea — so the word matters
            # to whoever reads a depth here.
            d["where"] = (f"data at lat {numfmt.fmt_fixed(ll[1], 3)}°,"
                          f" lon {numfmt.fmt_fixed(ll[0], 3)}° —"
                          f" {numfmt.fmt_fixed(ll[2], 0)} m"
                          " above the WGS84 ellipsoid")
            if abs(ll[2]) > 20000:
                hints.append("the height above the ellipsoid exceeds 20 km: "
                             "the vertical is not in meters, or its unit / "
                             "direction is off")
        elif scene.epsg and not problem and scene.visible_selectors():
            # visible blocks, usable code, yet nothing projected: worth a trace
            try:
                di = scene.geo.get_source().GetDataInformation()
                print(f"[fespp] globe {view_id}: no data bounds (points={di.GetNumberOfPoints()}"
                      f" epsg={scene.epsg} visible={len(scene.visible_selectors())})",
                      file=sys.stderr, flush=True)
            except Exception as exc:
                print(f"[fespp] globe {view_id}: no data bounds ({exc!r})", file=sys.stderr, flush=True)
        d["hint"] = " · ".join(hints)
        state[f"ui_globe__{view_id}"] = d

    def _globe_refresh_marks(vid):
        """Globe view: one locator + name per markable grid or well head (the
        scene knows selectors, the tree knows kinds and titles — a grid's
        geometry leaf is titled 'SolidColor', its grid folder carries the
        name).

        Marks are built for everything LOADED and merely toggled by the eyes:
        building one costs 4 ParaView proxies, so tying their existence to
        visibility would rebuild them on every click."""
        scene = _globe_scene(vid)
        if scene is None:
            return
        # minus the isolated: an isolated block is not drawn, so offering it as
        # a mark and a zoom target would fly the camera at nothing
        shown = set(scene.shown_selectors()) - set(scene.isolated)
        labels = {}
        for sel in set(scene.block_state) | shown:
            nid = tree.find_node_id(sel)
            kind = tree.find_type(nid) if nid is not None else None
            if kind in ("Trajectory", "WellboreTrajectory"):
                # a borehole is a few km long — at Earth scale its marker IS
                # the well head; the name lives on the parent Wellbore
                wid = tree.find_parent_node_id_with_type(nid, "Wellbore")
                labels[sel] = (((tree.find_title(wid) if wid is not None else None)
                                or tree.find_title(nid) or ""), False)
            elif kind in ("IjkGrid", "UnstructuredGrid"):
                name_path = sel.split("/_propsfolder_", 1)[0] if "/_propsfolder_" in sel else sel
                gid = tree.find_node_id(name_path)
                labels[sel] = (((tree.find_title(gid) if gid is not None else None)
                                or tree.find_title(nid) or ""), True)
        try:
            scene.set_marks(labels, shown)
        except Exception as exc:
            print(f"[fespp] globe marks error ({vid}): {exc!r}", file=sys.stderr, flush=True)

    def _frame_first(vid):
        """One-shot first-data framing: the whole Earth (locator on the data)
        for a Globe view, the data bounds otherwise, seen from the South when
        they are wells alone (_wells_only). Returns True when the
        view was framed on something with an extent (camera.py refuses to
        frame objects whose points all sit at one place): a view it returns
        False for must not count as framed, so the next object with an
        extent frames it."""
        scene = _globe_scene(vid)
        if scene is not None:
            scene.frame("earth")
            _push_globe_state(vid)
            return True
        from fespp_on_trame.app.views.camera import FROM_THE_SOUTH, reset_camera_centered
        mv = _mv()
        return reset_camera_centered(mv.get_pv_view(vid) if mv is not None else None,
                                     look=FROM_THE_SOUTH if _wells_only(vid) else None)

    # a well's own kinds, for a node the tree does not file under a Wellbore
    _WELL_KINDS = ("Trajectory", "WellboreTrajectory", "BlockedWellbore",
                   "Frame", "SeismicWellboreFrame", "MarkerFrame")

    def _wells_only(vid):
        """True when everything the view draws belongs to wells: seen from
        above a borehole is a dot, so a view whose first objects are wells
        looks at them from the side."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        shown = set(scene.shown_selectors()) if scene is not None else set()
        for sel in shown:
            nid = tree.find_node_id(sel)
            if nid is None:
                return False
            if (tree.find_type(nid) not in _WELL_KINDS
                    and tree.find_parent_node_id_with_type(nid, "Wellbore") is None):
                return False
        return bool(shown)

    @controller.set("inherit_eyes")
    def inherit_eyes(view_id, ref_view_id):
        """A view split from another with `inherit_eyes` (the Globe) starts
        showing what its reference view shows — 'where are THESE on the
        Earth' — instead of the usual empty eye set, through the eye service
        (app/scene/eyes)."""
        if not per_view_state.is_live(view_id):
            return
        try:
            eyes.inherit(view_id, ref_view_id)
        except Exception as exc:
            print(f"[fespp] inherit eyes error ({view_id}): {exc!r}", file=sys.stderr, flush=True)

    @controller.set("globe_epsg")
    def globe_epsg(code, view_id):
        scene = _globe_scene(view_id)
        if scene is None:
            return
        try:
            n = int(str(code).strip().upper().replace("EPSG:", "").strip() or 0)
        except ValueError:
            n = 0
        if n != scene.epsg:
            scene.set_epsg(n)
            if n:
                # The data MOVED, so re-fly to the object we were on — not to
                # `mode` alone: a bare "data" mode would re-frame the union of
                # everything visible, putting back through this text field
                # exactly the framing the per-grid zoom exists to replace.
                scene.frame(scene.mode, scene._framed)
            pins = getattr(ctx, "time_depth_pins_refresh", None)
            if pins is not None:
                pins(view_id)
        _push_globe_state(view_id)
        scheduler.flush()

    @controller.set("globe_frame")
    def globe_frame(mode, view_id, selector=None):
        """"earth" = the whole planet; anything else = fly onto `selector`.

        There is deliberately no "everything visible" framing: with two
        reservoirs loaded it would aim at the midpoint between them and show
        neither."""
        scene = _globe_scene(view_id)
        if scene is None:
            return
        scene.frame("earth" if mode == "earth" else "block", selector)
        _push_globe_state(view_id)
        scheduler.flush()

    @controller.set("globe_texture")
    def globe_texture(quality):
        """Earth imagery quality — a session preference, not a per-view one:
        two Globe views of the same session showing different sharpness would
        read as a bug."""
        from fespp_on_trame.engine import geo as _g
        from fespp_on_trame.engine.blockscope.globe_scene import GlobeScene
        # Every session is its own process and nothing caps how many run, so
        # the finest imagery is granted only if the machine can still spare
        # it — otherwise the OOM killer takes the fattest process, which is
        # somebody else's session.
        granted, note = _g.earth_texture_affordable(quality)
        state.ui_globe_texture = granted
        state.ui_globe_texture_note = note
        path = _g.earth_texture_path(granted)
        for scene in (getattr(ctx, "blockscope_scenes", None) or {}).values():
            if isinstance(scene, GlobeScene):
                scene.set_texture(path)
        scheduler.flush()

    @controller.set("globe_opacity")
    def globe_opacity(value, view_id):
        def _commit():
            scene = _globe_scene(view_id)
            if scene is None:
                return
            scene.set_earth_opacity(value)
            _push_globe_state(view_id)
            scheduler.flush()
        batcher.schedule(f"globe_opacity_{view_id}", _commit)
    return (_any_usable_crs, _detect_crs, _etp_on, _frame_first, _globe_refresh_marks, _globe_scene, _loaded_content, _publish_globe_availability, _push_globe_state)
