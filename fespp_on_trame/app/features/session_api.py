"""session_api — the session document as the application's language (S1,
21/10): what a URL, a host page or a REST front say to FesTrame.

One noun, the session document (`trame_fespp_session.format.document`),
one verb, apply:

* `session_apply_doc(doc)` — a partial document (a dict, or its JSON
  text) applied on the live session through the Session door: its sources
  read (an EPC by server path now, an ETP store once the reader typed the
  token), then `session_host.restore` for the groups it holds; the door's
  report is the answer (`ui_session_status`).
* `session_state()` — the session as one document, in `ui_session_state`
  (the autosave's rule: no query to the reader).
* `session_open_from_url(search)` — the page's query (engine/session_query)
  as a document, applied; `?state=<url>` fetches the document there.

A document names objects by uuid (`uuid:<uuid>`), never by the assembly
paths a host cannot know; the token of an ETP store is never in a URL."""
import json

from fespp_on_trame.engine import session_query

STATE_VAR = "ui_session_state"
# a document fetched from `?state=<url>`: http(s) only, this big at most
FETCH_CAP = 2 * 1024 * 1024


def register(server, session_ctl, host):
    """Wire the document controllers on `server`: `session_ctl` is the
    Session door's controller, `host` the application's session host."""
    from trame_fespp_session import format as sf
    state, controller = server.state, server.controller
    state.setdefault(STATE_VAR, {})

    @controller.set("session_apply_doc")
    def session_apply_doc(doc):
        try:
            obj = json.loads(doc) if isinstance(doc, str) else doc
            document = sf.document(obj, partial=True)
        except (TypeError, ValueError, sf.SessionFileError) as exc:
            # refused in the door's own words, where the report would be
            state[session_ctl.status_var] = {"phase": "error", "file": "document",
                                             "error": str(exc)}
            print(f"[fespp] session document refused: {exc}", flush=True)
            return
        session_ctl.open_document(document, name="document")

    @controller.set("session_state")
    def session_state():
        state[STATE_VAR] = {"schema": sf.SCHEMA, **(host.collect(citations=False) or {})}

    # callable from the page by name (`trame.trigger(name, args)`): what the
    # embed plugin relays from a host page (widgets/embed)
    server.trigger("session_apply_doc")(session_apply_doc)
    server.trigger("session_state")(session_state)

    _register_native(server, host)

    @controller.set("session_open_from_url")
    def session_open_from_url(search):
        try:
            doc = session_query.document_from_query(search)
        except session_query.QueryError as exc:
            state.load_error = str(exc)
            print(f"[fespp] open from URL refused: {exc}", flush=True)
            return
        if doc is None:
            return
        if "state_url" in doc:
            doc = _fetch(doc["state_url"])
            if doc is None:
                return
        print(f"[fespp] open from URL: {json.dumps(doc)[:200]}", flush=True)
        session_apply_doc(doc)

    def _fetch(url):
        """The document at `url` — http(s), at most FETCH_CAP bytes."""
        import requests
        if not url.lower().startswith(("http://", "https://")):
            state.load_error = "A state document is fetched over http(s) only."
            return None
        try:
            r = requests.get(url, timeout=10, stream=True)
            r.raise_for_status()
            body = r.raw.read(FETCH_CAP + 1)
            if len(body) > FETCH_CAP:
                raise ValueError(f"the document is over {FETCH_CAP // (1024 * 1024)} MB")
            return json.loads(body.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — a network or a parse failure: said on the snackbar
            state.load_error = f"The state document could not be read from {url}: {exc}"
            print(f"[fespp] state document: {exc}", flush=True)
            return None


def _register_native(server, host):
    """The native routes' gestures (engine/io/session_endpoint): the objects
    a session reads and a 3D view shows, and its sources, said by uuid —
    no document. The rules are engine/session_objects'; reads go through
    `session_select` (born hidden) and the view's eyes, as a restore does."""
    from fespp_on_trame.engine import node_facts
    from fespp_on_trame.engine import row_object
    from fespp_on_trame.engine import session_objects as so
    state, controller = server.state, server.controller

    def _mv():
        return getattr(server.context, "multi_view", None)

    def _view_ids():
        mv = _mv()
        return list(mv.view_ids()) if mv is not None else []

    def _view(asked, open_one=False):
        """The 3D view spoken of; `open_one`: a session without any (no
        browser attached yet) opens one, as a restore does."""
        mv = _mv()
        vid = so.first_render_view(_view_ids(), mv.kind_of if mv is not None else (lambda _v: ""), asked)
        if vid is None and open_one:
            if mv is None:
                raise so.ObjectsError("The session has no 3D view and cannot open one yet.")
            vid = mv.add_view(kind="render")
        return vid

    def _eyes(vid):
        return list(getattr(state, f"visible_paths__{vid}", None) or []) if vid else []

    def _set_eyes(vid, eyes):
        if eyes != _eyes(vid):
            state[f"visible_paths__{vid}"] = eyes
            controller.on_eye_changed(vid, eyes)

    def _selected():
        return list(getattr(state, "selected_paths", None) or [])

    def _describe(path):
        """(uuid, type, title): the title of the row that names the object,
        not of the leaf drawing it (SolidColor)."""
        tree = getattr(server.context, "tree", None)
        nid = tree.find_node_id(path) if tree is not None and path else None
        uuid = row_object.uuid_of(str(path).rsplit("/", 1)[-1])
        if nid is None:
            return uuid, "", ""
        root = tree.find_node_id(so.object_root(path, row_object.uuid_of))
        title = (tree.find_title(root) if root is not None else "") or tree.find_title(nid)
        return uuid, tree.find_type(nid) or "", title or ""

    def _loaded():
        """Whether a path's data is in the session (read, not only asked
        for): a representation, a property, a marker read; a calculator's
        property is computed when shown."""
        held = set()
        for key in ("ui_loaded_rep_paths", "ui_loaded_array_paths", "ui_loaded_marker_paths"):
            held.update(getattr(state, key, None) or [])
        return lambda path: path in held or node_facts.is_derived(path)

    def _objects(vid, missing=()):
        """The objects answer: each object read, shown or not, loaded or not;
        `loading` while a read runs."""
        return {"view": vid, "objects": so.rows(_selected(), _eyes(vid), _describe, _loaded()),
                "missing": list(missing),
                "loading": bool((getattr(state, "ui_load_progress", None) or {}).get("running"))}

    def _paths(uuids):
        found = [(u, host.path_by_uuid(u)) for u in uuids]
        return [p for _u, p in found if p], [u for u, p in found if not p]

    @controller.set("session_objects")
    def session_objects(view=None):
        return _objects(_view(view))

    @controller.set("session_show")
    def session_show(uuids, replace=False, show=True, view=None):
        """`uuids` read and shown in the 3D view, added to what is there,
        or (`replace`) the whole of it."""
        vid = _view(view, open_one=show)
        want, missing = _paths(uuids)
        selected = _selected()
        if replace:
            read, shown = so.replaced(want, show)
            _, others = so.removed([p for p in selected if p not in read], selected,
                                   {v: _eyes(v) for v in _view_ids() if v != vid})
        else:
            read, shown = so.added(want, selected, _eyes(vid), show)
            others = {}
        controller.session_select(read, replace=True)
        _set_eyes(vid, shown)
        for v, eyes in others.items():
            _set_eyes(v, eyes)
        return _objects(vid, missing)

    @controller.set("session_remove")
    def session_remove(uuids=None, view=None):
        """`uuids` (every object when None) no longer read, nor shown in
        any view."""
        vid = _view(view)
        selected = _selected()
        if uuids is None:
            gone, missing = selected, []
        else:
            found = [(u, host.path_by_uuid(u)) for u in uuids]
            gone = [p for _u, p in found if p in selected]
            missing = [u for u, p in found if p not in selected]
        read, eyes = so.removed(gone, selected, {v: _eyes(v) for v in _view_ids()})
        controller.session_select(read, replace=True)
        for v, e in eyes.items():
            _set_eyes(v, e)
        return _objects(vid, missing)

    @controller.set("session_catalogue")
    def session_catalogue(kind="", text="", limit=500, view=None):
        """Every object of the data the session holds, read or not
        (engine/session_objects.catalogue): what a host lists to choose from
        before it shows anything."""
        vid = _view(view)
        tree = getattr(server.context, "tree", None)
        objects, seen = [], set()
        for nid, _kids in (tree.iter_nodes() if tree is not None else ()):
            path = tree.find_path(nid) or ""
            uuid = row_object.uuid_of(path.rsplit("/", 1)[-1])
            if not uuid or uuid in seen:
                continue
            seen.add(uuid)
            target = host.path_by_uuid(uuid) or path
            objects.append((target,) + tuple(_describe(target)))
        rows, total = so.catalogue(objects, _selected(), _eyes(vid), kind, text, limit)
        return {"view": vid, "objects": rows, "total": total, "truncated": total > len(rows)}

    @controller.set("session_sources")
    def session_sources():
        """The files read and the ETP store, as the session holds them."""
        files = [{"name": f.get("name"), "size_mb": f.get("size_mb"), "failed": bool(f.get("failed"))}
                 for f in host.loaded_files()]
        end = dict(getattr(state, "ui_etp_endpoint", None) or {})
        etp = None
        if end.get("url"):
            now = host.etp_state() or {}
            etp = {"url": end["url"], "partition": end.get("partition") or "",
                   "connected": bool(now.get("connected")), "dataspaces": list(now.get("loaded") or []),
                   # what the store lists, loaded or not
                   "available": list(getattr(state, "etp_dataspaces", None) or []) if now.get("connected") else []}
        return {"files": files, "etp": etp}

    @controller.set("session_load_file")
    def session_load_file(path):
        """An EPC under the server's open directory read now: None, or why
        it was not."""
        state.load_error = ""
        if host.load_file(path):
            return None
        return getattr(state, "load_error", "") or f"{path}: not read."


def mount(server):
    """The page's query handed to the server once the client is mounted
    (inside the layout being built): `?epc=…`, `?uuid=…`, `?state=…`."""
    from trame.widgets import client
    client.ClientTriggers(mounted=(server.controller.session_open_from_url,
                                   "[window.location.search]"))


EMBED_ORIGINS_VAR = "FESPP_EMBED_ORIGINS"


def enable_embed(server):
    """The page that embeds FesTrame talks to it by postMessage with the
    same documents (widgets/embed): the plugin, with the origins it may
    hear (`FESPP_EMBED_ORIGINS`, comma-separated, "*" by default). Returns
    the module, for the www check."""
    import os
    from trame_fespp_embed import module as embed_module
    origins = [o.strip() for o in (os.environ.get(EMBED_ORIGINS_VAR) or "*").split(",") if o.strip()]
    server.enable_module({"serve": dict(embed_module.serve),
                          "scripts": list(embed_module.scripts),
                          "vue_use": [("trame_fespp_embed", {"origins": origins})]})
    return [embed_module]
