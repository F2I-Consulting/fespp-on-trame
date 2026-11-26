"""The Time & Realizations card as the shared slicer card (the PO, 29/10:
"the TS / MR / vector player should go and take the slicer: a cut of one
point = the time step, the realization's index, the vector's component";
app/features/slicer_card_host does the gestures, slicer_player the play,
looping or not — the same card as the Geometry and Property slicers).

Its subjects are what the view can step through: the time step of the
whole view (`view.ViewTime`) — the steps at which what the view colours by
changes, not every step of the session — the realization of each multi-realization
property the view colours by, the component of each vector property (its
magnitude being one more value). Each is a cut of one value in ONE Slice
box: the value is what the view shows, the player steps it. The boxes'
algebra means nothing here — a value shown is one value: the first cut of
the first Slice box is the one in force.

The application stays in app/features/time_realization (the view's time,
the realization shown; its controllers serve the assistant and the session
read back) and in colormap_edits (`set_vector_component`); this card asks
them. State: `ui_timereal_card__<vid>`, `ui_timereal_player__<vid>`; the old
`ui_timereal__<vid>` stays for the assistant.
"""
from fespp_on_trame.app.features.slicer_card_host import CardHost
from fespp_on_trame.engine import slicer_card as sc

TIME = "time"
# the card's object: the view itself
VIEW = "@view"


def nearest(values, at):
    """The value of `values` nearest to `at` (the lower on a tie); `at`
    itself when there are none."""
    best = None
    for v in values or ():
        if best is None or abs(float(v) - float(at)) < abs(float(best) - float(at)):
            best = v
    return at if best is None else best


def component_labels(n):
    """The labels of a vector's components: X, Y, Z for three, their numbers
    otherwise; |v| for the magnitude, the value -1."""
    names = ("X", "Y", "Z") if n == 3 else tuple(str(i + 1) for i in range(n))
    labels = {-1: "|v|"}
    labels.update({i: names[i] for i in range(n)})
    return labels


def time_info(steps, labels):
    """The card's Time step subject over `steps` (their indices, in order),
    `labels` {index: date}: a series of one step goes by "Unique time step",
    its date alone beside it (the slicer card's `single_label`)."""
    return {"label": "Time step", "single_label": "Unique time step", "kind": "Categorical",
            "extent": [steps[0], steps[-1]], "values": list(steps), "labels": labels}


def cut_values(card):
    """{subject: the value its first cut is at} of the first Slice box of
    `card` — what the card asks the view to show."""
    out = {}
    for box in card.get("boxes") or ():
        if box.get("mode") != sc.SLICE:
            continue
        for s, cuts in (box.get("cuts") or {}).items():
            if cuts:
                out[s] = cuts[0].get("at")
        break
    return out


def point_cuts(card, box, current):
    """The cuts of `box` set to `current` ({subject: value}): what the view
    shows, read back into the card."""
    for s, cuts in (box.get("cuts") or {}).items():
        if cuts and current.get(s) is not None:
            cuts[0]["at"] = float(current[s])


def register(core, *, timereal, _eye_driven_colors):
    """Wire the `timereal_slicer` controller. `timereal`: what
    time_realization.register hands back (push, apply_time, time_index,
    time_values, steps, specs, set_realization, after_push)."""
    controller = core.controller
    state = core.state
    tree = core.tree
    ctx = core.ctx
    scheduler = core.scheduler
    _cards = {}    # vid -> its card
    _asked = {}    # vid -> {subject: the value the card last asked the view for}

    def _components(array_path):
        """The values per element of a property, read on the source's
        output as it stands (1: a scalar, or an array not read yet) — not
        through the proxy's data information, which brings the pipeline up
        to date: asked in the middle of a lazy ETP read, that hung the
        server (29/10, a log ticked on a cut scene of 25 objects)."""
        from fespp_on_trame.engine import stats_dispatch
        from fespp_on_trame.engine.blockscope.scene_crop import _leaves
        _t, _k, name = stats_dispatch._resolve_vtk_name(tree, array_path)
        if not name:
            return 1
        try:
            data = ctx.active_data_source.get_display_source().GetClientSideObject().GetOutputDataObject(0)
        except Exception as exc:
            print(f"[fespp] Time & Realizations: no source output ({exc})", flush=True)
            return 1
        if data is None:
            return 1
        leaves = [ds for _it, ds in _leaves(data)] if data.IsA("vtkCompositeDataSet") else [data]
        for ds in leaves:
            for attrs in (ds.GetCellData(), ds.GetPointData()):
                arr = attrs.GetAbstractArray(name)
                if arr is not None:
                    return int(arr.GetNumberOfComponents() or 1)
        return 1

    def _vectors(vid):
        """[(array_path, title, components)] of the vector properties the
        view colours by."""
        out, seen = [], set()
        for _sel, p in (_eye_driven_colors.get(vid) or {}).items():
            if not p or p in seen:
                continue
            seen.add(p)
            n = _components(p)
            if n < 2:
                continue
            nid = tree.find_node_id(p)
            title = ""
            if nid is not None:
                title = tree.find_attribute_value(nid, "propTitle") or tree.find_title(nid) or ""
            out.append((p, title or p.rsplit("/", 1)[-1], n))
        return out

    def context(vid, _extra=()):
        from fespp_on_trame.engine import time_realization as _tr
        infos = {}
        values = timereal["time_values"]()
        # the steps at which what the view colours by changes, no other
        steps = timereal["steps"](vid) if values else []
        if steps:
            labels = {i: (_tr.label_for_time_value(tree, values[i]) or str(values[i])) for i in steps}
            infos[TIME] = time_info(steps, labels)
        for spec in timereal["specs"](vid):
            avail = [int(i) for i in spec["available_indices"]]
            infos[f"real:{spec['array_path']}"] = {
                "label": spec["title"], "kind": "Categorical", "extent": [min(avail), max(avail)],
                "values": avail, "labels": {i: str(i) for i in avail}}
        for path, title, n in _vectors(vid):
            infos[f"vec:{path}"] = {"label": f"{title} component", "kind": "Categorical",
                                    "extent": [-1, n - 1], "values": list(range(-1, n)),
                                    "labels": component_labels(n)}
        if not infos:
            return "", {}, "", []
        return VIEW, infos, "", []

    def _current(vid, s):
        """The value the view shows for subject `s`, or None."""
        if s == TIME:
            return timereal["time_index"](vid)
        kind, path = s.split(":", 1)
        if kind == "real":
            from fespp_on_trame.engine import realization_dispatch as _rd
            return _rd.get_active_realization_for_view(state, vid, path)
        if kind == "vec":
            v = (getattr(state, "ui_vector_component", None) or {}).get(path)
            return -1 if v is None else int(v)
        return None

    def card_of(vid, rep, infos):
        card = _cards.get(vid)
        if card is None or list(card["subjects"]) != list(infos):
            # one Slice box, one cut a subject
            card = sc.empty(tuple(infos))
            exts = {s: info["extent"] for s, info in infos.items()}
            values = {s: info["values"] for s, info in infos.items()}
            box = sc.new_box(card, exts, mode=sc.SLICE, values=values, whole=tuple(infos))
            for s in infos:
                sc.new_cut(card, box, s, exts[s], values[s], whole=True)
            _cards[vid] = card
        # a cut follows the view when another hand moved it (the assistant,
        # a session read back) — not when this card asked for the value the
        # view shows: the card is read again between a gesture and its
        # drawing (the player's refresh), and a cut set back to the view's
        # value there lost the hand's (the PO, 29/10 evening: "I move the
        # point, the 3D view does not follow")
        asked = _asked.setdefault(vid, {})
        for box in card["boxes"]:
            if box.get("mode") == sc.SLICE:
                moved = {}
                for s in infos:
                    cur = _current(vid, s)
                    if cur is None:
                        continue
                    cur = nearest(infos[s]["values"], cur)
                    if asked.get(s) != cur:
                        moved[s] = cur
                        asked[s] = cur
                point_cuts(card, box, moved)
                break
        return card

    def _apply(vid, s, value):
        if s == TIME:
            timereal["apply_time"](vid, int(value))
            return
        kind, path = s.split(":", 1)
        if kind == "real":
            timereal["set_realization"]([path, int(value)], vid)
            # the Property slicer's chain on that property reads the new
            # realization's array
            redraw = getattr(ctx, "property_card_redraw", None)
            if redraw is not None:
                redraw(vid)
        elif kind == "vec":
            controller.set_vector_component(path, None if int(value) < 0 else int(value))

    def draw(vid, rep, card, infos, live):
        """The view shown as the card's cuts say."""
        changed = False
        asked = _asked.setdefault(vid, {})
        for s, at in cut_values(card).items():
            info = infos.get(s)
            if info is None or at is None:
                continue
            value = nearest(info["values"], at)
            asked[s] = value
            if value == _current(vid, s):
                continue
            _apply(vid, s, value)
            changed = True
        if changed:
            scheduler.mark_dirty(vid)
            scheduler.flush()

    # rows of one value, nothing else (the PO, 29/10): no box to add, hide
    # or remove, no Range / Slice, no ≤ = ≥, one cut a subject
    host = CardHost(core, tool="timereal", card_key="ui_timereal_card__",
                    player_key="ui_timereal_player__", context=context, card_of=card_of,
                    draw=draw, fixed_subjects=True,
                    shape={"boxes": False, "modes": False, "cmp": False, "many": False})

    @controller.set("timereal_slicer")
    def timereal_slicer(edit, view_id):
        """One gesture of the Time & Realizations card (slicer_card_host)."""
        host.gesture(edit, view_id)

    @core.lifecycle.on("view_closed")
    def _forget_view(vid):
        _cards.pop(vid, None)
        _asked.pop(vid, None)
        host.player.drop(vid, "the view closed")

    _steps_seen = {}   # vid -> the time steps the card last offered

    def follow(vid):
        """The card published again; when the view's time steps changed
        (another series coloured), the view keeps its step when the new
        series has one there, else goes to the first; a player on the card
        steps through the new ones."""
        from fespp_on_trame.engine import time_realization as _tr
        steps = tuple(timereal["steps"](vid))
        if _steps_seen.get(vid) == steps:
            host.publish(vid)
            return
        _steps_seen[vid] = steps
        cur = timereal["time_index"](vid)
        kept = _tr.position_kept(steps, cur)
        if kept != cur:
            timereal["apply_time"](vid, kept)   # publishes again
        else:
            host.publish(vid)
        if host.player.row(vid) is not None:
            host.player.refresh(vid)

    @core.lifecycle.on("view_closed")
    def _forget_steps(vid):
        _steps_seen.pop(vid, None)

    # the card follows the view's time, realizations and vectors as the old
    # state does (a time series read, the eye changed)
    timereal["after_push"].append(follow)
    return follow
