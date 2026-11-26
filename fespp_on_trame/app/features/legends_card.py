"""the Legends card (engine/legends)

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine import legends
from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.engine.utils import numfmt


def register(core, *, _cmap_pushed, _cmap_target, _eye_driven_colors, _hex,
             _lut_range, _push_colormap_state):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    ctx = core.ctx
    tree = core.tree
    scheduler = core.scheduler
    _extracts = core.selection.extracts
    # --- the Legends card (engine/legends) ----------------------------------
    def _lut_stops(lut, lo, hi, log):
        """A continuous table's colours sampled left to right, as the bar
        paints them: read from the table itself (its colour space, its log
        scale), not re-interpolated from its nodes in the browser."""
        ctf = lut.GetClientSideObject()
        stops = []
        for x in legends.sample_positions(lo, hi, legends.SWATCH_STOPS, log):
            rgb = [0.0, 0.0, 0.0]
            ctf.GetColor(x, rgb)
            stops.append(_hex(rgb))
        return stops

    def _legend_describe(table):
        from fespp_on_trame.engine import categorical_palette as _catp
        lut = table["lut"]
        if _catp.is_indexed(lut):
            return {"codes": _catp.read(lut)}
        lo, hi = _lut_range(lut)
        log = bool(int(getattr(lut, "UseLogScale", 0) or 0))
        return {"lo": numfmt.fmt(lo), "hi": numfmt.fmt(hi), "log": log,
                "stops": _lut_stops(lut, lo, hi, log)}

    def _legend_where(vid, table):
        """`family` and `owners` of a legend row: the tree family of the
        properties the table paints (Reservoir, Well, Surface, Seismic — as
        the tree's cards sort, engine/tree_families.of_path) and the objects they belong to, by name: a grid's
        property names its grid (the blocked wellbores it also paints are
        its own), a log names its wellbore, two wells' GR both wells."""
        from fespp_on_trame.engine import tree_families
        eyed = _eye_driven_colors.get(vid) or {}
        family, owners = "", []
        for sel in table.get("selectors") or ():
            path = eyed.get(sel) or sel
            # an extract drawn in the grid's place: the table paints it, by
            # its own name (the PO, 21/10)
            shown = [e.get("title") for e in (_extracts.get(vid) or [])
                     if e.get("visible") and e.get("selector") == sel and e.get("title")]
            tab, nid = tree_families.of_path(tree, path)
            if tab:
                family = family or legends.family_of_tab(tab)
                for name in (shown or [tree.find_title(nid) or ""]):
                    if name and name not in owners:
                        owners.append(name)
        return {"family": family or "other", "owners": owners}

    def _publish_legends(vids):
        """Before a view is drawn (the render scheduler's flush): its
        Legends card lists every table colouring it, and its Colormap card
        is projected again when the table it falls back to has moved (a
        load pruned the old one, an eye opened without a click) — the
        card, the bar and the list read the scene the frame is drawn from."""
        scenes = getattr(ctx, "blockscope_scenes", None) or {}
        for vid in vids:
            scene = scenes.get(vid)
            if scene is None or not per_view_state.is_live(vid):
                continue
            try:
                # an eye pass an exception cut short must not leave the bar
                # frozen: nothing draws in the middle of one
                scene.end_bar_gesture()
                tgt = _cmap_target(vid)
                if (tgt[0] if tgt is not None else "") != _cmap_pushed.get(vid, ""):
                    _push_colormap_state(vid)
                tables, focus, hidden = scene.legend_tables()
                rows = legends.legend_rows(
                    tables, focus, hidden,
                    lambda t, vid=vid: {**_legend_describe(t),
                                        **_legend_where(vid, t)})
                var = f"ui_legends__{vid}"
                said = {"tables": rows, "bar": scene.bar_length()}
                if (getattr(state, var, None) or {}) != said:
                    state[var] = said
            except Exception as exc:
                print(f"[fespp] legends error ({vid}):", exc, flush=True)

    scheduler.add_flush_listener(_publish_legends)
