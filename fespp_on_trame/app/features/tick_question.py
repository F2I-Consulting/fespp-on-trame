"""one question before a tick reads a lot
ONE click in ANY tree can stand for dozens of reads (a folder stands
for its whole subtree), and in the data tree every property read
pulls its representation into the 3D view. Above
`tick_confirm.MAX_TICK_LOAD` unread properties the tick states its
size and waits: `ui_tick_confirm` is what the shared fp-scrim /
fp-dialog box in the application layout renders, and the two answers
are kept here because replaying a tick is the server's memory of what
to do, not something the page holds.

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import repo_query
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine import tick_confirm


def register(core, *, _expand_blocked_well_trajectories, _is_object_path,
             _is_property_path, _panel_reads, _prev_selected, _say,
             _set_selectors):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_apply_selection, _ask, _ask_tick, _drop_tick_question, _tree_tick)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    panel_trees = core.panel_trees
    _mv = core.mv
    from fespp_on_trame.app.views import per_view_state

    # the 3D views, for the one grammar (app/scene/panel_trees): who shows an
    # object an untick is about to unload
    def _render_users(paths):
        mv = _mv()
        if mv is None:
            return []
        return [v for v in mv.view_ids()
                if per_view_state.is_live(v)
                and set(getattr(state, f"visible_paths__{v}", None) or []) & paths]

    panel_trees.add_views(_render_users)
    # --- one question before a tick reads a lot ---------------------------
    # ONE click in ANY tree can stand for dozens of reads (a folder stands
    # for its whole subtree), and in the data tree every property read
    # pulls its representation into the 3D view. Above
    # `tick_confirm.MAX_TICK_LOAD` unread properties the tick states its
    # size and waits: `ui_tick_confirm` is what the shared fp-scrim /
    # fp-dialog box in the application layout renders, and the two answers
    # are kept here because replaying a tick is the server's memory of what
    # to do, not something the page holds.
    _tick_ask = {"yes": None, "no": None, "third": None}
    # What a server-side decision has already committed to reading, such as
    # a step of the headless harness. The question guards a click; asking again
    # about a read the server has just been told to do would be a loop, so
    # those paths go through `controller.select_paths` and are not counted.
    _decided_paths = set()

    _frame_nodes = {}   # frame uuid -> its nodes, as its XML says (0: it does not)

    def _log_values(paths):
        """(values, logs weighed): the values of the well logs among `paths`,
        each as many as its frame has nodes, the frames' XML read in one
        round trip and kept; a log whose frame says no count is left out."""
        logs = {p: node_facts.rep_path_for(tree, p) for p in paths if node_facts.is_log(tree, p)}
        uuid_of = {frame: frame.rsplit("/", 1)[-1].lstrip("_") for frame in set(logs.values())}
        missing = [u for u in uuid_of.values() if u not in _frame_nodes]
        if missing:
            try:
                texts = repo_query.object_xml(core.active_data_source.get_source(), missing)
            except Exception as exc:
                print(f"[fespp] tick question: the frames' sizes not read ({exc!r})", flush=True)
                texts = [""] * len(missing)
            _frame_nodes.update((u, tick_confirm.node_count(t)) for u, t in zip(missing, texts))
        weighed = [p for p, frame in logs.items() if _frame_nodes.get(uuid_of[frame])]
        values = sum(_frame_nodes[uuid_of[logs[p]]] for p in weighed)
        if logs:
            print(f"[fespp] journal read size: {len(logs)} log(s), {len(weighed)} weighed,"
                  f" {values} value(s); frames {[(u[:8], _frame_nodes.get(u)) for u in uuid_of.values()]}",
                  flush=True)
        return values, weighed

    def _ask_tick(count, on_yes, on_no, shown=True, remote=False, objects=False, values=0):
        """Ask, unless one question is already standing.

        There is one box and one pair of answers: a second question posed
        before the first is answered would overwrite them, and the reader's
        click would then run the wrong tick's callbacks. The standing
        question keeps the box; the newcomer steps back at once, its own
        `on_no` putting its checkboxes and its panel visibly back where they
        were, exactly as a cancel does. `shown` is where the read would land
        (the 3D view for the data tree, the panel alone for a panel's tree)
        and the box says which."""
        _ask(tick_confirm.question(count, shown=shown, remote=remote, objects=objects, values=values),
             on_yes, on_no)

    def _ask(question, on_yes, on_no, on_third=None):
        """Pose `question` ({title, body, ok, cancel?, third?}) in the one
        box, unless one is already standing (see `_ask_tick`); `on_third`
        answers the third button, when the question offers one."""
        if any(v is not None for v in _tick_ask.values()):
            print(f"[fespp] journal question: {question.get('title')!r} not asked,"
                  f" {(state.ui_tick_confirm or {}).get('title')!r} stands", flush=True)
            if on_no is not None:
                on_no()
            return
        _tick_ask["yes"], _tick_ask["no"], _tick_ask["third"] = on_yes, on_no, on_third
        state.ui_tick_confirm = question

    def _drop_tick_question():
        """The question lost its subject (its panel closed, another file was
        read): it goes, and neither answer runs."""
        if all(v is None for v in _tick_ask.values()):
            return
        _tick_ask.update(yes=None, no=None, third=None)
        state.ui_tick_confirm = {}

    @controller.set("tick_confirm_answer")
    def tick_confirm_answer(go):
        """The answer to that question: on a yes the very same tick runs
        with no cap, on a no the boxes go back to what they were, and
        nothing is said: the reader has just decided it."""
        act = _tick_ask["third"] if go == "third" else _tick_ask["yes"] if go else _tick_ask["no"]
        print(f"[fespp] journal question: {(state.ui_tick_confirm or {}).get('title')!r} answered {go!r}", flush=True)
        _tick_ask.update(yes=None, no=None, third=None)
        state.ui_tick_confirm = {}
        if act is not None:
            act()

    @controller.set("select_paths")
    def select_paths(paths):
        """Load these paths without asking, born visible, as a tick in the
        data tree would.

        The read has already been decided (a step of the headless harness,
        for instance), and the question (UI rule R7) guards a gesture, not a
        decision the server has already taken. A panel's read goes through
        `_apply_selection(..., shown=False)` instead."""
        want = [p for p in (paths or ()) if p]
        _decided_paths.update(want)
        # written as it will stand, its cascades run: a list written and then
        # replaced by its expansion is two messages to the browser, and one
        # that applies them the wrong way round keeps the first — a row
        # ticked without what it holds
        state.selected_paths = _effective(want)[0]
        # trame drops a write equal to the value it has already pushed, and
        # a caller asking for a read it has already decided must still see
        # the pipeline run.
        state.dirty("selected_paths")

    def _restore_selection(paths):
        """Stepping back from the question: the boxes go visibly back to
        what they were. The write is unconditional: the widget is still
        holding the tick that asked, so an unchanged effective selection is
        not an unchanged set of checkboxes."""
        paths = list(paths or [])
        # written only when it moved: a tick from a tree (`tree_tick`) never
        # wrote it, and rewriting the same list re-ran every watcher of the
        # selection — a full pass of the load for nothing. The trees read it
        # again (`tree_boxes_n`), the click that asked included.
        if list(getattr(state, "selected_paths", None) or []) != paths:
            state.selected_paths = paths
        _boxes_again()

    # Every tree's checkbox (the data tree and the panels' trees) sends ONE
    # event, {vid, kind, paths, t}: the whole set of boxes after the click,
    # and where it was made. `t` makes the same click after a refused one a
    # new value.
    state.setdefault("tree_tick", None)
    state.setdefault("tree_boxes_n", 0)

    def _boxes_again():
        """Every tree reads the selection again: the server owns the boxes,
        and the list it publishes may be the very one it already sent (a
        refused or vetoed tick)."""
        state.tree_boxes_n = int(getattr(state, "tree_boxes_n", 0) or 0) + 1

    @state.change("tree_tick")
    def _on_tree_tick(tree_tick=None, **_):
        ev = tree_tick if isinstance(tree_tick, dict) else None
        if not ev:
            return
        _tree_tick(str(ev.get("vid") or ""), str(ev.get("kind") or "render"),
                   [p for p in (ev.get("paths") or []) if p])

    def _tree_tick(vid, kind, paths):
        """A tick in the tree of view `vid`, of kind `kind` ("render" for a
        3D view's data tree): the checkbox is the session's load, the same in
        every tree. What a 3D view's tick reads is born visible there; what
        a panel's tick reads goes in THAT panel — the 3D view in use follows
        the Statistics view's eyes (app/features/compare_tree), no other
        panel's."""
        before = set(_prev_selected["paths"])
        added = [p for p in paths if p not in before]
        if kind == "render":
            if added:
                core.activation.ticked(vid, added)
            _apply_selection(paths, push=True, origin=vid)
            # an object ticked in the other vertical domain than the view's
            # (app/features/view_domain; the PO, 28/10)
            # and what it shows, the Statistics view's eyes show too
            def _told():
                for hook, args in ((getattr(core.ctx, "view_domain_tick", None), (vid, added)),
                                   (getattr(core.ctx, "stats_follow_eyes", None), (added, ()))):
                    if hook is not None:
                        hook(*args)

            if added:
                yes = _tick_ask["yes"]
                if yes is not None:
                    # the read waits for the box's answer: told after a yes,
                    # or the domain question would find the box taken
                    def _read_then_told():
                        yes()
                        _told()
                    _tick_ask["yes"] = _read_then_told
                else:
                    _told()
            return
        # taken in once the selection is written (`after`): the panel's own
        # setter then finds it read and asks for nothing
        _apply_selection(paths, push=True, shown=False, origin=vid,
                         after=lambda: panel_trees.take(kind, vid, added))

    def _titles_of(paths):
        """The titles of the topmost of `paths` (an unticked folder, not
        every leaf under it)."""
        tops = [p for p in paths
                if not any(p != q and p.startswith(q + "/") for q in paths)]
        out = []
        for p in tops:
            nid = tree.find_node_id(p)
            out.append((tree.find_title(nid) if nid is not None else "") or p.rsplit("/", 1)[-1])
        return out

    def _view_title(vid):
        mv = _mv()
        kind = panel_trees.kind_of(vid)
        if kind is not None:
            return panel_trees.title(kind, vid)
        return mv.title_of(vid) if mv is not None else str(vid)

    @state.change("selected_paths")
    def _on_selected(selected_paths=None, **_):
        _apply_selection(list(selected_paths or []))

    def _effective(curr_paths):
        """(`curr_paths` as the selection stands once its rules ran, {the
        trajectory a blocked wellbore pulled back: that wellbore's title}).
        The rules, applied on node ids against the selection before: grouping
        cascade, frame-element -> trajectory pull, property -> rep,
        rep/grouping removal cascade, geometry-sibling drop (SolidColor
        layout), empty-shell GC, trajectory veto and threshold guard (each
        says so in the snackbar), strict no-op on full veto; then the
        cross-tab rule: a checked blocked wellbore checks its referenced
        trajectory, so the well tab's checkbox reflects it, not only the data
        selectors."""
        from fespp_on_trame.app.ui.selection_deps import _expand_selection_with_deps
        curr_ids = [i for i in (tree.find_node_id(p) for p in curr_paths) if i is not None]
        prev_ids = [i for i in (tree.find_node_id(p) for p in _prev_selected["paths"]) if i is not None]
        eff_ids = _expand_selection_with_deps(curr_ids, prev_ids, tree)
        return _expand_blocked_well_trajectories([p for p in (tree.find_path(i) for i in eff_ids) if p])

    def _apply_selection(curr_paths, ask=True, on_no=None, push=False,
                         on_go=None, shown=True, origin=None, confirmed=False,
                         after=None):
        """Apply a selection, and keep `selected_paths` saying what it is.

        `on_go` is what a panel puts the ticked object in itself with: it
        runs when the read actually goes ahead (at once under the cap, from
        the answer above it), so a panel is never filled behind a box that
        is still asking, and `on_no` has nothing to undo.

        `push` is set by a gesture made outside that variable: a tick in a
        panel's tree, which calls this directly. Without it the write below
        is skipped whenever the expansion adds nothing, and the session's
        selection stays behind the baseline this call advances: the next
        tick in the data tree would send a list with none of those paths in
        it, the delta logic would read them as newly unticked, and unload
        them. The invariant after every call is
        `state.selected_paths == _prev_selected["paths"]`.

        `shown=False` is a panel's read: what this call adds to the
        selection (the properties named and the representations the cascade
        pulls in) is born with a closed eye (`_panel_reads`), read into the
        panel and shown in no 3D view until an eye is clicked.

        `origin` is the view whose tree the gesture came from (`tree_tick`;
        None for a decision of the server: the harness, a restored session).
        An untick from a tree of what a feature keeps read
        (`ctx.untick_vetoes`: [(paths before, paths after) -> (the rows to
        tick again, why)] — the velocity model the conversions read) is put
        back and says why; a decision of the server passes.
        An untick from a tree that would unload what ANOTHER view is using —
        a 3D view showing it, a panel holding it — asks first and names
        those views (the PO, 18/10); `confirmed` is the yes coming back.
        What leaves the selection leaves every panel (`panel_trees.prune`).
        `after` runs once the selection is written (a panel taking in what
        its tick read)."""
        try:
            curr_paths = list(curr_paths or [])
            prev_paths = list(_prev_selected["paths"])
            eff_paths, pulled = _effective(curr_paths)
            for veto in (getattr(core.ctx, "untick_vetoes", None) or ()) if origin is not None else ():
                back, why = veto(prev_paths, eff_paths)
                if back:
                    curr_paths = curr_paths + [p for p in back if p not in curr_paths]
                    eff_paths, pulled = _effective(curr_paths)
                    _say(why)
            # A trajectory the user just unchecked and the blocked well
            # pulled straight back: the checkbox re-ticks, so say why.
            for traj_path, bw_title in pulled.items():
                if traj_path in prev_paths and traj_path not in curr_paths:
                    nid = tree.find_node_id(traj_path)
                    name = (tree.find_title(nid) if nid is not None else "") \
                        or "The trajectory"
                    _say(
                        f"{name} stays checked: blocked wellbore {bw_title}"
                        " still needs it. Uncheck the blocked wellbore"
                        " first, or close the eye on the trajectory to"
                        " hide it.")
            # a row of the store asked for while the store is closed (the
            # reader disconnected, its token ended, its session was lost): not
            # read, and said — what is shown stays
            added = [p for p in eff_paths if p not in set(prev_paths)]
            closed = getattr(core.ctx, "store_closed", None)
            if added and closed is not None and core.active_data_source.store_paths(added):
                why = closed()
                if why:
                    _decided_paths.difference_update(eff_paths)
                    _restore_selection(prev_paths)
                    _say(why)
                    if on_no is not None:
                        on_no()
                    return
            gone = [p for p in prev_paths if p not in set(eff_paths)]
            if gone and origin is not None and not confirmed:
                users = panel_trees.users(gone, exclude=origin)
                if users:
                    unticked = [p for p in prev_paths if p not in set(curr_paths)] or gone

                    def _no_unload():
                        _restore_selection(prev_paths)
                        if on_no is not None:
                            on_no()
                    _ask(tick_confirm.unload_question(
                            _titles_of(unticked), [_view_title(v) for v in users]),
                         lambda: _apply_selection(curr_paths, ask=ask, on_no=on_no,
                                                  push=push, on_go=on_go, shown=shown,
                                                  origin=origin, confirmed=True,
                                                  after=after),
                         _no_unload)
                    return
            if ask:
                # What this gesture would read: the properties it adds that
                # no one has asked for yet. Nothing is read while the
                # question stands (`fespp_data_selectors` is the only
                # channel that loads and it is not written) and the boxes
                # stay as the user left them; stepping back writes the
                # previous selection, so the ticks come off where they went
                # on, in sight.
                before = set(prev_paths)
                # From an ETP / OSDU server every object is a download: a
                # "select all" of surfaces holds no property yet reads for
                # minutes. There the objects are counted, folders aside;
                # from a file, the properties, and in a panel's tree the parts
                # of a grid, each of which its rows map onto the grid's cells.
                # Which it is goes by the row's own reader: a session
                # reads a store and files together.
                far = core.active_data_source.store_paths(eff_paths)
                parts = [] if shown else [
                    p for p in eff_paths if p not in far and stats_supports.is_support(tree, p)]
                fresh = [p for p in eff_paths
                         if p not in before and p not in _decided_paths
                         and (_is_object_path(p) if p in far
                              else _is_property_path(p) or p in parts)]
                remote = any(p in far for p in fresh)
                # the logs of a file weighed by their values (their frames'
                # nodes); a log whose frame does not say counts as a property
                values, weighed = _log_values([p for p in fresh if p not in far])
                if tick_confirm.asks(len(fresh) - len(weighed), values):
                    def _no():
                        _restore_selection(prev_paths)
                        # a tick made in a panel: the panel itself was never
                        # filled (that is `on_go`'s job, and it has not run),
                        # so this only puts the tree's own checkboxes back
                        if on_no is not None:
                            on_no()
                    _ask_tick(
                        len(fresh),
                        lambda: _apply_selection(curr_paths, ask=False,
                                                 on_no=on_no, push=push,
                                                 on_go=on_go, shown=shown,
                                                 origin=origin, confirmed=True,
                                                 after=after),
                        _no, shown=shown, remote=remote,
                        objects=any(p in parts for p in fresh), values=values)
                    return
            if on_go is not None:
                on_go()
            # a read the server decided (the harness, a restored session,
            # the assistant) is waited for by its caller: it goes in one
            # step; a gesture's big read goes step by step
            decided = any(p in _decided_paths for p in eff_paths)
            _decided_paths.difference_update(eff_paths)
            if not shown:
                _panel_reads.update(p for p in eff_paths
                                    if p not in set(prev_paths))
            # a path that leaves the selection leaves the set: ticked again
            # in the data tree, it is shown as any data-tree tick is
            _panel_reads.intersection_update(eff_paths)
            _prev_selected["paths"] = eff_paths
            if push or set(eff_paths) != set(curr_paths):
                # Reflect cascades/vetoes back into the widget's checkboxes,
                # and publish the whole selection when the gesture did not
                # come through this variable in the first place.
                # Re-entrant but convergent: the next round expands to the
                # same effective set, pushes nothing and skips this write.
                state.selected_paths = eff_paths
                if push:
                    # the trees read the selection again (`tree_boxes_n`):
                    # a list equal to the one trame already holds is not
                    # re-sent, and marking it dirty re-ran every watcher of
                    # the selection for nothing
                    _boxes_again()
            # a panel's read (`shown` False) and a caller with a follow-up
            # (`after`) need the read done when this returns: no veil turn
            _set_selectors(eff_paths, stepped=not decided,
                           veil=shown and after is None and on_go is None)
            if gone:
                # unloaded: it leaves every panel holding it (its eye there
                # closes with it), and the 3D views' active nodes
                panel_trees.prune(gone)
                core.activation.unloaded(gone)
            if after is not None:
                after()
        except Exception as exc:
            print("[fespp] selected_paths error:", exc, flush=True)
    return (_apply_selection, _ask, _ask_tick, _drop_tick_question, _tree_tick)
