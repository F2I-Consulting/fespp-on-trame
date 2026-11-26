"""An object's own look in a 3D view (the PO, 03/11): its solid colour —
what it is drawn in when no property paints it, the colour its tree chip
wears — and two opacities of the whole object: the one it is drawn at in
that colour, the one it is drawn at while a property paints it (the
colormap's opacities are per colour). Shown and set in the Colormap card,
on the view's active node; the tree's colour chip opens that card on its
object.

The colour is the session's (`solid_color_by_rep`, "#rrggbbaa", the chips
read it), drawn in every view; the opacities are the view's
(PdcScene.BlockEntry.solid_opacity and .opacity, the one in use projected as
BlockOpacities).

State:   ``ui_object_look__<vid>`` = {path, label, node ("geometry" |
         "property": what the active node is — the card shows the colour
         and the opacity on a geometry, the opacity and the colormap on a
         property), color ("#rrggbb"), painted (a property paints it: the
         colour shows where it does not), opacity (of the solid colour on a
         geometry, under a property on a property)} | {}.
Gestures: ``controller.object_color(hex, vid)``, ``controller.object_opacity(value, vid)``.
Hooks:   ``ctx.object_look_publish(vid)``.
"""
from fespp_on_trame.engine import data_facts, node_facts


def register(core, *, _rep_path_of):
    controller, ctx, state, tree = core.controller, core.ctx, core.state, core.tree
    scheduler = core.scheduler

    def _kind(path):
        return node_facts.kind_of(tree, path) if path else ""

    def _drawn(scene, rep, path):
        """What the view draws for the active node `path` of `rep`: `rep`
        itself — or, a log frame drawing nothing of its own, the channel
        `path` is, else the one channel its eye shows ("" when none)."""
        if _kind(rep) not in data_facts.LOG_PARENTS:
            return rep
        if path != rep:
            return path
        states = scene.block_state.items() if scene is not None else ()
        return next((sel for sel, entry in states
                     if entry.visible and sel.startswith(rep + "/")), "")

    def _target(vid):
        """(path, its scene entry) of what the active node of `vid` draws, a
        loaded representation (`_drawn`); ("", None) otherwise."""
        path = getattr(state, f"active_path__{vid}", None) or ""
        rep = _rep_path_of(path) if path else ""
        if not rep or rep not in (getattr(state, "ui_loaded_rep_paths", None) or ()):
            return "", None
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        rep = _drawn(scene, rep, path)
        return rep, (scene.block_state.get(rep) if rep and scene is not None else None)

    def _node_kind(vid):
        """"property" when the active node of `vid` shows values — a
        property, or a log frame, drawn through its channel alone — else
        "geometry" (the representation, its geometry node)."""
        kind = _kind(getattr(state, f"active_path__{vid}", None) or "")
        return "property" if node_facts.is_property_kind(kind) or kind in data_facts.LOG_PARENTS else "geometry"

    def _opacity_of(entry, kind):
        if entry is None:
            return 1.0
        op = entry.opacity if kind == "property" else entry.solid_opacity
        return float(op) if op is not None else 1.0

    def publish(vid):
        vid = str(vid)
        rep, entry = _target(vid)
        if not rep:
            out = {}
        else:
            nid = tree.find_node_id(rep)
            hexv = str((getattr(state, "solid_color_by_rep", None) or {}).get(rep) or "#cccccc")[:7]
            kind = _node_kind(vid)
            out = {"path": rep, "label": (tree.find_rep_title(nid) if nid is not None else "") or rep.rsplit("/", 1)[-1],
                   "node": kind,
                   "color": hexv, "painted": bool(entry is not None and entry.color_array),
                   "opacity": _opacity_of(entry, kind)}
        if out != (getattr(state, f"ui_object_look__{vid}", None) or {}):
            state[f"ui_object_look__{vid}"] = out

    def _scenes():
        return [(v, s) for v, s in (getattr(ctx, "blockscope_scenes", None) or {}).items() if s is not None]

    def set_color(rep, hexv):
        """`rep` drawn in `hexv` ("#rrggbb") where no property paints it, in
        every view; its tree chip follows. False when refused."""
        hexv = str(hexv or "")
        if not rep or len(hexv) < 7 or not hexv.startswith("#"):
            print(f"[fespp] object colour: refused {hexv!r} on {rep!r}", flush=True)
            return False
        colors = dict(getattr(state, "solid_color_by_rep", None) or {})
        alpha = str(colors.get(rep) or "")[7:9] or "ff"
        colors[rep] = hexv[:7] + alpha
        state.solid_color_by_rep = colors
        changed = dict(getattr(state, "ui_object_colors", None) or {})
        changed[rep] = hexv[:7]
        state.ui_object_colors = changed
        rgb = tuple(int(hexv[k:k + 2], 16) / 255.0 for k in (1, 3, 5))
        for v, scene in _scenes():
            entry = scene.block_state.get(rep)
            if entry is not None:
                entry.solid_rgb = rgb
                scene.reconcile()
                scheduler.mark_dirty(v)
        scheduler.flush()
        print(f"[fespp] journal object colour: {rep} {hexv[:7]}", flush=True)
        return True

    def set_opacity(vid, rep, value, solid=False):
        """The whole of `rep` at `value` (0..1) in view `vid`, in its solid
        colour or (`solid` False) under a property. False when refused
        (nothing drawn there)."""
        try:
            op = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            print(f"[fespp] object opacity ({vid}): refused {value!r}", flush=True)
            return False
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(str(vid))
        entry = scene.ensure_entry(rep) if scene is not None and rep else None
        if entry is None:
            print(f"[fespp] object opacity ({vid}): no object drawn to set it on", flush=True)
            return False
        setattr(entry, "solid_opacity" if solid else "opacity", op)
        scene.reconcile()
        scheduler.mark_dirty(str(vid))
        scheduler.flush()
        return True

    def opacities(vid, solid=False):
        """{rep: opacity} of the objects of `vid` not wholly opaque, in their
        solid colour or under a property: what a session keeps of the view."""
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(str(vid))
        if scene is None:
            return {}
        attr = "solid_opacity" if solid else "opacity"
        return {sel: float(getattr(e, attr)) for sel, e in scene.block_state.items()
                if getattr(e, attr) is not None and getattr(e, attr) < 0.999}

    @controller.set("object_color")
    def object_color(hexv, view_id):
        vid = str(view_id or "")
        rep, _entry = _target(vid)
        if set_color(rep, hexv):
            publish(vid)

    @controller.set("object_opacity")
    def object_opacity(value, view_id):
        vid = str(view_id or "")
        rep, _entry = _target(vid)
        if set_opacity(vid, rep, value, solid=_node_kind(vid) != "property"):
            publish(vid)

    state.ui_object_colors = {}
    ctx.object_look_publish = publish
    ctx.object_set_color = set_color
    ctx.object_set_opacity = set_opacity
    ctx.object_opacities = opacities
    return publish
