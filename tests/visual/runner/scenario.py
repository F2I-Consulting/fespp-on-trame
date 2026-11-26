"""Headless visual-test scenario runner.

It lives with the tests, out of the product package (overhaul Q9):
``test-visual.ps1`` copies it into the container and names it in
``FESPP_SCENARIO_RUNNER``, and ``app/boot`` loads it from there.

Activated ONLY when the ``FESPP_SCENARIO`` environment variable points to a
scenario JSON file (see ``tests/visual/``): after ``on_server_ready`` the
runner executes the scripted steps through the SAME state vars and
controller methods the browser UI drives, and captures server-side
screenshots along the way. ``test-visual.ps1`` then diffs the captures
against per-scenario baselines. Inert in normal runs — no client, no UI
interaction, no state cost when the env var is absent.

Scenario file format — a JSON object::

    {"steps": [
      {"op": "load",   "path": "/tmp/testdata/drogon.epc"},
      {"op": "check",  "title": "Facies"},
      {"op": "shot",   "name": "grid_facies"},
      {"op": "eye",    "title": "Geogrid"},
      {"op": "set",    "var": "ui_slices_range_mode", "value": "range"},
      {"op": "volumes_fraction", "i": [0.4, 1.0], "j": [0, 1], "k": [0, 1]},
      {"op": "activate", "title": "Facies"},
      {"op": "reset_camera"},
      {"op": "wait",   "s": 2}
    ]}

Every step accepts an optional ``settle`` (seconds to sleep after the
step; default 1.5) so trame flush chains and renders complete before the
next step or shot."""
import asyncio
import hashlib
import json
import os
import struct
import time

from paraview import servermanager
from paraview import simple as pvsimple
from fespp_on_trame.engine import node_facts

# label -> MiB malloc held at a `memory` step
_MEMORY_MARKS = {}

# The well-side tree kinds the well-log probe ticks under a wellbore.
_WELL_KINDS = {
    "Wellbore", "Trajectory", "Frame", "MarkerFrame", "Marker",
    "SeismicWellboreFrame", "Completion", "Channel", "WellboreMarkerFrame",
}

_DEFAULT_SETTLE = 1.5
_SHOT_RESOLUTION = [1280, 800]


def schedule(server, state, controller, tree, view, scenario_path):
    """Fire the runner as a background task on the server loop."""
    asyncio.ensure_future(
        _run(server, state, controller, tree, view, scenario_path)
    )


def _out_dir():
    d = os.environ.get("FESPP_SCENARIO_OUT", "/tmp/visual_out")
    os.makedirs(d, exist_ok=True)
    return d


def _heavy_pending(controller):
    """True while a recompute is still running behind its view's bar
    (`app/features/heavy._defer`)."""
    try:
        return bool(controller.heavy_pending())
    except Exception:
        return False


def _log(out, msg):
    print(f"[SCENARIO] {msg}", flush=True)
    with open(os.path.join(out, "scenario.log"), "a") as f:
        f.write(msg + "\n")


def _fingerprint(values):
    """One digest of the values read. A min/max envelope is not enough to
    tell two readings apart: two components may share their bounds, hold
    the same values in another order, or differ only inside the envelope."""
    h = hashlib.md5()
    for x in values:
        h.update(struct.pack("<d", float(x)))
    return h.hexdigest()[:12]


async def _crossplot_settled(state, pid, timeout=30.0):
    """The cross-plot panel `pid` read every chart: the charts are
    computed one by one on the event loop (boot._refresh_crossplot), so a
    probe waits until none is loading before it reads the figures."""
    waited = 0.0
    while waited < timeout:
        await asyncio.sleep(0.25)
        waited += 0.25
        charts = getattr(state, f"ui_crossplot_charts_{pid}", None)
        if charts is not None and not any(c.get("loading") for c in charts):
            await asyncio.sleep(0.5)   # the final publish, meta included
            return
    raise RuntimeError(f"crossplot {pid}: still loading after {timeout:.0f} s")


def _find_node(tree, step):
    """The node a step names: by its `title` (and `under`), or the first
    node, in document order, of the kind `type` — for the nodes a scenario
    cannot name by title, as the SubRepresentations of a file, titled by
    whoever produced it."""
    kind = step.get("type")
    if not kind:
        return _find_node_by_title(tree, step["title"], step.get("under"))
    asm = tree._data_assembly
    if asm is None:
        return None

    def walk(nid):
        if (tree.find_type(nid) or "") == kind:
            return nid
        for i in range(asm.GetNumberOfChildren(nid)):
            hit = walk(asm.GetChild(nid, i))
            if hit is not None:
                return hit
        return None

    return walk(asm.GetRootNode())


def _find_node_by_title(tree, title, under=None):
    """First assembly node whose title (fallback: label) equals `title`.
    `under` (optional) scopes the search to the subtree of the first
    node titled `under` — disambiguates titles repeated across
    containers (every grid has a "SolidColor" geometry leaf)."""
    asm = tree._data_assembly
    if asm is None:
        return None
    hits = []

    def walk(nid, want):
        t = (asm.GetAttributeOrDefault(nid, "title", None)
             or asm.GetAttributeOrDefault(nid, "label", None))
        if t == want:
            hits.append(nid)
            return
        for i in range(asm.GetNumberOfChildren(nid)):
            walk(asm.GetChild(nid, i), want)

    root = asm.GetRootNode()
    if under:
        walk(root, under)
        if not hits:
            return None
        # the scope's CHILDREN, not the scope itself: a time-series leaf
        # titled like its own collection would otherwise resolve to the folder
        scope, hits = hits[0], []
        for i in range(asm.GetNumberOfChildren(scope)):
            walk(asm.GetChild(scope, i), title)
        return hits[0] if hits else None
    walk(root, title)
    return hits[0] if hits else None


def _prop_path_under(tree, rid, title):
    """The assembly path of the property titled `title` whose
    representation node is `rid` — a probe names properties the way the
    tree shows them, under a grid named the same way."""
    for nid in tree.find_all_descendant_ids(0):
        if not node_facts.is_property_kind(tree.find_type(nid) or ""):
            continue
        if tree.find_representation_node(nid) != rid:
            continue
        if (tree.find_title(nid) or "") == title:
            return tree.find_path(nid)
    raise RuntimeError(f"property not found under the grid: {title!r}")


def _resolve_args(tree, args, state=None):
    """Scenario args as the app expects them: a {"title": ..} (optional
    "under") stands for that node's assembly path, {"chain_entry": n} for
    the name of the active view's n-th threshold entry, {"compare_item":
    {"title": ..}} for the uid of that property's first row of its own in the
    Statistics view — at any depth inside the lists and dicts of a payload (a
    session document names its objects that way)."""
    def one(a):
        if isinstance(a, dict) and "title" in a:
            nid = _find_node_by_title(tree, a["title"], a.get("under"))
            if nid is None:
                raise RuntimeError(f"node not found: {a['title']!r}")
            return tree.find_path(nid)
        if isinstance(a, dict) and "panel_of_kind" in a:
            # the id of the first open panel of that kind (a singleton's id)
            from trame.app import get_server
            mv = getattr(get_server().context, "multi_view", None)
            ids = list(mv.panel_ids_of_kind(a["panel_of_kind"])) if mv is not None else []
            if not ids:
                raise RuntimeError(f"no open panel of kind {a['panel_of_kind']!r}")
            return ids[0]
        if isinstance(a, dict) and "compare_item" in a and state is not None:
            path = one(a["compare_item"])
            for it in getattr(state, "ui_compare_items", None) or ():
                if it.get("path") == path and not it.get("pinned"):
                    return it.get("uid")
            raise RuntimeError(f"no row of {path!r} in the Statistics view")
        if isinstance(a, dict) and "chain_entry" in a and state is not None:
            vid = getattr(state, "fespp_active_panel_id", "") or ""
            chain = list(getattr(state, f"ui_thresholds__{vid}", None) or [])
            return chain[int(a["chain_entry"])]["name"]
        if isinstance(a, list):
            return [one(x) for x in a]
        if isinstance(a, dict):
            # a controller payload: its values resolved as above
            # ({"path": {"title": "Geogrid"}, "mode": "keep"})
            return {k: one(v) for k, v in a.items()}
        return a
    return [one(a) for a in (args or [])]


def _render_vid(server, state):
    """The 3D view the scenario drives: the active panel when it is one,
    else the first render view — an analysis panel a probe opened may have
    taken the focus, and its id names no colour bar."""
    mv = getattr(server.context, "multi_view", None)
    ids = list(mv.view_ids()) if mv is not None else []
    pid = getattr(state, "fespp_active_panel_id", "") or ""
    return pid if pid in ids else (ids[0] if ids else pid)


def _graph_rep_blocks(rep, extract, root):
    """The blocks a log graph's representation really draws, named as the
    view's filter names them (`root`, its assembly's root: an ExtractBlock's
    output has a root of its own), and their colours: a selector that names
    no block of the extract draws nothing and is left out."""
    data = extract.GetClientSideObject().GetOutputDataObject(0)
    asm = data.GetDataAssembly() if data is not None and hasattr(data, "GetDataAssembly") else None

    def as_filter(path):
        return root + "/" + path.split("/", 2)[2] if path.count("/") >= 2 else path

    shown = {as_filter(b) for b in rep.BlockSelectors if asm is not None and len(asm.SelectNodes([b]))}
    quads = list(rep.BlockColors) if rep.GetProperty("BlockColors") else []
    colours = {as_filter(quads[k]): [round(float(c), 3) for c in quads[k + 1:k + 4]]
               for k in range(0, len(quads) - 3, 4)}
    return shown, colours


def _resolve_view(server, state, fallback):
    try:
        mv = getattr(server.context, "multi_view", None)
        pid = getattr(state, "fespp_active_panel_id", "") or ""
        v = mv.get_pv_view(pid) if (mv is not None and pid) else None
        if v is not None:
            return v
    except Exception:
        pass
    return fallback or pvsimple.GetActiveView()


def _same(got, want):
    """`got` is `want` — numbers to the float's precision (a state var
    written 3.0 is the 3 of a scenario)."""
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return abs(float(got) - float(want)) <= 1e-9 * max(1.0, abs(float(want)))
        except (TypeError, ValueError):
            return False
    return got == want


async def _assistant_probe(server, state, controller, tree, step, out):
    """One sentence said to the Assistant (widgets/assistant) through the
    panel's own controller, and its reply held to the step:

        {"op": "assistant_probe", "say": "filter porosity above 0.2",
         "expect_intent": "threshold", "expect_level": "ok",
         "expect_threshold": true, "then_undo": true}

    Optional keys: `expect_intent` (what the host's parse takes the
    sentence for — the command the controller runs), `expect_level`,
    `expect_text_contains`, `expect_text_matches` (a regex), `expect_row`
    (a row label of the reply's table, or a list of accepted ones),
    `expect_visible` ([{"title", "under"}] shown in the 3D view the
    assistant acts on), `expect_threshold` (true: the command added a
    threshold entry to that view; false: the view has none),
    `expect_panel` (a panel of that kind is open), `expect_state`
    ({var: value}), `expect_highlight_count_min` (a lower bound on the
    cells the command lit, checked twice: on the count boot's
    `highlight_where` returns during the step — caught on the controller,
    or else the count the reply starts with — and on the ids of the
    selection drawn on the active source; a highlight that lights nothing
    still replies ok), `expect_highlight_cleared` (true: the active source
    holds no selection), `expect_wait` (seconds, default 10), `then_undo`
    (the reply's Undo, whose own reply must be ok — and an added threshold
    must be gone again).

    What a reply changes in the application is POLLED for `expect_wait`
    seconds: a read, or a debounced commit (the Z scale), lands after the
    call returns. The first expectation not met raises."""
    import re
    from fespp_on_trame.engine.view_routing import resolve_active_render_panel

    say = step["say"]
    wait = float(step.get("expect_wait", 10.0))

    def _expect(cond, what):
        _log(out, f"  {'OK ' if cond else 'FAIL'} {what}")
        if not cond:
            raise RuntimeError(f"assistant_probe {say!r}: {what}")

    async def _until(pred):
        t0 = time.monotonic()
        while True:
            got = pred()
            if got or time.monotonic() - t0 >= wait:
                return got
            await asyncio.sleep(0.25)

    def _messages():
        return list((getattr(state, "ui_assistant", None) or {}).get("messages") or [])

    def _reply_after(msg_id):
        # the conversation's last message, once it is a reply newer than
        # `msg_id`
        msgs = _messages()
        m = msgs[-1] if msgs else {}
        return m if m.get("role") == "assistant" and m.get("id") != msg_id else None

    def _said(m):
        return (f"[{m.get('level')}] {m.get('text')!r} rows={m.get('rows') or []}"
                f" choices={[c.get('id') for c in m.get('choices') or []]}"
                f" undoable={bool(m.get('undoable'))}")

    def _gesture(name):
        fn = getattr(controller, name, None)
        exists = getattr(fn, "exists", None)
        if fn is None or (callable(exists) and not exists()):
            raise RuntimeError(f"assistant_probe: no controller {name!r} — the"
                               " assistant is off (FESPP_ASSISTANT=0) or was not built")
        return fn

    ask = _gesture("assistant_ask")
    if step.get("expect_intent") is not None:
        host = getattr(server.context, "assistant_host", None)
        _expect(host is not None, "the assistant's adapter is reachable (context.assistant_host)")
        cmd = host.parse(say) or {}
        _log(out, f"  parse: {cmd.get('intent')} {cmd.get('confidence')} sure={cmd.get('sure')}"
                  f" targets={[t.get('title') for t in cmd.get('targets') or []][:8]}"
                  f" missing={cmd.get('missing')}")
        _expect(cmd.get("intent") == step["expect_intent"],
                f"read as {step['expect_intent']!r} (got {cmd.get('intent')!r})")

    # the 3D view the assistant acts on, as its adapter resolves it
    vid = resolve_active_render_panel(state)

    def _chain():
        return [e.get("name") for e in (getattr(state, f"ui_thresholds__{vid}", None) or [])]

    def _lit():
        """How many ids the selection on the active source holds — what
        `node_highlight` and `highlight_where` draw (a composite id
        selection: flat index, piece, id) — or None, the reason logged,
        when it cannot be read."""
        ads = getattr(server.context, "active_data_source", None)
        try:
            from fespp_on_trame.engine.derived_arrays import display_source_of as _dsrc
            src = _dsrc(ads)
            if src is None:
                _log(out, "  -- no active source: the drawn selection cannot be read")
                return None
            sel = getattr(src, "SMProxy", src).GetSelectionInput(0)
            n, todo = 0, [sel] if sel is not None else []
            while todo:
                p = todo.pop()
                ids = p.GetProperty("IDs")
                if ids is not None:
                    n += ids.GetNumberOfElements() // 3
                inputs = p.GetProperty("Input")
                if inputs is not None:
                    todo += [inputs.GetProxy(i) for i in range(inputs.GetNumberOfProxies())]
            return n
        except Exception as exc:
            _log(out, f"  -- the drawn selection could not be read: {exc!r}")
            return None

    def _leading_count(text):
        # the reply starts with the count, thin-space grouped (numfmt)
        m = re.match(r"\s*(\d[\d\u2009\u202f\u00a0 ,]*)", text or "")
        return int(re.sub(r"\D", "", m.group(1))) if m else None

    # what boot's highlight_where returns, caught on the controller for the
    # step's length: the reply only says what the adapter made of it
    min_lit = step.get("expect_highlight_count_min")
    returned = []
    # well_cells_where is caught the same way: its "lit" (the cells the
    # wells go through) stands for the count
    wrapped = []
    for name in (("highlight_where", "well_cells_where") if min_lit is not None else ()):
        hw = getattr(controller, name, None)
        inner = getattr(hw, "func", None)
        if inner is None:
            continue

        def _caught(*args, _inner=inner, **kw):
            res = _inner(*args, **kw)
            if isinstance(res, dict) and "lit" in res and "count" not in res:
                res = dict(res, count=res["lit"])
            returned.append(res)
            return res
        hw.func = _caught
        wrapped.append((hw, inner))

    chain_before = _chain()
    before = _messages()
    try:
        with state:
            ask(say)
        reply = await _until(lambda: _reply_after(before[-1].get("id") if before else None)) or {}
    finally:
        for hw, inner in wrapped:
            hw.func = inner
    _log(out, f"  reply {_said(reply)}")
    _expect(bool(reply), "the assistant replied")
    if step.get("expect_level"):
        _expect(reply.get("level") == step["expect_level"],
                f"level {step['expect_level']!r} (got {reply.get('level')!r})")
    if step.get("expect_text_contains"):
        _expect(step["expect_text_contains"] in (reply.get("text") or ""),
                f"the reply says {step['expect_text_contains']!r}")
    if step.get("expect_text_matches"):
        _expect(re.search(step["expect_text_matches"], reply.get("text") or "") is not None,
                f"the reply matches /{step['expect_text_matches']}/")
    if step.get("expect_row"):
        want = step["expect_row"]
        want = [want] if isinstance(want, str) else list(want)
        labels = [str(r[0]) for r in reply.get("rows") or [] if r]
        _expect(any(w in labels for w in want),
                f"a row {' or '.join(map(repr, want))} (rows: {labels})")
    for spec in step.get("expect_visible") or []:
        nid = _find_node_by_title(tree, spec["title"], spec.get("under"))
        _expect(nid is not None, f"{spec['title']!r} is in the tree")
        path = tree.find_path(nid)
        shown = await _until(
            lambda p=path: p in (getattr(state, f"visible_paths__{vid}", None) or []))
        _expect(bool(shown), f"{spec['title']!r} is shown in {vid}")
    if step.get("expect_threshold") is not None:
        if step["expect_threshold"]:
            added = await _until(lambda: [n for n in _chain() if n not in chain_before])
            _expect(bool(added), f"a threshold entry was added in {vid} ({_chain()})")
        else:
            gone = await _until(lambda: not _chain())
            _expect(bool(gone), f"no threshold entry in {vid} ({_chain()})")
    if step.get("expect_panel"):
        mv = getattr(server.context, "multi_view", None)
        kind = step["expect_panel"]
        opened = await _until(lambda: mv is not None and list(mv.panel_ids_of_kind(kind)))
        _expect(bool(opened), f"a {kind!r} panel is open")
    for var, val in (step.get("expect_state") or {}).items():
        ok = await _until(lambda k=var, x=val: _same(getattr(state, k, None), x))
        _expect(bool(ok), f"{var} is {val!r} (got {getattr(state, var, None)!r})")
    if min_lit is not None:
        if returned:
            res = returned[-1] if isinstance(returned[-1], dict) else {}
            _log(out, f"  highlight_where returned {returned[-1]!r}")
            _expect(not res.get("error"), f"highlight_where lit cells ({res.get('error')!r})")
            count, source = res.get("count"), "highlight_where returned"
        else:
            count, source = _leading_count(reply.get("text")), "the reply says"
            _log(out, "  -- highlight_where could not be caught on the controller:"
                      " the count is the reply's")
        _expect(isinstance(count, int) and count >= int(min_lit),
                f"{source} {count!r} cell(s) lit, at least {min_lit}")
        # polled while readable (an unreadable selection is logged once)
        drawn = []
        await _until(lambda: drawn.append(_lit()) or drawn[-1] is None
                     or drawn[-1] >= int(min_lit))
        _expect(drawn[-1] is not None and drawn[-1] >= int(min_lit),
                f"the selection drawn on the active source holds {drawn[-1]!r} id(s),"
                f" at least {min_lit}")
    if step.get("expect_highlight_cleared"):
        drawn = []
        await _until(lambda: drawn.append(_lit()) or drawn[-1] in (None, 0))
        _expect(drawn[-1] == 0, f"no selection left on the active source (ids: {drawn[-1]!r})")

    if step.get("then_undo"):
        undo = _gesture("assistant_undo")
        last = _messages()
        with state:
            undo()
        back = await _until(lambda: _reply_after(last[-1].get("id") if last else None)) or {}
        _log(out, f"  undo {_said(back)}")
        _expect(back.get("level") == "ok", f"the undo is done (level {back.get('level')!r})")
        if step.get("expect_threshold"):
            restored = await _until(lambda: _chain() == chain_before)
            _expect(bool(restored), f"the undo took the threshold entry out ({_chain()})")


async def _run(server, state, controller, tree, view, scenario_path):
    out = _out_dir()
    shot_idx = 0
    try:
        with open(scenario_path) as f:
            steps = json.load(f).get("steps", [])
        _log(out, f"start: {scenario_path} ({len(steps)} steps)")
        # a native crash writes the Python stack it happened under to the
        # scenario's folder (faulthandler): which call of the app died
        try:
            import faulthandler as _fh
            _crash_file = open(os.path.join(out, "crash_stack.txt"), "a")
            _crash_file.write("--- run " + time.strftime("%H:%M:%S") + "\n")
            _crash_file.flush()
            _fh.enable(file=_crash_file, all_threads=True)
        except Exception as exc:
            _log(out, f"faulthandler not armed: {exc}")
        # Let boot (plugin load, layout, initial data_load) settle.
        await asyncio.sleep(4.0)

        # Headless: the first render panel is normally created by the
        # dockview client's `ready` event (content.py) — with no browser
        # attached it never fires, so the per-view scene machinery
        # (view_resources, fespp_active_panel_id, coloring fan-out)
        # would stay dormant. Create it server-side.
        mv = getattr(server.context, "multi_view", None)
        if mv is not None and not getattr(mv, "_first_view_adopted", False):
            with state:
                mv.add_view()
            _log(out, f"panel created: {getattr(state, 'fespp_active_panel_id', '')!r}")
            await asyncio.sleep(2.0)

        for i, step in enumerate(steps):
            op = step.get("op", "")
            _log(out, f"step {i}: {json.dumps(step)}")
            v = _resolve_view(server, state, view)

            if op == "load":
                with state:
                    controller.load_epc_file(step["path"])

            elif op in ("check", "uncheck"):
                # Through `selected_paths`, the tree widget's own variable:
                # the path the UI drives, with its cascades and vetoes.
                # Never the per-tab `ui_select_node_*` lists of the legacy
                # selector: the UI does not write them, and writing them
                # races the tree handler over `fespp_data_selectors`, each
                # unloading what the other has just loaded.
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                path = tree.find_path(nid)
                with state:
                    lst = list(getattr(state, "selected_paths", None) or [])
                    if op == "check" and path not in lst:
                        lst.append(path)
                    if op == "uncheck" and path in lst:
                        lst.remove(path)
                    controller.select_paths(lst)

            elif op in ("check_raw", "uncheck_raw"):
                # The data tree's OWN gesture, with no exemption: `check`
                # goes through `controller.select_paths`, which the tick
                # confirmation (engine/tick_confirm) lets through without a
                # question because the server has already decided to read.
                # Writing `selected_paths` is what the widget does, so this
                # is the only op that can reach the data tree's
                # confirmation box.
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                path = tree.find_path(nid)
                with state:
                    lst = list(getattr(state, "selected_paths", None) or [])
                    if op == "check_raw" and path not in lst:
                        lst.append(path)
                    if op == "uncheck_raw" and path in lst:
                        lst.remove(path)
                    state.selected_paths = lst
                    state.dirty("selected_paths")
                ask = getattr(state, "ui_tick_confirm", None) or {}
                _log(out, f"{op} {step['title']!r}:"
                          f" asked={ask.get('title')!r}")
                if ask and step.get("answer") is not None:
                    with state:
                        controller.tick_confirm_answer(bool(step["answer"]))
                    _log(out, f"  answered {bool(step['answer'])}:"
                              f" selected={len(getattr(state, 'selected_paths', None) or [])}")

            elif op == "tree_tick":
                # The tick of a 3D view's data tree as the widget sends it
                # (`tree_tick` = {vid, kind, paths}, tick_question._tree_tick):
                # what reaches the per-view reactions, as the vertical domain
                # question (app/features/view_domain).
                # {"op":"tree_tick","title":"BCU","answer":true}; with
                # "untick": true the row and what hangs under it are unticked;
                # with "geometry": true the row is the geometry of the object
                # titled so (its representation, a row under its container);
                # with "type" and "every": true every node of that kind at
                # once, as the tree's "Select" menu ticks them
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                path = tree.find_path(nid)
                every_ = ([tree.find_path(n_) for n_, _k in tree.iter_nodes()
                           if (tree.find_type(n_) or "") == step["type"]]
                          if step.get("every") and step.get("type") else [])
                if step.get("geometry"):
                    rid = next((r for r in tree.find_all_descendant_ids(nid)
                                if tree.find_representation_node(r) == r), None)
                    if rid is None:
                        raise RuntimeError(f"no representation under {step.get('title')!r}")
                    path = tree.find_path(rid)
                cvid = _render_vid(server, state)
                with state:
                    lst = list(getattr(state, "selected_paths", None) or [])
                    if step.get("untick"):
                        lst = [p for p in lst if p != path and not p.startswith(path + "/")]
                    elif every_:
                        lst += [p_ for p_ in every_ if p_ not in lst]
                    elif path not in lst:
                        lst.append(path)
                    # a new dict each time: an equal one would not be sent
                    state.tree_tick = {"vid": cvid, "kind": "render", "paths": lst, "n": i}
                    state.dirty("tree_tick")
                ask = getattr(state, "ui_tick_confirm", None) or {}
                _log(out, f"tree_tick {step.get('title')!r}: asked={ask.get('title')!r}")
                if ask and step.get("answer") is not None:
                    with state:
                        controller.tick_confirm_answer(bool(step["answer"]))
                    _log(out, f"  answered {bool(step['answer'])}")

            elif op == "tree_tick_all":
                # Every node of a kind ticked at once, as a hand ticking a
                # folder does (one tree_tick carrying all the paths);
                # `vdomain` keeps the nodes of that vertical domain only (the
                # others would ask the domain question).
                # {"op":"tree_tick_all","type":"Grid2d","vdomain":"depth"}
                asm_ = tree._data_assembly
                want_, dom_ = step.get("type") or "", step.get("vdomain")
                paths_ = []
                for n_ in asm_.GetChildNodes(0, True):
                    if (tree.find_type(n_) or "") != want_:
                        continue
                    if dom_ and (asm_.GetAttributeOrDefault(n_, "vdomain", "") or "") != dom_:
                        continue
                    paths_.append(tree.find_path(n_))
                cvid = _render_vid(server, state)
                with state:
                    lst = list(getattr(state, "selected_paths", None) or [])
                    lst += [p_ for p_ in paths_ if p_ not in lst]
                    state.tree_tick = {"vid": cvid, "kind": "render", "paths": lst, "n": i}
                    state.dirty("tree_tick")
                _log(out, f"tree_tick_all {want_!r}{' ' + dom_ if dom_ else ''}: {len(paths_)} node(s)")

            elif op == "scene_cut_trace":
                # the scene cut writes its steps to the scenario's folder
                # (engine/blockscope/scene_crop._trace): a crash leaves them
                os.environ["FESPP_SCENE_CUT_TRACE"] = os.path.join(out, "scenecut_trace.txt")
                _log(out, "scene cut traced to scenecut_trace.txt")

            elif op == "tick_log":
                # The first log channel of the tree (a property whose parent
                # is a wellbore frame) ticked like a hand does, its frame
                # opened first when a lazy ETP load left its channels on the
                # store. {"op":"tick_log","skip":0}
                asm_ = tree._data_assembly
                hits_ = []
                for n_ in asm_.GetChildNodes(0, True):
                    up_ = asm_.GetParent(n_)
                    kind_ = asm_.GetAttributeOrDefault(n_, "type", "") or ""
                    pkind_ = asm_.GetAttributeOrDefault(up_, "type", "") or "" if up_ is not None and up_ >= 0 else ""
                    if "Property" in kind_ and pkind_ == "Frame":
                        hits_.append(n_)
                if not hits_:
                    # open the first frames: their channels are read now
                    for n_ in asm_.GetChildNodes(0, True):
                        if (asm_.GetAttributeOrDefault(n_, "type", "") or "") == "Frame":
                            r_ = controller.tree_node_open(tree.find_path(n_))
                            if asyncio.iscoroutine(r_):
                                await r_
                            break
                    await asyncio.sleep(5)
                    asm_ = tree._data_assembly
                    for n_ in asm_.GetChildNodes(0, True):
                        up_ = asm_.GetParent(n_)
                        if ("Property" in (asm_.GetAttributeOrDefault(n_, "type", "") or "")
                                and (asm_.GetAttributeOrDefault(up_, "type", "") or "") == "Frame"):
                            hits_.append(n_)
                if not hits_:
                    raise RuntimeError("tick_log: no log channel in the tree")
                n_ = hits_[min(int(step.get("skip", 0)), len(hits_) - 1)]
                path_ = tree.find_path(n_)
                _log(out, f"tick_log: {asm_.GetAttributeOrDefault(n_, 'title', '')!r} ({path_[-60:]})")
                with state:
                    lst_ = list(getattr(state, "selected_paths", None) or [])
                    if path_ not in lst_:
                        lst_.append(path_)
                    state.tree_tick = {"vid": _render_vid(server, state), "kind": "render", "paths": lst_, "n": i}
                    state.dirty("tree_tick")

            elif op == "activate":
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                # the tree widget's click: this view's active node, and the
                # per-tab active the grid tools follow (reservoir by default)
                vid = _render_vid(server, state)
                path = tree.find_path(nid)
                tab = step.get("tab", "reservoir")
                with state:
                    server.context.activation.activate(vid, path, tab=tab)
                    state.dirty(f"active_path__{vid}")
                    state.dirty(f"active_by_tab__{vid}")

            elif op == "eye":
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                r_id = tree.find_representation_node(nid)
                rep_path = tree.find_path(r_id) if r_id is not None else None
                if not rep_path:
                    raise RuntimeError(f"no rep path for: {step.get('title') or step.get('type')!r}")
                # The tree widget's eye: this view's `visible_paths__<vid>`
                # toggled, then the reconcile — exactly what the widget
                # wrapper does (views/widgets/data_tree.py).
                vid = _render_vid(server, state)
                var = f"visible_paths__{vid}"
                # a PROPERTY eye lists the property's own path (on_eye_changed
                # adds the grid rep); toggling the rep path would hide the
                # grid. A rep or a folder toggles the rep path.
                own = node_facts.is_property_kind(tree.find_type(nid) or "")
                path = tree.find_path(nid) if own else rep_path
                with state:
                    cur = list(getattr(state, var, None) or [])
                    if path in cur:
                        cur.remove(path)
                    else:
                        cur.append(path)
                    state[var] = cur
                    state.dirty(var)
                    controller.on_eye_changed(vid, list(cur))

            elif op == "eyes_expect":
                # The eyes open in the render view, by title: each of "open"
                # open, none of "closed" —
                # {"op":"eyes_expect","open":["PROBA"],"closed":["GR","WIRE_GM"]}
                vid = _render_vid(server, state)
                titles_ = []
                for p_ in list(getattr(state, f"visible_paths__{vid}", None) or []):
                    n_ = tree.find_node_id(p_)
                    titles_.append((tree.find_title(n_) if n_ is not None else None) or p_)
                _log(out, f"eyes open ({vid}): {titles_}")
                for t_ in step.get("open", ()):
                    if t_ not in titles_:
                        raise RuntimeError(f"eyes_expect: {t_!r} is not open: {titles_}")
                for t_ in step.get("closed", ()):
                    if t_ in titles_:
                        raise RuntimeError(f"eyes_expect: {t_!r} is still open: {titles_}")

            elif op == "welllog_mdtvd":
                # The log view's MD-TVD table (`mdTvd`, the MD column beside a TVD axis) against each log's own
                # samples: for every sample [value, md, tvd], the TVD the table gives its MD — the largest gap said,
                # and a failure past "tol" metres. {"op":"welllog_mdtvd","tol":5}
                pids_ = list(mv.panel_ids_of_kind("welllog")) if mv is not None else []
                data_ = (getattr(state, f"welllog_data__{pids_[0]}", None) or {}) if pids_ else {}
                worst_ = 0.0
                for w_ in data_.get("wells") or ():
                    pairs_ = w_.get("mdTvd") or []
                    if len(pairs_) < 2:
                        _log(out, f"log view: {w_.get('name')} has no MD-TVD table (laid out on {w_.get('depthRef')})")
                        continue
                    mds_ = [p_[0] for p_ in pairs_]
                    tvds_ = [p_[1] for p_ in pairs_]
                    import bisect as _bisect

                    def _tvd_at(md):
                        k_ = max(1, min(len(mds_) - 1, _bisect.bisect_left(mds_, md)))
                        a_, b_ = mds_[k_ - 1], mds_[k_]
                        f_ = 0.0 if b_ == a_ else (md - a_) / (b_ - a_)
                        return tvds_[k_ - 1] + f_ * (tvds_[k_] - tvds_[k_ - 1])
                    _log(out, f"log view: {w_.get('name')} MD-TVD table of {len(pairs_)} pairs, MD {mds_[0]:.1f}..{mds_[-1]:.1f}"
                              f" first {pairs_[:4]}")
                    for t_ in w_.get("tracks") or ():
                        for c_ in t_.get("curves") or ():
                            s_ = [x_ for x_ in c_.get("samples") or () if len(x_) > 2 and x_[1] is not None
                                  and x_[2] is not None]
                            gaps_ = [abs(_tvd_at(x_[1]) - x_[2]) for x_ in s_]
                            if gaps_:
                                worst_ = max(worst_, max(gaps_))
                                _log(out, f"log view: {c_.get('name')}: {len(s_)} samples, first [md, tvd] "
                                          f"{[[round(x_[1], 1), round(x_[2], 1)] for x_ in s_[:3]]}, table off by up to "
                                          f"{max(gaps_):.1f} m")
                if "tol" in step and worst_ > float(step["tol"]):
                    raise RuntimeError(f"welllog_mdtvd: the MD-TVD table is off by {worst_:.1f} m")

            elif op == "welllog_expect":
                # The curves the log view draws, by name: each of "curves" drawn, none of "absent" —
                # {"op":"welllog_expect","curves":["GR"],"absent":["PROBA"]}
                pids_ = list(mv.panel_ids_of_kind("welllog")) if mv is not None else []
                if not pids_:
                    raise RuntimeError("welllog_expect: no log view open")
                drawn_ = sorted({c_.get("name") for w_ in (getattr(state, f"welllog_data__{pids_[0]}", None) or {})
                                 .get("wells") or () for t_ in w_.get("tracks") or ()
                                 for c_ in t_.get("curves") or () if c_.get("name")})
                _log(out, f"log view ({pids_[0]}): curves {drawn_}")
                for n_ in step.get("curves", ()):
                    if n_ not in drawn_:
                        raise RuntimeError(f"welllog_expect: {n_!r} is not drawn: {drawn_}")
                for n_ in step.get("absent", ()):
                    if n_ in drawn_:
                        raise RuntimeError(f"welllog_expect: {n_!r} is drawn: {drawn_}")
                if step.get("all_under"):
                    # every log of a node drawn: {"all_under": {"title": "WIRE_GM", "under": "<well>"}}
                    from fespp_on_trame.engine import node_facts as _nf
                    nid_ = _find_node(tree, step["all_under"])
                    if nid_ is None:
                        raise RuntimeError(f"welllog_expect: no node {step['all_under']!r}")
                    logs_ = sorted({tree.find_title(c_) for c_, _k in tree.iter_nodes(nid_)
                                    if c_ != nid_ and _nf.is_property_kind(tree.find_type(c_) or "")})
                    missing_ = [n_ for n_ in logs_ if n_ not in drawn_]
                    _log(out, f"log view: {len(logs_) - len(missing_)} of the {len(logs_)} logs under the node drawn")
                    if missing_ or not logs_:
                        raise RuntimeError(f"welllog_expect: logs under the node not drawn: {missing_}")

            elif op == "values_cursor":
                # The log view's cursor on a measured depth of a well, over the column of `curves`: the Values view
                # marks the nearest row of the log it reads when that log is one of them, none otherwise ("none")
                # — {"op":"values_cursor","well":"<wellbore title>","md":2000,"curves":["GR"]}
                vid = _render_vid(server, state)
                md_ = float(step["md"])
                with state:
                    controller.welllog_cursor({"well": step["well"], "depths": [{"ref": "MD", "value": md_}],
                                               "curves": list(step.get("curves") or [])})
                await asyncio.sleep(float(step.get("settle", 1)))
                page_ = (state.to_dict().get("ui_node_values_by_view") or {}).get(vid) or {}
                cols_ = page_.get("columns") or []
                cur_ = page_.get("cursor")
                if "MD" not in cols_:
                    raise RuntimeError(f"values_cursor: the Values page reads no MD: {cols_}")
                if step.get("none"):
                    _log(out, f"values cursor ({vid}): md {md_} over {step.get('curves')} -> row {cur_}")
                    if cur_ is not None:
                        raise RuntimeError("values_cursor: a row is marked from another log's column")
                else:
                    k_ = cols_.index("MD")
                    row_ = next((r_ for r_ in page_.get("rows") or () if r_[0] == cur_), None)
                    mds_ = [r_[k_] for r_ in page_.get("rows") or () if r_[k_] is not None]
                    _log(out, f"values cursor ({vid}): md {md_} -> row {cur_} at MD {row_[k_] if row_ else None}"
                              f" (page from {page_.get('offset')}, {len(mds_)} rows)")
                    if row_ is None or any(abs(m_ - md_) < abs(row_[k_] - md_) - 1e-9 for m_ in mds_):
                        raise RuntimeError("values_cursor: the row marked is not the nearest on its page")

            elif op == "camera_expect":
                # Where the render view's camera looks: "north" level with Z
                # up (the side look a view of wells starts with), "down" from
                # above — {"op":"camera_expect","looks":"north"}
                vid = _render_vid(server, state)
                cam_ = mv.get_pv_view(vid).GetActiveCamera()
                dop_ = [round(v, 3) for v in cam_.GetDirectionOfProjection()]
                up_ = [round(v, 3) for v in cam_.GetViewUp()]
                _log(out, f"camera ({vid}): looks {dop_}, up {up_}")
                want_ = {"north": ((0, 1, 0), (0, 0, 1)), "down": ((0, 0, -1), None)}[step["looks"]]
                if (any(abs(dop_[i] - want_[0][i]) > 0.01 for i in range(3))
                        or (want_[1] is not None and any(abs(up_[i] - want_[1][i]) > 0.01 for i in range(3)))):
                    raise RuntimeError(f"camera_expect: the camera does not look {step['looks']}:"
                                       f" looks {dop_}, up {up_}")

            elif op == "check_kinds":
                # Tick every node of the given kinds at once — the tree's
                # bulk "load all surfaces" — through `selected_paths`, the
                # widget's own variable: {"op":"check_kinds","kinds":[...]}
                kinds = set(step.get("kinds") or [])
                asm = tree._data_assembly
                paths, stack = [], [0]
                while stack:
                    nid = stack.pop()
                    if (tree.find_type(nid) or "") in kinds:
                        path = tree.find_path(nid)
                        if path:
                            paths.append(path)
                    stack.extend(asm.GetChildNodes(nid))
                _log(out, f"check_kinds {sorted(kinds)}: {len(paths)} nodes")
                with state:
                    cur = list(getattr(state, "selected_paths", None) or [])
                    wanted = cur + [q for q in paths if q not in cur]
                    if step.get("raw"):
                        # the data tree's OWN gesture (as check_raw): the
                        # read is not "decided" by the server, so a big one
                        # goes in steps (engine/progressive_load) — the
                        # confirmation box, if any, is answered yes
                        state.selected_paths = wanted
                        state.dirty("selected_paths")
                    else:
                        controller.select_paths(wanted)
                if step.get("raw"):
                    ask = getattr(state, "ui_tick_confirm", None) or {}
                    _log(out, f"check_kinds raw: asked={ask.get('title')!r}")
                    if ask:
                        with state:
                            controller.tick_confirm_answer(True)

            elif op == "set":
                with state:
                    setattr(state, step["var"], step["value"])
                    state.dirty(step["var"])

            elif op == "narrow_color_range":
                # Narrow the Colormap card's range of the render view to
                # fractions of the range it shows now, through the card's own
                # controller (cmap_range), and check the card follows:
                # {"op":"narrow_color_range","fraction":[0.25,0.75]}
                cvid = _render_vid(server, state)
                card = dict(getattr(state, f"ui_colormap__{cvid}", None) or {})
                lo, hi = card.get("min"), card.get("max")
                if lo is None or hi is None or not float(hi) > float(lo):
                    raise RuntimeError(f"narrow_color_range: the Colormap card of {cvid} shows"
                                       f" no range to narrow ({lo!r}, {hi!r})")
                frac = step.get("fraction", [0.25, 0.75])
                want = [float(lo) + frac[0] * (float(hi) - float(lo)),
                        float(lo) + frac[1] * (float(hi) - float(lo))]
                with state:
                    controller.cmap_range(want, cvid)
                card = dict(getattr(state, f"ui_colormap__{cvid}", None) or {})
                got = [card.get("min"), card.get("max")]
                tol = 1e-6 * max(1.0, abs(want[1] - want[0]))
                if None in got or any(abs(float(g) - w) > tol for g, w in zip(got, want)):
                    raise RuntimeError(f"narrow_color_range: asked {want}, the card shows {got}")
                _log(out, f"narrow_color_range ({cvid}): {want}")

            elif op == "subrep_eye_probe":
                # A SubRepresentation (the plugin types it "Sub") has an eye,
                # and the eye shows or hides it: the data tree offers the eye
                # on its kind, the view's eye set holds it or not, the
                # assembly index knows its datasets, the view's composite
                # shows its block or not ({"visible": true | false})
                from fespp_on_trame.app.views.widgets import data_tree as _dt
                kind = step.get("type", "Sub")
                want = bool(step.get("visible", True))
                nid = _find_node(tree, {"type": kind})
                if nid is None:
                    raise RuntimeError(f"subrep_eye_probe: no node of the kind {kind!r} in this file")
                path = tree.find_path(nid)
                vid = _render_vid(server, state)
                problems = []
                if kind not in _dt._REP_TYPES:
                    problems.append(f"the data tree offers no eye on the kind {kind!r}")
                if path not in (getattr(state, "selected_paths", None) or []):
                    problems.append("it is not ticked")
                eyed = path in (getattr(state, f"visible_paths__{vid}", None) or [])
                if eyed != want:
                    problems.append("its eye is " + ("closed" if want else "open") + " in the view's eye set")
                idx = getattr(server.context, "assembly_index", None)
                n = len(idx.datasets(path)) if idx is not None else 0
                if not n:
                    problems.append("the assembly index knows no dataset of it")
                scene = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid)
                sel = idx.selector_for(path) if idx is not None else path
                shown = scene is not None and sel in scene.visible_selectors()
                if shown != want:
                    problems.append("the view's composite " + ("does not show" if want else "still shows")
                                    + " its block")
                _log(out, f"subrep_eye_probe {path} (visible={want}): {n} dataset(s),"
                          f" problems: {'; '.join(problems) or 'none'}")
                if problems:
                    raise RuntimeError("subrep_eye_probe: " + "; ".join(problems))

            elif op == "stats_support_probe":
                # The Statistics view's row for a part of a grid: the first
                # node of the kind `type` (a ticked sub-representation, by
                # default) read under the first property of the kind
                # `property` of its grid ({"type": "Sub", "property":
                # "ContinuousProperty"}): the matrix holds a row on the part,
                # with values, and never more of them than the property's own
                # row — or {"part": "session://view_1/x1", "property_title":
                # "Facies"}: an extract's row; "publish": false reads the rows
                # as the app last published them (a rename must refresh them
                # by itself); "expect_label" a text the row must carry
                import json as _json
                part_nid = (None if step.get("part")
                            else _find_node(tree, {"type": step.get("type", "Sub")}))
                prop_nid = _find_node(tree, ({"title": step["property_title"]} if step.get("property_title")
                                             else {"type": step.get("property", "ContinuousProperty")}))
                if (part_nid is None and not step.get("part")) or prop_nid is None:
                    raise RuntimeError("stats_support_probe: no part or no property in this file")
                part = step.get("part") or tree.find_path(part_nid)
                prop = tree.find_path(prop_nid)
                if step.get("publish", True):
                    rvid = _render_vid(server, state)
                    with state:
                        controller.add_to_stats(prop)
                        state.ui_compare_parts = [part]
                        # the view opens in front: the scenario goes on in its 3D view
                        state.fespp_active_panel_id = rvid
                        state.dirty("fespp_active_panel_id")

                def _rows_of():
                    rows_ = list((getattr(state, "ui_compare_rows", None) or {}).values())
                    return ([r for r in rows_ if r.get("path") == prop and not r.get("support")],
                            next((r for r in rows_ if r.get("support") == part), None))

                # the rows come behind the view's bar, and a name after its rename
                waited = 0.0
                orig, sup = _rows_of()
                while waited < 60.0 and (
                        sup is None or _heavy_pending(controller)
                        or (step.get("expect_label") and step["expect_label"] not in _json.dumps(sup, default=str))):
                    await asyncio.sleep(0.25)
                    waited += 0.25
                    orig, sup = _rows_of()
                orig = orig[0] if orig else {}
                metrics = (sup or {}).get("metrics") or {}
                _log(out, f"stats_support_probe {part} under {prop}: own row n="
                          f"{(orig.get('metrics') or {}).get('Cardinality')}, part's n={metrics.get('Cardinality')},"
                          f" label: {(sup or {}).get('support_label')!r}, note: {(sup or {}).get('note')!r}")
                if sup is None:
                    raise RuntimeError(f"stats_support_probe: no row for {part} under {prop}")
                if not (metrics.get("Cardinality") or 0) > 0:
                    raise RuntimeError("stats_support_probe: the part's row holds no value")
                if orig and metrics["Cardinality"] > ((orig.get("metrics") or {}).get("Cardinality") or 0):
                    raise RuntimeError("stats_support_probe: the part has more values than its grid")
                if step.get("expect_label") and step["expect_label"] not in _json.dumps(sup, default=str):
                    raise RuntimeError(f"stats_support_probe: the row does not say"
                                       f" {step['expect_label']!r}: {_json.dumps(sup, default=str)[:200]}")

            elif op == "expect":
                # Check a state var after the gesture before it — a step that
                # verifies, where a dump only logs:
                # {"op":"expect","var":"ui_colormap__{vid}","key":"below",
                #  "equals":"#0000ff"}
                # "{vid}" in the name is the render view's id; "key" is one
                # key or a list of nested keys; then "equals", "contains" (an
                # item of a list, or a substring), "truthy": true, "missing"
                # (a key the dict must not hold, e.g. "error"), "size_ge" (at
                # least that many items), "size" (that many, no more)
                name = str(step["var"]).replace("{vid}", _render_vid(server, state) or "")
                val = getattr(state, name, None)
                where = name
                keys = step.get("key", [])
                for k in (keys if isinstance(keys, list) else [keys]):
                    where += f".{k}"
                    # an integer key is an item of a list (a row of the tree)
                    if isinstance(val, list) and isinstance(k, int):
                        val = val[k] if -len(val) <= k < len(val) else None
                    else:
                        val = val.get(k) if isinstance(val, dict) else None
                if "equals" in step and val != step["equals"]:
                    raise RuntimeError(f"expect {where}: {val!r}, not {step['equals']!r}")
                if "contains" in step and (val is None or step["contains"] not in val):
                    raise RuntimeError(f"expect {where}: {val!r} does not hold {step['contains']!r}")
                if step.get("truthy") and not val:
                    raise RuntimeError(f"expect {where}: {val!r} is empty")
                if "size_ge" in step and len(val or ()) < int(step["size_ge"]):
                    raise RuntimeError(f"expect {where}: {len(val or ())} item(s), not at least"
                                       f" {step['size_ge']}: {val!r}")
                if "size" in step and len(val or ()) != int(step["size"]):
                    raise RuntimeError(f"expect {where}: {len(val or ())} item(s), not {step['size']}: {val!r}")
                # a number between bounds: "gt" / "lt" (strict)
                if "gt" in step and not (isinstance(val, (int, float)) and val > step["gt"]):
                    raise RuntimeError(f"expect {where}: {val!r}, not above {step['gt']!r}")
                if "lt" in step and not (isinstance(val, (int, float)) and val < step["lt"]):
                    raise RuntimeError(f"expect {where}: {val!r}, not below {step['lt']!r}")
                if "missing" in step and isinstance(val, dict) and step["missing"] in val:
                    raise RuntimeError(f"expect {where}: holds {step['missing']!r} = {val[step['missing']]!r}")
                _log(out, f"expect {where}: ok")

            elif op == "call":
                # Invoke a registered controller method: {"op":"call",
                # "method":"slicer_mode","args":["slice","view_1"]}; an arg
                # {"title": ...} resolves to that node's path
                fn = getattr(controller, step["method"])
                with state:
                    fn(*_resolve_args(tree, step.get("args", []), state))

            elif op == "memory":
                # Where the memory stands, logged under a label: what malloc
                # holds (a leak makes it grow) and the process's memory, once
                # what was freed is given back. With "since" (an earlier
                # label) and "max_growth" (MiB) the step fails when what
                # malloc holds grew by more since then — a leak over cycles:
                # {"op":"memory","label":"cycle 4","since":"cycle 2","max_growth":25}
                from fespp_on_trame.engine import memory as _memory
                _memory.give_back()
                held_, proc_ = _memory.held_mib(), _memory.process_mib()
                if held_ is None or proc_ is None:
                    raise RuntimeError("memory: not readable on this system")
                _MEMORY_MARKS[step.get("label", "")] = held_
                _log(out, f"memory {step.get('label', '')}: held {held_:.0f} MiB, process {proc_:.0f} MiB")
                if step.get("objects"):
                    # the Python objects alive, by type, and those whose
                    # number grew most since the last step that counted them
                    import collections as _collections
                    import gc as _gc
                    now_ = _collections.Counter(type(o).__name__ for o in _gc.get_objects())
                    before_ = _MEMORY_MARKS.get("__types__")
                    _MEMORY_MARKS["__types__"] = now_
                    _log(out, f"memory: {sum(now_.values())} Python objects")
                    if before_ is not None:
                        grown_ = sorted(((n - before_.get(k, 0), k) for k, n in now_.items()), reverse=True)[:8]
                        _log(out, "memory: grew most: " + ", ".join(f"{k} {d:+d}" for d, k in grown_ if d > 0))
                if "max_growth" in step:
                    since_ = _MEMORY_MARKS.get(step.get("since"))
                    if since_ is None:
                        raise RuntimeError(f"memory: no earlier step labelled {step.get('since')!r}")
                    _log(out, f"memory: {held_ - since_:+.0f} MiB held since {step['since']}")
                    if held_ - since_ > float(step["max_growth"]):
                        raise RuntimeError(f"memory: what malloc holds grew by {held_ - since_:.0f} MiB since"
                                           f" {step['since']!r}, more than {step['max_growth']} MiB")

            elif op == "memory_sources":
                # What each pipeline object's output holds (VTK's own count, KiB:
                # an array shared by two outputs is counted in both), the
                # largest first, and one leaf of the largest composite looked
                # into: its points, cells and arrays.
                # {"op":"memory_sources","top":12}
                rows_ = []
                for (n_, _i), s_ in pvsimple.GetSources().items():
                    try:
                        d_ = s_.GetClientSideObject().GetOutputDataObject(0)
                    except Exception as exc:
                        _log(out, f"memory of {n_}: not read ({exc})")
                        continue
                    if d_ is None:
                        continue
                    leaves_ = 0
                    if hasattr(d_, "NewIterator"):
                        it_ = d_.NewIterator()
                        it_.InitTraversal()
                        while not it_.IsDoneWithTraversal():
                            leaves_ += 1
                            it_.GoToNextItem()
                    rows_.append((d_.GetActualMemorySize(), n_, d_.GetClassName(), leaves_, d_))
                rows_.sort(key=lambda r_: -r_[0])
                _log(out, f"memory of the pipeline: {sum(r_[0] for r_ in rows_) / 1024:.0f} MiB over {len(rows_)} object(s)")
                def _first_arrays(d_):
                    # the address of the largest leaf's points and first point array: two
                    # outputs giving the same ones share them (a shallow copy), else they copy
                    if not hasattr(d_, "NewIterator"):
                        return "-"
                    it_ = d_.NewIterator()
                    it_.SetVisitOnlyLeaves(True)
                    it_.InitTraversal()
                    best_ = None
                    while not it_.IsDoneWithTraversal():
                        l_ = it_.GetCurrentDataObject()
                        if best_ is None or l_.GetNumberOfPoints() > best_.GetNumberOfPoints():
                            best_ = l_
                        it_.GoToNextItem()
                    if best_ is None or not hasattr(best_, "GetPoints") or best_.GetPoints() is None:
                        return "-"
                    a_ = best_.GetPointData().GetArray(0) if best_.GetPointData().GetNumberOfArrays() else None
                    return (best_.GetPoints().GetData().GetAddressAsString("")[-8:] + "/"
                            + (a_.GetAddressAsString("")[-8:] if a_ is not None else "-"))
                for kb_, n_, cls_, leaves_, d_ in rows_[:int(step.get("top", 12))]:
                    _log(out, f"  {kb_ / 1024:8.0f} MiB  {n_[:60]}  {cls_}  {leaves_} leaf(s)  arrays {_first_arrays(d_)}")
                # what the views' representations hold of their own
                for r_ in pvsimple.GetActiveView().Representations if pvsimple.GetActiveView() is not None else ():
                    try:
                        co_ = r_.GetClientSideObject()
                        rd_ = co_.GetRenderedDataObject(0) if hasattr(co_, "GetRenderedDataObject") else None
                        if rd_ is not None and rd_.GetActualMemorySize() > 50 * 1024:
                            _log(out, f"  representation {r_.GetXMLName()}: rendered data {rd_.GetActualMemorySize() / 1024:.0f} MiB"
                                      f"  arrays {_first_arrays(rd_)}")
                    except Exception as exc:
                        _log(out, f"  representation not read ({exc})")
                if rows_ and hasattr(rows_[0][4], "NewIterator"):
                    it_ = rows_[0][4].NewIterator()
                    it_.SetVisitOnlyLeaves(True)
                    it_.InitTraversal()
                    big_ = []
                    while not it_.IsDoneWithTraversal():
                        l_ = it_.GetCurrentDataObject()
                        big_.append((l_.GetActualMemorySize(), l_))
                        it_.GoToNextItem()
                    big_.sort(key=lambda r_: -r_[0])
                    for kb_, l_ in big_[:3]:
                        pd_ = l_.GetPointData() if hasattr(l_, "GetPointData") else None
                        arrs_ = [(pd_.GetArrayName(k_), pd_.GetArray(k_).GetNumberOfComponents(),
                                  pd_.GetArray(k_).GetDataTypeAsString()) for k_ in range(pd_.GetNumberOfArrays())] if pd_ else []
                        _log(out, f"  leaf {kb_ / 1024:.1f} MiB: {l_.GetClassName()} {l_.GetNumberOfPoints()} points"
                                  f" {l_.GetNumberOfCells()} cells, {len(arrs_)} point array(s) {arrs_[:6]}")

            elif op == "symbols_cost":
                # What laying the graphs again for a new screen's right costs (the camera turned, a well plumb all
                # along in view): the view's well symbols filter as it is, then a filter of its graphs that face
                # the screen alone. {"op":"symbols_cost"}
                import time as _time
                from fespp_on_trame.engine.sources.representation import _create_plugin_filter_proxy
                vid_ = _render_vid(server, state)
                flt_ = pvsimple.FindSource(f"fesppWellGraphs_{vid_}")
                if flt_ is None:
                    raise RuntimeError("symbols_cost: the view has no filter of its graphs")
                sels_ = [s_ for s_ in flt_.GraphSelectors if not s_.startswith("/__")]
                out_ = flt_.GetClientSideObject().GetOutputDataObject(0)
                asm_ = out_.GetDataAssembly()
                facing_ = []
                for s_ in sels_:
                    for n_ in asm_.SelectNodes([f"{s_}/strip"]):
                        for ix_ in asm_.GetDataSetIndices(n_):
                            b_ = out_.GetPartition(ix_, 0) if out_.GetNumberOfPartitions(ix_) else None
                            if b_ is not None and b_.GetFieldData().GetArray("LogFacesScreen") is not None:
                                facing_.append(s_)

                def _relay_cost(f_):
                    was_ = [float(v_) for v_ in f_.ScreenRight]
                    t0_ = _time.perf_counter()
                    f_.ScreenRight = [was_[1], -was_[0], was_[2]]
                    f_.UpdatePipeline()
                    took_ = _time.perf_counter() - t0_
                    f_.ScreenRight = was_
                    f_.UpdatePipeline()
                    return took_

                whole_ = _relay_cost(flt_)
                part_ = None
                if facing_:
                    tmp_ = _create_plugin_filter_proxy(proxy_class="EnergisticsWellSymbols",
                                                       registration_name=f"fesppSymbolsCost_{vid_}",
                                                       inputs={"Input": flt_.Input})
                    ext_ = list(flt_.GraphExtents)
                    tmp_.PassOtherBlocks = 0
                    tmp_.Selectors = ["/__fespp_no_block__"]
                    tmp_.GraphSelectors = facing_
                    tmp_.CodeSelectors = [c_ for c_ in flt_.CodeSelectors if c_ in facing_] or ["/__fespp_no_block__"]
                    tmp_.GraphExtents = [v_ for k_ in range(0, len(ext_), 2) if ext_[k_] in facing_
                                         for v_ in ext_[k_:k_ + 2]]
                    tmp_.GraphWidth = flt_.GraphWidth
                    tmp_.VerticalExaggeration = flt_.VerticalExaggeration
                    tmp_.ScreenRight = list(flt_.ScreenRight)
                    tmp_.UpdatePipeline()
                    part_ = _relay_cost(tmp_)
                    pvsimple.Delete(tmp_)
                _log(out, f"symbols cost ({vid_}): {len(sels_)} graph(s), {len(facing_)} facing the screen;"
                          f" laid again for a new screen's right: the whole filter {whole_ * 1000:.0f} ms,"
                          f" a filter of the facing ones alone {part_ * 1000 if part_ is not None else 0:.0f} ms")

            elif op == "flight_time":
                # A tree's "Centre / Zoom the 3D view on <node>" timed: from the call to the last frame
                # of the camera's flight, the frames drawn and their time, and how many times the
                # view's log graphs were laid again on the way.
                # {"op":"flight_time","title":"...","under":"...","zoom":false,"max_s":1.5}
                import time as _time
                from paraview import simple as _pvs
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                frames_, laid_ = [], []
                started_ = {}

                def _start_(*_a):
                    started_["t"] = _time.monotonic()

                def _end_(*_a):
                    frames_.append((_time.monotonic(), _time.monotonic() - started_.get("t", _time.monotonic())))

                obs_ = [pvv_.SMProxy.AddObserver("StartEvent", _start_), pvv_.SMProxy.AddObserver("EndEvent", _end_)]
                graphs_ = _pvs.FindSource(f"fesppWellGraphs_{vid_}")
                alg_ = graphs_.GetClientSideObject() if graphs_ is not None else None
                lay_ = alg_.AddObserver("EndEvent", lambda *_a: laid_.append(1)) if alg_ is not None else None

                def _cam_():
                    c_ = pvv_.GetActiveCamera()
                    return tuple(round(v, 6) for v in tuple(c_.GetPosition()) + tuple(c_.GetFocalPoint()))

                t0_ = _time.monotonic()
                with state:
                    controller.nav_frame_node(_resolve_args(tree, [{"title": step["title"], "under": step.get("under")}], state)[0],
                                              None, bool(step.get("zoom")))
                last_, still_ = _cam_(), _time.monotonic()
                while _time.monotonic() - t0_ < 60:
                    # no browser here to ask for the frames: each camera step is drawn as its push would
                    # draw it (the view proxy's still render, whose StartEvent the log graphs listen to)
                    await asyncio.sleep(0.01)
                    now_ = _cam_()
                    if now_ != last_:
                        last_, still_ = now_, _time.monotonic()
                        pvv_.SMProxy.StillRender()
                    elif _time.monotonic() - still_ > 1.5:
                        break
                for o_ in obs_:
                    pvv_.SMProxy.RemoveObserver(o_)
                if lay_ is not None:
                    alg_.RemoveObserver(lay_)
                end_ = frames_[-1][0] if frames_ else still_
                took_ = end_ - t0_
                mean_ = sum(d for _t, d in frames_) / len(frames_) * 1000 if frames_ else 0.0
                _log(out, f"flight ({vid_}, {'zoom' if step.get('zoom') else 'centre'} on {step['title']}):"
                          f" {took_:.2f} s to the last frame, {len(frames_)} frames of {mean_:.0f} ms on average,"
                          f" the log graphs laid again {len(laid_)} times"
                          f" ({'no graph filter' if alg_ is None else 'graph filter watched'})")
                if step.get("max_s") is not None and took_ > float(step["max_s"]):
                    raise RuntimeError(f"flight: {took_:.2f} s, over {step['max_s']} s")

            elif op == "render_load":
                # What a frame of the 3D view draws: per visible representation, the cells and points of
                # its data and the polygons of its surface (what the renderer draws), then the time of a
                # still frame (best of 3). {"op":"render_load"}
                import time as _time
                from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter as _GF
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                polys_total_ = 0
                for rep_ in pvv_.Representations:
                    if not getattr(rep_, "Visibility", 0) or not hasattr(rep_, "Input") or rep_.Input is None:
                        continue
                    try:
                        d_ = rep_.Input.GetClientSideObject().GetOutputDataObject(0)
                    except Exception:  # noqa: BLE001 — a representation with no data object: nothing drawn
                        continue
                    if d_ is None:
                        continue
                    leaves_ = []
                    if hasattr(d_, "NewIterator"):
                        it_ = d_.NewIterator()
                        it_.InitTraversal()
                        while not it_.IsDoneWithTraversal():
                            leaves_.append(it_.GetCurrentDataObject())
                            it_.GoToNextItem()
                    else:
                        leaves_ = [d_]
                    cells_ = points_ = polys_ = 0
                    for leaf_ in leaves_:
                        if leaf_ is None or not hasattr(leaf_, "GetNumberOfCells"):
                            continue
                        cells_ += leaf_.GetNumberOfCells()
                        points_ += leaf_.GetNumberOfPoints()
                        g_ = _GF()
                        g_.SetInputData(leaf_)
                        g_.Update()
                        polys_ += g_.GetOutput().GetNumberOfCells()
                    polys_total_ += polys_
                    colour_ = list(getattr(rep_, "ColorArrayName", []) or [])
                    lut_ = getattr(rep_, "LookupTable", None)
                    paint_ = (f"coloured by {colour_[1]} ({colour_[0]}), lut nan opacity"
                              f" {getattr(lut_, 'NanOpacity', '?')}, opacity mapping"
                              f" {getattr(lut_, 'EnableOpacityMapping', '?')}, interpolate before mapping"
                              f" {getattr(rep_, 'InterpolateScalarsBeforeMapping', '?')}"
                              if len(colour_) > 1 and colour_[1] else "solid colour")
                    _log(out, f"render load ({vid_}): {rep_.Input.GetXMLLabel() if hasattr(rep_.Input, 'GetXMLLabel') else '?'}"
                              f" {len(leaves_)} block(s), {cells_} cells, {points_} points, {polys_} surface polygons,"
                              f" {paint_}, opacity {getattr(rep_, 'Opacity', '?')}, {getattr(rep_, 'Representation', '?')}")
                times_ = []
                for _k in range(3):
                    t0_ = _time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    times_.append((_time.perf_counter() - t0_) * 1000)
                _log(out, f"render load ({vid_}): {polys_total_} surface polygons in all, a still frame"
                          f" {min(times_):.0f} ms (best of 3)")
                # the colour tables: their opacity curve, whether VTK draws them as opaque, and with
                # "try_opaque": true the frame again with the opacity mapping off (then put back)
                for rep_ in pvv_.Representations:
                    lut_ = getattr(rep_, "LookupTable", None)
                    if not getattr(rep_, "Visibility", 0) or lut_ is None:
                        continue
                    pwf_ = getattr(lut_, "ScalarOpacityFunction", None)
                    try:
                        opaque_ = lut_.GetClientSideObject().IsOpaque()
                    except Exception:  # noqa: BLE001 — a table with no client object: not said
                        opaque_ = "?"
                    _log(out, f"render load ({vid_}): colour table opaque for VTK: {opaque_}, opacity curve"
                              f" {list(pwf_.Points) if pwf_ is not None else None}")
                    if step.get("try_translucent") and not int(getattr(lut_, "EnableOpacityMapping", 0)):
                        # the other way: the mapping turned on over the same opaque curve, frames timed
                        for round_ in range(2):
                            for on_ in (1, 0):
                                lut_.EnableOpacityMapping = on_
                                pvv_.SMProxy.StillRender()
                                times_ = []
                                for _k in range(5):
                                    t0_ = _time.perf_counter()
                                    pvv_.SMProxy.StillRender()
                                    times_.append((_time.perf_counter() - t0_) * 1000)
                                _log(out, f"render load ({vid_}): round {round_ + 1}, opacity mapping {on_},"
                                          f" a still frame {min(times_):.0f} ms (best of 5)")
                    if step.get("try_opaque") and int(getattr(lut_, "EnableOpacityMapping", 0)):
                        lut_.EnableOpacityMapping = 0
                        times_ = []
                        for _k in range(3):
                            t0_ = _time.perf_counter()
                            pvv_.SMProxy.StillRender()
                            times_.append((_time.perf_counter() - t0_) * 1000)
                        _log(out, f"render load ({vid_}): opacity mapping off, a still frame {min(times_):.0f} ms")
                        lut_.EnableOpacityMapping = 1
                        pvv_.SMProxy.StillRender()
            elif op == "turn_cost":
                # A camera turned, phase by phase: the graphs' filter laid again for the new screen's right, each
                # graph's extract made again from it, the frame drawn. {"op":"turn_cost"}
                import time as _time
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                g_ = pvsimple.FindSource(f"fesppWellGraphs_{vid_}")
                if g_ is None:
                    raise RuntimeError("turn_cost: the view has no filter of its graphs")
                exts_ = [s_ for (n_, _i), s_ in pvsimple.GetSources().items() if n_.startswith(f"fesppLogGraphs_{vid_}_")]
                was_ = [float(v_) for v_ in g_.ScreenRight]
                t0_ = _time.perf_counter()
                g_.ScreenRight = [was_[1], -was_[0], was_[2]]
                g_.UpdatePipeline()
                t1_ = _time.perf_counter()
                for e_ in exts_:
                    e_.UpdatePipeline()
                t2_ = _time.perf_counter()
                pvv_.SMProxy.StillRender()
                t3_ = _time.perf_counter()
                pvv_.SMProxy.StillRender()
                t4_ = _time.perf_counter()
                _log(out, f"turn cost ({vid_}): the graphs' filter {(t1_ - t0_) * 1000:.0f} ms, {len(exts_)} extract(s)"
                          f" {(t2_ - t1_) * 1000:.0f} ms, the frame {(t3_ - t2_) * 1000:.0f} ms, a frame again"
                          f" {(t4_ - t3_) * 1000:.0f} ms")
                g_.ScreenRight = was_
                g_.UpdatePipeline()
                pvv_.SMProxy.StillRender()
                if step.get("no_lod"):
                    # the same with the view's lighter geometry for the frames of a move never made
                    lod_ = pvv_.LODThreshold
                    pvv_.LODThreshold = 1e9
                    pvv_.SMProxy.StillRender()
                    t0_ = _time.perf_counter()
                    g_.ScreenRight = [was_[1], -was_[0], was_[2]]
                    g_.UpdatePipeline()
                    t1_ = _time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    t2_ = _time.perf_counter()
                    _log(out, f"turn cost ({vid_}), no LOD (threshold {lod_} -> 1e9): the graphs' filter"
                              f" {(t1_ - t0_) * 1000:.0f} ms, the frame {(t2_ - t1_) * 1000:.0f} ms")
                    pvv_.LODThreshold = lod_
                    g_.ScreenRight = was_
                    g_.UpdatePipeline()

            elif op == "welllog_kind_eye":
                # An eye on a property kind's folder in the log view's tree ("Prop. kind" layout): the logs of that
                # kind the session holds, as the widget sends them. {"op":"welllog_kind_eye","kind":"Rock Impedance"}
                from fespp_on_trame.engine import node_facts as _nf
                pids_ = list(mv.panel_ids_of_kind("welllog")) if mv is not None else []
                if not pids_:
                    raise RuntimeError("welllog_kind_eye: no log view")
                want_ = str(step["kind"]).lower()
                held_ = set(getattr(state, "ui_loaded_array_paths", None) or [])
                leaves_, kinds_ = [], set()
                for nid_, _k in tree.iter_nodes():
                    p_ = tree.find_path(nid_)
                    if not p_ or p_ not in held_ or not _nf.is_log(tree, p_):
                        continue
                    kind_of_ = getattr(server.context, "property_kind_of", None)
                    kind_ = str((kind_of_(nid_) if kind_of_ is not None else None)
                                or tree.find_attribute_value(nid_, "propertyKind") or "")
                    kinds_.add(kind_)
                    if kind_.lower() == want_:
                        leaves_.append(p_)
                _log(out, f"welllog kind eye: {len(leaves_)} log(s) of {step['kind']!r}; kinds held: {sorted(kinds_)[:20]}")
                if not leaves_:
                    raise RuntimeError(f"welllog_kind_eye: no log of the kind {step['kind']!r}")
                with state:
                    controller.panel_tree_eye(pids_[0], {"path": "layout://kind/" + str(step["kind"]), "paths": leaves_,
                                                         "visible": True, "n": i}, "welllog")
                await asyncio.sleep(float(step.get("settle", 10)))

            elif op == "trigger":
                # A CLIENT trigger by name, through the controller's registry
                # — the button's own path: {"op":"trigger","name":"<its name>",
                # "args":[{"title":"GasSat","under":"GasSat"},"ts"]}
                fn = server.controller._triggers.get(step["name"])
                if fn is None:
                    raise RuntimeError(f"trigger not registered: {step['name']!r}")
                with state:
                    fn(*_resolve_args(tree, step.get("args", []), state))

            elif op == "stats_probe":
                # what the Statistics view holds for the property titled
                # `title`: its entries in the selection, its rows, the time
                # steps and realizations a row offers; "rows": how many rows it
                # must have
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                path = tree.find_path(nid)
                snap = state.to_dict()
                held = [it for it in (snap.get("ui_compare_items") or []) if it.get("path") == path]
                rows_ = [r for r in (snap.get("ui_compare_rows") or {}).values() if r.get("path") == path]
                own = next((r for r in rows_ if not r.get("support") and not r.get("pinned")), {})
                _log(out, f"stats {step['title']!r} type={tree.find_type(nid)!r}:"
                          f" items={len(held)} pinned={sum(1 for it in held if it.get('pinned'))}"
                          f" rows={len(rows_)}"
                          f" available_ts={len(own.get('ts_opts') or [])}"
                          f" available_real={len(own.get('reals') or [])}")
                # the three means side by side, what the row says about the
                # weights it could or could not get, and whether a Sum of it
                # means anything (not on a fraction)
                for r in rows_[:2]:
                    m = r.get("metrics") or {}
                    _log(out, f"  row {r.get('label')!r}:"
                              f" Cardinality={m.get('Cardinality')}"
                              f" Mean={m.get('Mean')!r}"
                              f" Mean (V)={m.get('Mean (V)')!r}"
                              f" Mean (PV)={m.get('Mean (PV)')!r}"
                              f" uom={r.get('uom')!r}"
                              f" sum_meaningful={r.get('sum_meaningful')!r}"
                              f" note={r.get('note')!r}")
                    # the cell percentiles and the moments every row carries
                    vals = [m.get(k) for k in ("P10", "Q1", "Median", "Q3", "P90")]
                    _log(out, f"    P10..P90={vals!r} M2={m.get('M2')!r}"
                              f" M3={m.get('M3')!r} M4={m.get('M4')!r}")
                    if all(isinstance(v, (int, float)) for v in vals):
                        if not (vals[0] <= vals[1] <= vals[2] <= vals[3] <= vals[4]):
                            raise RuntimeError("stats_probe: percentiles out of order")
                    elif m.get("Cardinality", 0) > 0:
                        raise RuntimeError("stats_probe: a row without its percentiles")
                if own and not isinstance(own.get("sum_meaningful"), bool):
                    raise RuntimeError("stats_probe: the row does not say whether its Sum means anything")
                if "rows" in step and len(rows_) != int(step["rows"]):
                    raise RuntimeError(f"stats_probe: {len(rows_)} rows, not {step['rows']}")

            elif op == "panel_tree_probe":
                # The grammar shared by the trees, asserted where the engine
                # can see it: a tick in a panel's tree puts the object IN THAT
                # PANEL (the log fills, the Statistics view has its row, whatever
                # panel is active), and an eye is offered on what the session
                # holds, not on what the panel holds.
                mv = getattr(server.context, "multi_view", None)
                if mv is None:
                    raise RuntimeError("no view manager")

                def _expect(cond, what):
                    _log(out, f"  {'OK ' if cond else 'FAIL'} {what}")
                    if not cond:
                        raise RuntimeError(f"panel_tree_probe: {what}")

                async def _settled():
                    waited = 0.0
                    while waited < 120.0 and _heavy_pending(controller):
                        await asyncio.sleep(0.05)
                        waited += 0.05

                rvid = _render_vid(server, state)
                with state:
                    controller.open_welllog()
                    controller.open_compare()
                wl = (mv.panel_ids_of_kind("welllog") or [""])[0]
                sv = (mv.panel_ids_of_kind("compare") or [""])[0]
                if not wl or not sv:
                    raise RuntimeError(f"panels missing: welllog={wl!r} statistics={sv!r}")
                _log(out, f"panels: welllog={wl!r} statistics={sv!r} render={rvid!r}")

                def _held():
                    return [it.get("path") for it in (getattr(state, "ui_compare_items", None) or [])]

                # The door before anything is ticked: an eye is gated on what
                # a 3D view could show, so a freshly opened tree with nothing
                # of its own must already offer some.
                with state:
                    controller.panel_tree_eyes(wl, "welllog")
                snap = state.to_dict()
                _log(out, "eyeable with nothing ticked:"
                          f" welllog={len(snap.get(f'welllog_tree_shown__{wl}') or [])}"
                          f" statistics={len(snap.get(f'compare_tree_shown__{sv}') or [])}"
                          f" held={len(snap.get(f'compare_tree_selected__{sv}') or [])}")
                # A tick in the LOG tree: the wellbore goes in the LOG.
                asm = tree._data_assembly
                stack, wid = [0], None
                while stack:
                    nid = stack.pop(0)
                    if (tree.find_type(nid) or "") == "Wellbore":
                        wid = nid
                        break
                    stack.extend(asm.GetChildNodes(nid))
                if wid is None:
                    raise RuntimeError("no Wellbore node in the tree")
                well_path = tree.find_path(wid)
                # STEPPING BACK, in the Statistics tree, BEFORE anything is
                # read: a tick standing for more than the cap asks, and a no
                # must leave nothing behind. The tree is two-way, so holding a
                # property re-syncs its boxes and that rewrite calls the
                # controller straight back; read as a second gesture, it would
                # pose a second question over the first, and Cancel would run
                # the second one's callbacks, leaving every box ticked and
                # every property held.
                from fespp_on_trame.engine import compare_dispatch as _cd
                from fespp_on_trame.engine import compare_tree as _ct
                from fespp_on_trame.engine import tick_confirm as _tc
                was_read = list(getattr(state, "selected_paths", None) or [])
                folders = {}
                for syn_, real_ in controller.compare_tree_map().items():
                    if not syn_.startswith(_ct.PARTS_FOLDER + "/"):
                        folders.setdefault(syn_.rsplit("/", 2)[0], []).append(real_)
                wide = next((f for f, reals in folders.items()
                             if len([r for r in reals if r not in was_read]) > _tc.MAX_TICK_LOAD), None)
                if wide is None:
                    _log(out, "no kind folder holds more than one tick reads: nothing to ask about")
                else:
                    with state:
                        controller.compare_tree_paths(sv, [wide])
                    ask = getattr(state, "ui_tick_confirm", None) or {}
                    _log(out, f"statistics folder tick: asked={ask.get('title')!r}"
                              f" held_while_asking={len(_held())}")
                    _expect(bool(ask.get("title")),
                            "a tick standing for a whole kind asks first")
                    _expect(not _held(), "nothing is held while the question stands")
                    with state:
                        controller.tick_confirm_answer(False)
                    _log(out, "after Cancel:"
                              f" held={len(_held())}"
                              f" boxes={len(getattr(state, f'compare_tree_selected__{sv}', None) or [])}"
                              f" read={len(getattr(state, 'selected_paths', None) or [])}"
                              f" asking={getattr(state, 'ui_tick_confirm', None)}")
                    _expect(not _held(), "Cancel held nothing")
                    _expect(not (getattr(state, f"compare_tree_selected__{sv}", None) or []),
                            "Cancel put the eyes back")
                    _expect(list(getattr(state, "selected_paths", None) or [])
                            == was_read, "Cancel read nothing")
                    _expect(not (getattr(state, "ui_tick_confirm", None) or {}),
                            "one question, answered once")
                _log(out, f"log tick: {tree.find_title(wid)!r}")
                with state:
                    controller.welllog_tree_wells(wl, [well_path])
                question = getattr(state, "ui_tick_confirm", None) or {}
                if question:
                    _log(out, f"  asked first: {question.get('title')!r}"
                              f" wells_so_far={len(getattr(state, 'ui_welllog_wells', None) or [])}")
                    _expect(not (getattr(state, "ui_welllog_wells", None)
                                 or []),
                            "the log holds nothing while the question stands")
                    with state:
                        controller.tick_confirm_answer(True)
                await asyncio.sleep(4.0)
                snap = state.to_dict()
                payload = snap.get(f"welllog_data__{wl}") or {}
                wells = payload.get("wells") or []
                curves = sum(len(t.get("curves") or [])
                             for w in wells for t in (w.get("tracks") or []))
                _log(out, f"  in the log: {len(snap.get('ui_welllog_wells') or [])}"
                          f" wellbore(s); panel payload: wells={len(wells)}"
                          f" curves={curves}"
                          f" ticks={len(snap.get(f'welllog_tree_selected__{wl}') or [])}")
                _expect(len(snap.get("ui_welllog_wells") or []) == 1,
                        "the ticked wellbore is in the log")
                _expect(curves > 0, "the log draws a curve of the well it holds")
                _expect(not (snap.get(f"welllog_dropped__{wl}") or []),
                        "a tick dropped nothing from the log")
                # What that tick read went in the LOG and in no 3D view:
                # absent from the 3D view's own eye set, and absent from the
                # log panel's id too (a bucket no 3D view reads, where an
                # active-panel lookup would put it). The eye of the panel
                # tree is the door to the scene, checked below.
                read_now = [p for p in (snap.get("selected_paths") or [])
                            if p not in was_read]
                in_view = [p for p in (snap.get(f"visible_paths__{rvid}") or [])
                           if p in read_now]
                strayed = [p for p in (snap.get(f"visible_paths__{wl}") or [])
                           if p in read_now]
                _log(out, f"  born hidden (active panel ="
                          f" {snap.get('fespp_active_panel_id')!r}):"
                          f" read={len(read_now)} in {rvid}={len(in_view)}"
                          f" under the log panel's id={len(strayed)}")
                _expect(read_now, "the log tick read the well")
                _expect(not in_view, "nothing of the log tick's read is shown"
                                     " in the 3D view: a panel tick reads"
                                     " into the panel, the scene is unchanged")
                _expect(not strayed, "nothing of the log tick's read went under"
                                     " the log panel's own id")
                # A tick in the STATISTICS tree gives its row EVEN WHEN the
                # panel is not the active one. Made with the 3D VIEW active, on
                # a property of ANOTHER well the session has not read (else one
                # the log tick read): what it reads is born hidden all the same
                # — a panel tick reads into the panel whichever panel is active.
                _PROPS = ("ContinuousProperty", "DiscreteProperty",
                          "CategoricalProperty")
                read_set = set(snap.get("selected_paths") or [])
                prop = next((p for p in (tree.find_path(n) for n in
                                         tree.find_all_descendant_ids(0))
                             if p and p not in read_set
                             and not p.startswith(well_path + "/")
                             and (tree.find_type(tree.find_node_id(p)) or "")
                             in _PROPS), None) \
                    or next((p for p in (snap.get("selected_paths") or [])
                             if (tree.find_type(tree.find_node_id(p)) or "")
                             in _PROPS), None)
                with state:
                    state.fespp_active_panel_id = rvid
                    state.dirty("fespp_active_panel_id")
                if prop:
                    was_read = list(getattr(state, "selected_paths", None) or [])
                    syn = next((s for s, p in controller.compare_tree_map().items() if p == prop), None)
                    _expect(syn, "the Statistics tree lists the property")
                    with state:
                        if prop in was_read:
                            # read already: its box is ticked, its eye is the door
                            controller.compare_tree_eye(sv, {"path": syn})
                        else:
                            # the checkbox of the tree, as the widget sends it
                            boxes = list(getattr(state, f"compare_tree_loaded__{sv}", None) or [])
                            state.compare_tick = {"vid": sv, "paths": boxes + [syn], "t": i}
                            state.dirty("compare_tick")
                    if getattr(state, "ui_tick_confirm", None) or {}:
                        with state:
                            controller.tick_confirm_answer(True)
                    await asyncio.sleep(4.0)
                    held = _held()
                    _log(out, f"statistics tick (active panel = {rvid!r},"
                              f" {'unread' if prop not in was_read else 'read'}"
                              f" property): held={len(held)}"
                              f" holds_it={prop in held}")
                    _expect(prop in held,
                            "a tick in the Statistics tree gives its row even"
                            " when another panel is the active one")
                    _expect(prop in (getattr(state, "selected_paths", None)
                                     or []),
                            "the session's selection still holds the ticked"
                            " property (a panel tick must publish it, or the"
                            " next data-tree tick unloads it)")
                    _expect(set(getattr(state, "selected_paths", None) or [])
                            == set(getattr(state, "fespp_data_selectors", None)
                                   or []),
                            "selected_paths and the load channel agree")
                    read_now = [p for p in (getattr(state, "selected_paths", None) or [])
                                if p not in was_read]
                    in_view = [p for p in (getattr(state, f"visible_paths__{rvid}", None) or [])
                               if p in read_now]
                    strayed = [p for p in (getattr(state, f"visible_paths__{sv}", None) or [])
                               if p in read_now]
                    _log(out, f"  eyes in sync: read={len(read_now)}"
                              f" in {rvid}={len(in_view)}"
                              f" under the Statistics panel's id={len(strayed)}")
                    # the Statistics view's eyes and the 3D view's follow each
                    # other, on the same objects (app/features/compare_tree)
                    _expect(prop in in_view, "the 3D view in use shows the property"
                                             " the Statistics tree holds")
                    _expect(not strayed, "nothing of the Statistics tick's read"
                                         " went under the panel's own id")
                    # ...and the eye of that same tree: clicked, it takes the
                    # row out and closes the 3D view's eye on the same
                    # property; clicked again, both come back.
                    before = list(getattr(state, f"visible_paths__{rvid}", None) or [])
                    held0 = prop in _held()
                    with state:
                        controller.compare_tree_eye(sv, {"path": syn})
                    await asyncio.sleep(1.0)
                    held1 = prop in _held()
                    after = list(getattr(state, f"visible_paths__{rvid}", None) or [])
                    _log(out, f"panel eye: row {held0} -> {held1},"
                              f" 3D visible {len(before)} -> {len(after)}")
                    _expect(held0 and not held1,
                            "the panel tree's eye takes the row out of the panel")
                    _expect(prop in before and prop not in after,
                            "the panel tree's eye closes the 3D view's eye on the"
                            " same property")
                    with state:
                        controller.compare_tree_eye(sv, {"path": syn})
                    await asyncio.sleep(1.0)
                    _expect(prop in _held(), "the eye clicked again puts the row back")
                    _expect(prop in (getattr(state, f"visible_paths__{rvid}", None) or []),
                            "the eye clicked again opens the 3D view's eye again")
                else:
                    raise RuntimeError("panel_tree_probe: no property was read"
                                       " — the log tick read nothing, so the"
                                       " Statistics half of the grammar cannot"
                                       " be checked")
                # UNTICKING A CURVE leaves the LOG and nothing else: the
                # panel stops drawing it, the session keeps it loaded.
                def _curves(pid):
                    p = getattr(state, f"welllog_data__{pid}", None) or {}
                    return sum(len(t.get("curves") or [])
                               for w in (p.get("wells") or [])
                               for t in (w.get("tracks") or []))

                ticks = list(getattr(state, f"welllog_tree_selected__{wl}",
                                     None) or [])
                # a node the panel actually DRAWS: a curve is named in the
                # payload by its title, and the log holds many read nodes
                # (frames, markers, the trajectory) that are not curves
                drawn_names = {c.get("name") for w in (
                    (getattr(state, f"welllog_data__{wl}", None) or {})
                    .get("wells") or [])
                    for t in (w.get("tracks") or [])
                    for c in (t.get("curves") or [])}
                curve = next((t for t in ticks if t != well_path
                              and (tree.find_title(tree.find_node_id(t)) or "")
                              in drawn_names), None)
                if curve:
                    was_curves, was_read = _curves(wl), len(
                        getattr(state, "selected_paths", None) or [])
                    with state:
                        controller.welllog_tree_wells(
                            wl, [t for t in ticks if t != curve])
                    await _settled()
                    _log(out, f"untick one curve: drawn {was_curves} ->"
                              f" {_curves(wl)}; read {was_read} ->"
                              f" {len(getattr(state, 'selected_paths', None) or [])}"
                              " (unticking a panel's tree never unloads)")
                    _expect(_curves(wl) == was_curves - 1,
                            "unticking one curve takes exactly it out of the log")
                    _expect(len(getattr(state, "selected_paths", None) or [])
                            == was_read,
                            "unticking in a panel's tree unloads nothing")
                    with state:
                        controller.welllog_tree_wells(wl, ticks)
                    await _settled()
                    _expect(_curves(wl) == was_curves,
                            "ticking it back draws it again")
                else:
                    raise RuntimeError("panel_tree_probe: the log drew no"
                                       " curve to untick")
                # The right-click of the log tree acts on the same set as
                # its checkbox: removing the well empties the log, adding it
                # back brings its curves with it.
                with state:
                    controller.welllog_tree_action(
                        wl, {"action": "welllog-remove", "path": well_path})
                await _settled()
                _log(out, "menu Remove from this view:"
                          f" wells={len(getattr(state, 'ui_welllog_wells', None) or [])}"
                          f" drawn={_curves(wl)}")
                _expect(not (getattr(state, "ui_welllog_wells", None) or [])
                        and _curves(wl) == 0,
                        "Remove from this view empties the log")
                with state:
                    controller.welllog_tree_action(
                        wl, {"action": "welllog-add", "path": well_path})
                await _settled()
                back = _curves(wl)
                _log(out, "menu Add to this view:"
                          f" wells={len(getattr(state, 'ui_welllog_wells', None) or [])}"
                          f" drawn={back}")
                _expect(back == curves,
                        "Add to this view brings the well back with all its"
                        " curves")
                # THE DOOR. Once the session holds something, every panel
                # tree offers an eye on it — whether or not the panel holds
                # it. Gated on the tick, a tree would show none at all.
                with state:
                    controller.panel_tree_eyes(wl, "welllog")
                snap = state.to_dict()
                _log(out, "eyeable once the session holds properties:"
                          f" welllog={len(snap.get(f'welllog_tree_shown__{wl}') or [])}"
                          f" statistics={len(snap.get(f'compare_tree_shown__{sv}') or [])}"
                          f" held={len(_held())}"
                          f" log_ticks={len(snap.get(f'welllog_tree_selected__{wl}') or [])}")
                _expect((snap.get(f"welllog_tree_shown__{wl}") or [])
                        and (snap.get(f"compare_tree_shown__{sv}") or []),
                        "both panel trees offer an eye once the session holds"
                        " something")
                # THE PANEL OPENED A SECOND TIME, on a session that ALREADY
                # holds its wells and its rows: the tree seeds its ticks,
                # the seed fires the tree's own watcher, and a seed narrower
                # than what the panel draws must not read as "the reader has
                # just unticked every curve".
                held_curves, held_rows = _curves(wl), _held()
                with state:
                    controller.welllog_tree_ticks(wl)
                    controller.compare_tree_paths(
                        sv, list(getattr(state, f"compare_tree_selected__{sv}", None) or []))
                await asyncio.sleep(2.0)
                _log(out, "panels reopened on a full session:"
                          f" drawn {held_curves} -> {_curves(wl)};"
                          f" held {len(held_rows)} -> {len(_held())};"
                          f" dropped={len(getattr(state, f'welllog_dropped__{wl}', None) or [])}")
                _expect(_curves(wl) == held_curves,
                        "reopening the log keeps every curve it was drawing")
                _expect(set(_held()) == set(held_rows),
                        "reopening Statistics keeps every row it held")

            elif op == "dump":
                # Log state vars into scenario.log for assertions /
                # debugging: {"op":"dump","vars":["ui_hidden_rep_paths_by_view"]}; "keys": the items of each
                # to log instead of the whole of it ([["view_1", "count"], ["view_1", "total"]])
                for name in step.get("vars", []):
                    whole_ = getattr(state, name, None)
                    for path_ in step.get("keys") or [None]:
                        val_ = whole_
                        for k_ in path_ or ():
                            val_ = val_.get(k_) if isinstance(val_, dict) else None
                        _log(out, f"dump {name}{''.join(f'[{k_!r}]' for k_ in path_ or ())} = {val_!r}")

            elif op == "welllog_probe":
                # Drive the real "Add to Well Log view" path on the first wellbore
                # in the tree and report what the panel payload actually
                # carries. A missing stratigraphic band is invisible to a
                # screenshot diff — it just is not there — so the counts are
                # the assertion.
                asm = tree._data_assembly
                stack, wid = [0], None
                while stack and wid is None:
                    nid = stack.pop(0)
                    if (tree.find_type(nid) or "") == "Wellbore":
                        wid = nid
                        break
                    stack.extend(asm.GetChildNodes(nid))
                if wid is None:
                    raise RuntimeError("no Wellbore node in the tree")
                _log(out, f"probe well: {tree.find_title(wid)!r}")
                # tick every marker the wellbore owns, as the user does,
                # and every log CHANNEL: a channel's fine type is its
                # property class (ContinuousProperty...), not "Channel", so
                # _WELL_KINDS alone would leave every curve unchecked and the
                # zone statistics empty. Under a wellbore, a property IS a
                # channel (role WellboreChannel on a plugin that publishes
                # roles; the class names cover a plugin that does not).
                _channel = ("ContinuousProperty", "DiscreteProperty",
                            "CategoricalProperty")
                marks, st = [], [wid]
                while st:
                    nid = st.pop()
                    kind = tree.find_type(nid) or ""
                    if (kind in _WELL_KINDS or kind in _channel
                            or tree.find_role(nid) == "WellboreChannel"):
                        marks.append(nid)
                    st.extend(asm.GetChildNodes(nid))
                # `selected_paths` is what the tree widget writes and what the
                # panel reads back as "the checked set" — `ui_select_node_*`
                # only feeds the legacy selector, which renders the curves but
                # leaves the panel's checked set empty.
                paths = sorted({p for p in (tree.find_path(n) for n in marks)
                                if p}
                               | set(getattr(state, "selected_paths", None)
                                     or []))
                with state:
                    controller.select_paths(paths)
                    controller.add_to_welllog(tree.find_path(wid))
                _log(out, f"checked {len(paths)} well nodes")
                # the checked channels must reach the collector, which
                # materialises their blocks: a generous delay
                await asyncio.sleep(4.0)
                snap = state.to_dict()
                _log(out, f"strati columns in state: "
                          f"{len(snap.get('ui_strati_columns') or [])}"
                          f" note={snap.get('ui_strati_note')!r}")
                keys = [k for k in snap if k.startswith("welllog_data__")]
                _log(out, f"welllog payload keys: {keys}")
                # Build the payload DIRECTLY. The app's refresh only runs when
                # a well-log dockview panel exists, and headless there is no
                # client to create one — every welllog_data__ key seen here is
                # a render view's per-view seed, and stays empty. Going through
                # the dispatcher is what this probe is for anyway: it reports
                # what the panel WOULD carry.
                from fespp_on_trame.engine import welllog_dispatch
                sr = getattr(server.context, "source_registry", None)
                # WHAT THE PANEL DRAWS, not what the session holds: a log
                # builds its payload from the read paths LESS the ones its
                # own tree has unticked (`welllog_dropped__<vid>`). Feeding
                # `selected_paths` straight in would blind this probe to a
                # panel that has thrown every curve away.
                drawn = [p for p in (snap.get("selected_paths") or [])
                         if not any(p in (snap.get(k) or [])
                                    for k in snap
                                    if k.startswith("welllog_dropped__"))]
                payload = welllog_dispatch.build_payload(
                    tree, sr, [tree.find_path(wid)], drawn,
                    strati_columns=snap.get("ui_strati_columns"))
                _log(out, f"direct payload: wells={len(payload.get('wells') or [])}"
                          f" markers={len(payload.get('markers') or [])}"
                          f" drawn={len(drawn)}"
                          f" selected_paths={len(snap.get('selected_paths') or [])}")
                if not payload.get("wells"):
                    raise RuntimeError("the log panel would draw no well at"
                                       " all from what it holds")
                # THE DEPTH AXES. What is drawn, what is integrated, and the
                # proof the vertical depth is the trajectory's centreline: a
                # tube-SURFACE Z can go back up while the hole goes down and
                # break |dTVD| <= dMD, which is geometrically impossible.
                # Both the up-step count and the excess must be zero.
                w0 = (payload.get("wells") or [None])[0]
                if w0 is not None:
                    _log(out, f"axis: depthRef={w0.get('depthRef')}"
                              f" integrationRef={w0.get('integrationRef')}"
                              f" tvd_up_hole={w0.get('tvd_up_hole')}")
                    title = next(iter(w0.get("_full") or {}), None)
                    pts = (w0.get("_full") or {}).get(title) or []
                    if w0.get("depthRef") != "MD":
                        _log(out, "  monotonicity check skipped: this well is"
                                  " drawn on TVD, so no measured depth to"
                                  " check the vertical depth against")
                    elif len(pts) < 2:
                        _log(out, "  monotonicity check skipped: no channel"
                                  " with two samples on this well")
                    else:
                        ups, worst = 0, 0.0
                        for a, b in zip(pts, pts[1:]):
                            d_md, d_tvd = b[1] - a[1], b[2] - a[2]
                            if d_tvd < 0.0:
                                ups += 1
                            worst = max(worst, abs(d_tvd) - abs(d_md))
                        _log(out, f"  {title!r}: tvd_monotonic={ups}/{len(pts) - 1}"
                                  f" max(|dTVD|-dMD)={worst:.4f}")
                        if ups or worst > 1e-6:
                            raise RuntimeError(
                                f"the true vertical depth is not a centreline:"
                                f" {ups} up-steps, {worst:.2f} m over |dTVD| <="
                                f" dMD — the ring's first point is being read"
                                f" instead of its mean")
                # the zones table's export: its dated name and header
                csv = welllog_dispatch.zones_csv_payload(payload)
                _log(out, f"zones csv: name={csv['name']!r}"
                          f" header={len(csv['header'])} lines")
                # the synthetic log: the first LOADED grid property sampled
                # along this well's trajectory, then admitted to the payload
                if step.get("synth"):
                    from fespp_on_trame.engine import trajectory_sampling
                    choices = snap.get("welllog_synth_choices") or {}
                    props = list(choices.get("props") or [])
                    _log(out, f"synth choices: wells={len(choices.get('wells') or [])}"
                              f" grid props={len(props)}")
                    if not props:
                        raise RuntimeError("synth: no loaded grid property")
                    wpath = tree.find_path(wid)
                    curve = trajectory_sampling.synthetic_curve(
                        state, tree, sr, wpath, props[0]["value"], 0.5)
                    if curve is None:
                        raise RuntimeError("synthetic log failed: "
                                           + trajectory_sampling.last_error())
                    got = [s for s in curve["samples"] if s[0] is not None]
                    _log(out, f"synthetic log: samples={len(curve['samples'])}"
                              f" in_grid={len(got)} kind={curve['kind']!r}"
                              f" unit={curve['unit']!r}"
                              f" tvd_max={curve['samples'][-1][1]:.1f}")
                    if not got:
                        raise RuntimeError("no sample fell in the grid")
                    p2 = welllog_dispatch.build_payload(
                        tree, sr, [wpath], drawn,
                        strati_columns=snap.get("ui_strati_columns"),
                        synthetics={wpath: [curve]})
                    w2 = p2["wells"][0] if p2["wells"] else {}
                    tr = w2.get("tracks") or []
                    _log(out, f"  with synthetic: tracks={len(tr)}"
                              f" curves={sum(len(t['curves']) for t in tr)}"
                              f" synthetic={sum(1 for t in tr for c in t['curves'] if c.get('synthetic'))}")
                    # the stations' measured depth: the file's when the
                    # trajectory block carries the "MD" array, else the
                    # chord — and the well's drawing axis follows: a
                    # synthetic log with md keeps the well on MD
                    trajs = welllog_dispatch._descendants_of_kinds(
                        tree, wid, trajectory_sampling._TRAJ_ROLES,
                        trajectory_sampling._TRAJ_KINDS)
                    stations, true_md = trajectory_sampling.stations_and_md(
                        sr.shared_source(), tree.find_path(trajs[0]))
                    with_md = [s for s in curve["samples"] if s[2] is not None]
                    _log(out, f"  trajectory: stations={len(stations)}"
                              f" stored_md={true_md}"
                              f" md_first={stations[0][3]:.2f}"
                              f" md_last={stations[-1][3]:.2f}"
                              f" samples_with_md={len(with_md)}"
                              f" depthRef={w2.get('depthRef')!r}")
                    if true_md and len(with_md) != len(curve["samples"]):
                        raise RuntimeError("stored MD, but samples without md")
                    if not true_md and with_md:
                        raise RuntimeError("no stored MD, but samples with md")
                    want_md = step.get("stored_md")
                    if want_md is not None and bool(want_md) != bool(true_md):
                        raise RuntimeError(
                            f"expected stored_md={want_md}, got {true_md}")
                    if true_md and w2.get("depthRef") != "MD":
                        raise RuntimeError(
                            "the trajectory stores MD, yet the well with a"
                            f" synthetic log is drawn on {w2.get('depthRef')!r}")
                for w in payload.get("wells", []):
                    lanes = w.get("strati") or {}
                    sizes = {name: len(v) for name, v in lanes.items()}
                    _log(out, f"  well {w.get('name')!r}"
                              f" tops={len(w.get('tops') or [])}"
                              f" strati={sizes}")
                    # the per-zone statistics ride on the same payload;
                    # counts only, never a value that names the data
                    zones = w.get("zones") or []
                    with_curves = [z for z in zones if z.get("curves")]
                    _log(out, f"    zones={len(zones)}"
                              f" source={zones[0].get('source') if zones else None!r}"
                              f" with_curves={len(with_curves)}"
                              f" curves_in_first="
                              f"{len(with_curves[0]['curves']) if with_curves else 0}")
                    # gross along the hole against gross vertical: the ratio
                    # IS cos(inclination), so it lives in [0, 1] (a 5 % margin
                    # above 1 tolerated). A ratio outside it means the
                    # vertical depth was read off the tube surface, not off
                    # the centreline.
                    ratios = []
                    for z in zones:
                        gm, gt = z.get("thickness"), z.get("thickness_tvd")
                        if not gm or gt is None:
                            _log(out, f"      zone {z.get('name')!r}: no vertical"
                                      f" thickness — {z.get('tvd_na')}")
                            continue
                        ratios.append((gt / gm, z.get("name"), gm, gt))
                    for r, name, gm, gt in sorted(ratios)[:1] + sorted(ratios)[-1:]:
                        _log(out, f"      zone {name!r}: gross_md={gm:.2f}"
                                  f" gross_tvd={gt:.2f} ratio={r:.4f}")
                    bad = [x for x in ratios if not 0.0 <= x[0] <= 1.05]
                    if bad:
                        raise RuntimeError(
                            f"{len(bad)} zone(s) with a gross_tvd / gross_md"
                            f" outside [0, 1.05], first {bad[0]} — the vertical"
                            f" thicknesses are not read off a centreline")
                    flat = [x for x in ratios if x[3] <= 0.0]
                    if flat:
                        raise RuntimeError(f"{len(flat)} zone(s) of zero or"
                                           f" negative vertical thickness")
                    # the cutoff path: a threshold at a curve's own P50 in a
                    # zone must flag about half of that zone as pay — a
                    # data-independent check of pay_intervals / with_cutoffs
                    if (step.get("cutoff_p50") or step.get("cutoff_missing")) \
                            and not with_curves:
                        _log(out, "    cutoff checks skipped: no zone of"
                                  " this well holds a curve sample")
                    if step.get("cutoff_p50") and with_curves:
                        z0, c0 = with_curves[0], with_curves[0]["curves"][0]
                        rule = {"curve": c0["name"], "op": ">=",
                                "value": c0["p50"]}
                        cut = welllog_dispatch.with_cutoffs(payload, [rule])
                        cw = next(x for x in cut["wells"]
                                  if x["name"] == w.get("name"))
                        cz = next(x for x in cw["zones"]
                                  if x["name"] == z0["name"]
                                  and x["top"] == z0["top"])
                        cc = next(x for x in cz["curves"]
                                  if x["name"] == c0["name"])
                        _log(out, f"    cutoff at P50 of first curve:"
                                  f" pay_intervals={len(cw.get('pay') or [])}"
                                  f" ntg={cz.get('ntg'):.2f}"
                                  f" n_pay={cc.get('n_pay')}/{cc.get('n')}"
                                  f" phih={'set' if cz.get('phih') is not None else 'none'}"
                                  f" pay_na={cz.get('pay_na')}")
                        if not 0.25 <= (cz.get("ntg") or 0.0) <= 0.75:
                            raise RuntimeError(
                                f"a P50 cutoff flagged {cz.get('ntg')} of the"
                                " zone; expected about half")
                        # THE PAY BAND IS SHADED ON THE DRAWN AXIS. `pay` is
                        # what the renderer scales with depth.min/max, so
                        # every bound of it must lie in the track. Published
                        # on the vertical instead (what `pay_tvd` holds), the
                        # bands of a well drawn on MD would be shaded far
                        # above the rock they flag — or clipped away entirely
                        # on a steeply deviated well — while Net still
                        # reports metres of pay.
                        dmin = (cw.get("depth") or {}).get("min")
                        dmax = (cw.get("depth") or {}).get("max")
                        band, vert = cw.get("pay") or [], cw.get("pay_tvd") or []
                        outside = [p for p in band
                                   if not (dmin <= p[0] <= dmax
                                           and dmin <= p[1] <= dmax)]
                        _log(out, f"    pay bands: drawn={len(band)} on"
                                  f" {cw.get('depthRef')} [{dmin:.1f},"
                                  f" {dmax:.1f}] vertical={len(vert)}"
                                  f" outside the track={len(outside)}")
                        if len(band) != len(vert) or outside:
                            raise RuntimeError(
                                f"{len(outside)} pay band(s) of {len(band)}"
                                f" fall outside the drawn track"
                                f" [{dmin}, {dmax}] — the vertical intervals"
                                " are being published as the band")
                        # what the summation report discloses: the porosity
                        # and water-saturation logs it read (None when no
                        # kind names one — then Φ·h is not reported, and the
                        # panel says so) and the other candidates
                        sm = cw.get("summation") or {}
                        _log(out, f"    summation reads: phi={sm.get('phi')!r}"
                                  f" among {sm.get('phi_candidates')}"
                                  f" sw={sm.get('sw')!r}"
                                  f" among {sm.get('sw_candidates')}")
                        if (sm.get("phi") is None) != (cz.get("phih") is None):
                            raise RuntimeError("the summation disclosure and"
                                               " the Φ·h figure disagree")
                        # disclosure = figure: Φ·h of this zone recomputed
                        # from the curve the report NAMES, through the
                        # dispatcher's own helper, must be the table's — and
                        # the other candidates are logged so the reader sees
                        # the pick is not interchangeable
                        if sm.get("phi") is None:
                            _log(out, "    phi*h recomputation skipped: no"
                                      " curve's kind names a porosity on"
                                      " this well, so no phi*h is reported")
                        else:
                            curves = welllog_dispatch._curves_of(cw)
                            # on the VERTICAL pay and the VERTICAL bounds, as
                            # the table sums it — `pay` is the drawn one
                            span = (cw.get("pay_tvd") or [],
                                    cz["top_tvd"], cz["bottom_tvd"])
                            phih, hcph = welllog_dispatch._pore_thickness(
                                curves, sm["phi"], sm.get("sw"), *span)
                            others = {
                                n: welllog_dispatch._pore_thickness(
                                    curves, n, sm.get("sw"), *span)[0]
                                for n in sm.get("phi_candidates") or []
                                if n != sm["phi"]}
                            _log(out, f"    phi*h of the first zone from"
                                      f" {sm['phi']!r}: {phih:.6g}"
                                      f" (table {cz['phih']:.6g})"
                                      f" hcph={hcph!r} (table {cz.get('hcph')!r})"
                                      f" other candidates: {others}")
                            if (abs(phih - cz["phih"]) > 1e-9 * max(1.0, abs(phih))
                                    or (hcph is None) != (cz.get("hcph") is None)
                                    or (hcph is not None and abs(hcph - cz["hcph"])
                                        > 1e-9 * max(1.0, abs(hcph)))):
                                raise RuntimeError("phi*h recomputed from the"
                                                   " disclosed curve differs"
                                                   " from the table")
                    # a rule on a log this well does not carry — a log of
                    # ANOTHER wellbore of the file, the multi-well case where
                    # the cutoff editor offers every well's logs: the pay is
                    # not evaluable, so nothing is shaded and every pay
                    # figure is None with the missing log named, never a
                    # zero that would read as a sterile well
                    if step.get("cutoff_missing") and with_curves:
                        # every channel this well LOGS — read or not: a
                        # ticked channel that yields no sample is absent
                        # from the tracks yet not "a log of another
                        # wellbore"
                        absent = w.get("absent") or {}
                        own = {c["name"] for t in w.get("tracks") or []
                               for c in t.get("curves") or []
                               if not c.get("missing")} | set(absent)
                        _log(out, f"    channels of this well the panel does"
                                  f" not carry: unticked="
                                  f"{sum(1 for a in absent.values() if a['why'] == 'unticked')}"
                                  f" unreadable="
                                  f"{sum(1 for a in absent.values() if a['why'] == 'unreadable')}")
                        other = None
                        st2 = [0]
                        while st2 and other is None:
                            nid = st2.pop()
                            if nid != wid and (tree.find_type(nid) or "") == "Wellbore":
                                sub = [nid]
                                while sub and other is None:
                                    cid = sub.pop()
                                    if ((tree.find_type(cid) or "") in _channel
                                            or tree.find_role(cid) == "WellboreChannel"):
                                        t = tree.find_title(cid) or ""
                                        if t and t not in own:
                                            other = t
                                    sub.extend(asm.GetChildNodes(cid))
                                continue
                            st2.extend(asm.GetChildNodes(nid))
                        if other is None:
                            raise RuntimeError("cutoff_missing: every log of"
                                               " the other wellbores is also"
                                               " on this well")
                        _log(out, f"    cutoff on {other!r}, a log of another"
                                  f" wellbore this well lacks:")
                        rule = {"curve": other, "op": ">=", "value": 0.0}
                        cut = welllog_dispatch.with_cutoffs(payload, [rule])
                        cw = next(x for x in cut["wells"]
                                  if x["name"] == w.get("name"))
                        cz = next(x for x in cw["zones"]
                                  if x["name"] == with_curves[0]["name"]
                                  and x["top"] == with_curves[0]["top"])
                        na_zones = [z for z in cw["zones"]
                                    if z.get("pay_na") == [other]
                                    and z.get("net") is None
                                    and z.get("ntg") is None
                                    and z.get("phih") is None
                                    and z.get("hcph") is None]
                        _log(out, f"      pay_intervals={len(cw.get('pay') or [])}"
                                  f" well pay_na={cw.get('pay_na')}"
                                  f" why={cw.get('pay_na_why')}"
                                  f" zones not evaluable={len(na_zones)}/{len(cw['zones'])}"
                                  f" first zone: net={cz.get('net')!r}"
                                  f" ntg={cz.get('ntg')!r}"
                                  f" mean_pay={cz['curves'][0].get('mean_pay')!r}")
                        if (cw.get("pay") or cw.get("pay_na") != [other]
                                or cw.get("pay_na_why") != {other: "unlogged"}
                                or len(na_zones) != len(cw["zones"])
                                or any(c.get("n_pay") is not None
                                       for c in cz["curves"])):
                            raise RuntimeError("a rule on a log the well lacks"
                                               " must leave every pay figure"
                                               " None and name the log as"
                                               " unlogged")
                        # the same rule on a log this well DOES carry, left
                        # unticked — the common multi-well case, where the
                        # channels are ticked per wellbore: still not
                        # evaluable, but the reason must be "unticked", so
                        # the panel can say what to tick rather than claim
                        # the log is not there
                        c0 = with_curves[0]["curves"][0]["name"]
                        c0_paths = set()
                        sub = [wid]
                        while sub:
                            cid = sub.pop()
                            if ((tree.find_type(cid) or "") in _channel
                                    or tree.find_role(cid) == "WellboreChannel") \
                                    and tree.find_title(cid) == c0:
                                c0_paths.add(tree.find_path(cid))
                            sub.extend(asm.GetChildNodes(cid))
                        p3 = welllog_dispatch.build_payload(
                            tree, sr, [tree.find_path(wid)],
                            [p for p in (snap.get("selected_paths") or [])
                             if p not in c0_paths],
                            strati_columns=snap.get("ui_strati_columns"))
                        w3 = p3["wells"][0] if p3["wells"] else {}
                        cut3 = welllog_dispatch.with_cutoffs(
                            p3, [{"curve": c0, "op": ">=", "value": 0.0}])
                        cw3 = cut3["wells"][0] if cut3["wells"] else {}
                        _log(out, f"    cutoff on {c0!r}, a log of this well"
                                  f" left unticked ({len(c0_paths)} channel"
                                  f" path(s) removed): absent={w3.get('absent', {}).get(c0)}"
                                  f" pay_intervals={len(cw3.get('pay') or [])}"
                                  f" pay_na={cw3.get('pay_na')}"
                                  f" why={cw3.get('pay_na_why')}")
                        if (not c0_paths or cw3.get("pay")
                                or cw3.get("pay_na") != [c0]
                                or cw3.get("pay_na_why") != {c0: "unticked"}):
                            raise RuntimeError("a rule on a log the well"
                                               " carries unticked must name"
                                               " it as unticked, not unlogged")
                        # and on a ticked channel that yielded no sample,
                        # when the file has one: the third reason
                        bad = next((n for n, a in absent.items()
                                    if a["why"] == "unreadable"), None)
                        if bad is None:
                            _log(out, "    unreadable-channel cutoff skipped:"
                                      " every ticked channel of this well"
                                      " was read")
                        else:
                            cut4 = welllog_dispatch.with_cutoffs(
                                payload, [{"curve": bad, "op": ">=", "value": 0.0}])
                            cw4 = next(x for x in cut4["wells"]
                                       if x["name"] == w.get("name"))
                            _log(out, f"    cutoff on {bad!r}, a ticked channel"
                                      f" of this well that yielded no sample:"
                                      f" pay_intervals={len(cw4.get('pay') or [])}"
                                      f" pay_na={cw4.get('pay_na')}"
                                      f" why={cw4.get('pay_na_why')}")
                            if (cw4.get("pay") or cw4.get("pay_na") != [bad]
                                    or cw4.get("pay_na_why") != {bad: "unreadable"}):
                                raise RuntimeError("a rule on a ticked channel"
                                                   " that yielded no sample"
                                                   " must name it as unreadable")

            elif op == "assembly_probe":
                # Where the datasets sit in the collector's output for the
                # subtree of the node titled `title`: node path, its own
                # dataset indices, the subtree's, and the partition classes —
                # what an ExtractPath on each node would actually hand back.
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                sr = getattr(server.context, "source_registry", None)
                shared = sr.shared_source() if sr is not None else None
                shared.UpdatePipeline()
                pdc = shared.GetClientSideObject().GetOutputDataObject(0)
                asm = pdc.GetDataAssembly()
                stack = [(nid, 0)]
                while stack:
                    n, depth = stack.pop()
                    path = tree.find_path(n)
                    node = asm.GetFirstNodeByPath(path) if path else -1
                    own = list(asm.GetDataSetIndices(node, False)) if node >= 0 else []
                    sub = list(asm.GetDataSetIndices(node, True)) if node >= 0 else []
                    kinds = []
                    for i in sub[:4]:
                        pds = pdc.GetPartitionedDataSet(i)
                        d = pds.GetPartitionAsDataObject(0) if pds and pds.GetNumberOfPartitions() else None
                        kinds.append(d.GetClassName() if d is not None else None)
                    _log(out, f"{'  ' * depth}{tree.find_title(n)!r} type={tree.find_type(n)!r}"
                              f" node={node} own={own} subtree={sub[:6]} classes={kinds}")
                    for c in reversed(list(tree._data_assembly.GetChildNodes(n))):
                        stack.append((c, depth + 1))

            elif op == "isolate_probe":
                # Every per-view grid isolate: what its clone and its
                # extractor actually output (class, assembly, cells), and the
                # chain it carries — enough to tell a crop fed a PolyData
                # instead of a grid.
                ctx = server.context
                isolates = getattr(ctx, "grid_isolates", None) or {}
                _log(out, f"isolates: {list(isolates.keys())}")
                for key, iso in isolates.items():
                    def _describe(proxy, label):
                        if proxy is None:
                            _log(out, f"  {label}: None")
                            return
                        try:
                            proxy.UpdatePipeline()
                            o = proxy.GetClientSideObject().GetOutputDataObject(0)
                            asm = o.GetDataAssembly() if hasattr(o, "GetDataAssembly") else None
                            n = (o.GetNumberOfPartitionedDataSets()
                                 if hasattr(o, "GetNumberOfPartitionedDataSets") else None)
                            cells = o.GetNumberOfCells() if hasattr(o, "GetNumberOfCells") else None
                            _log(out, f"  {label}: {o.GetClassName()} assembly={asm is not None}"
                                      f" pds={n} cells={cells}")
                        except Exception as exc:
                            _log(out, f"  {label}: error {exc}")
                    _describe(getattr(iso, "_clone", None), "clone")
                    ext = getattr(iso, "source_extract", None)
                    try:
                        from paraview.servermanager import vtkSMPropertyHelper
                        path = vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").GetAsString() if ext is not None else None
                    except Exception as exc:
                        path = f"error {exc}"
                    _log(out, f"  extractor ExtractPath={path!r}")
                    _describe(ext, "extractor")
                    for axis in ("I", "J", "K", "i", "j", "k"):
                        srcs = getattr(iso, f"_src_slicers_{axis}", None)
                        if srcs:
                            _log(out, f"  slicers {axis}: {len(srcs)}")
                            _describe(srcs[0], f"  slicer {axis}[0]")
                    chain = getattr(iso, "_chain", None) or []
                    _log(out, f"  chain: {[getattr(e, 'name', e) for e in chain]}")
                    # what each threshold keeps now: its range and its cells
                    for e in chain:
                        for p in (getattr(e, "pv_proxies", None) or {}).values():
                            _describe(p, f"  threshold {getattr(e, 'array', '?')}"
                                         f" [{getattr(e, 'low', '?')}, {getattr(e, 'high', '?')}]")
                    _log(out, f"  current_extent={getattr(iso, '_current_extent', None)!r}")
                # EVERY crop proxy of the session: who feeds it, with what,
                # and the extent it was given
                for (name, _id), proxy in pvsimple.GetSources().items():
                    try:
                        if proxy.GetXMLName() != "ExplicitStructuredGridCrop":
                            continue
                        inp = proxy.Input
                        inp.UpdatePipeline()
                        io_ = inp.GetClientSideObject().GetOutputDataObject(0)
                        proxy.UpdatePipeline()
                        oo = proxy.GetClientSideObject().GetOutputDataObject(0)
                        _log(out, f"  crop {name!r}: input={inp.GetXMLName()}"
                                  f"->{io_.GetClassName() if io_ is not None else None}"
                                  f" extent={list(proxy.VOI if proxy.SMProxy.GetProperty('VOI') is not None else proxy.OutputWholeExtent)}"
                                  f" out_cells={oo.GetNumberOfCells() if oo is not None else None}")
                    except Exception as exc:
                        _log(out, f"  crop {name!r}: error {exc}")
                    for e in chain:
                        for attr in ("_proxies", "proxies", "_upstream_proxies"):
                            d = getattr(e, attr, None)
                            if isinstance(d, dict) and d:
                                for k, pr in list(d.items())[:2]:
                                    _describe(pr, f"    entry proxy {k}")
                                break

            elif op == "hide_nan_probe":
                # "Hide NaN cells" as the Colormap card and the view see it:
                # the card's projection, each isolate's mask, whether the grid
                # is isolated, whether its display is drawn, and the skin with
                # and without the mask (a geometry filter on each output — the
                # faces the neighbours gain are the point of the feature).
                # {"op":"hide_nan_probe","expect_on":true,"expect_auto":true,
                #  "expect_hidden_min":1,"expect_isolated":true,
                #  "expect_drawn":true,"expect_faces_change":true}
                from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter as _GF

                def _expect(cond, what):
                    _log(out, f"  {'OK ' if cond else 'FAIL'} {what}")
                    if not cond:
                        raise RuntimeError(f"hide_nan_probe: {what}")

                ctx = server.context
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                card = state.to_dict().get(f"ui_colormap__{vid}") or {}
                _log(out, f"hide_nan card ({vid}): array={card.get('array')!r}"
                          f" hide_nan={card.get('hide_nan')} auto={card.get('hide_nan_auto')}"
                          f" ok={card.get('hide_nan_ok')} why={card.get('hide_nan_why')!r}"
                          f" hidden={card.get('hide_nan_hidden')}")
                scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)

                def _skin(proxy):
                    ds = proxy.GetClientSideObject().GetOutputDataObject(0)
                    g = _GF()
                    g.SetInputData(ds)
                    g.Update()
                    return g.GetOutput().GetNumberOfCells()

                seen = []
                for (ivid, ipath), iso in (getattr(ctx, "grid_isolates", None) or {}).items():
                    if ivid != vid:
                        continue
                    sel = ipath
                    root = iso.render_root()
                    disp = servermanager.GetRepresentation(root, pvv) if root is not None else None
                    drawn = bool(disp is not None and int(getattr(disp, "Visibility", 0)))
                    isolated = bool(scene is not None and sel in scene.isolated)
                    faces = (_skin(iso.source_extract), _skin(root)) if root is not None else (None, None)
                    flag = (getattr(ctx, "grid_hide_nan", None) or {}).get((vid, ipath))
                    _log(out, f"  isolate {ipath[-40:]!r}: mask={iso.hide_nan_array!r}"
                              f" hidden={iso.hide_nan_hidden} flag={flag} isolated={isolated}"
                              f" drawn={drawn} skin unmasked={faces[0]} masked={faces[1]}"
                              f" mode={iso.range_mode!r} chain={len(iso.get_chain() or [])}")
                    seen.append((iso, isolated, drawn, faces))
                if not seen:
                    _log(out, "  no isolate in this view")
                for key, want in (("expect_on", "hide_nan"), ("expect_auto", "hide_nan_auto"),
                                  ("expect_ok", "hide_nan_ok")):
                    if step.get(key) is not None:
                        _expect(bool(card.get(want)) == bool(step[key]),
                                f"card {want}={card.get(want)!r},"
                                f" expected {bool(step[key])}")
                if step.get("expect_hidden_min") is not None:
                    _expect((card.get("hide_nan_hidden") or 0) >= int(step["expect_hidden_min"]),
                            f"{card.get('hide_nan_hidden')!r} cells hidden,"
                            f" expected at least {step['expect_hidden_min']}")
                if step.get("expect_isolated") is not None:
                    got = any(s[1] for s in seen)
                    _expect(got == bool(step["expect_isolated"]),
                            f"grid isolated={got}, expected {step['expect_isolated']}")
                if step.get("expect_drawn") is not None:
                    got = any(s[2] for s in seen)
                    _expect(got == bool(step["expect_drawn"]),
                            f"isolate drawn={got}, expected {step['expect_drawn']}")
                if step.get("expect_faces_change"):
                    _expect(any(s[3][0] is not None and s[3][0] != s[3][1] for s in seen),
                            "the skin changes with the mask")

            elif op == "slicer_probe":
                # What the view's grid isolate SHOWS: every crop with its
                # visibility in the view and the extent it cuts, the
                # colouring it carries — the card's truth against the screen
                ctx = server.context
                pvv = _resolve_view(server, state, view)
                shown_thr = []  # (tag, index, visible, kept cells, crop cells)
                shown_src = []  # (tag, index) of every base display drawn
                shown_colour = []  # the array each of those is coloured by
                for (ivid, ipath), iso in (getattr(ctx, "grid_isolates", None) or {}).items():
                    _log(out, f"isolate {ivid} mode={getattr(iso, 'range_mode', None)!r}"
                              f" colour={getattr(iso, '_title', None)!r}/{getattr(iso, '_current_array_type', None)!r}"
                              f" volumes={getattr(iso, '_volumes', None)!r}"
                              f" vis={getattr(iso, '_volumes_visible', None)!r}"
                              f" chain={[(e.get('name'), e.get('parent_name')) for e in (iso.get_chain() or [])]!r}")
                    groups = [("i", getattr(iso, "_src_slicers_i", [])),
                              ("j", getattr(iso, "_src_slicers_j", [])),
                              ("k", getattr(iso, "_src_slicers_k", [])),
                              ("vol", getattr(iso, "_src_volumes", [])),
                              ("rep", [iso.source_extract] if getattr(iso, "source_extract", None) is not None else []),
                              ("nan", [iso.nan_mask] if getattr(iso, "nan_mask", None) is not None else [])]
                    for tag, srcs in groups:
                        for i, src in enumerate(srcs):
                            try:
                                disp = servermanager.GetRepresentation(src, pvv)
                                visible = int(getattr(disp, "Visibility", 0)) if disp is not None else None
                                colour = list(disp.ColorArrayName)[1] if disp is not None else None
                                ext = (list(src.VOI if src.SMProxy.GetProperty("VOI") is not None else src.OutputWholeExtent)
                                       if tag not in ("rep", "nan") else None)
                                src.UpdatePipeline()
                                data_ = src.GetClientSideObject().GetOutputDataObject(0)
                                cells = data_.GetNumberOfCells()
                                bnds = [round(b, 1) for b in data_.GetBounds()] if cells else None
                            except Exception as exc:
                                visible, colour, ext, cells, bnds = f"error {exc}", None, None, None, None
                            _log(out, f"  {tag}[{i}] visible={visible} colour={colour!r}"
                                      f" extent={ext} cells={cells} bounds={bnds}")
                            if visible == 1:
                                shown_src.append((tag, i))
                                shown_colour.append(colour)
                            # the threshold chain on THIS upstream: what each
                            # entry keeps of it, and whether the view shows it
                            for entry in getattr(iso, "_chain", []) or []:
                                tp = (getattr(entry, "pv_proxies", None) or {}).get(id(src))
                                if tp is None:
                                    continue
                                try:
                                    tdisp = servermanager.GetRepresentation(tp, pvv)
                                    tvis = int(getattr(tdisp, "Visibility", 0)) if tdisp is not None else 0
                                    tp.UpdatePipeline()
                                    tcells = tp.GetClientSideObject().GetOutputDataObject(0).GetNumberOfCells()
                                except Exception as exc:
                                    tvis, tcells = f"error {exc}", None
                                _log(out, f"    threshold {entry.array!r} [{entry.low}, {entry.high}]"
                                          f" on {tag}[{i}]: visible={tvis} cells={tcells} of {cells}")
                                shown_thr.append((tag, i, tvis, tcells, cells))
                # "expect_nothing_shown": the grid's eye is closed — none of
                # its displays, crop or threshold, may still be drawn
                if step.get("expect_nothing_shown"):
                    drawn = shown_src + [t[:2] for t in shown_thr if t[2] == 1]
                    if drawn:
                        raise RuntimeError(f"slicer_probe: still drawn with the eye closed: {drawn}")
                # "expect_colour": a crop drawn is coloured by this array (a
                # formula's colour reaches the isolate: engine/derived_arrays)
                want_c = step.get("expect_colour")
                if want_c and want_c not in shown_colour:
                    raise RuntimeError(f"slicer_probe: no crop drawn coloured by {want_c!r}:"
                                       f" {shown_colour}")
                # "expect_thresholded": the crops of the current mode are
                # drawn THROUGH the chain — at least one threshold output
                # shown, each keeping fewer cells than the crop it filters
                if step.get("expect_thresholded"):
                    vis_thr = [t for t in shown_thr if t[2] == 1 and t[0] in ("i", "j", "k", "vol")]
                    if not vis_thr:
                        raise RuntimeError("slicer_probe: no threshold output shown on a crop")
                    bad = [t for t in vis_thr if t[3] is None or t[4] is None or t[3] >= t[4]]
                    if bad:
                        raise RuntimeError(f"slicer_probe: threshold keeps every cell of its crop: {bad}")

            elif op == "derived_probe":
                # A derived property created straight on the store — the
                # calculator's A − B row ends in the same create — then
                # evaluated: {"op":"derived_probe","grid":"Geogrid",
                # "name":"dSOIL","expr":"OilSat__t5 - OilSat__t0"}
                from fespp_on_trame.engine import derived_props
                # the grid by its title, or through one of its properties
                gid = _find_node_by_title(tree, step.get("grid") or step.get("prop"),
                                          step.get("under"))
                if gid is None:
                    raise RuntimeError(f"node not found: {step.get('grid') or step.get('prop')!r}")
                rid = tree.find_representation_node(gid)
                rep_path = tree.find_path(rid) if rid is not None else None
                store = derived_props.get_store()
                sr = getattr(server.context, "source_registry", None)
                chips = store.loaded_props_of_rep(state, tree, rep_path)
                _log(out, f"derived: loaded on {rep_path!r}: "
                          f"{sorted(t for t, _k in chips.values())}")
                err, d = store.create(state, tree, rep_path, step["name"], step["expr"],
                                      uom=step.get("uom", ""))
                if err:
                    _log(out, f"derived: create error: {err}")
                else:
                    path = derived_props.path_for(rep_path, d["name"])
                    _log(out, f"derived: created {d['name']!r} pins={d.get('inputs_pins')}"
                              f" caps={store.axis_caps(tree, path)}")
                    vals = store.evaluate(state, tree, sr, path)
                    import numpy as _np
                    fin = vals[_np.isfinite(vals)]
                    _log(out, f"derived: n={len(vals)} finite={len(fin)}"
                              f" min={fin.min() if len(fin) else None}"
                              f" mean={fin.mean() if len(fin) else None}"
                              f" max={fin.max() if len(fin) else None}"
                              f" nonzero={int((fin != 0).sum())}")
                    store.publish(state)

            elif op == "compare_probe":
                # The Statistics view opened the way the app does, the given
                # properties ticked in its docked tree (through the server's
                # synthetic path map, as a click would), then every tab read
                # and asserted: {"op":"compare_probe","grid":"Geogrid",
                # "props":["Total Porosity","Water Saturation"],
                # "baseline":"Total Porosity","dup":"Water Saturation"}.
                from fespp_on_trame.engine import compare_dispatch as cd
                from fespp_on_trame.engine import compare_tree as ct
                from fespp_on_trame.engine import tick_confirm
                gid = _find_node_by_title(tree, step.get("grid"), step.get("under"))
                if gid is None:
                    raise RuntimeError(f"node not found: {step.get('grid')!r}")
                rid = tree.find_representation_node(gid)
                props = list(step.get("props") or [])
                paths = [_prop_path_under(tree, rid, t) for t in props]

                def _expect(cond, what):
                    if not cond:
                        raise RuntimeError(f"compare_probe: {what}")

                def _chips():
                    chips = getattr(state, "ui_compare_chips", None) or []
                    _log(out, "compare chips: " + ", ".join(
                        f"{c.get('title')}[{c.get('kind')}|{c.get('align')}"
                        f"{'|baseline' if c.get('baseline') else ''}] {c.get('key')[-50:]}"
                        for c in chips))
                    return chips

                def _key_of(path):
                    return next((c["key"] for c in (getattr(state, "ui_compare_chips", None) or [])
                                 if c.get("path") == path), None)

                with state:
                    controller.open_compare()
                await asyncio.sleep(2.0)
                mv = getattr(server.context, "multi_view", None)
                vid = next(iter(mv.panel_ids_of_kind("compare")), None) if mv else None
                _expect(vid is not None, "no compare view opened")
                pmap = controller.compare_tree_map()
                _log(out, f"compare view {vid}: tree map {len(pmap)} leaves")

                def _loaded():
                    return list(getattr(state, "ui_loaded_array_paths",
                                        None) or [])

                # the tree lists what the FILE holds, not what is ticked
                # elsewhere: a property nobody loaded is offered here, and
                # ticking it loads it — then its row carries figures
                folder = paths[0].rsplit("/", 1)[0]
                cold = next((sp for sp, real in sorted(pmap.items())
                             if real not in _loaded()
                             and real.rsplit("/", 1)[0] == folder), None)
                if cold is None:
                    _log(out, "every property of the grid is already loaded:"
                              " the load-on-tick step has nothing to try")
                else:
                    cold_path = pmap[cold]
                    with state:
                        controller.compare_tree_paths(vid, [cold])
                    await asyncio.sleep(float(step.get("settle") or 3) + 4)
                    # the rows are keyed by the entry's uid: find the one of
                    # the property just ticked by the path it carries
                    row = next((r for r in (getattr(state, "ui_compare_rows", None)
                                            or {}).values()
                                if r.get("path") == cold_path), {})
                    _log(out, f"cold tick {cold_path[-50:]}:"
                              f" loaded={cold_path in _loaded()}"
                              f" Cardinality={(row.get('metrics') or {}).get('Cardinality')}"
                              f" load={row.get('load')!r} note={row.get('note')!r}")
                    _expect(cold_path in _loaded(),
                            "a tick in the Compare tree did not load the"
                            " property")
                    _expect((row.get("metrics") or {}).get("Cardinality", 0) > 0,
                            "the property just loaded has no figures:"
                            f" {row.get('note')!r}")
                    # The one grammar (the PO, 18/10): the Compare tree's
                    # checkbox is the session's load (`compare_tree_loaded__`,
                    # in its synthetic paths), its eye is "compared".
                    boxes = list(getattr(state, f"compare_tree_loaded__{vid}",
                                         None) or [])
                    held = list(getattr(state, f"compare_tree_selected__{vid}",
                                        None) or [])
                    _log(out, f"boxes: {len(boxes)} loaded, {len(held)} compared"
                              f" — the one just read is"
                              f" {'ticked' if cold in boxes else 'NOT TICKED'} and"
                              f" {'compared' if cold in held else 'NOT COMPARED'}")
                    _expect(cold in boxes,
                            "the property just read is not ticked in the"
                            " Compare tree (compare_tree_loaded__)")
                    _expect(cold in held,
                            "the property just read is not compared (its eye"
                            " in the Compare tree is closed)")
                    # A read for the COMPARISON goes in no 3D view: the 3D
                    # view's own eye set does not hold the property, nothing
                    # went under the Compare panel's id either (a bucket no
                    # 3D view reads, where an active-panel lookup would put
                    # it), and the panel says nothing about it.
                    rvid = _render_vid(server, state)
                    in_view = cold_path in (getattr(
                        state, f"visible_paths__{rvid}", None) or [])
                    strayed = [p for p in (getattr(
                        state, f"visible_paths__{vid}", None) or [])
                        if p == cold_path]
                    note = getattr(state, "ui_compare_note", "") or ""
                    _log(out, f"born hidden: active panel="
                              f"{getattr(state, 'fespp_active_panel_id', '')!r}"
                              f" in {rvid}={in_view}"
                              f" under the Compare panel's id={bool(strayed)}"
                              f" note={note!r}")
                    _expect(not in_view,
                            "a Compare tick showed the property in the 3D"
                            " view: a panel tick reads into the panel only")
                    _expect(not strayed,
                            "the read went under the Compare panel's own id"
                            " — a bucket no 3D view reads")
                    _expect(not note,
                            "a read that went well says nothing in the panel")
                    # The eye: clicked, the property leaves the comparison
                    # and the 3D view does not move; clicked again, back.
                    before3d = set(getattr(state, f"visible_paths__{rvid}", None) or [])
                    with state:
                        controller.compare_tree_eye(vid, {"path": cold})
                    await asyncio.sleep(1.0)
                    held = list(getattr(state, f"compare_tree_selected__{vid}",
                                        None) or [])
                    after3d = set(getattr(state, f"visible_paths__{rvid}", None) or [])
                    _log(out, f"eye clicked: compared={cold in held}"
                              f" 3D unchanged={before3d == after3d}")
                    _expect(cold not in held,
                            "the eye of the Compare tree takes the property"
                            " out of the comparison")
                    _expect(before3d == after3d,
                            "the eye of the Compare tree changed the 3D view")
                    with state:
                        controller.compare_tree_eye(vid, {"path": cold})
                    await asyncio.sleep(1.0)
                    _expect(cold in (getattr(state, f"compare_tree_selected__{vid}",
                                             None) or []),
                            "the eye clicked again puts it back in the comparison")
                    with state:
                        controller.compare_tree_paths(vid, [])
                    await asyncio.sleep(2.0)
                    _expect(not (getattr(state, "ui_compare_chips", None) or []),
                            "unticking left a chip behind")
                    # an untick leaves the comparison, it does not unload
                    _expect(cold_path in _loaded(),
                            "unticking in the Compare tree unloaded the"
                            " property")
                    pmap = controller.compare_tree_map()

                syn = [sp for pth in paths
                       for sp, real in pmap.items() if real == pth]
                _expect(len(syn) == len(paths),
                        f"{len(syn)} synthetic paths for {len(paths)} properties")
                with state:
                    controller.compare_tree_paths(vid, syn)
                await asyncio.sleep(float(step.get("settle") or 3))

                def _log_stats():
                    chips = _chips()
                    blocks = getattr(state, "ui_compare_blocks", None) or []
                    rows = getattr(state, "ui_compare_rows", None) or {}
                    ann = getattr(state, "ui_compare_annotations", None) or {}
                    for b in blocks:
                        _log(out, f"block {b.get('kind')!r}: {[k[-50:] for k in b.get('keys') or []]}")
                    for k, r in rows.items():
                        m = r.get("metrics") or {}
                        _log(out, f"row {r.get('label')!r}: Cardinality={m.get('Cardinality')}"
                                  f" Mean={m.get('Mean')} note={r.get('note')!r}")
                    n_ann = sum(len(v or {}) for v in ann.values())
                    _log(out, f"annotations: {n_ann}")
                    return chips, blocks, rows, ann

                chips, blocks, rows, ann = _log_stats()
                _expect(len(chips) == len(props), f"{len(chips)} chips for {len(props)} props")
                kinds = []
                for c in chips:
                    if c.get("kind") not in kinds:
                        kinds.append(c.get("kind"))
                # one tab per kind, each showing its own matrix — one block,
                # the kind's — with its own baseline (the first item of the
                # kind unless one was chosen)
                tabs = [k["kind"] for k in (getattr(state, "ui_compare_kinds", None) or [])]
                _expect(tabs == kinds, f"tabs {tabs} != kinds {kinds}")
                _expect(getattr(state, "ui_compare_tab", "") == kinds[0],
                        f"the panel did not land on the first kind: {getattr(state, 'ui_compare_tab', '')!r}")
                for k in kinds:
                    with state:
                        controller.compare_set("tab", k)
                    await asyncio.sleep(2.0)
                    _log(out, f"tab {k!r}:")
                    _c, blocks_k, _r, _a = _log_stats()
                    _expect(len(blocks_k) == 1 and blocks_k[0].get("kind") == k,
                            f"tab {k!r} shows blocks {[b.get('kind') for b in blocks_k]}")
                    n_kind = sum(1 for c in chips if c.get("kind") == k)
                    _expect(len(blocks_k[0].get("keys") or []) == n_kind,
                            f"tab {k!r}: {len(blocks_k[0].get('keys') or [])} rows for {n_kind} items")
                    starred = [c["key"] for c in chips if c.get("kind") == k and c.get("baseline")]
                    _expect(not starred, f"tab {k!r}: a baseline by default: {starred}")
                with state:
                    controller.compare_set("tab", kinds[0])
                await asyncio.sleep(2.0)
                chips, blocks, rows, ann = _log_stats()
                _expect(rows and all((r.get("metrics") or {}).get("Cardinality", 0) > 0
                                     for r in rows.values()),
                        "a row has no cardinality")
                # a ticked KIND folder stands for its whole subtree: the
                # widget sends the folder's own path and the server cascades,
                # then writes the tick back as the leaves it stands for. A
                # tick reading more than MAX_TICK_LOAD properties asks first,
                # so the folder taken here is the widest one below that
                by_folder = {}
                for s in pmap:
                    if not s.startswith(ct.PARTS_FOLDER + "/"):
                        by_folder.setdefault(s.rsplit("/", 2)[0], []).append(s)

                def _unread(syns):
                    have = set(_loaded())
                    return [s for s in syns if pmap[s] not in have]

                reach = {f: ss for f, ss in by_folder.items()
                         if len(_unread(ss)) <= tick_confirm.MAX_TICK_LOAD}
                folder = under = under_syn = None
                if not reach:
                    _log(out, "no kind folder reads without asking"
                              f" ({tick_confirm.MAX_TICK_LOAD} unread properties):"
                              " the cascade step has nothing to try")
                else:
                    folder, under_syn = max(reach.items(),
                                            key=lambda kv: len(kv[1]))
                    under = sorted(pmap[s] for s in under_syn)
                    with state:
                        controller.compare_tree_paths(vid, [folder])
                    await asyncio.sleep(float(step.get("settle") or 3) + 2)
                    _log(out, f"after ticking the folder {folder}"
                              f" ({len(under)} leaves):")
                    chips = _chips()
                    _expect(sorted(c.get("path") for c in chips) == under,
                            f"{len(chips)} chips for the {len(under)} leaves"
                            f" of {folder}")
                    back = list(getattr(state, f"compare_tree_selected__{vid}",
                                        None) or [])
                    _expect(folder not in back
                            and sorted(back) == sorted(under_syn),
                            "the folder tick was not written back as leaves:"
                            f" {back}")
                    # the tab of that kind holds several rows: its cross-plot,
                    # under the matrix, has X its first row and Y the next one,
                    # each picked over the chart among the rows of the kind
                    xpid = f"{vid}x"
                    axes_ = getattr(state, "ui_compare_xplot_axes", None) or {}
                    _log(out, f"cross-plot of the tab: axes={axes_}")
                    star = next(c for c in chips if c.get("uid") == axes_.get("x"))
                    mate = next((c for c in chips if c.get("uid") != star.get("uid")
                                 and c.get("rep") == star.get("rep")), None)
                    if mate is not None:
                        with state:
                            controller.compare_set("xplot_axis", ["y", mate["uid"]])
                        await _crossplot_settled(state, xpid)
                        charts_ = getattr(state, f"ui_crossplot_charts_{xpid}", None) or []
                        snap = state.to_dict()
                        xkey = cd.item_key(snap.get(f"ui_crossplot_x_{xpid}") or "",
                                           snap.get(f"ui_crossplot_xreal_{xpid}"),
                                           snap.get(f"ui_crossplot_xts_{xpid}"))
                        for c in charts_:
                            _log(out, f"  chart {c['key']} kept={c['kept']} title={c['title']!r}"
                                      f" note={c['note']!r}")
                        _expect(xkey == star["key"], f"X {xkey!r} is not the tab's first row {star['key']!r}")
                        _expect(len(charts_) == 1, f"{len(charts_)} charts for one Y")
                        _expect(charts_[0]["kept"] > 0, f"the chart kept 0 points: {charts_[0]['note']}")
                        figs = list(snap.get(f"ui_crossplot_figures_{xpid}") or [])
                        _expect([f.get("key") for f in figs] == [c["key"] for c in charts_],
                                f"figures {[f.get('key') for f in figs]} != {[c['key'] for c in charts_]}")
                # a folder standing for MORE unread properties than one tick
                # reads ASKS FIRST: nothing read, nothing joined, the boxes
                # left as the user set them, and a question stating the
                # number. Only the NO is walked here — the yes replays the
                # very same tick with no cap (unit:
                # test_the_same_tick_uncapped_reads_the_whole_cascade) and
                # would read the whole folder off the real file
                over = {f: ss for f, ss in by_folder.items()
                        if len(_unread(ss)) > tick_confirm.MAX_TICK_LOAD}
                if not over:
                    _log(out, "no kind folder holds more unread properties"
                              " than one tick reads: nothing to ask about")
                else:
                    big, big_syn = max(over.items(),
                                       key=lambda kv: len(_unread(kv[1])))
                    n_unread = len(_unread(big_syn))
                    was_loaded, was_chips = set(_loaded()), sorted(
                        c.get("path") for c in
                        (getattr(state, "ui_compare_chips", None) or []))
                    asked = list(under_syn or []) + [big]
                    boxes = list(getattr(state, f"compare_tree_selected__{vid}",
                                         None) or [])
                    with state:
                        controller.compare_tree_paths(vid, asked)
                    await asyncio.sleep(float(step.get("settle") or 3) + 2)
                    ask = getattr(state, "ui_tick_confirm", None) or {}
                    now_chips = sorted(c.get("path") for c in _chips())
                    joined = [c for c in now_chips if c not in was_chips]
                    _log(out, f"the folder {big} stands for {n_unread} unread"
                              f" properties: read={len(set(_loaded()) - was_loaded)}"
                              f" joined={len(joined)} chips={len(now_chips)}"
                              f" asking={ask.get('title')!r}")
                    _expect(set(_loaded()) == was_loaded,
                            "a folder tick over the cap read something"
                            " before being answered")
                    _expect(not joined,
                            "a folder tick over the cap changed the selection"
                            f" before being answered: {joined}")
                    _expect(ask.get("title") and str(n_unread) in ask["title"],
                            "the question does not say how many properties"
                            f" it would read: {ask!r}")
                    # the boxes stay as they were while the question stands:
                    # the widget holds the user's tick and the server must not
                    # write over it, or the question would be about a
                    # selection nobody can see
                    held = list(getattr(state, f"compare_tree_selected__{vid}",
                                        None) or [])
                    _expect(held == boxes,
                            "the checkboxes were rewritten while the question"
                            f" was still open: {held} (were {boxes})")
                    with state:
                        controller.tick_confirm_answer(False)
                    await asyncio.sleep(2.0)
                    back = list(getattr(state, f"compare_tree_selected__{vid}",
                                        None) or [])
                    _log(out, f"after stepping back: chips={len(_chips())}"
                              f" boxes={len(back)}"
                              f" asking={getattr(state, 'ui_tick_confirm', None)!r}")
                    _expect(not (getattr(state, "ui_tick_confirm", None)
                                 or {}),
                            "the question stayed open after the answer")
                    _expect(set(_loaded()) == was_loaded,
                            "stepping back read something anyway")
                    _expect(big not in back,
                            "stepping back left the folder ticked")
                with state:
                    controller.compare_tree_paths(vid, syn)
                await asyncio.sleep(2.0)
                chips = _chips()
                _expect(len(chips) == len(props),
                        f"{len(chips)} chips after the folder round trip")
                if step.get("baseline"):
                    bkey = _key_of(_prop_path_under(tree, rid, step["baseline"]))
                    _expect(bkey, "baseline chip not found")
                    # the baseline is the KIND's: its tab first
                    bkind = next((c.get("kind") for c in chips if c.get("key") == bkey), None)
                    with state:
                        controller.compare_set("tab", bkind)
                    await asyncio.sleep(1.0)
                    with state:
                        controller.compare_set("baseline", bkey)
                    await asyncio.sleep(2.0)
                    _log(out, f"after baseline {step['baseline']!r}:")
                    chips, blocks, rows, ann = _log_stats()
                    # the rows of a block are the entries, by uid; the baseline
                    # is held by uid too, and the chip of that key carries it
                    buid = next((c.get("uid") for c in chips if c.get("key") == bkey), "")
                    blk = next((b for b in blocks if buid in (b.get("keys") or [])), None)
                    _expect(blk is not None and blk["keys"][0] == buid,
                            "the baseline is not first in its block")
                    _expect(any(c.get("baseline") for c in chips if c.get("key") == bkey),
                            "the baseline chip is not flagged")
                if step.get("dup"):
                    # a pinned copy: a row's pin — the copy keeps its source's
                    # realization and time, fixed
                    dpath = _prop_path_under(tree, rid, step["dup"])
                    dkey = _key_of(dpath)
                    _expect(dkey, "pin chip not found")
                    with state:
                        controller.compare_set("pin", dkey)
                    await asyncio.sleep(2.0)
                    _log(out, f"after pin {step['dup']!r}:")
                    chips = _chips()
                    _expect(len(chips) == len(props) + 1,
                            f"{len(chips)} chips after pin, expected {len(props) + 1}")
                    pair = [c for c in chips if c.get("path") == dpath]
                    _expect(len(pair) == 2,
                            "the pinned copy does not share its source's path")
                    # the copy is marked in the selection (the rows on screen
                    # are the current kind tab's, which may not be this one)
                    items_now = getattr(state, "ui_compare_items", None) or []
                    _expect(sum(1 for it in items_now
                                if it.get("path") == dpath and it.get("pinned")) == 1,
                            "the copy is not marked pinned in the selection")
                    # the copy alone can be dropped: the two entries share an
                    # item key until the source picks a real / time, so a
                    # removal has to name the ENTRY
                    with state:
                        controller.compare_set(
                            "unpin", pair[-1].get("uid") or pair[-1]["key"])
                    await asyncio.sleep(2.0)
                    _log(out, "after unpinning the copy:")
                    chips = _chips()
                    _expect(sum(1 for c in chips if c.get("path") == dpath) == 1,
                            "unpinning the copy removed its source too")
                    _expect(len(chips) == len(props),
                            f"{len(chips)} chips after unpinning the copy")
                    with state:
                        controller.compare_set("pin", pair[0].get("uid")
                                               or dkey)
                    await asyncio.sleep(2.0)
                # under the matrix of a tab, at once: the histograms of that kind
                # alone, under the kind's own options
                await asyncio.sleep(2.0)
                tab_now = getattr(state, "ui_compare_tab", "") or ""
                dmeta = getattr(state, "ui_compare_dist_meta", None) or {}
                _log(out, f"dist of tab {tab_now!r}: meta={dmeta}")
                n_tab = sum(1 for c in _chips() if c.get("kind") == tab_now)
                _expect((dmeta.get("traces") or 0) == n_tab,
                        f"dist traces {dmeta.get('traces')} for {n_tab} items of the kind")
                # the options are the kind's own: set on one tab, absent on another
                with state:
                    controller.compare_set("dist_opt", ["nbins", 12])
                await asyncio.sleep(1.5)
                _expect((getattr(state, "ui_compare_dist_opts", None) or {}).get("nbins") == 12,
                        "nbins not applied to the kind")
                if len(kinds) > 1:
                    other_tab = next(k for k in kinds if k != tab_now)
                    with state:
                        controller.compare_set("tab", other_tab)
                    await asyncio.sleep(1.5)
                    other = (getattr(state, "ui_compare_dist_opts", None) or {}).get("nbins")
                    _expect(other != 12, f"nbins leaked to another kind: {other}")
                    with state:
                        controller.compare_set("tab", tab_now)
                    await asyncio.sleep(1.5)
                _expect(getattr(state, "ui_compare_dist_figure", None) is not None,
                        "dist figure is null")
                _expect((dmeta.get("traces") or 0) >= 1, f"dist traces {dmeta.get('traces')}")
                # a tab of one row has no cross-plot, and nothing is said about it
                if n_tab == 1:
                    note_one = getattr(state, "ui_compare_xplot_note", "") or ""
                    _log(out, f"cross-plot of a tab of one row: note={note_one!r}")
                    _expect(not note_one, f"a tab of one row says {note_one!r}")

            elif op == "cell_volume_probe":
                # Every visible cell's volume by vtkCellSizeFilter — what the
                # volumetrics take — and, for the first `limit` cells whose
                # volume is zero, negative or NaN, their type, corners and the
                # volume a tetrahedral decomposition gives for comparison.
                # {"op":"cell_volume_probe","grid":"Geogrid","limit":4}
                import numpy as _np
                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                from vtkmodules.vtkCommonCore import vtkIdList, vtkPoints
                from vtkmodules.vtkCommonDataModel import vtkTetra
                from vtkmodules.vtkFiltersVerdict import vtkCellSizeFilter
                from fespp_on_trame.engine import volumetrics_dispatch as vd
                gid = _find_node_by_title(tree, step["grid"], step.get("under"))
                rid = tree.find_representation_node(gid) if gid is not None else None
                rep_path = tree.find_path(rid) if rid is not None else None
                sr = getattr(server.context, "source_registry", None)
                ds = vd._largest_block(sr.shared_source(), rep_path) if rep_path else None
                if ds is None:
                    raise RuntimeError(f"cell_volume_probe: no block for {step['grid']!r}")
                f = vtkCellSizeFilter()
                f.SetInputData(ds)
                f.ComputeVolumeOn()
                f.ComputeAreaOff()
                f.ComputeLengthOff()
                f.ComputeVertexCountOff()
                f.Update()
                vol = _v2n(f.GetOutput().GetCellData().GetArray("Volume"))
                ghost = ds.GetCellData().GetArray("vtkGhostType")
                shown = _np.ones(len(vol), bool) if ghost is None else ((_v2n(ghost) & 32) == 0)
                bad = _np.where(shown & ~(_np.isfinite(vol) & (vol > 0)))[0]
                _log(out, f"cell volumes ({ds.GetClassName()}): {int(shown.sum())} visible of {len(vol)},"
                          f" {len(bad)} with a volume <= 0 or NaN"
                          f" (<0: {int(_np.sum(shown & (vol < 0)))}, ==0: {int(_np.sum(shown & (vol == 0)))},"
                          f" NaN: {int(_np.sum(shown & ~_np.isfinite(vol)))});"
                          f" total visible volume {float(_np.nansum(_np.where(shown, vol, 0))):.6g}")
                for i in bad[:int(step.get("limit", 4))]:
                    cell = ds.GetCell(int(i))
                    corners = [[round(c, 2) for c in ds.GetPoint(cell.GetPointId(k))]
                               for k in range(cell.GetNumberOfPoints())]
                    ids, pts = vtkIdList(), vtkPoints()
                    cell.Triangulate(0, ids, pts)
                    tets = 0.0
                    for t in range(0, pts.GetNumberOfPoints(), 4):
                        tets += vtkTetra.ComputeVolume(*(pts.GetPoint(t + k) for k in range(4)))
                    distinct = len({tuple(c) for c in corners})
                    _log(out, f"  cell {int(i)} type {cell.GetClassName()} filter={float(vol[i]):.6g}"
                              f" tetra-sum={tets:.6g} distinct corners {distinct}/{len(corners)}"
                              f" corners={corners}")
            elif op == "volumetrics_probe":
                # Volumetrics on a grid named by title: its property nodes
                # (with kinds) are listed, the porosity / NTG / Sw / region
                # picked as the panel would, ticked so they load, the
                # contacts placed at a third and two thirds of the grid's
                # depth range, then the table is computed and its totals
                # logged — the numbers are the assertion.
                from fespp_on_trame.engine import volumetrics_dispatch as vd
                gid = _find_node_by_title(tree, step.get("grid") or step.get("prop"),
                                          step.get("under"))
                if gid is None:
                    raise RuntimeError(f"node not found: {step.get('grid') or step.get('prop')!r}")
                rid = tree.find_representation_node(gid)
                rep_path = tree.find_path(rid) if rid is not None else None
                _log(out, f"volumetrics rep: {tree.find_title(rid)!r} type={tree.find_type(rid)!r}")
                # a lazy ETP load left the grid's properties on the store: their
                # kinds come with them, in one request (a no-op on a file)
                try:
                    from fespp_on_trame.engine import repo_query as _rq
                    _reg = getattr(server.context, "source_registry", None)
                    _src = _reg.shared_source() if _reg is not None else None
                    _leaf = (rep_path or "").rsplit("/", 1)[-1]
                    if _src is not None and _leaf.startswith("_"):
                        _rq.lazy_fetch(_src, 3000, 0, [_leaf[1:]])
                except Exception as exc:
                    _log(out, f"volumetrics: the grid's properties were not read from the store: {exc}")
                props = []
                for nid in tree.find_all_descendant_ids(0):
                    if not node_facts.is_property_kind(tree.find_type(nid) or ""):
                        continue
                    if tree.find_representation_node(nid) != rid:
                        continue
                    props.append({
                        "path": tree.find_path(nid),
                        "title": tree.find_title(nid) or "",
                        "kind": tree.find_attribute_value(nid, "propertyKind") or "",
                        "unit": tree.find_attribute_value(nid, "uom") or "",
                        "type": tree.find_prop_type(nid) or tree.find_type(nid) or "",
                    })
                _log(out, f"volumetrics rep {rep_path[-30:]!r}: {len(props)} properties: "
                          f"{[(p['title'], p['kind'], p['unit'], p['type']) for p in props][:30]}")
                picks = vd.auto_pick(props)
                _log(out, f"volumetrics picks: "
                          f"{ {k: (next((p['title'] for p in props if p['path'] == v), None)) for k, v in picks.items()} }")
                want = [v for v in picks.values() if v]
                with state:
                    cur = list(getattr(state, "selected_paths", None) or [])
                    controller.select_paths(
                        cur + [p for p in want if p not in cur])
                await asyncio.sleep(float(step.get("settle") or 10))
                sr = getattr(server.context, "source_registry", None)
                # what the arithmetic will index: the dataset the values
                # point at, and the values themselves, must agree in length
                try:
                    from fespp_on_trame.engine import trajectory_sampling as _ts
                    from fespp_on_trame.engine.property_values import values_for as _vf
                    ds = None
                    for k, v in picks.items():
                        if not v:
                            continue
                        ds = _ts._dataset_of(state, sr, tree, v, rep_path)
                        vals = _vf(state, tree, sr, v, rep_path)
                        _log(out, f"  {k}: dataset={ds.GetClassName() if ds is not None else None}"
                                  f" cells={ds.GetNumberOfCells() if ds is not None else None}"
                                  f" values={None if vals is None else len(vals)}")
                    if ds is None:
                        ds = vd._largest_block(sr.shared_source(), rep_path)
                        _log(out, f"  block: dataset={ds.GetClassName() if ds is not None else None}"
                                  f" cells={ds.GetNumberOfCells() if ds is not None else None}")
                    # every property of the rep, read through the seam: the
                    # value count must be the block's cell count
                    for p in props[:4]:
                        vals = _vf(state, tree, sr, p["path"], rep_path)
                        _log(out, f"  values {p['title']!r}: {None if vals is None else len(vals)}")
                    if ds is not None:
                        from vtkmodules.vtkFiltersCore import vtkCellCenters
                        from vtkmodules.vtkFiltersVerdict import vtkCellSizeFilter
                        f = vtkCellSizeFilter()
                        f.SetInputData(ds)
                        f.ComputeVolumeOn()
                        f.Update()
                        c = vtkCellCenters()
                        c.SetInputData(ds)
                        c.VertexCellsOff()
                        c.Update()
                        ghost = ds.GetCellData().GetArray("vtkGhostType")
                        _log(out, f"  geometry: size-filter cells={f.GetOutput().GetNumberOfCells()}"
                                  f" volume tuples={f.GetOutput().GetCellData().GetArray('Volume').GetNumberOfTuples()}"
                                  f" centres={c.GetOutput().GetNumberOfPoints()}"
                                  f" ghost array={'yes' if ghost is not None else 'no'}"
                                  f" conn={ds.GetCells().GetNumberOfCells() if hasattr(ds, 'GetCells') else '?'}")
                except Exception as exc:
                    _log(out, f"  index check failed: {exc}")
                try:
                    b = list(sr.shared_source().GetDataInformation().GetBounds())
                    d0, d1 = -b[5], -b[4]          # depth positive down
                except Exception:
                    d0, d1 = 0.0, 1.0
                goc = step.get("goc", d0 + (d1 - d0) / 3.0)
                owc = step.get("owc", d0 + 2.0 * (d1 - d0) / 3.0)
                _log(out, f"volumetrics depths: {d0:.1f}..{d1:.1f} goc={goc:.1f} owc={owc:.1f}")
                # the card is a tool of the active 3D view
                vid = getattr(state, "fespp_active_panel_id", "") or "view_1"
                with state:
                    controller.volumetrics_set("grid", rep_path, vid)
                    for k, v in picks.items():
                        controller.volumetrics_set(k, v or "", vid)
                    controller.volumetrics_set("goc", goc, vid)
                    controller.volumetrics_set("owc", owc, vid)
                    controller.volumetrics_set("show_contacts", True, vid)
                    # the surface factors of the step, when it gives them:
                    # the HCPV of the oil / gas zones to STOIIP / GIIP
                    for k in ("bo", "bg", "rf_oil", "rf_gas"):
                        if step.get(k) is not None:
                            controller.volumetrics_set(k, step[k], vid)
                    res = controller.volumetrics_compute(vid)
                _log(out, f"volumetrics: cells={res.get('cells')} active={res.get('active')}"
                          f" no_volume={res.get('no_volume')}"
                          f" rows={len(res.get('rows') or [])} note={res.get('note')!r}")
                for r in res.get("totals") or []:
                    _log(out, f"  {r['region']} | {r['fluid']} | cells={r['cells']}"
                              f" grv={r['grv']:.4g} nrv={r['nrv']:.4g}"
                              f" pv={r['pv'] if r['pv'] is None else round(r['pv'], 1)}"
                              f" hcpv={r['hcpv'] if r['hcpv'] is None else round(r['hcpv'], 1)}"
                              f" stoiip={r.get('stoiip') if r.get('stoiip') is None else round(r['stoiip'], 1)}"
                              f" giip={r.get('giip') if r.get('giip') is None else round(r['giip'], 1)}")
                sf = res.get("surface") or {}
                if sf.get("bo") or sf.get("bg"):
                    # the arithmetic of the surface columns, on the zones the
                    # contacts name: STOIIP = HCPV / Bo on the oil zone, GIIP
                    # = HCPV / Bg on the gas zone, nothing on the water, the
                    # total the sum of both
                    tot = {r["fluid"]: r for r in res.get("totals") or []}
                    oil = next((r for f, r in tot.items() if f.startswith("oil")), None)
                    gas = next((r for f, r in tot.items() if f.startswith("gas")), None)
                    water = next((r for f, r in tot.items() if f.startswith("water")), None)
                    if oil is not None and sf.get("bo") and oil["hcpv"]:
                        if abs(oil["stoiip"] - oil["hcpv"] / sf["bo"]) > 1e-6 * oil["hcpv"]:
                            raise RuntimeError("volumetrics_probe: STOIIP is not HCPV / Bo")
                    if gas is not None and sf.get("bg") and gas["hcpv"]:
                        if abs(gas["giip"] - gas["hcpv"] / sf["bg"]) > 1e-6 * gas["hcpv"]:
                            raise RuntimeError("volumetrics_probe: GIIP is not HCPV / Bg")
                    if water is not None and (water.get("stoiip") or water.get("giip")):
                        raise RuntimeError("volumetrics_probe: the water zone has a surface volume")
                    grand = tot.get("total") or {}
                    if oil is not None and grand.get("stoiip") is not None and oil.get("stoiip") is not None:
                        if abs(grand["stoiip"] - oil["stoiip"]) > 1e-6 * max(1.0, oil["stoiip"]):
                            raise RuntimeError("volumetrics_probe: the total's STOIIP is not the oil zone's")
                    _log(out, f"volumetrics surface: {sf} fluid={res.get('surface_fluid')!r}")
                for r in (res.get("rows") or [])[:6]:
                    _log(out, f"  {r['region']} (code {r.get('region_code')}) | {r['fluid']}"
                              f" | cells={r['cells']} grv={r['grv']:.4g}")
                # the export the card's Copy CSV writes: its dated name and
                # the provenance header the widget puts over the raw rows
                csv = vd.csv_payload(res)
                _log(out, f"volumetrics csv: name={csv['name']!r}"
                          f" header={len(csv['header'])} lines")
                for line in csv["header"][2:-1]:
                    _log(out, f"  {line}")

            elif op == "weights_probe":
                # What the Statistics view means by "Mean (V)" and
                # "Mean (PV)": the very cell volumes the Volumetrics card
                # cubes. The three means of one property, side by side, and
                # the count of cells that carried a usable weight.
                from fespp_on_trame.engine import cell_weights
                from fespp_on_trame.engine import stats_dispatch as _sd
                from fespp_on_trame.engine.property_values import values_for as _vf

                def _expect(cond, what):
                    if not cond:
                        raise RuntimeError(f"weights_probe: {what}")

                gid = _find_node_by_title(tree, step.get("grid"), step.get("under"))
                if gid is None:
                    raise RuntimeError(f"node not found: {step.get('grid')!r}")
                rid = tree.find_representation_node(gid)
                rep_path = tree.find_path(rid) if rid is not None else None
                pid = _find_node_by_title(tree, step.get("prop"),
                                          step.get("under") or step.get("grid"))
                if pid is None:
                    raise RuntimeError(f"node not found: {step.get('prop')!r}")
                prop_path = tree.find_path(pid)
                with state:
                    cur = list(getattr(state, "selected_paths", None) or [])
                    if prop_path not in cur:
                        controller.select_paths(cur + [prop_path])
                await asyncio.sleep(float(step.get("settle") or 8))
                sr = getattr(server.context, "source_registry", None)
                cell_weights.clear()
                w = cell_weights.weights_for(state, tree, sr, rep_path)
                vol, pore = w.get("volume"), w.get("pore")
                _log(out, f"weights on {rep_path[-30:]!r}: cells={w.get('n')}"
                          f" poro={w.get('poro_title')!r} ntg={w.get('ntg_title')!r}"
                          f" volume={'yes' if vol is not None else 'no'}"
                          f" pore={'yes' if pore is not None else 'no'}"
                          f" note={w.get('note')!r}")
                _expect(vol is not None,
                        f"no cell volume on {rep_path!r}: {w.get('note')!r}")
                vals = _vf(state, tree, sr, prop_path, rep_path)
                _expect(vals is not None and len(vals) == w["n"],
                        f"{step.get('prop')!r}: {0 if vals is None else len(vals)}"
                        f" values for {w['n']} cells")
                row = _sd._row_stats_from_values(vals, step.get("prop") or "",
                                                 volume=vol, pore_volume=pore)
                _log(out, f"weights {step.get('prop')!r}:"
                          f" Cardinality={row.get('Cardinality')}"
                          f" weighted_n={row.get('weighted_n')}"
                          f" Mean={row.get('Mean')!r}"
                          f" Mean (V)={row.get('Mean (V)')!r}"
                          f" Mean (PV)={row.get('Mean (PV)')!r}")
                want_n = step.get("weighted_n")
                if want_n == "card":
                    # The cells the Volumetrics card counts, whatever VTK
                    # makes of them: vtkCellSizeFilter gives a collapsed
                    # hexahedron (top face on the bottom face, 4 distinct
                    # corners of 8) a spurious non-zero volume in VTK 9.5
                    # and ZERO in 9.6 (ParaView 6.1), so the weighed cell
                    # count depends on the VTK version. A pinned count would
                    # pin the VTK version; this pins that both cards weigh
                    # the same cells.
                    _vid0 = getattr(state, "fespp_active_panel_id", "") or "view_1"
                    _t0 = state.to_dict().get(f"ui_volumetrics__{_vid0}") or {}
                    _all = next((t for t in (_t0.get("totals") or [])
                                 if t.get("region") == "all"
                                 and t.get("fluid") == "total"), None)
                    _expect(_all is not None and bool(_all.get("cells")),
                            "weighted_n 'card': no Volumetrics total to compare")
                    want_n = _all["cells"]
                    _log(out, f"  weighted_n against the Volumetrics card: {want_n}"
                              f" ({_t0.get('no_volume')!r} cells without a volume)")
                if want_n is not None:
                    _expect(row.get("weighted_n") == int(want_n),
                            f"weighted_n {row.get('weighted_n')} != {int(want_n)}")
                mv = row.get("Mean (V)")
                _expect(mv is not None and 0.0 < mv < 1.0,
                        f"Mean (V) = {mv!r}, expected a fraction")
                _expect(mv != row.get("Mean"),
                        "Mean (V) equals Mean: the cells are not being weighed")
                # THE WEIGHTS ARE THE VOLUMETRICS CARD'S OWN CELLS: summed,
                # they must BE that card's totals — the bulk volume its GRV,
                # the pore volume its PV. Two panels, two code paths, one
                # number, or "Mean (V)" and "PV" describe different rock.
                import numpy as _np
                _vid = getattr(state, "fespp_active_panel_id", "") or "view_1"
                _tbl = state.to_dict().get(f"ui_volumetrics__{_vid}") or {}
                _tot = next((t for t in (_tbl.get("totals") or [])
                             if t.get("region") == "all"
                             and t.get("fluid") == "total"), None)
                sums = {"GRV": float(_np.nansum(vol)),
                        "PV": None if pore is None else float(_np.nansum(pore))}
                _log(out, f"weights summed: GRV={sums['GRV']:.10g}"
                          f" PV={sums['PV']!r} against the volumetrics card"
                          f" GRV={(_tot or {}).get('grv')!r}"
                          f" PV={(_tot or {}).get('pv')!r}")
                for _name, _want in (("GRV", (_tot or {}).get("grv")),
                                     ("PV", (_tot or {}).get("pv"))):
                    _got = sums[_name]
                    if _got is None or _want is None:
                        continue
                    if abs(_got - _want) > 1e-9 * max(1.0, abs(_want)):
                        raise RuntimeError(
                            f"the weights do not sum to the Volumetrics card's"
                            f" {_name}: {_got!r} against {_want!r} — the"
                            " Statistics view is weighing other cells")
                # WHAT THE ROW SAYS OF ITS WEIGHTS. On the porosity term
                # itself the pore weight IS the property, so Mean (PV) is
                # that property weighted by itself and reads well above the
                # net-rock-weighted average the Volumetrics card implies
                # (PV / NRV). A reader must not be left with three averages
                # and no word about it.
                _note = _sd._weights_note(tree, prop_path, w, [row])
                _log(out, f"weights note: {_note!r}")
                if prop_path == w.get("poro_path"):
                    _nrv = (_tot or {}).get("nrv")
                    _log(out, f"  PV / NRV = "
                              f"{(sums['PV'] / _nrv) if _nrv else None!r}"
                              f" against Mean (PV) = {row.get('Mean (PV)')!r}")
                    _expect("weighted by itself" in _note,
                            "the row is silent about a property weighted by"
                            f" its own pore volume: note={_note!r}")

            elif op == "pick_probe":
                # A click in the middle of the first 3D view, in pick mode:
                # the readout must name the cell (its index, its I J K on an
                # IJK grid) and the colouring property by its DISPLAY name
                # with the value, never by the VTK array name.
                # {"op": "pick_probe", "expect_label": "Facies"}
                mv0 = server.context.multi_view
                vids0 = list(mv0.view_ids() or []) if mv0 is not None else []
                if not vids0:
                    raise RuntimeError("pick_probe: no 3D view")
                pvid = vids0[0]
                pvv = mv0.get_pv_view(pvid)
                try:
                    w, h = [int(x) for x in pvv.ViewSize]
                except Exception:
                    w, h = _SHOT_RESOLUTION
                # {"at": "log_track"}: on the graph of a log (app/features/log_tracks), where it stands
                # farthest off its hole, rather than the middle of the view
                cx_, cy_ = w / 2, h / 2
                if step.get("at") == "log_track":
                    # the first pixel, row by row, where the cursor's ray meets a graph: the same
                    # convention as the click's, whatever size the window was left at
                    pvv.SMProxy.StillRender()
                    found_ = None
                    for j_ in range(24):
                        for i_ in range(24):
                            x_, y_ = int((i_ + 0.5) * w / 24), int((j_ + 0.5) * h / 24)
                            _pt, blk_ = controller.cursor_hit(pvid, x_, y_)
                            if blk_ == "log track":
                                found_ = (x_, y_)
                                break
                        if found_:
                            break
                    if found_ is None:
                        raise RuntimeError("pick_probe: the cursor meets no graph in the view")
                    cx_, cy_ = found_[0], h - found_[1]
                    _log(out, f"pick on a graph at the pixel ({found_[0]}, {found_[1]})")
                with state:
                    state[f"ui_pick_mode__{pvid}"] = True
                    controller.view_pick([cx_, cy_, cx_, cy_, w, h], pvid, "surface")
                await asyncio.sleep(2.0)
                info = getattr(state, f"ui_pick_info__{pvid}", "") or ""
                _log(out, f"pick readout: {info!r}")

                def _expect(cond, what):
                    if not cond:
                        raise RuntimeError(f"pick_probe: {what} — {info!r}")
                # {"op": "pick_probe", "expect_text": "Zone Index"}: what is under the middle
                # of the view is no grid — the readout names it, and that is all it is asked
                grid_ = not step.get("expect_text")
                _expect(grid_ or step["expect_text"] in info, f"the readout does not name {step.get('expect_text')!r}")
                _expect(not grid_ or "cell #" in info, "the readout names no cell")
                _expect(not grid_ or (" I " in info and " J " in info and " K " in info),
                        "the readout gives no I J K on an IJK grid")
                want = step.get("expect_label")
                if want:
                    _expect(want in info, f"the readout does not name {want!r}")
                    _expect(" = " in info, "the readout gives no value")
                with state:
                    state[f"ui_pick_mode__{pvid}"] = False


            elif op == "cursor_probe":
                # The crosshair readout: the world position of the surface
                # under the pointer. Fired through the SAME state variable
                # the browser's mousemove writes (`pos_ev__<vid>`), so the
                # whole chain is under test — the listener, the ray and the
                # wording — and not just the arithmetic.
                #
                # It also asks the ray DIRECTLY, and reports both answers:
                # an empty readout because the ray missed and an empty
                # readout because the readout is broken look identical on
                # screen, and they are not the same defect.
                # {"op":"cursor_probe"}
                mv0 = server.context.multi_view
                vids0 = list(mv0.view_ids() or []) if mv0 is not None else []
                if not vids0:
                    raise RuntimeError("cursor_probe: no 3D view")
                cvid = vids0[0]
                # {"globe": true}: the readout of the Globe view, a view of its own
                if step.get("globe"):
                    cvid = next(iter(mv0.panel_ids_of_kind("globe")), "")
                    if not cvid:
                        raise RuntimeError("cursor_probe: no Globe view is open")
                pvv = mv0.get_pv_view(cvid)
                try:
                    w, h = [int(x) for x in pvv.ViewSize]
                except Exception as exc:
                    _log(out, f"cursor_probe: no ViewSize ({exc}) — falling"
                              f" back to {_SHOT_RESOLUTION}")
                    w, h = _SHOT_RESOLUTION
                # Is there anything under the centre pixel at all, and by
                # which road? A Globe view is answered by a camera ray met
                # with the ellipsoid (never a pick: that one does not return
                # there); a plain 3D view by the surface pick, which answers
                # the DATA. The probe asks the same way the readout does, and
                # TIMES it — a road that does not come back is the defect
                # this scenario exists for.
                from fespp_on_trame.app.views import camera as _cam
                from fespp_on_trame.engine import geo as _geo
                _globe = bool(getattr(state, f"ui_globe_mode__{cvid}", False))
                t0 = time.monotonic()
                if _globe:
                    _ray = _cam.view_ray(pvv, int(w / 2), int(h / 2))
                    pt = _geo.ellipsoid_hit(*_ray) if _ray else None
                else:
                    # the readout's own road: a camera ray met with the drawn
                    # blocks' cell locators, never a selection render
                    pt, _blk = controller.cursor_hit(cvid, int(w / 2), int(h / 2))
                dt = time.monotonic() - t0
                raw = pt is not None
                _log(out, f"cursor ray ({cvid}): globe={_globe} size={w}x{h}"
                          f" hit={raw} took={dt * 1000:.1f}ms"
                          f" point={None if pt is None else [round(v, 2) for v in pt]}")
                if dt > float(step.get("max_ray_s", 5.0)):
                    raise RuntimeError(
                        f"cursor_probe: the road under the pointer took"
                        f" {dt:.2f}s")
                snapped = None
                # and now the readout, through the listener the browser drives
                with state:
                    state[f"ui_cursor_mode__{cvid}"] = True
                await asyncio.sleep(0.5)
                with state:
                    # the payload of the browser's throttled mousemove:
                    # [x, y, canvas width, canvas height]
                    state[f"pos_ev__{cvid}"] = [w / 2, h / 2, w, h]
                await asyncio.sleep(float(step.get("settle", 2)))
                said = getattr(state, f"ui_cursor_pos__{cvid}", "") or ""
                _log(out, f"cursor readout ({cvid}): {said!r}")
                with state:
                    state[f"ui_cursor_mode__{cvid}"] = False
                if not (raw or snapped):
                    raise RuntimeError(
                        "cursor_probe: the ray found NO surface at the centre"
                        " pixel — either nothing is drawn there, or the depth"
                        " buffer read back empty (this is the assertion that"
                        " separates a miss from a broken readback)")
                if not said:
                    raise RuntimeError(
                        "cursor_probe: the ray hit but the readout is EMPTY —"
                        " the crosshair says nothing")
                # the vertical is named whatever the scene is: an elevation
                # in the data's own CRS, a height above the ellipsoid on the
                # Earth. A readout that gives two ordinates and no third is
                # the defect this catches.
                if not ("elevation" in said or "ellipsoid" in said):
                    raise RuntimeError(
                        f"cursor_probe: the readout names no vertical — {said!r}")
                # the block is named on the readout's second line, under the
                # position ("Geogrid   cell I 46 J 74 K 1")
                lines = said.split("\n")
                if step.get("block", False) and not (len(lines) > 1 and lines[1].strip()):
                    raise RuntimeError(
                        "cursor_probe: the readout names no VTK block —"
                        f" {said!r}")
                for token in (step.get("expect") or []):
                    if str(token) not in said:
                        raise RuntimeError(
                            f"cursor_probe: the readout does not carry"
                            f" {token!r} — {said!r}")

            elif op == "health_probe":
                # The Data health table as the panel would carry it: the
                # summary, then every finding — the counts are the assertion
                res = controller.health_compute()
                s = res.get("summary") or {}
                _log(out, f"health: errors={s.get('errors')} warnings={s.get('warnings')}"
                          f" infos={s.get('infos')} objects={s.get('objects')}"
                          f" partial={s.get('partial')} types={s.get('types')}"
                          f" note={res.get('note')!r}")
                by_cat, shown = {}, {}
                for f in res.get("findings") or []:
                    k = (f["severity"], f["category"])
                    by_cat[k] = by_cat.get(k, 0) + 1
                _log(out, f"health by category: {sorted(by_cat.items())}")
                for f in res.get("findings") or []:
                    k = (f["severity"], f["category"])
                    if shown.get(k, 0) >= 3:
                        continue
                    shown[k] = shown.get(k, 0) + 1
                    _log(out, f"  [{f['severity']}] {f['category']} | {f['object'][:40]} | {f['message'][:220]}")
                with state:
                    state.ui_health = res
                # a finding tied to an object: activating it must reach a
                # 3D view — its active node set, its tree card open — so the
                # click made behind the health panel shows something
                first = next((f for f in res.get("findings") or [] if f.get("path")), None)
                mv0 = server.context.multi_view
                vids0 = list(mv0.view_ids() or []) if mv0 is not None else []
                if first is not None and vids0:
                    with state:
                        controller.health_activate(first["path"])
                    await asyncio.sleep(1.0)
                    hit = next((v for v in vids0
                                if getattr(state, f"active_path__{v}", "") == first["path"]), None)
                    _log(out, f"health activate {first['object'][:40]!r}: view={hit}"
                              f" tree open={'tree' in ((getattr(state, 'ui_open_tools_by_view', None) or {}).get(hit or '', []))}")
                    if hit is None:
                        raise RuntimeError("health_probe: activating a finding set no view's active node")
                    if "tree" not in ((getattr(state, "ui_open_tools_by_view", None) or {}).get(hit) or []):
                        raise RuntimeError("health_probe: the activated view's tree card is not open")

            elif op == "reconcile_panel_probe":
                # The Log ↔ Grid table AS THE PANEL CARRIES IT (ui_reconcile,
                # computed from both doors: the log view's wells and the
                # panel's own tree), and what its tree shows ticked.
                # {"op":"reconcile_panel_probe","expect_logs":["SW"],
                #  "expect_no_logs":["GR"],"expect_rows_min":1,
                #  "expect_welllog_wells":0,"expect_note_contains":"No log yet"}
                def _expect(cond, what):
                    _log(out, f"  {'OK ' if cond else 'FAIL'} {what}")
                    if not cond:
                        raise RuntimeError(f"reconcile_panel_probe: {what}")

                res = state.to_dict().get("ui_reconcile") or {}
                titles = [lg.get("title") for lg in res.get("logs") or []]
                mv = getattr(server.context, "multi_view", None)
                ids = list(mv.panel_ids_of_kind("reconcile")) if mv is not None else []
                ticks = list(getattr(state, f"reconcile_tree_selected__{ids[0]}", None)
                             or []) if ids else []
                _log(out, f"reconcile panel {ids}: wells={res.get('wells')} logs={titles[:12]}"
                          f"{' …' if len(titles) > 12 else ''} ({len(titles)})"
                          f" props={[p.get('title') for p in res.get('props') or []]}"
                          f" pairs={[(p.get('log'), (p.get('prop') or '')[-20:]) for p in res.get('pairs') or []][:6]}"
                          f" rows={len(res.get('rows') or [])} note={res.get('note')!r}")
                _log(out, f"  own logs={len(getattr(state, 'ui_reconcile_logs', None) or [])}"
                          f" dropped={len(getattr(state, 'ui_reconcile_dropped', None) or [])}"
                          f" log view wells={len(getattr(state, 'ui_welllog_wells', None) or [])}"
                          f" tree ticks={len(ticks)}")
                for t in step.get("expect_logs") or []:
                    _expect(t in titles, f"the table reads the log {t!r}")
                for t in step.get("expect_no_logs") or []:
                    _expect(t not in titles, f"the table no longer reads {t!r}")
                if step.get("expect_rows_min") is not None:
                    _expect(len(res.get("rows") or []) >= int(step["expect_rows_min"]),
                            f"{len(res.get('rows') or [])} row(s), at least {step['expect_rows_min']}")
                if step.get("expect_welllog_wells") is not None:
                    n = len(getattr(state, "ui_welllog_wells", None) or [])
                    _expect(n == int(step["expect_welllog_wells"]),
                            f"{n} well(s) in the log view, {step['expect_welllog_wells']} expected")
                if step.get("expect_note_contains"):
                    _expect(step["expect_note_contains"] in (res.get("note") or ""),
                            f"the note says {step['expect_note_contains']!r}")
                if step.get("expect_ticks_min") is not None:
                    _expect(len(ticks) >= int(step["expect_ticks_min"]),
                            f"{len(ticks)} tick(s) in the panel's tree, at least {step['expect_ticks_min']}")

            elif op == "reconcile_probe":
                # The Log ↔ Grid table as the panel would carry it: the logs
                # and grid properties the session offers with their kinds, the
                # pairs the kinds give, the first rows. `list_grid_props`
                # also names every grid-hosted property of the tree, loaded
                # or not, so a scenario can pick what to tick.
                from fespp_on_trame.engine import reconcile_dispatch
                sr = getattr(server.context, "source_registry", None)
                if step.get("list_grid_props"):
                    asm = tree._data_assembly
                    names, st = [], [0]
                    while st:
                        nid = st.pop()
                        t = tree.find_type(nid) or ""
                        if node_facts.is_property_kind(t):
                            rid = tree.find_representation_node(nid)
                            if rid is not None and (tree.find_type(rid) or "") in (
                                    "IjkGrid", "UnstructuredGrid"):
                                names.append((tree.find_title(nid), t,
                                              tree.find_attribute_value(nid, "propertyKind"),
                                              tree.find_attribute_value(nid, "uom")))
                        st.extend(asm.GetChildNodes(nid))
                    _log(out, f"grid properties in the tree ({len(names)}): {names[:40]}")
                res = reconcile_dispatch.compute(
                    state, tree, sr, pairs=None, step=float(step.get("step") or 1.0))
                _log(out, f"reconcile: wells={res.get('wells')} logs="
                          f"{[(l['title'], l.get('kind'), l.get('unit')) for l in res.get('logs') or []]}")
                _log(out, f"reconcile: props="
                          f"{[(p['title'], p.get('kind'), p.get('unit')) for p in res.get('props') or []]}")
                _log(out, f"reconcile: pairs="
                          f"{[(p['log'], p['prop'].rsplit('/', 1)[-1][:24], p['basis']) for p in res.get('pairs') or []]}")
                _log(out, f"reconcile: rows={len(res.get('rows') or [])} note={res.get('note')!r}")
                # why a pair gives no row: the sampled curve itself, and the
                # well's depth axis against the zones
                from fespp_on_trame.engine import trajectory_sampling, welllog_dispatch
                wells = list(getattr(state, "ui_welllog_wells", None) or [])
                for pr in (res.get("pairs") or [])[:4]:
                    for w in wells[:2]:
                        curve = trajectory_sampling.synthetic_curve(
                            state, tree, sr, w, pr["prop"], float(step.get("step") or 1.0))
                        if curve is None:
                            _log(out, f"  synthetic {pr['prop'][-24:]}: {trajectory_sampling.last_error()!r}")
                            continue
                        got = [s for s in curve["samples"] if s[0] is not None]
                        tvds = [s[1] for s in curve["samples"]]
                        _log(out, f"  synthetic {curve['name']!r}: samples={len(curve['samples'])}"
                                  f" in_grid={len(got)} tvd={min(tvds):.1f}..{max(tvds):.1f}"
                                  f" kind={curve['kind']!r} unit={curve['unit']!r}")
                payload = welllog_dispatch.build_payload(
                    tree, sr, wells, list(getattr(state, "selected_paths", None) or []),
                    strati_columns=getattr(state, "ui_strati_columns", None))
                for w in payload.get("wells") or []:
                    zones, src = welllog_dispatch.zone_intervals(w)
                    _log(out, f"  well {w.get('name')!r}: depthRef={w.get('depthRef')}"
                              f" depth={w.get('depth')} zones={len(zones)} ({src})"
                              f" tops={len(w.get('tops') or [])}")
                # THE PROMISE, ON REAL DATA: adding a synthetic log changes
                # the DRAWN axis and nothing else. A sampled grid curve
                # carries no measured depth, so the whole well falls back to
                # the vertical for drawing; every summation is integrated on
                # the vertical either way, so the same cutoff must give the
                # same gross, net, N/G and Φ·h zone by zone.
                synth = trajectory_sampling.curves_for(
                    state, tree, sr,
                    [{"well": w, "prop": p,
                      "step": float(step.get("step") or 1.0)}
                     for w in wells
                     for p in sorted({pr["prop"] for pr in res.get("pairs") or []})])
                p2 = welllog_dispatch.build_payload(
                    tree, sr, wells,
                    list(getattr(state, "selected_paths", None) or []),
                    strati_columns=getattr(state, "ui_strati_columns", None),
                    synthetics=synth)
                _KEYS = ("thickness_tvd", "net", "ntg", "phih", "hcph")
                for w1, w2 in zip(payload.get("wells") or [],
                                  p2.get("wells") or []):
                    z0 = next((z for z in (w1.get("zones") or [])
                               if z.get("curves")), None)
                    if z0 is None:
                        _log(out, "  synthetic-log invariance skipped: no zone"
                                  " of this well holds a curve sample")
                        continue
                    c0 = z0["curves"][0]
                    rule = [{"curve": c0["name"], "op": ">=",
                             "value": c0["p50"]}]
                    a, b = (welllog_dispatch.with_cutoffs(
                        {"wells": [w]}, rule)["wells"][0] for w in (w1, w2))

                    def _fig(well):
                        return {(z["name"], z.get("top_tvd")):
                                tuple(z.get(k) for k in _KEYS)
                                for z in well.get("zones") or []}
                    fa, fb = _fig(a), _fig(b)
                    z1 = next(iter(sorted(fa)), None)
                    _log(out, f"  synthetic-log invariance on {w1.get('name')!r}:"
                              f" depthRef {w1.get('depthRef')} -> {w2.get('depthRef')}"
                              f" synthetics={len(synth.get(wells[0]) or [])}"
                              f" cutoff {c0['name']!r} >= {c0['p50']:.6g}"
                              f" zones={len(fa)}/{len(fb)}"
                              f" first {z1} -> {fa.get(z1)}")
                    moved = [k for k in set(fa) | set(fb)
                             if fa.get(k) != fb.get(k)]
                    if moved:
                        raise RuntimeError(
                            f"{len(moved)} zone(s) of {w1.get('name')!r} report"
                            f" a different gross / net / N/G / Φ·h once a"
                            f" synthetic log is added, first {moved[0]}:"
                            f" {fa.get(moved[0])} against {fb.get(moved[0])} —"
                            " the drawing axis is leaking into the summation")
                for r in (res.get("rows") or [])[:10]:
                    ml = r.get("mean_grid_len")
                    _log(out, f"  {r['well']} | {r['zone']} | {r['log']} vs {r['prop']}"
                              f" | n={r['n_log']}/{r['n_grid']}"
                              f" mean={r['mean_log']:.4g}/{r['mean_grid']:.4g}"
                              f" mean_grid_len={'none' if ml is None else f'{ml:.4g}'}"
                              f" len={r.get('len_grid'):.2f}"
                              f" z={r['z']} flags={r['flags']}")
                    # the quantity class of both sides, disclosed on every row
                    # whether or not it rejects anything
                    _log(out, f"    class: log={r.get('class_log')!r}"
                              f" grid={r.get('class_grid')!r}"
                              f" checked={r.get('class_checked')}"
                              f" mismatch={r.get('class_mismatch')}")
                rows = res.get("rows") or []
                bad = [r for r in rows if r.get("class_mismatch")]
                if bad:
                    raise RuntimeError(
                        f"{len(bad)} row(s) pair two different quantity classes,"
                        f" first {bad[0]['log']} vs {bad[0]['prop']}"
                        f" ({bad[0]['class_log']} / {bad[0]['class_grid']}) —"
                        f" the guard must reject nothing on this data")
                want = step.get("expect_rows")
                if want is not None and len(rows) != want:
                    raise RuntimeError(f"{len(rows)} rows, expected {want}: the"
                                       " quantity-class guard must neither drop"
                                       " nor add a row on this data")
                with state:
                    state.ui_reconcile = res

            elif op == "array_probe":
                # Every loaded array as the app reads it: the VTK shape, what
                # the value seam hands back, and the assembly's component
                # count — the three must agree for a vector property.
                from fespp_on_trame.engine import stats_dispatch as sd
                from fespp_on_trame.engine.property_values import (
                    _named_and_ghost, values_for,
                )
                sr = getattr(server.context, "source_registry", None)
                snap = state.to_dict()
                loaded = list(snap.get("ui_loaded_array_paths") or [])
                _log(out, f"loaded arrays: {len(loaded)}")
                for p in loaded:
                    rp = sd._rep_path_for_array_path(tree, p)
                    title, _k, vtk_name = sd._resolve_vtk_name(tree, p)
                    src, real = sd._original_source_and_name(
                        state, sr, tree, p, rp, vtk_name, title)
                    arr, _g = _named_and_ghost(src, real or vtk_name)
                    comp = {}
                    for key in ("ui_vector_component",):
                        comp = dict(snap.get(key) or {})
                    vals = values_for(state, tree, sr, p, rp)
                    nid = tree.find_node_id(p)
                    _log(out, f"array {title!r}:"
                              f" components={arr.GetNumberOfComponents() if arr is not None else None}"
                              f" tuples={arr.GetNumberOfTuples() if arr is not None else None}"
                              f" values_for={None if vals is None else len(vals)}"
                              f" attr={tree.find_attribute_value(nid, 'componentCount')!r}"
                              f" chosen={comp.get(p)!r}")
                    if vals is not None and len(vals):
                        finite = [float(x) for x in vals if x == x]
                        _log(out, f"  values: finite={len(finite)}"
                                  f" min={min(finite) if finite else None}"
                                  f" max={max(finite) if finite else None}")
                # {"pick": {"title": "velocity", "component": 0}} — choose a
                # component through the controller, then read back what the
                # value seam and the LUT say
                pick = step.get("pick")
                if pick:
                    target = next((q for q in loaded
                                   if sd._resolve_vtk_name(tree, q)[0] == pick["title"]),
                                  None)
                    if target is None:
                        raise RuntimeError(f"pick: no loaded array titled {pick['title']!r}")
                    with state:
                        controller.set_vector_component(target, pick.get("component"))
                    await asyncio.sleep(1.0)
                    rp = sd._rep_path_for_array_path(tree, target)
                    vals = values_for(state, tree, sr, target, rp)
                    finite = [float(x) for x in vals if x == x] if vals is not None else []
                    vname = sd._resolve_vtk_name(tree, target)[2]
                    lut = pvsimple.GetColorTransferFunction(vname)
                    vreg = getattr(server.context, "view_resources", None)
                    vsc = vreg.get("view_1") if vreg is not None else None
                    slut = vsc.get_or_create_lut(vname) if vsc is not None else None
                    _log(out, f"scoped lut: {slut.VectorMode if slut is not None else None}"
                              f"/{slut.VectorComponent if slut is not None else None}")
                    _log(out, f"picked {pick['title']!r}"
                              f" component={pick.get('component')!r}:"
                              f" values_for={None if vals is None else len(vals)}"
                              f" min={min(finite) if finite else None}"
                              f" max={max(finite) if finite else None}"
                              f" lut={lut.VectorMode}/{lut.VectorComponent}"
                              f" chosen={(state.to_dict().get('ui_vector_component') or {}).get(target)!r}")

            elif op == "value_action_guard_probe":
                # The four actions that read VALUES, aimed at a node that has
                # none (a grid, a folder, a well): whatever the door — the 3D
                # right-click resolves a pick to a representation — they must
                # refuse it and say why, not open an empty card.
                # {"op":"value_action_guard_probe","title":"velocity",
                #  "rep":true} — "rep" aims at the representation the node
                # rides on, which is what a pick in the 3D view resolves to.
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                if step.get("rep"):
                    nid = tree.find_representation_node(nid)
                    if nid is None:
                        raise RuntimeError(
                            f"no representation over {step['title']!r}")
                path = tree.find_path(nid)
                snap = state.to_dict()
                before = (len(snap.get("ui_compare_items") or []),
                          len(snap.get("ui_crossplot_panels") or []),
                          len(snap.get("ui_calc_panels") or []))
                for method in ("add_to_stats", "open_calculator"):
                    state.empty_color_snackbar_text = ""
                    with state:
                        getattr(controller, method)(path)
                    await asyncio.sleep(1.0)
                    note = getattr(state, "empty_color_snackbar_text", "")
                    _log(out, f"guard {method} on {path!r}"
                              f" ({tree.find_type(nid)!r}): note={note!r}")
                    if not note:
                        raise RuntimeError(
                            f"value_action_guard_probe: {method} said nothing"
                            f" on {step['title']!r}")
                    # the refusal names the node clicked in the tree's own
                    # words — a grid's geometry leaf or its properties folder
                    # is said as such WITH its grid, never as the grid alone
                    if "/_propsfolder_" in path:
                        kind = tree.find_type(nid) or ""
                        want = ("The properties folder of "
                                if kind == "PropertiesFolder"
                                else "The geometry of ")
                        if not note.startswith(want):
                            raise RuntimeError(
                                f"value_action_guard_probe: the refusal on a"
                                f" {kind!r} under a properties folder should"
                                f" start with {want!r}: {note!r}")
                snap = state.to_dict()
                after = (len(snap.get("ui_compare_items") or []),
                         len(snap.get("ui_crossplot_panels") or []),
                         len(snap.get("ui_calc_panels") or []))
                _log(out, f"guard: panels {before} -> {after}")
                if after != before:
                    raise RuntimeError(
                        "value_action_guard_probe: a panel opened on a node"
                        f" that carries no values ({before} -> {after})")

            elif op == "vector_component_probe":
                # A vector property and a RECIPE over it, read at each
                # component the session can choose: the values must MOVE with
                # the choice (an entry cached without it keeps serving the
                # previous component) and every label must say which one it
                # shows. {"op":"vector_component_probe","grid":"Grid",
                #  "prop":"velocity","name":"twice","expr":"2 * velocity",
                #  "components":["magnitude",0,1,2]}
                from fespp_on_trame.engine import compare_dispatch as _cd
                from fespp_on_trame.engine import crossplot_dispatch as _xd
                from fespp_on_trame.engine import derived_props as _dp
                from fespp_on_trame.engine import property_values as _pv
                from fespp_on_trame.engine import stats_dispatch as _sd
                gid = _find_node_by_title(tree, step.get("grid") or step["prop"],
                                          step.get("under"))
                if gid is None:
                    raise RuntimeError(f"node not found: {step.get('grid')!r}")
                rid = tree.find_representation_node(gid)
                rep_path = tree.find_path(rid) if rid is not None else None
                prop_path = _prop_path_under(tree, rid, step["prop"])
                sr = getattr(server.context, "source_registry", None)
                store = _dp.get_store()
                name = step.get("name") or "vec2"
                err, d = store.create(state, tree, rep_path, name,
                                      step.get("expr") or f"2 * {step['prop']}")
                if err:
                    # the recipe is the half that goes through the derived
                    # cache — the very thing this probe watches
                    raise RuntimeError(
                        f"vector_component_probe: recipe {name!r}: {err}")
                der_path = _dp.path_for(rep_path, d["name"])
                _log(out, f"vector: recipe {name!r} on {step['prop']!r}:"
                          f" {der_path}")
                with state:
                    controller.add_to_stats(prop_path)
                await asyncio.sleep(2.0)
                readings = []
                for comp in (step.get("components") or ["magnitude", 0, 1, 2]):
                    with state:
                        controller.set_vector_component(prop_path, comp)
                    await asyncio.sleep(2.0)
                    snap = state.to_dict()
                    vals = _pv.values_for(state, tree, sr, prop_path, rep_path)
                    fin = [float(x) for x in (vals if vals is not None else [])
                           if x == x]
                    der = store.evaluate(state, tree, sr, der_path)
                    dfin = [float(x) for x in (der if der is not None else [])
                            if x == x]
                    if not fin or not dfin:
                        raise RuntimeError(
                            f"vector_component_probe: nothing read at"
                            f" component {comp!r}"
                            f" (property {len(fin)}, recipe {len(dfin)})")
                    lbl = _pv.component_label(state, tree, prop_path)
                    labels = {
                        "statistics row": next(
                            (r.get("title", "") for r in (snap.get("ui_compare_rows") or {}).values()
                             if r.get("path") == prop_path), ""),
                        "crossplot": _xd._axis_title(state, tree, prop_path),
                        "compare": _cd._row_label(state, tree, prop_path,
                                                  None, None),
                    }
                    # the Colormap card and the 3D colour bar say the same
                    # thing — when they show THIS property. The card edits
                    # the active node's array; the view shows ONE bar, that
                    # table's when it paints the view, another's otherwise
                    # (engine/legends: a property whose eye lost its rep to
                    # another one paints nothing, its bar would describe
                    # colours that are not on screen) — so only a bar of
                    # THIS property's table is read.
                    vid = _render_vid(server, state)
                    cmap = snap.get(f"ui_colormap__{vid}") or {}
                    vtk_name = _sd._resolve_vtk_name(tree, prop_path)[2]
                    if cmap.get("array") == vtk_name:
                        labels["colormap card"] = cmap.get("label", "")
                        scene = (getattr(server.context, "blockscope_scenes", None)
                                 or {}).get(vid)
                        if cmap.get("bar") and scene is not None:
                            key = scene.scoped_lut(vtk_name).GetGlobalIDAsString()
                            pvv = mv.get_pv_view(vid) if mv is not None else v
                            labels["colorbar"] = " | ".join(
                                str(r.Title) for r in pvv.Representations
                                if r.GetXMLName() == "ScalarBarWidgetRepresentation"
                                and int(getattr(r, "Visibility", 0))
                                and getattr(r, "LookupTable", None) is not None
                                and r.LookupTable.GetGlobalIDAsString() == key)
                    readings.append({
                        "comp": comp, "label": lbl,
                        "prop": _fingerprint(fin),
                        "derived": _fingerprint(dfin),
                        "prop_range": (min(fin), max(fin)),
                        "derived_range": (min(dfin), max(dfin)),
                    })
                    # the count published off the live array — what names
                    # the component of a property the assembly says nothing
                    # about (a time series, a multi-realization)
                    live_n = (snap.get("ui_vector_component_count")
                              or {}).get(prop_path)
                    if not live_n or int(live_n) < 2:
                        # what each source's data information lists: the
                        # count is read off what displays chain on
                        ads_ = getattr(server.context, "active_data_source", None)

                        def _cell_arrays(src_):
                            try:
                                cdi_ = src_.GetDataInformation().GetCellDataInformation()
                                return [(cdi_.GetArrayInformation(i).GetName(),
                                         cdi_.GetArrayInformation(i).GetNumberOfComponents())
                                        for i in range(cdi_.GetNumberOfArrays())]
                            except Exception as exc_:
                                return f"unreadable, error {exc_!r}"
                        if ads_ is not None:
                            _log(out, f"  display source cell arrays: {_cell_arrays(ads_.get_display_source())}")
                            _log(out, f"  reader cell arrays: {_cell_arrays(ads_.get_source())}")
                        raise RuntimeError(
                            f"vector_component_probe: no live component count"
                            f" published for {step['prop']!r} — a time-series"
                            f" or multi-realization property would then be"
                            f" labelled 'Component <n>' where the Colormap"
                            f" card says X")
                    _log(out, f"vector {step['prop']!r} component={comp!r}"
                              f" label={lbl!r} n={0 if vals is None else len(vals)}"
                              f" live_components={live_n!r}"
                              f" range={readings[-1]['prop_range']}"
                              f" recipe={readings[-1]['derived_range']}")
                    for k, v_lbl in labels.items():
                        _log(out, f"  {k} label: {v_lbl!r}")
                    tag = f"{_pv.COMPONENT_SEP}{lbl}"
                    for k, v_lbl in labels.items():
                        if not v_lbl:
                            continue
                        if lbl and tag not in v_lbl:
                            raise RuntimeError(
                                f"vector_component_probe: the {k} label"
                                f" {v_lbl!r} does not say {tag!r}")
                        if not lbl and _pv.COMPONENT_SEP in v_lbl:
                            raise RuntimeError(
                                f"vector_component_probe: the {k} label"
                                f" {v_lbl!r} names a component on the magnitude")
                for a, b in zip(readings, readings[1:]):
                    for key in ("prop", "derived"):
                        if a[key] == b[key]:
                            raise RuntimeError(
                                f"vector_component_probe: the {key} values did"
                                f" not move from component {a['comp']!r} to"
                                f" {b['comp']!r} (still"
                                f" {a[key + '_range']})")

            elif op == "colorbar_probe":
                # ONE colour bar per view (engine/legends), and the 3D bar
                # and the Colormap card carry ONE name for the property:
                # RESQML title, component read, unit. Refuses when the view
                # shows no bar or more than one, when the bar is not the
                # card's table, when the card's tool target is not that
                # text, when `expect` is not in it. The Legends card lists
                # every table colouring the view, the bar's marked.
                # {"op":"colorbar_probe","expect":"Temperature (K)"}
                # "none": true       — no bar (its box off, nothing coloured)
                # "legend_min": 11   — the Legends card lists at least 11 tables
                # "legend_has": ["GR"] — titles the list must carry
                # "pick": "GR"       — first pick the row whose title holds it,
                #                      the card's gesture, then check
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid) if mv is not None else v
                sch = getattr(server.context, "render_scheduler", None)

                def _drawn():
                    # the rows are published before each render: draw first
                    with state:
                        if sch is not None:
                            sch.mark_dirty(vid)
                            sch.flush()
                    snap_ = state.to_dict()
                    return snap_, ((snap_.get(f"ui_legends__{vid}") or {})
                                   .get("tables") or [])

                snap, rows = _drawn()
                if step.get("pick"):
                    row = next((r for r in rows if step["pick"] in r["title"]), None)
                    if row is None:
                        raise RuntimeError(
                            f"colorbar_probe: no legend row says {step['pick']!r}:"
                            f" {[r['title'] for r in rows]}")
                    with state:
                        controller.legend_pick(row["key"], vid)
                    snap, rows = _drawn()
                titles = []
                for r in pvv.Representations:
                    if (r.GetXMLName() == "ScalarBarWidgetRepresentation"
                            and int(getattr(r, "Visibility", 0))):
                        titles.append(str(r.Title))
                cmap = snap.get(f"ui_colormap__{vid}") or {}
                label = cmap.get("label", "")
                target = (snap.get(f"ui_tool_target__{vid}") or {}).get(
                    "colormap", "")
                marked = [r["title"] for r in rows if r.get("bar")]
                _log(out, f"colorbar: bars={titles!r} card={label!r}"
                          f" target={target!r} array={cmap.get('array')!r}"
                          f" legends={len(rows)} marked={marked!r}")
                if step.get("none"):
                    if titles or marked:
                        raise RuntimeError(
                            f"colorbar_probe: a bar is shown ({titles!r},"
                            f" marked {marked!r}), none expected")
                else:
                    if len(titles) != 1:
                        raise RuntimeError(
                            f"colorbar_probe: {len(titles)} bar(s) {titles!r},"
                            " one expected")
                    # a flat field says so on its bar, after the name
                    if titles[0] != label and not titles[0].startswith(
                            label + " — constant"):
                        raise RuntimeError(
                            f"colorbar_probe: the card says {label!r}, the"
                            f" bar {titles[0]!r}")
                    if marked != titles:
                        raise RuntimeError(
                            f"colorbar_probe: the Legends card marks {marked!r},"
                            f" the view shows {titles!r}")
                # the title bar names what the card edits: the object whose own
                # colour it shows on a geometry node (app/features/object_look),
                # the property whose table it shows otherwise
                look = snap.get(f"ui_object_look__{vid}") or {}
                on_object = bool(look.get("path")) and look.get("node") == "geometry"
                named = look.get("label", "") if on_object else label
                if target != named:
                    raise RuntimeError(
                        f"colorbar_probe: the card's title bar names {target!r}, "
                        + (f"the object it colours is {named!r}" if on_object
                           else f"its header {named!r}"))
                want = step.get("expect")
                if want and want not in label:
                    raise RuntimeError(
                        f"colorbar_probe: {label!r} does not say {want!r}")
                if len(rows) < int(step.get("legend_min", 0)):
                    raise RuntimeError(
                        f"colorbar_probe: the Legends card lists {len(rows)}"
                        f" table(s), at least {step['legend_min']} expected")
                for t in step.get("legend_has") or []:
                    if not any(t in r["title"] for r in rows):
                        raise RuntimeError(
                            f"colorbar_probe: no legend row says {t!r}")

            elif op == "session_roundtrip":
                # The session door, save then restore (widgets/session,
                # app/session_host): save, put the views out of order — eyes
                # closed, another style, exact colours, the camera moved,
                # slicers and thresholds dropped, the NaN mask off,
                # the colour tables and bars reset, the cards closed — open
                # the file just saved and restore it: every 3D view must be as
                # it was. {"op":"session_roundtrip"}
                import json as _json
                ctx_ = server.context

                def _lut_fp(vid_, name_):
                    vs_ = ctx_.view_resources.get(vid_) if getattr(ctx_, "view_resources", None) else None
                    lut_ = vs_.get_or_create_lut(name_) if vs_ is not None else None
                    if lut_ is None:
                        return None
                    pts_ = list(lut_.RGBPoints or [])
                    return {"range": [round(float(pts_[0]), 6), round(float(pts_[-4]), 6)] if len(pts_) >= 8 else None,
                            "nan": [round(float(x), 3) for x in lut_.NanColor],
                            "log": int(lut_.UseLogScale),
                            "pinned": "Never" in str(lut_.AutomaticRescaleRangeMode)}

                def _fp():
                    snap_ = state.to_dict()
                    out_ = {"selected": sorted(snap_.get("selected_paths") or [])}
                    for vid_ in (mv.view_ids() if mv is not None else []):
                        pvv_ = mv.get_pv_view(vid_)
                        scene_ = (getattr(ctx_, "blockscope_scenes", None) or {}).get(vid_)
                        grids_ = {}
                        for (ivid_, rep_), iso_ in (getattr(ctx_, "grid_isolates", None) or {}).items():
                            if ivid_ != vid_:
                                continue
                            chain_ = iso_.get_chain() or []
                            names_ = {e["name"]: i for i, e in enumerate(chain_)}
                            grids_[rep_] = {
                                "mode": getattr(iso_, "range_mode", "full"),
                                "volumes": [[list(r) for r in v] for v in (getattr(iso_, "_volumes", None) or [])],
                                "positions": [list(getattr(iso_, f"_slices_{a}_list", None) or []) for a in "ijk"],
                                "chain": [(e["array"], round(float(e["low"]), 6), round(float(e["high"]), 6),
                                           bool(e["visible"]), names_.get(e.get("parent_name"), -1))
                                          for e in chain_],
                            }
                        tables_ = {}
                        if scene_ is not None:
                            for t_ in scene_.legend_tables()[0]:
                                for a_ in t_["arrays"]:
                                    tables_[a_] = _lut_fp(vid_, a_)
                        out_[vid_] = {
                            "eyes": sorted(snap_.get(f"visible_paths__{vid_}") or []),
                            "active": snap_.get(f"active_path__{vid_}") or "",
                            "style": snap_.get(f"ui_rep_style__{vid_}") or "Surface",
                            "flat": bool(snap_.get(f"ui_flat_colors__{vid_}")),
                            "globe": bool(snap_.get(f"ui_globe_mode__{vid_}")),
                            "grids": grids_,
                            "hide_nan": sorted(r for (v, r), f in (getattr(ctx_, "grid_hide_nan", None) or {}).items()
                                               if v == vid_ and (f or {}).get("on")),
                            "tables": tables_,
                            "hidden_bars": sorted(getattr(scene_, "hidden_bars", None) or []),
                            "cards": sorted((snap_.get("ui_open_tools_by_view") or {}).get(vid_) or []),
                            "time": ((snap_.get(f"ui_timereal__{vid_}") or {}).get("time") or {}).get("index"),
                            "realizations": dict((snap_.get("ui_active_realization_by_array_by_view") or {}).get(vid_) or {}),
                            # each selection extract: grid, mode, cells, shown
                            "extracts": [(x_["rep_path"], x_["mode"],
                                          sum(int(r_[1]) - int(r_[0]) + 1 for _i, runs_ in x_["cells"] for r_ in runs_),
                                          x_["visible"])
                                         for x_ in (controller.session_view_extracts(vid_) or [])],
                            "camera": [round(float(x), 3) for x in
                                       list(pvv_.CameraPosition) + list(pvv_.CameraFocalPoint)],
                        }
                    return out_

                before = _fp()
                with state:
                    controller.session_save("scenario")
                text = (state.to_dict().get("ui_session_download") or {}).get("text") or ""
                if not text:
                    raise RuntimeError("session_roundtrip: Save produced no file")
                _log(out, f"session file: {len(text)} characters")
                # the autosave holds the same session (its note aside)
                with state:
                    controller.session_autosave()
                auto = state.to_dict().get("ui_session_autosave") or {}
                if not auto.get("text"):
                    raise RuntimeError("session_roundtrip: no autosave for a session with data")
                a_doc, s_doc = _json.loads(auto["text"]), _json.loads(text)
                if a_doc.get("views") != s_doc.get("views") or a_doc.get("session") != s_doc.get("session"):
                    raise RuntimeError("session_roundtrip: the autosave differs from the saved session")
                _log(out, f"autosave: {len(auto['text'])} characters, n={auto.get('n')}")
                # every view out of order
                with state:
                    for vid_ in mv.view_ids():
                        for (ivid_, rep_), iso_ in list((getattr(ctx_, "grid_isolates", None) or {}).items()):
                            if ivid_ != vid_:
                                continue
                            for e_ in reversed(iso_.get_chain() or []):
                                controller.threshold_remove(e_["name"], vid_)
                            state[f"active_by_tab__{vid_}"] = {**(state[f"active_by_tab__{vid_}"] or {}),
                                                               "reservoir": rep_}
                            controller.slicer_mode("full", vid_)
                        for key_ in [k for k in (getattr(ctx_, "grid_hide_nan", None) or {}) if k[0] == vid_]:
                            ctx_.grid_hide_nan.pop(key_, None)
                        scene_ = (getattr(ctx_, "blockscope_scenes", None) or {}).get(vid_)
                        for a_ in list(getattr(scene_, "hidden_bars", None) or []):
                            scene_.set_bar_visible(a_, True)
                        vs_ = ctx_.view_resources.get(vid_)
                        for t_ in (scene_.legend_tables()[0] if scene_ is not None else []):
                            for a_ in t_["arrays"]:
                                lut_ = vs_.get_or_create_lut(a_)
                                lut_.NanColor = [0.0, 0.0, 0.0]
                                lut_.AutomaticRescaleRangeMode = "Grow and update on 'Apply'"
                        server.context.cards.set(vid_, [])
                        controller.session_restore_extracts(vid_, [])
                        state[f"visible_paths__{vid_}"] = []
                        controller.on_eye_changed(vid_, [])
                        controller.set_rep_style(vid_, "Wireframe")
                        controller.set_flat_colors(vid_, True)
                        pvv_ = mv.get_pv_view(vid_)
                        pvv_.CameraPosition = [0.0, 0.0, 1.0e6]
                        pvv_.CameraFocalPoint = [0.0, 0.0, 0.0]
                with state:
                    controller.session_open({"name": "roundtrip.fespp.json", "text": text})
                st = state.to_dict().get("ui_session_status") or {}
                _log(out, f"session opened: phase={st.get('phase')!r} files={st.get('files')!r}")
                if st.get("phase") != "ready":
                    raise RuntimeError(f"session_roundtrip: the opened session is {st.get('phase')!r},"
                                       " not ready, with every file loaded")
                with state:
                    controller.session_apply()
                st = state.to_dict().get("ui_session_status") or {}
                for r in st.get("report") or []:
                    _log(out, f"  report {r['level']}: {r['text']}")
                after = _fp()
                bad = []
                for key in before:
                    if not isinstance(before[key], dict):
                        if before[key] != after.get(key):
                            bad.append(f"{key}: {before[key]!r} saved, {after.get(key)!r} now")
                        continue
                    for sub, val in before[key].items():
                        now_ = (after.get(key) or {}).get(sub)
                        if val != now_:
                            bad.append(f"{key}.{sub}: {val!r} saved, {now_!r} now")
                for b in bad:
                    _log(out, f"  NOT RESTORED {b}")
                if bad:
                    raise RuntimeError(f"session_roundtrip: {len(bad)} thing(s) not restored: {bad[0]}")
                _log(out, f"session restored: {sorted(before)} — "
                          + "; ".join(f"{k}: {len(v['grids'])} grid(s), {len(v['tables'])} table(s)"
                                      for k, v in before.items() if isinstance(v, dict)))

            elif op == "session_roundtrip_panels":
                # The session door on the ANALYSIS PANELS and the calculator's
                # recipes: save, CLOSE every panel and clear what it held,
                # delete the recipes, open the file and restore it — each
                # panel must come back, by kind, holding what it held (ids
                # and uids are new: they are compared without them).
                # {"op":"session_roundtrip_panels"}
                import json as _json
                from fespp_on_trame.app.session_host import FesppSessionHost
                from fespp_on_trame.engine import derived_props as _dp
                host_ = FesppSessionHost(server)

                def _norm(kind_, p_):
                    p_ = _json.loads(_json.dumps(p_ or {}))
                    if kind_ == "compare":
                        paths_ = {i.get("uid"): i.get("path") for i in p_.get("items") or []}
                        p_["items"] = sorted((i.get("path"), i.get("real"), i.get("ts"), bool(i.get("pinned")))
                                             for i in p_.get("items") or [])
                        for st_ in (p_.get("kinds") or {}).values():
                            for slot_ in ("baseline", "xplot_x", "xplot_y"):
                                st_[slot_] = paths_.get(st_.get(slot_), st_.get(slot_))
                    if kind_ == "stratigraphy":
                        p_.pop("column", None)      # global, checked once below
                    return p_

                def _fp():
                    panels_ = host_._collect_panels()
                    by_kind_ = {}
                    for pid_, p_ in panels_.items():
                        kind_ = mv.kind_of(pid_)
                        by_kind_.setdefault(kind_, []).append(
                            _json.dumps(_norm(kind_, p_), sort_keys=True, default=str))
                    snap_ = state.to_dict()
                    return {"panels": {k: sorted(v) for k, v in by_kind_.items()},
                            "titles": sorted(t for pid_, t in (mv._titles or {}).items()
                                             if mv.kind_of(pid_) != "render"),
                            "derived": sorted((d.get("name"), d.get("expression"))
                                              for d in host_._collect_derived()),
                            # per panel, and the panels get new ids on restore
                            "strati_column": sorted((snap_.get("ui_strati_selected_by_view")
                                                     or {}).values())}

                before = _fp()
                _log(out, "panels saved: " + ", ".join(f"{k}×{len(v)}" for k, v in before["panels"].items())
                          + f"; recipes: {len(before['derived'])}")
                with state:
                    controller.session_save("scenario")
                text = (state.to_dict().get("ui_session_download") or {}).get("text") or ""
                if not text:
                    raise RuntimeError("session_roundtrip_panels: Save produced no file")
                # every panel closed, what it held cleared, the recipes gone
                with state:
                    for pid_ in [p for p in list(mv._titles) if mv.kind_of(p) != "render"]:
                        mv._on_view_closed(pid_)
                    state.ui_welllog_wells = []
                    state.ui_welllog_synth = []
                    state.ui_reconcile_logs = []
                    state.ui_reconcile_dropped = []
                    state.ui_compare_items = []
                    state.ui_compare_parts = []
                    store_ = _dp.get_store()
                    for d_ in list(store_.all_defs()):
                        store_.delete(_dp.path_for(d_["rep_path"], d_["name"]))
                    store_.publish(state)
                closed = _fp()
                if closed["panels"]:
                    raise RuntimeError(f"session_roundtrip_panels: panels left open: {list(closed['panels'])}")
                with state:
                    controller.session_open({"name": "roundtrip.fespp.json", "text": text})
                with state:
                    controller.session_apply()
                await asyncio.sleep(float(step.get("settle", 6)))
                st = state.to_dict().get("ui_session_status") or {}
                for r in st.get("report") or []:
                    _log(out, f"  report {r['level']}: {r['text']}")
                after = _fp()
                bad = []
                for key in ("titles", "derived", "strati_column"):
                    if before[key] != after[key]:
                        bad.append(f"{key}: {before[key]!r} saved, {after[key]!r} now")
                for kind_, saved_ in before["panels"].items():
                    now_ = after["panels"].get(kind_)
                    if saved_ != now_:
                        bad.append(f"{kind_}: {saved_!r} saved, {now_!r} now")
                for b in bad:
                    _log(out, f"  NOT RESTORED {b[:600]}")
                if bad:
                    raise RuntimeError(f"session_roundtrip_panels: {len(bad)} thing(s) not restored: {bad[0][:300]}")
                _log(out, "panels restored: " + ", ".join(f"{k}×{len(v)}" for k, v in after["panels"].items()))

            elif op == "cmap_graph_probe":
                # The Colormap card's graph: its opacity curve spans the whole
                # table. An opacity function left on ParaView's 0..1 while the
                # table is rescaled (say to 0..0.9) keeps a single node inside
                # the table, and the graph is drawn in its first colour alone.
                # {"op":"cmap_graph_probe","expect":"GasSat"}
                vid = _render_vid(server, state)
                snap = state.to_dict()
                cmap = snap.get(f"ui_colormap__{vid}") or {}
                op_nodes = snap.get(f"ui_cmap_opacities__{vid}") or []
                xs = [float(n[0]) for n in op_nodes]
                lo, hi = float(cmap.get("min", 0)), float(cmap.get("max", 1))
                tol = abs(hi - lo) * 1e-3 + 1e-12
                _log(out, f"cmap graph: {cmap.get('label')!r} range=({lo}, {hi})"
                          f" opacity nodes={op_nodes!r}")
                want = step.get("expect")
                if want and want not in (cmap.get("label") or ""):
                    raise RuntimeError(f"cmap_graph_probe: the card edits"
                                       f" {cmap.get('label')!r}, not {want!r}")
                if len(xs) < 2 or min(xs) > lo + tol or max(xs) < hi - tol:
                    raise RuntimeError(
                        f"cmap_graph_probe: the opacity curve {op_nodes!r} does"
                        f" not span the table ({lo}, {hi})")

            elif op == "categorical_opacity_probe":
                # The opacity of a property painted by code, as the reader
                # sets it in the Colormap card's graph: {"phase": "set",
                # "alpha": 0} puts the opacity curve at `alpha` over the card's
                # whole range (the graph's own state variable); {"phase":
                # "check", "alpha": 0} reads the view's table — every code at
                # `alpha` (IndexedOpacities: an indexed table ignores the
                # opacity function) and the opacity mapping on below 1.
                # The card's own sliders: {"phase": "set_code", "index": 0,
                # "alpha": 0} is the slider of the card's first code, without
                # "index" its "Opacity" row (every code); a check with
                # "index" reads that code alone, in the table and on the card
                from fespp_on_trame.engine import categorical_palette as _cp
                vid = _render_vid(server, state)
                cmap = dict(getattr(state, f"ui_colormap__{vid}", None) or {})
                name = cmap.get("array") or ""
                alpha = float(step.get("alpha", 0.0))
                idx = step.get("index")
                cats = list(cmap.get("categories") or [])
                if idx is not None and not (0 <= int(idx) < len(cats)):
                    raise RuntimeError(f"categorical_opacity_probe: no code #{idx} on the card"
                                       f" ({len(cats)} codes)")
                if step.get("phase", "check") == "set_code":
                    code = cats[int(idx)]["code"] if idx is not None else None
                    controller.cmap_category_opacity([code, alpha], vid)
                    _log(out, f"categorical_opacity {name!r}: code {code} set to {alpha}")
                elif step.get("phase") == "mask":
                    # a code at 0 takes its cells OUT of the grid (the cell
                    # mask of engine/nan_mask), so their neighbours' faces
                    # show: {"phase": "mask", "hidden": [0]} wants an isolate
                    # of the view hiding exactly the card's codes #0, the
                    # grid isolated, cells hidden and the skin changed;
                    # "hidden": [] wants no code hidden anywhere
                    from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter as _GF
                    ctx = server.context
                    scene = (getattr(ctx, "blockscope_scenes", None) or {}).get(vid)
                    want = tuple(sorted(float(cats[int(i)]["code"]) for i in step.get("hidden") or ()))

                    def _skin(proxy):
                        g = _GF()
                        g.SetInputData(proxy.GetClientSideObject().GetOutputDataObject(0))
                        g.Update()
                        return g.GetOutput().GetNumberOfCells()

                    isos = [(ip, iso) for (iv, ip), iso in
                            (getattr(ctx, "grid_isolates", None) or {}).items() if iv == vid]
                    for ip, iso in isos:
                        root = iso.render_root()
                        _log(out, f"  isolate {ip[-40:]!r}: codes={iso.hidden_codes}"
                                  f" hidden={iso.hide_nan_hidden}"
                                  f" isolated={bool(scene is not None and ip in scene.isolated)}"
                                  f" skin unmasked={_skin(iso.source_extract)}"
                                  f" masked={_skin(root) if root is not None else None}")
                    if not want:
                        if any(iso.hidden_codes for _ip, iso in isos):
                            raise RuntimeError("categorical_opacity_probe: codes still hidden")
                    else:
                        hits = [(ip, iso) for ip, iso in isos if tuple(iso.hidden_codes) == want]
                        if not hits:
                            raise RuntimeError(f"categorical_opacity_probe: no isolate hides"
                                               f" the codes {want}")
                        ip, iso = hits[0]
                        if scene is None or ip not in scene.isolated:
                            raise RuntimeError("categorical_opacity_probe: the grid is not isolated")
                        if not (iso.hide_nan_hidden or 0) > 0:
                            raise RuntimeError(f"categorical_opacity_probe: {iso.hide_nan_hidden}"
                                               " cells hidden")
                        if _skin(iso.render_root()) == _skin(iso.source_extract):
                            raise RuntimeError("categorical_opacity_probe: the skin did not change")
                elif idx is not None:
                    vreg = getattr(server.context, "view_resources", None)
                    vres = vreg.get(vid) if vreg is not None else None
                    lut = vres.get_or_create_lut(name) if vres is not None and name else None
                    ops = [float(o) for o in _cp._get_list(lut, "IndexedOpacities")] if lut is not None else []
                    mapping = int(getattr(lut, "EnableOpacityMapping", 0) or 0) if lut is not None else 0
                    card = cats[int(idx)].get("opacity")
                    _log(out, f"categorical_opacity {name!r}: code #{idx} table={ops[int(idx)] if int(idx) < len(ops) else None}"
                              f" card={card} opacities={ops} mapping={mapping}")
                    if int(idx) >= len(ops) or abs(ops[int(idx)] - alpha) > 1e-6:
                        raise RuntimeError(f"categorical_opacity_probe: code #{idx} at {ops}, not {alpha}")
                    if card is None or abs(float(card) - alpha) > 1e-6:
                        raise RuntimeError(f"categorical_opacity_probe: the card shows {card} for"
                                           f" code #{idx}, not {alpha}")
                    if any(o < 0.999 for o in ops) != bool(mapping):
                        raise RuntimeError(f"categorical_opacity_probe: opacity mapping {mapping}"
                                           f" for the opacities {ops}")
                elif step.get("phase", "check") == "set":
                    lo, hi = cmap.get("min"), cmap.get("max")
                    if not name or lo is None or hi is None:
                        raise RuntimeError(f"categorical_opacity_probe: the card shows no"
                                           f" array or range ({name!r}, {lo!r}, {hi!r})")
                    var = f"ui_cmap_opacities__{vid}"
                    with state:
                        state[var] = [[float(lo), alpha], [float(hi), alpha]]
                        state.dirty(var)
                    _log(out, f"categorical_opacity {name!r}: curve set to {alpha} on [{lo}, {hi}]")
                else:
                    vreg = getattr(server.context, "view_resources", None)
                    vres = vreg.get(vid) if vreg is not None else None
                    lut = vres.get_or_create_lut(name) if vres is not None and name else None
                    ops = [float(o) for o in _cp._get_list(lut, "IndexedOpacities")] if lut is not None else []
                    mapping = int(getattr(lut, "EnableOpacityMapping", 0) or 0) if lut is not None else 0
                    _log(out, f"categorical_opacity {name!r}: indexed={_cp.is_indexed(lut)}"
                              f" opacities={ops} mapping={mapping}")
                    if not ops or any(abs(o - alpha) > 1e-6 for o in ops):
                        raise RuntimeError(f"categorical_opacity_probe: the codes' opacities are"
                                           f" {ops}, not {alpha}")
                    if (alpha < 0.999) != bool(mapping):
                        raise RuntimeError(f"categorical_opacity_probe: opacity mapping {mapping}"
                                           f" for an opacity of {alpha}")

            elif op == "categorical_probe":
                # A discrete or categorical property is painted ONE COLOUR
                # PER CODE: the view's scoped LUT is indexed on the codes
                # of the data, each named, and the Colormap card lists them
                # with their colours; a continuous property is not.
                # {"op":"categorical_probe","codes":6,"expect":true,
                #  "labels":["1","2"]}
                from fespp_on_trame.engine import categorical_palette as _cp
                vid = _render_vid(server, state)
                snap = state.to_dict()
                cmap = snap.get(f"ui_colormap__{vid}") or {}
                name = cmap.get("array") or ""
                vreg = getattr(server.context, "view_resources", None)
                vscene = vreg.get(vid) if vreg is not None else None
                lut = (vscene.get_or_create_lut(name)
                       if vscene is not None and name else None)
                if lut is None and name:
                    lut = pvsimple.GetColorTransferFunction(name)
                indexed = _cp.is_indexed(lut) if lut is not None else False
                ann = _cp.annotations_of(lut) if lut is not None else {}
                colors = _cp._get_list(lut, "IndexedColors") if lut is not None else []
                cats = cmap.get("categories") or []
                _log(out, f"categorical {name!r}: indexed={indexed}"
                          f" annotations={len(ann)} colours={len(colors) // 3}"
                          f" card_categorical={cmap.get('categorical')!r}"
                          f" card_codes={len(cats)}"
                          f" preset={cmap.get('preset')!r}"
                          f" note={cmap.get('categories_note')!r}")
                for c in cats[:8]:
                    _log(out, f"  code {c.get('code')!r} {c.get('label')!r} {c.get('color')!r}")
                bars = [str(r.Title) for r in (mv.get_pv_view(vid) if mv is not None else v).Representations
                        if r.GetXMLName() == "ScalarBarWidgetRepresentation"
                        and int(getattr(r, "Visibility", 0))]
                _log(out, f"  bars={bars!r}")

                def _expect(cond, what):
                    _log(out, f"  {'OK ' if cond else 'FAIL'} {what}")
                    if not cond:
                        raise RuntimeError(f"categorical_probe: {what}")
                want = step.get("expect", True)
                _expect(indexed is bool(want) or indexed == bool(want),
                        f"the LUT is {'indexed' if want else 'a ramp'}")
                _expect(bool(cmap.get("categorical")) == bool(want),
                        f"the card says {'codes' if want else 'a ramp'}")
                if want:
                    _expect(len(ann) == len(cats) and len(colors) >= 3 * len(ann),
                            "one annotation and one colour per code")
                    _expect(all(c.get("color", "").startswith("#") for c in cats),
                            "every code has a colour")
                    _expect(list(ann.keys()) == sorted(ann.keys()),
                            "the codes are sorted")
                    if "codes" in step:
                        _expect(len(cats) == int(step["codes"]),
                                f"{step['codes']} codes ({len(cats)} found)")
                    if step.get("labels"):
                        got = [c.get("label") for c in cats]
                        _expect(all(lbl in got for lbl in step["labels"]),
                                f"the codes are named {step['labels']!r} ({got!r})")
                    _expect(bool(bars), "the colour bar is shown")
                if step.get("note"):
                    _expect(step["note"] in (cmap.get("categories_note") or ""),
                            f"the card says {step['note']!r}")

            elif op == "xml_relations_probe":
                # What an object designates, and what designates IT. The
                # second direction is readable NOWHERE else: a
                # DataObjectReference lives in the XML of the object that
                # points, never in the one it points at.
                #
                # The assertion is a SYMMETRY, so it needs no uuid written
                # here and holds on any file: take an object with at least
                # one target, ask that target for its sources, and the first
                # object must be among them. A direction that came back from
                # the wrong map, or silently empty, cannot pass it.
                # Driven through the CONTROLLER, not the query helper: what
                # is read here is the whole chain the Graph reading uses —
                # C++ answer, repo_query parsing, the panel's own map.
                # {"op":"xml_relations_probe","title":"Geogrid"}
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                uuid = tree.find_path(nid).rsplit("/", 1)[-1].lstrip("_")
                # a grid's row is the CONTAINER the tree builds
                # ("_gridfolder_<uuid>"), which is no RESQML object: the
                # object is its geometry representation; "of_rep": the
                # representation of the node named (a property's grid)
                if "_" in uuid or step.get("of_rep"):
                    rid = tree.find_representation_node(nid)
                    if rid is not None:
                        uuid = (tree.find_path(rid) or "").rsplit("/", 1)[-1].lstrip("_")
                before = set(mv.panel_ids_of_kind("xml") or [])
                with state:
                    controller.xml_open(uuid, step["title"])
                await asyncio.sleep(float(step.get("settle", 2)))
                new = [v for v in (mv.panel_ids_of_kind("xml") or []) if v not in before]
                pid = new[0] if new else (sorted(before)[0] if before else None)
                if pid is None:
                    raise RuntimeError("xml_relations_probe: no explorer panel")
                if not state.to_dict().get("ui_xml_relations_ok"):
                    raise RuntimeError("xml_relations_probe: this FESPP build"
                                       " does not answer the relationship query")
                with state:
                    controller.xml_relations(uuid, pid)
                await asyncio.sleep(1)
                rel = (state.to_dict().get(f"xml_relations__{pid}") or {}).get(uuid) or {}
                targets, sources = rel.get("target") or [], rel.get("source") or []
                _log(out, f"relations of {step['title']!r} ({uuid[:8]}):"
                          f" {len(targets)} target(s), {len(sources)} source(s)")
                for d, items in (("target", targets), ("source", sources)):
                    for e in items[:4]:
                        _log(out, f"  {d}: {e['type']} {e['title']!r}"
                                  f" {e['uuid'][:8]}{' (partial)' if e['partial'] else ''}")
                # the members of a series (a property met once per time step
                # or realization) carry their index, read from their own XML,
                # which the diagram folds them into ONE box with:
                # "series_ge": at least that many marked
                marked = [e for e in targets + sources if "ts" in e or "real" in e]
                _log(out, f"  series members marked: {len(marked)}"
                          + (f" (e.g. {marked[0]['title']!r} ts={marked[0].get('ts')}"
                             f" real={marked[0].get('real')})" if marked else ""))
                if "series_ge" in step and len(marked) < int(step["series_ge"]):
                    raise RuntimeError(f"xml_relations_probe: {len(marked)} series member(s)"
                                       f" marked, not at least {step['series_ge']}")
                if not targets:
                    raise RuntimeError("xml_relations_probe: no target at all —"
                                       " a RESQML representation designates"
                                       " at least its interpretation or its CRS")
                # the symmetry: what it designates must designate it back
                other = targets[0]
                with state:
                    controller.xml_relations(other["uuid"], pid)
                await asyncio.sleep(1)
                back = ((state.to_dict().get(f"xml_relations__{pid}") or {})
                        .get(other["uuid"]) or {}).get("source") or []
                _log(out, f"  back from {other['title']!r}: {len(back)} source(s)")
                if uuid.lower() not in [s["uuid"].lower() for s in back]:
                    raise RuntimeError(
                        "xml_relations_probe: the object is not among the"
                        " sources of what it designates — the two directions"
                        " do not agree")

            elif op == "xml_probe":
                # The XML explorer on one object: opened by the node's uuid
                # (the tail of its path), the panel holds the object's XML
                # and no note — or says why the channel gave nothing.
                # {"op":"xml_probe","title":"Temperature","under":"Geogrid"}
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title') or step.get('type')!r}")
                path = tree.find_path(nid)
                uuid = path.rsplit("/", 1)[-1].lstrip("_")
                before = set(mv.panel_ids_of_kind("xml") or [])
                with state:
                    controller.xml_open(uuid, step["title"])
                await asyncio.sleep(float(step.get("settle", 2)))
                new = [v for v in (mv.panel_ids_of_kind("xml") or []) if v not in before]
                snap = state.to_dict()
                pid = new[0] if new else None
                xml = (snap.get(f"xml_xml__{pid}") or "") if pid else ""
                note = (snap.get(f"xml_note__{pid}") or "") if pid else ""
                tabs = (snap.get(f"xml_tabs__{pid}") or []) if pid else []
                _log(out, f"xml explorer: panel={pid!r} kind={mv.kind_of(pid) if pid else None!r}"
                          f" tabs={len(tabs)} xml_chars={len(xml)} note={note!r}")
                if step.get("show"):
                    # the parts of the XML a regex names, spaces folded:
                    # {"op":"xml_probe","title":"VAvg","show":"PropertyKind.*?PropertyKind>"}
                    import re as _re
                    for hit in _re.findall(step["show"], xml, _re.S)[:4]:
                        _log(out, "  xml: " + _re.sub(r"\s+", " ", hit)[:600])
                if pid is None:
                    raise RuntimeError("xml_probe: no explorer panel opened")
                if not xml and not note:
                    raise RuntimeError("xml_probe: the explorer shows neither XML nor a reason")
                if xml and uuid.lower() not in xml.lower():
                    raise RuntimeError("xml_probe: the XML shown does not carry the object's uuid")
                if step.get("expect_xml", True) and not xml:
                    raise RuntimeError(f"xml_probe: no XML — {note}")
                # "follow": a reference clicked inside the explorer is pushed
                # onto the active tab's stack (controller xml_follow) — the
                # click must walk to the referenced object
                if step.get("follow") and xml:
                    import re as _re
                    refs = [u for u in _re.findall(r"<(?:\w+:)?UUID\b[^>]*>([^<]+)</(?:\w+:)?UUID>", xml)
                            if u.strip().lower() != uuid.lower()]
                    if not refs:
                        raise RuntimeError("xml_probe: the object references nothing to follow")
                    depth0 = len((tabs[int(snap.get(f"xml_tab__{pid}") or 0)] or {}).get("stack") or [])
                    with state:
                        controller.xml_follow({"uuid": refs[0].strip(), "title": "ref"}, pid)
                    snap = state.to_dict()
                    tabs = snap.get(f"xml_tabs__{pid}") or []
                    depth1 = len((tabs[int(snap.get(f"xml_tab__{pid}") or 0)] or {}).get("stack") or [])
                    _log(out, f"xml follow: {refs[0].strip()} — stack {depth0} -> {depth1}")
                    if depth1 != depth0 + 1:
                        raise RuntimeError(f"xml_probe: following a reference did not walk"
                                           f" to it (stack {depth0} -> {depth1})")

            elif op == "second_view_probe":
                # A second 3D view opened as a COPY of the first: it shows
                # what the first shows (its eyes) and takes its camera — but
                # the two cameras are NOT synchronized, because a copy is a
                # starting point and a view that dragged its neighbour along
                # from the first click took that choice away.
                # {"op":"second_view_probe"}
                ref = _render_vid(server, state)
                before = set(mv.view_ids() or [])
                with state:
                    controller.open_render_view(ref)
                await asyncio.sleep(float(step.get("settle", 4)))
                new = [v for v in (mv.view_ids() or []) if v not in before]
                snap = state.to_dict()
                vid = new[0] if new else None
                eyes_ref = sorted(snap.get(f"visible_paths__{ref}") or [])
                eyes_new = sorted(snap.get(f"visible_paths__{vid}") or []) if vid else []
                links = (snap.get("view_links") or {})
                cam_ref = mv.get_pv_view(ref)
                cam_new = mv.get_pv_view(vid) if vid else None
                pos_ref = [round(float(x), 3) for x in cam_ref.CameraPosition]
                pos_new = ([round(float(x), 3) for x in cam_new.CameraPosition]
                           if cam_new is not None else None)
                _log(out, f"second view: ref={ref} new={vid!r} kind={mv.kind_of(vid) if vid else None!r}"
                          f" eyes_ref={len(eyes_ref)} eyes_new={len(eyes_new)}"
                          f" synchronized={vid in (links.get(ref) or [])}"
                          f" camera_same={pos_ref == pos_new}")
                if vid is None or mv.kind_of(vid) != "render":
                    raise RuntimeError("second_view_probe: no second render view")
                if eyes_new != eyes_ref:
                    raise RuntimeError(f"second_view_probe: eyes differ — {eyes_ref} vs {eyes_new}")
                if pos_ref != pos_new:
                    raise RuntimeError("second_view_probe: the camera was not copied")
                if vid in (links.get(ref) or []):
                    raise RuntimeError("second_view_probe: the two cameras were"
                                       " synchronized without being asked")

            elif op in ("timereal_play", "timereal_player_expect"):
                # The Time & Realizations card's player: played or paused through the card's own gesture
                # {"op":"timereal_play","on":true}; what it says {"op":"timereal_player_expect","playing":false}
                # ("moving": true — its step moves over `settle` seconds; false — it stays)
                vid = _render_vid(server, state)
                card_ = dict(state.to_dict().get(f"ui_timereal_card__{vid}") or {})
                cut_ = next((c_ for box_ in (card_.get("card") or {}).get("boxes") or []
                             for c_ in (box_.get("cuts") or {}).get("time") or []), None)
                if cut_ is None:
                    raise RuntimeError(f"{op}: the card has no time cut")
                if op == "timereal_play":
                    with state:
                        controller.timereal_slicer({"op": "player", "id": cut_["id"], "action": "play",
                                                    "value": bool(step.get("on", True))}, vid)
                    await asyncio.sleep(float(step.get("settle", 1)))
                else:
                    said_ = dict(state.to_dict().get(f"ui_timereal_player__{vid}") or {})
                    moves_ = said_.get("moves", 0)
                    await asyncio.sleep(float(step.get("settle", 2)))
                    again_ = dict(state.to_dict().get(f"ui_timereal_player__{vid}") or {})
                    _log(out, f"timereal player ({vid}): playing={again_.get('playing')} entry={again_.get('entry')!r}"
                              f" index={again_.get('index')}/{again_.get('count')} moves {moves_} -> {again_.get('moves', 0)}"
                              f" (cut {cut_['id']!r})")
                    if "playing" in step and bool(again_.get("playing")) != bool(step["playing"]):
                        raise RuntimeError(f"timereal_player_expect: playing={again_.get('playing')}, not {step['playing']}")
                    if "moving" in step and (again_.get("moves", 0) > moves_) != bool(step["moving"]):
                        raise RuntimeError(f"timereal_player_expect: moves {moves_} -> {again_.get('moves', 0)},"
                                           f" moving should be {step['moving']}")
                    if "time_steps" in step:
                        # the steps the card's Time step row offers: those of what the view colours by
                        card_ = dict(state.to_dict().get(f"ui_timereal_card__{vid}") or {})
                        time_ = next((s_ for s_ in card_.get("subjects") or [] if s_.get("value") == "time"), {})
                        offered_ = list(time_.get("values") or [])
                        _log(out, f"timereal time steps ({vid}): {offered_}")
                        if len(offered_) != int(step["time_steps"]):
                            raise RuntimeError(f"timereal_player_expect: {len(offered_)} time steps offered,"
                                               f" not {step['time_steps']}")
                    if "view_step" in step:
                        # the step the view shows (its position in the session's time steps)
                        shown_ = ((state.to_dict().get(f"ui_timereal__{vid}") or {}).get("time") or {}).get("index")
                        _log(out, f"timereal view step ({vid}): {shown_}")
                        if shown_ != int(step["view_step"]):
                            raise RuntimeError(f"timereal_player_expect: the view shows step {shown_},"
                                               f" not {step['view_step']}")

            elif op == "timereal_card_probe":
                # The Time & Realizations card as the shared slicer card
                # (29/10): its time cut moved through the card's own
                # controller reaches the view's ViewTime, and the card says
                # the step shown. {"op":"timereal_card_probe","index":5}
                vid = _render_vid(server, state)
                idx = int(step.get("index", 0))
                card_ = dict(state.to_dict().get(f"ui_timereal_card__{vid}") or {})
                subjects_ = [s_.get("value") for s_ in card_.get("subjects") or []]
                cut_ = None
                for box_ in (card_.get("card") or {}).get("boxes") or []:
                    for c_ in (box_.get("cuts") or {}).get("time") or []:
                        cut_ = c_
                        break
                    if cut_:
                        break
                _log(out, f"timereal card ({vid}): target={card_.get('target')!r} subjects={subjects_}"
                          f" time cut={cut_!r}")
                if cut_ is None:
                    raise RuntimeError("timereal_card_probe: the card has no time cut")
                with state:
                    controller.timereal_slicer({"op": "set_cut", "id": cut_["id"], "at": idx}, vid)
                await asyncio.sleep(float(step.get("settle", 3)))
                snap = state.to_dict()
                card_ = dict(snap.get(f"ui_timereal_card__{vid}") or {})
                at_ = None
                for box_ in (card_.get("card") or {}).get("boxes") or []:
                    for c_ in (box_.get("cuts") or {}).get("time") or []:
                        at_ = c_.get("at")
                        break
                values = list(pvsimple.GetTimeKeeper().TimestepValues or [])
                vt = float(mv.get_pv_view(vid).ViewTime)
                old_ = (snap.get(f"ui_timereal__{vid}") or {}).get("time") or {}
                _log(out, f"timereal card ({vid}): asked={idx} cut at={at_} view time={vt}"
                          f" expected={values[idx] if 0 <= idx < len(values) else None}"
                          f" old state index={old_.get('index')}")
                if not values or at_ != float(idx) or abs(vt - values[idx]) > 1e-6:
                    raise RuntimeError("timereal_card_probe: the card's cut did not reach the view")

            elif op == "timereal_probe":
                # The time step of a view: the Time card's index reaches the
                # view's ViewTime and the card's state. {"op":"timereal_probe",
                # "index": 5}
                vid = _render_vid(server, state)
                idx = int(step.get("index", 0))
                with state:
                    controller.time_index(idx, vid)
                await asyncio.sleep(float(step.get("settle", 3)))
                snap = state.to_dict()
                card = (snap.get(f"ui_timereal__{vid}") or {}).get("time") or {}
                values = list(pvsimple.GetTimeKeeper().TimestepValues or [])
                pvv = mv.get_pv_view(vid)
                vt = float(pvv.ViewTime)
                _log(out, f"time ({vid}): steps={len(values)} asked={idx}"
                          f" card_index={card.get('index')!r} card_value={card.get('value')!r}"
                          f" view_time={vt}")
                if not values:
                    raise RuntimeError("timereal_probe: the file has no time steps")
                want = values[max(0, min(idx, len(values) - 1))]
                if card.get("index") != max(0, min(idx, len(values) - 1)):
                    raise RuntimeError("timereal_probe: the card does not show the asked index")
                if abs(vt - float(want)) > 1e-6:
                    raise RuntimeError(f"timereal_probe: view time {vt} is not step {idx} ({want})")

            elif op == "strati_probe":
                # The Stratigraphy view over the loaded wells: one column per
                # well that carries a rock lane or markers, or the reason none
                # could be built. {"op":"strati_probe","min_columns":1}
                before = set(mv.panel_ids_of_kind("stratigraphy") or [])
                with state:
                    controller.open_stratigraphy()
                await asyncio.sleep(float(step.get("settle", 4)))
                new = [v for v in (mv.panel_ids_of_kind("stratigraphy") or []) if v not in before]
                snap = state.to_dict()
                cols = snap.get("ui_strati_columns") or []
                note = snap.get("ui_strati_note") or ""
                _log(out, f"stratigraphy: panel={new[0] if new else None!r}"
                          f" columns={len(cols)} titles={[c.get('title') for c in cols][:6]!r}"
                          f" note={note!r}")
                if not new:
                    raise RuntimeError("strati_probe: no stratigraphy panel opened")
                if len(cols) < int(step.get("min_columns", 1)) and not note:
                    raise RuntimeError("strati_probe: no column and no reason")
                if len(cols) < int(step.get("min_columns", 1)):
                    raise RuntimeError(f"strati_probe: {len(cols)} column(s) — {note}")

            elif op == "crs_axes_probe":
                # What the two horizontal ordinates are CALLED, and by whom.
                # The FILE is the first authority (RESQML's
                # ProjectedAxisOrder, carried by the CRS object through the
                # query channel); the EPSG registry only answers when the
                # file says nothing. {"op":"crs_axes_probe"}
                from fespp_on_trame.engine import geo as _geo
                crs = controller.detect_crs() if controller.detect_crs.exists() else None
                nx, ny, src = _geo.axis_names_of(crs)
                _log(out, f"CRS: epsg={(crs or {}).get('epsg')!r}"
                          f" axis_order={(crs or {}).get('axis_order')!r}"
                          f" depth_oriented={(crs or {}).get('depth')!r}"
                          f" unit={(crs or {}).get('projected_unit')!r}")
                _log(out, f"axes: {nx} / {ny} — named by {src or 'nobody'}")
                if step.get("from_file", True) and src != "the file":
                    raise RuntimeError(
                        "crs_axes_probe: the axis names did not come from the"
                        f" file (they came from {src or 'nowhere'}) — the"
                        " plugin's axis_order field is the first authority")

            elif op == "crs_dump":
                # Every local CRS the reader holds, as the app reads it
                # (geo.crs_info_from_fields): code, domain, axis order, units.
                # {"op":"crs_dump"}
                from fespp_on_trame.engine import geo as _geo
                from fespp_on_trame.engine import repo_query as _rq
                src_ = server.context.active_data_source.get_source()
                tag_ = _rq.tag(src_)
                for u_ in list(_rq.object_uuids(src_, "AbstractLocal3dCrs", cache_tag=tag_))[:12]:
                    info_ = _geo.crs_info_from_fields(_rq.object_fields(src_, u_, cache_tag=tag_))
                    _log(out, f"crs {u_}: {info_!r}")

            elif op == "axes_labels_probe":
                # The letters on the render view's orientation axes (bottom
                # left), their units with them, T in a view switched to time
                # (28/10): {"op":"axes_labels_probe","expect":["E (m)","N (m)","T (ms)"]}
                cvid = _render_vid(server, state)
                pvv = mv.get_pv_view(cvid)
                got = [str(getattr(pvv, f"OrientationAxes{a}LabelText")) for a in "XYZ"]
                _log(out, f"orientation axes ({cvid}): {got}")
                want = step.get("expect")
                if want is not None and got != list(want):
                    raise RuntimeError(f"axes_labels_probe: {got}, not {want}")

            elif op == "interactive_frame_probe":
                # THE FRAME A HAND ACTUALLY SEES WHILE IT DRAGS.
                #
                # Every other colour probe here calls SaveScreenshot, and
                # SaveScreenshot forces a STILL render: it looks at the full
                # actor, never at the decimated LOD one ParaView swaps in
                # during an interaction. So a scene whose still frame is
                # perfect can still be drawn colourless the moment the camera
                # moves, and no scenario would ever have seen it. This one
                # asks for an INTERACTIVE render and reads the render
                # window's own pixels back, which is the only way to catch it.
                # {"op":"interactive_frame_probe","min_coloured":30000}
                import numpy as _np
                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                from vtkmodules.vtkCommonCore import vtkUnsignedCharArray
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                if pvv is None:
                    raise RuntimeError("interactive_frame_probe: no render view")
                _rw = pvv.GetClientSideObject().GetRenderWindow()

                def _frame_count(kind):
                    if kind == "interactive":
                        pvv.SMProxy.InteractiveRender()
                    else:
                        pvv.SMProxy.StillRender()
                    w0, h0 = _rw.GetSize()
                    # the ARRAY form: the 5-argument call hands back raw
                    # bytes as a str, which numpy_support cannot read
                    arr = vtkUnsignedCharArray()
                    _rw.GetRGBACharPixelData(0, 0, w0 - 1, h0 - 1, 1, arr)
                    a = _v2n(arr)[:, :3].astype(int)
                    mx, mn = a.max(axis=1), a.min(axis=1)
                    coloured = int((((mx - mn) > 40) & (mx > 60)).sum())
                    white = int((mn > 225).sum())
                    return coloured, white, w0, h0

                # FORCING THE LOD. ParaView only swaps in the decimated actor
                # once the geometry passes `LODThreshold` megabytes, so a
                # small grid never shows what a large one does. Dropping the
                # threshold to zero makes every interactive render take the
                # LOD road, which is the road a reader's camera drag takes on
                # a grid big enough — and the one no screenshot probe can
                # reach, SaveScreenshot always rendering still.
                lod_before = None
                if step.get("force_lod"):
                    lod_before = float(pvv.LODThreshold)
                    pvv.LODThreshold = 0.0
                    pvv.UpdateVTKObjects()
                ci, wi, w0, h0 = _frame_count("interactive")
                cs, ws, _, _ = _frame_count("still")
                reps_lod = [f"{r.GetXMLName()} suppress={r.GetProperty('SuppressLOD').GetElement(0) if r.GetProperty('SuppressLOD') is not None else '-'}"
                            for r in (pvv.Representations or [])
                            if r.GetProperty("Visibility") is not None
                            and int(r.GetProperty("Visibility").GetElement(0))]
                _log(out, f"frames ({vid}) {w0}x{h0}: interactive coloured={ci}"
                          f" white={wi} | still coloured={cs} white={ws}"
                          f" | lod_threshold={pvv.LODThreshold} forced={bool(step.get('force_lod'))}"
                          f" | {reps_lod}")
                if lod_before is not None:
                    pvv.LODThreshold = lod_before
                    pvv.UpdateVTKObjects()
                floor = int(step.get("min_coloured", 0))
                if cs < floor:
                    raise RuntimeError(
                        f"interactive_frame_probe: the STILL frame is not"
                        f" coloured either ({cs} px) — this probe is about the"
                        " difference between the two, and there is no colour"
                        " to lose")
                if ci < floor:
                    raise RuntimeError(
                        f"interactive_frame_probe: the INTERACTIVE frame has"
                        f" {ci} coloured pixels against {cs} on the still one"
                        " — the grid loses its colours the moment the camera"
                        " moves, and every screenshot-based probe is blind to"
                        " it (SaveScreenshot always renders still)")

            elif op == "dump_tree":
                # Every node the tree holds, by title and type. A scenario
                # that names a node it cannot find says only "node not
                # found"; this says what there WAS to find, which is the
                # question one actually has at that moment.
                # {"op":"dump_tree","type":"Property","limit":80}
                asm = tree._data_assembly
                want = step.get("type")
                rows = []
                for n in asm.GetChildNodes(0, True):
                    kind = asm.GetAttributeOrDefault(n, "type", "") or ""
                    title = asm.GetAttributeOrDefault(n, "title", "") or ""
                    if want and want.lower() not in kind.lower():
                        continue
                    # the vertical domain where the plugin set it (28/10)
                    dom = asm.GetAttributeOrDefault(n, "vdomain", "") or ""
                    # "paths": true — each row with its path, which tells two
                    # rows of one title apart
                    where = f"  {tree.find_path(n)}" if step.get("paths") else ""
                    rows.append(f"{kind}:{title}" + (f" [{dom}]" if dom else "") + where)
                _log(out, f"tree: {len(rows)} node(s)"
                          + (f" of type ~{want}" if want else ""))
                for row in rows[:int(step.get("limit", 120))]:
                    _log(out, f"    {row}")

            elif op == "unstructured_threshold_probe":
                # A threshold on a NON-IJK representation, built by hand.
                # Under BlockScope a thresholded block is drawn only by
                # something that OWNS displays, and the only such thing is
                # the IjkGrid isolate. This builds the non-IJK equivalent —
                # the same generic `EnergisticsExtractor(ExtractPath=...)` the
                # isolate uses, a Threshold on it, and the composite asked to
                # let the block go — and counts pixels: if the picture
                # follows, the path works outside the isolate.
                # {"op":"unstructured_threshold_probe"}
                import numpy as _np
                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                from vtkmodules.vtkCommonCore import vtkUnsignedCharArray
                from paraview.modules.vtkRemotingServerManager import vtkSMPropertyHelper
                from fespp_on_trame.engine.sources.representation import (
                    _create_plugin_filter_proxy,
                )
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                scene = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid)
                if pvv is None or scene is None:
                    raise RuntimeError("unstructured_threshold_probe: no scene")
                asm = tree._data_assembly
                target, ttype = None, None
                for n in asm.GetChildNodes(0, True):
                    kind = asm.GetAttributeOrDefault(n, "type", "") or ""
                    if kind in ("UnstructuredGrid", "Sub", "TriangulatedSet",
                                "Grid2d", "PolylineSet"):
                        p = asm.GetNodePath(n)
                        if p in (state.ui_loaded_rep_paths or []):
                            target, ttype = p, kind
                            break
                if target is None:
                    loaded = [(asm.GetAttributeOrDefault(
                        tree.find_node_id(p), "type", "") or "?", p.rsplit("/", 1)[-1][:28])
                        for p in (state.ui_loaded_rep_paths or [])]
                    raise RuntimeError(
                        "unstructured_threshold_probe: no non-IJK rep loaded"
                        f" — loaded reps are {loaded}")
                sel = target
                _log(out, f"target: {ttype} {target.rsplit('/', 1)[-1][:40]}")

                from vtkmodules.vtkIOImage import vtkPNGReader
                _shot_n = [0]

                def _count():
                    # SaveScreenshot, never a read of the render window's own
                    # buffer: that buffer is not reliably what the last Render
                    # drew, and a probe that reads a stale frame concludes
                    # that a display it just created draws nothing.
                    _shot_n[0] += 1
                    f = os.path.join(out, f"unstr_{_shot_n[0]}.png")
                    pvsimple.SaveScreenshot(f, pvv, ImageResolution=[800, 600])
                    r = vtkPNGReader()
                    r.SetFileName(f)
                    r.Update()
                    a = _v2n(r.GetOutput().GetPointData().GetScalars())[:, :3].astype(int)
                    mx, mn = a.max(axis=1), a.min(axis=1)
                    return int((((mx - mn) > 40) & (mx > 60)).sum()), int((mn > 225).sum())

                before = _count()
                ext = _create_plugin_filter_proxy(
                    proxy_class="EnergisticsExtractor",
                    registration_name=f"probe_ext_{_render_vid(server, state)}",
                    inputs={"Input": getattr(scene, "_clone", None)
                            or server.context.collector.get_source()},
                )
                if ext is None:
                    raise RuntimeError(
                        "unstructured_threshold_probe: EnergisticsExtractor"
                        " could not be created — the generic extractor is"
                        " the whole basis of the design")
                vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(target)
                ext.SMProxy.UpdateVTKObjects()
                ext.UpdatePipelineInformation()
                ext.UpdatePipeline()
                cso = ext.GetClientSideObject().GetOutputDataObject(0)
                ncells = cso.GetNumberOfCells() if cso is not None else 0
                _log(out, f"extractor: {type(cso).__name__} with {ncells} cells")
                if not ncells:
                    raise RuntimeError(
                        "unstructured_threshold_probe: the extractor produced"
                        " NO cells for a non-IJK rep — the design does not"
                        " hold")
                scene.set_isolated(sel, True)
                await asyncio.sleep(2)
                dropped = _count()
                disp = pvsimple.Show(ext, pvv)
                await asyncio.sleep(1)
                shown = _count()
                # Second try, with the display DRESSED the way the IjkGrid
                # isolate dresses its crops: an explicit solid colour and an
                # association. A representation created on a plugin filter
                # proxy does not come out of Show() with the defaults an
                # ordinary source gets.
                try:
                    disp.Representation = "Surface"
                    disp.ColorArrayName = ["POINTS", ""]
                    disp.DiffuseColor = [0.35, 0.7, 1.0]
                    disp.Opacity = 1.0
                except Exception as _exc:
                    _log(out, f"dressing failed — {_exc}")
                await asyncio.sleep(1)
                dressed = _count()
                _log(out, f"pixels dressed: {dressed}")
                if dressed[0] > shown[0]:
                    shown = dressed
                try:
                    _db = ext.GetDataInformation().GetBounds()
                except Exception as _exc:
                    _log(out, f"bounds unreadable — {_exc}")
                    _db = None
                _cam = pvv.GetActiveCamera()
                _log(out, f"display: vis={getattr(disp, 'Visibility', '?')}"
                          f" repr={getattr(disp, 'Representation', '?')!r}"
                          f" scale={list(getattr(disp, 'Scale', []) or [])}"
                          f" opacity={getattr(disp, 'Opacity', '?')}"
                          f" colour={list(getattr(disp, 'ColorArrayName', []) or [])}")
                _log(out, f"bounds: extractor={None if _db is None else [round(c) for c in _db]}"
                          f" camera_pos={[round(c) for c in _cam.GetPosition()]}"
                          f" focal={[round(c) for c in _cam.GetFocalPoint()]}"
                          f" zscale={getattr(state, f'ui_scale_z__{_render_vid(server, state)}', '?')}")
                _log(out, f"pixels: before={before} composite_dropped={dropped}"
                          f" extractor_shown={shown}")
                # CONTROL: a plain sphere at the data's own centre. If THIS
                # does not draw either, the fault is in how this probe shows
                # and captures, not in the extractor.
                cx = (_db[0] + _db[1]) / 2 if _db else 0
                cy = (_db[2] + _db[3]) / 2 if _db else 0
                cz = (_db[4] + _db[5]) / 2 if _db else 0
                rad = max((_db[1] - _db[0]), (_db[3] - _db[2])) / 4 if _db else 1
                ball = pvsimple.Sphere(Center=[cx, cy, cz], Radius=rad)
                bdisp = pvsimple.Show(ball, pvv)
                bdisp.DiffuseColor = [1.0, 0.2, 0.2]
                await asyncio.sleep(1)
                control = _count()
                _log(out, f"control sphere at {[round(cx), round(cy), round(cz)]}"
                          f" r={round(rad)}: pixels={control}")
                pvsimple.Hide(ball, pvv)
                pvsimple.Delete(ball)
                scene.set_isolated(sel, False)
                pvsimple.Hide(ext, pvv)
                if control[0] <= dropped[0]:
                    raise RuntimeError(
                        "unstructured_threshold_probe: even a PLAIN SPHERE at"
                        " the data's centre draws nothing — the fault is in"
                        " this probe's show/capture, not in the extractor")
                if shown[0] <= dropped[0]:
                    raise RuntimeError(
                        "unstructured_threshold_probe: the control sphere drew"
                        f" ({control[0]} px) but the extractor did not — a"
                        " non-IJK isolate would have no way to draw")

            elif op == "cursor_sweep":
                # The crosshair's ray over an n x n lattice of the view, as a
                # hit map, next to ParaView's own surface SELECTION at the
                # same pixels — the slow road, but the truth about what is
                # drawn there. A ray that misses where the selection hits is
                # a ray cast wrong, not a pointer over nothing.
                # And each point the ray hands back, drawn (the Z
                # exaggeration in), lies under its pixel: a line is named
                # within PICK_PX pixels of the pointer, no further. "titles":
                # the blocks the sweep must name, each at least once.
                # {"op":"cursor_sweep","n":7,"selection":true,"titles":["Drilled trajectory"]}
                import math
                from fespp_on_trame.engine import ray_pick as _ray_pick
                from fespp_on_trame.engine.state_defaults import z_scale_of as _z_scale_of
                cvid = _render_vid(server, state)
                pvv = mv.get_pv_view(cvid)
                if pvv is None:
                    raise RuntimeError("cursor_sweep: no render view")
                pvv.SMProxy.StillRender()
                w, h = [int(v) for v in pvv.ViewSize]
                n = int(step.get("n", 7))
                want_sel = bool(step.get("selection", True))
                hits_ray = hits_sel = agree = 0
                lines = []
                zs_ = _z_scale_of(state, cvid)
                ren_ = pvv.GetClientSideObject().GetRenderer()
                reach_ = _ray_pick.PICK_PX + 2
                astray, named = [], {}
                for j in range(n - 1, -1, -1):        # top row first, like the screen
                    y = int((j + 0.5) * h / n)
                    ray_line = sel_line = ""
                    for i in range(n):
                        x = int((i + 0.5) * w / n)
                        pt, _blk = controller.cursor_hit(cvid, x, y)
                        r = pt is not None
                        hits_ray += r
                        ray_line += "#" if r else "."
                        if r:
                            named[_blk] = named.get(_blk, 0) + 1
                            ren_.SetWorldPoint(pt[0], pt[1], pt[2] * zs_, 1.0)
                            ren_.WorldToDisplay()
                            dx_, dy_, _dz = ren_.GetDisplayPoint()
                            off_ = math.hypot(dx_ - x, dy_ - y)
                            if off_ > reach_:
                                astray.append((x, y, round(off_), _blk))
                        if want_sel:
                            wp = [0.0, 0.0, 0.0]
                            nm = [0.0, 0.0, 0.0]
                            s_hit = bool(pvv.SMProxy.ConvertDisplayToPointOnSurface([x, y], wp, nm))
                            hits_sel += s_hit
                            agree += (s_hit == r)
                            sel_line += "#" if s_hit else "."
                    lines.append((ray_line, sel_line))
                _log(out, f"cursor sweep ({cvid}) {w}x{h}, {n}x{n} pixels:"
                          f" ray hits {hits_ray}/{n * n}"
                          + (f", selection hits {hits_sel}/{n * n}, agree {agree}/{n * n}" if want_sel else ""))
                for ray_line, sel_line in lines:
                    _log(out, f"  ray {ray_line}" + (f"   selection {sel_line}" if want_sel else ""))
                _log(out, f"  named (Z x {zs_:g}): {named}")
                if astray:
                    raise RuntimeError(
                        f"cursor_sweep: {len(astray)} hit(s) of {hits_ray} lie more than {reach_} px from"
                        f" their pixel, drawn at Z x {zs_:g} — (x, y, px away, block): {astray[:6]}")
                missing_ = [t for t in step.get("titles") or () if t not in named]
                if missing_:
                    raise RuntimeError(f"cursor_sweep: never named {missing_} — named {sorted(named)}")
                if want_sel and hits_sel and hits_ray < hits_sel // 2:
                    raise RuntimeError(
                        f"cursor_sweep: the ray hits {hits_ray} pixels where the"
                        f" selection hits {hits_sel} — the ray is cast wrong")
            elif op == "log_track_probe":
                # The trial of how the wells are drawn (app/features/log_tracks,
                # FESPP_LOG_TRACK=1). A log is a GRAPH on its hole by default:
                # "count": how many graphs the view draws; "on_hole": true says
                # each one's first line IS its hole — the reader's ring centres,
                # its zero —; "lines": how many curves are drawn (a band of
                # codes has none); "true_range": the table of each graph keeps
                # within the values the graphs shown hold — no bound made up on
                # the other side of zero —; "curtain": true says the graph stands in the
                # well's curtain, + towards the surface (a plumb well: the screen's plane, + right). "curves": how many
                # logs are drawn as a curve alone (their strip hidden), "coloured": every
                # curve drawn wears a colour (not white), "chips": how many rows of the
                # trees wear their curve's colour; "curves_unbarred": no colour bar for
                # the properties drawn as curves; "one_scale": the graphs shown (of one
                # kind) share one table range; "gaps": how many logs have stretches of
                # hole without a value drawn, in the NaN colour.
                # "tube": true reads what the view's well symbols filter (FESPP's
                # EnergisticsWellSymbols) makes of the logs shown as tubes and of
                # the markers: each tube as wide across as high AS DRAWN with the
                # reader's hole, radii, values and field data ("tubes": how
                # many), each marker as far from its centre as drawn as the
                # reader made it ("markers", "markers_ge"); and everything drawn
                # here is off the composite.
                # {"op":"log_track_probe","count":1,"lines":1,"on_hole":true,"tube":true,"tubes":0,"markers_ge":1}
                import numpy as np
                from vtkmodules.util.numpy_support import vtk_to_numpy as _to_np
                from fespp_on_trame.engine import log_track as _log_track
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                ren_ = pvv_.GetClientSideObject().GetRenderer()
                # what is DRAWN is read: without a browser no frame follows a change by itself
                pvv_.SMProxy.StillRender()
                found_, tables_, spans_, strips_ = [], [], [], {}
                # the graphs the view's filter (FESPP's well symbols) draws: per log, its strip, its curve, its
                # gaps, shown by the representation of the filter's graph blocks
                parts_of_ = getattr(server.context, "log_graph_parts", None)
                graphs_ = parts_of_(vid_) if parts_of_ is not None else {}
                # one representation per log's graph (fesppLogGraphs_<view>_<n>): what each shows, its colours
                rep_, shown_blocks_, colour_of_ = None, set(), {}
                root_ = "/" + next(iter(graphs_)).split("/")[1] if graphs_ else "/data"
                for (n_, _i), s_ in pvsimple.GetSources().items():
                    if not n_.startswith(f"fesppLogGraphs_{vid_}_"):
                        continue
                    r_ = pvsimple.GetRepresentation(proxy=s_, view=pvv_)
                    if r_ is None or not int(getattr(r_, "Visibility", 0) or 0):
                        continue
                    rep_ = r_
                    drawn_, colours_ = _graph_rep_blocks(r_, s_, root_)
                    shown_blocks_ |= drawn_
                    colour_of_.update(colours_)
                for sel_, parts_ in sorted(graphs_.items()):
                    name_ = "graph of " + (sel_.rsplit("/", 1)[-1][-12:])
                    data_ = parts_.get("strip")
                    seen_ = f"{sel_}/strip" in shown_blocks_ and data_ is not None
                    ent_ = scene_.block_state.get(sel_) if scene_ is not None else None
                    arr_ = None
                    if data_ is not None and ent_ is not None and ent_.color_array:
                        arr_ = data_.GetPointData().GetArray(ent_.color_array) or data_.GetCellData().GetArray(ent_.color_array)
                    rng_ = arr_.GetRange() if arr_ is not None else (0.0, 0.0)
                    lut_ = scene_.scoped_lut(ent_.color_array) if ent_ is not None and ent_.color_array else None
                    pts_ = list(lut_.RGBPoints) if lut_ is not None else []
                    table_ = (pts_[0], pts_[-4]) if len(pts_) >= 8 else (0.0, 0.0)
                    _log(out, f"log graph {name_}: visible={int(seen_)}, {data_.GetNumberOfPolys() if data_ is not None else 0}"
                              f" strips, values {rng_[0]:g} .. {rng_[1]:g} on its"
                              f" {'cells' if data_ is not None and data_.GetCellData().GetNumberOfArrays() else 'points'},"
                              f" table {table_[0]:g} .. {table_[1]:g}")
                    strips_[sel_] = seen_
                    if not seen_:
                        continue
                    found_.append(name_)
                    tables_.append(table_)
                    spans_.append(rng_)
                    at_ = _to_np(data_.GetPoints().GetData()).copy()
                    n_ = len(at_) // 2
                    if step.get("on_hole"):
                        # its first line is the hole of one of the logs drawn here: the reader's ring centres, in
                        # their order, the trajectory's own points between them where the log was read far apart
                        on_, added_ = False, 0
                        for sel_ in scene_.isolated:
                            ent_ = scene_.block_state.get(sel_)
                            for d_, _f in server.context.assembly_index.datasets(sel_) if ent_ is not None else ():
                                r_ = _log_track.rings(d_, ent_.color_array) if ent_.color_array else None
                                if r_ is None or len(r_[0]) > n_:
                                    continue
                                k_ = 0
                                for c_ in r_[0]:
                                    while k_ < n_ and not np.allclose(at_[k_], c_, atol=1e-6):
                                        k_ += 1
                                    k_ += 1
                                if k_ <= n_:
                                    on_, added_ = True, n_ - len(r_[0])
                        _log(out, f"log graph {name_}: {added_} point(s) of its trajectory between its samples")
                        off_hole_ = float(np.linalg.norm((at_[n_:] - at_[:n_]) * [1.0, 1.0, float(rep_.Scale[2])], axis=1).max())
                        _log(out, f"log graph {name_}: its zero on its hole {on_}, the curve up to {off_hole_:.0f} off it as drawn")
                        if not on_:
                            raise RuntimeError(f"log_track_probe: the zero of {name_} is not its hole")
                    if step.get("trajectory_gap"):
                        # in plan, how far the graph's zero line and its curve stand from the TRAJECTORY as the
                        # reader draws it (its own polyline, not the log's nodes): seen from above, they coincide
                        from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                        gaps_out_ = []
                        for sel_ in scene_.isolated:
                            nid_ = tree.find_node_id(sel_)
                            wb_ = tree.find_parent_node_id_with_type(nid_, "Wellbore") if nid_ is not None else None
                            tid_ = ((tree.find_first_child_of_type(wb_, "WellboreTrajectory")
                                     or tree.find_first_child_of_type(wb_, "Trajectory")) if wb_ is not None else None)
                            for tds_, _f in (server.context.assembly_index.datasets(tree.find_path(tid_))
                                             if tid_ is not None else ()):
                                tp_ = _v2n(tds_.GetPoints().GetData()).astype(float)[:, :2]
                                a_, sg_ = tp_[:-1], np.diff(tp_, axis=0)
                                sl_ = np.maximum((sg_ ** 2).sum(1), 1e-24)

                                def _plan_gap(pts_):
                                    out_ = []
                                    for q_ in pts_[:: max(1, len(pts_) // 300)]:
                                        rel_ = q_[:2] - a_
                                        t_ = np.clip((rel_ * sg_).sum(1) / sl_, 0.0, 1.0)
                                        out_.append(float(np.linalg.norm(rel_ - t_[:, None] * sg_, axis=1).min()))
                                    return np.asarray(out_)
                                z_gap_, c_gap_ = _plan_gap(at_[:n_]), _plan_gap(at_[n_:])
                                gaps_out_.append((float(z_gap_.max()), float(np.median(z_gap_)),
                                                  float(c_gap_.max()), float(np.median(c_gap_))))
                                break
                        for zmax_, zmed_, cmax_, cmed_ in gaps_out_:
                            _log(out, f"log graph {name_}: in plan, its zero line {zmed_:.2f} (max {zmax_:.2f}) and its"
                                      f" curve {cmed_:.2f} (max {cmax_:.2f}) off the trajectory as drawn")
                    if step.get("curtain"):
                        # the graph stands in the well's curtain, the vertical surface between the hole and its
                        # trace at Z = 0: seen from above every point of it is on the trace; in the curtain unrolled
                        # (how far along the trace, how high, as drawn) it is square to the hole, a positive value
                        # towards the surface. A well plumb all along faces the screen, a positive value on its
                        # right. The hole's run is read over the stretch the graph eases its bearing on
                        # (engine/log_track.EASE times its width).
                        zs_ = float(rep_.Scale[2])
                        cam_ = pvv_.GetActiveCamera()
                        sight_ = np.asarray(cam_.GetDirectionOfProjection(), float)
                        cright_ = np.cross(sight_, np.asarray(cam_.GetViewUp(), float))
                        cright_ /= np.linalg.norm(cright_)
                        vals_ = data_.GetPointData().GetScalars()
                        # a log of codes wears its values on its cells: each interval's, at its first node
                        by_node_ = {}
                        cvals_ = data_.GetCellData().GetScalars() if vals_ is None else None
                        if cvals_ is not None:
                            from vtkmodules.vtkCommonCore import vtkIdList as _IdList
                            ids_ = _IdList()
                            for c_ in range(data_.GetNumberOfCells()):
                                data_.GetCellPoints(c_, ids_)
                                on_hole_ = [ids_.GetId(k_) for k_ in range(ids_.GetNumberOfIds()) if ids_.GetId(k_) < n_]
                                if on_hole_:
                                    by_node_[min(on_hole_)] = float(cvals_.GetTuple1(c_))
                        hole_ = at_[:n_] * [1.0, 1.0, zs_]
                        curve_ = at_[n_:] * [1.0, 1.0, zs_]
                        along_ = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(hole_, axis=0), axis=1))])
                        flat_ = hole_[:, :2]
                        run_ = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(flat_, axis=0), axis=1))])
                        wide_ = float(np.linalg.norm(curve_ - hole_, axis=1).max())
                        from fespp_on_trame.engine import log_track as _lt
                        half_ = _lt.EASE * wide_ / 2.0
                        # a well plumb all along: the filter says its graph faces the screen
                        plumb_well_ = data_.GetFieldData().GetArray("LogFacesScreen") is not None
                        seg_a_, seg_ = flat_[:-1], np.diff(flat_, axis=0)
                        seg_len_ = np.linalg.norm(seg_, axis=1)
                        good_, seen_n_, off_trace_, past_ = 0, 0, 0, 0
                        for i_ in range(1, n_ - 1, max(1, n_ // 400)):
                            v_ = float(vals_.GetTuple1(i_)) if vals_ is not None else by_node_.get(i_, 0.0)
                            o3_ = curve_[i_] - hole_[i_]
                            if abs(v_) < 1e-12 or float(np.linalg.norm(o3_)) < 1e-9:
                                continue
                            sign_ = 1.0 if v_ > 0 else -1.0
                            seen_n_ += 1
                            if plumb_well_:
                                good_ += int(float(o3_ @ cright_) / float(np.linalg.norm(o3_)) * sign_ >= 0.97)
                                continue
                            # seen from above: on the trace (its nearest point), past its ends left out
                            rel_ = curve_[i_, :2] - seg_a_
                            t_ = np.clip(np.einsum("mk,mk->m", rel_, seg_) / np.maximum(seg_len_ ** 2, 1e-24), 0.0, 1.0)
                            far_ = np.linalg.norm(rel_ - t_[:, None] * seg_, axis=1)
                            k_ = int(np.argmin(far_))
                            if (k_ == 0 and t_[k_] <= 0.0) or (k_ == len(seg_) - 1 and t_[k_] >= 1.0):
                                past_ += 1
                                continue
                            if float(far_[k_]) > 0.01 * wide_:
                                off_trace_ += 1
                                continue
                            # unrolled: (along the trace, up) from the node, against the hole's run there
                            o2_ = np.array([run_[k_] + t_[k_] * seg_len_[k_] - run_[i_], o3_[2]])
                            lo_ = int(np.searchsorted(along_, along_[i_] - half_))
                            hi_ = min(n_ - 1, int(np.searchsorted(along_, along_[i_] + half_)))
                            lo_, hi_ = min(lo_, i_ - 1), max(hi_, i_ + 1)
                            chord_ = np.array([run_[hi_] - run_[lo_], hole_[hi_, 2] - hole_[lo_, 2]])
                            want_ = np.array([-chord_[1], chord_[0]]) / (float(np.linalg.norm(chord_)) or 1.0)
                            good_ += int(float(o2_ @ want_) / (float(np.linalg.norm(o2_)) or 1.0) * sign_ >= 0.97)
                        read_ = seen_n_ - past_
                        share_ = good_ / read_ if read_ > 0 else 0.0
                        _log(out, f"log graph {name_}: {good_} of {read_} values"
                                  f" {'in the screen plane (plumb well)' if plumb_well_ else 'in the curtain'}, square"
                                  f" to the hole, on the side of their sign; {off_trace_} off the trace seen from"
                                  f" above, {past_} past its ends")
                        if read_ < 10 or share_ < 0.95 or off_trace_:
                            raise RuntimeError(f"log_track_probe: {name_}: {good_} of {read_} values in the well's"
                                               f" curtain on the side of their sign, {off_trace_} off its trace")
                if step.get("true_range") and spans_:
                    # every table within the values the graphs hold (a gap is worn as 0 on the strip)
                    low_, high_ = min(min(a_, 0.0) for a_, _b in spans_), max(max(b_, 0.0) for _a, b_ in spans_)
                    for a_, b_ in tables_:
                        if a_ < low_ - 1e-6 * max(1.0, abs(low_)) or b_ > high_ + 1e-6 * max(1.0, abs(high_)) or b_ <= a_:
                            raise RuntimeError(f"log_track_probe: a table {a_:g} .. {b_:g} reaches past the values"
                                               f" {low_:g} .. {high_:g} of the graphs")
                curves_, tinted_, alone_, gaps_, named_colours_ = 0, [], 0, 0, {}
                for sel_ in sorted(graphs_):
                    ent_ = scene_.block_state.get(sel_) if scene_ is not None else None
                    arr_ = ent_.color_array if ent_ is not None else ""
                    if f"{sel_}/gaps" in shown_blocks_:
                        gaps_ += 1
                    if f"{sel_}/curve" not in shown_blocks_:
                        continue
                    curves_ += 1
                    colour_ = colour_of_.get(f"{sel_}/curve", [1.0, 1.0, 1.0])
                    named_colours_[arr_] = tuple(colour_)
                    if colour_ != [1.0, 1.0, 1.0]:
                        tinted_.append(colour_)
                    elif step.get("coloured"):
                        raise RuntimeError(f"log_track_probe: the curve of {sel_[-12:]} is white")
                    if not strips_.get(sel_, False):
                        alone_ += 1
                        # a curve's colour is its name's: no colour bar for its property
                        if step.get("curves_unbarred") and scene_.bar_visible(arr_):
                            raise RuntimeError(f"log_track_probe: the curve of {arr_} still has its colour bar")
                # the rails drawn by graph, the track's edges: one on each side its kind's values reach
                # {"rails": [2, 1]} — their numbers, graph by graph, in any order
                rails_ = {}
                for sel_ in sorted(graphs_):
                    r_, s_ = graphs_[sel_].get("rails"), graphs_[sel_].get("strip")
                    if r_ is None or s_ is None or f"{sel_}/rails" not in shown_blocks_:
                        continue
                    n_ = s_.GetNumberOfPoints() // 2
                    rails_[sel_[-12:]] = r_.GetNumberOfPoints() // n_ if n_ else 0
                _log(out, f"log rails ({vid_}): {rails_}")
                if "rails" in step and sorted(rails_.values()) != sorted(int(k_) for k_ in step["rails"]):
                    raise RuntimeError(f"log_track_probe: rails {sorted(rails_.values())}, not {sorted(step['rails'])}")
                # the samples highlighted, the held ones (fesppLogLit_) and the one under the log view's cursor
                # (fesppLogCursor_): {"lit": 1} lines from the hole to the curve on graphs, both together,
                # {"lit_cursor": 1} the cursor's alone, {"lit_rings": 1} rings on tubes
                lit_, rings_, cursor_ = 0, 0, 0
                for (n_, _i), s_ in pvsimple.GetSources().items():
                    if n_ not in (f"fesppLogLit_{vid_}", f"fesppLogCursor_{vid_}"):
                        continue
                    if not int(getattr(pvsimple.GetRepresentation(proxy=s_, view=pvv_), "Visibility", 0) or 0):
                        continue
                    d_ = s_.GetClientSideObject().GetOutputDataObject(0)
                    cells_ = d_.GetLines() if d_ is not None else None
                    if cells_ is not None:
                        from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                        offs_ = _v2n(cells_.GetOffsetsArray())
                        sizes_ = offs_[1:] - offs_[:-1]
                        lit_ += int((sizes_ == 2).sum())
                        rings_ += int((sizes_ > 2).sum())
                        if n_.startswith("fesppLogCursor_"):
                            cursor_ += int((sizes_ == 2).sum())
                _log(out, f"log highlights ({vid_}): {lit_} sample(s) lit on the graphs, {rings_} ring(s) on the tubes")
                if "lit" in step and lit_ != int(step["lit"]):
                    raise RuntimeError(f"log_track_probe: {lit_} sample(s) lit, not {step['lit']}")
                if "lit_cursor" in step and cursor_ != int(step["lit_cursor"]):
                    raise RuntimeError(f"log_track_probe: {cursor_} sample(s) lit by the cursor, not {step['lit_cursor']}")
                if "lit_rings" in step and rings_ != int(step["lit_rings"]):
                    raise RuntimeError(f"log_track_probe: {rings_} ring(s) lit, not {step['lit_rings']}")
                # the scales' labels at the logs' two ends: "0" at the hole, a rail's value with its unit
                # {"scale_labels": 6}
                texts_ = sorted(str(s_.Text) for (n_, _i), s_ in pvsimple.GetSources().items()
                                if n_.startswith(f"fesppLogScale_{vid_}_")
                                and int(getattr(pvsimple.GetRepresentation(proxy=s_, view=pvv_), "Visibility", 0) or 0))
                _log(out, f"log scales ({vid_}): {len(texts_)} label(s) {texts_[:8]}")
                if "scale_labels" in step and (len(texts_) != int(step["scale_labels"])
                                               or (texts_ and texts_.count("0") != 2)):
                    raise RuntimeError(f"log_track_probe: {len(texts_)} scale label(s), not {step['scale_labels']}")
                # the chips of the logs' rows, and of the markers' rows ("marker_chips")
                chips_, mchips_ = {}, {}
                for p_, c_ in dict(getattr(state, "ui_tree_extra_chips", None) or {}).items():
                    n_ = tree.find_node_id(p_)
                    marker_ = (tree.find_type(n_) or "") in ("Marker", "WellboreMarker") if n_ is not None else False
                    (mchips_ if marker_ else chips_)[p_] = c_
                _log(out, f"log curves ({vid_}): {alone_} drawn alone, {len(tinted_)} coloured {tinted_}, {len(chips_)}"
                          f" chip(s) in the trees {sorted(chips_.values())}, {len(mchips_)} marker chip(s)"
                          f" {sorted(set(mchips_.values()))}, {gaps_} log(s) with stretches without a value")
                if "marker_chips" in step and len(mchips_) != int(step["marker_chips"]):
                    raise RuntimeError(f"log_track_probe: {len(mchips_)} marker chip(s), not {step['marker_chips']}")
                if "marker_chips_ge" in step and len(mchips_) < int(step["marker_chips_ge"]):
                    raise RuntimeError(f"log_track_probe: {len(mchips_)} marker chip(s), fewer than"
                                       f" {step['marker_chips_ge']}")
                if "curves" in step and alone_ != int(step["curves"]):
                    raise RuntimeError(f"log_track_probe: {alone_} curve(s) drawn alone, not {step['curves']}")
                if "names" in step:
                    # the markers' names written in the view, facing the screen
                    names_ = [n_ for (n_, _i), s_ in pvsimple.GetSources().items()
                              if n_.startswith(f"fesppMarkerName_{vid_}_")
                              and int(getattr(pvsimple.GetRepresentation(proxy=s_, view=pvv_), "Visibility", 0) or 0)]
                    _log(out, f"marker names ({vid_}): {len(names_)} written")
                    if len(names_) != int(step["names"]):
                        raise RuntimeError(f"log_track_probe: {len(names_)} marker name(s) written, not {step['names']}")
                if "gaps" in step and gaps_ != int(step["gaps"]):
                    raise RuntimeError(f"log_track_probe: {gaps_} log(s) with stretches without a value, not {step['gaps']}")
                if step.get("colours_of_2d"):
                    # each curve drawn here wears the colour the 2D log view gives the curve of its log
                    from fespp_on_trame.engine.utils.naming import make_valid_vtk_name as _vtk_name
                    two_d_ = {}
                    for pid_ in mv.panel_ids_of_kind("welllog"):
                        for well_ in (getattr(state, f"welllog_data__{pid_}", None) or {}).get("wells") or ():
                            for track_ in well_.get("tracks") or ():
                                for c_ in track_.get("curves") or ():
                                    hex_ = str(c_.get("color") or "")
                                    if len(hex_) >= 7 and c_.get("name"):
                                        two_d_[_vtk_name(c_["name"])] = tuple(
                                            round(int(hex_[k_:k_ + 2], 16) / 255.0, 3) for k_ in (1, 3, 5))
                    pairs_ = {a_: (c_, two_d_.get(a_)) for a_, c_ in named_colours_.items()}
                    _log(out, f"log curves ({vid_}): 3D colour against the 2D log view's, by log: {pairs_}")
                    if not pairs_ or any(c_ != w_ for c_, w_ in pairs_.values()):
                        raise RuntimeError(f"log_track_probe: the curves' colours differ from the 2D log view's: {pairs_}")
                if "chips" in step and len(chips_) != int(step["chips"]):
                    raise RuntimeError(f"log_track_probe: {len(chips_)} chip(s) in the trees, not {step['chips']}")
                _log(out, f"log graphs ({vid_}): {len(found_)} drawn, {curves_} curve(s),"
                          f" {len(scene_.isolated)} block(s) off the composite")
                if "lines" in step and curves_ != int(step["lines"]):
                    raise RuntimeError(f"log_track_probe: {curves_} curve(s) drawn, not {step['lines']}")
                if "count" in step and len(found_) != int(step["count"]):
                    raise RuntimeError(f"log_track_probe: {len(found_)} graph(s) drawn, not {step['count']}")
                if step.get("curves_unbarred") and found_:
                    # the view's one bar is on a property still drawn by value
                    shown_bar_ = scene_.bar_table()
                    off_bar_ = shown_bar_ is None or scene_.table_bar_hidden(shown_bar_)
                    _log(out, f"log graphs ({vid_}): the view's bar on {(shown_bar_ or {}).get('key')!r}, hidden {off_bar_}")
                    if off_bar_:
                        raise RuntimeError("log_track_probe: no colour bar left for the graphs drawn by value")
                if step.get("one_scale") and len({(round(a_, 9), round(b_, 9)) for a_, b_ in tables_}) > 1:
                    # the logs of one kind drawn to one scale: their tables share one range
                    raise RuntimeError(f"log_track_probe: the graphs of one kind are not on one scale: {tables_}")
                if step.get("tube") or "tubes" in step or "markers" in step or "markers_ge" in step:
                    flt_ = next((s_ for (n_, _i), s_ in pvsimple.GetSources().items()
                                 if n_ == f"fesppWellSymbols_{vid_}"), None)
                    named_ = [s_ for s_ in (flt_.Selectors if flt_ is not None else ()) if not s_.startswith("/__")]
                    round_, marks_, frames_, kb_, kept_kb_ = 0, 0, 0, 0, 0
                    if flt_ is not None:
                        frep_ = pvsimple.GetRepresentation(proxy=flt_, view=pvv_)
                        made_ = flt_.GetClientSideObject().GetOutputDataObject(0)
                        asm_ = made_.GetDataAssembly()
                        zs_ = float(frep_.Scale[2])
                        mscale_ = float(flt_.MarkerScale)
                        if "marker_scale" in step and abs(mscale_ - float(step["marker_scale"])) > 1e-9:
                            raise RuntimeError(f"log_track_probe: the markers drawn {mscale_:g} times as large, not"
                                               f" {step['marker_scale']}")
                        it_ = made_.NewIterator()
                        it_.SetVisitOnlyLeaves(True)
                        it_.SetSkipEmptyNodes(True)
                        it_.InitTraversal()
                        while not it_.IsDoneWithTraversal():
                            kb_ += it_.GetCurrentDataObject().GetActualMemorySize()
                            it_.GoToNextItem()
                        for sel_ in named_:
                            entry_ = scene_.block_state.get(sel_)
                            read_ = [d_ for d_, _f in server.context.assembly_index.datasets(sel_)]
                            mine_ = [made_.GetPartition(i_, 0) for n_ in asm_.SelectNodes([sel_])
                                     for i_ in sorted(asm_.GetDataSetIndices(n_)) if made_.GetNumberOfPartitions(i_)]
                            if not read_ or len(mine_) != len(read_) or any(m_ is None for m_ in mine_):
                                raise RuntimeError(f"log_track_probe: the filter made {len(mine_)} block(s) of {sel_[-40:]}"
                                                   f" for the reader's {len(read_)}")
                            if read_[0].GetFieldData().GetArray("MarkerSymbol") is not None:
                                frames_ += 1
                                for was_, got_ in zip(read_, mine_):
                                    # a marker: MarkerScale times as far from its centre, as drawn, as the reader made it
                                    sym_ = was_.GetFieldData().GetArray("MarkerSymbol")
                                    c_ = np.array(sym_.GetTuple(0)[:3])
                                    far_ = np.linalg.norm((_to_np(got_.GetPoints().GetData()) - c_) * [1.0, 1.0, zs_], axis=1)
                                    ref_ = np.linalg.norm(_to_np(was_.GetPoints().GetData()) - c_, axis=1) * mscale_
                                    if not marks_:
                                        _log(out, f"marker of {sel_[-12:]}: {len(far_)} points up to {far_.max():.1f} from its"
                                                  f" centre as drawn at Z x {zs_:g}, {mscale_:g} times the reader's in the"
                                                  f" data's space")
                                    if not np.allclose(far_, ref_, atol=1e-3):
                                        raise RuntimeError(f"log_track_probe: a marker of {sel_[-12:]} does not keep its size as"
                                                           f" drawn ({far_.max():.2f} for {ref_.max():.2f})")
                                    marks_ += 1
                                continue
                            tube_, was_ = mine_[0], read_[0]
                            kept_kb_ += was_.GetActualMemorySize()
                            sides_ = tube_.GetNumberOfCells()
                            # the reader's log: a tube of as many sides, or its polyline (its LogTubes off): one point a node
                            was_sides_ = was_.GetNumberOfStrips() or 1
                            if ((was_sides_ > 1 and sides_ != was_sides_) or tube_.GetNumberOfPoints() % sides_
                                    or tube_.GetNumberOfPoints() // sides_ < was_.GetNumberOfPoints() // was_sides_):
                                raise RuntimeError(f"log_track_probe: the tube of {sel_} is not laid out as the reader's")
                            ring_ = _to_np(tube_.GetPoints().GetData()).reshape(-1, sides_, 3) * [1.0, 1.0, zs_]
                            far_ = np.linalg.norm(ring_ - ring_.mean(axis=1, keepdims=True), axis=2)
                            flat_ = float((far_.max(axis=1) / np.maximum(far_.min(axis=1), 1e-9)).max())
                            # the reader's tube: the same hole, the same radii — round in the data's space —, the
                            # trajectory's stations between two of its rings (the filter lays the tube on them)
                            rwas_ = _to_np(was_.GetPoints().GetData()).reshape(-1, was_sides_, 3)
                            cwas_ = rwas_.mean(axis=1) * [1.0, 1.0, zs_]
                            cnow_ = ring_.mean(axis=1)
                            said_ = tube_.GetPointData().GetArray("LogSample")
                            if said_ is not None:
                                # the rings that stand for a sample, as the filter says (a station's: -1)
                                rings_said_ = _to_np(said_).reshape(-1, sides_)[:, 0]
                                match_ = np.nonzero(rings_said_ >= 0)[0]
                            else:
                                match_, k_ = [], 0
                                for c_ in cwas_:
                                    while k_ < len(cnow_) and np.abs(cnow_[k_] - c_).max() > 1e-3:
                                        k_ += 1
                                    match_.append(min(k_, len(cnow_) - 1))
                                    k_ += 1
                                match_ = np.asarray(match_)
                            if len(match_) != len(cwas_):
                                raise RuntimeError(f"log_track_probe: the tube of {sel_[-12:]} stands for {len(match_)}"
                                                   f" samples, not the reader's {len(cwas_)}")
                            inserted_ = len(cnow_) - len(cwas_)
                            off_ = float(np.abs(cnow_[match_] - cwas_).max())
                            name_ = entry_.color_array if entry_ is not None else ""
                            a_, b_ = tube_.GetPointData().GetArray(name_), was_.GetPointData().GetArray(name_)
                            # each node's value: the first point of its ring
                            bv_ = _to_np(b_).reshape(-1, was_sides_)[:, 0] if b_ is not None else None
                            if was_sides_ > 1:
                                fwas_ = np.linalg.norm(rwas_ - rwas_.mean(axis=1, keepdims=True), axis=2).mean(axis=1)
                            else:
                                # a polyline's tube has the radius the reader's tube filter gave: 10, up to ten times
                                # as large across the log's values
                                lo_, hi_ = (float(bv_.min()), float(bv_.max())) if bv_ is not None and len(bv_) else (0.0, 0.0)
                                fwas_ = 10.0 * (1.0 + 9.0 * ((bv_ - lo_) / (hi_ - lo_) if hi_ > lo_ else 0.0 * bv_))
                            wide_ = float(np.abs(far_.mean(axis=1)[match_] - fwas_).max())
                            av_ = _to_np(a_).reshape(-1, sides_)[match_][:, 0] if a_ is not None else None
                            same_ = (a_ is not None and b_ is not None and np.array_equal(av_, bv_)
                                     and np.array_equal(np.signbit(av_), np.signbit(bv_)))
                            _log(out, f"log tube {name_!r}: {inserted_} ring(s) of the trajectory's stations between its"
                                      f" samples")
                            fields_ = sorted(was_.GetFieldData().GetArrayName(k_)
                                             for k_ in range(was_.GetFieldData().GetNumberOfArrays()))
                            lost_ = [f_ for f_ in fields_ if tube_.GetFieldData().GetArray(f_) is None]
                            _log(out, f"log tube {name_!r}: {len(ring_)} rings of {sides_}, radius {far_.min():.1f} .."
                                      f" {far_.max():.1f} as drawn, the least round ring {flat_:.3f} times as wide one way as"
                                      f" the other; hole off the reader's by {off_:.2g}, radii by {wide_:.2g}; values the"
                                      f" reader's: {same_}; field data {fields_}, lost {lost_}")
                            if flat_ > 1.01:
                                raise RuntimeError(f"log_track_probe: the tube of {name_} is not round as drawn ({flat_:.2f})")
                            if off_ > 1e-3 or wide_ > 1e-3 or not same_ or lost_:
                                raise RuntimeError(f"log_track_probe: the tube of {name_} is not the reader's made round"
                                                   f" (hole {off_:.3g}, radii {wide_:.3g}, values {same_}, lost {lost_})")
                            round_ += 1
                        if (round_ or marks_) and not int(getattr(frep_, "Visibility", 0) or 0):
                            raise RuntimeError("log_track_probe: the filter's representation is hidden")
                    off_composite_ = len(scene_.isolated)
                    # a log drawn here is a filled graph or a curve alone (its strip hidden)
                    logs_here_ = len(found_) + alone_
                    _log(out, f"well symbols ({vid_}): {round_} round tube(s), {marks_} marker(s) of {frames_} row(s) by the"
                              f" plugin's filter; its output {kb_} kB (the reader's own tubes of them: {kept_kb_} kB);"
                              f" {off_composite_} block(s) off the composite for {round_ + frames_ + logs_here_} drawn here")
                    if off_composite_ != round_ + frames_ + logs_here_:
                        raise RuntimeError(f"log_track_probe: {off_composite_} block(s) off the composite for {round_} tube(s),"
                                           f" {frames_} marker row(s) and {logs_here_} log(s) drawn as a graph or a curve")
                    if "tubes" in step and round_ != int(step["tubes"]):
                        raise RuntimeError(f"log_track_probe: {round_} round tube(s), not {step['tubes']}")
                    if "markers" in step and marks_ != int(step["markers"]):
                        raise RuntimeError(f"log_track_probe: {marks_} marker(s), not {step['markers']}")
                    if marks_ < int(step.get("markers_ge", 0)):
                        raise RuntimeError(f"log_track_probe: {marks_} marker(s), fewer than {step['markers_ge']}")
                for sel_ in sorted(scene_.isolated) if step.get("samples") else ():
                    # what the plugin's block holds: its samples, those without a value, its plain zeros
                    entry_ = scene_.block_state.get(sel_)
                    for ds_, _f in server.context.assembly_index.datasets(sel_):
                        arr_ = ds_.GetPointData().GetArray(entry_.color_array)
                        if arr_ is None:
                            continue
                        sides_ = ds_.GetNumberOfCells()
                        vals_ = _to_np(arr_).reshape(-1, sides_)[:, 0]
                        cnt_ = ds_.GetFieldData().GetArray(entry_.color_array + "_nanCount")
                        zero_ = vals_ == 0
                        _log(out, f"log samples {entry_.color_array!r}: {len(vals_)} nodes, nanCount field"
                                  f" {cnt_.GetTuple1(0) if cnt_ is not None else None}, {int(zero_.sum())} zeros of which"
                                  f" {int(np.signbit(vals_[zero_]).sum())} negative, {arr_.GetDataTypeAsString()}")

            elif op == "log_as":
                # A log drawn as a tube or as a graph through the trial's
                # right-click menus (app/features/log_tracks): the trees' menu
                # must offer the entry on its row and the 3D view's on the log,
                # then the entry runs.
                # {"op":"log_as","title":"Total Porosity","under":"55/33-A-4","tube":true}
                nid_ = _find_node(tree, step)
                if nid_ is None:
                    raise RuntimeError(f"log_as: node not found: {step.get('title')!r}")
                path_ = tree.find_path(nid_)
                mode_ = step.get("mode") or ("tube" if step.get("tube") else "graph")
                key_ = f"log-as-{mode_}"
                vid_ = _render_vid(server, state)
                state.flush()
                offered_ = [a_ for a_ in (getattr(state, "ui_tree_context_actions", None) or [])
                            if a_.get("key") == key_ and path_ in (a_.get("rows") or [])]
                viewed_ = [k_ for x_ in (getattr(server.context, "view_menu_extras", None) or ())
                           for k_, _l in x_(vid_, path_)]
                _log(out, f"log as {mode_}: offered by the tree's menu on its row"
                          f" {bool(offered_)}, by the 3D view's on the log {key_ in viewed_}")
                if not offered_ or key_ not in viewed_:
                    raise RuntimeError(f"log_as: {key_} not offered (tree {bool(offered_)}, view {viewed_})")
                server.context.context_actions_extra[key_](path_, vid_)
                await asyncio.sleep(float(step.get("settle", 2.0)))

            elif op == "folder_eye":
                # The eye of a folder of the tree (a wellbore), as the widget
                # sends it: the deepest eyes under it and the state to put them
                # in (DataExplorerTree.toggleVisible). Closed, nothing under the
                # folder may stay drawn. {"op":"folder_eye","title":"55/33-A-4","visible":false}
                nid_ = _find_node(tree, step)
                if nid_ is None:
                    raise RuntimeError(f"folder_eye: node not found: {step.get('title')!r}")
                folder_ = tree.find_path(nid_)
                vid_ = _render_vid(server, state)
                open_ = list(getattr(state, f"visible_paths__{vid_}", None) or [])
                under_ = [p_ for p_ in open_ if p_.startswith(folder_ + "/")]
                deepest_ = [p_ for p_ in under_ if not any(q_.startswith(p_ + "/") for q_ in under_)]
                with state:
                    state[f"eye_toggle__{vid_}"] = {"path": folder_, "paths": deepest_,
                                                    "visible": bool(step.get("visible")), "n": 900 + len(deepest_)}
                await asyncio.sleep(float(step.get("settle", 3.0)))
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                left_ = [p_ for p_ in (getattr(state, f"visible_paths__{vid_}", None) or []) if p_.startswith(folder_ + "/")]
                drawn_ = [s_ for s_ in (scene_.shown_selectors() if scene_ is not None else ()) if s_.startswith(folder_ + "/")]
                _log(out, f"folder eye {'opened' if step.get('visible') else 'closed'} on {folder_[-30:]}: it sent"
                          f" {len(deepest_)} of the {len(under_)} eyes open under it; {len(left_)} left open,"
                          f" {len(drawn_)} block(s) under it still drawn")
                if not step.get("visible") and (left_ or drawn_):
                    raise RuntimeError(f"folder_eye: closed, {len(left_)} eye(s) left open under it, {len(drawn_)} block(s)"
                                       f" drawn: {[p_[-30:] for p_ in (left_ or drawn_)[:4]]}")

            elif op == "tree_action":
                # An entry of the data tree's right-click menu, as the widget sends it — "read" when the row is a
                # property not read yet (the entry reads it first): {"op":"tree_action","action":"add-to-welllog",
                # "title":"TWTIME","under":"<well>","read":true}
                nid_ = _find_node(tree, step)
                if nid_ is None:
                    raise RuntimeError(f"tree_action: node not found: {step.get('title')!r}")
                with state:
                    state.context_action = {"action": step["action"], "path": tree.find_path(nid_),
                                            "read": bool(step.get("read")), "n": time.time()}

            elif op == "context_extra":
                # An entry a feature added to the right-click menus
                # (`ui_tree_extra_actions`, `ctx.view_menu_extras`): offered by
                # the tree's menu on the row and by the 3D view's on it, then
                # run. {"op":"context_extra","action":"markers-larger","title":"Stratigraphic Marker Set"}
                nid_ = _find_node(tree, step)
                if nid_ is None:
                    raise RuntimeError(f"context_extra: node not found: {step.get('title')!r}")
                path_ = tree.find_path(nid_)
                key_ = step["action"]
                vid_ = _render_vid(server, state)
                state.flush()
                type_ = tree.find_type(nid_) or ""
                offered_ = [a_ for a_ in (getattr(state, "ui_tree_context_actions", None) or [])
                            if a_.get("key") == key_ and (not a_.get("types") or type_ in a_["types"])
                            and (a_.get("rows") is None or path_ in a_["rows"])]
                viewed_ = [k_ for x_ in (getattr(server.context, "view_menu_extras", None) or ())
                           for k_, _l in x_(vid_, path_)]
                _log(out, f"context entry {key_}: offered by the tree's menu on a {type_} row {bool(offered_)},"
                          f" by the 3D view's {key_ in viewed_}")
                if not offered_ or key_ not in viewed_:
                    raise RuntimeError(f"context_extra: {key_} not offered (tree {bool(offered_)}, view {viewed_})")
                server.context.context_actions_extra[key_](path_, vid_)
                await asyncio.sleep(float(step.get("settle", 2.0)))

            elif op == "pictogram_probe":
                # The flag at the head of each well shows the trial's pictogram
                # (engine/wellhead.PICTOGRAM): a glyph of the wellhead font, not
                # the letter A ("glyph": its code point, the platform's by
                # default). {"op":"pictogram_probe","count_ge":1}
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                heads_ = []
                for (name_, _id), src_ in pvsimple.GetSources().items():
                    if not name_.endswith("_mdDatum"):
                        continue
                    rep_ = pvsimple.GetRepresentation(proxy=src_, view=pvv_)
                    heads_.append((name_, f"U+{ord(src_.Text[0]):04X}" if src_.Text else "", str(rep_.FontFamily).strip("'\""),
                                   str(rep_.FontFile or "").replace("\\", "/").rsplit("/", 1)[-1], int(rep_.FontSize),
                                   int(rep_.Visibility)))
                _log(out, f"wellhead flags ({vid_}): {heads_[:4]} of {len(heads_)}")
                good_ = [h_ for h_ in heads_ if h_[1] == step.get("glyph", "U+E001") and h_[2] == "File"
                         and h_[3] == "wellhead.ttf"]
                if len(good_) != len(heads_) or len(good_) < int(step.get("count_ge", 1)):
                    raise RuntimeError(f"pictogram_probe: {len(good_)} flag(s) of {len(heads_)} show the pictogram")
                if "drag" in step:
                    # "drag": the share of the resolution trame gives the frames of a
                    # drag (software rendering: 0.5), which the browser stretches back.
                    # The view shrunk as trame shrinks it, the pictograms, the wells'
                    # names and the markers' names are written that share of their
                    # size — so drawn their size on screen —, and back on release.
                    import types as _types
                    from paraview import servermanager as _sm
                    from trame_vtk.modules import paraview as _tv
                    share_ = float(step["drag"])

                    def _fonts():
                        got_ = {}
                        for (n_, _i), s_ in pvsimple.GetSources().items():
                            if n_.endswith(("_mdDatum", "_name")) or n_.startswith(f"fesppMarkerName_{vid_}_"):
                                r_ = _sm.GetRepresentation(s_, pvv_)
                                if r_ is not None and int(r_.Visibility):
                                    got_[n_] = int(r_.FontSize)
                        return got_

                    pvv_.SMProxy.StillRender()
                    rest_size_ = [int(v) for v in pvv_.ViewSize]
                    rest_ = _fonts()

                    class _Root:
                        def getLinkProtocols(self):
                            return [_types.SimpleNamespace(tracking_views={
                                pvv_.GetGlobalIDAsString(): {"originalSize": tuple(rest_size_)}})]

                    _tv.HELPERS_PER_SERVER["fespp_drag_probe"] = _types.SimpleNamespace(_root_protocol=_Root())
                    try:
                        pvv_.ViewSize = [int(round(v * share_)) for v in rest_size_]
                        dragged_ = _fonts()
                        pvv_.SMProxy.StillRender()
                        drawn_ = _fonts()
                        pvv_.ViewSize = rest_size_
                        back_ = _fonts()
                        pvv_.SMProxy.StillRender()
                    finally:
                        _tv.HELPERS_PER_SERVER.pop("fespp_drag_probe", None)
                    wrong_ = {n_: (f_, dragged_.get(n_), drawn_.get(n_), back_.get(n_)) for n_, f_ in rest_.items()
                              if abs(dragged_.get(n_, -9) - f_ * share_) > 1 or drawn_.get(n_) != dragged_.get(n_)
                              or back_.get(n_) != f_}
                    _log(out, f"drag frames at {share_:g} ({vid_}): {len(rest_)} names and pictograms, at rest"
                              f" {sorted(set(rest_.values()))}, in the drag {sorted(set(dragged_.values()))},"
                              f" back {sorted(set(back_.values()))}")
                    if not rest_ or wrong_:
                        raise RuntimeError(f"pictogram_probe: not sized for the drag's frames"
                                           f" (rest, drag, drawn, back): {dict(list(wrong_.items())[:4])}")

            elif op == "z_change_cost":
                # What a change of the view's Z exaggeration costs once data is
                # drawn: the app's own pass — the scales, the wells' symbols
                # told the new one — with the frame that shows it, then the
                # frame after, against a frame with nothing changed.
                # {"op":"z_change_cost","values":[5,10,22]}
                import time as _time
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                sch_ = server.context.render_scheduler
                idle_ = []
                for _k in range(3):
                    t0_ = _time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    idle_.append(_time.perf_counter() - t0_)
                _log(out, f"z change cost: a frame with nothing changed: {min(idle_) * 1000:.0f} ms")
                for z_ in step.get("values") or (5, 10, 22):
                    t0_ = _time.perf_counter()
                    controller.set_zscale_now(z_)
                    sch_.mark_dirty(vid_)
                    sch_.flush()
                    t1_ = _time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    t2_ = _time.perf_counter()
                    _log(out, f"  Z x {z_}: the app's pass and its frame {1000 * (t1_ - t0_):.0f} ms,"
                              f" the frame after {1000 * (t2_ - t1_):.0f} ms")

            elif op == "reader_property_cost":
                # What a DISPLAY property of the reader costs once data is drawn
                # (the plugin's MarkerSize: a symbol's size, no data read): the
                # reader's own pass, then the view's frame after it — every
                # block's surface extracted again or not —, against a frame with
                # nothing changed. What a vertical exaggeration handed to the
                # plugin would cost at each change of Z.
                # {"op":"reader_property_cost","property":"MarkerSize","times":3}
                import time as _time
                # the reader itself: the source the views draw may be the join of two readers
                src_ = next((p_.SMProxy for p_ in pvsimple.GetSources().values()
                             if p_.SMProxy.GetXMLName() in ("EPCCollector", "ETPsource")), None)
                if src_ is None:
                    raise RuntimeError("reader_property_cost: no reader in the session")
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                name_ = step.get("property", "MarkerSize")
                data_ = src_.GetClientSideObject().GetOutputDataObject(0)
                cells_, blocks_ = 0, 0
                it_ = data_.NewIterator()
                it_.SetVisitOnlyLeaves(True)
                it_.SetSkipEmptyNodes(True)
                it_.InitTraversal()
                while not it_.IsDoneWithTraversal():
                    cells_ += it_.GetCurrentDataObject().GetNumberOfCells()
                    blocks_ += 1
                    it_.GoToNextItem()
                idle_ = []
                for _k in range(3):
                    t0_ = _time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    idle_.append(_time.perf_counter() - t0_)
                prop_ = src_.GetProperty(name_)
                if prop_ is None:
                    raise RuntimeError(f"reader_property_cost: the reader has no property {name_!r}")
                was_ = int(prop_.GetElement(0))
                _log(out, f"reader property cost: {blocks_} block(s), {cells_} cells drawn from the reader;"
                          f" a frame with nothing changed: {min(idle_) * 1000:.0f} ms")
                for k_ in range(int(step.get("times", 3))):
                    prop_.SetElement(0, was_ + 1 + k_)
                    src_.UpdateVTKObjects()
                    t0_ = _time.perf_counter()
                    src_.UpdatePipeline()
                    t1_ = _time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    t2_ = _time.perf_counter()
                    _log(out, f"  {name_} = {was_ + 1 + k_}: the reader {1000 * (t1_ - t0_):.0f} ms,"
                              f" the frame after it {1000 * (t2_ - t1_):.0f} ms")
                prop_.SetElement(0, was_)
                src_.UpdateVTKObjects()
                src_.UpdatePipeline()
                pvv_.SMProxy.StillRender()

            elif op == "block_codes_probe":
                # The shown blocks painted by an array whose name holds
                # `array`: each is painted by CODE — its categories read on
                # its own block, the view's table of that array indexed — as
                # a discrete property is, a well log's channel included.
                # {"op":"block_codes_probe","array":"Zone","codes_ge":2}
                from fespp_on_trame.engine import categorical_palette as _cp
                vid_ = _render_vid(server, state)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                if scene_ is None:
                    raise RuntimeError("block_codes_probe: the view has no scene")
                want_ = str(step.get("array") or "")
                met_ = 0
                for sel_ in sorted(scene_.shown_selectors()):
                    entry_ = scene_.block_state.get(sel_)
                    if entry_ is None or not entry_.color_array or want_ not in entry_.color_array:
                        continue
                    met_ += 1
                    codes_ = [c_["code"] for c_ in (entry_.categories or ())]
                    lut_ = scene_.scoped_lut(entry_.color_array)
                    _log(out, f"block codes {sel_[-50:]}: {entry_.color_array!r} on {entry_.assoc},"
                              f" codes {codes_}, table indexed: {_cp.is_indexed(lut_)},"
                              f" note {entry_.categories_note!r}")
                    if len(codes_) < int(step.get("codes_ge", 1)):
                        raise RuntimeError(f"block_codes_probe: {entry_.color_array!r} is not painted by code"
                                           f" ({entry_.categories_note or 'no codes'})")
                    if not _cp.is_indexed(lut_):
                        raise RuntimeError(f"block_codes_probe: the view's table of {entry_.color_array!r}"
                                           " is not indexed")
                if not met_:
                    raise RuntimeError(f"block_codes_probe: no shown block is painted by an array named like {want_!r}")

            elif op == "lut_annotations":
                # How many named categories the lookup table of an array
                # carries, and whether it paints by category: what the 3D
                # colour bar has to lay out at every render.
                # {"op":"lut_annotations","array":"datetime"}
                lut = pvsimple.GetColorTransferFunction(step["array"])
                prop = lut.SMProxy.GetProperty("Annotations") if lut is not None else None
                n = prop.GetNumberOfElements() // 2 if prop is not None else -1
                _log(out, f"lut {step['array']!r}: IndexedLookup={getattr(lut, 'IndexedLookup', '?')},"
                          f" {n} annotation(s)"
                          + (f", first {prop.GetElement(1)!r}" if n > 0 else ""))
                # and the tables the view's VISIBLE bars draw: what a
                # render lays out (the session table above may not be it)
                pvv = mv.get_pv_view(_render_vid(server, state))
                for r in (pvv.Representations if pvv is not None else []):
                    if r.GetXMLName() != "ScalarBarWidgetRepresentation" \
                            or not int(getattr(r, "Visibility", 0)):
                        continue
                    blut = r.LookupTable
                    ip = blut.SMProxy.GetProperty("IndexedLookup")
                    ap = blut.SMProxy.GetProperty("Annotations")
                    _log(out, f"  bar {r.Title!r}: IndexedLookup={ip.GetElement(0) if ip else '?'},"
                              f" {ap.GetNumberOfElements() // 2 if ap else -1} annotation(s),"
                              f" DrawAnnotations={getattr(r, 'DrawAnnotations', '?')},"
                              f" same table as the session's: {blut.GetGlobalIDAsString() == lut.GetGlobalIDAsString()}")

            elif op == "lut_probe":
                # Are the per-block colour lists PAIRED? BlockColorArrayNames
                # is 3 strings per block, BlockLookupTables one proxy per
                # block, index-wise. Counts them, lists the coloured blocks
                # whose array name another block shares, and tries the
                # ProxyProperty with duplicates to see whether it keeps them.
                # {"op":"lut_probe"}
                cvid = _render_vid(server, state)
                pvv = mv.get_pv_view(cvid)
                src = server.context.active_data_source.get_display_source()
                rep = pvsimple.GetRepresentation(proxy=src, view=pvv)
                scene = (getattr(server.context, "blockscope_scenes", None) or {}).get(cvid)
                names = list(rep.BlockColorArrayNames)
                lut_prop = rep.SMProxy.GetProperty("BlockLookupTables")
                n_lut = lut_prop.GetNumberOfProxies() if lut_prop is not None else -1
                _log(out, f"lut probe ({cvid}): {len(names) // 3} colour triplets,"
                          f" {n_lut} lookup tables on the representation;"
                          f" InterpolateScalarsBeforeMapping={getattr(rep, 'InterpolateScalarsBeforeMapping', '?')}"
                          f" MapScalars={getattr(rep, 'MapScalars', '?')}"
                          f" anchor={list(rep.ColorArrayName)}")
                if scene is not None:
                    by_array = {}
                    for sel in sorted(scene.visible_selectors()):
                        e = scene.block_state[sel]
                        if e.color_array:
                            by_array.setdefault(e.color_array, []).append(sel.rsplit("/", 1)[-1][:12])
                    shared = {a: v for a, v in by_array.items() if len(v) > 1}
                    _log(out, f"  {sum(len(v) for v in by_array.values())} coloured blocks,"
                              f" {len(by_array)} distinct arrays, shared: {shared}")
                # every coloured block whose selector starts with a prefix of
                # "detail": its dataset index, the array's range ON THAT block,
                # and the table it was given (RGBPoints span, NaN colour/opacity)
                if scene is not None and step.get("detail"):
                    import math
                    pdc = src.GetClientSideObject().GetOutputDataObject(0)
                    asm = pdc.GetDataAssembly()
                    for sel in sorted(scene.visible_selectors()):
                        if not any(sel.startswith(p) for p in step["detail"]):
                            continue
                        e = scene.block_state[sel]
                        node = asm.GetFirstNodeByPath(sel)
                        idx = [int(i) for i in asm.GetDataSetIndices(node, True)] if node is not None and node >= 0 else []
                        rng = None
                        for i in idx:
                            pds = pdc.GetPartitionedDataSet(i)
                            for j in range(pds.GetNumberOfPartitions() if pds is not None else 0):
                                ds = pds.GetPartition(j)
                                if ds is None:
                                    continue
                                arr = (ds.GetCellData() if e.assoc == "CELLS" else ds.GetPointData()).GetArray(e.color_array) if e.color_array else None
                                if arr is not None:
                                    rng = list(arr.GetRange())
                        # the block's own arrays, and how many of its cells a
                        # ghost array hides (HIDDENCELL = bit 32)
                        for i in idx:
                            pds = pdc.GetPartitionedDataSet(i)
                            for j in range(pds.GetNumberOfPartitions() if pds is not None else 0):
                                ds = pds.GetPartition(j)
                                if ds is None:
                                    continue
                                cd, pd_ = ds.GetCellData(), ds.GetPointData()
                                cells = [(cd.GetArrayName(k), [round(v, 3) for v in cd.GetArray(k).GetRange()])
                                         for k in range(cd.GetNumberOfArrays())]
                                points = [pd_.GetArrayName(k) for k in range(pd_.GetNumberOfArrays())]
                                ghost = cd.GetArray("vtkGhostType")
                                hidden = 0
                                if ghost is not None:
                                    from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                                    hidden = int(((_v2n(ghost) & 32) != 0).sum())
                                _log(out, f"    partition {i}/{j}: {ds.GetNumberOfCells()} cells, cell arrays {cells},"
                                          f" point arrays {points}, ghost-hidden cells {hidden}")
                        lut = scene.scoped_lut(e.color_array) if e.color_array else None
                        pts = list(lut.RGBPoints) if lut is not None else []
                        if lut is not None:
                            ip = lut.GetProperty("IndexedLookup")
                            ann = lut.GetProperty("Annotations")
                            _log(out, f"    table {lut.GetXMLName()} id={lut.SMProxy.GetGlobalIDAsString()}"
                                      f" indexed={list(ip)[0] if ip is not None else '-'}"
                                      f" annotations={len(list(ann)) // 2 if ann is not None else '-'}"
                                      f" rgb={[round(v, 2) for v in pts[:12]]}"
                                      f" indexed_colours={[round(v, 2) for v in list(getattr(lut, 'IndexedColors', []) or [])[:9]]}"
                                      f" indexed_opacities={list(getattr(lut, 'IndexedOpacities', []) or [])[:6]}"
                                      f" enable_opacity={getattr(lut, 'EnableOpacityMapping', '?')}")
                        xs = pts[0::4]
                        _log(out, f"  block {sel.rsplit('/', 1)[-1][:14]}: array={e.color_array!r} assoc={e.assoc}"
                                  f" categories={len(e.categories) if e.categories else 0}"
                                  f" indexed={getattr(lut, 'IndexedLookup', '?') if lut is not None else '-'}"
                                  f" indices={idx} range_on_block={rng}"
                                  f" lut_span={[min(xs), max(xs)] if xs else None}"
                                  f" nan_colour={list(getattr(lut, 'NanColor', []) or [])}"
                                  f" nan_opacity={getattr(lut, 'NanOpacity', '?')}"
                                  f" finite={all(math.isfinite(v) for v in pts) if pts else None}")
                # the pixels where the grid should be: the still frame's colour
                # at the view's centre and two neighbours on the middle row
                seen_px = []
                try:
                    from vtkmodules.vtkCommonCore import vtkUnsignedCharArray as _UCA
                    pvv.SMProxy.StillRender()
                    rw = pvv.GetClientSideObject().GetRenderWindow()
                    w, h = rw.GetSize()
                    px = _UCA()
                    rw.GetRGBACharPixelData(0, 0, w - 1, h - 1, 1, px)
                    def _at(fx, fy):
                        x, y = int(fx * w), int(fy * h)
                        k = (y * w + x) * 4
                        return [int(px.GetValue(k + c)) for c in range(4)]
                    seen_px = [_at(0.5, 0.5), _at(0.36, 0.5), _at(0.64, 0.5)]
                    _log(out, f"  pixels centre={seen_px[0]} left={seen_px[1]} right={seen_px[2]}"
                              f" background={[round(v * 255) for v in pvv.Background]}")
                except Exception as exc:
                    _log(out, f"  pixels unreadable: {exc}")
                # "expect_painted": the three pixels are an object's, none the
                # background's — what was drawn there is still drawn
                if step.get("expect_painted"):
                    ground = [round(v * 255) for v in pvv.Background]
                    bare = [p for p in seen_px if all(abs(p[c] - ground[c]) <= 2 for c in range(3))]
                    if bare or len(seen_px) != 3:
                        raise RuntimeError(
                            f"lut_probe: {len(bare) if seen_px else 'every'} of the three pixels"
                            f" read on the middle row show the background {ground}: an"
                            f" object coloured there is no longer drawn")
                # "expect_anchor": [assoc, array] — the representation-level
                # anchor the scene must have chosen (the categorical block,
                # since ParaView's per-block road cannot map an indexed table)
                want_anchor = step.get("expect_anchor")
                if want_anchor and list(rep.ColorArrayName) != list(want_anchor):
                    raise RuntimeError(
                        f"lut_probe: the anchor is {list(rep.ColorArrayName)} where"
                        f" {list(want_anchor)} was expected — a block coloured by code"
                        f" left on the per-block road is not drawn")
                # the ORDER of the table list as ParaView holds it, against the
                # colour triplets at the same indices — paired by index in C++
                if lut_prop is not None and n_lut > 0 and scene is not None:
                    by_addr = {}
                    for sel in sorted(scene.visible_selectors()):
                        e = scene.block_state[sel]
                        if e.color_array:
                            by_addr[scene.scoped_lut(e.color_array).GetClientSideObject().GetAddressAsString("vtkObject")] = e.color_array
                    pairs = []
                    for k in sorted(set([0, 1, 2, max(0, n_lut - 2), max(0, n_lut - 1)])):
                        if k < n_lut and 3 * k + 2 < len(names):
                            a = by_addr.get(lut_prop.GetProxy(k).GetClientSideObject().GetAddressAsString("vtkObject"), "?")
                            pairs.append(f"[{k}] triplet={names[3 * k + 2]} table={a}")
                    _log(out, "  pairing " + " | ".join(pairs))
                # what the MAPPER was told, block by block: the composite
                # mapper's display attributes for every leaf of its input,
                # against the tables the scene meant (by client-side address)
                if step.get("mapper"):
                    try:
                        # the actor: the renderer's vtkPVLODActor whose composite
                        # mapper feeds the biggest input (the grid is in it)
                        ren = pvv.GetClientSideObject().GetRenderer()
                        props = ren.GetViewProps()
                        props.InitTraversal()
                        mapper = None
                        for _ in range(props.GetNumberOfItems()):
                            p = props.GetNextProp()
                            m = p.GetMapper() if hasattr(p, "GetMapper") else None
                            if m is None or not m.IsA("vtkCompositePolyDataMapper") or m.GetInputDataObject(0, 0) is None:
                                continue
                            has = m.GetCompositeDataDisplayAttributes() is not None
                            _log(out, f"    candidate {p.GetClassName()} visible={p.GetVisibility()}"
                                      f" mode={m.GetScalarMode()} array={m.GetArrayName()!r} attrs={has}"
                                      f" cells={m.GetInputDataObject(0, 0).GetNumberOfCells()}")
                            if p.GetVisibility() and has and (mapper is None or m.GetInputDataObject(0, 0).GetNumberOfCells() > mapper.GetInputDataObject(0, 0).GetNumberOfCells()):
                                mapper = m
                        if mapper is None:
                            raise RuntimeError("no composite mapper in the renderer")
                        attrs = mapper.GetCompositeDataDisplayAttributes()
                        inp = mapper.GetInputDataObject(0, 0)
                        want = {}
                        if scene is not None:
                            for sel in sorted(scene.visible_selectors()):
                                e = scene.block_state[sel]
                                if e.color_array:
                                    lut = scene.scoped_lut(e.color_array)
                                    want[lut.GetClientSideObject().GetAddressAsString("vtkObject")] = e.color_array
                        rep_lut = rep.LookupTable.GetClientSideObject().GetAddressAsString("vtkObject") if rep.LookupTable else None
                        _log(out, f"  mapper {mapper.GetClassName()} input {inp.GetClassName()},"
                                  f" global ScalarMode={mapper.GetScalarMode()} array={mapper.GetArrayName()!r}"
                                  f" rep LUT={want.get(rep_lut, rep_lut)}")
                        it = inp.NewIterator()
                        it.SetVisitOnlyLeaves(False)
                        it.SetSkipEmptyNodes(True)
                        it.InitTraversal()
                        shown = 0
                        while not it.IsDoneWithTraversal():
                            d = it.GetCurrentDataObject()
                            flat = it.GetCurrentFlatIndex()
                            it.GoToNextItem()
                            n_cells = d.GetNumberOfCells() if hasattr(d, "GetNumberOfCells") else -1
                            big = n_cells > 100000 or (d.IsA("vtkCompositeDataSet") and flat <= 3)
                            if not big and shown >= int(step.get("mapper_limit", 3)):
                                continue
                            shown += 0 if big else 1
                            bl = attrs.GetBlockLookupTable(d) if attrs.HasBlockLookupTable(d) else None
                            bl_addr = bl.GetAddressAsString("vtkObject") if bl is not None else None
                            _log(out, f"    flat {flat} {d.GetClassName()} cells={n_cells}"
                                      f" vis={attrs.GetBlockVisibility(d) if attrs.HasBlockVisibility(d) else '-'}"
                                      f" array={attrs.GetBlockArrayName(d) if attrs.HasBlockArrayName(d) else '-'!r}"
                                      f" mode={attrs.GetBlockScalarMode(d) if attrs.HasBlockScalarMode(d) else '-'}"
                                      f" scalarvis={attrs.GetBlockScalarVisibility(d) if attrs.HasBlockScalarVisibility(d) else '-'}"
                                      f" lut={want.get(bl_addr, bl_addr)}"
                                      f" uselutrange={attrs.GetBlockUseLookupTableScalarRange(d) if attrs.HasBlockUseLookupTableScalarRange(d) else '-'}")
                    except Exception as exc:
                        _log(out, f"  mapper probe failed: {exc!r}")
            elif op == "pixel_blame":
                # WHO DRAWS THIS COLOUR. Counts the still frame's pixels of
                # `rgb` (each channel within `tol`), then hides every visible
                # representation of the view in turn, renders, counts again
                # and restores it: a representation whose absence changes the
                # count is named, with the properties that say what it is.
                # "expect_none": true fails the scenario while any such pixel
                # is left — AFTER the blame, so the log says who.
                # {"op":"pixel_blame","rgb":[255,0,255],"tol":8,"expect_none":true}
                import numpy as _np
                from vtkmodules.vtkCommonCore import vtkUnsignedCharArray as _UCA
                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                cvid = _render_vid(server, state)
                pvv = mv.get_pv_view(cvid)
                want = _np.array(step.get("rgb") or [255, 0, 255], dtype=int)
                tol = int(step.get("tol") if step.get("tol") is not None else 8)
                rw = pvv.GetClientSideObject().GetRenderWindow()
                # "invert": count the pixels NOT of `rgb` — with the view's
                # background as `rgb`, everything drawn. "hide_families":
                # representation kinds hidden for the whole probe (the colour
                # bars and labels, to count the geometry alone), put back at
                # the end.
                invert = bool(step.get("invert"))
                pre_hidden = [r for r in pvv.Representations
                              if getattr(r, "Visibility", 0)
                              and r.SMProxy.GetXMLName() in (step.get("hide_families") or [])]
                for r in pre_hidden:
                    r.Visibility = 0

                def _hits():
                    pvv.SMProxy.StillRender()
                    w, h = rw.GetSize()
                    px = _UCA()
                    rw.GetRGBACharPixelData(0, 0, w - 1, h - 1, 1, px)
                    a = _v2n(px).reshape(h, w, 4)[:, :, :3].astype(int)
                    m = _np.abs(a - want).max(axis=2) <= tol
                    if invert:
                        m = ~m
                    n = int(m.sum())
                    if not n:
                        return 0, None
                    ys, xs = _np.nonzero(m)
                    # the box in screen terms: x from the left, y from the TOP
                    return n, [int(xs.min()), int(h - 1 - ys.max()),
                               int(xs.max()), int(h - 1 - ys.min())]

                def _who(r):
                    src = getattr(r, "Input", None)
                    name = None
                    if src is not None:
                        for (nm, _id), p in pvsimple.GetSources().items():
                            if p == src:
                                name = nm
                                break
                    bits = [r.SMProxy.GetXMLName(), f"source={name!r}"]
                    if src is not None and hasattr(src, "Text"):
                        bits.append(f"text={str(src.Text)[:40]!r}")
                    for prop in ("TextPropMode", "Color", "Opacity", "BackgroundColor",
                                 "BackgroundOpacity", "ShowBorder", "FrameColor",
                                 "FontSize", "BillboardPosition", "DisplayOffset",
                                 "BasePosition", "TopPosition", "FlagSize",
                                 "Representation", "ColorArrayName", "Title"):
                        # a property this kind of representation lacks is
                        # simply not listed
                        if not hasattr(r, prop):
                            continue
                        v = getattr(r, prop)
                        if hasattr(v, "__len__") and not isinstance(v, str):
                            v = list(v)
                        bits.append(f"{prop}={v!r}")
                    return " ".join(bits)

                n0, box0 = _hits()
                # the context's texture units, and how many are held: VTK 9.6
                # composite mappers each hold one they never give back
                try:
                    tum = rw.GetState().GetTextureUnitManager()
                    n_units = tum.GetNumberOfTextureUnits()
                    held = sum(1 for i in range(n_units) if tum.IsAllocated(i))
                    _log(out, f"pixel_blame ({cvid}): texture units held {held}"
                              f" of {n_units}")
                except Exception as exc:
                    _log(out, f"pixel_blame ({cvid}): texture units unreadable: {exc!r}")
                _log(out, f"pixel_blame ({cvid}): {n0} pixel(s) of {want.tolist()}"
                          f" within {tol}, box={box0} (x0, y0, x1, y1 from the top-left)"
                          f" window={list(rw.GetSize())}")
                reps = [r for r in pvv.Representations
                        if getattr(r, "Visibility", 0)]
                _log(out, f"  {len(reps)} visible representation(s)")
                blamed = []
                if n0:
                    for r in reps:
                        r.Visibility = 0
                        try:
                            n1, _box1 = _hits()
                        finally:
                            r.Visibility = 1
                        if n1 != n0:
                            blamed.append(r)
                            _log(out, f"  BLAMED: {n0} -> {n1} without {_who(r)}")
                    if not blamed:
                        _log(out, "  no single representation carries it: hiding each"
                                  " in turn leaves the count unchanged")
                    # by FAMILY (the representation's XML name), every subset
                    # of families hidden at once: a colour two families draw
                    # each on their own survives any single removal
                    fams = {}
                    for r in reps:
                        fams.setdefault(r.SMProxy.GetXMLName(), []).append(r)
                    names = sorted(fams)
                    import itertools as _it
                    for k in range(1, len(names) + 1):
                        for combo in _it.combinations(names, k):
                            hid = [r for nm in combo for r in fams[nm]]
                            for r in hid:
                                r.Visibility = 0
                            try:
                                n2, box2 = _hits()
                            finally:
                                for r in hid:
                                    r.Visibility = 1
                            _log(out, f"  hidden {'+'.join(f'{nm}({len(fams[nm])})' for nm in combo)}:"
                                      f" {n2} pixel(s), box={box2}")
                    try:
                        caps = rw.ReportCapabilities() or ""
                        rend = [ln.strip() for ln in caps.splitlines()
                                if "renderer" in ln.lower() or "vendor" in ln.lower()][:2]
                    except Exception as exc:
                        rend = [f"error: {exc}"]
                    bg = {}
                    for prop in ("Background", "Background2", "BackgroundColorMode",
                                 "UseColorPaletteForBackground",
                                 "OrientationAxesVisibility", "UseFXAA",
                                 "UseToneMapping", "UseSSAO", "EnableOSPRay",
                                 "UseLight", "UseFrameBufferObject"):
                        try:
                            v = getattr(pvv, prop)
                        except Exception as exc:
                            bg[prop] = f"error: {exc}"
                            continue
                        if hasattr(v, "__len__") and not isinstance(v, str):
                            v = list(v)
                        bg[prop] = v
                    _log(out, f"  renderer: {rend}")
                    _log(out, f"  view: {bg}")
                    # "experiments": each one sets properties, counts, and
                    # puts every value back — on the view ("view"), on the
                    # main composite representation ("rep"), on every text
                    # representation ("text")
                    # {"experiments":[{"view":{"UseFXAA":0}},
                    #                 {"rep":{"InterpolateScalarsBeforeMapping":0}}]}
                    main_src = server.context.active_data_source.get_display_source()
                    main_rep = pvsimple.GetRepresentation(proxy=main_src, view=pvv)
                    texts = fams.get("TextSourceRepresentation", [])
                    for ex in step.get("experiments") or []:
                        undo = []
                        try:
                            for key, targets in (("view", [pvv]), ("rep", [main_rep]),
                                                 ("text", texts)):
                                for prop, val in (ex.get(key) or {}).items():
                                    for t in targets:
                                        old = getattr(t, prop)
                                        if hasattr(old, "GetData"):
                                            old = old.GetData()
                                        undo.append((t, prop, old))
                                        setattr(t, prop, val)
                            n3, box3 = _hits()
                            _log(out, f"  experiment {ex}: {n3} pixel(s), box={box3}")
                        except Exception as exc:
                            _log(out, f"  experiment {ex}: failed: {exc!r}")
                        finally:
                            for t, prop, old in reversed(undo):
                                try:
                                    setattr(t, prop, old)
                                except Exception as exc:
                                    _log(out, f"  experiment undo {prop}: {exc!r}")
                    for r in reps[:60]:
                        if r not in blamed:
                            _log(out, f"  innocent: {_who(r)[:160]}")
                    _hits()
                for r in pre_hidden:
                    r.Visibility = 1
                if pre_hidden:
                    pvv.SMProxy.StillRender()
                if step.get("expect_none") and n0:
                    raise RuntimeError(
                        f"pixel_blame: {n0} pixel(s) of {want.tolist()} in the frame,"
                        f" box={box0}; blamed: "
                        + ("; ".join(_who(r)[:120] for r in blamed) or "none"))
            elif op == "rep_set":
                # Set properties on the view's main (composite) representation
                # by hand and render — a way to ask ParaView "and if the anchor
                # named THIS array?" without touching the projection code.
                # {"op":"rep_set","props":{"ColorArrayName":["CELLS","Fluids"]}}
                cvid = _render_vid(server, state)
                pvv = mv.get_pv_view(cvid)
                src = server.context.active_data_source.get_display_source()
                rep = pvsimple.GetRepresentation(proxy=src, view=pvv)
                for name, value in (step.get("props") or {}).items():
                    setattr(rep, name, value)
                    _log(out, f"rep_set ({cvid}): {name} = {value!r}")
                # "keep_triplets": keep only the colour triplets (and their
                # paired tables) whose selector starts with one of these —
                # a block isolated on the per-block road, the others gone
                keep = step.get("keep_triplets")
                if keep is not None:
                    names = list(rep.BlockColorArrayNames)
                    lut_prop = rep.SMProxy.GetProperty("BlockLookupTables")
                    luts = [lut_prop.GetProxy(i) for i in range(lut_prop.GetNumberOfProxies())]
                    trip = [(names[k:k + 3], luts[k // 3] if k // 3 < len(luts) else None)
                            for k in range(0, len(names), 3)]
                    chosen = [t for t in trip if any(t[0][0].startswith(p) for p in keep)]
                    rep.BlockColorArrayNames = [x for t in chosen for x in t[0]]
                    lut_prop.RemoveAllProxies()
                    for t in chosen:
                        if t[1] is not None:
                            lut_prop.AddProxy(t[1])
                    rep.SMProxy.UpdateProperty("BlockColorArrayNames", 1)
                    rep.SMProxy.UpdateProperty("BlockLookupTables", 1)
                    _log(out, f"rep_set ({cvid}): {len(chosen)} triplet(s) kept: "
                              + ", ".join(t[0][0].rsplit('/', 1)[-1][:12] + ':' + t[0][2] for t in chosen[:4]))
                rep.SMProxy.UpdateVTKObjects()
                pvv.SMProxy.StillRender()
            elif op == "block_vis_probe":
                # What ParaView was TOLD about the composite: the block
                # selectors and visibilities on the view's main representation,
                # its colour array, and what the scene believes is visible —
                # the two sides of "the eye is open but the grid is gone".
                # {"op":"block_vis_probe"}
                cvid = _render_vid(server, state)
                pvv = mv.get_pv_view(cvid)
                src = server.context.active_data_source.get_display_source()
                scene = (getattr(server.context, "blockscope_scenes", None) or {}).get(cvid)
                # the scene's own representation: on a stage of the source (a
                # converted or a cut view), asking for the source's makes a leaf
                # one — which {"of_source": true} does on purpose, as a display
                # lookup of the app does: the scene, back on the source, must
                # not take that leaf for its composite
                rep = ((None if step.get("of_source") else getattr(scene, "main_rep", None))
                       or pvsimple.GetRepresentation(proxy=src, view=pvv))
                vis_sel = sorted(scene.visible_selectors()) if scene is not None else None
                _log(out, f"block vis ({cvid}): rep Visibility={rep.Visibility}"
                          f" ColorArrayName={list(rep.ColorArrayName)}"
                          f" Assembly={getattr(rep, 'Assembly', '?')}")
                for prop in ("BlockSelectors", "BlockColorArrayNames", "BlockLookupTables",
                             "BlockColors", "BlockOpacities"):
                    try:
                        val = list(getattr(rep, prop))
                    except Exception as exc:
                        val = f"unreadable ({exc})"
                        _log(out, f"  rep.{prop}: unreadable ({exc})")
                    if isinstance(val, list):
                        _log(out, f"  rep.{prop}: {len(val)} entr{'y' if len(val) == 1 else 'ies'}")
                        for v in val[:int(step.get('limit', 12))]:
                            _log(out, f"    {v}")
                        # and, whatever the limit, the entries of the blocks
                        # the step expects visible: a triplet is 3 strings
                        for prefix in (step.get("expect_visible") or []):
                            for k, v in enumerate(val):
                                if isinstance(v, str) and v.startswith(prefix):
                                    _log(out, f"    [{k}] {v} {val[k + 1:k + 3]}")
                    else:
                        _log(out, f"  rep.{prop}: {val}")
                if vis_sel is not None:
                    _log(out, f"  scene.visible_selectors: {len(vis_sel)}")
                    for v in vis_sel[:int(step.get('limit', 12))]:
                        _log(out, f"    {v}")
                    _log(out, f"  scene.isolated: {sorted(getattr(scene, 'isolated', ()) or ())}")
                    # the assertion: every prefix named must still be visible
                    for prefix in (step.get("expect_visible") or []):
                        if not any(s.startswith(prefix) for s in vis_sel):
                            raise RuntimeError(
                                f"block_vis_probe: no visible selector starts with"
                                f" {prefix!r} — that block left the visible set")
            elif op == "property_type":
                # A property's kind set as the T→D view's Kind does
                # (app/features/property_types; "" = the file's kind back).
                # {"op":"property_type","title":"VAvg","under":"velocity_dataset","kind":"avg seismic velocity"}
                nid = _find_node(tree, step)
                if nid is None:
                    raise RuntimeError(f"node not found: {step.get('title')!r}")
                with state:
                    server.context.property_type_set(tree.find_path(nid), step.get("kind", ""))
                await asyncio.sleep(float(step.get("settle", 3)))
                _log(out, f"property_type {step.get('title')!r}:"
                          f" kinds={dict(getattr(state, 'property_kinds', None) or {})!r}")
            elif op == "bounds_probe":
                # The bounds of every leaf dataset the reader holds, with its
                # assembly path, and the bounds the renderer computes for
                # what is drawn — a NaN, an infinity or a coordinate a
                # thousand times the others is what makes a camera reset,
                # a clipping range or a locator go wrong, and it says which
                # object brought it. {"op":"bounds_probe","limit":40}
                import math
                cvid = _render_vid(server, state)
                pvv = mv.get_pv_view(cvid)
                src = server.context.collector.get_source()
                pdc = src.GetClientSideObject().GetOutputDataObject(0)
                asm = pdc.GetDataAssembly() if pdc is not None else None
                # the assembly names each partitioned dataset by index: walk
                # every node once and remember which index it owns
                owner = {}
                if asm is not None:
                    for node in asm.GetChildNodes(0, True):
                        for idx in asm.GetDataSetIndices(node, False):
                            owner[int(idx)] = asm.GetNodePath(node)
                leaves = []
                for i in range(pdc.GetNumberOfPartitionedDataSets()):
                    pds = pdc.GetPartitionedDataSet(i)
                    for j in range(pds.GetNumberOfPartitions() if pds is not None else 0):
                        leaves.append((i, j, pds.GetPartition(j)))
                bad = []
                shown = 0
                limit = int(step.get("limit", 40))
                _log(out, f"pdc: {pdc.GetNumberOfPartitionedDataSets()} partitioned dataset(s),"
                          f" {len(leaves)} partition(s)")
                for i, j, ds in leaves:
                    flat = f"{i}/{j}"
                    if ds is None or not ds.IsA("vtkDataSet") or ds.GetNumberOfPoints() == 0:
                        continue
                    b = list(ds.GetBounds())
                    finite = all(math.isfinite(v) for v in b)
                    huge = finite and max(abs(v) for v in b) > 1e8
                    name = owner.get(i, "(no assembly node)")
                    line = (f"  pds {flat} {ds.GetClassName()} pts={ds.GetNumberOfPoints()}"
                            f" cells={ds.GetNumberOfCells()} bounds={[round(v, 1) if math.isfinite(v) else v for v in b]}"
                            f" {name}")
                    if not finite or huge:
                        bad.append(line)
                    elif shown < limit:
                        shown += 1
                        _log(out, line)
                for line in bad:
                    _log(out, "  BAD" + line)
                # what the assembly SAYS each node owns: a node with several
                # indices, or an index past the collection's end, is a link
                # the reader left behind
                stale = 0
                if asm is not None:
                    n_pds = pdc.GetNumberOfPartitionedDataSets()
                    for node in asm.GetChildNodes(0, True):
                        idx = [int(i) for i in asm.GetDataSetIndices(node, False)]
                        if len(idx) > 1 or any(i >= n_pds for i in idx):
                            stale += 1
                            _log(out, f"  assembly node {asm.GetNodePath(node)} owns indices {idx}"
                                      f" (collection has {n_pds})")
                # "expect_partitions": the collection must hold exactly this many
                # partitioned datasets; "unique_links": no node may own two
                want_n = step.get("expect_partitions")
                if want_n is not None and pdc.GetNumberOfPartitionedDataSets() != int(want_n):
                    raise RuntimeError(
                        f"bounds_probe: {pdc.GetNumberOfPartitionedDataSets()} partitioned"
                        f" dataset(s) where {want_n} were expected — the reader duplicated"
                        f" or lost blocks")
                if step.get("unique_links") and stale:
                    raise RuntimeError(
                        f"bounds_probe: {stale} assembly node(s) own several or stale"
                        f" dataset indices")
                if pvv is not None:
                    ren = pvv.GetClientSideObject().GetRenderer()
                    vb = [0.0] * 6
                    ren.ComputeVisiblePropBounds(vb)
                    cam = ren.GetActiveCamera()
                    _log(out, f"renderer visible prop bounds={[round(v, 1) for v in vb]}"
                              f" clipping={list(cam.GetClippingRange())}"
                              f" position={[round(v, 1) for v in cam.GetPosition()]}"
                              f" focal={[round(v, 1) for v in cam.GetFocalPoint()]}")
                    # "expect_max_extent": the visible scene spans at most this
                    # many metres in X and in Y. One object placed in the
                    # wrong crs (thousands of kilometres off) stretches it
                    # until a camera reset leaves everything sub-pixel; an
                    # extent is what says so in one number.
                    max_ext = step.get("expect_max_extent")
                    if max_ext is not None:
                        span = max(vb[1] - vb[0], vb[3] - vb[2])
                        if not span <= float(max_ext):
                            raise RuntimeError(
                                f"bounds_probe: the visible scene spans {span:.0f} m,"
                                f" more than {float(max_ext):.0f} — an object sits far"
                                f" from the rest (a crs origin missing?)")
                _log(out, f"bounds probe: {len(bad)} dataset(s) with non-finite or huge bounds")
                if bad and step.get("strict", True):
                    raise RuntimeError(f"bounds_probe: {len(bad)} dataset(s) carry NaN, infinite"
                                       f" or absurd coordinates — see the BAD lines")
            elif op in ("profile_on", "profile_off"):
                # Where the time of a run of steps goes, function by function:
                # profile_on starts a cProfile of the server thread (the
                # handlers and the event loop the steps and their settles
                # run), profile_off stops it and logs the wall time and the
                # top entries by cumulative and by own time.
                # {"op":"profile_on"} … {"op":"profile_off","top":40}
                import cProfile
                import pstats
                import io
                if op == "profile_on":
                    _prof = cProfile.Profile()
                    _prof_t0 = time.monotonic()
                    _prof.enable()
                    _log(out, "profile: on")
                else:
                    _prof.disable()
                    _log(out, f"profile: off after {time.monotonic() - _prof_t0:.1f} s wall")
                    for key in ("cumulative", "tottime"):
                        buf = io.StringIO()
                        pstats.Stats(_prof, stream=buf).sort_stats(key).print_stats(int(step.get("top", 40)))
                        _log(out, f"  --- by {key}")
                        for ln in buf.getvalue().splitlines():
                            if ln.strip() and not ln.strip().startswith(("Ordered", "ncalls")) \
                                    and "function calls" not in ln:
                                _log(out, "    " + ln.rstrip()[:230])

            elif op == "stack_dump":
                # Where is the server WHEN IT HANGS? faulthandler writes the
                # Python stack of every thread to stderr (app.log) every
                # `every` seconds, whatever the main thread is doing — a
                # render that never returns shows up as the same frames
                # dump after dump. {"op":"stack_dump","every":30}
                import faulthandler
                every = float(step.get("every", 30))
                # to the scenario's crash_stack.txt when the run armed it (a
                # file the kill leaves whole; the process's fd 2 goes through
                # the stderr tee, which a main thread stuck in C starves, and
                # the dumps were lost — 29/10), else to the process's own fd 2
                # (pvpython's sys.stderr is a capture helper with no fileno())
                sink_ = _crash_file if "_crash_file" in dir() and _crash_file is not None else 2
                faulthandler.enable(file=sink_, all_threads=True)
                faulthandler.dump_traceback_later(every, repeat=True, file=sink_)
                _log(out, f"stack dump: every {every:g} s to"
                          f" {'crash_stack.txt' if sink_ != 2 else 'stderr'}, all threads,"
                          f" until the scenario ends")
            elif op == "render_bench":
                # What one frame costs, and what the delivery settings do to
                # it — measured, on the loaded scene, in the view as it is:
                #   still and interactive renders, timed (best of N);
                #   the interactive render again with the LOD forced on, and
                #   the view's own word on whether the LOD really drew it;
                #   the still render again with FXAA off;
                #   the JPEG a still frame becomes ON THE PATH trame TAKES
                #   (vtkPVWebApplication.StillRenderToBuffer: render, readback
                #   and encode in one call), at each quality, size and time.
                #   These are the knobs a config change can turn.
                # {"op":"render_bench","repeat":8}
                from paraview.modules.vtkPVClientWeb import vtkPVWebApplication
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                if pvv is None:
                    raise RuntimeError("render_bench: no render view")
                reps = int(step.get("repeat", 8))
                if step.get("view_size"):
                    # the reader's real window, not the harness's 400x400:
                    # encode and render costs scale with the pixels
                    pvv.ViewSize = [int(v) for v in step["view_size"]]
                    pvv.SMProxy.StillRender()
                cso = pvv.GetClientSideObject()
                rw = cso.GetRenderWindow()
                w0, h0 = rw.GetSize()
                # what the LOD threshold is compared with: the geometry the
                # view delivers to its renderer, in KB, as ParaView sums it
                try:
                    vis_kb = cso.GetDeliveryManager().GetVisibleDataSize(False)
                    vis = f"{vis_kb / 1024:.1f} MB"
                except Exception as exc:
                    _log(out, f"  visible geometry unreadable: {exc}")
                    vis = "?"
                _log(out, f"render bench ({vid}) window {w0}x{h0}:"
                          f" visible geometry {vis}"
                          f" LODThreshold={pvv.LODThreshold}"
                          f" LODResolution={getattr(pvv, 'LODResolution', '?')}"
                          f" RemoteRenderThreshold={getattr(pvv, 'RemoteRenderThreshold', '?')}"
                          f" UseFXAA={getattr(pvv, 'UseFXAA', '?')}")

                def _best(fn):
                    best = None
                    for _ in range(reps):
                        t0 = time.perf_counter()
                        fn()
                        dt = time.perf_counter() - t0
                        best = dt if best is None else min(best, dt)
                    return best * 1000.0

                still = _best(pvv.SMProxy.StillRender)
                inter = _best(pvv.SMProxy.InteractiveRender)
                lod_before = float(pvv.LODThreshold)
                pvv.LODThreshold = 0.0
                pvv.UpdateVTKObjects()
                inter_lod = _best(pvv.SMProxy.InteractiveRender)
                # the view says whether the LOD really drew that frame
                lod_used = bool(cso.GetUsedLODForLastRender())
                pvv.LODThreshold = lod_before
                pvv.UpdateVTKObjects()
                fxaa_before = int(pvv.UseFXAA)
                pvv.UseFXAA = 0
                pvv.UpdateVTKObjects()
                still_nofxaa = _best(pvv.SMProxy.StillRender)
                pvv.UseFXAA = fxaa_before
                pvv.UpdateVTKObjects()
                pvv.SMProxy.StillRender()
                _log(out, f"  still={still:.1f} ms  interactive={inter:.1f} ms"
                          f"  interactive+LOD(forced)={inter_lod:.1f} ms"
                          f" (LOD used: {lod_used})"
                          f"  still without FXAA={still_nofxaa:.1f} ms")
                # the still frame as the browser receives it, at each
                # quality: what StillRenderToBuffer costs and weighs, the
                # cache invalidated before every call so each one really
                # renders, reads back and encodes. NOT vtkJPEGWriter on the
                # same pixels — that writer is several times slower than the
                # delivered path and the browser never sees it, so a bench of
                # it overstates the encode cost.
                web = vtkPVWebApplication()
                for q in (100, 90, 80, 70):
                    best_ms = None
                    size = -1
                    for _ in range(reps):
                        web.InvalidateCache(pvv.SMProxy)
                        t0 = time.perf_counter()
                        buf = web.StillRenderToBuffer(pvv.SMProxy, int(t0 * 1000), q)
                        dt = (time.perf_counter() - t0) * 1000.0
                        best_ms = dt if best_ms is None else min(best_ms, dt)
                        size = buf.GetNumberOfTuples() if buf else -1
                    _log(out, f"  still frame as delivered q{q}: {size / 1024:.0f} KB"
                              f" in {best_ms:.1f} ms (render+readback+encode)")

            elif op == "filter_bench":
                # The real VTK filters, on the REAL loaded block, with an
                # explicit Update() so the work actually happens here and not
                # in some later frame. This is what answers "what does the
                # threaded backend buy on OUR data" — a synthetic benchmark
                # answers a different question.
                # {"op":"filter_bench","repeat":3}
                from vtkmodules.vtkCommonCore import vtkSMPTools
                from vtkmodules.vtkFiltersCore import vtkThreshold
                from vtkmodules.vtkFiltersVerdict import vtkCellSizeFilter
                src = server.context.collector.get_source()
                pdc = src.GetClientSideObject().GetOutputDataObject(0)
                it = pdc.NewIterator()
                it.SetVisitOnlyLeaves(True)
                it.InitTraversal()
                biggest, ncells = None, 0
                while not it.IsDoneWithTraversal():
                    ds = it.GetCurrentDataObject()
                    n = ds.GetNumberOfCells() if ds is not None else 0
                    if n > ncells:
                        biggest, ncells = ds, n
                    it.GoToNextItem()
                if biggest is None or ncells == 0:
                    raise RuntimeError("filter_bench: no block with cells")
                cd = biggest.GetCellData()
                arr = None
                for i in range(cd.GetNumberOfArrays() if cd is not None else 0):
                    a = cd.GetArray(i)
                    if a is not None and a.GetNumberOfComponents() == 1:
                        arr = a
                        break
                tag = (f"{vtkSMPTools.GetBackend()}"
                       f"/{vtkSMPTools.GetEstimatedNumberOfThreads()}")
                reps = int(step.get("repeat", 3))
                res = {}
                if arr is not None:
                    lo, hi = arr.GetRange()
                    mid = lo + (hi - lo) * 0.5
                    best = None
                    for _ in range(reps):
                        th = vtkThreshold()
                        th.SetInputData(biggest)
                        th.SetInputArrayToProcess(0, 0, 0, 1, arr.GetName())
                        th.SetLowerThreshold(lo)
                        th.SetUpperThreshold(mid)
                        th.SetThresholdFunction(vtkThreshold.THRESHOLD_BETWEEN)
                        t0 = time.perf_counter()
                        th.Update()
                        dt = time.perf_counter() - t0
                        best = dt if best is None else min(best, dt)
                    res[f"vtkThreshold({arr.GetName()})"] = best
                best = None
                for _ in range(reps):
                    f = vtkCellSizeFilter()
                    f.SetInputData(biggest)
                    f.ComputeVolumeOn()
                    t0 = time.perf_counter()
                    f.Update()
                    dt = time.perf_counter() - t0
                    best = dt if best is None else min(best, dt)
                res["vtkCellSizeFilter"] = best
                _log(out, f"filter bench — VTK {tag} — block of"
                          f" {ncells} cells: "
                          + "  ".join(f"{k}={v * 1000:.0f} ms"
                                      for k, v in res.items()))

            elif op == "xyz_crop_probe":
                # The X/Y/Z crops of the view's isolates (the Geometry slicer
                # on an object without I/J/K, engine/sources/xyz_crop): the
                # object's cells, each crop's axes and cells kept.
                # {"op":"xyz_crop_probe","crops":1,"axes":[[0]],"fewer":true}
                cvid = _render_vid(server, state)
                isolates = {k: v for k, v in (getattr(server.context, "grid_isolates", None) or {}).items()
                            if k[0] == cvid and not v.snapshot().get("ijk")}
                if not isolates:
                    raise RuntimeError("xyz_crop_probe: no X/Y/Z isolate in the view")
                for key, iso in isolates.items():
                    snap = iso.snapshot()
                    whole = iso.source_extract.GetDataInformation().GetNumberOfCells()
                    crops = iso.xyz_crop_cells()
                    _log(out, f"xyz crops of {key[1][-50:]!r}: mode={snap['mode']}"
                              f" bounds={[round(v, 1) for v in snap['bounds']]} whole={whole}"
                              f" crops={crops} volumes={snap['volumes']}")
                    # what the preparation made of the object (its cells'
                    # extents, the scene cut's filters)
                    from fespp_on_trame.engine.blockscope import scene_crop as _sc
                    for crop_ in getattr(iso, "_xyz_crops", []):
                        prep_ = getattr(crop_, "_prep", None)
                        if prep_ is None:
                            continue
                        src_ = prep_.Input
                        src_.UpdatePipeline()
                        sd_ = src_.GetClientSideObject().GetOutputDataObject(0)
                        pd_ = prep_.GetClientSideObject().GetOutputDataObject(0)
                        dims_ = [0, 0, 0]
                        if sd_ is not None and sd_.IsA("vtkStructuredGrid"):
                            sd_.GetDimensions(dims_)
                        cb_ = pd_.GetFieldData().GetArray(_sc.CELLBOX) if pd_ is not None and pd_.IsA("vtkDataSet") else None
                        _log(out, f"  prep: in {sd_.GetClassName() if sd_ else None} dims {dims_}"
                                  f" {sd_.GetNumberOfPoints() if sd_ else 0}p {sd_.GetNumberOfCells() if sd_ else 0}c;"
                                  f" out {pd_.GetClassName() if pd_ else None}, extents {cb_.GetNumberOfTuples() if cb_ else None}")
                    if "crops" in step and len(crops) != int(step["crops"]):
                        raise RuntimeError(f"xyz_crop_probe: {len(crops)} crops, not {step['crops']}")
                    if "axes" in step and [list(a) for a, _c in crops] != step["axes"]:
                        raise RuntimeError(f"xyz_crop_probe: axes {[a for a, _c in crops]}, not {step['axes']}")
                    if step.get("fewer") and not all(c is not None and 0 < c < whole for _a, c in crops):
                        raise RuntimeError(f"xyz_crop_probe: a crop keeps nothing or everything: {crops}"
                                           f" of {whole}")
                    if "mode" in step and snap["mode"] != step["mode"]:
                        raise RuntimeError(f"xyz_crop_probe: mode {snap['mode']}, not {step['mode']}")

            elif op == "render_timing":
                # What a frame of the view costs: the first still render
                # (pipelines brought up to date with it), then still and
                # interactive renders of a camera turning — what a hand
                # rotating the view waits for (the PO, 29/10: the cut scene
                # was slow even to rotate). The representations drawn and
                # the cells they hold are logged. `drag`: the frames drawn as
                # a drag's, the button down as trame's mouse handler says it
                # (frames.in_drag), at that share of the resolution (1: a GPU
                # drags at full resolution; below 1 what frames.drag_ratio
                # says while trame streams smaller frames — the harness has no
                # trame link), then one frame at rest, the release, timed.
                # {"op":"render_timing","label":"cut","frames":5,"drag":0.5}
                import time as _time
                import statistics as _stats
                from fespp_on_trame.app.features import log_tracks as _log_tracks
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                cam_ = pvv_.GetActiveCamera()
                t0_ = _time.perf_counter()
                pvv_.SMProxy.StillRender()
                first_ = _time.perf_counter() - t0_
                still_, inter_ = [], []
                drag_ = step.get("drag")
                rest_ratio_ = _log_tracks.drag_ratio
                if drag_:
                    pvv_.UseInteractiveRenderingForScreenshots = 1
                    if float(drag_) < 1.0:
                        _log_tracks.drag_ratio = lambda _view, r=float(drag_): r
                try:
                    for _k in range(int(step.get("frames", 5))):
                        cam_.Azimuth(12)
                        t0_ = _time.perf_counter()
                        pvv_.SMProxy.InteractiveRender()
                        inter_.append(_time.perf_counter() - t0_)
                        cam_.Azimuth(12)
                        t0_ = _time.perf_counter()
                        pvv_.SMProxy.StillRender()
                        still_.append(_time.perf_counter() - t0_)
                finally:
                    _log_tracks.drag_ratio = rest_ratio_
                    if drag_:
                        pvv_.UseInteractiveRenderingForScreenshots = 0
                if drag_:
                    t0_ = _time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    _log(out, f"render timing [{step.get('label', '')}]: release frame"
                              f" {(_time.perf_counter() - t0_) * 1000:.0f} ms")
                reps_ = []
                for r_ in pvv_.Representations or []:
                    try:
                        if not int(r_.Visibility):
                            continue
                        info_ = r_.GetRepresentedDataInformation()
                        reps_.append(f"{r_.GetXMLName()}:{info_.GetNumberOfCells()}c")
                    except Exception as exc:
                        reps_.append(f"? ({exc})")
                _log(out, f"render timing [{step.get('label', '')}]: first {first_ * 1000:.0f} ms,"
                          f" still {_stats.median(still_) * 1000:.0f} ms, interactive"
                          f" {_stats.median(inter_) * 1000:.0f} ms (median of {len(still_)});"
                          f" {len(reps_)} rep(s) drawn: {', '.join(reps_[:8])}")

            elif op == "card_narrow":
                # Every range of one box of a slicer card narrowed to the
                # middle `fraction` of its subject's extent, through the
                # card's own gesture — the worst case of a cut: every axis
                # narrowed on both sides.
                # {"op":"card_narrow","card":"ui_geometry_card__view_1",
                #  "method":"geometry_slicer","box":0,"fraction":0.5}
                vid_ = _render_vid(server, state)
                st_ = getattr(state, step["card"], None) or {}
                box_ = (st_.get("card") or {}).get("boxes", [])[int(step.get("box", 0))]
                ext_ = {s["value"]: s["extent"] for s in st_.get("subjects") or []}
                fr_ = float(step.get("fraction", 0.5))
                for subj_, ranges_ in (box_.get("ranges") or {}).items():
                    lo_, hi_ = (float(v) for v in ext_[subj_])
                    pad_ = (hi_ - lo_) * (1.0 - fr_) / 2.0
                    for r_ in ranges_:
                        getattr(controller, step["method"])(
                            {"op": "set_range", "id": r_["id"], "low": lo_ + pad_, "high": hi_ - pad_}, vid_)
                await asyncio.sleep(float(step.get("settle", 2)))

            elif op == "scene_cut_mark_profile":
                # The mark of the cut scene taken apart, on the prep stage's
                # real output: the collection's shallow copy, the walk over
                # its leaves, the numpy rule, the arrays added.
                # {"op":"scene_cut_mark_profile"}
                import time as _time
                import numpy as _np
                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                vid_ = _render_vid(server, state)
                crop_ = getattr((getattr(server.context, "blockscope_scenes", None) or {}).get(vid_), "crop", None)
                if crop_ is None or not crop_._stages:
                    raise RuntimeError("scene_cut_mark_profile: the scene is not cut")
                data_ = crop_._stages[0].GetClientSideObject().GetOutputDataObject(0)
                t0_ = _time.perf_counter()
                cp_ = data_.NewInstance()
                cp_.ShallowCopy(data_)
                t1_ = _time.perf_counter()
                it_ = data_.NewIterator()
                it_.SetVisitOnlyLeaves(True)
                it_.SetSkipEmptyNodes(True)
                it_.InitTraversal()
                leaves_, cells_, boxed_ = 0, 0, 0
                t_np = 0.0
                while not it_.IsDoneWithTraversal():
                    ds_ = it_.GetCurrentDataObject()
                    leaves_ += 1
                    if ds_ is not None and ds_.IsA("vtkDataSet"):
                        cells_ += ds_.GetNumberOfCells()
                        cb_ = ds_.GetFieldData().GetArray("__fespp_cellbox")
                        if cb_ is not None:
                            boxed_ += 1
                            a_ = _time.perf_counter()
                            v_ = _v2n(cb_).reshape(6, -1)
                            (v_[0] <= 1e12) & (v_[1] >= -1e12)
                            t_np += _time.perf_counter() - a_
                    it_.GoToNextItem()
                t2_ = _time.perf_counter()
                # each leaf's own shallow copy, by class
                it_ = data_.NewIterator()
                it_.SetVisitOnlyLeaves(True)
                it_.SetSkipEmptyNodes(True)
                it_.InitTraversal()
                while not it_.IsDoneWithTraversal():
                    ds_ = it_.GetCurrentDataObject()
                    a_ = _time.perf_counter()
                    c_ = ds_.NewInstance()
                    c_.ShallowCopy(ds_)
                    b_ = _time.perf_counter()
                    arrs_ = [ds_.GetCellData().GetArrayName(i) for i in range(ds_.GetCellData().GetNumberOfArrays())]
                    _log(out, f"  leaf {it_.GetCurrentFlatIndex()}: {ds_.GetClassName()} {ds_.GetNumberOfCells()} cells,"
                              f" shallow copy {(b_ - a_) * 1000:.1f} ms, cell arrays {arrs_[:8]}")
                    it_.GoToNextItem()
                asm_ = data_.GetDataAssembly() if hasattr(data_, "GetDataAssembly") else None
                if asm_ is not None:
                    _log(out, f"  assembly: {len(asm_.GetChildNodes(0, True))} node(s)")
                _log(out, f"mark profile: shallow copy {(t1_ - t0_) * 1000:.0f} ms, walk {(t2_ - t1_) * 1000:.0f} ms"
                          f" ({leaves_} leaves, {boxed_} boxed, {cells_} cells), numpy {t_np * 1000:.0f} ms")
                # the cut itself, on a move
                for k_ in range(3):
                    crop_._boxes = [[[lo + 1, hi + 1] for lo, hi in b] for b in crop_._boxes]
                    crop_._stages[1].Boxes = json.dumps(crop_._boxes)
                    a_ = _time.perf_counter()
                    crop_._stages[1].UpdatePipeline()
                    b_ = _time.perf_counter()
                    _log(out, f"  cut {(b_ - a_) * 1000:.0f} ms")

            elif op == "cut_chain_bisect":
                # The scene cut's work redone by hand on what the view draws,
                # block by block and step by step, each step logged BEFORE
                # it runs: the last line before a crash names the call that
                # died. {"op":"cut_chain_bisect"}
                from fespp_on_trame.engine.blockscope import scene_crop as _sc
                vid_ = _render_vid(server, state)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                sels_ = sorted(scene_.shown_selectors() - scene_.isolated)
                base_ = server.context.active_data_source.get_display_source()
                _log(out, f"bisect: {len(sels_)} block(s) drawn: {[s_[-40:] for s_ in sels_]}")
                eb_ = pvsimple.ExtractBlock(Input=base_)
                eb_.Assembly = "Assembly"
                eb_.Selectors = sels_
                _log(out, "bisect: ExtractBlock update")
                eb_.UpdatePipeline()
                ids_ = pvsimple.PointAndCellIds(Input=eb_)
                ids_.GeneratePointIds = 0
                ids_.CellIdsArrayName = "vtkOriginalCellIds"
                _log(out, "bisect: PointAndCellIds update")
                ids_.UpdatePipeline()
                data_ = ids_.GetClientSideObject().GetOutputDataObject(0)
                for it_, ds_ in _sc._leaves(data_):
                    tag_ = (f"leaf {it_.GetCurrentFlatIndex()} {ds_.GetClassName()} {ds_.GetNumberOfCells()}c"
                            f" {ds_.GetNumberOfPoints()}p")
                    if ds_.IsA("vtkPolyData"):
                        tag_ += (f" verts {ds_.GetNumberOfVerts()} lines {ds_.GetNumberOfLines()}"
                                 f" polys {ds_.GetNumberOfPolys()} strips {ds_.GetNumberOfStrips()}")
                    _log(out, f"bisect: {tag_}: prepared")
                    c_ = _sc._prep_leaf(ds_, {}, {})
                    _log(out, f"bisect: {tag_}: cut ({c_.GetClassName()} {c_.GetNumberOfCells()}c, extents"
                              f" {c_.GetFieldData().GetArray(_sc.CELLBOX) is not None}, face table"
                              f" {c_.GetFieldData().GetArray(_sc.FACE_META) is not None})")
                    d_ = _sc._cut_leaf(c_, [[[-1e12, 1e12], [-1e12, 1e12], [-1e12, 1e12]]])
                    _log(out, f"bisect: {tag_}: kept {d_.GetClassName()} {d_.GetNumberOfCells()}c")
                for p_ in (ids_, eb_):
                    pvsimple.Delete(p_)
                _log(out, "bisect: done")

            elif op == "scene_cut_step_timing":
                # Where a step of the cut scene goes (the PO, 29/10: slow on
                # ADME): the cut's planes moved a little, then each stage
                # brought up to date in turn — the shared source, the ids
                # filter, the pieces — and the still render.
                # {"op":"scene_cut_step_timing","steps":3}
                import time as _time
                vid_ = _render_vid(server, state)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                crop_ = getattr(scene_, "crop", None)
                if crop_ is None or not crop_.tips():
                    raise RuntimeError("scene_cut_step_timing: the scene is not cut")
                pvv_ = mv.get_pv_view(vid_)
                rows_ = []
                from fespp_on_trame.engine.blockscope import scene_crop as _sc
                for k_ in range(int(step.get("steps", 3))):
                    d_ = 1.0 if k_ % 2 == 0 else -1.0
                    crop_._boxes = [[[lo + d_, hi + d_] for lo, hi in box_] for box_ in crop_._boxes]
                    crop_._stages[1].Boxes = json.dumps(crop_._boxes)
                    t = [_time.perf_counter()]
                    crop_._base.UpdatePipeline()
                    t.append(_time.perf_counter())
                    crop_._stages[0].UpdatePipeline()
                    t.append(_time.perf_counter())
                    # the cut's own run (VTK), then what the proxy adds
                    crop_._stages[1].GetClientSideObject().Update()
                    t.append(_time.perf_counter())
                    crop_._stages[1].UpdatePipeline()
                    t.append(_time.perf_counter())
                    # the representation's own run (VTK), then what the proxy adds
                    scene_.main_rep.GetClientSideObject().Update()
                    t.append(_time.perf_counter())
                    scene_.main_rep.UpdatePipeline()
                    t.append(_time.perf_counter())
                    pvv_.SMProxy.Update()
                    t.append(_time.perf_counter())
                    pvv_.SMProxy.StillRender()
                    t.append(_time.perf_counter())
                    pvv_.SMProxy.StillRender()
                    t.append(_time.perf_counter())
                    rows_.append([round((t[i + 1] - t[i]) * 1000) for i in range(9)])
                    prof_ = ", ".join(f"{c_[:14]} {n_in}->{n_out} {ms_:.0f}" for c_, n_in, n_out, ms_ in _sc.LAST_CUT_PROFILE)
                    _log(out, f"  cut leaf by leaf (class in->out ms): {prof_}")
                _log(out, "scene cut step [source, prep, cut, cut proxy, rep, rep proxy, view update, render, render again] ms: "
                          + "; ".join(map(str, rows_)))
                # ParaView's geometry filter alone, on the whole cut: what the
                # representation pays per block
                try:
                    from paraview.modules.vtkPVVTKExtensionsFiltersRendering import vtkPVGeometryFilter as _PVGeo
                    tip_ = crop_._stages[-1].GetClientSideObject().GetOutputDataObject(0)
                    leaves_ = [ds_ for _it, ds_ in _sc._leaves(tip_)]
                    g_ = _PVGeo()
                    g_.SetInputData(tip_)
                    a_ = _time.perf_counter()
                    g_.Update()
                    b_ = _time.perf_counter()
                    g2_ = _PVGeo()
                    g2_.SetInputData(tip_)
                    g2_.SetPassThroughCellIds(0)
                    g2_.SetPassThroughPointIds(0)
                    g2_.Update()
                    c_ = _time.perf_counter()
                    _log(out, f"  geometry filter on the whole cut ({len(leaves_)} leaves,"
                              f" {sum(d.GetNumberOfCells() for d in leaves_)} cells): {(b_ - a_) * 1000:.0f} ms;"
                              f" without the pass-through ids {(c_ - b_) * 1000:.0f} ms")
                    # what else the representation does with the composite
                    # each step: ParaView's hierarchy of the assembly, the
                    # block selectors resolved, the memory walked
                    from vtkmodules.vtkCommonDataModel import vtkDataAssembly as _DA
                    from vtkmodules.vtkCommonDataModel import vtkDataAssemblyUtilities as _DAU
                    a_ = _time.perf_counter()
                    h_ = _DA()
                    _DAU.GenerateHierarchy(tip_, h_)
                    b_ = _time.perf_counter()
                    sels_ = sorted(scene_.shown_selectors() - scene_.isolated)
                    nodes_ = tip_.GetDataAssembly().SelectNodes(sels_)
                    c_ = _time.perf_counter()
                    mem_ = tip_.GetActualMemorySize()
                    d_ = _time.perf_counter()
                    _log(out, f"  composite of {tip_.GetNumberOfPartitionedDataSets()} partitioned sets,"
                              f" assembly of {len(tip_.GetDataAssembly().GetChildNodes(0, True))} nodes:"
                              f" hierarchy {(b_ - a_) * 1000:.0f} ms, {len(sels_)} selectors to {len(nodes_)} nodes"
                              f" {(c_ - b_) * 1000:.0f} ms, memory size {(d_ - c_) * 1000:.0f} ms ({mem_} kB)")
                except Exception as exc_:
                    _log(out, f"  geometry filter: not profiled ({exc_})")
                # what the representation does with the biggest leaf of the
                # cut: ParaView's geometry filter as it is, and cell normals
                # alone
                try:
                    from paraview.modules.vtkPVVTKExtensionsFiltersRendering import vtkPVGeometryFilter as _PVGeo
                    from vtkmodules.vtkFiltersCore import vtkPolyDataNormals as _Normals
                    tip_ = crop_._stages[-1].GetClientSideObject().GetOutputDataObject(0)
                    big_ = max((ds_ for _it, ds_ in _sc._leaves(tip_)), key=lambda d: d.GetNumberOfCells())
                    g_ = _PVGeo()
                    g_.SetInputData(big_)
                    a_ = _time.perf_counter()
                    g_.Update()
                    b_ = _time.perf_counter()
                    n_ = _Normals()
                    n_.SetInputData(big_)
                    n_.ComputePointNormalsOff()
                    n_.ComputeCellNormalsOn()
                    n_.SplittingOff()
                    n_.ConsistencyOff()
                    n_.Update()
                    c_ = _time.perf_counter()
                    _log(out, f"  biggest leaf: {big_.GetClassName()} {big_.GetNumberOfCells()} cells"
                              f" {big_.GetNumberOfPoints()} points; PV geometry filter {(b_ - a_) * 1000:.0f} ms"
                              f" (cell normals {g_.GetGenerateCellNormals()}), cell normals alone {(c_ - b_) * 1000:.0f} ms")
                except Exception as exc_:
                    _log(out, f"  biggest leaf: not profiled ({exc_})")

            elif op == "xyz_vs_scene_bench":
                # The object's X/Y/Z crop two ways, on the isolate's own grid,
                # the same box at each step: the VTK chain (a Threshold an
                # axis, engine/sources/xyz_crop) and the scene cut's filters
                # (engine/blockscope/scene_crop, numpy on the cells' extents).
                # {"op":"xyz_vs_scene_bench","fraction":0.6,"steps":5}
                import time as _time
                from fespp_on_trame.engine.sources import xyz_crop as _xc
                from fespp_on_trame.engine.blockscope.scene_crop import SceneCrop as _SC
                vid_ = _render_vid(server, state)
                isos_ = [v_ for k_, v_ in (getattr(server.context, "grid_isolates", None) or {}).items() if k_[0] == vid_]
                if not isos_:
                    raise RuntimeError("xyz_vs_scene_bench: no isolate in the view")
                root_ = isos_[0]._render_root()
                root_.UpdatePipeline()
                b_ = list(root_.GetDataInformation().GetBounds())
                fr_ = float(step.get("fraction", 0.6))

                def _box(k_):
                    out_ = []
                    for n_ in range(3):
                        lo_, hi_ = b_[2 * n_], b_[2 * n_ + 1]
                        pad_ = (hi_ - lo_) * (1.0 - fr_) / 2.0
                        shift_ = (hi_ - lo_) * 0.01 * (k_ % 3)
                        out_.append([lo_ + pad_ + shift_, hi_ - pad_ + shift_])
                    return out_

                def _cells(proxy_):
                    d_ = proxy_.GetClientSideObject().GetOutputDataObject(0)
                    if d_.IsA("vtkCompositeDataSet"):
                        it_ = d_.NewIterator()
                        it_.InitTraversal()
                        n_ = 0
                        while not it_.IsDoneWithTraversal():
                            n_ += it_.GetCurrentDataObject().GetNumberOfCells()
                            it_.GoToNextItem()
                        return n_
                    return d_.GetNumberOfCells()

                steps_ = int(step.get("steps", 5))
                # the object's crop as it is (engine/sources/xyz_crop)
                crop_ = _xc.CoordCrop(root_, "bench_crop")
                crop_.set_box(_box(0), b_)
                a_ = _time.perf_counter()
                crop_.tip.UpdatePipeline()
                t_coords = (_time.perf_counter() - a_) * 1000
                vtk_ms, vtk_cells = [], 0
                for k_ in range(steps_):
                    crop_.set_box(_box(k_ + 1), b_)
                    a_ = _time.perf_counter()
                    crop_.tip.UpdatePipeline()
                    vtk_ms.append((_time.perf_counter() - a_) * 1000)
                    vtk_cells = _cells(crop_.tip)
                crop_.delete()
                # the scene cut's filters
                sc_ = _SC(f"{vid_}_bench")
                sc_.set_boxes(root_, [_box(0)], b_)
                tip_ = sc_.tips()[0]
                a_ = _time.perf_counter()
                tip_.UpdatePipeline()
                t_prep = (_time.perf_counter() - a_) * 1000
                np_ms, np_cells = [], 0
                for k_ in range(steps_):
                    sc_.set_boxes(root_, [_box(k_)], b_)
                    a_ = _time.perf_counter()
                    tip_.UpdatePipeline()
                    np_ms.append((_time.perf_counter() - a_) * 1000)
                    np_cells = _cells(tip_)
                sc_.release()
                _log(out, f"xyz bench ({root_.GetDataInformation().GetNumberOfCells()} cells, box {fr_:.0%} on 3 axes):"
                          f" object crop once {t_coords:.0f} ms, a step {[round(v) for v in vtk_ms]} ms, {vtk_cells} cells kept;"
                          f" scene filters once {t_prep:.0f} ms, a step {[round(v) for v in np_ms[1:]]} ms, {np_cells} cells kept")

            elif op == "peek":
                # The view as it is, to the scenario's folder: what a reader
                # sees, when the counts say nothing (a block whose selector
                # is off still counts its cells) — in shots/, never compared
                # (`shot` makes the images a baseline holds). {"op":"peek","name":"after"}
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                pvsimple.Render(view=pvv_)
                # in a folder of its own: a png at the top of the scenario's
                # folder is compared with a baseline
                os.makedirs(os.path.join(out, "shots"), exist_ok=True)
                f_ = os.path.join(out, "shots", f"shot_{step.get('name', i)}.png")
                pvsimple.SaveScreenshot(f_, pvv_, ImageResolution=[800, 600])
                _log(out, f"shot: shots/{os.path.basename(f_)}")

            elif op == "visible_reps_probe":
                # Every display the view draws: the proxy behind it, its
                # cells, the array it is coloured by — the answer to "what is
                # painted?" when the counts and the shot disagree (the PO,
                # 30/10: a cut scene drawn whole under a SOIL range).
                # {"op":"visible_reps_probe"}
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                names_ = {}
                for (name_, _id), p_ in pvsimple.GetSources().items():
                    names_[p_.SMProxy.GetGlobalIDAsString()] = name_
                shown_ = []
                for rep_ in pvv_.Representations:
                    try:
                        if not int(rep_.Visibility):
                            continue
                        inp_ = getattr(rep_, "Input", None)
                        if inp_ is None:
                            continue
                        gid_ = inp_.SMProxy.GetGlobalIDAsString()
                        inp_.UpdatePipeline()
                        info_ = inp_.GetDataInformation()
                        try:
                            color_ = list(rep_.ColorArrayName)
                        except Exception:
                            color_ = None
                        b_ = info_.GetBounds()
                        shown_.append(f"    {names_.get(gid_, '?')} ({inp_.GetXMLName()} #{gid_}):"
                                      f" {info_.GetNumberOfCells()} cells, colour {color_},"
                                      f" z {b_[4]:.1f}..{b_[5]:.1f}")
                        try:
                            data_ = inp_.GetClientSideObject().GetOutputDataObject(0)
                        except Exception:
                            data_ = None
                        if data_ is not None and data_.IsA("vtkCompositeDataSet"):
                            from fespp_on_trame.engine.blockscope.scene_crop import _leaves as _lv
                            try:
                                sel_ = list(rep_.BlockSelectors)
                            except Exception:
                                sel_ = None
                            shown_.append(f"      blocks selected: {sel_}")
                            for it_, ds_ in _lv(data_):
                                bb_ = ds_.GetBounds()
                                shown_.append(f"      leaf {it_.GetCurrentFlatIndex()} {ds_.GetClassName()}"
                                              f" {ds_.GetNumberOfCells()} cells, z {bb_[4]:.1f}..{bb_[5]:.1f}")
                    except Exception as exc_:
                        shown_.append(f"    (a display unread: {exc_!r})")
                _log(out, f"visible displays ({vid_}): {len(shown_)}")
                for line_ in shown_:
                    _log(out, line_)

            elif op == "scene_entries":
                # What the view's scene gives the blocks whose selector holds `match`: shown, painted by which
                # array (and whether their datasets hold it), their solid colour — {"op":"scene_entries","match":"subrep"}
                vid_ = _render_vid(server, state)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                index_ = getattr(server.context, "assembly_index", None)
                for sel_, ent_ in sorted((getattr(scene_, "block_state", None) or {}).items()):
                    nid_ = tree.find_node_id(sel_)
                    title_ = (tree.find_title(nid_) or "") if nid_ is not None else ""
                    if step.get("title") is not None and title_ != step["title"]:
                        continue
                    if str(step.get("match", "")).lower() not in sel_.lower():
                        continue
                    sets_ = index_.datasets(sel_) if index_ is not None else []
                    held_ = [bool(ent_.color_array) and any(
                        (ds_.GetCellData() is not None and ds_.GetCellData().GetArray(ent_.color_array) is not None)
                        or (ds_.GetPointData() is not None and ds_.GetPointData().GetArray(ent_.color_array) is not None)
                        for ds_, _f in sets_)]
                    _log(out, f"scene entry {sel_[-60:]}: visible={getattr(ent_, 'visible', None)}"
                              f" array={ent_.color_array!r} ({ent_.assoc}) held={held_} solid={ent_.solid_rgb}"
                              f" isolated={sel_ in getattr(scene_, 'isolated', ())} datasets={len(sets_)}"
                              f" {[ds_.GetClassName() + ':' + str(ds_.GetNumberOfCells()) for ds_, _f in sets_[:2]]}")
                    # {"no_missing_array": true}: a block shown is never painted by an array it does not hold (white)
                    if step.get("no_missing_array") and getattr(ent_, "visible", False) and ent_.color_array                             and sets_ and sel_ not in getattr(scene_, "isolated", ()) and not any(held_):
                        raise RuntimeError(f"scene_entries: {sel_[-40:]} painted by {ent_.color_array!r}, which it does"
                                           f" not hold")

            elif op == "scene_blocks_probe":
                # Every block the view draws: its cells in the source and in
                # the scene cut's output (the PO, 29/10 evening: wellbores
                # ticked outside the cut stayed away once the cut widened).
                # {"op":"scene_blocks_probe"}; with "drawn": true every block
                # shown must find, at the place its row of the tree points
                # at, the very datasets its own reader delivered for it —
                # readers joined in one tree (engine/sources/merged_source)
                # whose rows point elsewhere draw another object's, or nothing.
                vid_ = _render_vid(server, state)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                crop_ = getattr(scene_, "crop", None)
                tips_ = crop_.tips() if crop_ is not None else []
                src_ = server.context.active_data_source.get_display_source()
                src_.UpdatePipeline()
                sdata_ = src_.GetClientSideObject().GetOutputDataObject(0)
                tdata_ = None
                if tips_:
                    tips_[0].UpdatePipeline()
                    tdata_ = tips_[0].GetClientSideObject().GetOutputDataObject(0)

                def _leaf_cells(data_, flat_):
                    if data_ is None:
                        return "-"
                    it_ = data_.NewIterator()
                    it_.SetVisitOnlyLeaves(True)
                    it_.SetSkipEmptyNodes(False)
                    it_.InitTraversal()
                    while not it_.IsDoneWithTraversal():
                        if it_.GetCurrentFlatIndex() == flat_:
                            d_ = it_.GetCurrentDataObject()
                            return "empty" if d_ is None else f"{d_.GetClassName()} {d_.GetNumberOfCells()}c"
                        it_.GoToNextItem()
                    return "absent"

                def _datasets_of(data_, path_):
                    """(class, points, cells) of every dataset the row
                    `path_` of the tree of `data_` points at."""
                    asm_ = data_.GetDataAssembly() if data_ is not None else None
                    node_ = asm_.GetFirstNodeByPath(path_) if asm_ is not None else -1
                    if node_ <= 0:
                        return None
                    found_ = []
                    for i_ in asm_.GetDataSetIndices(node_, True):
                        pds_ = data_.GetPartitionedDataSet(i_)
                        for k_ in range(pds_.GetNumberOfPartitions() if pds_ is not None else 0):
                            d_ = pds_.GetPartition(k_)
                            if d_ is not None:
                                found_.append((d_.GetClassName(), d_.GetNumberOfPoints(), d_.GetNumberOfCells()))
                    return sorted(found_)

                shown_ = sorted(scene_.shown_selectors() - scene_.isolated) if scene_ is not None else []
                _log(out, f"scene blocks ({vid_}): {len(shown_)} shown, cut={'yes' if tips_ else 'no'},"
                          f" boxes={crop_._boxes if crop_ is not None else None}")
                for sel_ in shown_:
                    flats_ = server.context.assembly_index.flat_indices(sel_)
                    cells_ = [(f_, _leaf_cells(sdata_, f_), _leaf_cells(tdata_, f_)) for f_ in flats_]
                    _log(out, f"  {sel_[-45:]}: {cells_}")
                    if step.get("drawn"):
                        reader_ = server.context.active_data_source.reader_of(sel_)
                        rdata_ = reader_.GetClientSideObject().GetOutputDataObject(0)
                        own_ = _datasets_of(rdata_, sel_)
                        seen_ = _datasets_of(sdata_, sel_)
                        _log(out, f"    its reader's: {own_}; the view's: {seen_}")
                        if not own_ or not any(d_[2] for d_ in own_):
                            raise RuntimeError(f"scene_blocks_probe: the reader holds no cells for {sel_[-45:]}")
                        if seen_ != own_:
                            raise RuntimeError(f"scene_blocks_probe: the row {sel_[-45:]} points at {seen_},"
                                               f" its reader delivered {own_}")
                if step.get("drawn") and not shown_:
                    raise RuntimeError("scene_blocks_probe: the view shows no block")
                # "no_kinds": [...] — no row of these kinds is a block the view
                # shows: a wellbore or one of its folders shown would draw
                # everything under it, whatever the eyes of its rows say
                kinds_ = {s_: (tree.find_type(tree.find_node_id(s_)) or "") for s_ in shown_}
                wrong_ = sorted(s_[-40:] + " (" + k_ + ")" for s_, k_ in kinds_.items() if k_ in (step.get("no_kinds") or ()))
                if wrong_:
                    raise RuntimeError(f"scene_blocks_probe: shown as blocks: {wrong_}")
                # "count": n — the view shows that many blocks, no more
                if "count" in step and len(shown_) != int(step["count"]):
                    raise RuntimeError(f"scene_blocks_probe: {len(shown_)} block(s) shown, {step['count']} expected:"
                                       f" {[s_[-40:] for s_ in shown_]}")
                try:
                    rep_sel_ = list(scene_.main_rep.BlockSelectors) if scene_ is not None and scene_.main_rep is not None else []
                    _log(out, f"  main rep selectors: {len(rep_sel_)} {[s_[-30:] for s_ in rep_sel_][:4]},"
                              f" visible={int(scene_.main_rep.Visibility) if scene_ is not None and scene_.main_rep is not None else '-'},"
                              f" input is {'the cut' if tips_ and scene_.main_rep.Input is tips_[0] else 'the source'}")
                except Exception as exc_:
                    _log(out, f"  main rep: {exc_}")

            elif op == "isolate_cut_probe":
                # The isolates of the view: each one's mode, what it draws,
                # the scene cuts on its displays (engine/sources/ijkgrid
                # .set_scene_cut) and the cells and z range of each
                # (`isolate_probe` above says the chain).
                # {"op":"isolate_cut_probe"}
                vid_ = _render_vid(server, state)
                isos_ = {k_: v_ for k_, v_ in (getattr(server.context, "grid_isolates", None) or {}).items()
                         if k_[0] == vid_}
                _log(out, f"isolates ({vid_}): {len(isos_)}")

                def _zspan(proxy_):
                    try:
                        proxy_.UpdatePipeline()
                        d_ = proxy_.GetClientSideObject().GetOutputDataObject(0)
                        b_ = d_.GetBounds()
                        return f"{d_.GetClassName()} {d_.GetNumberOfCells()} cells, z {b_[4]:.1f}..{b_[5]:.1f}"
                    except Exception as exc_:
                        return f"unreadable ({exc_})"

                for (_v, rp_), iso_ in isos_.items():
                    crops_ = getattr(iso_, "_scene_crops", None) or {}
                    _log(out, f"  {rp_[-50:]}: mode={iso_._range_mode} volumes={len(iso_._src_volumes)}"
                              f" chain={len(iso_._chain)} scene cuts={len(crops_)}")
                    for src_ in list(iso_._src_volumes) + [s_ for s_ in [iso_._render_root()] if s_ is not None]:
                        _log(out, f"    source {src_.GetXMLName()}: {_zspan(src_)}")
                    for base_, crop_ in crops_.values():
                        for tip_ in crop_.tips():
                            _log(out, f"    scene cut of {base_.GetXMLName()}: {_zspan(tip_)}")
                        # stage by stage: the cells prepared, their extents,
                        # the cells the boxes meet
                        try:
                            from fespp_on_trame.engine.blockscope import scene_crop as _sc
                            bd_ = base_.GetClientSideObject().GetOutputDataObject(0)
                            pd_ = crop_._stages[0].GetClientSideObject().GetOutputDataObject(0)
                            cb_ = pd_.GetFieldData().GetArray(_sc.CELLBOX)
                            keep_ = _sc.mask_of(pd_, crop_._boxes)
                            arrs_ = [bd_.GetCellData().GetArrayName(i) for i in range(bd_.GetCellData().GetNumberOfArrays())]
                            _log(out, f"      base {bd_.GetClassName()} {bd_.GetNumberOfCells()}c {bd_.GetNumberOfPoints()}p"
                                      f" arrays {arrs_}; prep {pd_.GetClassName()} {pd_.GetNumberOfCells()}c,"
                                      f" extents {cb_.GetNumberOfTuples() if cb_ else None};"
                                      f" marked {int(keep_.sum()) if keep_ is not None else None}; boxes {crop_._boxes}")
                            if cb_ is not None and pd_.GetNumberOfCells():
                                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                                v_ = _v2n(cb_).reshape(6, -1)
                                _log(out, f"      extents span x {v_[0].min():.1f}..{v_[1].max():.1f}"
                                          f" y {v_[2].min():.1f}..{v_[3].max():.1f} z {v_[4].min():.1f}..{v_[5].max():.1f}")
                        except Exception as exc_:
                            _log(out, f"      stages: {exc_!r}")

            elif op == "scene_cut_faces_check":
                # The IJK grid's exposed faces (scene_crop._exposed_faces)
                # against a hash of every face of its kept cells, on the
                # cut's own prepared grid. {"op":"scene_cut_faces_check"}
                import numpy as _np
                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                from fespp_on_trame.engine.blockscope import scene_crop as _sc
                vid_ = _render_vid(server, state)
                crop_ = getattr((getattr(server.context, "blockscope_scenes", None) or {}).get(vid_), "crop", None)
                if crop_ is None or not crop_._stages:
                    raise RuntimeError("scene_cut_faces_check: the scene is not cut")
                prep_ = crop_._stages[0].GetClientSideObject().GetOutputDataObject(0)
                grids_ = [ds_ for _it, ds_ in _sc._leaves(prep_) if ds_.GetFieldData().GetArray(_sc.FACE_META) is not None]
                if not grids_:
                    raise RuntimeError("scene_cut_faces_check: no grid with a face table")
                g_ = max(grids_, key=lambda d: d.GetNumberOfCells())
                meta_ = _v2n(g_.GetFieldData().GetArray(_sc.FACE_META)).tolist()
                match_ = _v2n(g_.GetFieldData().GetArray(_sc.FACE_MATCH))
                lone_ = _v2n(g_.GetFieldData().GetArray(_sc.FACE_LONE))
                import time as _time
                t0_ = _time.perf_counter()
                keep_ = _sc.mask_of(g_, crop_._boxes)
                t1_ = _time.perf_counter()
                quads_, owners_ = _sc._exposed_faces(g_, keep_)
                t2_ = _time.perf_counter()
                poly_ = _sc._faces_polydata(g_, quads_, owners_)
                t3_ = _time.perf_counter()
                _log(out, f"faces check: mask {(t1_ - t0_) * 1000:.0f} ms, exposed faces {(t2_ - t1_) * 1000:.0f} ms,"
                          f" polydata {(t3_ - t2_) * 1000:.0f} ms ({poly_.GetNumberOfPoints()} points,"
                          f" {poly_.GetCellData().GetNumberOfArrays()} cell arrays, {poly_.GetPointData().GetNumberOfArrays()} point arrays)")
                n_ = g_.GetNumberOfCells()
                conn_ = _v2n(g_.GetCells().GetConnectivityArray()).reshape(n_, 8)
                kept_cells = _np.flatnonzero(keep_)
                allf_ = _np.sort(conn_[kept_cells][:, _np.array(_sc._HEX_FACES)].reshape(-1, 4), axis=1)
                _u, counts_ = _np.unique(allf_, axis=0, return_counts=True)
                got_ = _np.sort(quads_, axis=1)
                gu_ = _np.unique(got_, axis=0)
                _log(out, f"faces check: grid {n_} cells, meta {meta_}, matched pairs {int(match_.sum())} of {len(match_)},"
                          f" lone faces {len(lone_) // 2}; kept {len(kept_cells)} cells; exposed faces {len(quads_)}"
                          f" ({len(gu_)} distinct), hash says {int((counts_ == 1).sum())}; owners kept: {bool(keep_[owners_].all()) if len(owners_) else True}")
                # where the kept cells are, against the boxes: a cut "=" keeps
                # the cells the plane crosses, "≤" everything below it
                cb_ = _v2n(g_.GetFieldData().GetArray(_sc.CELLBOX)).reshape(6, n_)
                if len(kept_cells):
                    span_ = [f"{ax}: {cb_[2 * k][kept_cells].min():.1f}..{cb_[2 * k + 1][kept_cells].max():.1f}"
                             for k, ax in enumerate("xyz")]
                else:
                    span_ = ["nothing kept"]
                _log(out, f"  kept cells span {'; '.join(span_)}; boxes {crop_._boxes}")

            elif op == "scene_crop_probe":
                # The cut of the whole scene (the Geometry slicer on the
                # scene, engine/blockscope/scene_crop, 29/10): its pieces, the
                # composite reps drawing them, the cells kept in the blocks
                # the view draws, the blocks' assembly carried through, and a
                # polyline (a well) cut rather than kept whole.
                # {"op":"scene_crop_probe","pieces":1,"fewer":true,"wells_cut":true}
                # {"op":"scene_crop_probe","pieces":0}
                import time as _time
                cvid = _render_vid(server, state)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(cvid)
                if scene_ is None:
                    raise RuntimeError("scene_crop_probe: no scene in the view")
                crop_ = getattr(scene_, "crop", None)
                tips_ = crop_.tips() if crop_ is not None else []
                main_in = scene_.main_rep.Input if scene_.main_rep is not None else None
                _log(out, f"scene cut ({cvid}): {len(tips_)} piece(s), {len(scene_._extras)} extra rep(s),"
                          f" main rep on {'a piece' if tips_ and main_in is tips_[0] else 'the source'}")
                if "pieces" in step and len(tips_) != int(step["pieces"]):
                    raise RuntimeError(f"scene_crop_probe: {len(tips_)} pieces, not {step['pieces']}")
                if tips_ and main_in is not tips_[0]:
                    raise RuntimeError("scene_crop_probe: the view's composite rep is not on the first piece")
                if len(scene_._extras) != max(0, len(tips_) - 1):
                    raise RuntimeError(f"scene_crop_probe: {len(scene_._extras)} extra reps for {len(tips_)} pieces")
                if not tips_ and main_in is not server.context.active_data_source.get_display_source():
                    raise RuntimeError("scene_crop_probe: an uncut scene is not drawn from the source")
                if tips_:
                    flats_ = set()
                    for sel_ in scene_.shown_selectors() - set(scene_.isolated):
                        flats_.update(server.context.assembly_index.flat_indices(sel_))

                    def _leaves(proxy):
                        d = proxy.GetClientSideObject().GetOutputDataObject(0)
                        it = d.NewIterator()
                        it.SetVisitOnlyLeaves(True)
                        it.SetSkipEmptyNodes(True)
                        it.InitTraversal()
                        got = {}
                        while not it.IsDoneWithTraversal():
                            got[it.GetCurrentFlatIndex()] = it.GetCurrentDataObject()
                            it.GoToNextItem()
                        return d, got

                    src_ = server.context.active_data_source.get_display_source()
                    src_.UpdatePipeline()
                    sd_, sleaves = _leaves(src_)
                    whole_ = sum(ds.GetNumberOfCells() for f, ds in sleaves.items() if f in flats_)
                    t0_ = _time.perf_counter()
                    for tip_ in tips_:
                        tip_.UpdatePipeline()
                    dt_ = _time.perf_counter() - t0_
                    kept_, cut_lines, lines_seen, per_piece = 0, 0, [], []
                    for tip_ in tips_:
                        piece_kept = 0
                        td_, tleaves = _leaves(tip_)
                        # the blocks the view draws, extracted: the assembly
                        # keeps the source's paths (its root name)
                        if td_.GetDataAssembly() is None or (sd_.GetDataAssembly() is not None and
                                td_.GetDataAssembly().GetRootNodeName()
                                != sd_.GetDataAssembly().GetRootNodeName()):
                            raise RuntimeError("scene_crop_probe: the cut lost the blocks' paths")
                        for f_tip, ds in tleaves.items():
                            f = crop_.source_flat(f_tip, server.context.assembly_index)
                            if f not in flats_:
                                continue
                            orig_ = ds.GetCellData().GetArray("vtkOriginalCellIds")
                            if orig_ is None and ds.GetNumberOfCells():
                                raise RuntimeError(f"scene_crop_probe: block {f} lost its source cell ids")
                            src_ds = sleaves.get(f)
                            # an IJK grid drawn as its exposed faces: the
                            # cells they belong to
                            if (orig_ is not None and ds.IsA("vtkPolyData") and src_ds is not None
                                    and not src_ds.IsA("vtkPolyData")):
                                from vtkmodules.util.numpy_support import vtk_to_numpy as _v2n
                                import numpy as _np
                                n_kept = int(_np.unique(_v2n(orig_)).size)
                            else:
                                n_kept = ds.GetNumberOfCells()
                            kept_ += n_kept
                            piece_kept += n_kept
                            # a polyline of the source cut: fewer points kept
                            # than it has, a cell or more kept
                            if (src_ds is not None and src_ds.GetNumberOfCells()
                                    and src_ds.GetCellType(0) in (4, 3)):  # VTK_POLY_LINE, VTK_LINE
                                if 0 < ds.GetNumberOfPoints() < src_ds.GetNumberOfPoints():
                                    cut_lines += 1
                                if step.get("wells_cut") and len(lines_seen) < 12:
                                    b_ = src_ds.GetBounds()
                                    lines_seen.append(f"{f}: {ds.GetNumberOfPoints()}/{src_ds.GetNumberOfPoints()}"
                                                      f" pts, x {b_[0]:.0f}..{b_[1]:.0f}")
                        per_piece.append(piece_kept)
                    # a plane splits the cells it crosses: a piece may count
                    # a few more cells than it keeps of the source's
                    _log(out, f"scene cut cells: {per_piece} kept per piece, of {whole_} drawn"
                              f" ({dt_ * 1000:.0f} ms to update the pieces), {cut_lines} polyline block(s) cut")
                    if lines_seen:
                        _log(out, "  polylines (kept/source points): " + "; ".join(lines_seen))
                        # the source's polylines: what they are, how many
                        n_src = sum(1 for f, ds in sleaves.items() if f in flats_ and ds.GetNumberOfCells()
                                    and ds.GetCellType(0) in (4, 3))
                        _log(out, f"  {n_src} polyline block(s) drawn in the source")
                    if step.get("fewer") and not all(0 < k < whole_ for k in per_piece):
                        raise RuntimeError(f"scene_crop_probe: {per_piece} cells kept of {whole_}")
                    if step.get("wells_cut") and not cut_lines:
                        raise RuntimeError("scene_crop_probe: no polyline cut through")

            elif op == "xyz_crop_bench":
                # The ParaView ways to keep the cells of an X/Y/Z box, timed on
                # the REAL loaded blocks (the biggest volume, the biggest
                # surface), Update() inside the stopwatch — what the Geometry
                # slicer in X/Y/Z can be built on (29/10). The box keeps the
                # middle half of the block in X, all of it in Y and Z; the
                # slice is the plane through the middle of X.
                # {"op":"xyz_crop_bench","repeat":3}
                import numpy as _np
                from vtkmodules.util.numpy_support import numpy_to_vtk
                from vtkmodules.vtkCommonDataModel import vtkBox, vtkPlane, vtkDataObject
                from vtkmodules.vtkFiltersCore import vtkThreshold, vtkCutter
                from vtkmodules.vtkFiltersGeneral import vtkTableBasedClipDataSet
                from vtkmodules.vtkFiltersExtraction import vtkExtractGeometry
                src = server.context.collector.get_source()
                pdc = src.GetClientSideObject().GetOutputDataObject(0)
                it = pdc.NewIterator()
                it.SetVisitOnlyLeaves(True)
                it.InitTraversal()
                volume, surface = None, None
                while not it.IsDoneWithTraversal():
                    ds = it.GetCurrentDataObject()
                    n = ds.GetNumberOfCells() if ds is not None else 0
                    if n:
                        slot = "surface" if ds.IsA("vtkPolyData") else "volume"
                        cur = surface if slot == "surface" else volume
                        if cur is None or n > cur.GetNumberOfCells():
                            if slot == "surface":
                                surface = ds
                            else:
                                volume = ds
                    it.GoToNextItem()
                reps = int(step.get("repeat", 3))

                def _best(make):
                    best, kept = None, 0
                    for _ in range(reps):
                        f = make()
                        t0 = time.perf_counter()
                        f.Update()
                        dt = time.perf_counter() - t0
                        best = dt if best is None else min(best, dt)
                        kept = f.GetOutput().GetNumberOfCells()
                    return best, kept

                for name, ds in (("volume", volume), ("surface", surface)):
                    if ds is None:
                        _log(out, f"xyz crop bench: no {name} block loaded")
                        continue
                    b = ds.GetBounds()
                    w = b[1] - b[0]
                    lo, hi = b[0] + 0.25 * w, b[0] + 0.75 * w
                    pad = 1.0 + 0.01 * max(abs(v) for v in b)
                    box = vtkBox()
                    box.SetBounds(lo, hi, b[2] - pad, b[3] + pad, b[4] - pad, b[5] + pad)
                    plane = vtkPlane()
                    plane.SetOrigin((lo + hi) / 2.0, 0.0, 0.0)
                    plane.SetNormal(1.0, 0.0, 0.0)
                    res = {}

                    def clip_exact():
                        f = vtkTableBasedClipDataSet()
                        f.SetInputData(ds)
                        f.SetClipFunction(box)
                        f.InsideOutOn()
                        return f
                    res["Clip box (exact)"] = _best(clip_exact)

                    def crinkle():
                        # ParaView's "Crinkle clip": whole cells inside or crossing
                        f = vtkExtractGeometry()
                        f.SetInputData(ds)
                        f.SetImplicitFunction(box)
                        f.ExtractInsideOn()
                        f.ExtractBoundaryCellsOn()
                        return f
                    res["Crinkle clip box (whole cells)"] = _best(crinkle)

                    def by_region():
                        # "Extract Cells By Region", cells wholly inside
                        f = vtkExtractGeometry()
                        f.SetInputData(ds)
                        f.SetImplicitFunction(box)
                        f.ExtractInsideOn()
                        f.ExtractBoundaryCellsOff()
                        return f
                    res["Extract Cells By Region (inside)"] = _best(by_region)

                    # a threshold on the X of the points (the property
                    # slicer's chain on a coordinate array): the array made
                    # once, timed apart
                    from vtkmodules.util.numpy_support import vtk_to_numpy
                    t0 = time.perf_counter()
                    xs = _np.ascontiguousarray(vtk_to_numpy(ds.GetPoints().GetData())[:, 0])
                    arr = numpy_to_vtk(xs, deep=1)
                    arr.SetName("__x")
                    copy = ds.NewInstance()
                    copy.ShallowCopy(ds)
                    copy.GetPointData().AddArray(arr)
                    made = time.perf_counter() - t0

                    def thresh():
                        f = vtkThreshold()
                        f.SetInputData(copy)
                        f.SetInputArrayToProcess(0, 0, 0, vtkDataObject.FIELD_ASSOCIATION_POINTS, "__x")
                        f.SetLowerThreshold(lo)
                        f.SetUpperThreshold(hi)
                        f.SetThresholdFunction(vtkThreshold.THRESHOLD_BETWEEN)
                        f.AllScalarsOn()
                        return f
                    res["Threshold on X (all points)"] = _best(thresh)

                    def cut():
                        f = vtkCutter()
                        f.SetInputData(ds)
                        f.SetCutFunction(plane)
                        return f
                    res["Slice plane X (cross-section)"] = _best(cut)

                    def band():
                        # the cells the plane crosses: a "slice" of cells
                        f = vtkExtractGeometry()
                        f.SetInputData(ds)
                        f.SetImplicitFunction(plane)
                        f.ExtractInsideOff()
                        f.ExtractOnlyBoundaryCellsOn()
                        f.ExtractBoundaryCellsOn()
                        return f
                    res["Cells crossed by plane X"] = _best(band)

                    def continuous(a, b_):
                        # a cell kept when its extent in X meets [a, b_]:
                        # Threshold's "Use Continuous Cell Range"
                        def make():
                            f = vtkThreshold()
                            f.SetInputData(copy)
                            f.SetInputArrayToProcess(0, 0, 0, vtkDataObject.FIELD_ASSOCIATION_POINTS, "__x")
                            f.SetLowerThreshold(a)
                            f.SetUpperThreshold(b_)
                            f.SetThresholdFunction(vtkThreshold.THRESHOLD_BETWEEN)
                            # AllScalars (on by default) wins over the
                            # continuous range: off
                            f.AllScalarsOff()
                            f.UseContinuousCellRangeOn()
                            return f
                        return make
                    res["Threshold X, continuous cell range"] = _best(continuous(lo, hi))
                    mid = (lo + hi) / 2.0
                    res["Threshold X continuous, cut X = middle"] = _best(continuous(mid, mid))
                    # a range thinner than a cell: what a box keeps then
                    thin = w / 4000.0
                    tbox = vtkBox()
                    tbox.SetBounds(mid - thin, mid + thin, b[2] - pad, b[3] + pad, b[4] - pad, b[5] + pad)

                    def thin_crinkle():
                        f = vtkExtractGeometry()
                        f.SetInputData(ds)
                        f.SetImplicitFunction(tbox)
                        f.ExtractInsideOn()
                        f.ExtractBoundaryCellsOn()
                        return f
                    res[f"THIN range ({2 * thin:.1f}): crinkle box"] = _best(thin_crinkle)
                    res[f"THIN range ({2 * thin:.1f}): threshold continuous"] = _best(
                        continuous(mid - thin, mid + thin))
                    _log(out, f"xyz crop bench — {name} {ds.GetClassName()} of"
                              f" {ds.GetNumberOfCells()} cells, {ds.GetNumberOfPoints()} points"
                              f" (X array made in {made * 1000:.0f} ms):")
                    for k, (dt, kept) in res.items():
                        _log(out, f"    {k}: {dt * 1000:.0f} ms, {kept} cells kept")

            elif op == "profile_call":
                # WHERE the time of a controller call goes, by function —
                # cProfile around the call, the top entries by cumulative time
                # written to the log. A stopwatch says what a gesture costs;
                # this says where that time goes. {"op":"profile_call",
                #  "method":"threshold_add","args":[["Fluids",null],"view_1"],
                #  "top":30,"settle":5}
                import cProfile
                import pstats
                import io
                # either a controller call, or a STATE WRITE whose @state.change
                # listener is what we want to see (the crosshair's pos_ev)
                writes = dict(step.get("set") or {})
                if writes:
                    meth, args = None, []
                else:
                    meth = getattr(controller, step["method"])
                    # resolved as a plain call's: an unresolved
                    # {"chain_entry": 0} made the profiled call a silent
                    # no-op, timed as if it had worked (27/10)
                    args = _resolve_args(tree, step.get("args", []), state)
                pr = cProfile.Profile()
                t0 = time.monotonic()
                pr.enable()
                with state:
                    if writes:
                        for k, v in writes.items():
                            state[k] = v
                    else:
                        meth(*args)
                pr.disable()
                took = (time.monotonic() - t0) * 1000.0
                buf = io.StringIO()
                st = pstats.Stats(pr, stream=buf)
                st.sort_stats("cumulative").print_stats(int(step.get("top", 30)))
                lines = [ln.rstrip() for ln in buf.getvalue().splitlines()
                         if ln.strip() and not ln.strip().startswith(("Ordered", "ncalls"))
                         and "function calls" not in ln]
                _log(out, f"profile {step.get('method') or ('set ' + ','.join(writes))}({args!r}): {took:.0f} ms wall")
                for ln in lines:
                    _log(out, "    " + ln)
                await asyncio.sleep(float(step.get("settle", 2)))

            elif op == "etp_open":
                # A dataspace of a live ETP server opened as the Import door
                # opens it, with the token the harness forwards (OSDU_TOKEN,
                # never written anywhere). Without a token the scenario stops
                # here and passes: the full suite runs without a server.
                # {"op":"etp_open","url":"wss://…/","partition":"opendes",
                #  "dataspace":"eml:///dataspace('brian/volve_velocity')","settle":30}
                import os as _os
                tok = _os.environ.get("OSDU_TOKEN", "")
                if not tok:
                    _log(out, "etp_open: no OSDU_TOKEN — the steps after it are not run")
                    break
                r = controller.etp_connect({"url": step["url"], "partition": step.get("partition", ""),
                                            "token": tok, "auth": "Bearer"})
                if asyncio.iscoroutine(r):
                    await r
                await asyncio.sleep(1)
                r = controller.etp_select({"dataspace": step["dataspace"]})
                if asyncio.iscoroutine(r):
                    await r
                await asyncio.sleep(float(step.get("settle", 20)))
                _log(out, f"etp_open: {step['dataspace']}"
                          f" connected={bool(getattr(state, 'etp_connected', False))}")

            elif op == "etp_profile":
                # Where a dataspace's load goes, function by function, on a
                # live ETP server: connect with the token the harness
                # forwards (OSDU_TOKEN, never written anywhere), then cProfile
                # around the Load (etp_select), the top entries by cumulative
                # and by own time. {"op":"etp_profile","url":"wss://…/",
                #  "partition":"opendes","dataspace":"eml:///dataspace('demo/Volve')",
                #  "top":60}
                import cProfile
                import pstats
                import io
                import os as _os
                tok = _os.environ.get("OSDU_TOKEN", "")
                if not tok:
                    raise RuntimeError("etp_profile: no OSDU_TOKEN in the environment")
                t0 = time.monotonic()
                r = controller.etp_connect({"url": step["url"], "partition": step.get("partition", ""),
                                            "token": tok, "auth": "Bearer"})
                if asyncio.iscoroutine(r):
                    await r
                _log(out, f"etp_profile: connected={bool(getattr(state, 'etp_connected', False))}"
                          f" in {time.monotonic() - t0:.1f} s")
                await asyncio.sleep(float(step.get("before", 1)))
                pr = cProfile.Profile()
                t0 = time.monotonic()
                pr.enable()
                r = controller.etp_select({"dataspace": step["dataspace"]})
                if asyncio.iscoroutine(r):
                    await r
                pr.disable()
                _log(out, f"etp_profile: {step['dataspace']} in {time.monotonic() - t0:.1f} s wall")
                for key in ("cumulative", "tottime"):
                    buf = io.StringIO()
                    pstats.Stats(pr, stream=buf).sort_stats(key).print_stats(int(step.get("top", 50)))
                    _log(out, f"  --- by {key}")
                    for ln in buf.getvalue().splitlines():
                        if ln.strip() and not ln.strip().startswith(("Ordered", "ncalls")) \
                                and "function calls" not in ln:
                            _log(out, "    " + ln.rstrip())
                await asyncio.sleep(float(step.get("settle", 2)))

            elif op == "time_until":
                # How long a gesture takes to land, as the reader waits for it:
                # the controller called, the read's question answered yes when
                # it asks, then the state polled until a key starting with
                # `prefix` holds a dict whose `key` is not empty — for a log
                # view's payload (`curves_ge`), until its wells draw that many
                # curves; the wall time logged.
                # {"op":"time_until","method":"add_to_welllog",
                #  "args":[{"title":"Well Log Frame","under":"55/33-A-4"}],
                #  "prefix":"welllog_data__","key":"wells","curves_ge":25,"timeout":300,
                #  "asks":true}   (`asks`: whether the read must ask first)
                meth_ = getattr(controller, step["method"])
                t0_ = time.monotonic()
                with state:
                    meth_(*_resolve_args(tree, step.get("args", []), state))
                prefix_, key_ = step["prefix"], step.get("key", "")
                asked_, landed_ = None, None
                while time.monotonic() - t0_ < float(step.get("timeout", 300)):
                    await asyncio.sleep(0.2)
                    if asked_ is None and (getattr(state, "ui_tick_confirm", None) or {}).get("title"):
                        asked_ = time.monotonic() - t0_
                        with state:
                            controller.tick_confirm_answer(True)
                    every_ = state.to_dict() if hasattr(state, "to_dict") else {}
                    hits_ = [v for k, v in every_.items()
                             if k.startswith(prefix_) and isinstance(v, dict) and (not key_ or v.get(key_))]
                    if "curves_ge" in step:
                        hits_ = [v for v in hits_ if sum(len(t.get("curves") or ()) for w in v.get("wells") or ()
                                                         for t in w.get("tracks") or ()) >= int(step["curves_ge"])]
                    if hits_:
                        landed_ = time.monotonic() - t0_
                        break
                _log(out, f"time until [{step.get('label', step['method'])}]: "
                          + (f"landed in {landed_:.1f} s" if landed_ is not None else "never landed")
                          + (f" (asked first, at {asked_:.1f} s)" if asked_ is not None else " (no question)"))
                if "asks" in step and bool(step["asks"]) != (asked_ is not None):
                    raise RuntimeError(f"time_until: the read {'asked' if asked_ is not None else 'did not ask'}"
                                       f" first, expected {'a question' if step['asks'] else 'none'}")
                if landed_ is None:
                    raise RuntimeError("time_until: never landed")

            elif op == "timed_call":
                # Call a controller and say how long it took, WITHOUT putting
                # a stopwatch in the product. Paired with `vtk_backend`, this
                # times the same operation on one thread and on all of them
                # inside a single process, on the same data — the only way to say
                # what the SMP backend is worth here rather than on a
                # synthetic benchmark.
                # {"op":"timed_call","method":"volumetrics_refresh",
                #  "args":["view_1"],"repeat":3,"settle":4}
                from vtkmodules.vtkCommonCore import vtkSMPTools
                meth = getattr(controller, step["method"])
                args = list(step.get("args") or [])
                reps = int(step.get("repeat", 1))
                took = []
                for _ in range(reps):
                    t0 = time.monotonic()
                    with state:
                        meth(*args)
                    await asyncio.sleep(float(step.get("settle", 2)))
                    took.append(time.monotonic() - t0
                                - float(step.get("settle", 2)))
                best = min(took) * 1000.0
                _log(out, f"timed {step['method']}({args!r}):"
                          f" best={best:.0f} ms of {reps}"
                          f" all={[round(t * 1000) for t in took]}"
                          f" — VTK {vtkSMPTools.GetBackend()}"
                          f"/{vtkSMPTools.GetEstimatedNumberOfThreads()}")

            elif op == "vtk_backend":
                # Flip VTK's SMP backend mid-scenario, so the SAME gesture is
                # timed on one thread and on many WITHOUT changing process,
                # data or camera — the only honest way to compare the two.
                # {"op":"vtk_backend","backend":"Sequential"}
                from vtkmodules.vtkCommonCore import vtkSMPTools
                want = str(step.get("backend", "STDThread"))
                vtkSMPTools.SetBackend(want)
                got = vtkSMPTools.GetBackend()
                _log(out, f"VTK backend: asked {want!r} — now {got!r},"
                          f" {vtkSMPTools.GetEstimatedNumberOfThreads()} thread(s)")
                if got != want:
                    raise RuntimeError(
                        f"vtk_backend: asked {want!r}, the build gave {got!r}")

            elif op == "threshold_colour_probe":
                # What the VISIBLE displays of the view are coloured by.
                # With a threshold chain active the isolate does not show its
                # base sources at all: `_show_source_or_chain` hides them and
                # shows the chain's TIP proxies instead. So the only honest
                # question is what the SHOWN representations name, not what
                # the isolate believes.
                # {"op":"threshold_colour_probe","expect":"Temperature"}
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                if pvv is None:
                    raise RuntimeError("threshold_colour_probe: no render view")
                shown = []
                for rep in (pvv.Representations or []):
                    vis = rep.GetProperty("Visibility")
                    inp = rep.GetProperty("Input")
                    if vis is None or inp is None or not int(vis.GetElement(0)):
                        continue
                    src = inp.GetProxy(0)
                    nm = src.GetXMLLabel() if src is not None else "?"
                    ca = rep.GetProperty("ColorArrayName")
                    arr = ca.GetElement(4) if ca is not None and ca.GetNumberOfElements() > 4 else ""
                    shown.append((nm, arr))
                iso = None
                for (ivid, ipath), o2 in list(
                        (getattr(server.context, "grid_isolates", None) or {}).items()):
                    if ivid == vid:
                        iso = o2
                        break
                _log(out, f"threshold colours ({vid}): isolate_title="
                          f"{getattr(iso, '_title', None)!r} shown="
                          + " | ".join(f"{n}:{a or '-'}" for n, a in shown))
                if step.get("expect_tool"):
                    # The card must also be OFFERED. A chain that works while
                    # the toolbar hides its button is not a feature: the tool
                    # must not be gated on "this view has an IJK grid", or the
                    # non-IJK case is unreachable.
                    tools = list(getattr(state, f"view_tools_{vid}", None) or [])
                    keys = [t.get("key") for t in tools if isinstance(t, dict)]
                    _log(out, f"tools offered ({vid}): {keys}")
                    if "thresholds" not in keys:
                        raise RuntimeError(
                            "threshold_colour_probe: the Thresholds card is"
                            f" NOT offered in this view — tools are {keys}")
                want = step.get("expect")
                if want:
                    thr = [a for n, a in shown if "hreshold" in n]
                    if not thr:
                        raise RuntimeError(
                            "threshold_colour_probe: no Threshold proxy is"
                            " VISIBLE — the chain is not on screen, so this"
                            " probe would prove nothing")
                    if not all(a == want for a in thr):
                        raise RuntimeError(
                            f"threshold_colour_probe: the visible Threshold"
                            f" proxies are coloured by {thr!r}, not {want!r}"
                            f" — changing the property eye did not reach the"
                            " thresholded display")

            elif op == "camera_move":
                # MOVE THE CAMERA THE WAY A HAND DOES — through the
                # interactor, so the interactor style, its observers and
                # everything hanging off them are on the path. `drag` is a
                # left-button drag from the centre (a rotate), `wheel` is a
                # count of notches, positive inwards. A `back` wheel of the
                # same count comes back out, so the framing is where it
                # started and a pixel count before and after can be compared.
                # {"op":"camera_move","drag":[60,40],"wheel":5,"back":5}
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                if pvv is None:
                    raise RuntimeError("camera_move: no render view")
                iren = pvv.GetClientSideObject().GetInteractor()
                if iren is None:
                    raise RuntimeError("camera_move: the view has no interactor")
                w, h = [int(x) for x in pvv.ViewSize]
                cam = pvv.GetActiveCamera()
                before = list(cam.GetPosition())
                drag = step.get("drag")
                if drag:
                    dx, dy = int(drag[0]), int(drag[1])
                    iren.SetEventPosition(int(w / 2), int(h / 2))
                    iren.LeftButtonPressEvent()
                    for k in range(1, 6):
                        iren.SetEventPosition(int(w / 2) + dx * k // 5,
                                              int(h / 2) + dy * k // 5)
                        iren.MouseMoveEvent()
                    iren.LeftButtonReleaseEvent()
                for _ in range(int(step.get("wheel", 0))):
                    iren.MouseWheelForwardEvent()
                for _ in range(int(step.get("back", 0))):
                    iren.MouseWheelBackwardEvent()
                await asyncio.sleep(float(step.get("settle", 2)))
                after = list(cam.GetPosition())
                moved = sum((after[i] - before[i]) ** 2 for i in range(3)) ** 0.5
                _log(out, f"camera move ({vid}): drag={drag} wheel={step.get('wheel', 0)}"
                          f" back={step.get('back', 0)} eye_moved={moved:.1f}")
                if moved <= 0 and (drag or step.get("wheel")):
                    raise RuntimeError(
                        "camera_move: the camera did not move at all — the"
                        " gesture never reached the interactor style")

            elif op == "selection_probe":
                # A SELECTION SHOWS IN THE VIEW THAT MADE IT ONLY: each render
                # view's composite draws the shared source's selection
                # (SelectionVisibility) exactly when it is `shown_in`.
                # {"op":"selection_probe","shown_in":"view_1"}
                # "none": no source holds a selection at all (a log's samples
                # are lit by its graph or tube alone)
                if step.get("none"):
                    held_ = [n_ for (n_, _i), s_ in pvsimple.GetSources().items()
                             if s_.SMProxy.GetSelectionInput(0) is not None]
                    _log(out, f"selection probe: sources holding a selection: {held_}")
                    if held_:
                        raise RuntimeError(f"selection_probe: a selection is held by {held_}")
                want = str(step.get("shown_in") or "")
                ctx_ = server.context
                for vid_, scene_ in sorted((getattr(ctx_, "blockscope_scenes", None) or {}).items()
                                           if not step.get("none") else ()):
                    rep_ = getattr(scene_, "main_rep", None)
                    if rep_ is None:
                        continue
                    shown = bool(int(rep_.SelectionVisibility))
                    _log(out, f"selection probe: {vid_} draws the selection: {shown}")
                    if shown != (vid_ == want):
                        raise RuntimeError(
                            f"selection_probe: {vid_} " + ("draws another view's selection"
                                                           if shown else "hides its own selection"))

            elif op == "derived_filter_probe":
                # Q12 PROBE (slice 4a of the overhaul): ONE ProgrammableFilter
                # chained on the active source adds a computed array to a
                # grid's blocks — what every display would read if a derived
                # property became an array like any other. It measures the
                # filter's first run and its re-runs (a recipe changed), the
                # render of a display of it, and checks that its output keeps
                # the collection's numbering (a pick on it names the source's
                # cells), that an extract of it carries the array, and what a
                # time step costs when the data has steps.
                # {"op":"derived_filter_probe","grid":"Geogrid","prop":"Total Porosity"}
                import numpy as _np
                from fespp_on_trame.engine import node_facts as _nf
                from vtkmodules.vtkCommonCore import vtkCollection as _vtkColl
                ctx_ = server.context
                gnid = _find_node_by_title(tree, step["grid"])
                grep_ = tree.find_path(tree.find_representation_node(gnid)) if gnid is not None else ""
                pnid = _find_node_by_title(tree, step["prop"], step.get("under"))
                ppath = tree.find_path(pnid) if pnid is not None else ""
                if not grep_ or not ppath:
                    raise RuntimeError("derived_filter_probe: grid or property not found")
                aname = _nf.vtk_base_name(tree, ppath)
                src = ctx_.active_data_source.get_source()
                spdc = src.GetClientSideObject().GetOutputDataObject(0)
                sasm = spdc.GetDataAssembly()
                node = sasm.GetFirstNodeByPath(grep_)
                pds_idx = sorted(set(sasm.GetDataSetIndices(node, True))) if node is not None and node >= 0 else []
                ncells = 0
                found = None
                for i in pds_idx:
                    pds = spdc.GetPartitionedDataSet(i)
                    for j in range(pds.GetNumberOfPartitions()):
                        ds = pds.GetPartition(j)
                        if ds is None:
                            continue
                        ncells += ds.GetNumberOfCells()
                        cd = ds.GetCellData()
                        for k in range(cd.GetNumberOfArrays()):
                            n_ = cd.GetArrayName(k) or ""
                            if found is None and (n_ == aname or n_.startswith(aname + "_real_")):
                                found = n_
                if found is None:
                    raise RuntimeError(f"derived_filter_probe: no array {aname!r} on {step['grid']}")
                out_name = step.get("name", "derived__probe")
                script = (
                    "from vtkmodules.util.numpy_support import vtk_to_numpy, numpy_to_vtk\n"
                    "inp = self.GetInputDataObject(0, 0)\n"
                    "out = self.GetOutputDataObject(0)\n"
                    "out.ShallowCopy(inp)\n"
                    f"targets = set({pds_idx!r})\n"
                    "for i in range(out.GetNumberOfPartitionedDataSets()):\n"
                    "    if i not in targets:\n"
                    "        continue\n"
                    "    pds = out.GetPartitionedDataSet(i)\n"
                    "    for j in range(pds.GetNumberOfPartitions()):\n"
                    "        ds = pds.GetPartition(j)\n"
                    "        arr = ds.GetCellData().GetArray(%r) if ds is not None else None\n" % found
                    + "        if arr is None:\n"
                    "            continue\n"
                    "        cp = ds.NewInstance()\n"
                    "        cp.ShallowCopy(ds)\n"
                    "        a = vtk_to_numpy(arr).astype('float64')\n"
                    "        v = numpy_to_vtk(a * a, deep=1)\n"
                    "        v.SetName(%r)\n" % out_name
                    + "        cp.GetCellData().AddArray(v)\n"
                    "        pds.SetPartition(j, cp)\n")
                pvv_ = mv.get_pv_view(_render_vid(server, state))
                t0 = time.perf_counter()
                pf = pvsimple.ProgrammableFilter(registrationName="q12_probe", Input=src)
                pf.OutputDataSetType = "Same as Input"
                pf.Script = script
                pf.UpdatePipeline()
                t_first = time.perf_counter() - t0
                reruns = []
                for r_ in range(3):
                    pf.Script = script + f"# rerun {r_}\n"
                    t0 = time.perf_counter()
                    pf.UpdatePipeline()
                    reruns.append(time.perf_counter() - t0)
                fpdc = pf.GetClientSideObject().GetOutputDataObject(0)
                same_layout = (fpdc.GetNumberOfPartitionedDataSets() == spdc.GetNumberOfPartitionedDataSets()
                               and all(fpdc.GetPartitionedDataSet(i).GetNumberOfPartitions()
                                       == spdc.GetPartitionedDataSet(i).GetNumberOfPartitions()
                                       for i in range(spdc.GetNumberOfPartitionedDataSets())))
                carried = 0
                for i in pds_idx:
                    pds = fpdc.GetPartitionedDataSet(i)
                    for j in range(pds.GetNumberOfPartitions()):
                        ds = pds.GetPartition(j)
                        if ds is not None and ds.GetCellData().GetArray(out_name) is not None:
                            carried += 1
                # the source untouched
                src_clean = all(spdc.GetPartitionedDataSet(i).GetPartition(j) is None
                                or spdc.GetPartitionedDataSet(i).GetPartition(j).GetCellData().GetArray(out_name) is None
                                for i in pds_idx
                                for j in range(spdc.GetPartitionedDataSet(i).GetNumberOfPartitions()))
                disp = pvsimple.Show(pf, pvv_)
                disp.ColorArrayName = ["CELLS", out_name]
                disp.LookupTable = pvsimple.GetColorTransferFunction(out_name)
                renders = []
                for _r in range(3):
                    pvv_.StillRender()   # warm
                    t0 = time.perf_counter()
                    pvv_.SMProxy.StillRender()
                    renders.append(time.perf_counter() - t0)
                w_, h_ = [int(x) for x in pvv_.ViewSize]
                reps_, srcs_ = _vtkColl(), _vtkColl()
                ok_ = pvv_.SMProxy.SelectSurfaceCells([w_ // 2, h_ // 2, w_ // 2, h_ // 2],
                                                      reps_, srcs_, False, 0, False)
                ids_ = []
                if ok_:
                    for k in range(srcs_.GetNumberOfItems()):
                        prop_ = srcs_.GetItemAsObject(k).GetProperty("IDs")
                        if prop_ is not None:
                            ids_ += [int(prop_.GetElement(m)) for m in range(prop_.GetNumberOfElements())]
                grid_flats = set(ctx_.assembly_index.flat_indices(grep_))
                picked_flats = {ids_[m] for m in range(0, len(ids_) - 2, 3)}
                pick_ok = bool(picked_flats) and picked_flats <= grid_flats
                ex_cells, ex_has = 0, False
                if ids_:
                    sel_ = pvsimple.servermanager.sources.CompositeDataIDSelectionSource(
                        IDs=ids_, FieldType="CELL")
                    ex_ = pvsimple.ExtractSelection(Input=pf, Selection=sel_)
                    ex_.UpdatePipeline()
                    eo = ex_.GetClientSideObject().GetOutputDataObject(0)
                    it_ = eo.NewIterator()
                    it_.SetVisitOnlyLeaves(True)
                    it_.InitTraversal()
                    while not it_.IsDoneWithTraversal():
                        d_ = it_.GetCurrentDataObject()
                        ex_cells += d_.GetNumberOfCells()
                        ex_has = ex_has or d_.GetCellData().GetArray(out_name) is not None
                        it_.GoToNextItem()
                    pvsimple.Delete(ex_)
                steps_ = list(pvsimple.GetTimeKeeper().TimestepValues or [])
                t_step = None
                if len(steps_) > 1:
                    tk = pvsimple.GetTimeKeeper()
                    before_t = tk.Time
                    t0 = time.perf_counter()
                    tk.Time = steps_[1] if before_t != steps_[1] else steps_[0]
                    pf.UpdatePipeline(tk.Time)
                    t_step = time.perf_counter() - t0
                    tk.Time = before_t
                    pf.UpdatePipeline(before_t)
                pvsimple.Hide(pf, pvv_)
                pvsimple.Delete(pf)
                _log(out, f"q12 probe {step['grid']}/{step['prop']} ({found}): {len(pds_idx)} block(s),"
                          f" {ncells} cells")
                _log(out, f"q12 probe: filter first run {t_first * 1000:.0f} ms, re-runs "
                          f"{', '.join(f'{x * 1000:.0f}' for x in reruns)} ms")
                _log(out, f"q12 probe: render of its display {', '.join(f'{x * 1000:.0f}' for x in renders)} ms")
                _log(out, f"q12 probe: layout kept={same_layout}, blocks carrying the array={carried},"
                          f" source untouched={src_clean}")
                _log(out, f"q12 probe: pick on it -> flats {sorted(picked_flats)} within the grid's={pick_ok};"
                          f" extract of it: {ex_cells} cell(s), carries the array={ex_has}")
                _log(out, "q12 probe: time step " + (f"{t_step * 1000:.0f} ms" if t_step is not None
                                                     else "n/a (no steps)"))
                if not (same_layout and carried and src_clean):
                    raise RuntimeError("derived_filter_probe: the filter broke the collection")

            elif op == "eye_passes":
                # HOW MANY EYE PASSES a gesture costs (app/scene/eyes, W1): the
                # state watcher must not run a set the last pass left.
                # {"op":"eye_passes","reset":true} before the gesture, then
                # {"op":"eye_passes","expect":{"view_1":1}} after it
                eyes_ = getattr(server.context, "eyes", None)
                if eyes_ is None:
                    raise RuntimeError("eye_passes: the app has no eye service")
                if step.get("reset"):
                    eyes_.passes.clear()
                    eyes_.echoes.clear()
                    _log(out, "eye passes: counters reset")
                else:
                    _log(out, f"eye passes: {dict(eyes_.passes)}"
                              f" watcher echoes skipped: {dict(eyes_.echoes)}")
                    for v_, n_ in (step.get("expect") or {}).items():
                        if eyes_.passes.get(v_, 0) != int(n_):
                            raise RuntimeError(f"eye_passes: {v_} ran {eyes_.passes.get(v_, 0)}"
                                               f" pass(es) where {n_} was expected")

            elif op == "derived_eye":
                # The eye of a formula, found by its grid's title and its
                # name (app/scene/eyes: an eye like any property's), then
                # what the view's composite colours the grid by.
                # {"op":"derived_eye","grid":"Geogrid","name":"Fx2",
                #  "toggle":true, "expect_colour":true}
                # "toggle": false only checks; "expect_colour": true wants the
                # grid's block coloured by the formula's array, false not
                from fespp_on_trame.engine import derived_props
                from fespp_on_trame.engine.utils.naming import make_valid_vtk_name
                gid_ = _find_node_by_title(tree, step["grid"], step.get("under"))
                rid_ = tree.find_representation_node(gid_) if gid_ is not None else None
                rep_ = tree.find_path(rid_) if rid_ is not None else ""
                if not rep_:
                    raise RuntimeError(f"derived_eye: no grid {step['grid']!r}")
                vid_ = _render_vid(server, state)
                dpath_ = derived_props.path_for(rep_, step["name"])
                if step.get("toggle", True):
                    controller.session_row_eye({"path": dpath_}, vid_)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid_)
                entry_ = scene_.block_state.get(rep_) if scene_ is not None else None
                arr_ = entry_.color_array if entry_ is not None else ""
                open_ = dpath_ in (getattr(state, f"visible_paths__{vid_}", None) or [])
                _log(out, f"derived eye ({vid_}) {step['name']!r}: eye open={open_}"
                          f" block coloured by {arr_!r}")
                if "expect_colour" in step:
                    want_ = "derived__" + make_valid_vtk_name(step["name"])
                    if bool(step["expect_colour"]) != (open_ and arr_ == want_):
                        raise RuntimeError(f"derived_eye: expected the block coloured by"
                                           f" {want_!r}={step['expect_colour']}, got eye open={open_}"
                                           f" colour={arr_!r}")

            elif op == "occupancy_probe":
                # WHO DRAWS A GRID IN A VIEW (app/scene/occupancy; D7, N8):
                # the decision, and the view consistent with it — the
                # composite skips the block exactly when something else draws
                # it, the isolate's displays are visible exactly when it is
                # the one drawing.
                # {"op":"occupancy_probe","title":"Geogrid","expect":"composite"}
                occ_ = getattr(server.context, "occupancy", None)
                if occ_ is None:
                    raise RuntimeError("occupancy_probe: the app has no occupancy")
                nid_ = _find_node_by_title(tree, step["title"], step.get("under"))
                rid_ = tree.find_representation_node(nid_) if nid_ is not None else None
                rep_ = tree.find_path(rid_) if rid_ is not None else ""
                if not rep_:
                    raise RuntimeError(f"occupancy_probe: no representation for {step['title']!r}")
                ovid = str(step.get("view") or _render_vid(server, state))
                decision_ = occ_.decide(ovid, rep_)
                scene_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(ovid)
                iso_ = (getattr(server.context, "grid_isolates", None) or {}).get((ovid, rep_))
                pvv_ = mv.get_pv_view(ovid)
                shown_ = 0
                if iso_ is not None and pvv_ is not None:
                    for proxy_ in iso_.colourable_sources():
                        d_ = pvsimple.GetRepresentation(proxy=proxy_, view=pvv_)
                        if d_ is not None and int(d_.Visibility):
                            shown_ += 1
                isolated_ = bool(scene_ is not None and rep_ in scene_.isolated)
                _log(out, f"occupancy ({ovid}) {step['title']}: {decision_}, isolated={isolated_},"
                          f" isolate displays shown={shown_}")
                if step.get("expect") and decision_ != step["expect"]:
                    raise RuntimeError(f"occupancy_probe: {decision_}, {step['expect']} expected")
                if isolated_ != (decision_ != "composite"):
                    raise RuntimeError("occupancy_probe: the composite "
                                       + ("skips" if isolated_ else "draws")
                                       + f" the grid, decided {decision_}")
                if (shown_ > 0) != (decision_ == "isolate"):
                    raise RuntimeError(f"occupancy_probe: {shown_} isolate display(s) shown,"
                                       f" decided {decision_}")

            elif op == "time_depth_pins_probe":
                # WHAT THE TIME-DEPTH MODEL DRAWS ON ITS OWN in the 3D view
                # (app/features/time_depth_pins): the box of a model not
                # generated yet, its columns' lines, points and halo.
                # {"op":"time_depth_pins_probe","shown":["box","lines","points","halo"]}
                vid_ = _render_vid(server, state)
                pvv_ = mv.get_pv_view(vid_)
                shown_ = []
                for name_ in ("box", "lines", "points", "halo"):
                    src_ = pvsimple.FindSource(f"fesppTimeDepthPins_{name_}_{vid_}")
                    if src_ is not None and any(int(r_.Visibility) for r_ in (pvv_.Representations or [])
                                                if getattr(r_, "Input", None) == src_):
                        shown_.append(name_)
                # "bar": true / false — the colour bar of a model not generated
                # yet is, or is not, the one the view shows
                lut_ = pvsimple.GetColorTransferFunction("fesppVelocityPins")
                bar_ = any(r_.GetXMLName() == "ScalarBarWidgetRepresentation" and int(r_.Visibility)
                           and getattr(r_, "LookupTable", None) == lut_ for r_ in (pvv_.Representations or []))
                _log(out, f"time-depth pins ({vid_}): {shown_}, its bar {'shown' if bar_ else 'not shown'}")
                if "shown" in step and sorted(step["shown"]) != sorted(shown_):
                    raise RuntimeError(f"time_depth_pins_probe: {shown_} drawn, {step['shown']} expected")
                if "bar" in step and bool(step["bar"]) != bar_:
                    raise RuntimeError(f"time_depth_pins_probe: the preview's bar {'shown' if bar_ else 'not shown'},"
                                       f" {'shown' if step['bar'] else 'not shown'} expected")

            elif op == "model_shown_probe":
                # THE ACTIVE MODEL OF THE SESSION AS ITS ROWS SAY IT: its grid
                # and its velocity ticked, their eyes open in the 3D view
                # (app/features/time_depth_tree: Generate shows the model).
                # {"op":"model_shown_probe"}
                vid_ = _render_vid(server, state)
                cube_ = getattr(state, "ui_cube_tree", None) or {}
                ticked_ = set(getattr(state, "selected_paths", None) or ())
                eyes_ = set(getattr(state, f"visible_paths__{vid_}", None) or ())
                said_ = {k_: (cube_.get(k_) in ticked_, cube_.get(k_) in eyes_) for k_ in ("row", "grid", "prop")}
                _log(out, f"model shown ({vid_}): (ticked, eye open) {said_}")
                wrong_ = [k_ for k_ in ("grid", "prop") if said_[k_] != (True, True)]
                if wrong_ or not cube_.get("row"):
                    raise RuntimeError(f"model_shown_probe: {wrong_ or 'no model in the tree'} not ticked and shown: {said_}")

            elif op == "wellheads_probe":
                # THE WELLS' HEADS (flag and name, engine/wellhead) drawn in
                # the 3D view: {"op":"wellheads_probe","shown":0}
                vid_ = _render_vid(server, state)
                heads_ = [w_ for w_ in server.context.selector.wellheads() if getattr(w_, "view_id", None) == vid_]
                shown_ = [w_ for w_ in heads_ if w_._head is not None and int(w_._head.Visibility)]
                _log(out, f"wellheads ({vid_}): {len(shown_)} shown of {len(heads_)}")
                if "shown" in step and len(shown_) != int(step["shown"]):
                    raise RuntimeError(f"wellheads_probe: {len(shown_)} shown, {step['shown']} expected")

            elif op == "close_view":
                # a view closed the way the dockview's × closes it
                # {"op":"close_view","view":"view_2"}
                with state:
                    mv._on_view_closed(str(step.get("view") or ""))

            elif op == "displays_probe":
                # WHAT A VIEW DRAWS OUTSIDE ITS COMPOSITE (app/scene/displays):
                # how many displays of each kind; every one that follows the
                # exaggeration drawn at the view's — an isolate's visible
                # threshold tips included (E2); with "style", every one that
                # follows Represent By drawn so, the isolate's too (E1).
                # {"op":"displays_probe","view":"view_1","kinds":{"isolate":1},"style":"Wireframe"}
                reg = getattr(server.context, "displays", None)
                if reg is None:
                    raise RuntimeError("displays_probe: the app has no display registry")
                pvid = str(step.get("view") or _render_vid(server, state))
                entries = reg.entries(pvid)
                counts = {}
                for e_ in entries:
                    counts[e_.kind] = counts.get(e_.kind, 0) + 1
                _log(out, f"displays ({pvid}): {sorted(counts.items())}")
                for kind_, n_ in (step.get("kinds") or {}).items():
                    if counts.get(kind_, 0) != int(n_):
                        raise RuntimeError(f"displays_probe: {counts.get(kind_, 0)} {kind_}"
                                           f" in {pvid}, {n_} expected")
                zs_ = float(getattr(state, f"ui_scale_z__{pvid}", 1.0) or 1.0)
                style_ = step.get("style")
                dressed = []
                for e_ in entries:
                    if e_.display is not None:
                        dressed.append((f"{e_.kind} {e_.key}", e_.display, e_.follows_z,
                                        e_.follows_style))
                pvv_ = mv.get_pv_view(pvid)
                for (ivid_, rep_), iso_ in (getattr(server.context, "grid_isolates", None) or {}).items():
                    if ivid_ != pvid or pvv_ is None:
                        continue
                    for t_ in iso_.visible_leaf_tips():
                        for p_ in t_.pv_proxies.values():
                            d_ = pvsimple.GetRepresentation(proxy=p_, view=pvv_)
                            if d_ is not None and int(d_.Visibility):
                                dressed.append((f"threshold tip of {rep_.rsplit('/', 1)[-1]}",
                                                d_, True, True))
                for what_, d_, fz_, fs_ in dressed:
                    if fz_ and abs(float(list(d_.Scale)[2]) - zs_) > 1e-6:
                        raise RuntimeError(f"displays_probe: {what_} drawn at Z x{list(d_.Scale)[2]},"
                                           f" the session is at x{zs_}")
                    if style_ and fs_ and str(d_.Representation).strip("'\"") != style_:
                        raise RuntimeError(f"displays_probe: {what_} drawn as"
                                           f" {d_.Representation}, the view as {style_}")
                _log(out, f"displays ({pvid}): {len(dressed)} display(s) at Z x{zs_}"
                          + (f", as {style_}" if style_ else ""))

            elif op == "camlink_probe":
                # LINKED VIEWS FOLLOW THE GESTURE ITSELF: after a camera_move
                # in the render view (a drag through its interactor, the path
                # a browser drag takes), every view linked to it stands where
                # it stands — ParaView's own camera link, frame by frame, not
                # a copy on the release. {"op":"camlink_probe"}
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                links = list((state.view_links or {}).get(vid) or [])
                if pvv is None or not links:
                    raise RuntimeError(f"camlink_probe: {vid} is linked to no view")
                # the frame ParaView web pushes after each event of a browser
                # drag: a still render of the view PROXY (StillRenderToString)
                # — the interactor itself draws nothing in a trame view
                # (EnableRenderOnInteraction off), and the link copies on
                # that render
                _log(out, f"camlink probe: {vid} EnableRenderOnInteraction="
                          f"{getattr(pvv, 'EnableRenderOnInteraction', '?')}")
                pvv.SMProxy.StillRender()
                ref = [round(float(x), 3) for x in pvv.GetActiveCamera().GetPosition()]
                for other in links:
                    o = mv.get_pv_view(other)
                    pos = ([round(float(x), 3) for x in o.GetActiveCamera().GetPosition()]
                           if o is not None else None)
                    _log(out, f"camlink probe: {vid} {ref} / {other} {pos}")
                    if pos != ref:
                        raise RuntimeError(f"camlink_probe: {other} did not follow"
                                           f" {vid} ({pos} against {ref})")

            elif op == "zoom_wall_probe":
                # The wheel stops at the face of the data instead of flying
                # through it and out the other side. Fired ON THE INTERACTOR,
                # which is the path a browser wheel takes (the remote view
                # hands the event to it): the interactor style dollies and
                # the wall bracketing it judges the result, so the whole
                # chain is under test and not just the arithmetic.
                # {"op":"zoom_wall_probe","notches":80}
                from fespp_on_trame.app.views import camera as _cam
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid)
                if pvv is None:
                    raise RuntimeError("zoom_wall_probe: no render view")
                # On the Earth the framings are blocked (they aim at
                # local-CRS bounds), and the Globe framed itself.
                on_globe = bool(getattr(state, f"ui_globe_mode__{vid}", False))
                if not on_globe:
                    with state:
                        controller.nav_reset(vid)
                await asyncio.sleep(float(step.get("settle", 2)))
                box = _cam.visible_box(pvv, data_only=on_globe)
                if box is None:
                    raise RuntimeError(
                        "zoom_wall_probe: no PICKABLE prop is visible — there"
                        " is no data box to stop at (on the Earth, the planet"
                        " and the wellhead marks are unpickable on purpose,"
                        " so this means no data is drawn)")
                iren = pvv.GetClientSideObject().GetInteractor()
                if iren is None:
                    raise RuntimeError(
                        "zoom_wall_probe: this view has NO interactor, so no"
                        " wheel event can reach the wall — the wall would be"
                        " installed on nothing")
                start = list(pvv.GetActiveCamera().GetPosition())
                # "via": "button" zooms with the title bar's buttons
                # (nav_zoom_step) instead of the wheel: the same wall, judged
                # by the other control
                by_button = step.get("via") == "button"
                for _ in range(int(step.get("notches", 80))):
                    if by_button:
                        with state:
                            controller.nav_zoom_step(vid, 0.8)
                    else:
                        iren.MouseWheelForwardEvent()
                end = list(pvv.GetActiveCamera().GetPosition())
                moved = sum((end[i] - start[i]) ** 2 for i in range(3)) ** 0.5
                span = sum((box[1][i] - box[0][i]) ** 2 for i in range(3)) ** 0.5
                inside = _cam.eye_is_inside(
                    pvv, _cam.visible_box(pvv, data_only=on_globe))
                said = state.to_dict().get(f"ui_zoom_note__{vid}") or ""
                _log(out, f"zoom wall ({vid}): globe={on_globe}"
                          f" box_diagonal={span:.1f} box_lo={[round(v) for v in box[0]]}"
                          f" eye_moved={moved:.1f} inside={inside}"
                          f" said={said!r}")
                if moved <= 0:
                    raise RuntimeError(
                        "zoom_wall_probe: the wheel did not move the camera at"
                        " all — the wall was never asked anything")
                if step.get("through"):
                    # {"through": true}: a plain 3D view has NO wall — the
                    # wheel goes into the grid (the PO, 14/10: only the Globe
                    # stops it), silently
                    if not inside:
                        raise RuntimeError(
                            "zoom_wall_probe: the wheel stopped at the data on a"
                            " plain 3D view, where it must go through")
                    if said:
                        raise RuntimeError(
                            f"zoom_wall_probe: a plain 3D view spoke of a wall: {said!r}")
                else:
                    if inside:
                        raise RuntimeError(
                            "zoom_wall_probe: the wheel took the eye INSIDE the"
                            " data's box")
                    if not said:
                        raise RuntimeError(
                            "zoom_wall_probe: the zoom stopped and said nothing")
                    # and the refusal clears itself: one notch the other way is
                    # a notch the wall has no reason to refuse
                    if by_button:
                        with state:
                            controller.nav_zoom_step(vid, 1.25)
                    else:
                        iren.MouseWheelBackwardEvent()
                    await asyncio.sleep(float(step.get("clear_settle", 1)))
                    still = state.to_dict().get(f"ui_zoom_note__{vid}") or ""
                    _log(out, f"zoom wall ({vid}): after one notch out, said={still!r}")
                    if still:
                        raise RuntimeError(
                            "zoom_wall_probe: the refusal stayed on screen after a"
                            " notch that was not refused")

            elif op == "globe_probe":
                # The Globe's availability speaks: offered exactly when a usable
                # CRS is known, else the Camera card says why.
                # {"op":"globe_probe","expect":false}
                snap = state.to_dict()
                ok = bool(snap.get("ui_globe_ok"))
                why = snap.get("ui_globe_why") or ""
                _log(out, f"globe: offered={ok} why={why!r}")
                if ok == bool(why):
                    raise RuntimeError("globe_probe: the Globe is offered with a reason not to,"
                                       " or refused without one")
                if "expect" in step and bool(step["expect"]) != ok:
                    raise RuntimeError(f"globe_probe: expected offered={step['expect']}, got {ok}")
                if step.get("mode") is not None and ok:
                    # "mode": true opens the Globe view beside the 3D view in
                    # use (its door): the flag, the scene kind and the eyes it
                    # inherited; false closes it, the 3D view left as it was
                    mv_ = getattr(server.context, "multi_view", None)
                    ref = _render_vid(server, state)
                    want = bool(step["mode"])
                    if not want:
                        # closing: the 3D view that stays is the one compared
                        gone = {str(v) for v in mv_.panel_ids_of_kind("globe")}
                        ref = next((str(v) for v in mv_.view_ids() if str(v) not in gone), ref)
                    eyes = list(state.to_dict().get(f"visible_paths__{ref}") or [])
                    with state:
                        if want:
                            controller.open_globe()
                        else:
                            for pid_ in list(mv_.panel_ids_of_kind("globe")):
                                mv_._on_view_closed(pid_)
                    await asyncio.sleep(float(step.get("settle", 6)))
                    globes = list(mv_.panel_ids_of_kind("globe"))
                    vid = globes[0] if globes else _render_vid(server, state)
                    snap = state.to_dict()
                    scene = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid)
                    kind = type(scene).__name__ if scene is not None else None
                    now = list(snap.get(f"visible_paths__{vid}") or [])
                    card = snap.get(f"ui_globe__{vid}") or {}
                    _log(out, f"globe view ({vid}, from {ref}): wanted={want} globes={globes}"
                              f" flag={bool(snap.get(f'ui_globe_mode__{vid}'))}"
                              f" scene={kind!r} eyes_before={len(eyes)} eyes_after={len(now)}"
                              f" card_keys={sorted(card.keys())[:8]}")
                    if bool(globes) != want or bool(snap.get(f"ui_globe_mode__{vid}")) != want:
                        raise RuntimeError("globe_probe: the Globe view did not open or close")
                    if want and (kind or "") != "GlobeScene":
                        raise RuntimeError(f"globe_probe: the scene is {kind!r}, not a GlobeScene")
                    if not want and (kind or "") != "PdcScene":
                        raise RuntimeError(f"globe_probe: the 3D view's scene is {kind!r}, not a PdcScene")
                    if sorted(now) != sorted(eyes):
                        raise RuntimeError("globe_probe: the Globe does not show what its 3D view shows")

            elif op == "well_layout_probe":
                # The well laid out like a grid: under the wellbore titled
                # `well`, the trajectory a direct child, the log frames in a
                # "logs" folder, the marker frames in "markers", the
                # completions in "completions", each folder present only
                # when the well has some — {"op":"well_layout_probe",
                # "well":"55/33-A-4","logs":1,"markers":1,"completions":0}
                asm = tree._data_assembly
                wid = _find_node_by_title(tree, step["well"])
                if wid is None:
                    raise RuntimeError(f"well_layout_probe: no node titled {step['well']!r}")

                def _t(n):
                    return asm.GetAttributeOrDefault(n, "type", "") or ""

                def _title(n):
                    return asm.GetAttributeOrDefault(n, "title", "") or ""
                if _t(wid) != "Wellbore":
                    raise RuntimeError(f"well_layout_probe: {step['well']!r} is a {_t(wid)!r} node")
                kids = list(asm.GetChildNodes(wid, False))
                by_type = {}
                for k in kids:
                    by_type.setdefault(_t(k), []).append(k)
                folders = {"logs": "WellboreLogsFolder", "markers": "WellboreMarkersFolder",
                           "completions": "WellboreCompletionsFolder"}
                counts = {}
                for name, ftype in folders.items():
                    fs_ = by_type.get(ftype, [])
                    if len(fs_) > 1:
                        raise RuntimeError(f"well_layout_probe: {len(fs_)} {name} folders")
                    counts[name] = (len(list(asm.GetChildNodes(fs_[0], False))) if fs_ else 0)
                    if fs_ and _title(fs_[0]) != name:
                        raise RuntimeError(f"well_layout_probe: the {name} folder is titled {_title(fs_[0])!r}")
                traj = [k for k in kids if _t(k) in ("Trajectory", "WellboreTrajectory")]
                stray = [k for k in kids if _t(k) in ("Frame", "WellboreFrame", "MarkerFrame",
                                                      "WellboreMarkerFrame", "Completion",
                                                      "WellboreCompletion")]
                _log(out, f"well layout {step['well']!r}: trajectories={len(traj)} {counts}"
                          f" stray={[_t(k) + ':' + _title(k) for k in stray]}"
                          f" children={[_t(k) + ':' + _title(k) for k in kids]}")
                if stray:
                    raise RuntimeError(f"well_layout_probe: {len(stray)} frame(s) / completion(s)"
                                       " beside the folders instead of inside")
                if not traj:
                    raise RuntimeError("well_layout_probe: the trajectory is not a direct child")
                for name in folders:
                    if name in step and counts[name] != int(step[name]):
                        raise RuntimeError(f"well_layout_probe: {counts[name]} in {name},"
                                           f" expected {step[name]}")

            elif op == "tree_owners_probe":
                # What the widget lays the Interpretation and Feature rows out by:
                # the plugin's attributes on a representation's top node, none on
                # one with no interpretation, and the forest flat under the root.
                # {"op":"tree_owners_probe","nodes":[{"title":"Depth Surface - Interpreted",
                # "feature":true},{"title":"Geogrid","owned":false}]}
                asm = tree._data_assembly

                def _t(n):
                    return asm.GetAttributeOrDefault(n, "type", "") or ""
                top = sorted({_t(k) for k in asm.GetChildNodes(0, False)})
                _log(out, f"tree top={top}")
                if any(t in ("Feature", "Interpretation") for t in top):
                    raise RuntimeError("tree_owners_probe: grouping rows in the assembly")
                for want in step.get("nodes") or []:
                    nid = _find_node_by_title(tree, want["title"])
                    if nid is None:
                        raise RuntimeError(f"tree_owners_probe: no node titled {want['title']!r}")
                    while asm.GetParent(nid) > 0:
                        nid = asm.GetParent(nid)
                    says = {k: asm.GetAttributeOrDefault(nid, k, "") or ""
                            for k in ("interpretation", "interpretationTitle", "feature", "featureTitle")}
                    _log(out, f"  {want['title']!r} ({_t(nid)}): {says}")
                    if bool(says["interpretation"]) != bool(want.get("owned", True)):
                        raise RuntimeError(f"tree_owners_probe: {want['title']!r} says {says}")
                    if want.get("feature") and not says["feature"]:
                        raise RuntimeError(f"tree_owners_probe: {want['title']!r} names no feature")

            elif op == "xml_find_probe":
                # The explorer's own door: an explorer panel opened empty,
                # a search typed in it, the hits, one picked — a tab of THAT
                # panel. {"op":"xml_find_probe","text":"poro","pick":0,
                # "min_hits":1,"title":"Porosity"}
                # the Explorer is ONE panel: opened, or the one already there
                with state:
                    mv.add_view(kind="xml")
                await asyncio.sleep(float(step.get("settle", 2)))
                panels = [str(v) for v in (mv.panel_ids_of_kind("xml") or [])]
                if len(panels) != 1:
                    raise RuntimeError(f"xml_find_probe: {len(panels)} explorer panels, one expected")
                pid = panels[0]
                with state:
                    controller.xml_search(step["text"], pid)
                await asyncio.sleep(1.0)
                snap = state.to_dict()
                found = snap.get(f"xml_hits__{pid}") or {}
                hits = found.get("hits") or []
                _log(out, f"xml find {step['text']!r}: total={found.get('total')} hits={len(hits)}"
                          f" first={[(h['title'], h['type']) for h in hits[:3]]} note={found.get('note')!r}")
                if found.get("note"):
                    raise RuntimeError(f"xml_find_probe: {found['note']}")
                if len(hits) < int(step.get("min_hits", 1)):
                    raise RuntimeError(f"xml_find_probe: {len(hits)} hits, expected at least {step.get('min_hits', 1)}")
                if "title" in step and not any(h["title"] == step["title"] for h in hits):
                    raise RuntimeError(f"xml_find_probe: {step['title']!r} is not among the hits")
                pick = hits[int(step.get("pick", 0))]
                with state:
                    controller.xml_pick(pick, pid)
                await asyncio.sleep(1.0)
                snap = state.to_dict()
                tabs = snap.get(f"xml_tabs__{pid}") or []
                xml = snap.get(f"xml_xml__{pid}") or ""
                cleared = not (snap.get(f"xml_hits__{pid}") or {}).get("query")
                _log(out, f"xml pick {pick['title']!r}: tabs={[t.get('title') for t in tabs]} xml={len(xml)} chars"
                          f" list_cleared={cleared} panels={len(mv.panel_ids_of_kind('xml') or [])}")
                at = int(snap.get(f"xml_tab__{pid}") or 0)
                shown = tabs[at] if 0 <= at < len(tabs) else None
                if not shown or shown.get("title") != pick["title"]:
                    raise RuntimeError("xml_find_probe: the pick did not open a tab in the same panel")
                if not xml or pick["uuid"].lower() not in xml.lower():
                    raise RuntimeError("xml_find_probe: the tab does not show the picked object")
                if not cleared:
                    raise RuntimeError("xml_find_probe: the list was not cleared after the pick")
                if len(mv.panel_ids_of_kind("xml") or []) != 1:
                    raise RuntimeError("xml_find_probe: the pick opened another panel")

            elif op == "xml_row_probe":
                # "Explore the XML" on a row: the explorer panel that opens
                # and what it says — {"op":"xml_row_probe","title":"GasSat",
                # "expect":"object"|"series"|"none"}; "path":"" for nothing
                # active. object = a tab on the row, no note; series = a tab
                # on the TimeSeries with the band; none = no tab, a note
                if "path" in step:
                    path = step["path"]
                else:
                    nid = _find_node_by_title(tree, step["title"], step.get("under"))
                    if nid is None:
                        raise RuntimeError(f"xml_row_probe: no node titled {step['title']!r}")
                    path = tree.find_path(nid)
                # the Explorer is ONE panel: a row explored after another opens
                # a tab in it
                before = [str(v) for v in (mv.panel_ids_of_kind("xml") or [])]
                tabs_before = len(getattr(state, f"xml_tabs__{before[0]}", None) or []) if before else 0
                with state:
                    if path:
                        state.context_action = {"action": "xml", "path": path, "n": i}
                    else:
                        # the Attributes card's Explore with nothing active
                        vid = getattr(state, "fespp_active_panel_id", "") or "view_1"
                        state[f"active_path__{vid}"] = ""
                        controller.xml_open_active(vid)
                await asyncio.sleep(float(step.get("settle", 2)))
                panels = [str(v) for v in (mv.panel_ids_of_kind("xml") or [])]
                if len(panels) != 1:
                    raise RuntimeError(f"xml_row_probe: {len(panels)} explorer panels, one expected")
                pid = panels[0]
                snap = state.to_dict()
                tabs = list(snap.get(f"xml_tabs__{pid}") or [])
                at = int(snap.get(f"xml_tab__{pid}") or 0)
                shown = tabs[at] if 0 <= at < len(tabs) else None
                note = snap.get(f"xml_note__{pid}") or ""
                xml = snap.get(f"xml_xml__{pid}") or ""
                root_tag = ""
                if xml:
                    # the root element, past the XML declaration
                    body = xml.split("?>", 1)[-1] if xml.lstrip().startswith("<?") else xml
                    root_tag = body.lstrip()[:120].split(">", 1)[0]
                _log(out, f"xml row {step.get('title')!r}: tabs={[t.get('title') for t in tabs]} shown={at}"
                          f" xml={len(xml)} chars root={root_tag!r} note={note!r}")
                want = step.get("expect", "object")
                if want == "object" and not (shown and xml and not note):
                    raise RuntimeError("xml_row_probe: expected the object, no note")
                if want == "series" and not (shown and xml and "TimeSeries" in note and "TimeSeries" in root_tag):
                    raise RuntimeError("xml_row_probe: expected the TimeSeries under a band saying so")
                if want == "none" and (len(tabs) != tabs_before or not note):
                    raise RuntimeError("xml_row_probe: expected no tab opened and a note")
                # "tab": the name the explorer gives the object — a grid's
                # geometry leaf ("SolidColor" in FESPP) is named by its grid
                if step.get("tab") is not None and (not shown or shown.get("title") != step["tab"]):
                    raise RuntimeError(f"xml_row_probe: tab {shown.get('title') if shown else None!r},"
                                       f" expected {step['tab']!r}")

            elif op == "grid_layout_probe":
                # The SolidColor layout of a grid, whatever order its EPCs
                # came in (a grid met first as a partial stub — its
                # properties' file read before its own — must not stay flat):
                # the node titled `grid` is a GridContainer, its properties
                # folder holds the geometry leaf and the property leaves (in
                # their property sets), the completions sit beside the folder
                # — {"op":"grid_layout_probe","grid":"Sector","properties":9};
                # "partial": true while only a file that REFERENCES the grid
                # is read: the leaf is then a Partial stub of the grid's type
                asm = tree._data_assembly
                nid = _find_node_by_title(tree, step["grid"])
                if nid is None:
                    raise RuntimeError(f"grid_layout_probe: no node titled {step['grid']!r}")

                def _t(n):
                    return asm.GetAttributeOrDefault(n, "type", "") or ""

                def _title(n):
                    return asm.GetAttributeOrDefault(n, "title", "") or ""
                if _t(nid) != "GridContainer":
                    raise RuntimeError(f"grid_layout_probe: {step['grid']!r} is a"
                                       f" {_t(nid)!r} node, not a GridContainer")
                kids = list(asm.GetChildNodes(nid, False))
                folder = next((k for k in kids if _t(k) == "PropertiesFolder"), None)
                if folder is None:
                    raise RuntimeError("grid_layout_probe: no properties folder under the container")
                if step.get("partial"):
                    geom = [k for k in asm.GetChildNodes(folder, False)
                            if _t(k) == "Partial" and (asm.GetAttributeOrDefault(k, "supporttype", "") or "")
                            in ("IjkGrid", "UnstructuredGrid")]
                else:
                    geom = [k for k in asm.GetChildNodes(folder, False)
                            if _title(k) == "SolidColor" and _t(k) in ("IjkGrid", "UnstructuredGrid")]
                props = [k for k in asm.GetChildNodes(folder, True) if _t(k).endswith("Property")]
                comps = [k for k in kids if _t(k) in ("Completion", "WellboreCompletion")]
                _log(out, f"grid layout {step['grid']!r}: geometry={len(geom)} properties={len(props)}"
                          f" completions={len(comps)} container={[_t(k) + ':' + _title(k) for k in kids]}")
                if len(geom) != 1:
                    raise RuntimeError(f"grid_layout_probe: {len(geom)}"
                                       f" {'partial stubs' if step.get('partial') else 'geometry leaves'}"
                                       " in the properties folder")
                if "properties" in step and len(props) != int(step["properties"]):
                    raise RuntimeError(f"grid_layout_probe: {len(props)} properties under the folder,"
                                       f" expected {step['properties']}")
                if "completions" in step and len(comps) != int(step["completions"]):
                    raise RuntimeError(f"grid_layout_probe: {len(comps)} completions beside the folder,"
                                       f" expected {step['completions']}")

            elif op == "contact_planes_probe":
                # The Volumetrics card's contact planes in the active 3D
                # view: one per depth given, drawn at the vertical
                # exaggeration in force, gone with the box or the grid —
                # {"op":"contact_planes_probe","expect":true,"zscale":3}
                vid = getattr(state, "fespp_active_panel_id", "") or "view_1"
                views = getattr(server.context, "multi_view", None)
                pvv = views.get_pv_view(vid) if views is not None else v
                found = {}
                for name in ("goc", "owc"):
                    src = pvsimple.FindSource(f"contact_{name}__{vid}")
                    if src is not None:
                        disp = pvsimple.GetDisplayProperties(src, view=pvv)
                        found[name] = [float(x) for x in disp.Scale]
                _log(out, f"contact planes ({vid}): {found}")
                want = step.get("expect", True)
                if bool(found) != bool(want):
                    raise RuntimeError(f"contact_planes_probe: expected planes={want},"
                                       f" found {sorted(found)}")
                if "zscale" in step:
                    for name, scale in found.items():
                        if abs(scale[2] - float(step["zscale"])) > 1e-9:
                            raise RuntimeError(
                                f"contact_planes_probe: the {name.upper()} plane is at"
                                f" z scale {scale[2]}, expected {step['zscale']}")

            elif op == "axes_grid_probe":
                # The navigation card's axes grid: ParaView's data axes grid
                # of the view, its DataScale following the vertical
                # exaggeration so the Z graduations read true depths.
                # {"op":"axes_grid_probe","expect":true,"zscale":3}
                vid = _render_vid(server, state)
                pvv = mv.get_pv_view(vid) if mv is not None else v
                vis = int(pvv.AxesGrid.Visibility)
                scale = [float(x) for x in pvv.AxesGrid.DataScale]
                flag = bool(state.to_dict().get(f"ui_nav_axes_grid__{vid}"))
                _log(out, f"axes grid ({vid}): visible={vis} data_scale={scale}"
                          f" state={flag}")
                want = step.get("expect", True)
                if bool(vis) != bool(want) or flag != bool(want):
                    raise RuntimeError(
                        f"axes_grid_probe: expected {want}, view says {vis},"
                        f" state says {flag}")
                if "zscale" in step and abs(scale[2] - float(step["zscale"])) > 1e-9:
                    raise RuntimeError(
                        f"axes_grid_probe: DataScale z={scale[2]}, expected"
                        f" {step['zscale']}")

            elif op == "camera":
                # Tilt / turn the camera then refit: a slice or a crop seen
                # from straight above is indistinguishable from the whole
                # grid — {"op":"camera","elevation":-60,"azimuth":30}; "zoom":
                # that many times closer, once refitted
                cam = v.GetActiveCamera()
                if step.get("azimuth"):
                    cam.Azimuth(float(step["azimuth"]))
                if step.get("elevation"):
                    cam.Elevation(float(step["elevation"]))
                cam.OrthogonalizeViewUp()
                pvsimple.ResetCamera(v)
                if step.get("zoom"):
                    cam.Dolly(float(step["zoom"]))
                    v.ResetCameraClippingRange() if hasattr(v, "ResetCameraClippingRange") else None
                if step.get("from") in ("south", "north", "east", "west"):
                    # level, from one side: from the South looking North, and so on
                    import math
                    fp_ = list(cam.GetFocalPoint())
                    far_ = math.dist(cam.GetPosition(), fp_)
                    dx_, dy_ = {"south": (0.0, -1.0), "north": (0.0, 1.0), "east": (1.0, 0.0),
                                "west": (-1.0, 0.0)}[step["from"]]
                    cam.SetPosition(fp_[0] + dx_ * far_, fp_[1] + dy_ * far_, fp_[2])
                    cam.SetViewUp(0.0, 0.0, 1.0)
                    pvsimple.ResetCamera(v)
                    _log(out, f"camera: from the {step['from']}")
                if step.get("frame") == "log_tube":
                    # on the tubes of the view's well symbols filter, as drawn:
                    # the middle "span" share of each (a log runs its whole
                    # well, whose view shows nothing of its width)
                    import math
                    import numpy as np
                    from vtkmodules.util.numpy_support import vtk_to_numpy
                    flt_ = next((s_ for (n_, _i), s_ in pvsimple.GetSources().items()
                                 if n_.startswith("fesppWellSymbols_")
                                 and int(getattr(pvsimple.GetRepresentation(proxy=s_, view=v), "Visibility", 0) or 0)),
                                None)
                    if flt_ is None:
                        raise RuntimeError("camera: no log tube to frame")
                    zs_ = float(pvsimple.GetRepresentation(proxy=flt_, view=v).Scale[2])
                    made_ = flt_.GetClientSideObject().GetOutputDataObject(0)
                    asm_ = made_.GetDataAssembly()
                    off_ = (getattr(server.context, "blockscope_scenes", None) or {}).get(_render_vid(server, state)).isolated
                    kept_ = []
                    # the channels the filter draws are off the composite: their tubes, not what else it holds
                    for sel_ in [s_ for s_ in flt_.Selectors if s_ in off_]:
                        for n_ in asm_.SelectNodes([sel_]):
                            for i_ in asm_.GetDataSetIndices(n_):
                                if not made_.GetNumberOfPartitions(i_) or made_.GetPartition(i_, 0) is None:
                                    continue
                                if made_.GetPartition(i_, 0).GetFieldData().GetArray("MarkerSymbol") is not None:
                                    continue      # a marker, drawn by the same filter: no tube
                                pts_ = vtk_to_numpy(made_.GetPartition(i_, 0).GetPoints().GetData())
                                half_ = max(1, int(len(pts_) * float(step.get("span", 0.1)) / 2))
                                at_ = int(len(pts_) * float(step.get("at", 0.5)))
                                kept_.append(pts_[max(0, at_ - half_):at_ + half_] * [1.0, 1.0, zs_])
                    if not kept_:
                        raise RuntimeError("camera: the well symbols filter holds no tube")
                    kept_ = np.concatenate(kept_)
                    centre_ = [float(x_) for x_ in (kept_.min(axis=0) + kept_.max(axis=0)) / 2]
                    size_ = float(np.linalg.norm(kept_.max(axis=0) - kept_.min(axis=0))) * float(step.get("margin", 1.0))
                    way_ = cam.GetDirectionOfProjection()
                    far_ = size_ / (2.0 * math.tan(math.radians(cam.GetViewAngle()) / 2.0))
                    cam.SetFocalPoint(*centre_)
                    cam.SetPosition(*[centre_[i] - way_[i] * far_ for i in range(3)])
                    v.CenterOfRotation = centre_
                    _log(out, f"camera: on the log tubes, {size_:.0f} across as drawn")
                if step.get("frame") == "log_track":
                    # on the trial's tracks (app/features/log_tracks), as drawn,
                    # where they stand off their hole: a log is a short stretch
                    # of its well, lost in a view of the whole — "margin": that
                    # many times their size around
                    import math
                    import numpy as np
                    from vtkmodules.util.numpy_support import vtk_to_numpy
                    box_ = None
                    vid_ = _render_vid(server, state)
                    parts_of_ = getattr(server.context, "log_graph_parts", None)
                    rep_, shown_ = None, set()
                    graphs_ = parts_of_(vid_) if parts_of_ is not None else {}
                    root_ = "/" + next(iter(graphs_)).split("/")[1] if graphs_ else "/data"
                    for (n_, _i), s_ in pvsimple.GetSources().items():
                        r_ = pvsimple.GetRepresentation(proxy=s_, view=v) if n_.startswith(f"fesppLogGraphs_{vid_}_") else None
                        if r_ is not None and int(getattr(r_, "Visibility", 0) or 0):
                            rep_ = r_
                            shown_ |= _graph_rep_blocks(r_, s_, root_)[0]
                    for sel_, parts_ in sorted((parts_of_(vid_) if parts_of_ is not None else {}).items()):
                        data_ = parts_.get("strip") if f"{sel_}/strip" in shown_ else (
                            parts_.get("curve") if f"{sel_}/curve" in shown_ else None)
                        if data_ is None or data_.GetNumberOfPoints() < 4:
                            continue
                        pts_ = vtk_to_numpy(data_.GetPoints().GetData())
                        n_ = len(pts_) // 2
                        # where the log's values are large in size, away from its least
                        # where the graph stands far off its hole: its values large in size
                        off_ = np.linalg.norm(pts_[n_:] - pts_[:n_], axis=1)
                        far_ = off_ > float(step.get("above", 0.05)) * off_.max() if off_.max() > 0 else off_ >= 0
                        pts_ = pts_[:n_][far_]
                        zs_ = float(rep_.Scale[2])
                        b_ = [float(f_(pts_[:, k_]) * (zs_ if k_ == 2 else 1.0)) for k_ in range(3) for f_ in (np.min, np.max)]
                        box_ = b_ if box_ is None else [min(box_[i], b_[i]) if i % 2 == 0 else max(box_[i], b_[i])
                                                        for i in range(6)]
                    if box_ is None:
                        raise RuntimeError("camera: no log track to frame")
                    centre_ = [(box_[0] + box_[1]) / 2, (box_[2] + box_[3]) / 2, (box_[4] + box_[5]) / 2]
                    size_ = math.dist(box_[0::2], box_[1::2]) * float(step.get("margin", 1.0))
                    way_ = cam.GetDirectionOfProjection()
                    far_ = size_ / (2.0 * math.tan(math.radians(cam.GetViewAngle()) / 2.0))
                    cam.SetFocalPoint(*centre_)
                    cam.SetPosition(*[centre_[i] - way_[i] * far_ for i in range(3)])
                    v.CenterOfRotation = centre_
                    _log(out, f"camera: on the log tracks, {size_:.0f} across as drawn")
                if step.get("frame") == "log_lit":
                    # on the highlighted samples of the logs (app/features/log_tracks), each line said
                    import math
                    vid_ = _render_vid(server, state)
                    src_ = pvsimple.FindSource(f"fesppLogLit_{vid_}")
                    if src_ is None:
                        raise RuntimeError("camera: no highlighted sample to frame")
                    lit_ = src_.GetClientSideObject().GetOutputDataObject(0)
                    for c_ in range(lit_.GetNumberOfCells()):
                        ids_ = lit_.GetCell(c_).GetPointIds()
                        _log(out, "  lit cell %d: %s" % (c_, [tuple(round(x_, 1) for x_ in lit_.GetPoint(ids_.GetId(k_)))
                                                            for k_ in range(ids_.GetNumberOfIds())]))
                    b_ = lit_.GetBounds()
                    centre_ = [(b_[0] + b_[1]) / 2, (b_[2] + b_[3]) / 2, (b_[4] + b_[5]) / 2]
                    size_ = math.dist(b_[0::2], b_[1::2]) * float(step.get("margin", 1.0))
                    way_ = cam.GetDirectionOfProjection()
                    far_ = size_ / (2.0 * math.tan(math.radians(cam.GetViewAngle()) / 2.0))
                    cam.SetFocalPoint(*centre_)
                    cam.SetPosition(*[centre_[i] - way_[i] * far_ for i in range(3)])
                    _log(out, f"camera: on the highlighted samples, {size_:.0f} across")
                v.CenterOfRotation = list(v.CameraFocalPoint)
                pvsimple.Render(v)

            elif op == "flush":
                # the views' next frame, as the browser's next gesture asks for one (an import renders none):
                # {"op": "flush"}
                sch_ = getattr(server.context, "render_scheduler", None)
                if sch_ is not None:
                    with state:
                        sch_.flush()

            elif op == "reset_camera":
                pvsimple.ResetCamera(v)
                v.CenterOfRotation = list(v.CameraFocalPoint)
                pvsimple.Render(view=v)

            elif op == "wait":
                await asyncio.sleep(float(step.get("s", 1.0)))

            elif op == "interactive_render_probe":
                # The frame ParaView draws WHILE the camera moves (an
                # interactive render, with its level of detail past
                # LODThreshold) against the still frame after: a camera move
                # must not drop every representation but the wellhead marks.
                # {"op":"interactive_render_probe","lod":true}
                import numpy as _np
                from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
                from vtkmodules.util.numpy_support import vtk_to_numpy
                vid = getattr(state, "fespp_active_panel_id", "") or "view_1"
                pvv = mv.get_pv_view(vid) if mv is not None else v
                rw = pvv.GetRenderWindow()

                def _frame(tag):
                    w2i = vtkWindowToImageFilter()
                    w2i.SetInput(rw)
                    w2i.ShouldRerenderOff()
                    w2i.ReadFrontBufferOff()
                    w2i.Update()
                    img = w2i.GetOutput()
                    a = vtk_to_numpy(img.GetPointData().GetScalars())[:, :3].astype(int)
                    mx, mn = a.max(axis=1), a.min(axis=1)
                    coloured = int((((mx - mn) > 40) & (mx > 60)).sum())
                    # anything drawn over the background grey (95, 93, 91 ≈)
                    bg = ((abs(a[:, 0] - a[0, 0]) < 6) & (abs(a[:, 1] - a[0, 1]) < 6)).sum()
                    drawn = int(a.shape[0] - bg)
                    _log(out, f"  {tag}: coloured={coloured} drawn={drawn} of {a.shape[0]}")
                    return coloured, drawn
                # the pivot: vtk.js and ParaView's interactor orbit around the
                # view's CenterOfRotation; framed once, it must sit on the
                # camera's focal point — a pivot left at the origin swings
                # UTM data thousands of kilometres away on the first drag,
                # and everything but the wellhead marks leaves the screen
                cam0 = pvv.GetActiveCamera()
                focal0 = list(cam0.GetFocalPoint())
                pivot = list(pvv.CenterOfRotation)
                _log(out, f"  pivot={[round(x, 1) for x in pivot]} focal={[round(x, 1) for x in focal0]}")
                if max(abs(p - f) for p, f in zip(pivot, focal0)) > 1e-3 * max(1.0, max(abs(x) for x in focal0)):
                    raise RuntimeError(f"interactive_render_probe: the pivot {pivot} is not the focal point {focal0}")
                old_lod = float(pvv.LODThreshold)
                if step.get("lod", True):
                    pvv.LODThreshold = 0.0    # every interactive render uses the LOD
                pvsimple.Render(view=pvv)
                c_still, d_still = _frame("still before")
                pvv.SMProxy.InteractiveRender()
                c_inter, d_inter = _frame("interactive")
                pvv.SMProxy.StillRender()
                c_after, d_after = _frame("still after")
                # the remote view's road: the window at half size for the
                # interactive frames, back to full size for the still one
                size = list(pvv.ViewSize)
                pvv.ViewSize = [max(1, size[0] // 2), max(1, size[1] // 2)]
                pvv.SMProxy.InteractiveRender()
                _frame("interactive at half size")
                pvv.ViewSize = size
                pvv.SMProxy.StillRender()
                c_resized, _d = _frame("still after the resize")
                if c_resized < 0.95 * c_still:
                    raise RuntimeError(f"interactive_render_probe: the scene did not survive the"
                                       f" half-size interactive frame ({c_resized} against {c_still})")
                # a camera turned by the interactor, no reset: the clipping
                # planes come from the visible geometry's bounds — a bogus
                # bounds hides everything on the first move
                cam = pvv.GetActiveCamera()
                cam.Azimuth(30.0)
                cam.Elevation(15.0)
                pvv.SMProxy.InteractiveRender()
                c_turn, d_turn = _frame("interactive after a turn (no reset)")
                pvv.SMProxy.StillRender()
                c_turn2, d_turn2 = _frame("still after the turn (no reset)")
                try:
                    cr = list(cam.GetClippingRange())
                    _log(out, f"  clipping range={cr} camera pos={[round(x, 1) for x in cam.GetPosition()]}"
                              f" focal={[round(x, 1) for x in cam.GetFocalPoint()]}")
                    scene = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid)
                    rep = scene.ensure_main_rep() if scene is not None else None
                    if rep is not None:
                        b = list(rep.GetProperty("Representation") and rep.SMProxy.GetRepresentedDataInformation().GetBounds())
                        _log(out, f"  composite represented bounds={[round(x, 1) for x in b]}")
                except Exception as exc:
                    _log(out, f"  clipping readout failed: {exc}")
                pvsimple.ResetCamera(pvv)
                pvv.SMProxy.StillRender()
                _frame("still after a reset")
                # the remote view's own road: trame-vtk hands the mouse to
                # vtkPVWebApplication.HandleInteractionEvent — a drag of
                # twelve moves at half size, the release, a still frame
                try:
                    from paraview.modules.vtkPVClientWeb import vtkPVWebApplication
                    from vtkmodules.vtkWebCore import vtkWebInteractionEvent
                    app = vtkPVWebApplication()
                    pvv.ViewSize = [max(1, size[0] // 2), max(1, size[1] // 2)]
                    pvv.UseInteractiveRenderingForScreenshots = 1
                    x, y = 0.5, 0.5
                    for i in range(13):
                        ev = vtkWebInteractionEvent()
                        ev.SetButtons(vtkWebInteractionEvent.LEFT_BUTTON)
                        ev.SetModifiers(0)
                        ev.SetX(x + 0.01 * i)
                        ev.SetY(y + 0.004 * i)
                        app.HandleInteractionEvent(pvv.SMProxy, ev)
                    c_web, d_web = _frame("web drag (interactive, half size)")
                    ev = vtkWebInteractionEvent()
                    ev.SetButtons(0)
                    ev.SetX(x + 0.12)
                    ev.SetY(y + 0.048)
                    app.HandleInteractionEvent(pvv.SMProxy, ev)
                    pvv.UseInteractiveRenderingForScreenshots = 0
                    pvv.ViewSize = size
                    pvv.SMProxy.StillRender()
                    c_web2, d_web2 = _frame("still after the web drag")
                    cam = pvv.GetActiveCamera()
                    _log(out, f"  after the web drag: clipping={[round(v, 1) for v in cam.GetClippingRange()]}"
                              f" pos={[round(v, 1) for v in cam.GetPosition()]} focal={[round(v, 1) for v in cam.GetFocalPoint()]}"
                              f" dist={round(cam.GetDistance(), 1)}")
                    if c_web2 < 0.5 * c_still:
                        raise RuntimeError(f"interactive_render_probe: the scene did not survive the web drag"
                                           f" ({c_web2} against {c_still})")
                except ImportError as exc:
                    _log(out, f"  no web application here: {exc}")
                pvv.LODThreshold = old_lod
                _log(out, f"interactive render: still={c_still} interactive={c_inter} after={c_after}"
                          f" LODThreshold={old_lod}")
                if c_inter < 0.5 * c_still:
                    raise RuntimeError(f"interactive_render_probe: the interactive frame lost the colours"
                                       f" ({c_inter} against {c_still})")
                if d_inter < 0.5 * d_still:
                    raise RuntimeError(f"interactive_render_probe: the interactive frame lost the objects"
                                       f" ({d_inter} against {d_still})")
                if c_after < 0.95 * c_still:
                    raise RuntimeError(f"interactive_render_probe: the still frame after did not come back"
                                       f" ({c_after} against {c_still})")

            elif op == "block_color_probe":
                # Per-block colouring of the composite, measured in pixels:
                # every coloured block keeps its own array (a grid its
                # property, a log its channel), one bar per table. The
                # reconcile's own projection (A) is compared with the
                # triplets written by hand (B) and with the global anchor
                # alone (D, one array for every block: the grid comes out
                # white when a log is coloured first). ONE bar per view (engine/legends):
                # "bars" counts the visible bars, "legend" the tables the
                # Legends card lists. {"op":"block_color_probe",
                # "min_coloured": 80000, "bars": 1, "legend": 2}
                import numpy as _np
                from vtkmodules.vtkIOImage import vtkPNGReader
                from vtkmodules.util.numpy_support import vtk_to_numpy
                vid = getattr(state, "fespp_active_panel_id", "") or "view_1"
                scene = (getattr(server.context, "blockscope_scenes", None) or {}).get(vid)
                if scene is None:
                    raise RuntimeError("block_color_probe: no blockscope scene")
                rep = scene.ensure_main_rep()
                pvv = mv.get_pv_view(vid) if mv is not None else v

                def _shot_count(tag):
                    pvsimple.Render(view=pvv)
                    f = os.path.join(out, f"probe_{tag}.png")
                    pvsimple.SaveScreenshot(f, pvv, ImageResolution=[800, 600])
                    r = vtkPNGReader()
                    r.SetFileName(f)
                    r.Update()
                    img = r.GetOutput()
                    a = vtk_to_numpy(img.GetPointData().GetScalars())[:, :3].astype(int)
                    mx, mn = a.max(axis=1), a.min(axis=1)
                    sat = (mx - mn)
                    # a coloured pixel: saturated (not the grey background,
                    # not a white block); the axes widget is constant
                    # across arrangements and cancels out in the deltas
                    coloured = int(((sat > 40) & (mx > 60)).sum())
                    white = int(((mn > 225)).sum())
                    return coloured, white
                entries = [(sel, e) for sel, e in scene.block_state.items()
                           if e.color_array and sel in scene.visible_selectors()]
                _log(out, f"block colour: {len(entries)} coloured visible block(s):"
                          + "".join(f"\n    {sel.rsplit('/', 1)[-1][:24]} {e.assoc} {e.color_array!r}" for sel, e in entries))
                _log(out, f"  global anchor: {list(rep.ColorArrayName)}"
                          f" triplets={list(rep.BlockColorArrayNames) if rep.GetProperty('BlockColorArrayNames') is not None else None}")
                c0, w0 = _shot_count("anchor_only")
                _log(out, f"  A anchor only: coloured={c0} white={w0}")
                bars = [(r.Title, [round(float(x), 3) for x in list(r.Position)], str(r.WindowLocation), round(float(r.ScalarBarLength), 3))
                        for r in pvv.Representations
                        if r.GetXMLName() == "ScalarBarWidgetRepresentation" and int(getattr(r, "Visibility", 0))]
                _log(out, f"  bars: {len(bars)} {bars}")
                # B: the triplets written by hand, the anchor kept: the same
                # picture as A when the reconcile does its job
                triplets, luts = [], []
                for sel, e in entries:
                    triplets += [sel, "1" if e.assoc == "CELLS" else "0", e.color_array]
                    luts.append(scene.scoped_lut(e.color_array))
                rep.BlockColorArrayNames = triplets
                lut_prop = rep.SMProxy.GetProperty("BlockLookupTables")
                lut_prop.RemoveAllProxies()
                for lut in luts:
                    lut_prop.AddProxy(lut.SMProxy)
                rep.SMProxy.UpdateProperty("BlockColorArrayNames", 1)
                rep.SMProxy.UpdateProperty("BlockLookupTables", 1)
                c1, w1 = _shot_count("anchor_plus_triplets")
                _log(out, f"  B anchor + {len(entries)} triplet(s) by hand: coloured={c1} white={w1}")
                # D: the global anchor alone on the LAST coloured block's
                # array — the single-anchor projection, kept as the reference
                # the per-block colouring must beat
                last = entries[-1][1] if entries else None
                if last is not None:
                    rep.ColorArrayName = [last.assoc, last.color_array]
                    rep.LookupTable = scene.scoped_lut(last.color_array)
                    rep.BlockColorArrayNames = []
                    lut_prop.RemoveAllProxies()
                    rep.SMProxy.UpdateProperty("BlockColorArrayNames", 1)
                    rep.SMProxy.UpdateProperty("BlockLookupTables", 1)
                    c3, w3 = _shot_count("other_anchor_only")
                    _log(out, f"  D anchor={last.color_array!r} alone (the old projection): coloured={c3} white={w3}")
                # back to the reconcile's own projection, and the assertions
                scene.reconcile()
                pvsimple.Render(view=pvv)
                if c0 < 0.95 * c1:
                    raise RuntimeError(f"block_color_probe: the reconcile paints {c0} pixels,"
                                       f" the triplets by hand {c1}")
                if "min_coloured" in step and c0 < int(step["min_coloured"]):
                    raise RuntimeError(f"block_color_probe: {c0} coloured pixels, expected at least"
                                       f" {step['min_coloured']}")
                if "bars" in step and len(bars) != int(step["bars"]):
                    raise RuntimeError(f"block_color_probe: {len(bars)} bar(s), expected {step['bars']}")
                tables = scene.legend_tables()[0]
                _log(out, f"  legends: {len(tables)} {[t['title'] for t in tables]}")
                if "legend" in step and len(tables) != int(step["legend"]):
                    raise RuntimeError(f"block_color_probe: the Legends card lists {len(tables)}"
                                       f" table(s), expected {step['legend']}")
                if "coloured_blocks" in step and len(entries) != int(step["coloured_blocks"]):
                    raise RuntimeError(f"block_color_probe: {len(entries)} coloured visible"
                                       f" block(s), expected {step['coloured_blocks']}")
                # "arrays_present": every coloured block must really CARRY the
                # array it is coloured by — a range can only be read off the
                # block's own data. This is what tells "the application asked
                # for the colour" from "the data is there to give it": a cell
                # SUBSET of a grid (a blocked wellbore, a sub-representation)
                # owns no property, it borrows the grid's by restriction in
                # the plugin, and without that borrowing the block is told to
                # colour by a name nothing holds.
                for sel, e in entries:
                    br = scene.block_range(e, sel)
                    short = sel.rsplit("/", 1)[-1][:26]
                    # A range alone cannot tell a varied field from a constant
                    # one: `_widened` opens a zero-width range to (v-0.5,
                    # v+0.5), which reads like an ordinary range while the
                    # whole object is painted ONE flat colour — which a
                    # reader calls "the grid has lost its colours". So the RAW
                    # range is read too, and the table's title must say it —
                    # on the bar when it holds the view's bar, in the Legends
                    # card otherwise (one bar per view, engine/legends).
                    raw = scene.block_raw_range(e, sel)
                    const = (raw is not None and raw[1] - raw[0] <= 1e-12 * max(
                        1.0, abs(raw[0]), abs(raw[1])))
                    _log(out, f"  block {short} colour={e.color_array!r}"
                              f" range={br} raw={raw} constant={const}")
                    if const:
                        said = [t["title"] for t in tables
                                if e.color_array in t["arrays"]]
                        _log(out, f"  block {short}: CONSTANT field — its table"
                                  f" says {said}")
                        if not any("constant" in t for t in said):
                            raise RuntimeError(
                                "block_color_probe: the block is painted one"
                                " flat colour because its array is constant,"
                                f" and its legend does not say so — {said}")
                    if step.get("arrays_present") and br is None:
                        raise RuntimeError(
                            f"block_color_probe: block {short} is coloured by"
                            f" {e.color_array!r} but does not carry it")
                    if e.categories:
                        continue
                    if br is not None and br[1] - br[0] > 0 and (br[1] - br[0]) < 1e-30:
                        raise RuntimeError(f"block_color_probe: the range of {e.color_array!r} is degenerate: {br}")

            elif op == "assistant_probe":
                await _assistant_probe(server, state, controller, tree, step, out)

            elif op == "shot":
                pvsimple.Render(view=v)
                name = step.get("name", f"step{i}")
                fname = f"{shot_idx:02d}_{name}.png"
                pvsimple.SaveScreenshot(
                    os.path.join(out, fname), v,
                    ImageResolution=list(_SHOT_RESOLUTION),
                )
                shot_idx += 1
                _log(out, f"shot: {fname}")

            else:
                raise RuntimeError(f"unknown op: {op!r}")

            await asyncio.sleep(float(step.get("settle", _DEFAULT_SETTLE)))
            # a panel's figures are computed one turn after the gesture,
            # behind its view's bar: a probe reads them
            # once they are out, not while they are being read
            waited = 0.0
            while waited < 120.0 and _heavy_pending(controller):
                await asyncio.sleep(0.1)
                waited += 0.1

        _log(out, "done")
    except Exception as exc:
        _log(out, f"ERROR: {exc!r}")
        with open(os.path.join(out, "ERROR.txt"), "w") as f:
            f.write(repr(exc))
    finally:
        with open(os.path.join(out, "DONE"), "w") as f:
            f.write("done")
