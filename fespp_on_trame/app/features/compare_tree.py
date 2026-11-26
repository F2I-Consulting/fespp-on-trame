"""The gestures of the Statistics view (`compare` in the code): its docked
tree, the widget's one `set` channel and the session door (app/session_host).
The view keeps a state per kind tab, and gives every selected item a uid from
its own counter — a restored selection takes NEW uids (an old "i3" would
collide with the next one made) and its baselines follow them."""
from fespp_on_trame.engine import compare_matrix
from fespp_on_trame.engine import crossplot_dispatch
from fespp_on_trame.engine import compare_dispatch
from fespp_on_trame.engine import compare_rows
from fespp_on_trame.engine import compare_tree
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine import tick_confirm
from fespp_on_trame.app.views import per_view_state

_FOLLOWS = "this row follows the row above it"
# why a gesture does not apply to a row that follows an item (engine/compare_rows)
_REFUSED_ON_FOLLOWING = {
    "baseline": "the baseline is a row of the property itself",
    "pin": _FOLLOWS, "unpin": _FOLLOWS, "pin_all": _FOLLOWS, "unpin_all": _FOLLOWS,
    "real": _FOLLOWS, "ts": _FOLLOWS,
    "remove": ("this row is the 3D view's: it goes when the view shows the whole"
               " grid again, or closes its eye"),
}


def _is_part(syn):
    """A path of the docked tree on a part of a grid, or on a folder of them."""
    return node_facts.is_under(syn, [compare_tree.PARTS_FOLDER])


def register(core, *, _ask_tick, _compare, _tree_tick,
             _compare_current_kind, _compare_index, _compare_item_key,
             _compare_items, _compare_loaded_paths, _compare_names,
             _compare_note, _compare_parts, _compare_published, _compare_request_load,
             _compare_resort, _compare_set_axis, _compare_tick_note,
             _compare_uid, _kind_state, _project_kind_state,
             _rebuild_compare_tree, _refresh_compare, _refresh_compare_now,
             _set_compare_items, _set_compare_parts,
             _sync_compare_tree_selection, open_compare):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_compare_add, _sync_compare_tree_eyes, _sync_panel_tree_eyes)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    _mv = core.mv
    from fespp_on_trame.app.boot import _COMPARE_DIST_OPTS
    # --- the session door (app/session_host): the view keeps a state per kind
    # tab in this closure, and gives every selected item a uid from its own
    # counter — a restored selection takes NEW uids (an old "i3" would
    # collide with the next one made) and its baselines follow them
    @controller.set("session_compare_state")
    def session_compare_state():
        import copy
        selected = set(getattr(state, "selected_paths", None) or [])
        return {"items": [dict(i) for i in _compare_items()],
                # the parts the session reads, in the file: an extract is its
                # view's, it comes back with it
                "parts": [p for p in _compare_parts() if p in selected],
                "tab": getattr(state, "ui_compare_tab", "") or "",
                "kinds": copy.deepcopy(_compare["kinds"])}

    @controller.set("session_compare_restore")
    def session_compare_restore(saved):
        """Returns {the uid an item was saved under: its uid now}."""
        saved = saved or {}
        renamed, items = {}, []
        for it in saved.get("items") or ():
            new = dict(it)
            new["uid"] = _compare_uid()
            if it.get("uid"):
                renamed[it["uid"]] = new["uid"]
            items.append(new)
        state.ui_compare_items = items
        parts = list(saved.get("parts") or ())
        _set_compare_parts(parts)
        for kind, st in (saved.get("kinds") or {}).items():
            st = dict(st)
            st.pop("transposed", None)  # what an older document may hold
            for slot in ("baseline", "xplot_x", "xplot_y"):
                st[slot] = renamed.get(st.get(slot), st.get(slot) or "")
            # a document saved with no parts knew no Mean (L) either: not left
            # out of its metrics by a choice
            if "parts" not in saved and "visible_metrics" in st:
                st["visible_metrics"] = [m for m in compare_matrix._METRIC_KEYS
                                         if m in st["visible_metrics"] or m == "Mean (L)"]
            if "dist_opts" in st:
                st["dist_opts"] = dict(_COMPARE_DIST_OPTS, **st["dist_opts"])
            # a document written by hand may say part of it: the rest is the
            # kind's default
            _compare["kinds"].pop(kind, None)
            _kind_state(kind).update(st)
        if saved.get("tab"):
            state.ui_compare_tab = saved["tab"]
        # what it holds waits for its values, as a tick's does: the document's
        # reads may still be on their way, and what it does not read is read
        plan = compare_tree.tick_plan([it["path"] for it in items if it.get("path")], items,
                                          _compare_loaded_paths(), _compare["pending"])
        _compare["pending"] = plan["pending"]
        selected = set(getattr(state, "selected_paths", None) or [])
        stuck = _compare_request_load(plan["to_load"] + [p for p in parts if p not in selected])
        if plan["to_load"]:
            _rebuild_compare_tree()
        open_compare()
        _refresh_compare_now()
        _compare_tick_note(stuck)
        return renamed

    def _compare_add(entries):
        """"Stats": the entries join the selection, and the view opens on the
        kind of the last one; the rows of another kind leave, as an eye
        opened in a 3D view's tree has them (`_stats_follow_eyes`)."""
        entries = [e for e in entries or () if isinstance(e, dict) and e.get("path")]
        if not entries:
            return
        _keep_kinds_of([e["path"] for e in entries])
        _compare_join(entries)
        state.ui_compare_tab = compare_dispatch._kind_label(tree, entries[-1]["path"])
        controller.open_compare()
        _refresh_compare()

    def _compare_join(entries):
        """Each entry ({path, real, ts}) joins the selection at the realization
        / time step it reads — one already there at the same coordinates is not
        doubled, and nothing else leaves: the kind rule is the tree's tick and
        eye. What is not read is read, exactly as a tick in the tree reads it."""
        entries = [{"path": e["path"],
                    "real": compare_dispatch._int_or_none(e.get("real")),
                    "ts": compare_dispatch._int_or_none(e.get("ts"))}
                   for e in entries or () if isinstance(e, dict) and e.get("path")]
        if not entries:
            return
        items = _compare_items()
        have = {(it["path"], it["real"], it["ts"]) for it in items}
        fresh = []
        for e in entries:
            coord = (e["path"], e["real"], e["ts"])
            if coord not in have:
                have.add(coord)
                fresh.append(e)
        if fresh:
            known = {it["path"] for it in items}
            new_paths = []
            for e in fresh:
                if e["path"] not in known and e["path"] not in new_paths:
                    new_paths.append(e["path"])
            plan = compare_tree.tick_plan(
                [it["path"] for it in items] + new_paths, items,
                _compare_loaded_paths(), _compare["pending"])
            _compare["pending"] = plan["pending"]
            stuck = _compare_request_load(plan["to_load"])
            # the entries of a new property carry their own coordinates:
            # they take the place of the default entry the plan added
            merged = ([it for it in plan["items"] if it["path"] not in new_paths]
                      + fresh)
            # the leaf of a property being read says so, as it does on a
            # tick — unless no view is open yet to hold a tree
            if plan["to_load"] and _compare["views"]:
                _rebuild_compare_tree(merged)
            else:
                _set_compare_items(merged)
            _compare_tick_note(stuck)

    def _stats_follow_eyes(opened, closed):
        """An eye of a 3D view's tree opened or closed: the Statistics view's on
        the same objects follows — a property its row, a part its rows. What the
        one-eye-per-grid rule closes by itself stays here: this view shows
        several properties of one grid."""
        parts = set(stats_supports.assembly_parts(tree))
        held = _compare_parts()
        kept = [p for p in held if p not in closed] + [p for p in opened if p in parts and p not in held]
        if kept != held:
            _set_compare_parts(kept)
        items = _compare_items()
        rows = [it for it in items if it["path"] not in closed]
        if len(rows) != len(items):
            _set_compare_items(rows)
        props = [p for p in opened if node_facts.is_property(tree, p)]
        _keep_kinds_of(props)
        _compare_join([{"path": p} for p in props])
        _refresh_compare()

    def _keep_kinds_of(paths):
        """The properties among `paths` are the kind last asked for: the rows
        of another kind leave, as an eye of this view's own tree has them
        (`_eye_opens`)."""
        props = [p for p in paths if node_facts.is_property(tree, p)]
        if not props:
            return
        kinds = {compare_dispatch._kind_label(tree, p) for p in props}
        items = _compare_items()
        rows = [it for it in items if compare_dispatch._kind_label(tree, it["path"]) in kinds]
        if len(rows) != len(items):
            _set_compare_items(rows)

    core.ctx.stats_follow_eyes = _stats_follow_eyes

    @controller.set("compare_tree_map")
    def compare_tree_map():
        """The docked tree's synthetic path -> real property path (the
        harness ticks through it, as a click would)."""
        return dict(_compare["path_map"])

    def _compare_ticked_paths(paths):
        """The real property paths a set of ticked tree paths stands for: a
        leaf is itself, a KIND or REPRESENTATION folder is every leaf under
        it — the widget sends the folder's own path and the cascade is the
        server's, exactly as in the data tree."""
        pmap = _compare["path_map"]
        ticked = []
        for syn in paths or ():
            hits = ([pmap[syn]] if syn in pmap
                    else [p for s, p in pmap.items()
                          if s.startswith(f"{syn}/")])
            for p in hits:
                if p not in ticked:
                    ticked.append(p)
        return ticked

    def _compare_ask(vid, ticked, to_read):
        """One click that would read more than it can show asks first —
        through the SAME box as every other tree (`_ask_tick`). The plan is
        kept here and replayed on a yes: nothing is read, nothing joins the
        view, and the boxes stay as the user left them until the
        answer (`_sync_compare_tree_selection` stands back meanwhile)."""
        _compare["confirm"] = {"vid": str(vid or ""), "ticked": list(ticked)}

        def _yes():
            req = _compare["confirm"]
            _compare["confirm"] = None
            if req:
                _compare_apply_tick(req["vid"], req["ticked"])

        def _no():
            _compare["confirm"] = None
            _sync_compare_tree_selection()

        _ask_tick(len(to_read), _yes, _no, shown=False)

    def _compare_apply_tick(vid, ticked, max_load=None):
        """One new item (default real / time) per newly ticked property,
        every item of an unticked one dropped. A property the session has
        not read is LOADED by the tick — through `selected_paths`, the very
        channel the data tree writes, so every cascade of the load pipeline
        applies — and its item waits, saying so, until the values are there.
        An untick leaves the view and nothing else: unloading here
        would pull the property out of the 3D views showing it.
        Above `max_load` unread properties the tick ASKS first and this
        returns having changed nothing."""
        items = _compare_items()
        plan = compare_tree.tick_plan(
            ticked, items, _compare_loaded_paths(), _compare["pending"],
            max_load=max_load)
        if plan["confirm"]:
            _compare_ask(vid, ticked, plan["confirm"])
            return
        _compare["pending"] = plan["pending"]
        stuck = _compare_request_load(plan["to_load"])
        if plan["to_load"]:
            # the leaves of the properties being read now say "loading",
            # and the rebuild writes the selection once
            _rebuild_compare_tree(plan["items"])
        elif plan["items"] != items:
            _set_compare_items(plan["items"])
        else:
            # nothing changed but the widget may hold a folder tick: give it
            # back the leaves it actually stands for
            _sync_compare_tree_selection()
        _compare_tick_note(stuck)

    def _compare_hold_properties(view_id, paths, max_load=None):
        """The properties the panel holds, folders cascaded (a part it holds
        is no item: `_compare_hold`)."""
        vid = str(view_id or "")
        incoming = [p for p in (paths or ()) if p and not _is_part(p)]
        if vid in _compare_published and set(incoming) == {p for p in _compare_published[vid] if not _is_part(p)}:
            # the server's own rewrite coming back, not a gesture
            return
        _compare_apply_tick(vid, _compare_ticked_paths(incoming), max_load=max_load)

    @controller.set("compare_tree_paths")
    def compare_tree_paths(view_id, paths):
        """What the panel holds, said from outside its tree (the assistant's
        undo, a harness). The cap is a QUESTION, not a refusal: see
        `_compare_apply_tick`."""
        _compare_hold_properties(view_id, paths, max_load=tick_confirm.MAX_TICK_LOAD)

    def _compare_render_vids():
        mv = _mv()
        if mv is None:
            return []
        return [v for v in mv.view_ids()
                if per_view_state.is_live(v)]

    def _compare_visible_paths():
        """Every path a 3D view is showing, all views taken together."""
        seen = set()
        for rvid in _compare_render_vids():
            seen.update(getattr(state, f"visible_paths__{rvid}", None) or [])
        return seen

    @controller.set("panel_tree_eye")
    def panel_tree_eye(view_id, ev, kind=None):
        """An eye clicked in the well-log or Log <-> Grid tree: "in this panel"
        (the one grammar, app/scene/panel_trees) — the well, the row taken in
        or let go; nothing is read or unloaded."""
        ev = ev if isinstance(ev, dict) else {}
        paths = [p for p in (ev.get("paths")
                             or ([ev["path"]] if ev.get("path") else []))
                 if p]
        if not paths:
            return
        vid = str(view_id or "")
        kind = kind or core.panel_trees.kind_of(vid)
        # the one grammar: the eye of a panel's tree is "in this panel"
        core.panel_trees.eye(kind, vid, paths,
                             bool(ev["visible"]) if "visible" in ev else None)

    def _panel_tree_eyeable():
        """What a 3D view could show: the representations, the arrays and the
        wellbore markers the session holds. An eye on anything else would be
        a door onto nothing — which is the only thing that ever gates an eye.

        Markers have their own bucket (`data_load._update_marker_tracking`)
        and are exactly what the log tree is about: left out, a marker a 3D
        view is showing would sit in the tree with no eye to close it."""
        return (list(getattr(state, "ui_loaded_rep_paths", None) or [])
                + list(getattr(state, "ui_loaded_array_paths", None) or [])
                + list(getattr(state, "ui_loaded_marker_paths", None) or []))

    @controller.set("panel_tree_eyes")
    def panel_tree_eyes(view_id, kind):
        """The eyes of ONE docked tree, published on demand: a panel that
        opens calls this from its tree, because a well-log panel is not a
        render panel and its arrival changes no list anybody else watches —
        without it the tree would come up with no eye at all until an
        unrelated click in a 3D view."""
        vid = str(view_id or "")
        shown = list(_compare_visible_paths())
        able = _panel_tree_eyeable()
        for var, val in ((f"{kind}_tree_eye__{vid}", shown),
                         (f"{kind}_tree_shown__{vid}", able)):
            if set(getattr(state, var, None) or []) != set(val):
                state[var] = val

    def _sync_panel_tree_eyes():
        """The eyes of the three docked trees: which paths a 3D view is
        SHOWING, and which ones it could show. The well-log and Log <-> Grid
        trees speak the assembly's own paths; the Statistics view's are
        synthetic and keep their own mapping."""
        _sync_compare_tree_eyes()
        mv = _mv()
        if mv is None:
            return
        for kind in ("welllog", "reconcile"):
            for vid in mv.panel_ids_of_kind(kind):
                panel_tree_eyes(vid, kind)

    def _sync_compare_tree_eyes():
        """The docked tree's eyes, in its synthetic paths: which properties
        a 3D view is SHOWING, and which ones it could show (the ones the
        session holds — an eye on a property with no values would be a door
        onto nothing)."""
        if not _compare["views"]:
            return
        # and its boxes: a view opened on a tree the same as before (nothing
        # read since) gets them from here, no change of the tree announcing it
        _sync_compare_tree_loaded()
        pmap = _compare["path_map"]
        held = set(_compare_loaded_paths())
        visible = _compare_visible_paths()
        eyes = [s for s, p in pmap.items() if p in visible]
        able = [s for s, p in pmap.items() if p in held]
        for vid in list(_compare["views"]):
            for var, val in ((f"compare_tree_eye__{vid}", eyes),
                             (f"compare_tree_shown__{vid}", able)):
                if set(getattr(state, var, None) or []) != set(val):
                    state[var] = val

    @state.change("fespp_render_panels")
    def _on_compare_render_panels(**_):
        # The 3D views changed. A view that CLOSES takes its eyes with it, and
        # nothing else says so: its own eye set is nulled by the per-view
        # teardown, which marks the view dead first, so `on_eye_changed`
        # returns before it can tell the docked trees. This list is published
        # once the view is out of the manager — the earliest moment the eyes
        # can be counted without it.
        _sync_panel_tree_eyes()

    @state.change("ui_loaded_rep_paths", "ui_loaded_array_paths",
                  "ui_loaded_marker_paths")
    def _on_panel_tree_eyeable(**_):
        # what a 3D view COULD show has just changed, and that — nothing
        # else — is what an eye is offered on
        _sync_panel_tree_eyes()

    @controller.set("compare_tree_eye")
    def compare_tree_eye(view_id, ev):
        """An eye clicked in the docked tree: in this panel or not, as in
        every panel's tree (`_eye_opens`, `_compare_hold`)."""
        ev = ev if isinstance(ev, dict) else {}
        syns = list(ev.get("paths") or ([ev["path"]] if ev.get("path") else []))
        if not syns:
            return
        # the one grammar: the eye of the Statistics tree is "in the view"
        core.panel_trees.eye("compare", str(view_id or ""), syns,
                             bool(ev["visible"]) if "visible" in ev else None)

    # --- the one grammar: the view's checkbox is the session's load ---------
    state.setdefault("compare_tick", None)

    def _held_leaves():
        """The synthetic paths whose object the session holds: its selection,
        and the recipes, which no selection holds. They may carry an eye."""
        sel = set(getattr(state, "selected_paths", None) or [])
        return [s for s, p in _compare["path_map"].items() if p in sel or derived_props.is_derived(p)]

    def _sync_compare_tree_loaded():
        """The Statistics tree's checkboxes, and the eyes they offer, in the
        view when it is open. A recipe has an eye and no box."""
        sel = set(getattr(state, "selected_paths", None) or [])
        boxes = [s for s, p in _compare["path_map"].items() if p in sel]
        able = _held_leaves()
        for vid in list(_compare["views"]):
            for var, syn in ((f"compare_tree_loaded__{vid}", boxes),
                             (f"compare_tree_eyeable__{vid}", able)):
                if set(getattr(state, var, None) or []) != set(syn):
                    state[var] = syn

    @state.change("selected_paths", "ui_compare_tree_xml")
    def _on_compare_loaded_boxes(**_):
        _sync_compare_tree_loaded()

    @state.change("compare_tick")
    def _on_compare_tick(compare_tick=None, **_):
        """A checkbox of the Statistics tree: read or unload, as anywhere —
        the synthetic paths ticked or unticked turned into the properties
        they stand for (a folder is every property under it)."""
        ev = compare_tick if isinstance(compare_tick, dict) else None
        if not ev:
            return
        vid = str(ev.get("vid") or "")
        boxes = {p for p in (ev.get("paths") or []) if p}
        before = set(getattr(state, f"compare_tree_loaded__{vid}", None) or [])
        # a folder stands for what is under it, and a recipe is nothing to read
        added = [p for p in _compare_ticked_paths(sorted(boxes - before))
                 if not derived_props.is_derived(p)]
        removed = set(_compare_ticked_paths(sorted(before - boxes)))
        sel = [p for p in (getattr(state, "selected_paths", None) or [])
               if p not in removed]
        sel += [p for p in added if p not in sel]
        _tree_tick(vid, "compare", sel)

    def _compare_vids():
        return list(_compare["views"])

    def _eye_opens(vid, paths):
        """An eye opened in the docked tree. On a part: it joins what the panel
        holds, all the rest staying. On properties: every property of their
        kinds the session holds, no property of another kind, the parts held
        staying. The properties asked for are kept for the 3D view in use
        (`_compare_hold`)."""
        held = sorted(_compare_published.get(vid) or ())
        parts = list(dict.fromkeys(p for p in held + list(paths) if _is_part(p)))
        props = [p for p in paths if not _is_part(p)]
        if not props:
            return [p for p in held if not _is_part(p)] + parts
        pmap = _compare["path_map"]
        _compare["asked"] = [pmap[p] for p in props if p in pmap]
        kind_of = lambda syn: compare_dispatch._kind_label(tree, pmap.get(syn))  # noqa: E731
        kinds = {kind_of(p) for p in props}
        same = [s for s in _held_leaves() if not _is_part(s) and kind_of(s) in kinds]
        return same + [p for p in props if p not in same] + parts

    def _eyes_follow(opened, closed):
        """The eyes of the 3D view in use follow this panel's, on the same
        objects. Several on one grid: the pass keeps the last, a grid is painted
        by one property; one in the other domain is drawn converted, as a tick
        there does."""
        vids = _compare_render_vids()
        vid = getattr(state, "fespp_last_render_panel_id", None)
        vid = vid if vid in vids else (vids[0] if vids else "")
        if not vid:
            return
        shown = core.eyes.get(vid)
        kept = [p for p in shown if p not in closed]
        fresh = [p for p in opened if p not in kept]
        if fresh or len(kept) != len(shown):
            core.eyes.set(vid, kept + fresh)
            tick = getattr(core.ctx, "view_domain_tick", None)
            if tick is not None and fresh:
                tick(vid, fresh)

    def _compare_hold(vid, paths):
        """What the panel holds, in the tree's paths: the parts have rows (an
        extract, not in those paths, is left to its own eye), the rest is the
        selection. It asks nothing: a tick's read was asked about before it
        got here, an eye reads nothing. The 3D view in use follows, the
        properties whose eye was asked for (`_eye_opens`) given last: they
        paint their grid, over those of their kind that came with them."""
        pmap = _compare["path_map"]
        before = set(_compare_published.get(vid) or ())
        asked = _compare.pop("asked", ())
        opened = [pmap[p] for p in paths if p in pmap and p not in before]
        _eyes_follow(sorted(opened, key=lambda p: p in asked),
                     [pmap[p] for p in before if p in pmap and p not in set(paths)])
        _set_compare_parts([pmap[p] for p in paths if _is_part(p) and p in pmap]
                           + [q for q in _compare_parts() if stats_supports.is_extract(q)])
        _compare_hold_properties(vid, paths)

    def _compare_moves(moved):
        """Objects replaced by a new version (`moved(path) -> path`): the rows
        on them read it, once its values are there. Whoever replaces them
        selects it next, what the session still reads of the old one; meanwhile
        it waits, as a tick's read does. A recipe stays on its grid, and says
        so when that one leaves."""
        items = _compare_items()
        sel = set(getattr(state, "selected_paths", None) or [])
        followed = [dict(it, path=moved(it["path"])) if it["path"] in sel else it for it in items]
        if followed != items:
            loaded = set(_compare_loaded_paths())
            _compare["pending"].update({now["path"]: compare_dispatch.LOADING
                                        for now, was in zip(followed, items)
                                        if now["path"] != was["path"] and now["path"] not in loaded})
            # the tree lists it from now on: what comes next holds it by its leaf
            if _compare["views"]:
                _rebuild_compare_tree(followed)
            else:
                _set_compare_items(followed)
        _set_compare_parts([moved(p) for p in _compare_parts()])

    core.panel_trees.add(
        "compare", vids=_compare_vids, opens=_eye_opens, moves=_compare_moves,
        held=lambda vid: sorted(_compare_published.get(vid) or ()),
        hold=_compare_hold,
        to_real=_compare_ticked_paths,
        from_real=lambda real: [s for s, p in _compare["path_map"].items()
                                if p in set(real)],
        title=lambda vid: (core.mv().title_of(vid) if core.mv() is not None
                           else "Statistics"))

    @controller.set("compare_tree_layout")
    def compare_tree_layout(mode):
        """The docked tree's layout: by kind the server builds it, else the widget
        groups the representations it is given."""
        state.ui_compare_tree_layout = str(mode or "") or "kind"
        _rebuild_compare_tree()

    @controller.set("compare_tree_action")
    def compare_tree_action(view_id, ev):
        """The right-click menu of the docked tree: the baseline, and what the
        file knows about the object, which needs nothing read. The widget's
        `when` offers the baseline on what the panel holds."""
        ev = ev if isinstance(ev, dict) else {}
        action = ev.get("action")
        real = _compare["path_map"].get(ev.get("path"))
        if not action or not real:
            return
        if action == "compare-health":
            controller.health_focus(real)
        elif action == "compare-baseline":
            _compare_tree_baseline(real)

    def _compare_tree_baseline(real):
        """"Set as baseline" on a property the panel holds; on the baseline
        itself, back to plain statistics."""
        hit = next((it for it in _compare_items() if it.get("path") == real), None)
        if hit is None:
            _compare_note(
                f"{_compare_names([real])} is no longer in the statistics,"
                " so there is nothing to act on. Tick it again to put it"
                " back.")
            return
        # the tree names any kind: its tab shows what the gesture did
        own = compare_dispatch._kind_label(tree, real)
        state.ui_compare_tab = own
        uid = hit.get("uid") or _compare_item_key(hit)
        compare_set("baseline", "" if _kind_state(own)["baseline"] == uid else uid)

    def _compare_dist_opts_set(kind, name, value):
        """One histogram option of one kind's tab; True when it changed."""
        opts = dict(_COMPARE_DIST_OPTS, **_kind_state(kind)["dist_opts"])
        if name == "nbins":
            try:
                opts["nbins"] = max(2, min(500, int(value)))
            except (TypeError, ValueError):
                return False
        elif name in ("log_y", "cumulative"):
            opts[name] = bool(value)
        elif name == "mode" and value in ("bars", "line", "curve"):
            opts["mode"] = value
        elif name == "norm" and value in ("count", "density", "probability"):
            opts["norm"] = value
        else:
            return False
        _kind_state(kind)["dist_opts"] = opts
        return True

    def _following_row(ref):
        """The row of the matrix `ref` names when it follows an item, else None."""
        row = (getattr(state, "ui_compare_rows", None) or {}).get(str(ref or ""))
        return row if row and row.get("support") else None

    def _on_following_row(key, value):
        """A gesture naming a row that follows an item: `remove` closes a
        part's eye, all its rows going; the others are refused, said. False
        when the gesture is not about such a row."""
        if key not in _REFUSED_ON_FOLLOWING:
            return False
        ref = value[0] if isinstance(value, (list, tuple)) and value else value
        row = _following_row(ref)
        if row is None:
            return False
        if key == "remove" and not compare_rows.is_view_row(row):
            _set_compare_parts([p for p in _compare_parts() if p != row["support"]])
        else:
            _compare_note(f"{row.get('label') or ref}: {_REFUSED_ON_FOLLOWING[key]}.")
        return True

    def _axis_options(path):
        """What a property can be read at; nothing when that cannot be said."""
        try:
            return crossplot_dispatch.axis_options(state, tree, path)
        except Exception as exc:
            print(f"[fespp] compare axes of {path!r}:", exc, flush=True)
            return {"reals": [], "ts": []}

    def _pinned_at(items, path):
        """The coordinates a property has a pinned row at."""
        return {(it["real"], it["ts"]) for it in items if it["path"] == path and it.get("pinned")}

    @controller.set("compare_set")
    def compare_set(key, value):
        """One entry point for the Statistics widget: the widget names the
        control, the server writes the var or edits the selection, and
        recomputes what the active tab shows. A pure display key (metric
        visibility) writes and stops there. The docked tree is
        opened by the panel's own header button, as in every other panel —
        the widget has no say in it, and no `view_id` to send."""
        if _on_following_row(key, value):
            return
        items = _compare_items()
        kind = _compare_current_kind()
        if key == "tab":
            labels = [k["kind"] for k in
                      (getattr(state, "ui_compare_kinds", None) or [])]
            state.ui_compare_tab = (
                value if value in labels else (labels[0] if labels else ""))
        elif key == "xplot_axis":
            which, uid = (list(value) + [None, None])[:2] if isinstance(
                value, (list, tuple)) else (None, None)
            _compare_set_axis(which, uid)
            return
        elif key == "baseline":
            # the baseline is an ITEM (its uid): it follows the row, whatever
            # realization or time step it is moved to; it is its own kind's,
            # whichever tab is shown
            idx = _compare_index(items, value)
            if idx is not None:
                own = compare_dispatch._kind_label(tree, items[idx]["path"])
                _kind_state(own)["baseline"] = items[idx].get("uid") or ""
            elif kind:
                _kind_state(kind)["baseline"] = ""
        elif key in ("remove", "unpin"):
            idx = _compare_index(items, value)
            if idx is None:
                return
            # ONE row, not every item of that property: a pinned copy and
            # its source share an item key until the source moves on
            _set_compare_items(items[:idx] + items[idx + 1:])
            return
        elif key == "pin":
            # a row's pin: a copy of the row as it is read
            # now, its realization and time step fixed; the source row
            # keeps its pickers and moves on
            idx = _compare_index(items, value)
            if idx is None:
                return
            src = items[idx]
            opts = _axis_options(src["path"])
            if not (opts.get("reals") or opts.get("ts")):
                _compare_note(f"{_compare_names([src['path']])} has neither realization"
                              " nor time step: nothing to pin a copy at.")
                return
            if (src["real"], src["ts"]) in _pinned_at(items, src["path"]):
                _compare_note(f"{_compare_names([src['path']])} has a pinned row at this"
                              " realization and time step already.")
                return
            _set_compare_items(items + [{"path": src["path"],
                                         "real": src["real"], "ts": src["ts"],
                                         "pinned": True}])
            return
        elif key == "pin_all":
            # one pinned copy per time step (or per realization) of the
            # item's property, at the item's other coordinate — a row's
            # "Pin all Time Steps"
            k, axis = (list(value) + [None, None])[:2] if isinstance(
                value, (list, tuple)) else (None, None)
            idx = _compare_index(items, k)
            if idx is None or axis not in ("ts", "real"):
                return
            src = items[idx]
            opts = _axis_options(src["path"])
            values = [o.get("value") for o in
                      (opts.get("ts" if axis == "ts" else "reals") or [])]
            values = [int(v) for v in values if v is not None]
            if not values:
                _compare_note(f"{_compare_names([src['path']])} has no"
                              f" {'time step' if axis == 'ts' else 'realization'}"
                              " to pin one row per.")
                return
            have = _pinned_at(items, src["path"])
            fresh = []
            for v in values:
                coord = ((src["real"], v) if axis == "ts" else (v, src["ts"]))
                if coord in have:
                    continue
                fresh.append({"path": src["path"], "real": coord[0],
                              "ts": coord[1], "pinned": True})
            if not fresh:
                _compare_note(f"{_compare_names([src['path']])}: every"
                              f" {'time step' if axis == 'ts' else 'realization'}"
                              " is already pinned.")
                return
            _set_compare_items(items + fresh)
            return
        elif key == "unpin_all":
            # every pinned copy of the item's property goes; the sources stay
            idx = _compare_index(items, value)
            if idx is None:
                return
            path = items[idx]["path"]
            kept = [it for it in items
                    if not (it["path"] == path and it.get("pinned"))]
            if len(kept) == len(items):
                _compare_note(f"{_compare_names([path])} has no pinned row.")
                return
            _set_compare_items(kept)
            return
        elif key in ("real", "ts"):
            k, v = (list(value) + [None, None])[:2] if isinstance(
                value, (list, tuple)) else (None, None)
            idx = _compare_index(items, k)
            if idx is None:
                return
            items[idx][key] = int(v) if v is not None else None
            _set_compare_items(items)
            return
        elif key == "visible_metrics":
            if not kind:
                return
            want = set(value or [])
            _kind_state(kind)["visible_metrics"] = [
                m for m in compare_matrix._METRIC_KEYS if m in want]
            _project_kind_state()
            return
        elif key == "sort":
            if not kind:
                return
            sk, asc = (list(value) + ["", True])[:2] if isinstance(
                value, (list, tuple)) else ("", True)
            st = _kind_state(kind)
            st["sort_key"] = sk if sk in compare_matrix.SORT_KEYS else ""
            st["sort_asc"] = bool(asc)
            _project_kind_state()
            _compare_resort()
            return
        elif key == "dist_opt":
            if not kind or not isinstance(value, (list, tuple)) or len(value) != 2:
                return
            if not _compare_dist_opts_set(kind, value[0], value[1]):
                return
        elif key == "note":
            # the reader closed the note band
            state.ui_compare_note = ""
            return
        else:
            return
        _refresh_compare()
    return (_compare_add, _sync_compare_tree_eyes, _sync_panel_tree_eyes)
