"""The Colormap card's edits applied back on the view-scoped colour table and
opacity of the active array: the vector component, the range and its
scale, the presets, the categories' colours, below / above / NaN colours,
the hidden NaN cells, the colour nodes.

(Split out of app/features/title_bar, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.engine import stats_dispatch
from fespp_on_trame.app.views import per_view_state


def register(core, *, _apply_pwf, _cmap_array_path, _cmap_components, _codes_mask_sync,
             _cmap_data_range, _cmap_done, _cmap_exp, _cmap_target, _cmap_tfs,
             _core_opacity_nodes, _edges, _exp_remap, _find_scalar_bar,
             _hide_nan_grids, _hide_nan_set, _lut_range, _node_positions,
             _presets, _property_label, _push_active_array_label,
             _push_colormap_state, _refresh_compare, _refresh_crossplot,
             _refresh_welllog, _rgb, _set_node_positions):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_apply_cmap_nodes, _cmap_apply_range, _hide_nan_flagged, cmap_preset)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    ctx = core.ctx
    tree = core.tree
    scheduler = core.scheduler
    _mv = core.mv
    @controller.set("set_vector_component")
    def set_vector_component(array_path, value, name=None, assoc="CELLS"):
        """One choice per vector property, session-wide: the colour, the
        statistics, every plot and the synthetic logs all read the same
        component — or the magnitude, the default. The LUT is per array
        name, so every view colouring by the array follows at once."""
        choice = None
        try:
            if value not in (None, "", "magnitude"):
                choice = int(value)
        except (TypeError, ValueError):
            choice = None
        m = dict(getattr(state, "ui_vector_component", None) or {})
        if choice is None:
            m.pop(array_path, None)
        else:
            m[array_path] = choice
        state.ui_vector_component = m
        if not name:
            _t, _k, name = stats_dispatch._resolve_vtk_name(tree, array_path)
        # The count comes from the live array, the same source the card's
        # Component row spells its X / Y / Z from — published so every
        # label names the component the way the reader chose it. The
        # assembly says nothing about the components of a time series or of
        # a multi-realization property.
        n_comp = _cmap_components(name, assoc) if name else 1
        if n_comp > 1:
            counts = dict(getattr(state, "ui_vector_component_count", None) or {})
            if counts.get(array_path) != n_comp:
                counts[array_path] = n_comp
                state.ui_vector_component_count = counts
        mv = _mv()
        views = list(mv.view_ids()) if mv is not None else []
        if name:
            # every view colours through its OWN scoped LUT (seeded once from
            # the global one): set on the global LUT alone, the 3D colouring
            # would stay on the magnitude while every panel reported the
            # component
            luts = []
            for vid in views:
                lut, _pwf = _cmap_tfs(vid, name)
                if lut is not None and all(lut is not x for x in luts):
                    luts.append(lut)
            try:
                g = pvsimple.GetColorTransferFunction(name)
                if all(g is not x for x in luts):
                    luts.append(g)
            except Exception:
                pass
            dr = _cmap_data_range(name, assoc, -1 if choice is None else choice)
            for lut in luts:
                try:
                    lut.VectorMode = "Magnitude" if choice is None else "Component"
                    lut.VectorComponent = 0 if choice is None else choice
                    # the range follows the component, unless the user pinned it
                    if ("Never" not in str(getattr(lut, "AutomaticRescaleRangeMode", ""))
                            and dr is not None and dr[1] > dr[0]):
                        lut.RescaleTransferFunction(dr[0], dr[1])
                except Exception as exc:
                    print("[fespp] vector component error:", exc, flush=True)
            # every colour bar of the array says the component it now shows
            label = _property_label(array_path) or name
            for vid in views:
                scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
                if scene is not None:
                    scene.relabel(name, label)
                    _push_active_array_label(vid)
                    continue
                pvv = mv.get_pv_view(vid) if mv is not None else None
                sb = _find_scalar_bar(_cmap_tfs(vid, name)[0], pvv)
                if sb is not None:
                    sb.Title = label
        for vid in views:
            _push_colormap_state(vid)
            scheduler.mark_dirty(vid)
        scheduler.flush()
        # every analysis panel reads through the same seam: recompute
        _refresh_compare()
        for pid in list(getattr(state, "ui_crossplot_panels", None) or ()):
            _refresh_crossplot(pid)
        _refresh_welllog()

    @controller.set("cmap_component")
    def cmap_component(value, view_id):
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        name, assoc, path, _scene = tgt
        set_vector_component(_cmap_array_path(view_id, path), value,
                             name=name, assoc=assoc)

    def _cmap_apply_range(view_id, lo, hi, pin=True, note=""):
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        name = tgt[0]
        lut, pwf = _cmap_tfs(view_id, name)
        if lut is None:
            return
        lo, hi = float(lo), float(hi)
        if not hi > lo:
            hi = lo + 1e-6
        if int(getattr(lut, "UseLogScale", 0) or 0) and lo <= 0:
            lo = max(hi * 1e-4, 1e-12)
        # Capture the user's opacity curve on the OLD range first — the
        # boundary points sit outside it and must not be squeezed in.
        old_lo, old_hi = _lut_range(lut)
        core = _core_opacity_nodes(pwf, old_lo, old_hi)
        try:
            lut.RescaleTransferFunction(lo, hi)
            # 'Never' = pinned: the auto-rescale sites (eye toggles,
            # reconcile's rescale) must not snap it back to the data.
            lut.AutomaticRescaleRangeMode = (
                "Never" if pin else "Grow and update on 'Apply'")
        except Exception as exc:
            print(f"[fespp] cmap range error ({view_id}):", exc, flush=True)
            return
        try:
            ospan = (old_hi - old_lo) or 1.0
            core2 = [[lo + (x - old_lo) / ospan * (hi - lo), y] for x, y in core]
            _apply_pwf(view_id, name, lut, pwf, core2)
        except Exception:
            pass
        _cmap_done(view_id, note=note)

    def _cat_entry(view_id, name, scene):
        """The block entry painted by code with `name` in this view, else
        None: the card then edits its categories, not a ramp."""
        if scene is None:
            return None
        for e in scene.block_state.values():
            if e.color_array == name and e.categories:
                return e
        return None

    @controller.set("cmap_category_color")
    def cmap_category_color(payload, view_id):
        """One code's colour from the card's picker: [code, '#rrggbb']."""
        from fespp_on_trame.engine import categorical_palette
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        try:
            code, hex_color = float(payload[0]), str(payload[1])
        except (TypeError, ValueError, IndexError):
            return
        lut, _pwf = _cmap_tfs(view_id, tgt[0])
        if lut is None or not categorical_palette.set_code_color(
                lut, code, hex_color):
            _push_colormap_state(
                view_id, note=f"code {payload[0]} is not painted here")
            return
        _cmap_done(view_id)

    @controller.set("cmap_category_opacity")
    def cmap_category_opacity(payload, view_id):
        """One code's opacity from the card's slider: [code, alpha]; a code
        of None sets every code (the card's "Opacity" row)."""
        from fespp_on_trame.engine import categorical_palette
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        try:
            code = None if payload[0] is None else float(payload[0])
            alpha = float(payload[1])
        except (TypeError, ValueError, IndexError):
            print(f"[fespp] code opacity ({view_id}): unreadable {payload!r}", flush=True)
            return
        lut, _pwf = _cmap_tfs(view_id, tgt[0])
        if lut is None or categorical_palette.set_code_opacity(
                lut, code, alpha) is None:
            _push_colormap_state(
                view_id, note=f"code {payload[0]} is not painted here")
            return
        # a code at 0 takes its cells out, so their neighbours' faces show
        # (a see-through hole otherwise); back above 0, they return
        try:
            _codes_mask_sync(view_id, tgt[0])
        except Exception as exc:
            print(f"[fespp] codes at opacity 0 ({view_id}):", exc, flush=True)
        _cmap_done(view_id)

    def _preset_name(preset):
        """The name ParaView knows `preset` by: as given, else without its
        parenthesised origin ("Viridis (matplotlib)" is "Viridis" in
        ParaView 6, and the assistant's words still say the former), else
        the same name in another case; "" when ParaView has no such table.
        Unjudged (as given) while the session's preset list is not read."""
        known = list(getattr(state, "ui_colormap_presets", None) or [])
        if not known or preset in known:
            return preset
        by_lower = {k.lower(): k for k in known}
        short = preset.split(" (")[0].strip()
        for cand in (short, preset):
            if cand in known:
                return cand
            if cand.lower() in by_lower:
                return by_lower[cand.lower()]
        return ""

    @controller.set("cmap_preset")
    def cmap_preset(preset, view_id):
        tgt = _cmap_target(view_id)
        if tgt is None or not preset:
            return
        name = _preset_name(str(preset))
        if not name:
            _push_colormap_state(view_id, note=f"no color table named {preset!r} in this ParaView")
            return
        preset = name
        lut, _pwf = _cmap_tfs(view_id, tgt[0])
        if lut is None:
            return
        cat_entry = _cat_entry(view_id, tgt[0], tgt[3])
        if cat_entry is not None:
            # painted by code: the preset gives the codes new colours, the
            # codes and their names stay
            from fespp_on_trame.engine import categorical_palette
            note = categorical_palette.recolor(lut, cat_entry.categories, preset)
            _presets[(view_id, tgt[0])] = preset
            _cmap_done(view_id, note=note)
            return
        lo, hi = _lut_range(lut)
        try:
            lut.ApplyPreset(preset, True)
            if hi > lo:
                lut.RescaleTransferFunction(lo, hi)  # keep the range
            _cmap_exp.pop((view_id, tgt[0]), None)  # fresh node positions
        except Exception as exc:
            print(f"[fespp] cmap preset error ({view_id}):", exc, flush=True)
            return
        _presets[(view_id, tgt[0])] = preset
        _cmap_done(view_id)

    @controller.set("cmap_range")
    def cmap_range(rng, view_id):
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except (TypeError, ValueError, IndexError):
            _push_colormap_state(
                view_id, note=f"range not applied: {rng!r} is not two numbers")
            return
        _cmap_apply_range(view_id, lo, hi, pin=True)

    @controller.set("cmap_scale")
    def cmap_scale(mode, view_id):
        # 'linear' | 'log' (native UseLogScale) | 'exp' (node re-spacing).
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        name = tgt[0]
        lut, _pwf = _cmap_tfs(view_id, name)
        if lut is None:
            return
        key = (view_id, name)
        is_log = int(getattr(lut, "UseLogScale", 0) or 0) == 1
        try:
            if key in _cmap_exp and mode != "exp":
                orig = _cmap_exp.pop(key)
                if len(orig) == len(_node_positions(lut)):
                    _set_node_positions(lut, orig)
            if mode == "log":
                if not is_log:
                    lo, hi = _lut_range(lut)
                    if lo <= 0:
                        lut.RescaleTransferFunction(max(hi * 1e-4, 1e-12), hi)
                    lut.UseLogScale = 1
                    lut.MapControlPointsToLogSpace()
            else:
                if is_log:
                    lut.MapControlPointsToLinearSpace()
                    lut.UseLogScale = 0
                if mode == "exp" and key not in _cmap_exp:
                    _cmap_exp[key] = _exp_remap(lut)
        except Exception as exc:
            print(f"[fespp] cmap scale error ({view_id}):", exc, flush=True)
        _cmap_done(view_id)

    def _cmap_side(view_id, which, payload):
        # payload = ['#rrggbb', alpha] — the colour goes on the LUT (always
        # enabled: the default IS the clamp colour), the alpha as a PWF
        # boundary point (the below/above alpha byte).
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        name = tgt[0]
        lut, pwf = _cmap_tfs(view_id, name)
        if lut is None:
            return
        try:
            hexs = payload[0] if len(payload) > 0 else ""
            alpha = float(payload[1]) if len(payload) > 1 else 1.0
        except (TypeError, ValueError, IndexError):
            return
        use_prop = "UseBelowRangeColor" if which == "below" else "UseAboveRangeColor"
        col_prop = "BelowRangeColor" if which == "below" else "AboveRangeColor"
        try:
            if hexs:
                setattr(lut, col_prop, _rgb(hexs))
                setattr(lut, use_prop, 1)
            _edges(view_id, name)[which] = max(0.0, min(1.0, alpha))
            lo, hi = _lut_range(lut)
            _apply_pwf(view_id, name, lut, pwf, _core_opacity_nodes(pwf, lo, hi))
        except Exception as exc:
            print(f"[fespp] cmap {which} error ({view_id}):", exc, flush=True)
        _cmap_done(view_id)

    @controller.set("cmap_below")
    def cmap_below(payload, view_id):
        _cmap_side(view_id, "below", payload)

    @controller.set("cmap_above")
    def cmap_above(payload, view_id):
        _cmap_side(view_id, "above", payload)

    @controller.set("cmap_nan")
    def cmap_nan(payload, view_id):
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        lut, _pwf = _cmap_tfs(view_id, tgt[0])
        if lut is None:
            return
        prev = None
        try:
            prev = float(lut.NanOpacity)
            lut.NanColor = _rgb(payload[0])
            lut.NanOpacity = float(payload[1])
        except Exception as exc:
            print(f"[fespp] cmap nan error ({view_id}):", exc, flush=True)
        # "Hide NaN cells" checks itself when the NaN opacity CROSSES to 0 —
        # a transparent NaN cell is a see-through hole, the user wants the
        # faces behind it — and unchecks itself when the opacity comes back
        # above 0, only where it was the opacity that checked it. A colour
        # change at opacity 0 crosses nothing: a hand-made uncheck stays.
        try:
            alpha = float(payload[1])
            if prev is not None and prev > 0 and alpha <= 0:
                for rp, _sel, _e in _hide_nan_grids(view_id, tgt[0]):
                    if not (ctx.grid_hide_nan.get((view_id, rp)) or {}).get("on"):
                        _hide_nan_set(view_id, rp, True, auto=True)
            elif alpha > 0:
                for rp in _hide_nan_flagged(view_id, tgt[0], auto_only=True):
                    _hide_nan_set(view_id, rp, False)
        except Exception as exc:
            print(f"[fespp] cmap nan: hide NaN cells follow-up ({view_id}):", exc, flush=True)
        _cmap_done(view_id)

    def _hide_nan_flagged(view_id, array, auto_only=False):
        """The grids of this view whose NaN mask is on and painted by
        `array` (realization suffix aside) — visible or not."""
        from fespp_on_trame.engine.utils.naming import strip_realization_suffix
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        want = strip_realization_suffix(array or "")
        out = []
        for (vid, rp), flag in list(ctx.grid_hide_nan.items()):
            if vid != view_id or not flag.get("on") or (auto_only and not flag.get("auto")):
                continue
            sel = rp
            entry = scene.block_state.get(sel) if scene is not None else None
            if entry is not None and strip_realization_suffix(entry.color_array or "") == want:
                out.append(rp)
        return out

    @controller.set("cmap_hide_nan")
    def cmap_hide_nan(on, view_id):
        # Every grid of this view painted by the card's array: the NaN
        # opacity is that array's (one table per view and array), so is the
        # box. A hand on it clears "auto" — the choice wins over the opacity.
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        name = tgt[0]
        logs = getattr(ctx, "log_nan", None)
        if logs is not None and logs[0](view_id, name):
            logs[2](view_id, name, bool(on))
            _cmap_done(view_id)
            return
        try:
            if on:
                grids = [rp for rp, _s, _e in _hide_nan_grids(view_id, name)]
                if not grids:
                    print(f"[fespp] hide NaN cells ({view_id}): no visible grid is"
                          f" painted by {name!r} as a cell property", flush=True)
            else:
                grids = _hide_nan_flagged(view_id, name)
            for rp in grids:
                _hide_nan_set(view_id, rp, bool(on), auto=False)
                # the hand on the box wins over the default (slicers._hide_nan_defaults)
                (ctx.grid_nan_shown.discard if on else ctx.grid_nan_shown.add)((view_id, rp))
        except Exception as exc:
            print(f"[fespp] cmap hide nan error ({view_id}):", exc, flush=True)
        _cmap_done(view_id)

    def _pts_equal(a, b):
        if len(a) != len(b):
            return False
        return all(abs(float(x) - float(y)) <= 1e-9 * (1.0 + abs(float(x)))
                   for x, y in zip(a, b))

    def _apply_cmap_nodes(view_id, kind, nodes):
        """COE graph edit -> the scoped LUT (colour nodes [[x,[r,g,b]],…])
        or PWF (opacity nodes [[x, a],…]). Skips when the transfer function
        already holds these points — the projection writes the same lists
        back, so this is what keeps the two-way binding from looping."""
        if not per_view_state.is_live(view_id):
            return
        nodes = nodes or []
        tgt = _cmap_target(view_id)
        if tgt is None:
            return
        lut, pwf = _cmap_tfs(view_id, tgt[0])
        if lut is None:
            return
        # Drop the below / above BAND decorations (outside the LUT core)
        # the projection added for the graph's data-range axis.
        lo, hi = _lut_range(lut)
        eps = ((hi - lo) or 1.0) * 1e-5
        nodes = [n for n in nodes if lo - eps <= float(n[0]) <= hi + eps]
        if len(nodes) < 2:
            return
        try:
            if kind == "colors":
                pts = [c for n in nodes
                       for c in (float(n[0]), float(n[1][0]),
                                 float(n[1][1]), float(n[1][2]))]
                if _pts_equal(pts, list(lut.RGBPoints or [])):
                    return
                lut.RGBPoints = pts
            else:
                if pwf is None:
                    return
                core = [[float(n[0]), float(n[1])] for n in nodes]
                cur = _core_opacity_nodes(pwf, lo, hi)
                if _pts_equal([c for n in core for c in n],
                              [c for n in cur for c in n]):
                    return
                # the graph on a property painted by code: each code takes
                # the curve's value (its indexed table reads no curve), and
                # a code at 0 takes its cells out
                from fespp_on_trame.engine import categorical_palette
                by_code = categorical_palette.apply_opacity_curve(lut, core) is not None
                _apply_pwf(view_id, tgt[0], lut, pwf, core)
                if by_code:
                    _codes_mask_sync(view_id, tgt[0])
        except Exception as exc:
            print(f"[fespp] cmap {kind} nodes error ({view_id}):", exc,
                  flush=True)
            return
        _cmap_done(view_id)
    return (_apply_cmap_nodes, _cmap_apply_range, _hide_nan_flagged, cmap_preset)
