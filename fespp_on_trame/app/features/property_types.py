"""The kind of a property as the session knows it (the PO, 12/11): set in
the T→D view for the velocity a model reads (its row Velocity: Kind, Value
at), kept for the session by the property's uuid, the file's own kind
otherwise (engine/property_types). Whoever reads a kind follows a change
(`ctx.property_kind_listeners`: the T→D model reads its velocity again).
The tree's right-click "Type…" was taken out the same evening (the PO).

State:   ``property_kinds`` {uuid: kind}, the kinds set in the session;
         ``property_positions`` {uuid: "top" | "centre" | "bottom"}, where in
         its cell a velocity's value stands."""
from fespp_on_trame.engine import property_types, pwls_kinds


def register(core):
    state, ctx = core.state, core.ctx
    for name, default in (("property_kinds", {}), ("property_positions", {})):
        if getattr(state, name, None) is None:
            state[name] = default

    def _tree():
        return getattr(core, "tree", None)

    def set_kind(path, kind):
        """The property at `path` is of `kind` in this session ("" or an
        unknown kind: the file's again)."""
        tree = _tree()
        nid = tree.find_node_id(path) if tree is not None else None
        uuid = property_types.uuid_of(tree, nid) if nid is not None else ""
        if not uuid:
            return
        kinds = dict(state.property_kinds or {})
        kind = kind.strip().lower()
        if kind and pwls_kinds.known(kind) and kind != property_types.file_kind(tree, nid).lower():
            kinds[uuid] = kind
        else:
            kinds.pop(uuid, None)
        if kinds == dict(state.property_kinds or {}):
            return
        state.property_kinds = kinds
        print(f"[fespp] journal property type: {tree.find_title(nid)} is "
              f"{kinds.get(uuid) or 'of the file’s kind'}", flush=True)
        for hook in list(getattr(ctx, "property_kind_listeners", None) or ()):
            hook(path)

    def set_position(path, at):
        """Where in its cell the value of the property at `path` stands."""
        tree = _tree()
        nid = tree.find_node_id(path) if tree is not None else None
        uuid = property_types.uuid_of(tree, nid) if nid is not None else ""
        if not uuid or at not in property_types.POSITIONS:
            return
        positions = dict(state.property_positions or {})
        if at == property_types.DEFAULT_POSITION:
            positions.pop(uuid, None)
        else:
            positions[uuid] = at
        if positions == dict(state.property_positions or {}):
            return
        state.property_positions = positions
        print(f"[fespp] journal property type: {tree.find_title(nid)} stands at the {at} of its cells", flush=True)
        for hook in list(getattr(ctx, "property_kind_listeners", None) or ()):
            hook(path)

    ctx.property_kind_of = lambda node: property_types.kind_of(_tree(), node, state.property_kinds)
    ctx.property_position_of = lambda node: property_types.position_of(_tree(), node, state.property_positions)
    ctx.property_type_set = set_kind
    ctx.property_position_set = set_position
    ctx.property_kind_listeners = list(getattr(ctx, "property_kind_listeners", None) or [])
