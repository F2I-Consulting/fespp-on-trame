"""exact colours (the title bar's shading toggle)
Shading lights a coloured surface: the same value reads darker on a
face turned away from the light, i.e. another colour than the legend
says. "Exact colours" puts every representation of the view in pure
ambient (Ambient 1, Diffuse 0, Specular 0): what is drawn is the
table's colour. Shaded (ParaView's 0 / 1 / 0) by default — the relief
of faults and horizons reads through it.

(Moved out of app/boot, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.app.views import per_view_state


def register(core, *, _cmap_apply_range, _cmap_data_range, _cmap_done,
             _cmap_target, _cmap_tfs, _re, _say, _table_path, cmap_preset):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    active_data_source = core.active_data_source
    scheduler = core.scheduler
    activation = core.activation
    _mv = core.mv
    # --- exact colours (the title bar's shading toggle) -----------------------
    # Shading lights a coloured surface: the same value reads darker on a
    # face turned away from the light, i.e. another colour than the legend
    # says. "Exact colours" puts every representation of the view in pure
    # ambient (Ambient 1, Diffuse 0, Specular 0): what is drawn is the
    # table's colour. Shaded (ParaView's 0 / 1 / 0) by default — the relief
    # of faults and horizons reads through it.
    _FLAT = {True: (1.0, 0.0, 0.0), False: (0.0, 1.0, 0.0)}
    _lit = {}    # vid -> (the view's mode, the ids of the representations put in it)

    def _apply_flat_colors(vids):
        """Before a view is drawn: every representation that takes light —
        the composite, the grid crops and thresholds, a well's labels have
        none — in the view's mode. A representation done once is left
        alone until the mode flips (a new one, an isolate's display after
        the toggle, is done when it appears), and the properties are read
        on the proxies themselves: listing a view's representations and
        reading two properties through paraview.simple's wrappers cost
        25 ms a draw with twelve wells shown, and a cut scene draws at
        every move of the hand (29/10)."""
        mv = _mv()
        for vid in vids:
            pvv = mv.get_pv_view(vid) if mv is not None else None
            if pvv is None or not per_view_state.is_live(vid):
                continue
            flat = bool(getattr(state, f"ui_flat_colors__{vid}", False))
            amb, dif, spe = _FLAT[flat]
            mode, done = _lit.get(vid) or (None, set())
            if mode != flat:
                done = set()
            seen = set()
            reps = pvv.SMProxy.GetProperty("Representations")
            for i in range(reps.GetNumberOfProxies() if reps is not None else 0):
                rep = reps.GetProxy(i)
                if rep is None:
                    continue
                gid = rep.GetGlobalIDAsString()
                seen.add(gid)
                if gid in done:
                    continue
                ambient = rep.GetProperty("Ambient")
                if ambient is None:
                    done.add(gid)
                    continue
                try:
                    diffuse, specular = rep.GetProperty("Diffuse"), rep.GetProperty("Specular")
                    if ambient.GetElement(0) != amb or diffuse.GetElement(0) != dif:
                        ambient.SetElement(0, amb)
                        diffuse.SetElement(0, dif)
                        if specular is not None:
                            specular.SetElement(0, spe)
                        rep.UpdateVTKObjects()
                    done.add(gid)
                except Exception as exc:
                    print(f"[fespp] exact colors ({vid}):", exc, flush=True)
            _lit[vid] = (flat, done & seen)

    scheduler.add_flush_listener(_apply_flat_colors)

    @core.lifecycle.on("view_closed")
    def _forget_lit(vid):
        _lit.pop(vid, None)

    @controller.set("set_flat_colors")
    def set_flat_colors(view_id, on):
        """The title bar's toggle: this view in exact colours (no shading)
        or shaded."""
        vid = str(view_id or "")
        if not per_view_state.is_live(vid):
            return
        state[f"ui_flat_colors__{vid}"] = bool(on)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("legend_pick")
    def legend_pick(key, view_id, open_card=False):
        """A row of the Legends card: its table becomes the one the Colormap
        card edits — the view's active tree node moves to the property that
        paints it, as a click on that node would — and so the view's one
        bar (`_on_active` re-projects the card, open or not, and draws the
        view). `open_card`: the card opens on it."""
        vid = str(view_id or "")
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is None or not key:
            return
        table = next((t for t in scene.legend_tables()[0] if t["key"] == key), None)
        path = _table_path(vid, table) if table is not None else ""
        if not path:
            _say("That legend no longer colors this view.")
            return
        activation.activate(vid, path)
        if open_card:
            core.cards.open(vid, "colormap")

    @controller.set("legend_open")
    def legend_open(view_id):
        """A click on the view's colour bar: the Colormap card opens on its table."""
        vid = str(view_id or "")
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        if scene is not None:
            legend_pick(scene.legend_tables()[1], vid, open_card=True)

    @controller.set("cmap_rescale")
    def cmap_rescale(mode, view_id):
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        name, assoc, _path, _scene = tgt
        if mode == "data":
            dr = _cmap_data_range(name, assoc)
            if dr is not None:
                _cmap_apply_range(view_id, dr[0], dr[1], pin=False)
            return
        if mode in ("symmetric", "diverging"):
            # [-m, +m] around zero, m the largest magnitude of the data: a
            # difference then reads a rise and a drop on the same scale;
            # 'diverging' first applies the diverging preset
            note = ""
            lut, _pwf = _cmap_tfs(view_id, name)
            if lut is not None and int(getattr(lut, "UseLogScale", 0) or 0):
                # a log scale has no zero: the range would be rewritten
                # to a positive one behind the user's back
                _cmap_done(view_id, note="log scale: no range symmetric around 0"
                                         " — untick Log first")
                return
            if mode == "diverging":
                from fespp_on_trame.engine.utils.color_palette import DIVERGING_PRESET
                presets = list(getattr(state, "ui_colormap_presets", None) or [])
                # the list is seeded when a Colormap card is first built;
                # before that the preset is simply tried
                if not presets or DIVERGING_PRESET in presets:
                    cmap_preset(DIVERGING_PRESET, view_id)
                else:
                    note = (f"'{DIVERGING_PRESET}' is not among this ParaView's"
                            " presets: the symmetric range is applied alone")
            dr = _cmap_data_range(name, assoc)
            m = max(abs(dr[0]), abs(dr[1])) if dr is not None else 0.0
            if m > 0:
                _cmap_apply_range(view_id, -m, m, pin=True, note=note)
            else:
                why = (f"the data range of {name} could not be read: no symmetric"
                       " range applied" if dr is None
                       else "every value is 0: no symmetric range to apply")
                _cmap_done(view_id, note=(note + "; " if note else "") + why)
            return
        def _mr_range():
            # Union over every realization array of the property loaded on
            # the source: '<base>' and '<base>_real_<n>' (FESPP names the
            # realizations of an MR property that way — ParaView itself has
            # no realization notion, so this is a plain array-name sweep).
            base = _re.sub(r"_real_\d+$", "", name)
            mlo, mhi = float("inf"), float("-inf")
            try:
                di = active_data_source.get_source().GetDataInformation()
                adi = (di.GetPointDataInformation() if assoc == "POINTS"
                       else di.GetCellDataInformation())
                for i in range(adi.GetNumberOfArrays()):
                    ai = adi.GetArrayInformation(i)
                    nm = ai.GetName() if ai is not None else ""
                    if nm == base or nm.startswith(base + "_real_"):
                        r = ai.GetComponentRange(-1)
                        if r is not None and r[0] <= r[1]:
                            mlo, mhi = min(mlo, r[0]), max(mhi, r[1])
            except Exception as exc:
                print(f"[fespp] cmap mr rescale error ({view_id}):", exc,
                      flush=True)
            return (mlo, mhi) if mlo <= mhi else None

        lo, hi = float("inf"), float("-inf")
        if mode in ("time", "all"):
            # Union over EVERY time step — the source is stepped through
            # the time keeper's values and restored (as the stats do); one
            # pipeline update per step. 'all' unions the realizations too.
            per_step = _mr_range if mode == "all" else (
                lambda: _cmap_data_range(name, assoc))
            try:
                tk = pvsimple.GetTimeKeeper()
                values = list(tk.TimestepValues or [])
                src = active_data_source.get_source()
                saved = float(tk.Time)
            except Exception:
                return
            if not values:
                r = per_step()
                if r is not None:
                    lo, hi = r
            else:
                try:
                    for t in values:
                        src.UpdatePipeline(float(t))
                        r = per_step()
                        if r is not None:
                            lo, hi = min(lo, r[0]), max(hi, r[1])
                finally:
                    try:
                        src.UpdatePipeline(saved)
                    except Exception:
                        pass
        elif mode == "mr":
            r = _mr_range()
            if r is not None:
                lo, hi = r
        else:
            return
        if lo <= hi and lo != float("inf"):
            _cmap_apply_range(view_id, lo, hi, pin=True)

    # ------------------------------------------------------------------
