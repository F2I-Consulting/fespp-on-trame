"""the session door (widgets/session, app/session_host)
A colour table IS its proxies plus three memos only this closure holds
(the edge alphas, the pre-exponential node positions, the categorical
preset): saved and written back raw, so the card and the image come
back exactly — a pinned range stays pinned (AutomaticRescaleRangeMode).

(Moved out of app/boot, overhaul slice 10.)"""


def register(core, *, _cmap_done, _cmap_edges, _cmap_exp, _cmap_target, _codes_mask_sync,
             _cmap_tfs, _hide_nan_set, _presets, _push_colormap_state):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    controller = core.controller
    ctx = core.ctx
    scheduler = core.scheduler
    # --- the session door (widgets/session, app/session_host) --------------
    # A colour table IS its proxies plus three memos only this closure holds
    # (the edge alphas, the pre-exponential node positions, the categorical
    # preset): saved and written back raw, so the card and the image come
    # back exactly — a pinned range stays pinned (AutomaticRescaleRangeMode).
    _SESSION_LUT_PROPS = (
        "RGBPoints", "ColorSpace", "UseLogScale", "AutomaticRescaleRangeMode",
        "UseBelowRangeColor", "BelowRangeColor", "UseAboveRangeColor",
        "AboveRangeColor", "NanColor", "NanOpacity", "EnableOpacityMapping",
        "VectorMode", "VectorComponent", "IndexedLookup", "Annotations",
        "IndexedColors", "IndexedOpacities")

    def _proxy_props(proxy, names):
        out = {}
        for n in names:
            prop = proxy.SMProxy.GetProperty(n) if proxy is not None else None
            if prop is not None:
                out[n] = [prop.GetElement(i) for i in range(prop.GetNumberOfElements())]
        return out

    def _write_proxy_props(proxy, values):
        for n, vals in (values or {}).items():
            prop = proxy.SMProxy.GetProperty(n)
            if prop is None:
                continue
            try:
                prop.SetNumberOfElements(len(vals))
                for i, v in enumerate(vals):
                    prop.SetElement(i, v)
            except Exception as exc:
                print(f"[fespp] session color table {n}:", exc, flush=True)
        proxy.UpdateVTKObjects()

    @controller.set("session_view_tables")
    def session_view_tables(view_id):
        """Every colour table of a view — the ones colouring it and the one
        the Colormap card edits — as the session file keeps them."""
        vid = str(view_id or "")
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        names = []
        if scene is not None:
            for t in scene.legend_tables()[0]:
                names += [a for a in t["arrays"] if a not in names]
        tgt = _cmap_target(vid)
        if tgt is not None and tgt[0] not in names:
            names.append(tgt[0])
        out = []
        for name in names:
            lut, pwf = _cmap_tfs(vid, name)
            if lut is None:
                continue
            out.append({
                "array": name,
                "lut": _proxy_props(lut, _SESSION_LUT_PROPS),
                "pwf": _proxy_props(pwf, ("Points",)),
                "edges": dict(_cmap_edges.get((vid, name)) or {}),
                "exp": list(_cmap_exp[(vid, name)]) if (vid, name) in _cmap_exp else None,
                "preset": _presets.get((vid, name)),
            })
        return out

    @controller.set("session_restore_view_tables")
    def session_restore_view_tables(view_id, tables):
        """The colour tables of a view written back as saved, then the card
        projected again from them."""
        vid = str(view_id or "")
        for t in tables or ():
            name = t.get("array")
            lut, pwf = _cmap_tfs(vid, name) if name else (None, None)
            if lut is None:
                continue
            _write_proxy_props(lut, t.get("lut"))
            ctx.colormap_restored[(vid, name)] = True
            if pwf is not None:
                _write_proxy_props(pwf, t.get("pwf"))
            if t.get("edges"):
                _cmap_edges[(vid, name)] = dict(t["edges"])
            if t.get("exp") is not None:
                _cmap_exp[(vid, name)] = list(t["exp"])
            else:
                _cmap_exp.pop((vid, name), None)
            # "cat_preset": the key of the files saved before 16/10/2026,
            # when only a palette of codes was remembered
            preset = t.get("preset", t.get("cat_preset"))
            if preset:
                _presets[(vid, name)] = preset
            elif "preset" in t or "cat_preset" in t:
                # the saved table had none: a preset set since (an undone
                # assistant palette change, say) is forgotten too
                _presets.pop((vid, name), None)
        # the codes a saved table puts at opacity 0 take their cells out
        try:
            _codes_mask_sync(vid)
        except Exception as exc:
            print(f"[fespp] session codes at opacity 0 ({vid}):", exc, flush=True)
        _push_colormap_state(vid)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    @controller.set("session_hide_nan")
    def session_hide_nan(view_id, rep_path, auto=False):
        """One grid's NaN mask as the session saved it."""
        _hide_nan_set(str(view_id or ""), rep_path, True, auto=bool(auto))
        scheduler.flush()

    @controller.set("cmap_bar")
    def cmap_bar(on, view_id):
        # The bar of the ONE table the card edits (its array), in this view:
        # the view shows one bar, that table's (engine/legends), and the
        # choice stays with the table. Per view, on by default.
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        name, _assoc, _path, scene = tgt
        try:
            scene.set_bar_visible(name, bool(on))
        except Exception as exc:
            print(f"[fespp] cmap bar error ({view_id}):", exc, flush=True)
        _cmap_done(view_id)
