"""the Statistics view, `compare` in the code (engine/compare_dispatch)
ONE selection (state ui_compare_items) for the singleton view, expanded at each
refresh into the rows of the matrix (engine/compare_rows); `views`
= the open view ids (one at most — a reopened view gets a fresh id, so
a closed one never matches again), `path_map` = the docked tree's
synthetic paths -> real paths of the properties and parts of the current tree xml.
`pending` = the properties a tick in the docked tree asked the session
to load, path -> "loading" until the values arrive, "failed" once a load
cycle has run without bringing them in.
`confirm`: the tick waiting for an answer — {vid, ticked} — kept here
and not in state, because it is the SERVER's memory of what to replay,
not something the panel renders."""
import time
from fespp_on_trame.engine import compare_matrix
from fespp_on_trame.engine import crossplot_dispatch
from fespp_on_trame.engine import compare_dispatch
from fespp_on_trame.engine import compare_rows
from fespp_on_trame.engine import compare_tree
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine.vtk_log import capture_vtk_messages


def register(core, *, _apply_selection, _defer, _drop_crossplot,
             _drop_crossplot_figures, _drop_tick_question, _property_label,
             _refresh_crossplot, _register_crossplot, _sync_compare_tree_eyes):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_close_compare_view, _compare, _compare_current_kind, _compare_index, _compare_item_key, _compare_items, _compare_loaded_paths, _compare_names, _compare_note, _compare_parts, _compare_published, _compare_request_load, _compare_resort, _compare_set_axis, _compare_tick_note, _compare_uid, _kind_state, _project_kind_state, _rebuild_compare_tree, _refresh_compare, _refresh_compare_now, _refresh_compare_rows, _set_compare_items, _set_compare_parts, _sync_compare_tree_selection, open_compare)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    source_registry = core.source_registry
    _derived_store = core.derived_store
    _mv = core.mv
    from fespp_on_trame.app.boot import _COMPARE_DIST_OPTS, _COMPARE_PAYLOAD
    # `extract_folders` = the folders of the tree xml the rows of the extracts
    # hang under.
    _compare = {"views": [], "path_map": {}, "extract_folders": set(), "uid": 0,
                "pending": {}, "confirm": None, "unread_said": set(),
                # what the 3D views' rows read, as they last read it
                "cuts": {},
                # kind label -> its own state, kept for the session even
                # while no item of the kind is selected (it comes back with
                # the item)
                "kinds": {}}

    def _kind_state(kind):
        """The state of one kind tab: its baseline, sort, metrics,
        distribution options and cross-plot axes (the rows' uids). Created on
        first sight."""
        st = _compare["kinds"].get(kind)
        if st is None:
            st = {"baseline": "", "sort_key": "", "sort_asc": True,
                  "visible_metrics": list(compare_matrix._METRIC_KEYS),
                  "xplot_x": "", "xplot_y": "",
                  "dist_opts": dict(_COMPARE_DIST_OPTS)}
            _compare["kinds"][kind] = st
        return st

    def _compare_kinds(chips):
        """[{kind, count}] in first-appearance order — the tabs."""
        kinds = []
        for c in chips:
            k = c.get("kind") or compare_dispatch.NO_KIND
            hit = next((d for d in kinds if d["kind"] == k), None)
            if hit is None:
                kinds.append({"kind": k, "count": 1})
            else:
                hit["count"] += 1
        return kinds

    def _compare_current_kind():
        return getattr(state, "ui_compare_tab", "") or ""

    def _project_kind_state():
        """The current kind's state into the flat vars the widget reads."""
        kind = _compare_current_kind()
        if not kind:
            return
        st = _kind_state(kind)
        state.ui_compare_baseline = st["baseline"]
        state.ui_compare_sort_key = st["sort_key"]
        state.ui_compare_sort_asc = st["sort_asc"]
        state.ui_compare_visible_metrics = list(st["visible_metrics"])
        state.ui_compare_dist_opts = dict(st["dist_opts"])

    def _kind_items(items, chips, kind):
        """The items of one kind, with their chips matched by position, by
        key should the two lists ever disagree in length."""
        if len(chips) == len(items):
            pairs = list(zip(items, chips))
        else:
            by_key = {c.get("key"): c for c in chips}
            pairs = [(it, by_key.get(_compare_item_key(it)) or {})
                     for it in items]
        return [it for it, c in pairs
                if (c.get("kind") or compare_dispatch.NO_KIND) == kind]
    # What the server last PUBLISHED as each Statistics tree's ticks
    # (`_sync_compare_tree_selection`). The tree is two-way, so the rewrite
    # comes back through its own watcher; this record lets the watcher tell
    # that echo from a gesture (read as a gesture, it would replay the tick,
    # re-derive `pending` from what is already in and swallow the arrival
    # note). Same guard as `_welllog_published`.
    _compare_published = {}

    def _compare_item_key(it):
        return compare_dispatch.item_key(it.get("path"), it.get("real"),
                                         it.get("ts"))

    def _compare_uid():
        """A stable identity per selection entry: two items of the same
        property at the same realization and time share an item key, so the
        key alone cannot say which row a gesture came from."""
        _compare["uid"] += 1
        return f"i{_compare['uid']}"

    def _compare_items():
        """The selection, normalised: a client-edited real / ts may arrive
        as a float or a string. `pinned` marks a copy the reader pinned
        beside its source (its realization / time step are fixed)."""
        out = []
        for it in (getattr(state, "ui_compare_items", None) or []):
            if not isinstance(it, dict) or not it.get("path"):
                continue
            real, ts = it.get("real"), it.get("ts")
            out.append({"path": it["path"],
                        "real": int(real) if real is not None else None,
                        "ts": int(ts) if ts is not None else None,
                        "uid": str(it.get("uid") or ""),
                        "pinned": bool(it.get("pinned"))})
        return out

    def _compare_index(items, ref):
        """The item a widget event names: its uid, else the FIRST item
        carrying that item key (a client that sends no uid, such as the test
        harness, names an item by its key)."""
        ref = str(ref or "")
        if not ref:
            return None
        for i, it in enumerate(items):
            if it.get("uid") and it["uid"] == ref:
                return i
        for i, it in enumerate(items):
            if _compare_item_key(it) == ref:
                return i
        return None

    def _compare_loaded_paths():
        return (list(getattr(state, "ui_loaded_array_paths", None) or [])
                + _derived_store.active_paths())

    def _compare_parts():
        """The parts of a grid whose eye is open: their rows follow the items
        of their grid."""
        return list(getattr(state, "ui_compare_parts", None) or [])

    def _set_compare_parts(parts):
        """The rows follow through the watcher of `ui_compare_parts`
        (app/features/compare_parts), the eyes of the tree at once."""
        parts = list(dict.fromkeys(parts))
        if parts != _compare_parts():
            state.ui_compare_parts = parts
        _sync_compare_tree_selection()

    def _matrix_rows(items):
        """The rows of the matrix over `items`: each item, and the rows that
        follow it."""
        return compare_rows.with_following(state, tree, items, _compare_parts())

    def _compare_listed_paths(recipes=()):
        """What the docked tree LISTS: every property the file holds — the
        assembly names its kind, its rep and its title without a value being
        read — plus the derived recipes, which live in the store and not in
        the assembly: the active ones and `recipes`, those the selection
        holds whatever became of their grid. Listing is free; reading is what
        needs a load. A velocity model the session generated is not listed here,
        read or not (`ui_model_tree_rows`)."""
        hidden = list(getattr(state, "ui_model_tree_rows", None) or [])
        listed = [p for p in compare_tree.assembly_property_paths(tree) if not node_facts.is_under(p, hidden)]
        seen = set(listed)
        loaded = [p for p in _compare_loaded_paths() if not node_facts.is_under(p, hidden)]
        for path in [*loaded, *recipes]:
            if path not in seen:
                listed.append(path)
                seen.add(path)
        return listed

    def _compare_listed_parts():
        """The parts of a grid it lists: the file's, read or not, and the 3D
        views' extracts."""
        hidden = list(getattr(state, "ui_model_tree_rows", None) or [])
        return ([p for p in stats_supports.assembly_parts(tree) if not node_facts.is_under(p, hidden)]
                + stats_supports.session_extracts())

    def _sync_compare_tree_selection():
        """The docked tree's eyes follow the selection, in every open view: the
        synthetic paths whose real path still has an item, or is a part with
        its rows. The leaves are the whole truth — a ticked folder the widget
        sent is written away here, its leaves carrying the tick instead."""
        if _compare["confirm"]:
            # A tick is waiting for an answer: its boxes must stay as the
            # user left them, or the question would be about a selection
            # the screen no longer shows.
            return
        pmap = _compare["path_map"]
        have = {it["path"] for it in _compare_items()} | set(_compare_parts())
        syn = [s for s, p in pmap.items() if p in have]
        for vid in list(_compare["views"]):
            var = f"compare_tree_selected__{vid}"
            cur = list(getattr(state, var, None) or [])
            _compare_published[vid] = set(syn)
            if set(cur) != set(syn):
                state[var] = syn

    def _set_compare_items(items):
        items = [dict(it) for it in items]
        for it in items:
            if not it.get("uid"):
                it["uid"] = _compare_uid()
        if items != list(getattr(state, "ui_compare_items", None) or []):
            state.ui_compare_items = items
        _sync_compare_tree_selection()
        _refresh_compare()

    def _compare_set_axis(which, uid):
        """X or Y of the tab's cross-plot picked, or the two swapped: that chart
        alone is drawn again."""
        kind = _compare_current_kind()
        if not kind or which not in ("x", "y", "swap"):
            return
        st = _kind_state(kind)
        if which == "swap":
            axes = getattr(state, "ui_compare_xplot_axes", None) or {}
            st["xplot_x"], st["xplot_y"] = axes.get("y") or "", axes.get("x") or ""
        else:
            st["xplot_" + which] = str(uid or "")
        chips = list(getattr(state, "ui_compare_chips", None) or [])
        _compare_tab_xplot(kind, _kind_items(_compare_items(), chips, kind))

    def _cuts_read():
        """What the 3D views' rows of the selection read now, whichever tab
        they are in (engine/compare_rows.cuts_read)."""
        return compare_rows.cuts_read(state, tree, _compare_items(),
                                      getattr(core.ctx, "grid_isolates", None) or {},
                                      getattr(core.ctx, "blockscope_scenes", None) or {})

    def _compare_tab_stats(kind, items):
        """The matrix of ONE kind: its items and the rows that follow them,
        its baseline, its sort. The value reads of the items come from the
        session's row cache (compare_dispatch.READS): a row read once is not
        read again while its values cannot have changed — re-reading every
        pinned time step at each tick would cost minutes of pipeline runs for
        a matrix that has not moved."""
        st = _kind_state(kind)
        items = _matrix_rows(items)
        t0 = time.monotonic()
        blocks, rows, ann = compare_dispatch.matrix(
            state, tree, source_registry, items, st["baseline"],
            st["sort_key"], st["sort_asc"], _compare["pending"],
            cache=compare_dispatch.READS, loaded=set(_compare_loaded_paths()))
        dt = time.monotonic() - t0
        if dt > 1.0:
            print(f"[fespp] compare matrix: {len(rows)} rows in {dt:.1f} s"
                  f" ({compare_dispatch.READS.get('_hits', 0)} from the cache,"
                  f" {compare_dispatch.READS.get('_reads', 0)} read)",
                  flush=True)
        state.ui_compare_blocks = blocks
        state.ui_compare_rows = rows
        state.ui_compare_annotations = ann
        state.ui_compare_deltas = compare_dispatch.deltas_from_rows(
            items, rows, st["baseline"])
        state.ui_compare_csv = compare_dispatch.csv_payload(
            items, rows, st["baseline"], kind=kind)
        _compare["cuts"] = _cuts_read()

    def _compare_resort():
        """A sort only reorders rows that are already computed: the blocks
        are rebuilt from ui_compare_rows, no array is read again."""
        if not _compare["views"]:
            return
        kind = _compare_current_kind()
        rows = getattr(state, "ui_compare_rows", None) or {}
        if not kind or not rows:
            _refresh_compare()
            return
        st = _kind_state(kind)
        items = _matrix_rows(_kind_items(_compare_items(),
                                         list(getattr(state, "ui_compare_chips", None) or []),
                                         kind))
        blocks, ann = compare_dispatch.blocks_from_rows(
            items, rows, st["baseline"], st["sort_key"], st["sort_asc"])
        state.ui_compare_blocks = blocks
        state.ui_compare_annotations = ann
        state.ui_compare_deltas = compare_dispatch.deltas_from_rows(
            items, rows, st["baseline"])

    def _push_compare_dist_figure(fig):
        # an EMPTY figure, never None: the plotly widget reads .data off it
        if fig is None:
            state.ui_compare_dist_figure = {"data": [], "layout": {}}
            return
        upd = getattr(controller, "update_compare_dist_figure", None)
        try:
            if upd is None:
                raise RuntimeError("no widget yet")
            upd(fig)
        except Exception:
            state.ui_compare_dist_figure = fig.to_plotly_json()

    def _compare_tab_dist(kind, items):
        """The overlaid histograms of ONE kind under its own options, the rows
        that follow an item among them."""
        opts = dict(_COMPARE_DIST_OPTS, **_kind_state(kind)["dist_opts"])
        fig, meta = compare_dispatch.dist_figure(
            state, tree, source_registry, _matrix_rows(items), opts, _compare["pending"],
            cache=compare_dispatch.TRACES, loaded=set(_compare_loaded_paths()))
        state.ui_compare_dist_meta = meta
        _push_compare_dist_figure(fig)

    def _compare_tab_xplot(kind, items):
        """The cross-plot of a kind tab is a cross-plot panel of its own (id =
        view id + "x"), seeded from the rows of its matrix: the X and the Y
        picked among them, never the same row; first the baseline, or the first
        row, and the next one. A row on another grid than X cannot pair with
        it: said in the note."""
        st = _kind_state(kind)
        uids = [it["uid"] for it in items if it.get("uid")]
        x = next((u for u in (st.get("xplot_x"), st["baseline"]) if u in uids), uids[0] if uids else "")
        y = st.get("xplot_y")
        if y not in uids or y == x:
            y = next((u for u in uids if u != x), "")
        state.ui_compare_xplot_axes = {"x": x, "y": y}
        seeds = compare_dispatch.xplot_seeds(state, tree, [dict(it, xplot=it.get("uid") == y) for it in items],
                                             x, _compare["pending"])
        skipped = seeds.get("skipped") or []
        state.ui_compare_xplot_note = "left out: " + "; ".join(skipped) if y and skipped else ""
        values = {"x": seeds.get("x") or None,
                  "xreal": seeds.get("xreal"), "xts": seeds.get("xts"),
                  "ys": [crossplot_dispatch.y_entry(y)
                         for y in (seeds.get("ys") or [])]}
        for vid in list(_compare["views"]):
            pid = f"{vid}x"
            changed = False
            for k, v in values.items():
                var = f"ui_crossplot_{k}_{pid}"
                if getattr(state, var, None) != v:
                    state[var] = v
                    changed = True
            # an axis write refreshes through the panel's own watcher; an
            # unchanged seeding still needs the figure recomputed
            if not changed:
                _refresh_crossplot(pid)

    def _compare_note(what, severity="warn", next_step=""):
        """The panel's one note line. It is a BAND under the bar, not a chip
        between the buttons, and it stays until its cause is gone or the
        reader closes it — nothing here clears it on the next refresh. An
        error names its next step apart, so the band can say it (R10)."""
        state.ui_compare_note_severity = severity
        state.ui_compare_note_next = next_step
        state.ui_compare_note = what
        _compare["unread_said"] = set()

    def _compare_failed(what):
        """A failed recompute must never leave the previous numbers on
        screen as if they were fresh: the matrix and the charts are emptied
        and the panel says so."""
        _compare_note(what, "error", "see the server log")
        state.ui_compare_dist_meta = {"kept": 0, "total": 0, "traces": 0,
                                      "note": what}
        _push_compare_dist_figure(None)
        state.ui_compare_xplot_note = what
        for vid in list(_compare["views"]):
            _drop_crossplot_figures(f"{vid}x")
        state.ui_compare_blocks = []
        state.ui_compare_rows = {}
        state.ui_compare_annotations = {}

    def _refresh_compare():
        """Deferred one turn behind the view's bar (see `_defer`): a tick
        and its echo in the same turn compute the matrix once, not twice."""
        if not _compare["views"]:
            return
        _defer("compare", _refresh_compare_now)

    def _refresh_compare_now():
        """The chips always, then the ACTIVE tab's matrix and charts —
        switching tab computes the one just shown."""
        if not _compare["views"]:
            return
        items = _compare_items()
        tab = getattr(state, "ui_compare_tab", "") or ""
        try:
            with capture_vtk_messages(state):
                chips = compare_dispatch.resolve_items(
                    state, tree, items, "", _compare["pending"])
                # the engine works on {path, real, ts}; the widget needs the
                # item's identity to name the row a gesture came from
                for chip, it in zip(chips, items):
                    chip["uid"] = it["uid"]
                # the tabs follow the selection: a tab whose last item left
                # goes with it, and the panel lands on the first kind
                kinds = _compare_kinds(chips)
                state.ui_compare_kinds = kinds
                labels = [k["kind"] for k in kinds]
                if tab not in labels:
                    tab = labels[0] if labels else ""
                    state.ui_compare_tab = tab
                # each chip's flag is its KIND's baseline: the item (by its
                # uid) the kind holds, while it is selected; none by default
                for k in labels:
                    st = _kind_state(k)
                    uids = [c["uid"] for c in chips
                            if (c.get("kind") or compare_dispatch.NO_KIND) == k]
                    if st["baseline"] not in uids:
                        st["baseline"] = ""
                    for c in chips:
                        if (c.get("kind") or compare_dispatch.NO_KIND) == k:
                            c["baseline"] = c["uid"] == st["baseline"]
                state.ui_compare_chips = chips
                _project_kind_state()
                if tab:
                    kind_items = _kind_items(items, chips, tab)
                    _compare_tab_stats(tab, kind_items)
                    _compare_tab_dist(tab, kind_items)
                    _compare_tab_xplot(tab, kind_items)
                else:
                    state.ui_compare_blocks = []
                    state.ui_compare_rows = {}
                    state.ui_compare_annotations = {}
                    state.ui_compare_deltas = {}
                    _compare["cuts"] = {}
        except Exception as exc:
            print("[fespp] compare error:", exc, flush=True)
            _compare_failed("the last recompute failed")

    def _refresh_compare_rows():
        """What a 3D view draws may have moved: when its rows would read
        something else, only what reads it comes again. The matrix and the
        overlay have their items from their caches (`READS`, `TRACES`), the
        chips and the cross-plot read the items alone."""
        if _compare["views"] and _cuts_read() != _compare["cuts"]:
            _defer("compare-rows", _refresh_compare_rows_now, views=list(_compare["views"]))

    def _refresh_compare_rows_now():
        kind = _compare_current_kind()
        if not _compare["views"] or not kind:
            return
        items = _kind_items(_compare_items(),
                            list(getattr(state, "ui_compare_chips", None) or []), kind)
        try:
            with capture_vtk_messages(state):
                _compare_tab_stats(kind, items)
                _compare_tab_dist(kind, items)
        except Exception as exc:
            print("[fespp] compare error:", exc, flush=True)
            _compare_failed("the last recompute failed")

    def _rebuild_compare_tree(items=None):
        """The docked tree — kind -> representation -> property, or the data
        tree's layout down to the representation, then the parts of the grids —
        over every property and part the FILE holds, derived
        recipes included, each leaf saying whether it is in the session; the
        items of a property no longer there are scrubbed (and the open view
        refreshed).

        `items` is the selection the caller has just computed: it is then
        written ONCE, here, instead of once before the tree and once again
        with it — each write recomputes the matrix, values included.
        Nothing is built while the Statistics view is closed: a tick in the data
        tree would otherwise walk the whole assembly and push a tree the
        session is not showing (opening a view builds it)."""
        if not _compare["views"]:
            return
        keep = _compare_items() if items is None else items
        # a recipe outlives its grid: its row says why it has no figures, and
        # reads again when the grid is read again
        recipes = {it["path"] for it in keep if _derived_store.get(it["path"]) is not None}
        loaded = _compare_loaded_paths()
        pending = dict(_compare["pending"])
        try:
            xml, path_map = compare_tree.kind_tree_xml(
                tree, _compare_listed_paths(recipes),
                # a part is read as a representation
                loaded=set(loaded) | set(getattr(state, "ui_loaded_rep_paths", None) or []) | recipes,
                pending=pending, parts=_compare_listed_parts(),
                by_kind=(getattr(state, "ui_compare_tree_layout", "kind") or "kind") == "kind")
        except Exception as exc:
            print("[fespp] compare tree error:", exc, flush=True)
            _compare_note("the selection tree could not be built", "error",
                          "see the server log")
            return
        _compare["path_map"] = dict(path_map)
        _compare["extract_folders"] = {compare_tree.extract_folder(tree, p)
                                       for p in stats_supports.session_extracts()}
        state.ui_compare_tree_xml = xml
        tabs = compare_tree.tree_tabs(xml)
        if tabs != (getattr(state, "ui_compare_tree_tabs", None) or []):
            state.ui_compare_tree_tabs = tabs
        held = compare_tree.families_present(xml)
        if held != (getattr(state, "ui_compare_tree_families", None) or []):
            state.ui_compare_tree_families = held
        # a property the tree no longer lists at all (another file was
        # opened) is not being waited for any more
        listed = set(path_map.values())
        pending = {p: st for p, st in pending.items() if p in listed}
        _compare["pending"] = pending
        # the selection follows what is LOADED, not what the tree managed to
        # title: a property the tree cannot show for a beat keeps its item —
        # and so does one whose load was asked for and has not landed yet,
        # which would otherwise be scrubbed between the tick and the values
        present = set(loaded) | set(pending) | recipes
        # a part unloaded with no view open to let it go goes now; an extract
        # is its view's (app/features/compare_parts)
        selected = set(getattr(state, "selected_paths", None) or [])
        _set_compare_parts([p for p in _compare_parts() if stats_supports.is_extract(p) or p in selected])
        _set_compare_items([it for it in keep if it["path"] in present])
        # The eyes are drawn in the paths this rebuild has just renamed, and
        # over the properties it has just found loaded: publish them HERE too,
        # or a tree opened on a session that already holds properties shows no
        # eye at all until an unrelated eye is clicked in a 3D view.
        _sync_compare_tree_eyes()

    def _compare_settle_pending(finished=False):
        """A load has run: the properties that arrived stop waiting. When the
        cycle is OVER, one that did not arrive is not waited on for ever — it
        turns "failed". Returns the properties that never came, None when
        nothing was waiting or nothing changed."""
        if not _compare["pending"]:
            return None
        pending, failed = compare_tree.settle_pending(
            _compare["pending"], _compare_loaded_paths(), finished)
        if pending == _compare["pending"]:
            return None
        _compare["pending"] = pending
        return failed

    def _compare_names(paths):
        return ", ".join(_property_label(p) or p.rsplit("/", 1)[-1]
                         for p in paths)

    def _compare_request_load(to_load):
        """Ask the session to READ these properties, through the very
        channel the data tree writes — born hidden: they enter the
        view and no 3D view, their eye in this tree being the door
        to the scene. A path already in `selected_paths` moves nothing —
        trame drops a write equal to the value it has pushed, so no load
        cycle runs and a wait for one would never end: such a path is
        declared failed at once instead, unless that selection is still being
        written (this tree's own tick) or has not reached the reader yet (a
        read going step by step): it waits like the others. Returns those
        declared failed.

        `ask=False`: this read has already been decided here (a tick under
        the cap, or one the user answered), so the data tree's own question
        must not be asked a second time about the very same properties;
        `push`, because nothing has written `selected_paths` for it."""
        if not to_load:
            return []
        sel = list(getattr(state, "selected_paths", None) or [])
        fresh = [p for p in to_load if p not in sel]
        handed = set(getattr(state, "fespp_data_selectors", None) or [])
        stuck = ([] if state.is_dirty("selected_paths")
                 else [p for p in to_load if p in sel and p in handed])
        if fresh:
            _apply_selection(sel + fresh, ask=False, push=True, shown=False)
        for path in stuck:
            _compare["pending"][path] = compare_dispatch.FAILED
        return stuck

    def _compare_tick_note(stuck):
        """What a tick did NOT do, said where the panel says everything
        else, and never blanking a note it has nothing to add to."""
        if stuck:
            _compare_note(
                f"{_compare_names(stuck)}: already selected in the data"
                " tree, yet the reader never brought the values in.",
                "error", "see Data health for what it said")
            _compare["unread_said"] = set(stuck)

    def _compare_load_note(failed):
        """A read asked from this tree that brought nothing says so."""
        if failed:
            _compare_note(
                f"{_compare_names(failed)}: the read did not bring the"
                " values in.", "error",
                "see Data health for what the reader said, then untick it"
                " here and tick it again to retry")
            _compare["unread_said"] = set(failed)

    def _compare_unread_note_goes():
        """The values a note said were missing are in: the note goes."""
        said = _compare["unread_said"]
        if said and said <= set(_compare_loaded_paths()):
            _compare_note("")

    @state.change("ui_loaded_array_paths", "ui_loaded_rep_paths")
    def _on_compare_loaded(**_):
        failed = _compare_settle_pending()
        _rebuild_compare_tree()
        _compare_load_note(failed)
        _compare_unread_note_goes()

    @state.change("ui_loading")
    def _on_compare_loading(ui_loading=False, **_):
        # the load cycle is over: a property still waiting never came
        if ui_loading:
            return
        failed = _compare_settle_pending(finished=True)
        if failed is None:
            return
        _rebuild_compare_tree()
        _compare_load_note(failed)

    @state.change("assembly_rev")
    def _on_compare_assembly(**_):
        # another file: the tree lists what the session holds now, what it no
        # longer lists is not being waited for any more (`_rebuild_compare_tree`)
        # and a question about the properties of a file gone has lost its subject
        if _compare["confirm"]:
            _compare["confirm"] = None
            _drop_tick_question()
        _rebuild_compare_tree()

    @state.change("lazy_rev")
    def _on_compare_lazy_read(**_):
        # properties read from the store: their kind folders are known now
        if _compare["views"]:
            _rebuild_compare_tree()

    @state.change("ui_cube_grid_rows")
    def _on_compare_lattice(**_):
        # the lattice grids are listed after the assembly: their properties
        # are filed under Seismic from now on
        _rebuild_compare_tree()

    def _ensure_compare_view(vid):
        """The Statistics view `vid` was just mounted: its cross-plot
        registers as a cross-plot panel, its tree is built and the
        selection that survived a close is read again."""
        if vid in _compare["views"]:
            return
        _compare["views"].append(vid)
        _register_crossplot(f"{vid}x")
        _rebuild_compare_tree()
        # its kind tree files every property: what a lazy load left on
        # the store is read in the background (lazy_rev rebuilds it)
        controller.lazy_read_all()

    def _close_compare_view(panel_id):
        if panel_id not in _compare["views"]:
            return
        if (_compare["confirm"] or {}).get("vid") == panel_id:
            _compare["confirm"] = None   # the question closed with its panel
            _drop_tick_question()
        _compare["views"] = [v for v in _compare["views"] if v != panel_id]
        _compare_published.pop(panel_id, None)
        _drop_crossplot(f"{panel_id}x")
        for k, v in _COMPARE_PAYLOAD.items():
            state[f"ui_compare_{k}"] = v

    @controller.set("open_compare")
    def open_compare():
        """Open (or focus) THE view. Which properties it holds is chosen in
        its own docked tree, or by "Stats" from a data tree."""
        mv = _mv()
        if mv is None:
            return
        try:
            vid = mv.add_view(kind="compare")
        except Exception as exc:
            print("[fespp] open compare view error:", exc, flush=True)
            return
        _ensure_compare_view(str(vid))
    return (_close_compare_view, _compare, _compare_current_kind, _compare_index, _compare_item_key, _compare_items, _compare_loaded_paths, _compare_names, _compare_note, _compare_parts, _compare_published, _compare_request_load, _compare_resort, _compare_set_axis, _compare_tick_note, _compare_uid, _kind_state, _project_kind_state, _rebuild_compare_tree, _refresh_compare, _refresh_compare_now, _refresh_compare_rows, _set_compare_items, _set_compare_parts, _sync_compare_tree_selection, open_compare)
