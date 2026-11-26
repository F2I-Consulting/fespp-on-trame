"""The doors to the slicer cards (the PO's manager, 28/10): besides the
view's toolbar button (the active node), a right-click on a node of the
tree or on an object of the 3D view opens the Geometry or the Property
slicer of a 3D view on THAT object — picked in the card's list, so it stays
the card's object until another is picked. The Property slicer opened on a
property starts cutting on it (the manager, 29/10: "the right-click does
not initialise it"); opened on an object, on the property it is coloured
by when that one is ticked."""
from fespp_on_trame.engine import view_routing

# the card each door opens, and the controller that points it at an object
_DOORS = {"geometry-slicer": ("slicers", "geometry_slicer"),
          "property-slicer": ("thresholds", "property_slicer")}
_NAMES = {"slicers": "Geometry slicer", "thresholds": "Property slicer"}


def register(core, *, _rep_path_of, _rep_card_arrays):
    """Wire the `open_slicer` controller."""
    state = core.state
    controller = core.controller
    activation = core.activation
    cards = core.cards
    ctx = core.ctx

    def _first_property(vid, path, rep):
        """The property the Property slicer starts on: the one right-clicked,
        else the one painting the object in `vid` — when ticked; None."""
        arrays = _rep_card_arrays(rep)
        for a in arrays:
            if a.get("path") == path:
                return a["name"]
        scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
        entry = scene.block_state.get(rep) if scene is not None else None
        painting = getattr(entry, "color_array", "") or ""
        if painting:
            from fespp_on_trame.engine.utils.naming import strip_realization_suffix
            for a in arrays:
                if strip_realization_suffix(a["name"]) == strip_realization_suffix(painting):
                    return a["name"]
        return None

    @controller.set("open_slicer")
    def open_slicer(door, path, view_id=None):
        """Open the card `door` ("geometry-slicer" | "property-slicer") of
        `view_id` (the active 3D view when None) on the object of `path`."""
        try:
            tool, pointer = _DOORS[door]
        except KeyError:
            print(f"[fespp] open slicer: unknown door {door!r}", flush=True)
            return
        vid = str(view_id) if view_id else view_routing.resolve_active_render_panel(state)
        rep = _rep_path_of(path) or path if path else ""
        if not vid or not rep:
            return
        if rep not in activation.targets(vid, tool):
            core.notifier.say(f"The {_NAMES[tool]} cannot cut this object.")
            return
        getattr(controller, pointer)({"op": "target", "path": rep}, vid)
        if tool == "thresholds":
            name = _first_property(vid, path, rep)
            if name:
                controller.property_slicer({"op": "add_subject", "subject": name}, vid)
        if not cards.is_open(vid, tool):
            controller.toggle_tool(tool, vid)
