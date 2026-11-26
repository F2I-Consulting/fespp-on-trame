"""the dataspace explorer (engine/osdu_explorer)
The REST facade beside the ETP endpoint and the OSDU Search, with the
connection's credentials: the rows right after the connection, then
the facts of each dataspace by a background task the state mirrors
as it goes, and the catalogue on demand.
Plain HTTP in threads: nothing of ParaView here.
`inventory`: path -> the facade's (type, name) rows; `kinds`: path ->
the plugin's (type, name, kind) rows of the properties, read over ETP
on demand (osdu_kinds); `kinds_busy`: one inventory at a time
`base`: the REST facade of the current server; `memory`: what this
process read of each server before, by facade then dataspace path
({last_write, facts, inventory, kinds, kinds_summary}) — a connection
that ended, a token renewed, and the next listing keeps the facts of
every dataspace the store has not written since (no second scan), and
marks the others `changed` (the search's "modified" / "new" words)

(Moved out of app/boot, overhaul slice 10.)"""
import asyncio
import sys
import time
from fespp_on_trame.engine import osdu_explorer
from fespp_on_trame.engine import repo_query
from fespp_on_trame.engine import row_object
from fespp_on_trame.engine import etp
from fespp_on_trame.engine.vtk_log import capture_vtk_messages


def register(core, *, _conn, _etp_creds, _etp_do_connect, _etp_lost,
             _lost_next, _plugin_rebinds, _progress, _progressive,
             _publish_lazy_read, _token_expired, _watch_session):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_expand_blocked_well_trajectories, _osdu_list, _panel_reads, _prev_selected)."""
    # the shared services (app/core/context.Core)
    server = core.server
    state = core.state
    controller = core.controller
    tree = core.tree
    etp_connector = core.etp_connector
    # --- the dataspace explorer (engine/osdu_explorer) ---
    # The REST facade beside the ETP endpoint and the OSDU Search, with the
    # connection's credentials: the rows right after the connection, then
    # the facts of each dataspace by a background task the state mirrors
    # as it goes, and the catalogue on demand.
    # Plain HTTP in threads: nothing of ParaView here.
    # `inventory`: path -> the facade's (type, name) rows; `kinds`: path ->
    # the plugin's (type, name, kind) rows of the properties, read over ETP
    # on demand (osdu_kinds); `kinds_busy`: one inventory at a time
    # `base`: the REST facade of the current server; `memory`: what this
    # process read of each server before, by facade then dataspace path
    # ({last_write, facts, inventory, kinds, kinds_summary}) — a connection
    # that ended, a token renewed, and the next listing keeps the facts of
    # every dataspace the store has not written since (no second scan), and
    # marks the others `changed` (the search's "modified" / "new" words)
    _osdu = {"rest": None, "scan": None, "inventory": {}, "kinds": {}, "kinds_busy": False, "base": "", "memory": {}}

    def _remember(path, **fields):
        """Keep `fields` of the dataspace at `path` for the current server."""
        if _osdu["base"] and path:
            _osdu["memory"].setdefault(_osdu["base"], {}).setdefault(path, {}).update(fields)

    def _explorer(**changes):
        cur = dict(state.osdu_explorer or osdu_explorer.empty_state())
        cur.update(changes)
        # the rows this session has read are marked: the widget shows them
        # in the green of the logo
        loaded = set(state.ui_etp_loaded_dataspaces or [])
        cur["dataspaces"] = [dict(r, loaded=r.get("uri") in loaded) for r in (cur.get("dataspaces") or [])]
        state.osdu_explorer = cur
        state.flush()

    async def _osdu_list():
        uris = list(state.etp_dataspaces or [])
        _osdu["rest"] = None
        _osdu["inventory"] = {}
        _osdu["kinds"] = {}
        fresh = osdu_explorer.empty_state()
        fresh.update(status="listing", dataspaces=osdu_explorer.names_only(uris), total=len(uris))
        _explorer(**fresh)
        base = osdu_explorer.rest_base(_etp_creds.get("url"))
        if not base:
            print(f"[fespp] osdu explorer: no REST facade for {_etp_creds.get('url')}: names only", flush=True)
            _explorer(status="done", message="No REST facade beside this ETP endpoint: names only.")
            return
        rest = osdu_explorer.Rest(base, osdu_explorer.search_url(_etp_creds["url"]), _etp_creds.get("partition"),
                                  _etp_creds["token"], _etp_creds.get("token_type", "Bearer"))
        try:
            rows = await asyncio.to_thread(osdu_explorer.list_dataspaces, rest, uris)
        except osdu_explorer.OsduError as exc:
            print(f"[fespp] osdu explorer: facade {base} refused: {exc}", flush=True)
            _explorer(status="done", message=f"REST facade not reachable ({exc}): names only.")
            return
        # the facts, names and kinds read of this server before, for every
        # dataspace the store has not written since: kept, not scanned
        # again; a dataspace written since, or new, is marked `changed`
        _osdu["base"] = base
        known = _osdu["memory"].get(base) or {}
        kept = 0
        for r in rows:
            old = known.get(r.get("path"))
            # the seconds its last read took, whatever the store wrote since:
            # the Load button says them, the bar fills at that pace
            if old and old.get("load_seconds"):
                r["load_seconds"] = old["load_seconds"]
            if old is None:
                r["changed"] = bool(known)          # new since the last visit, when there was one
            elif (old.get("last_write") == r.get("last_write") and old.get("facts")
                  and not old["facts"].get("error")):
                r.update(facts=old["facts"], scan="done", progress=1.0, changed=False)
                _osdu["inventory"][r["path"]] = old.get("inventory") or []
                if old.get("kinds"):
                    _osdu["kinds"][r["path"]] = old["kinds"]
                    r["kinds"] = old.get("kinds_summary")
                kept += 1
            else:
                r["changed"] = True
        _osdu["rest"] = rest
        print(f"[fespp] osdu explorer: {len(rows)} dataspaces from {base}, facts scan starts"
              + (f" ({kept} unchanged since the last visit: facts kept)" if kept else ""), flush=True)
        _explorer(status="idle", rest=True, dataspaces=rows, total=len(rows))
        osdu_scan()

    async def _osdu_scan_task(rest):
        # (a row whose facts the memory of the server gave is done already)
        rows = [r if (r.get("scan") == "done" and r.get("facts")) else dict(r, scan="pending", progress=0.0)
                for r in (state.osdu_explorer.get("dataspaces") or [])]
        done = {"n": sum(1 for r in rows if r.get("scan") == "done")}
        _explorer(status="scanning", scanned=done["n"], total=len(rows), dataspaces=rows)
        # SCAN_PARALLEL dataspaces at a time, the most recent first: one
        # dataspace takes several seconds (three calls) and the server
        # answers several side by side; the loop only stitches the answers in
        gate = asyncio.Semaphore(osdu_explorer.SCAN_PARALLEL)
        started = time.monotonic()
        order = sorted((r for r in rows if r.get("scan") != "done"),
                       key=lambda r: r.get("last_write") or "", reverse=True)

        def mark(path, **fields):
            # one row's scan state, what the widget draws it with: "pending"
            # (a blue line), "scanning" with a progress 0..1 (a bar from blue
            # to green), "done" (a green dot), "error"
            current = [dict(r, **fields) if r.get("path") == path else r
                       for r in (state.osdu_explorer.get("dataspaces") or [])]
            _explorer(dataspaces=current)

        async def one(row):
            async with gate:
                if _osdu["rest"] is not rest:       # disconnected meanwhile
                    return
                mark(row["path"], scan="scanning", progress=0.15)
                try:
                    facts = await asyncio.to_thread(osdu_explorer.dataspace_facts, rest, row["path"])
                    if _osdu["rest"] is not rest:
                        return
                    # the facts are on screen at once; the names of its
                    # objects (what the search box finds a well, a property
                    # or a horizon by) come second
                    mark(row["path"], facts=facts, scan="scanning", progress=0.6)
                    _osdu["inventory"][row["path"]] = await asyncio.to_thread(
                        osdu_explorer.dataspace_inventory, rest, row["path"])
                    outcome = "done"
                except osdu_explorer.OsduError as exc:
                    facts, outcome = {"error": str(exc)}, "error"
                except Exception as exc:            # a thread's surprise never kills the loop
                    facts, outcome = {"error": repr(exc)}, "error"
            if _osdu["rest"] is not rest:
                return
            done["n"] += 1
            if outcome == "done":
                _remember(row["path"], last_write=row.get("last_write"), facts=facts,
                          inventory=_osdu["inventory"].get(row["path"]) or [])
            current = [dict(r, facts=facts, scan=outcome, progress=1.0) if r.get("path") == row["path"] else r
                       for r in (state.osdu_explorer.get("dataspaces") or [])]
            _explorer(dataspaces=current, scanned=done["n"])
            if facts.get("error"):
                print(f"[fespp] osdu explorer: {row['path']}: {facts['error']}", flush=True)

        await asyncio.gather(*(one(row) for row in order))
        if _osdu["rest"] is rest:
            print(f"[fespp] osdu explorer: facts of {len(rows)} dataspaces read in "
                  f"{time.monotonic() - started:.0f} s", flush=True)
            _explorer(status="done")

    @controller.set("osdu_scan")
    def osdu_scan():
        rest = _osdu["rest"]
        if rest is None or (_osdu["scan"] is not None and not _osdu["scan"].done()):
            return
        _osdu["scan"] = asyncio.ensure_future(_osdu_scan_task(rest))

    def _mark_kinds(uri, kinds):
        """One row's `kinds`: "reading", {total, kinds, unknown} or {error}."""
        current = [dict(r, kinds=kinds) if r.get("uri") == uri else r
                   for r in (state.osdu_explorer.get("dataspaces") or [])]
        _explorer(dataspaces=current)

    @controller.set("osdu_kinds")
    async def osdu_kinds(payload):
        """The property KINDS of one dataspace — porosity, permeability…,
        what no resource list carries — read by the plugin over the ETP
        session into a scratch repository, nothing loaded in the tree
        (repo_query.inventory_lines, the properties and their PropertyKind
        objects only). The row's `kinds` goes "reading", then {total, kinds,
        unknown} or {error}; the search box then finds a kind. The plugin
        answers synchronously, seconds on a hosted store, on the server
        loop: one at a time, never while a dataspace loads."""
        uri = ((payload or {}).get("uri") or "").strip()
        rows = list(state.osdu_explorer.get("dataspaces") or [])
        row = next((r for r in rows if r.get("uri") == uri), None)
        if row is None or not etp_connector.is_connected:
            return
        if state.etp_connecting or _osdu["kinds_busy"]:
            _mark_kinds(uri, {"error": "a dataspace is being read: ask again when it is done"})
            return
        source = etp_connector.get_source()
        if not repo_query.has_inventory(source):
            _mark_kinds(uri, {"error": "the FESPP plugin of this server predates the dataspace inventory"})
            return
        _osdu["kinds_busy"] = True
        _mark_kinds(uri, "reading")
        await asyncio.sleep(0.05)       # the "reading" state reaches the browser before the loop blocks
        t0 = time.monotonic()
        try:
            # the plugin answers an unchanged tag from its cache (and checks
            # the store's stamp behind a changed one): a refresh asked for
            # is a new tag
            refresh = (payload or {}).get("refresh")
            tag = f"{_conn['gen']}:{row.get('last_write') or '-'}:{int(time.time()) if refresh else 0}"
            with capture_vtk_messages(state) as msgs:
                lines = repo_query.inventory_lines(source, uri, ",".join(osdu_explorer.KIND_TYPES), tag)
            _say_etp_timing(msgs)
            parsed = osdu_explorer.parse_inventory(lines)
        except Exception as exc:
            print(f"[fespp] osdu kinds: {uri}: {exc!r}", flush=True)
            parsed = {"error": str(exc) or repr(exc), "objects": [], "info": {}}
        finally:
            _osdu["kinds_busy"] = False
        if parsed.get("error"):
            _mark_kinds(uri, {"error": parsed["error"]})
            return
        summary = osdu_explorer.kinds_summary(parsed["objects"])
        _osdu["kinds"][row.get("path")] = osdu_explorer.kind_rows(parsed["objects"])
        _remember(row.get("path"), last_write=row.get("last_write"), kinds=_osdu["kinds"][row.get("path")],
                  kinds_summary=summary)
        _mark_kinds(uri, summary)
        info = parsed.get("info") or {}
        print(f"[fespp] osdu kinds: {row.get('path')}: {summary['total']} properties, {len(summary['kinds'])} kinds"
              f" ({info.get('fetched', '?')} fetched, from_cache={info.get('from_cache', '?')},"
              f" plugin {info.get('seconds', '?')} s) in {time.monotonic() - t0:.1f} s", file=sys.stderr, flush=True)
        # a search typed meanwhile ranks with the kinds now
        typed = ((state.osdu_explorer.get("find") or {}).get("text") or "").strip()
        if typed:
            await osdu_find({"text": typed})

    @controller.set("osdu_find")
    async def osdu_find(payload):
        """The search box: ranked at once from what the scan inventoried
        (every dataspace of the server), then completed by the OSDU
        catalogue when it answers (the published ones); a newer text
        supersedes a catalogue answer still on its way."""
        text = ((payload or {}).get("text") or "").strip()
        rows = list(state.osdu_explorer.get("dataspaces") or [])
        # the facade's rows, the properties among them replaced by the
        # plugin's once their kinds were read
        inventories = {p: osdu_explorer.merge_inventories(_osdu["inventory"].get(p), _osdu["kinds"].get(p))
                       for p in set(_osdu["inventory"]) | set(_osdu["kinds"])}
        found = osdu_explorer.find(text, rows, inventories)
        _explorer(find=found)
        rest = _osdu["rest"]
        if rest is None or len(text) < 3:
            return
        ticket = object()
        _osdu["find_ticket"] = ticket
        try:
            catalogue = await asyncio.to_thread(osdu_explorer.catalogue_search, rest, text)
        except osdu_explorer.OsduError as exc:
            print(f"[fespp] osdu explorer: catalog for {text!r}: {exc}", flush=True)
            return
        if _osdu.get("find_ticket") is ticket:
            _explorer(find=osdu_explorer.merge_catalogue(found, catalogue, rows))

    @controller.set("osdu_search")
    async def osdu_search(payload):
        text = ((payload or {}).get("text") or "").strip()
        rest = _osdu["rest"]
        if rest is None:
            return
        _explorer(search={"text": text, "status": "searching", "total": 0, "dataspaces": [], "components": [], "message": ""})
        try:
            out = await asyncio.to_thread(osdu_explorer.catalogue_search, rest, text)
            _explorer(search={"text": text, "status": "done", "message": "", **out})
        except osdu_explorer.OsduError as exc:
            _explorer(search={"text": text, "status": "error", "total": 0, "dataspaces": [], "components": [],
                              "message": str(exc)})

    def _say_etp_timing(msgs):
        """The plugin times each step of a dataspace load ("[fespp] etp load
        <ds>: N resources in a s; M data objects (x MB) in b s; deserialized
        in c s; tree in d s; total t s") and of an inventory: what tells a
        slow network from the work done in FESPP, put in the session log
        where the warnings of a large dataspace would bury it."""
        for m in msgs or ():
            text = str((m or {}).get("text") or "")
            if text.startswith("[fespp] etp load") or text.startswith("[fespp] etp inventory"):
                print(text.strip(), file=sys.stderr, flush=True)

    # The objects a lazy dataspace load left on the store (FESPP, 2026-10-14):
    # in the tree from the discovery's edges, their XML read when OPENED: a
    # node selected (the plugin reads it with what it holds: a grid with its
    # properties), a tree node expanded (`tree_node_open`), a query on its
    # uuid. Everything is read in the background only while an assistant
    # view is open (`lazy_read_all`): the assistant names properties by their
    # kind. LAZY_BATCH at a time (about 0.3 s on ADME), never during a load,
    # never while a camera is moved: the views are rendered on this loop, and
    # a read froze their frames (the PO, 14/10, a grid turning by jerks for
    # the 20 s of the read). Once all are in, the tree is refreshed. `gen`
    # numbers the loads: a newer one takes the loop over.
    LAZY_BATCH = 40
    _lazy = {"gen": 0, "nonce": 0, "running": None, "remaining": None}

    def _lazy_source():
        """The ETP source when its plugin reads lazy objects, else None."""
        from fespp_on_trame.engine import repo_query as _rq
        try:
            src = etp_connector.get_source() if etp_connector.is_connected else None
            return src if src is not None and _rq.has_lazy_fetch(src) else None
        except Exception as exc:
            print("[fespp] lazy fetch: no channel:", exc, flush=True)
            return None

    def _lazy_busy():
        """A load, a connection, a stepped read, or a hand on a camera."""
        from fespp_on_trame.app.views.camera import ACTIVITY
        return (state.ui_loading or state.etp_connecting or _progressive["stepping"]
                or bool((state.ui_load_progress or {}).get("running"))
                or not ACTIVITY.quiet())

    async def _lazy_enrich(gen):
        from fespp_on_trame.engine import repo_query as _rq
        src = _lazy_source()
        if src is None:
            return
        _lazy["running"] = gen
        try:
            t0 = time.monotonic()
            fetched_all = 0
            while _lazy["gen"] == gen and etp_connector.is_connected:
                if _lazy_busy():
                    await asyncio.sleep(0.3)
                    continue
                _lazy["nonce"] += 1
                try:
                    got = _rq.lazy_fetch(src, LAZY_BATCH, _lazy["nonce"])
                except Exception as exc:
                    print("[fespp] lazy fetch error:", exc, flush=True)
                    return
                if got is None:
                    return
                remaining, fetched, _seconds = got
                _lazy["remaining"] = remaining
                fetched_all += fetched
                if remaining == 0 or fetched == 0:
                    break
                # a turn of the loop between batches: a frame, a click
                await asyncio.sleep(0.05)
            if _lazy["gen"] != gen or not fetched_all:
                return
            print(f"[fespp] lazy fetch: {fetched_all} objects read in the background"
                  f" in {time.monotonic() - t0:.1f} s", flush=True)
            while _lazy_busy():
                await asyncio.sleep(0.5)
                if _lazy["gen"] != gen:
                    return
            _publish_lazy_read()
            state.flush()
        finally:
            if _lazy["running"] == gen:
                _lazy["running"] = None

    @controller.set("lazy_read_all")
    def lazy_read_all():
        """Read in the background every object the lazy loads left on the
        store (the assistant's door asks it, and a load while an assistant
        view is open). A no-op when nothing waits or the read already runs."""
        if _lazy["remaining"] == 0 or _lazy["running"] == _lazy["gen"]:
            return
        if not state.ui_etp_loaded_dataspaces or _lazy_source() is None:
            return
        asyncio.ensure_future(_lazy_enrich(_lazy["gen"]))

    # the views that weigh EVERY property (the assistant names them by kind,
    # Compare files them by kind): while one is open, all is read
    _READS_ALL_KINDS = ("assistant", "compare")

    def _reader_of_all_open():
        mv = getattr(server.context, "multi_view", None)
        try:
            return bool(mv is not None and any(mv.panel_ids_of_kind(k) for k in _READS_ALL_KINDS))
        except Exception as exc:
            print("[fespp] lazy fetch: open views unknown, nothing read in the background:", exc, flush=True)
            return False

    @controller.set("tree_node_open")
    def tree_node_open(path):
        """A tree node the user expanded: the objects it and its children
        name, and what they hold (a grid's properties, a well's frames and
        channels), read from the store in ONE request when a lazy load left
        them there. A no-op on a file, or once nothing waits."""
        from fespp_on_trame.engine import repo_query as _rq
        if not path or _lazy["remaining"] == 0 or not state.ui_etp_loaded_dataspaces:
            return
        src = _lazy_source()
        nid = tree.find_node_id(path) if src is not None else None
        if nid is None:
            return
        asm = getattr(tree, "_data_assembly", None)
        names = [path.rsplit("/", 1)[-1]]
        try:
            names += [asm.GetNodeName(asm.GetChild(nid, i)) for i in range(asm.GetNumberOfChildren(nid))]
        except Exception as exc:
            print(f"[fespp] lazy fetch (opened node): children of {path} not listed:", exc, flush=True)
        uuids = []
        for name in names:
            uuid = row_object.uuid_of(name)
            if uuid and uuid not in uuids:
                uuids.append(uuid)
        if not uuids:
            return
        _lazy["nonce"] += 1
        try:
            got = _rq.lazy_fetch(src, 3000, _lazy["nonce"], uuids)
        except Exception as exc:
            print("[fespp] lazy fetch (opened node):", exc, flush=True)
            return
        if got is None:
            return
        _lazy["remaining"] = got[0]
        if got[1]:
            # the browser tree only shows the ×N of a vector property: the
            # 2.6 MB of XML go again only when one was just read
            vector = False
            try:
                for i in range(asm.GetNumberOfChildren(nid)):
                    c = asm.GetChild(nid, i)
                    if int(asm.GetAttributeOrDefault(c, "componentCount", "1") or 1) > 1:
                        vector = True
                        break
            except Exception as exc:
                print("[fespp] lazy fetch (opened node): component counts unread, tree not sent:", exc, flush=True)
            _publish_lazy_read(xml=vector)

    @controller.set("etp_select")
    async def etp_select(payload):
        dataspace = ((payload or {}).get("dataspace") or "").strip()
        if not dataspace or not etp_connector.is_connected:
            return
        state.etp_connecting = True
        state.etp_status = f"Loading dataspace {dataspace} …"
        state.flush()
        # the flush only queues the message: the loop must turn once for it
        # to reach the browser BEFORE the plugin's call blocks the loop for
        # the whole load (minutes on a hosted store). Without this turn the
        # explorer's Load bar, which waits ten seconds for "busy", gave up
        # and the row looked idle while the dataspace was still being read
        # (the PO, 12/10, a Load clicked during the facts scan).
        await asyncio.sleep(0.05)
        from fespp_on_trame.engine.etp_debug import etp_debug
        # how long a dataspace takes to reach the tree, in the session log:
        # what tells a slow server from a large dataspace
        t_load = time.monotonic()
        ok = False
        try:
            with capture_vtk_messages(state) as msgs:
                # On success this ends with controller.update_data_information()
                # -> tree + assembly_xml refresh, same path as an EPC load.
                ok = await etp.select_etp_dataspace(etp_connector, dataspace)
            # The connector's verdict counts the tree's children: a tree that
            # already holds another dataspace has some, so a dataspace that
            # gave nothing would pass as loaded. FESPP's own warning, and
            # fetpapi's, decide.
            _say_etp_timing(msgs)
            empty = etp.said_empty(msgs, dataspace)
            lost = _etp_lost()
            ok = ok and not empty and not lost
            etp_debug(f"etp_select: first attempt ok={ok} empty={empty} lost={lost}; vtk tail="
                      f"{[str((m or {}).get('text') or '')[:200] for m in (state.vtk_log_messages or [])[-5:]]}")
            expired = not ok and _token_expired()
            # A new session only while no object of this connection is in
            # memory — on an old plugin, where the objects already read would
            # keep the dead session (see _LOST_NEXT); a plugin that rebinds
            # them reconnects whatever is in memory. The first dataspace of a
            # session that died before anything was read is the case this
            # retry was first for.
            fresh_start = not state.ui_etp_loaded_dataspaces or _plugin_rebinds()
            if not ok and _etp_creds and not expired and fresh_start:
                state.etp_status = ("Nothing received — the server probably "
                                    "closed the session. Reconnecting …")
                state.flush()
                # Close the old fetpapi session BEFORE opening a new one:
                # reconnecting over a still-live session leaves its asio
                # handlers orphaned, and the process crashes seconds later.
                try:
                    etp_connector.disconnect()
                    etp_debug("etp_select: old session closed before reconnect")
                except Exception as exc:
                    etp_debug(f"etp_select: disconnect before reconnect failed: {exc}")
                if await _etp_do_connect(_etp_creds["url"], _etp_creds.get("partition"),
                                         _etp_creds["token"],
                                         _etp_creds.get("token_type", "Bearer")):
                    asyncio.ensure_future(_watch_session(_conn["gen"], _etp_creds.get("expiry")))
                    with capture_vtk_messages(state) as msgs:
                        ok = await etp.select_etp_dataspace(etp_connector, dataspace)
                    _say_etp_timing(msgs)
                    empty = etp.said_empty(msgs, dataspace)
                    lost = _etp_lost()
                    ok = ok and not empty and not lost
                    etp_debug(f"etp_select: retry after reconnect ok={ok}; vtk tail="
                              f"{[str((m or {}).get('text') or '')[:200] for m in (state.vtk_log_messages or [])[-5:]]}")
                else:
                    etp_debug("etp_select: reconnect FAILED")
            if ok:
                state.etp_status = f"Dataspace {dataspace} loaded."
                # what this load left on the store is read when opened; all of
                # it in the background only while an assistant view is open
                _lazy["gen"] += 1
                _lazy["remaining"] = None
                if _reader_of_all_open():
                    controller.lazy_read_all()
                loaded = list(state.ui_etp_loaded_dataspaces or [])
                if dataspace not in loaded:
                    state.ui_etp_loaded_dataspaces = loaded + [dataspace]
                # how long this dataspace took, on the row and in the memory
                # of this server: the next Load of it shows a bar filling at
                # that pace, and the Load button says "about N s last time"
                seconds = round(time.monotonic() - t_load, 1)
                rows = []
                for r in (state.osdu_explorer or {}).get("dataspaces") or []:
                    if r.get("uri") == dataspace:
                        r = dict(r, load_seconds=seconds)
                        _remember(r.get("path"), load_seconds=seconds)
                    rows.append(r)
                _explorer(dataspaces=rows)
            elif expired:
                # a reconnection with the same token would be refused too
                state.etp_status = ("The token has expired: connect again with a"
                                    " fresh one to read this dataspace.")
            elif lost:
                state.etp_status = (f"Nothing received for {dataspace}: the connection"
                                    " to the server was lost. " + _lost_next())
            elif state.etp_connected:
                state.etp_status = (
                    f"Nothing received for {dataspace}: it holds nothing this"
                    " application reads, or the server dropped the session. If"
                    " another dataspace gives nothing too, reload the page and"
                    " resume from the Session button.")
            else:
                state.etp_status = ("Reconnection failed — the token may have "
                                    "expired. Connect again with a fresh one.")
        except Exception as exc:
            print("[fespp] etp_select error:", exc, flush=True)
            state.etp_status = f"Failed to load dataspace {dataspace}."
        finally:
            state.etp_connecting = False
            print(f"[fespp] etp_select: {dataspace} {'loaded' if ok else 'not loaded'} "
                  f"in {time.monotonic() - t_load:.1f} s", file=sys.stderr, flush=True)

    @controller.set("etp_disconnect")
    def etp_disconnect():
        # a stepped read from this server ends here: no step after the
        # session. It STOPS (not a newer generation, which would skip its
        # catch-up): what was not read is unticked, and the reason is said
        if (state.ui_load_progress or {}).get("running"):
            _progressive["stop"] = True
            _progressive["disconnected"] = True
            _progress(**dict(state.ui_load_progress, stopping=True))
        try:
            etp_connector.disconnect()
        except Exception as exc:
            print("[fespp] etp_disconnect error:", exc, flush=True)
        state.etp_connected = etp_connector.is_connected
        if not state.etp_connected:
            _etp_creds.clear()
            _osdu["rest"] = None
            _osdu["inventory"] = {}
            _osdu["kinds"] = {}
            if _osdu["scan"] is not None and not _osdu["scan"].done():
                _osdu["scan"].cancel()
            state.osdu_explorer = osdu_explorer.empty_state()
            state.etp_dataspaces = []
            state.etp_status = ""
            state.ui_etp_endpoint = {}
            state.ui_etp_loaded_dataspaces = []

    # The tree widget owns its interaction state and writes back path lists.
    # A node's path is the assembly's GetNodePath, which is what
    # fespp_data_selectors expects, so loading is almost a direct
    # passthrough (no id or dict round-trip).
    def _expand_blocked_well_trajectories(paths):
        """Add the trajectory of every selected BlockedWellbore to `paths`.

        A BlockedWellbore (under its supporting grid) references its
        WellboreTrajectory (well tree) by a `trajectoryUuid` attribute. The
        tree widget does not tick that trajectory across tabs, so it is
        mirrored here: the well line renders alongside the blocked cells.
        Recomputed on each change, so the added trajectory follows the
        blocked wellbore, while a trajectory ticked on its own persists
        through `paths` itself. Returns (paths, {trajectory path: title of
        the blocked wellbore that pulled it})."""
        out = list(paths)
        seen = set(out)
        pulled = {}    # trajectory path -> title of the blocked well pulling it
        for p in paths:
            nid = tree.find_node_id(p)
            if nid is None or tree.find_type(nid) != "BlockedWellbore":
                continue
            traj_uuid = tree.find_attribute_value(nid, "trajectoryUuid")
            traj_nid = tree.find_node_id_by_uuid(traj_uuid) if traj_uuid else None
            traj_path = tree.find_path(traj_nid) if traj_nid is not None else None
            if traj_path and traj_path not in seen:
                out.append(traj_path)
                seen.add(traj_path)
                pulled[traj_path] = tree.find_title(nid) or "a blocked wellbore"
        return out, pulled

    # Previous EFFECTIVE selection (post-cascade paths): the expansion works
    # on deltas (added / removed against the previous one), so the watcher
    # keeps its own baseline instead of trusting the raw widget value.
    _prev_selected = {"paths": []}

    # What a PANEL's tree asked to read (Statistics, the well-log)
    # and the representations that read pulled in. A tick there puts the
    # object in the panel and nowhere else: these paths are born with a
    # closed eye, and the two born-visible writers (`_on_selectors` for the
    # arrays, `_on_loaded_reps` for the representations) leave them out of
    # every 3D view's eye set. The eye of the panel tree is then the door
    # to the scene. A path leaves the set when it leaves the selection, so
    # ticking it again in the data tree shows it as any data-tree tick does.
    _panel_reads = set()
    return (_expand_blocked_well_trajectories, _osdu_list, _panel_reads, _prev_selected)
