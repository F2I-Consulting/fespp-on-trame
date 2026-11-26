"""The XML explorer (overhaul slice 10: the first feature out of app/boot).

A reference chain is a graph, and a 420 px card is the wrong room for
walking one. The explorer is its own view: per PANEL, a list of tabs, each
tab a navigation STACK. Descending is a click; coming back is the
breadcrumb, and keeping several places open at once is what the tabs are
for — a single stack loses the branch you left."""
from fespp_on_trame.engine import repo_query, row_object


def register(core):
    """Wire the feature's controllers and watchers; hands back what
    the rest of the app still calls (_xml_open_from_path)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    active_data_source = core.active_data_source
    _mv = core.mv
    # ---- XML explorer -------------------------------------------------
    # A reference chain is a graph, and a 420 px card is the wrong room for
    # walking one. The explorer is its own view: per PANEL, a list of tabs,
    # each tab a navigation STACK. Descending is a click; coming back is the
    # breadcrumb, and keeping several places open at once is what the tabs
    # are for — a single stack loses the branch you left.
    def _xml_state(vid):
        tabs = list(getattr(state, f"xml_tabs__{vid}", None) or [])
        idx = int(getattr(state, f"xml_tab__{vid}", 0) or 0)
        if tabs:
            idx = max(0, min(idx, len(tabs) - 1))
        return tabs, idx

    def _xml_show(vid, tabs, idx, note="", with_note=False):
        """Publish a panel's state and fetch what its active tab points at.
        A note alone says why a follow led nowhere and the body stays
        empty; `with_note` shows the object under the note (a row that
        opened something other than what it names)."""
        state[f"xml_tabs__{vid}"] = tabs
        state[f"xml_tab__{vid}"] = idx
        state[f"xml_note__{vid}"] = note
        # Does this plugin build answer the relationship query at all? On an
        # older one both directions come back empty, which reads exactly like
        # "this object is related to nothing" — the Graph reading says which
        # of the two it is showing instead of letting the reader guess.
        try:
            state.ui_xml_relations_ok = repo_query.has_relations(
                active_data_source.get_source())
        except Exception as exc:
            state.ui_xml_relations_ok = False
            print("[fespp] xml relations probe:", exc, flush=True)
        text = ""
        if tabs and (with_note or not note):
            stack = tabs[idx].get("stack") or []
            if stack:
                try:
                    text = repo_query.object_xml(
                        active_data_source.get_source(), stack[-1]["uuid"])
                except repo_query.ChannelMissing:
                    state[f"xml_note__{vid}"] = (
                        "This FESPP build has no query channel — rebuild the "
                        "plugin to browse objects.")
                except Exception as exc:
                    print("[fespp] xml explorer error:", exc, flush=True)
        state[f"xml_xml__{vid}"] = text

    @controller.set("xml_open")
    def xml_open(uuid, title, note=""):
        """The explorer on one object: a new TAB of the one explorer panel
        (opened when there is none, brought to the front otherwise).

        A tab per click, deliberately: following a reference from a 3D
        view's Attributes card is a branch of the exploration, not a
        replacement of it, and the tabs keep every branch at hand.
        """
        uuid = (uuid or "").strip()
        if not uuid:
            return
        mv = _mv()
        if mv is None:
            return
        try:
            pid = mv.add_view(kind="xml")
        except Exception as exc:
            print("[fespp] open xml explorer error:", exc, flush=True)
            return
        vid = str(pid)
        tab = {"title": title or uuid[:8],
               "stack": [{"uuid": uuid, "title": title or uuid[:8]}]}
        # the one explorer panel (views_config): the object opens as a new
        # tab of it, the branches already open kept
        tabs, _idx = _xml_state(vid)
        tabs = tabs + [tab]
        _xml_show(vid, tabs, len(tabs) - 1, note, with_note=bool(note))

    def _xml_open_from_path(path):
        """The XML explorer on the object a row of the tree, a pick in the
        3D view or the active node stands for (engine/row_object says
        which: the row itself, the grid of a grid folder, the TimeSeries
        of a series row, the completion of a perforation). A row that
        opens something other than what it names says so above the
        object; a row with no object of its own, or nothing active, still
        opens an explorer panel — one that says so, instead of a click
        that does nothing."""
        path = path or ""
        leaf = path.rsplit("/", 1)[-1]
        nid = tree.find_node_id(path) if path else None
        title = ""
        holder = ""
        if nid is not None:
            # the name the reader knows the object by: a grid's geometry
            # leaf (a pick on a grid shown without a property) is titled
            # "SolidColor" by FESPP and its properties folder "properties";
            # both open the grid, whose folder carries the grid's name
            title = tree.find_rep_title(nid) or tree.find_label(nid) or ""
            if (tree.find_type(nid) or "") == "PropertiesFolder":
                gid = tree.find_parent_node_id_with_type(nid, "GridContainer")
                title = (tree.find_title(gid) if gid is not None else "") or title
            cid = tree.find_parent_node_id_with_type(nid, "Completion")
            holder = (tree.find_title(cid) or "") if cid is not None else ""
        uuid, note = row_object.resolve(leaf, title, holder) if path else ("", "")
        if uuid:
            controller.xml_open(uuid, title or uuid[:8], note)
            return
        mv = _mv()
        if mv is None:
            return
        try:
            pid = mv.add_view(kind="xml")
        except Exception as exc:
            print("[fespp] open xml explorer error:", exc, flush=True)
            return
        if not path:
            note = ("Nothing is active in this view: click a row of the"
                    " tree, or right-click an object, and explore from there.")
        # the one explorer panel keeps its tabs under the note
        tabs, idx = _xml_state(str(pid))
        _xml_show(str(pid), tabs, idx, note, with_note=bool(tabs))

    @controller.set("xml_open_active")
    def xml_open_active(view_id):
        """The Attributes card's Explore: the explorer on the node the card
        shows — this view's active node."""
        vid = str(view_id or "")
        _xml_open_from_path(getattr(state, f"active_path__{vid}", "") or "")

    _SERIES_MAX = 400   # repeated properties whose indices one answer reads

    def _mark_series(source, tag, rel):
        """The properties a relations answer lists several times under one
        title (one per time step, one per realization: Volve's GasSat, once
        per step) carry their index — `ts`, `real` — read from their own XML
        in ONE round trip, so the Graph reading draws them as ONE time series
        or realization set (the PO, 16/10)."""
        for side in ("target", "source"):
            items = rel.get(side) or []
            seen = {}
            for it in items:
                if "Property" in (it.get("type") or ""):
                    key = (it.get("type"), it.get("title") or "")
                    seen[key] = seen.get(key, 0) + 1
            repeated = [it for it in items
                        if seen.get((it.get("type"), it.get("title") or ""), 0) > 1]
            if not repeated:
                continue
            if len(repeated) > _SERIES_MAX:
                print(f"[fespp] xml relations: {len(repeated)} repeated properties,"
                      f" the indices of the first {_SERIES_MAX} read", flush=True)
                repeated = repeated[:_SERIES_MAX]
            xmls = repo_query.object_xml(source, [it["uuid"] for it in repeated],
                                         cache_tag=tag)
            marked = 0
            for it, xml in zip(repeated, xmls):
                ts, real = repo_query.series_indices(xml)
                if ts is not None:
                    it["ts"] = ts
                if real is not None:
                    it["real"] = real
                marked += ts is not None or real is not None
            print(f"[fespp] xml relations: {len(repeated)} repeated properties ({side}),"
                  f" {marked} with a time step or a realization", flush=True)

    @controller.set("xml_raw")
    def xml_raw(payload, view_id):
        """The Graph reading's right-click "View raw": an object's XML shown
        beside the graph, without leaving the object the tab is on (the PO,
        16/10). `payload` = {uuid, title, type, action}: "show" (the raw
        replaces the unpinned one), "pin" (kept when the next one comes, or
        released), "close"."""
        vid = str(view_id or "")
        p = payload or {}
        uuid = str(p.get("uuid") or "").strip()
        action = str(p.get("action") or "show")
        var = f"xml_raws__{vid}"
        raws = [dict(r) for r in (getattr(state, var, None) or [])]
        if not vid or not uuid:
            return
        if action == "close":
            state[var] = [r for r in raws if r["uuid"] != uuid]
            return
        if action == "pin":
            for r in raws:
                if r["uuid"] == uuid:
                    r["pinned"] = not r.get("pinned")
            state[var] = raws
            return
        if any(r["uuid"] == uuid for r in raws):
            return          # already beside the graph
        source = active_data_source.get_source()
        try:
            xml = repo_query.object_xml(source, uuid)
        except Exception as exc:
            print(f"[fespp] xml raw ({uuid}):", exc, flush=True)
            state[f"xml_note__{vid}"] = f"The XML of this object could not be read ({exc})."
            return
        kept = [r for r in raws if r.get("pinned")]
        state[var] = kept + [{"uuid": uuid, "title": str(p.get("title") or uuid[:8]),
                              "type": str(p.get("type") or ""), "xml": xml or "",
                              "pinned": False}]

    @controller.set("xml_relations")
    def xml_relations(uuid, view_id):
        """The Graph reading asks for one object's relationships; the answer
        is merged into this panel's map so the walk keeps what it already
        has, and a row already answered is never asked again.

        The map is keyed by the reader's assembly TAG: another file loaded is
        another repository, and a uuid that meant something there means
        something else — or nothing — here."""
        vid = str(view_id or "")
        uuid = str(uuid or "").strip()
        if not vid or not uuid:
            return
        var = f"xml_relations__{vid}"
        source = active_data_source.get_source()
        try:
            tag = repo_query.tag(source)
        except Exception as exc:
            print(f"[fespp] xml relations tag ({vid}):", exc, flush=True)
            tag = 0
        have = dict(getattr(state, var, None) or {})
        if have.get("__tag") != tag:
            have = {"__tag": tag}
        if uuid in have:
            return
        try:
            rel = repo_query.object_relations(source, uuid, cache_tag=tag)
            _mark_series(source, tag, rel)
            have[uuid] = rel
        except repo_query.ChannelMissing:
            state[f"xml_note__{vid}"] = (
                "This FESPP build has no query channel — rebuild the plugin "
                "to walk the object graph.")
            return
        except Exception as exc:
            print(f"[fespp] xml relations ({uuid}):", exc, flush=True)
            state[f"xml_note__{vid}"] = (
                f"The relationships of this object could not be read ({exc}).")
            return
        state[var] = have

    @controller.set("xml_follow")
    def xml_follow(ref, view_id):
        """A DataObjectReference was clicked INSIDE the explorer: push it onto
        the active tab's stack. The referenced object need not be in the tree
        — most are not — only in the reader's repository."""
        vid = str(view_id or "")
        ref = ref or {}
        uuid = (ref.get("uuid") or "").strip()
        if not vid or not uuid:
            return
        tabs, idx = _xml_state(vid)
        if not tabs:
            return
        title = ref.get("title") or uuid[:8]
        try:
            text = repo_query.object_xml(
                active_data_source.get_source(), uuid)
        except Exception:
            text = ""
        if not text:
            _xml_show(vid, tabs, idx,
                      "This object is not in the loaded data — the reference "
                      "points outside it.")
            return
        tabs[idx] = dict(tabs[idx])
        tabs[idx]["stack"] = list(tabs[idx].get("stack") or []) + [
            {"uuid": uuid, "title": title}]
        tabs[idx]["title"] = title
        _xml_show(vid, tabs, idx)

    @controller.set("xml_back")
    def xml_back(depth, view_id):
        """Walk the active tab's stack back; depth = entries to keep."""
        vid = str(view_id or "")
        if not vid:
            return
        tabs, idx = _xml_state(vid)
        if not tabs:
            return
        stack = list(tabs[idx].get("stack") or [])
        keep = max(1, min(int(depth or 1), len(stack)))
        tabs[idx] = dict(tabs[idx])
        tabs[idx]["stack"] = stack[:keep]
        tabs[idx]["title"] = stack[keep - 1]["title"]
        _xml_show(vid, tabs, idx)

    @controller.set("xml_select_tab")
    def xml_select_tab(index, view_id):
        vid = str(view_id or "")
        tabs, _ = _xml_state(vid)
        if not vid or not tabs:
            return
        _xml_show(vid, tabs, max(0, min(int(index or 0), len(tabs) - 1)))

    @controller.set("xml_close_tab")
    def xml_close_tab(index, view_id):
        vid = str(view_id or "")
        tabs, idx = _xml_state(vid)
        if not vid or len(tabs) <= 1:
            return          # the last tab stays: an empty explorer says nothing
        i = max(0, min(int(index or 0), len(tabs) - 1))
        tabs.pop(i)
        _xml_show(vid, tabs, min(idx, len(tabs) - 1))

    @controller.set("xml_search")
    def xml_search(text, view_id):
        """The explorer's own door: the objects of the repository whose
        title, type or uuid carry every word typed — at most sixty, the
        panel says how many there were. An empty text clears the list."""
        vid = str(view_id or "")
        if not vid:
            return
        text = (text or "").strip()
        if not text:
            state[f"xml_hits__{vid}"] = {"query": "", "hits": [], "total": 0, "note": ""}
            return
        note = ""
        try:
            index = repo_query.object_index(active_data_source.get_source())
        except repo_query.ChannelMissing:
            index, note = [], ("This FESPP build has no query channel — rebuild"
                               " the plugin to find objects here.")
        except Exception as exc:
            print("[fespp] xml search error:", exc, flush=True)
            index, note = [], f"The repository could not be listed: {exc}"
        if not index and not note:
            note = ("Nothing to find: no file is loaded, or this FESPP build"
                    " does not list its objects (rebuild the plugin).")
        hits, total = repo_query.search_index(index, text)
        state[f"xml_hits__{vid}"] = {
            "query": text, "total": total, "note": note,
            "hits": [{"uuid": h["uuid"], "title": h["title"] or h["uuid"][:8],
                      "type": h["type"], "partial": bool(h.get("partial"))} for h in hits]}

    @controller.set("xml_pick")
    def xml_pick(ref, view_id):
        """An object picked in the explorer's own list: a new tab of THIS
        panel (the user is already where the reading happens), the list
        cleared."""
        vid = str(view_id or "")
        uuid = str((ref or {}).get("uuid") or "").strip()
        if not vid or not uuid:
            return
        title = (ref or {}).get("title") or uuid[:8]
        tabs, idx = _xml_state(vid)
        tabs.append({"title": title, "stack": [{"uuid": uuid, "title": title}]})
        state[f"xml_hits__{vid}"] = {"query": "", "hits": [], "total": 0, "note": ""}
        _xml_show(vid, tabs, len(tabs) - 1)

    @controller.set("xml_new_tab")
    def xml_new_tab(view_id):
        """Duplicate the active tab, so a branch can be explored without
        losing where you were."""
        vid = str(view_id or "")
        tabs, idx = _xml_state(vid)
        if not vid or not tabs:
            return
        clone = {"title": tabs[idx].get("title", ""),
                 "stack": list(tabs[idx].get("stack") or [])}
        tabs.append(clone)
        _xml_show(vid, tabs, len(tabs) - 1)
    return _xml_open_from_path
