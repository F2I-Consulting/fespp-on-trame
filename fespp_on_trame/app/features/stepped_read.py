"""a big read goes step by step (engine/progressive_load)
What is ticked shows as it arrives, and Stop ends the read: the
selection reaches `fespp_data_selectors` in growing steps, each one a
load of its own, and the server loop is free between two of them, so
Stop, a "clear all" or a new tick get in (a single load holds the
server for its whole length and cannot be stopped). `ui_load_progress`
is the pill at the bottom of the view that says how far the read is
and carries Stop (fespp_on_trame.__main__). `gen` numbers the
selections: a newer one supersedes a stepped read still running.
`per_object`: the seconds one object took on the last stepped read, by
source ("file", or the server's URL): what sizes the first step of the
next one (engine/progressive_load.first_batch)

(Moved out of app/boot, overhaul slice 10.)"""
import asyncio
import os
import sys
import time
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import data_load
from fespp_on_trame.engine import tick_confirm
from fespp_on_trame.app.views import per_view_state


def register(core, *, _apply_selection, _conn, _etp_creds, _etp_lost,
             _frame_first, _lost_next, _prev_selected, _progressive, _say,
             _token_expired):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_is_object_path, _is_property_path, _panel_tick_read, _progress, _set_selectors)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    scheduler = core.scheduler
    # --- a big read goes step by step (engine/progressive_load) ------------
    # What is ticked shows as it arrives, and Stop ends the read: the
    # selection reaches `fespp_data_selectors` in growing steps, each one a
    # load of its own, and the server loop is free between two of them, so
    # Stop, a "clear all" or a new tick get in (a single load holds the
    # server for its whole length and cannot be stopped). `ui_load_progress`
    # is the pill at the bottom of the view that says how far the read is
    # and carries Stop (fespp_on_trame.__main__). `gen` numbers the
    # selections: a newer one supersedes a stepped read still running.
    # `per_object`: the seconds one object took on the last stepped read, by
    # source ("file", or the server's URL): what sizes the first step of the
    # next one (engine/progressive_load.first_batch)

    def _progress(**fields):
        state.ui_load_progress = dict(fields)
        state.flush()

    # A grid of this many cells or more is announced before it is read: its
    # read holds the server for a while, and the reader should know why.
    BIG_CELLS = 5_000_000

    def _big_grids(paths):
        """"velocity_dataset: 94.7 M cells" for each IJK grid among `paths`
        whose XML counts BIG_CELLS cells or more, in one round trip; a grid
        whose XML is not at hand is not announced."""
        from fespp_on_trame.engine import repo_query
        grids = {uuid: tree.find_title(tree.find_node_id(path)) or "a grid"
                 for uuid, path in tree.ijk_grids_of(paths).items()}
        if not grids:
            return []
        try:
            texts = repo_query.object_xml(core.active_data_source.get_source(), list(grids))
        except Exception as exc:
            print("[fespp] load: the grids' sizes not read:", exc, flush=True)
            return []
        out = []
        for (uuid, title), text in zip(grids.items(), texts):
            cells = tick_confirm.ijk_cells(text)
            if cells >= BIG_CELLS:
                out.append(f"{title}: {cells / 1e6:.1f} M cells")
        return out

    def _holds_back(path):
        """A node whose tick selects its whole subtree in the reader (a
        folder): kept for the last step of a stepped read, or it would load
        its subtree at once."""
        nid = tree.find_node_id(path)
        if nid is None:
            return False
        from fespp_on_trame.engine import element_type as _et
        try:
            return _et.for_kind(tree.find_type(nid)).propagates_selection()
        except Exception as exc:
            print(f"[fespp] holds_back {path}: {exc}", file=sys.stderr, flush=True)
            return False

    def _owner_of(path):
        """The lot a leaf belongs to in a stepped read: its wellbore (a
        trajectory, its frames, their channels and markers arrive together),
        else its grid (the properties of one grid), else itself."""
        nid = tree.find_node_id(path)
        if nid is None:
            return path
        for kind in ("Wellbore", "GridContainer", "IjkGrid", "UnstructuredGrid"):
            owner = tree.find_parent_node_id_with_type(nid, kind)
            if owner is not None and owner != nid:
                return tree.find_path(owner) or path
        return path

    def _is_object_path(path):
        """An object the reader reads — a representation, a property, a
        well — and not a folder: what a server read downloads one by one."""
        return tree.find_node_id(path) is not None and not _holds_back(path)

    def _veil_then(paths, gen, n_now):
        """A tick or an untick read in one go: the loading veil is pushed,
        and the load runs one loop turn later. The load holds the loop for
        its whole length, and wslink sends on the NEXT turn: a veil written
        in the same handler reached the browser only once it was over, so
        the reader saw a frozen view and no veil (the PO, 20/10). A newer
        selection made in between supersedes this one (`gen`)."""
        delta = len(paths) - n_now
        big = _big_grids([p for p in paths if p not in set(state.fespp_data_selectors or [])]) if delta > 0 else []
        if big:
            state.view_loading_message = f"Loading {', '.join(big)} — a long read…"
        elif delta > 0:
            state.view_loading_message = (
                f"Loading {delta} checked item{'s' if delta != 1 else ''}…")
        elif delta < 0:
            state.view_loading_message = (
                f"Unloading {-delta} item{'s' if delta != -1 else ''}…")
        else:
            state.view_loading_message = "Updating the selection…"
        state.ui_loading = True
        state.flush()

        async def _go():
            await asyncio.sleep(0.03)
            if _progressive["gen"] != gen:
                return
            try:
                with state:
                    state.fespp_data_selectors = paths
            finally:
                # the selectors handler clears it when its load ends; a write
                # equal to the current selection runs no handler at all
                if state.ui_loading and _progressive["gen"] == gen:
                    with state:
                        state.ui_loading = False

        asyncio.ensure_future(_go())

    def _set_selectors(paths, stepped=True, veil=True):
        """Load `paths`: at once, or step by step when the read is big.
        `veil` False keeps a gesture's one-go read synchronous: a panel's
        read fills the panel right after it, from what was read."""
        from fespp_on_trame.engine import progressive_load as _pl
        _progressive["gen"] += 1
        _progressive["stop"] = False
        _progressive["expired"] = False
        _progressive["lost"] = False
        _progressive["disconnected"] = False
        current = list(state.fespp_data_selectors or [])
        had = set(current)
        if had == set(paths) and not (state.ui_load_progress or {}).get("running"):
            # the same set (another order at most): nothing to read or drop —
            # writing it again would run the whole load for nothing; a veil
            # a superseded gesture put up goes with it
            if state.ui_loading and not _progressive["stepping"]:
                state.ui_loading = False
            return
        leaves, _held = _pl.plan([p for p in paths if p not in had], _holds_back)
        # a server's objects among them: each is a download
        remote = bool(core.active_data_source.store_paths(leaves))
        if not stepped or not _pl.worth_stepping(leaves, remote):
            if (state.ui_load_progress or {}).get("running"):
                _progress(running=False)
            if stepped and veil:
                # a gesture read in one go: the veil goes out FIRST
                _veil_then(paths, _progressive["gen"], len(current))
                return
            state.fespp_data_selectors = paths
            return
        keep = set(paths)
        base = [p for p in current if p in keep]
        # the steps take LOTS, things that belong together: a wellbore with
        # its frames, channels and markers; the properties of one grid
        asyncio.ensure_future(_load_in_steps(
            _progressive["gen"], base, _pl.lots(leaves, _owner_of), list(paths), remote))

    async def _load_in_steps(gen, base, lots, final, remote):
        from fespp_on_trame.engine import progressive_load as _pl
        started = time.monotonic()
        where = "from the server" if remote else "from the file"
        leaves = [p for lot in lots for p in lot]
        note = ", ".join(_big_grids(leaves))
        pace_key = (_etp_creds.get("url") or "server") if remote else "file"
        # the views framed DURING this read were framed on its first objects
        # alone: they are framed again on everything once it has arrived
        framed_before = set(per_view_state.FRAMED)

        def apply(selectors):
            # one step: the selectors handler loads it and renders it,
            # without the veil — the pill says it, the view stays in sight.
            # Returns the part of it that was the redraw (all of it but the
            # reader's own pass): the next step is sized from it.
            _progressive["stepping"] = True
            t0 = time.monotonic()
            before = len(state.fespp_data_selectors or [])
            # FESPP_STEP_PROFILE=1: the step's whole handler chain profiled,
            # the app's own functions by cumulative time (the bench
            # tests/visual/scenarios/step_cost reads it in the log)
            prof = None
            if os.environ.get("FESPP_STEP_PROFILE") == "1":
                import cProfile
                prof = cProfile.Profile()
                prof.enable()
            # a step with another to come pushes one image (data_load.run);
            # the last one, the whole selection, pushes its two as a load does
            data_load.INTERMEDIATE_STEP = set(selectors) != set(final)
            try:
                state.fespp_data_selectors = selectors
                state.flush()
            finally:
                _progressive["stepping"] = False
                data_load.INTERMEDIATE_STEP = False
                if prof is not None:
                    prof.disable()
            spent = time.monotonic() - t0
            if prof is not None:
                import io as _io
                import pstats
                buf = _io.StringIO()
                pstats.Stats(prof, stream=buf).sort_stats("cumulative").print_stats("fespp_on_trame", 16)
                print(buf.getvalue(), file=sys.stderr, flush=True)
            redraw = max(0.0, spent - data_load.LAST_READ_SECONDS)
            # one line per step, the measure of what a step costs beyond its
            # own objects: the redraw of everything loaded (TODO "rendre
            # chaque étape de lecture moins chère")
            costly = [ph for ph in data_load.LAST_PHASES if ph[1] >= 0.1]
            in_run = sum(s for _label, s in data_load.LAST_PHASES)
            print(f"[fespp] load: step of {max(0, len(selectors) - before)} object(s), {len(selectors)} selected:"
                  f" read {data_load.LAST_READ_SECONDS:.2f} s, redraw {redraw:.2f} s"
                  + (" (" + ", ".join(f"{label} {s:.2f}" for label, s in costly) + ")" if costly else "")
                  + f", outside data_load.run {max(0.0, spent - in_run):.2f} s",
                  file=sys.stderr, flush=True)
            return redraw

        def report(done, total):
            _progress(running=True, done=done, total=total, where=where, note=note,
                      stopping=bool(_progressive["stop"]))

        def should_stop():
            # past the token's end, or once the session is gone, every
            # object would fail or wait out its own delay: the read stops
            # by itself, and says why
            if _progressive["disconnected"]:
                return True          # the user disconnected: said as such
            if remote and _token_expired():
                _progressive["expired"] = True
                return True
            if remote and _etp_lost():
                _progressive["lost"] = True
                return True
            return _progressive["stop"]

        try:
            outcome, loaded = await _pl.run_steps(
                base, lots, final, apply, report, should_stop,
                lambda: _progressive["gen"] == gen,
                # the pace measured on this source, else, on a server, the
                # guess that keeps a first step short (a hosted store reads
                # an object in about a second: a first lot of sixteen would
                # be a blank quarter of a minute)
                per_object=_progressive["per_object"].get(pace_key)
                or (_pl.REMOTE_PACE_GUESS if remote else None),
                learned=lambda seconds: _progressive["per_object"].__setitem__(pace_key, seconds))
        except Exception as exc:
            print(f"[fespp] stepped load error: {exc}", file=sys.stderr, flush=True)
            outcome, loaded = "error", list(state.fespp_data_selectors or [])
        print(f"[fespp] load: stepped read {outcome}, {len(leaves)} objects {where}, "
              f"{time.monotonic() - started:.1f} s", file=sys.stderr, flush=True)
        if _progressive["gen"] != gen:
            return          # the newer selection owns the reader and the pill
        _progress(running=False)
        # a view framed on the first step's objects is framed again on the
        # whole: a stepped read must end as a one-shot load looks
        for vid in sorted(per_view_state.FRAMED - framed_before):
            try:
                _frame_first(vid)
                scheduler.mark_dirty(vid)
            except Exception as exc:
                print(f"[fespp] load: framing {vid} after the stepped read:", exc, flush=True)
        if per_view_state.FRAMED - framed_before:
            try:
                scheduler.flush()
            except Exception as exc:
                print("[fespp] load: flush after the stepped read:", exc, flush=True)
        if outcome == "done":
            return
        # what was not read comes off, in sight: the boxes say what is loaded
        read = sum(1 for p in leaves if p in set(loaded))
        _prev_selected["paths"] = list(loaded)
        state.selected_paths = list(loaded)
        state.flush()
        if _progressive["disconnected"]:
            _say(f"Disconnected: the download stopped after {read} of {len(leaves)} objects;"
                 " the others are unticked.")
        elif _progressive["expired"]:
            _say(f"The OSDU token has expired: the download stopped after {read} of "
                 f"{len(leaves)} objects. Connect again with a fresh token to read the rest.")
        elif _progressive["lost"]:
            _conn["lost_said"] = True        # said here, the watcher need not
            _say(f"The connection to the OSDU server was lost: the download stopped after"
                 f" {read} of {len(leaves)} objects. " + _lost_next())
        elif outcome == "stopped":
            _say(f"Stopped: {read} of {len(leaves)} objects read, the others are unticked.")
        else:
            _say(f"The read failed after {read} of {len(leaves)} objects; the others are unticked.")
        # a task, not a trame callback: nothing pushes the state for it
        state.flush()

    @controller.set("load_stop")
    def load_stop():
        """Stop: the read ends after the object being read, what has
        arrived stays."""
        if not (state.ui_load_progress or {}).get("running"):
            return
        _progressive["stop"] = True
        _progress(**dict(state.ui_load_progress, stopping=True))

    def _is_property_path(path):
        """A property leaf or a derived recipe — the only paths that carry
        values (engine/node_facts, the one answer)."""
        return node_facts.is_property(tree, path)

    @controller.set("session_select")
    def session_select(paths, replace=False):
        """A restored session's reads (app/session_host): what the session
        held, read without the large-read question — the reader asked for
        the whole session by opening it — and born hidden: each view's eyes,
        restored next, say where it shows. `replace`: the list IS the
        session's reads (a document's `selected_paths`), what it leaves
        out is unloaded."""
        sel = list(getattr(state, "selected_paths", None) or [])
        want = [p for p in (paths or ()) if p]
        if replace:
            if sorted(want) != sorted(sel):
                _apply_selection(want, ask=False, push=True, shown=False)
            return
        fresh = [p for p in want if p not in sel]
        if fresh:
            _apply_selection(sel + fresh, ask=False, push=True, shown=False)

    def _panel_tick_read(want, on_cancel=None, on_go=None):
        """A tick made in a PANEL's tree reads what it names — into the
        panel, and into no 3D view.

        Same channel, same question, same cap as a tick in the data tree —
        `selected_paths` is the one thing that loads — so a folder standing
        for more unread properties than one click can show asks first. But
        the read is born hidden (`shown=False`): the object goes in the
        panel whose tree was ticked, the scene does not change, and the eye
        of that tree is the door to it.
        `on_go` is how the panel takes the object in: it runs when the read
        goes ahead, so a question that is refused leaves the panel exactly as
        it was rather than needing `on_cancel` to undo what it had shown.
        `on_cancel` stays for what a caller had already changed."""
        sel = list(getattr(state, "selected_paths", None) or [])
        fresh = [p for p in (want or ()) if p and p not in sel]
        if not fresh:
            # nothing to read: the panel takes it in straight away
            if on_go is not None:
                on_go()
            return
        # `push`: the tick came from a panel's tree and not from
        # `selected_paths`, so nothing has written it — see `_apply_selection`
        _apply_selection(sel + fresh, on_no=on_cancel, push=True, on_go=on_go,
                         shown=False)
    return (_is_object_path, _is_property_path, _panel_tick_read, _progress, _set_selectors)
