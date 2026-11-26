"""The Property slicer — the Thresholds card as the shared slicer card on the
properties added to it (the PO's manager, 28/10: the same card as the
Geometry slicer; app/features/slicer_card_host does the gestures).

The card compiles into a sum of products (`engine/slicer_card.products`),
drawn as the view's threshold chain on the grid isolate: one branch per
product, its entries intersecting, the branches shown together
(`GridIsolate.replace_chain`, the filters rebuilt once). A live step (a
drag, the player) only moves the ranges of the entries on screen. A cut of
one value on a continuous property keeps a thin window around it (the
player's default width).

A chain made elsewhere — a session read back, the assistant — reaches the
card as one box per branch (`slicer_card.from_paths`).

A multi-realization property is ONE subject of the card, under its base
name; the array it reads is the realization the view shows (the Time &
Realizations card picks it, and the chain follows): the card offered
PORV_real_23 and PORV_real_24, two raw names for one property (the PO,
29/10 evening).

State: `ui_property_card__<vid>`, `ui_property_player__<vid>`.
"""
from fespp_on_trame.app.features.slicer_card_host import CardHost
from fespp_on_trame.engine import slicer_card as sc
from fespp_on_trame.engine import value_sweep


def register(core, *, _threshold_isolate, _threshold_target, _push_threshold_state,
             _push_grid_targets, _rep_card_arrays, _ensure_isolate, occupancy):
    """Wire the `property_slicer` controller."""
    controller = core.controller
    ctx = core.ctx
    state = core.state
    tree = core.tree
    scheduler = core.scheduler
    _cards = {}    # (vid, rep_path) -> (card, entry names per branch, subjects per branch)
    _mr_paths = {}  # (vid, rep_path, base name) -> the multi-realization property's path

    def _iso(vid, rep):
        return ctx.grid_isolates.get((vid, rep))

    def _arrays_of(vid, rep):
        """The subjects a card on `rep` can take, [{name, array}]: a
        multi-realization property once, under its base name, its array
        the realization the view shows."""
        from fespp_on_trame.engine import view_axes
        from fespp_on_trame.engine.realization_dispatch import suffixed_array_name
        from fespp_on_trame.engine.utils.naming import strip_realization_suffix
        out, seen = [], set()
        for a in _rep_card_arrays(rep):
            name = a["name"]
            base = strip_realization_suffix(name)
            if base in seen:
                continue
            seen.add(base)
            array = name
            if base != name:
                path = a.get("path") or ""
                _mr_paths[(vid, rep, base)] = path
                idx = view_axes.real_for(state, tree, vid, path) if path else None
                if idx is not None:
                    array = suffixed_array_name(base, idx)
            out.append({"name": base, "array": array})
        return out

    def _array_of(vid, rep, s):
        """The array subject `s` reads now: a multi-realization property's
        current realization, the property itself otherwise."""
        path = _mr_paths.get((vid, rep, s))
        if not path:
            return s
        from fespp_on_trame.engine import view_axes
        from fespp_on_trame.engine.realization_dispatch import suffixed_array_name
        idx = view_axes.real_for(state, tree, vid, path)
        return suffixed_array_name(s, idx) if idx is not None else s

    def context(vid, extra=()):
        rep = _threshold_target(vid)[0] or ""
        if not rep:
            return "", {}, ("The Property slicer acts on a grid, a surface, a polyline or a point"
                            " set — none is loaded in this view."), []
        ticked = [a["name"] for a in _arrays_of(vid, rep)]
        held = _cards.get((vid, rep))
        wanted = list(dict.fromkeys((held[0]["subjects"] if held else []) + [s for s in extra if s]))
        iso = _iso(vid, rep)
        if iso is None and wanted:
            # what a property is (its kind, its values) is read on the
            # object's cells: the isolate, built when a property is added
            iso = _ensure_isolate(vid, _threshold_target(vid))[0]
        infos = {}
        for s in wanted:
            dom = iso.array_domain(_array_of(vid, rep, s)) if iso is not None else None
            if dom is None:
                continue
            integer = dom["kind"] in ("Discrete", "Categorical")
            infos[s] = {"label": s, "kind": dom["kind"], "extent": list(dom["data_range"]),
                        "values": list(dom["unique_values"] or []) if integer else None,
                        "labels": dict(dom["labels"] or {})}
        note = "" if ticked or infos else ("Tick a property of this object in the tree: its values"
                                           " are what the card cuts.")
        addable = [{"value": n, "label": n} for n in ticked if n not in infos]
        return rep, infos, note, addable

    def _branches_of(chain):
        """The visible root-to-tip branches of a chain: [(subject, low,
        high)] — a realization's array under its property's base name."""
        from fespp_on_trame.engine.utils.naming import strip_realization_suffix
        by_name = {e["name"]: e for e in chain}
        visible = [e for e in chain if e.get("visible", True)]
        parents = {e.get("parent_name") for e in visible}
        out = []
        for tip in (e for e in visible if e["name"] not in parents):
            path, cur = [], tip
            while cur is not None:
                path.append((strip_realization_suffix(cur["array"]), cur["low"], cur["high"]))
                cur = by_name.get(cur.get("parent_name"))
            out.append(list(reversed(path)))
        return out

    def card_of(vid, rep, infos):
        key = (vid, rep)
        iso = _iso(vid, rep)
        chain = list(iso.get_chain() or []) if iso is not None else []
        held = _cards.get(key)
        if held is not None and (key in host.off
                                 or sorted(n for b in held[1] for n in b) == sorted(e["name"] for e in chain)):
            card = held[0]
        elif chain:
            # a chain made elsewhere: one box per branch
            card = sc.from_paths(_branches_of(chain), [])
            _cards[key] = (card, [[e["name"] for e in chain]], None)
        else:
            card = sc.empty(())
            _cards[key] = (card, [], [])
        # a property no longer ticked is no longer cut on
        for s in [s for s in card["subjects"] if s not in infos]:
            sc.remove_subject(card, s)
        return card

    def _branches(vid, rep, card, infos):
        """The chain branches of the card: one per product, a cut of one
        value only on a continuous property widened into its thin window; a card
        that cuts and keeps nothing gets a branch nothing passes. Each entry
        names the ARRAY its subject reads now."""
        out = []
        prods = sc.products(card, {s: info["extent"] for s, info in infos.items()})
        if any(not prod for prod in prods):
            # a piece cut on nothing (its subjects constant, its ranges
            # whole) keeps everything: the object whole, no chain
            return []
        for prod in prods:
            branch = []
            for s in card["subjects"]:
                if s not in prod:
                    continue
                lo, hi = prod[s]
                if lo == hi and infos[s]["kind"] == "Continuous":
                    a, b = infos[s]["extent"]
                    half = (float(b) - float(a)) * value_sweep.DEFAULT_WIDTH / 2.0
                    lo, hi = max(float(a), lo - half), min(float(b), hi + half)
                branch.append((_array_of(vid, rep, s), lo, hi))
            if branch:
                out.append(branch)
        if not out and card["subjects"]:
            out = [[(card["subjects"][0], 1.0, 0.0)]]
        return out

    def draw(vid, rep, card, infos, live):
        key = (vid, rep)
        try:
            branches = (_branches(vid, rep, card, infos)
                        if sc.cutting(card) and key not in host.off else [])
        except ValueError as exc:
            core.notifier.note(vid, f"Property slicer: {exc}")
            return
        shape = [[s for s, _lo, _hi in b] for b in branches]
        iso = _iso(vid, rep)
        held = _cards.get(key)
        if live and iso is not None and held is not None and held[2] == shape:
            # a step: the ranges of the entries on screen, nothing rebuilt
            for branch, names in zip(branches, held[1]):
                for (_s, lo, hi), name in zip(branch, names):
                    iso.set_range(name, lo, hi, update=False)
            scheduler.mark_dirty(vid)
            scheduler.flush()
            return
        if iso is None:
            if not branches:
                _cards[key] = (card, [], [])
                return
            iso = _ensure_isolate(vid, _threshold_target(vid))[0]
            if iso is None:
                return
        _cards[key] = (card, iso.replace_chain(branches), shape)
        occupancy.settle(vid, rep)
        _push_threshold_state(vid, iso)
        scheduler.mark_dirty(vid)
        scheduler.flush()

    host = CardHost(core, tool="thresholds", card_key="ui_property_card__",
                    player_key="ui_property_player__", context=context, card_of=card_of,
                    draw=draw)

    @controller.set("property_slicer")
    def property_slicer(edit, view_id):
        """One gesture of the Property slicer card (slicer_card_host)."""
        try:
            host.gesture(edit, view_id)
        except Exception as exc:
            print(f"[fespp] property slicer error ({view_id}):", exc, flush=True)

    def redraw(vid):
        """The card drawn again on what the view shows now — a realization
        picked in the Time & Realizations card: the chain reads the new
        array (app/features/timereal_slicer calls it)."""
        rep, infos, _note, _add = context(vid, ())
        if not rep:
            return
        card = card_of(vid, rep, infos)
        if card is not None and sc.cutting(card):
            draw(vid, rep, card, infos, False)
        host.publish(vid)

    def opened(vid):
        """The card opened (the PO, 30/10): with no box, and the view's
        active node a property of the card's object, a box with that
        property — the card starts on what the view is coloured by
        (app/features/view_wiring.toggle_tool calls it)."""
        rep, infos, _note, _add = context(vid, ())
        if not rep or (card_of(vid, rep, infos) or {}).get("boxes"):
            return
        active = core.activation.path(vid)
        if not active:
            return
        from fespp_on_trame.engine.utils.naming import strip_realization_suffix
        names = [strip_realization_suffix(a["name"]) for a in _rep_card_arrays(rep)
                 if a.get("path") == active]
        if names:
            host.gesture({"op": "add_subject", "subject": names[0]}, vid)

    # a property ticked or unticked, another object active or picked, the
    # chain changed elsewhere: the card reads them again
    # (app/features/node_helpers, app/features/thresholds call the listeners)
    ctx.slicer_listeners = list(getattr(ctx, "slicer_listeners", None) or []) + [host.publish]
    ctx.property_card_publish = host.publish
    ctx.property_card_redraw = redraw
    ctx.property_card_open = opened
    return host
