"""The document routes of a session's own HTTP server (S3, 21/10) — what
Apache's `<prefix>/api/<session id>/<path>` rule reaches, and what the
pool's REST front proxies:

    POST /apply   a partial session document (JSON) applied on this
                  session (app/features/session_api); the answer is the
                  door's status — its report, or the error that refused
                  the document (400). An `Authorization: Bearer <token>`
                  header connects the document's ETP store first: the
                  token travels in the header, never in the document.
    GET  /state   the session as one document.

and the native routes, objects and sources said by uuid, no document
(app/features/session_api's gestures, engine/session_objects' rules):

    GET    /objects        the objects read, each shown or not in the 3D view,
                           loaded or not
    POST   /objects        {"uuids": […], "show": true} read and shown, added;
                           ?wait=<s> answers once the reads are over (110 s
                           at most)
    PUT    /objects        the same, the whole of what is read and shown
    GET    /catalogue      every object of the data, read or not: ?type=,
                           ?q= (in its title), ?limit= (500)
    DELETE /objects        ?uuid=… (repeated) no longer read; none: all
    GET    /sources        the files read and the ETP store
    POST   /sources/files  {"path": …} an EPC under the server's open directory
    POST   /sources/etp    {"url", "partition", "dataspaces"} connected and
                           loaded; the credentials in the Authorization
                           header, Bearer or Basic, never in the body

`?view=<id>` names the 3D view of the object routes (the first one when
absent). Registered on the same route registry as the upload
(upload_endpoint)."""
import asyncio
import base64

from aiohttp import web as aiohttp_web

from fespp_on_trame.engine import session_objects as so
from fespp_on_trame.engine.io.upload_endpoint import register_route


def bearer_token(headers):
    """The token of an `Authorization: Bearer …` header, "" otherwise."""
    auth = (headers or {}).get("Authorization", "") or ""
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def etp_credentials(headers):
    """The ETP store's credentials of an Authorization header, in the words
    of the OSDU / ETP form (engine/etp.credentials): Bearer gives
    {"token"}, Basic (base64 of user:password) {"auth": "basic", "user",
    "password"}; anything else {}."""
    scheme, _, value = ((headers or {}).get("Authorization", "") or "").strip().partition(" ")
    value = value.strip()
    if not value:
        return {}
    if scheme.lower() == "bearer":
        return {"token": value}
    if scheme.lower() == "basic":
        try:
            user, sep, password = base64.b64decode(value, validate=True).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError) as exc:
            # said without the header: it holds a password
            print(f"[fespp] native route: a Basic header that is not base64 of user:password ({type(exc).__name__})",
                  flush=True)
            return {}
        if sep and user:
            return {"auth": "basic", "user": user, "password": password}
    return {}


#: the longest a request waits for its reads (`?wait=`): the pool relays with a 120 s timeout
WAIT_MOST = 110


def _error(status, text):
    return aiohttp_web.json_response({"error": text}, status=status)


async def _body(request):
    """The request's JSON object, {} when it has no body."""
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001 — the body is the client's: said back
        raise so.ObjectsError(f"A JSON object is expected ({exc}).") from None
    if not isinstance(body, dict):
        raise so.ObjectsError("A JSON object is expected.")
    return body


def register(server):
    state, controller = server.state, server.controller

    async def handle_apply(request):
        try:
            doc = await request.json()
        except Exception:  # noqa: BLE001 — the body is the client's: said back as the refusal
            return aiohttp_web.json_response({"phase": "error", "error": "A JSON document is expected."},
                                             status=400)
        token = bearer_token(request.headers)
        etp = ((doc if isinstance(doc, dict) else {}).get("sources") or {}).get("etp") or {}
        if token and etp.get("url") and not getattr(state, "etp_connected", False):
            # the host's token: the connection first, the door loads the
            # dataspaces once connected and applies the document then
            res = controller.etp_connect({"url": etp["url"], "partition": etp.get("partition") or "",
                                          "token": token})
            if asyncio.iscoroutine(res):
                await res
        controller.session_apply_doc(doc)
        state.flush()
        status = dict(getattr(state, "ui_session_status", None) or {})
        return aiohttp_web.json_response(status, status=400 if status.get("phase") == "error" else 200)

    async def handle_state(request):
        controller.session_state()
        state.flush()
        return aiohttp_web.json_response(getattr(state, "ui_session_state", None) or {})

    register_route("POST", "/apply", handle_apply)
    register_route("GET", "/state", handle_state)
    _register_native(server)


def _register_native(server):
    state, controller = server.state, server.controller

    def native(handler):
        """A native route: its refusals said in a JSON `error` (400), the
        answer flushed to the browser attached to the session."""
        async def route(request):
            try:
                answer = await handler(request)
            except so.ObjectsError as exc:
                return _error(400, str(exc))
            state.flush()
            return answer if isinstance(answer, aiohttp_web.Response) else aiohttp_web.json_response(answer)
        return route

    def view_of(request):
        return request.query.get("view") or None

    @native
    async def objects_get(request):
        return controller.session_objects(view=view_of(request))

    async def _settle(answer, wait):
        """The answer once the reads it asked for are over, `wait` seconds at
        most — said again as it then stands, `loading` true when the time ran
        out first."""
        if wait <= 0 or so.settled(answer):
            return answer
        loop = asyncio.get_event_loop()
        end = loop.time() + wait
        again = answer
        while loop.time() < end:
            await asyncio.sleep(0.25)
            again = controller.session_objects(view=answer.get("view"))
            if so.settled(again):
                break
        return dict(again, missing=answer.get("missing", []))

    async def _show(request, replace):
        body = await _body(request)
        wait = so.count_of(request.query.get("wait"), "wait", 0, WAIT_MOST)
        answer = controller.session_show(so.uuids_of(body), replace=replace,
                                         show=so.flag_of(body, "show"), view=view_of(request))
        return await _settle(answer, wait)

    @native
    async def objects_post(request):
        return await _show(request, replace=False)

    @native
    async def objects_put(request):
        return await _show(request, replace=True)

    @native
    async def objects_delete(request):
        asked = request.query.getall("uuid", [])
        uuids = so.uuids_of({"uuids": asked}) if asked else None
        return controller.session_remove(uuids, view=view_of(request))

    @native
    async def catalogue_get(request):
        q = request.query
        return controller.session_catalogue(kind=q.get("type", ""), text=q.get("q", ""),
                                            limit=so.count_of(q.get("limit"), "limit", 500, 5000),
                                            view=view_of(request))

    @native
    async def sources_get(request):
        return controller.session_sources()

    @native
    async def sources_files(request):
        path = (await _body(request)).get("path")
        if not isinstance(path, str) or not path.strip():
            raise so.ObjectsError('A JSON object {"path": "<file under the open directory>"} is expected.')
        why = controller.session_load_file(path.strip())
        if why:
            return _error(400, why)
        return controller.session_sources()

    @native
    async def sources_etp(request):
        body = await _body(request)
        url = str(body.get("url") or "").strip()
        partition = str(body.get("partition") or "").strip()
        dataspaces = body.get("dataspaces") or []
        if not url or not isinstance(dataspaces, list) or not all(isinstance(d, str) for d in dataspaces):
            raise so.ObjectsError('A JSON object {"url", "partition", "dataspaces": ["<name>", …]} is expected.')
        creds = etp_credentials(request.headers)
        end = dict(getattr(state, "ui_etp_endpoint", None) or {})
        connected = bool(getattr(state, "etp_connected", False)) and end.get("url") == url
        if not connected:
            if not creds:
                return _error(401, "The store's credentials travel in the Authorization header: "
                                   "Bearer <token>, or Basic <base64 of user:password>.")
            res = controller.etp_connect({"url": url, "partition": partition, **creds})
            if asyncio.iscoroutine(res):
                await res
            if not getattr(state, "etp_connected", False):
                return _error(502, getattr(state, "etp_status", "") or f"No ETP session with {url}.")
        from trame_fespp_session.format import etp_dataspace_uri
        for name in dataspaces:
            uri = etp_dataspace_uri(name)
            if uri in (getattr(state, "ui_etp_loaded_dataspaces", None) or []):
                continue
            res = controller.etp_select({"dataspace": uri})
            if asyncio.iscoroutine(res):
                await res
            if uri not in (getattr(state, "ui_etp_loaded_dataspaces", None) or []):
                return _error(502, getattr(state, "etp_status", "") or f"The dataspace {name} was not loaded.")
        return controller.session_sources()

    register_route("GET", "/objects", objects_get)
    register_route("POST", "/objects", objects_post)
    register_route("PUT", "/objects", objects_put)
    register_route("DELETE", "/objects", objects_delete)
    register_route("GET", "/catalogue", catalogue_get)
    register_route("GET", "/sources", sources_get)
    register_route("POST", "/sources/files", sources_files)
    register_route("POST", "/sources/etp", sources_etp)
