"""Per-view COLORMAP editor (widgets/colormap): projection of the
view-scoped LUT / PWF of the active array into ui_colormap__<vid>,
and the edits applied back on them (plus the data / custom /
all-time-steps / all-realizations rescales).

(Split out of app/features/title_bar, overhaul slice 10.)"""
from paraview import simple as pvsimple
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import source_resolver


def register(core, *, _eye_driven_colors, _hide_nan_flagged, _hide_nan_grids,
             _is_property_path, _property_label, _real_idx_for, _rep_path_of,
             _set_tool_target):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_apply_pwf, _cmap_array_path, _cmap_components, _cmap_data_range, _cmap_done, _cmap_edges, _cmap_exp, _cmap_pushed, _cmap_target, _cmap_tfs, _core_opacity_nodes, _edges, _exp_remap, _find_scalar_bar, _hex, _lut_range, _node_positions, _presets, _push_colormap_state, _rgb, _set_node_positions, _table_path)."""
    # the shared services (app/core/context.Core)
    state = core.state
    ctx = core.ctx
    tree = core.tree
    active_data_source = core.active_data_source
    source_registry = core.source_registry
    scheduler = core.scheduler
    lifecycle = core.lifecycle
    # Per-view COLORMAP editor (widgets/colormap): projection of the
    # view-scoped LUT / PWF of the active array into ui_colormap__<vid>,
    # and the edits applied back on them (plus the data / custom /
    # all-time-steps / all-realizations rescales).
    import re as _re

    def _cmap_var(view_id):
        return f"ui_colormap__{view_id}"

    def _cmap_active_target(view_id):
        """(name, assoc, node_path, scene) the tree's active node names: the
        DISPLAYED tab's active node when it is an array node, else the
        array currently colouring the active rep. None = the node names no
        array."""
        path = getattr(state, f"active_path__{view_id}", None) or ""
        if node_facts.is_derived(path):
            # a formula is no array of its grid's block: its table is the
            # view's bar while it is shown (`_cmap_target` falls back to it),
            # never the array the hidden grid was coloured with
            return None
        rep_path = _rep_path_of(path) if path else ""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        if not rep_path or scene is None:
            return None
        sel = rep_path
        entry = scene.block_state.get(sel)
        name, assoc = "", "CELLS"
        if path != rep_path:
            try:
                ridx = _real_idx_for(view_id, path)
                a, n, _s = source_resolver.resolve_array_for_path(
                    source_registry, tree, rep_path, path,
                    realization_idx=ridx)
                if n:
                    name, assoc = n, a or "CELLS"
            except Exception:
                pass
        if not name and entry is not None and entry.color_array:
            name, assoc = entry.color_array, entry.assoc or "CELLS"
        if not name:
            return None
        return name, assoc, path, scene

    def _cmap_target(view_id):
        """(name, assoc, node_path, scene) the editor edits: the array the
        tree's active node names (`_cmap_active_target`), else the table
        holding the view's one colour bar (engine/legends) — so the card and
        the bar never name two tables, and a view coloured through an eye
        opened without a click still has a table to edit. None = nothing
        colours the view either."""
        tgt = _cmap_active_target(view_id)
        return tgt if tgt is not None else _bar_table_target(view_id)

    def _table_path(view_id, table):
        """The tree node a table of the view stands for: the property whose
        eye paints its first block (a log channel is its own block)."""
        eyed = _eye_driven_colors.get(view_id) or {}
        sels = list(table.get("selectors") or ())
        for sel in sels:
            if eyed.get(sel):
                return eyed[sel]
        return next((s for s in sels if _is_property_path(s)), "")

    def _bar_table_target(view_id):
        """`_cmap_target` for the table holding the view's bar."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        table = scene.bar_table() if scene is not None else None
        if table is None:
            return None
        sels = list(table.get("selectors") or ())
        entry = scene.block_state.get(sels[0]) if sels else None
        name = ((entry.color_array if entry is not None else "")
                or table["arrays"][0])
        assoc = (entry.assoc if entry is not None else "") or "CELLS"
        return name, assoc, _table_path(view_id, table), scene

    def _sync_bar_focus(view_id):
        """The view's one colour bar follows the array the tree's active
        node names (engine/legends); the scene marks the view dirty when the
        bar moved, the caller's flush draws it."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        if scene is None:
            return
        tgt = _cmap_active_target(view_id)
        try:
            scene.set_bar_target(tgt[0] if tgt is not None else "")
        except Exception as exc:
            print(f"[fespp] bar focus error ({view_id}):", exc, flush=True)

    def _cmap_entry(scene, path, name):
        """The block entry painted by `name` the card's node stands for: the
        node's own block first — a log channel IS its block, its frame owns
        none — then its representation's."""
        if scene is None or not path:
            return None
        rp = _rep_path_of(path) or ""
        for p in (path, rp):
            if not p:
                continue
            e = scene.block_state.get(p)
            if e is not None and e.color_array == name:
                return e
        return None

    def _cmap_tfs(view_id, name):
        # Same resolution as PdcScene._scoped_lut: the view's scoped
        # LUT/PWF, else the global ones (single view / early boot).
        vres = core.view_resources.get(view_id)
        if vres is not None:
            lut = vres.get_or_create_lut(name)
            if lut is not None:
                return lut, vres.get_or_create_pwf(name)
        try:
            return (pvsimple.GetColorTransferFunction(name),
                    pvsimple.GetOpacityTransferFunction(name))
        except Exception:
            return None, None

    def _cmap_array_info(name, assoc):
        """The array's data information: off the reader (its own arrays,
        current after every read), else off the derived-arrays filter (a
        computed array, current once put)."""
        try:
            for src in (active_data_source.get_source(),
                        active_data_source.get_display_source()):
                di = src.GetDataInformation()
                adi = (di.GetPointDataInformation() if assoc == "POINTS"
                       else di.GetCellDataInformation())
                ai = adi.GetArrayInformation(name)
                if ai is not None:
                    return ai
        except Exception:
            return None
        return None

    def _cmap_data_range(name, assoc, comp=-1):
        # comp -1 = the magnitude (VTK's convention), which for a scalar is
        # the value itself; a vector property asks for its chosen component
        try:
            ai = _cmap_array_info(name, assoc)
            if ai is not None:
                r = ai.GetComponentRange(comp)
                if r is not None and r[0] <= r[1]:
                    return float(r[0]), float(r[1])
        except Exception:
            pass
        return None

    def _cmap_components(name, assoc):
        """How many values per element the array carries (1 = a scalar)."""
        try:
            ai = _cmap_array_info(name, assoc)
            return int(ai.GetNumberOfComponents()) if ai is not None else 1
        except Exception:
            return 1

    def _cmap_array_path(view_id, path):
        """The ARRAY the card edits: the active node when it carries values,
        else what colours the active rep — the key of the component map. A
        grid's container node differs from its rep path too, and is no
        array: the card would then be titled by the grid it does not
        edit."""
        rp = _rep_path_of(path) if path else ""
        if path and _is_property_path(path):
            return path
        # a rep node: the array its EYE colours it with, from the live
        # per-view memory (ui_active_array_by_rep_by_view stays empty in
        # this app; keyed on the rep path, the component choice would not
        # be the one the analysis panels read)
        try:
            sel = rp
            eyed = (_eye_driven_colors.get(view_id) or {}).get(sel)
            if eyed:
                return eyed
        except Exception:
            pass
        by_view = getattr(state, "ui_active_array_by_rep_by_view", None) or {}
        return ((by_view.get(view_id) or {}).get(rp)) or path

    def _hex(rgb):
        try:
            return "#%02x%02x%02x" % tuple(
                min(255, max(0, round(float(c) * 255))) for c in list(rgb)[:3])
        except Exception:
            return "#000000"

    def _rgb(hexs):
        h = (hexs or "").lstrip("#")
        if len(h) < 6:
            return [0.0, 0.0, 0.0]
        return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def _find_scalar_bar(lut, pvv):
        """This view's scalar bar bound to `lut`, WITHOUT creating one
        (pvsimple.GetScalarBar creates a visible rep as a side effect)."""
        if pvv is None or lut is None:
            return None
        try:
            for r in pvv.Representations:
                if (r.GetXMLName() == "ScalarBarWidgetRepresentation"
                        and getattr(r, "LookupTable", None) is not None
                        and r.LookupTable.GetGlobalIDAsString()
                        == lut.GetGlobalIDAsString()):
                    return r
        except Exception:
            pass
        return None

    def _lut_range(lut):
        pts = list(lut.RGBPoints or [])
        if len(pts) >= 8:
            return float(pts[0]), float(pts[-4])
        return 0.0, 1.0

    # Out-of-range OPACITIES (the alpha byte of the below / above
    # colours), emulated as boundary points just outside the LUT core in
    # the PWF; and the "exponential" node re-spacing (original positions
    # kept to restore). Both keyed (view_id, array).
    _cmap_edges = {}
    _cmap_exp = {}
    _EDGE = 0.001   # boundary offset, fraction of the LUT span

    def _edges(view_id, name):
        return _cmap_edges.setdefault((view_id, name),
                                      {"below": 1.0, "above": 1.0})

    def _core_opacity_nodes(pwf, lo, hi):
        """The user's opacity curve WITHOUT the boundary points: only
        the PWF points inside the LUT core."""
        try:
            pp = list(pwf.Points or []) if pwf is not None else []
        except Exception:
            pp = []
        eps = ((hi - lo) or 1.0) * _EDGE * 0.5
        core = [[float(pp[i]), float(pp[i + 1])]
                for i in range(0, len(pp) - 3, 4)
                if lo - eps <= float(pp[i]) <= hi + eps]
        if not core:
            return [[lo, 1.0], [hi, 1.0]]
        # the curve spans the whole table: a curve stopping short of an end
        # (one node left, the opacity function on another range than the
        # table) would draw the graph in the table's first colour alone
        if core[0][0] > lo + eps:
            core.insert(0, [lo, core[0][1]])
        if core[-1][0] < hi - eps:
            core.append([hi, core[-1][1]])
        return core

    def _apply_pwf(view_id, name, lut, pwf, core):
        """PWF = below boundary + the user's core curve + above boundary.
        Opacity mapping ON only when something is translucent (VTK ignores
        NanOpacity while it is on)."""
        if lut is None or pwf is None:
            return
        lo, hi = _lut_range(lut)
        span = (hi - lo) or 1.0
        e = _edges(view_id, name)
        pts = []
        if e["below"] < 0.999:
            pts += [lo - span * _EDGE, e["below"], 0.5, 0.0]
        for x, y in core:
            pts += [float(x), float(y), 0.5, 0.0]
        if e["above"] < 0.999:
            pts += [hi + span * _EDGE, e["above"], 0.5, 0.0]
        pwf.Points = pts
        translucent = (e["below"] < 0.999 or e["above"] < 0.999
                       or any(float(y) < 0.999 for _x, y in core))
        # a property painted by code: its indexed table ignores the opacity
        # function and reads one opacity per code (IndexedOpacities, the
        # card's code sliders) — the mapping follows those; a range or an
        # edge edit never rewrites them (the graph does: _apply_cmap_nodes)
        from fespp_on_trame.engine import categorical_palette
        if categorical_palette.is_indexed(lut):
            translucent = any(c["opacity"] < 0.999 for c in categorical_palette.read(lut))
        lut.EnableOpacityMapping = 1 if translucent else 0

    def _node_positions(lut):
        pts = list(lut.RGBPoints or [])
        return [float(pts[i]) for i in range(0, len(pts) - 3, 4)]

    def _set_node_positions(lut, xs):
        pts = list(lut.RGBPoints or [])
        for k, i in enumerate(range(0, len(pts) - 3, 4)):
            if k < len(xs):
                pts[i] = float(xs[k])
        lut.RGBPoints = pts

    def _exp_remap(lut, k=3.0):
        """'Exponential' scale: re-space the colour nodes so the colour
        variation crowds toward the MAX — the mirror of the native log
        scale, which crowds it toward the min. Returns the original
        positions (restored when leaving the mode)."""
        import math
        xs = _node_positions(lut)
        if len(xs) < 2:
            return xs
        lo, hi = xs[0], xs[-1]
        span = (hi - lo) or 1.0
        den = math.exp(k) - 1.0
        new = [hi - span * (math.exp(k * (1.0 - (x - lo) / span)) - 1.0) / den
               for x in xs]
        _set_node_positions(lut, new)
        return xs

    # the preset chosen per (view, array): a ramp for a continuous property,
    # a qualitative palette for one painted by code (the palette's default,
    # Brewer Set1, until the reader picks another). One memory for both, so
    # the card names the preset of THE array it edits, and a session keeps it
    _presets = {}
    ctx.colormap_presets = _presets
    # (view, array) -> True: the tables a session wrote back
    _restored = {}
    ctx.colormap_restored = _restored

    # vid -> the array the card was last projected for ("" = none): the
    # flush listener re-projects it when the table it falls back to moved
    _cmap_pushed = {}

    @lifecycle.on("view_closed")
    def _forget_colormaps_of(vid):
        """A closed view's colour-map memories go with it — out-of-range
        edges, exponential spacing, presets by array (02-carte M6)."""
        for memo in (_cmap_edges, _cmap_exp, _presets, _restored):
            for k in [k for k in memo if isinstance(k, tuple) and k and k[0] == vid]:
                memo.pop(k, None)
        _cmap_pushed.pop(vid, None)

    def _push_colormap_state(view_id, note=""):
        """`note` is what the last action has to say (a range that could
        not be applied, a preset this ParaView lacks); the next push clears
        it."""
        # the active object's own colour and opacity, at the top of the card
        # (app/features/object_look): an eye opened changes what paints it
        look = getattr(ctx, "object_look_publish", None)
        if look is not None:
            look(view_id)
        # on a geometry node the card shows the object's colour: it names it
        seen = getattr(state, f"ui_object_look__{view_id}", None) or {}
        geometry = seen.get("label", "") if seen.get("node") == "geometry" else ""
        titles = {"colormap": "Color"} if geometry else {}
        if (getattr(state, f"ui_tool_title__{view_id}", None) or {}) != titles:
            state[f"ui_tool_title__{view_id}"] = titles
        # first: the view's one bar follows the card (engine/legends), and
        # the card's fallback target is the table holding that bar
        _sync_bar_focus(view_id)
        var = _cmap_var(view_id)
        tgt = _cmap_target(view_id)
        _cmap_pushed[view_id] = tgt[0] if tgt is not None else ""
        if tgt is None:
            if getattr(state, var, None):
                state[var] = {}
            _set_tool_target(view_id, "colormap", geometry)
            return
        name, assoc, path, _scene = tgt
        lut, pwf = _cmap_tfs(view_id, name)
        if lut is None:
            state[var] = {}
            _set_tool_target(view_id, "colormap", geometry)
            return
        lo, hi = _lut_range(lut)
        pts = list(lut.RGBPoints or [])
        from fespp_on_trame.engine import property_values as _pv
        n_comp = _cmap_components(name, assoc)
        array_path = _cmap_array_path(view_id, path)
        comp = _pv.component_choice(state, array_path)
        # the card names the PROPERTY it edits the way the colour bar does:
        # the property node's display name, else the bar's own title (the
        # block entry's label), else the VTK name — never the grid node
        # the reader clicked, which the card does not edit
        entry = _cmap_entry(_scene, path, name)
        label = ((_property_label(array_path)
                  if _is_property_path(array_path) else "")
                 or (entry.label if entry is not None
                     and entry.color_array == name else "")
                 or name)
        _set_tool_target(view_id, "colormap", geometry or label)
        # a property painted by code: the card lists the codes, their
        # names and their colours instead of a ramp and a range
        from fespp_on_trame.engine import categorical_palette as _catp
        cat_entry = (entry if entry is not None and entry.color_array == name
                     else None)
        categories = (_catp.read(lut)
                      if cat_entry is not None and cat_entry.categories
                      else [])
        cat_note = cat_entry.categories_note if cat_entry is not None else ""
        dr = _cmap_data_range(name, assoc, -1 if comp is None else comp) or (lo, hi)
        nid = tree.find_node_id(path) if path else None
        kind = (tree.find_type(nid) or "") if nid is not None else ""
        try:
            n_ts = len(list(pvsimple.GetTimeKeeper().TimestepValues or []))
        except Exception:
            n_ts = 0
        is_mr = (kind in ("MultiRealization", "MultiRealizationTimeSeries")
                 or bool(_re.search(r"_real_\d+$", name)))
        is_ts = (kind in ("TimeSeries", "MultiRealizationTimeSeries")
                 or (kind not in ("ContinuousProperty", "DiscreteProperty")
                     and n_ts > 1))
        # EFFECTIVE out-of-range colours (the swatches): the LUT's explicit
        # below/above colour when set, else its first / last stop (what
        # VTK's clamp renders).
        core_colors = [
            [float(pts[i]), [float(pts[i + 1]), float(pts[i + 2]),
                             float(pts[i + 3])]]
            for i in range(0, len(pts) - 3, 4)]
        below_rgb = (list(lut.BelowRangeColor)
                     if int(getattr(lut, "UseBelowRangeColor", 0) or 0)
                     else (core_colors[0][1] if core_colors else [0, 0, 0]))
        above_rgb = (list(lut.AboveRangeColor)
                     if int(getattr(lut, "UseAboveRangeColor", 0) or 0)
                     else (core_colors[-1][1] if core_colors else [1, 1, 1]))
        edges = _edges(view_id, name)
        # The COE graph keeps the DATA range as its axis: the colormap
        # occupies [lo, hi] and flat below / above BANDS (colour + opacity)
        # fill the rest. The band nodes are decorations — stripped on the
        # way back (_apply_cmap_nodes), they never reach the LUT.
        g_lo, g_hi = min(dr[0], lo), max(dr[1], hi)
        gspan = (g_hi - g_lo) or 1.0
        # The band's inner node sits 1e-4 of the axis outside the core —
        # sub-pixel on the graph, but clearly beyond the 1e-5 strip
        # tolerance of _apply_cmap_nodes (a node inside that tolerance
        # would be written to the LUT and re-decorated: endless loop).
        tiny = gspan * 1e-4
        core_op = _core_opacity_nodes(pwf, lo, hi)
        colors = list(core_colors)
        opac = list(core_op)
        if g_lo < lo - tiny:
            colors = [[g_lo, below_rgb], [lo - tiny, below_rgb]] + colors
            opac = [[g_lo, edges["below"]], [lo - tiny, edges["below"]]] + opac
        if g_hi > hi + tiny:
            colors = colors + [[hi + tiny, above_rgb], [g_hi, above_rgb]]
            opac = opac + [[hi + tiny, edges["above"]], [g_hi, edges["above"]]]
        state[f"ui_cmap_colors__{view_id}"] = colors
        state[f"ui_cmap_opacities__{view_id}"] = opac
        is_log = bool(int(getattr(lut, "UseLogScale", 0) or 0))
        scale = ("log" if is_log
                 else ("exp" if (view_id, name) in _cmap_exp else "linear"))
        # the box says whether THIS table's bar is on — the reader's choice,
        # read from the scene: the bar widget itself may not exist yet, or
        # show another table (one bar per view, engine/legends)
        bar = _scene.bar_visible(name) if _scene is not None else True
        try:
            nan_op = float(getattr(lut, "NanOpacity", 1.0))
        except Exception:
            nan_op = 1.0
        preset = _presets.get((view_id, name), _catp.DEFAULT_PRESET if categories else "")
        # the preset the card names, for the assistant (its undo puts it back)
        presets_by_view = dict(state.ui_active_colormap_by_view or {})
        if presets_by_view.get(view_id) != preset:
            presets_by_view[view_id] = preset
            state.ui_active_colormap_by_view = presets_by_view
        state[var] = {
            "array": name,
            "label": label,
            "preset": preset,
            # one colour per code, the reader's edits included; and why a
            # discrete property is nevertheless painted with a ramp
            "categorical": bool(categories),
            "categories": categories,
            "categories_note": cat_note,
            "min": lo, "max": hi, "data_min": dr[0], "data_max": dr[1],
            "graph_min": g_lo, "graph_max": g_hi,
            "log": is_log, "scale": scale,
            "below": _hex(below_rgb), "below_alpha": edges["below"],
            "above": _hex(above_rgb), "above_alpha": edges["above"],
            "nan": _hex(getattr(lut, "NanColor", None) or [1, 0, 0]),
            "nan_opacity": nan_op,
            # "Hide NaN cells": on, checked by the opacity, possible (else why)
            **_hide_nan_projection(view_id, name, assoc),
            "bar": bar,
            "is_ts": bool(is_ts), "is_mr": bool(is_mr),
            # a vector property: how many values per element, and which one
            # the session reads (the magnitude when none is chosen)
            "components": n_comp,
            "component": "magnitude" if comp is None else comp,
            "note": note or "",
        }

    def _hide_nan_projection(view_id, name, assoc):
        """What the Colormap card shows of "Hide NaN cells" for its array:
        checked when a grid painted by it has the mask on, "auto" when the
        opacity did it everywhere, disabled with the reason where the mask
        cannot act, and how many cells it hides."""
        off = {"hide_nan": False, "hide_nan_auto": False, "hide_nan_hidden": None}
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(view_id)
        if scene is not None and type(scene).__name__ == "GlobeScene":
            return {**off, "hide_nan_ok": False,
                    "hide_nan_why": "Not available in a Globe view"}
        logs = getattr(ctx, "log_nan", None)
        if logs is not None and logs[0](view_id, name):
            # a log drawn as a graph: its stretches without a value
            return {**off, "hide_nan": logs[1](view_id, name), "hide_nan_ok": True, "hide_nan_why": ""}
        if (assoc or "CELLS") != "CELLS":
            return {**off, "hide_nan_ok": False,
                    "hide_nan_why": "Only a cell property can hide cells: this one is on the nodes"}
        flagged = _hide_nan_flagged(view_id, name)
        if not flagged and not _hide_nan_grids(view_id, name):
            return {**off, "hide_nan_ok": False,
                    "hide_nan_why": "No visible grid is painted by this property"}
        hidden = [ctx.grid_isolates[(view_id, rp)].hide_nan_hidden
                  for rp in flagged if (view_id, rp) in ctx.grid_isolates]
        hidden = [h for h in hidden if h is not None]
        return {
            "hide_nan": bool(flagged),
            "hide_nan_auto": bool(flagged) and all(
                (ctx.grid_hide_nan.get((view_id, rp)) or {}).get("auto") for rp in flagged),
            "hide_nan_ok": True, "hide_nan_why": "",
            "hide_nan_hidden": sum(hidden) if hidden else None,
        }

    ctx.colormap_push = _push_colormap_state

    def _cmap_done(view_id, note=""):
        _push_colormap_state(view_id, note=note)
        scheduler.mark_dirty(view_id)
        scheduler.flush()
    return (_apply_pwf, _cmap_array_path, _cmap_components, _cmap_data_range, _cmap_done, _cmap_edges, _cmap_exp, _cmap_pushed, _cmap_target, _cmap_tfs, _core_opacity_nodes, _edges, _exp_remap, _find_scalar_bar, _hex, _lut_range, _node_positions, _presets, _push_colormap_state, _rgb, _set_node_positions, _table_path)
