"""The native Sources and Objects routes: app/features/session_api's
gestures on a fake session (state, controllers, views, tree), and the
session's own routes (engine/io/session_endpoint) answering over HTTP."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from fespp_on_trame.app.features import session_api
from fespp_on_trame.engine.io import session_endpoint

U1 = "0eb751ef-219b-4e1f-8e4e-06187f16e61a"
U2 = "5af3641f-5a55-43a9-bb31-d7f81ab0ba70"
GONE = "11111111-2222-3333-4444-555555555555"
# FESPP's tree: a grid drawn as its SolidColor leaf, in folders of its uuid; a property beside it
GRID = f"/data/_gridfolder_{U1}"
A = f"{GRID}/_propsfolder_{U1}/_{U1}"
B = f"{GRID}/_propsfolder_{U1}/_{U2}"


class FakeState(dict):
    """trame's state: attributes and items alike, None for what was never set."""

    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __missing__(self, k):
        return None

    def flush(self):
        pass


class FakeController:
    """trame's controller: functions set by name, called by attribute."""

    def __init__(self):
        self.__dict__["fns"] = {}

    def set(self, name):
        def deco(fn):
            self.fns[name] = fn
            return fn
        return deco

    def __getattr__(self, name):
        try:
            return self.fns[name]
        except KeyError:
            raise AttributeError(name) from None


class FakeTree:
    def __init__(self, rows):
        self.rows = rows  # path -> (type, title)

    def find_node_id(self, path):
        return path if path in self.rows else None

    def find_type(self, nid):
        return self.rows[nid][0]

    def find_title(self, nid):
        return self.rows[nid][1]

    def iter_nodes(self):
        return [(path, []) for path in self.rows]

    def find_path(self, nid):
        return nid


class FakeViews:
    def __init__(self):
        self.kinds = {"view_1": "render", "stats_1": "compare", "view_2": "render"}

    def view_ids(self):
        return list(self.kinds)

    def kind_of(self, vid):
        return self.kinds[vid]

    def add_view(self, direction=None, kind="render", reference_panel_id=None):
        vid = f"{kind}_{len(self.kinds) + 1}"
        self.kinds[vid] = kind
        return vid


class FakeHost:
    def __init__(self, state):
        self.state = state
        self.paths = {U1: A, U2: B}

    def path_by_uuid(self, uuid):
        return self.paths.get(uuid)

    def loaded_files(self):
        return list(self.state.ui_loaded_files or [])

    def etp_state(self):
        return {"connected": bool(self.state.etp_connected),
                "loaded": list(self.state.ui_etp_loaded_dataspaces or [])}

    def load_file(self, path):
        if path != "explorer/demo.epc":
            self.state.load_error = f"{path}: no such file on the server."
            return False
        self.state.ui_loaded_files = [{"name": "demo.epc", "size_mb": 0.1, "objects": 2, "failed": False}]
        return True


@pytest.fixture
def server():
    state, ctl = FakeState(), FakeController()
    srv = SimpleNamespace(state=state, controller=ctl, calls=[], slow=False,
                          context=SimpleNamespace(multi_view=FakeViews(),
                                                  tree=FakeTree({GRID: ("Grid2dRepresentation", "Top"),
                                                                 A: ("Grid2dRepresentation", "SolidColor"),
                                                                 B: ("ContinuousProperty", "Depth")})))

    @ctl.set("session_select")
    def session_select(paths, replace=False):
        srv.calls.append(("select", list(paths), replace))
        state.selected_paths = list(paths)
        # what is read is loaded at once, unless the test holds the reads back
        if not srv.slow:
            state.ui_loaded_rep_paths = list(paths)

    @ctl.set("on_eye_changed")
    def on_eye_changed(vid, eyes):
        srv.calls.append(("eyes", vid, list(eyes)))

    @ctl.set("etp_connect")
    async def etp_connect(payload):
        srv.calls.append(("connect", dict(payload)))
        state.etp_connected = payload.get("password") == "bar" or payload.get("token") == "t0k"
        if state.etp_connected:
            state.ui_etp_endpoint = {"url": payload["url"], "partition": payload["partition"]}
        else:
            state.etp_status = "Connection failed (timeout or refused) — check URL, data partition and token."

    @ctl.set("etp_select")
    async def etp_select(payload):
        srv.calls.append(("select_dataspace", payload["dataspace"]))
        state.ui_etp_loaded_dataspaces = list(state.ui_etp_loaded_dataspaces or []) + [payload["dataspace"]]

    session_api._register_native(srv, FakeHost(state))
    return srv


def rows(answer):
    return [(r["uuid"], r["shown"]) for r in answer["objects"]]


# ---------------------------------------------------------------- the gestures
def test_show_adds_to_what_is_read_and_shown(server):
    server.state.selected_paths = [A]
    server.state.visible_paths__view_1 = [A]
    out = server.controller.session_show([U2])
    assert server.state.selected_paths == [A, B] and server.state.visible_paths__view_1 == [A, B]
    assert out == {"view": "view_1", "missing": [], "loading": False, "objects": [
        {"uuid": U1, "type": "Grid2dRepresentation", "title": "Top", "shown": True, "loaded": True},
        {"uuid": U2, "type": "ContinuousProperty", "title": "Depth", "shown": True, "loaded": True}]}


def test_replace_unreads_the_rest_and_no_view_keeps_an_eye_on_it(server):
    server.state.selected_paths = [A]
    server.state.visible_paths__view_1 = [A]
    server.state.visible_paths__view_2 = [A]
    out = server.controller.session_show([U2], replace=True)
    assert server.state.selected_paths == [B]
    assert server.state.visible_paths__view_1 == [B] and server.state.visible_paths__view_2 == []
    assert ("eyes", "view_2", []) in server.calls and rows(out) == [(U2, True)]


def test_read_only_leaves_the_eyes_and_a_uuid_not_in_the_data_is_said(server):
    out = server.controller.session_show([U1, GONE], show=False)
    assert rows(out) == [(U1, False)] and out["missing"] == [GONE]
    assert not any(c[0] == "eyes" for c in server.calls)


def test_another_3d_view_by_its_id(server):
    out = server.controller.session_show([U1], view="view_2")
    assert out["view"] == "view_2" and server.state.visible_paths__view_2 == [A]
    assert server.state.visible_paths__view_1 is None


def test_a_session_no_browser_attached_to_yet_opens_its_3d_view(server):
    views = server.context.multi_view
    views.kinds = {}
    assert server.controller.session_objects() == {"view": None, "objects": [], "missing": [], "loading": False}
    out = server.controller.session_show([U1], show=False)  # read only: no view needed
    assert out["view"] is None and views.kinds == {}
    out = server.controller.session_show([U2])
    assert out["view"] == "render_1" and views.kinds == {"render_1": "render"}
    assert server.state.visible_paths__render_1 == [B] and rows(out) == [(U1, False), (U2, True)]


def test_remove_one_then_all(server):
    server.state.selected_paths = [A, B]
    server.state.visible_paths__view_1 = [A, B]
    out = server.controller.session_remove([U2, GONE])
    assert rows(out) == [(U1, True)] and out["missing"] == [GONE]
    out = server.controller.session_remove(None)
    assert out["objects"] == [] and server.state.visible_paths__view_1 == []


def test_sources_say_the_files_and_the_store(server):
    assert server.controller.session_sources() == {"files": [], "etp": None}
    assert server.controller.session_load_file("explorer/demo.epc") is None
    assert server.controller.session_load_file("nowhere.epc") == "nowhere.epc: no such file on the server."
    server.state.ui_etp_endpoint = {"url": "ws://h:9002/", "partition": "osdu"}
    server.state.etp_connected = True
    server.state.ui_etp_loaded_dataspaces = ["eml:///dataspace('demo/Drogon')"]
    assert server.controller.session_sources() == {
        "files": [{"name": "demo.epc", "size_mb": 0.1, "failed": False}],
        "etp": {"url": "ws://h:9002/", "partition": "osdu", "connected": True,
                "dataspaces": ["eml:///dataspace('demo/Drogon')"], "available": []}}


# ---------------------------------------------------------------- the routes
def test_basic_and_bearer_credentials_are_read_off_the_header():
    basic = "Basic " + base64.b64encode(b"foo:b:ar").decode()
    assert session_endpoint.etp_credentials({"Authorization": basic}) == {
        "auth": "basic", "user": "foo", "password": "b:ar"}
    assert session_endpoint.etp_credentials({"Authorization": "Bearer t0k"}) == {"token": "t0k"}
    for header in ("Basic not-base64!", "Basic " + base64.b64encode(b"nocolon").decode(), "Token x", ""):
        assert session_endpoint.etp_credentials({"Authorization": header}) == {}
    assert session_endpoint.etp_credentials(None) == {}


def http(server, method, path, **kw):
    """One request to the session's own routes, on a test server."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    session_endpoint.register(server)

    async def go():
        async with TestClient(TestServer(web.Application())) as client:
            r = await client.request(method, path, **kw)
            return r.status, await r.json()
    return asyncio.run(go())


def test_the_object_routes(server):
    status, out = http(server, "POST", "/objects", json={"uuids": [U1, f"uuid:{U2}"]})
    assert status == 200 and rows(out) == [(U1, True), (U2, True)]
    status, out = http(server, "DELETE", f"/objects?uuid={U1}")
    assert status == 200 and rows(out) == [(U2, True)]
    status, out = http(server, "PUT", "/objects", json={"uuids": [U1], "show": False})
    assert status == 200 and rows(out) == [(U1, False)]
    status, out = http(server, "GET", "/objects?view=view_2")
    assert status == 200 and out["view"] == "view_2"


def test_the_object_routes_refuse_in_words(server):
    status, out = http(server, "POST", "/objects", json={"uuid": U1})
    assert status == 400 and "uuids" in out["error"]
    status, out = http(server, "GET", "/objects?view=stats_1")
    assert status == 400 and "No 3D view 'stats_1'" in out["error"]
    status, out = http(server, "POST", "/objects", data="not json", headers={"Content-Type": "application/json"})
    assert status == 400 and "JSON" in out["error"]


def test_a_server_file(server):
    status, out = http(server, "POST", "/sources/files", json={"path": "explorer/demo.epc"})
    assert status == 200 and out["files"][0]["name"] == "demo.epc"
    status, out = http(server, "POST", "/sources/files", json={"path": "nowhere.epc"})
    assert status == 400 and "no such file" in out["error"]


def test_an_etp_store_with_basic_credentials(server):
    body = {"url": "ws://h:9002/", "partition": "osdu", "dataspaces": ["demo/Drogon"]}
    status, out = http(server, "POST", "/sources/etp", json=body)
    assert status == 401 and "Authorization" in out["error"]
    wrong = "Basic " + base64.b64encode(b"foo:nope").decode()
    status, out = http(server, "POST", "/sources/etp", json=body, headers={"Authorization": wrong})
    assert status == 502 and "Connection failed" in out["error"]
    right = "Basic " + base64.b64encode(b"foo:bar").decode()
    status, out = http(server, "POST", "/sources/etp", json=body, headers={"Authorization": right})
    assert status == 200 and out["etp"]["dataspaces"] == ["eml:///dataspace('demo/Drogon')"]
    assert ("connect", {"url": "ws://h:9002/", "partition": "osdu", "auth": "basic", "user": "foo",
                        "password": "bar"}) in server.calls
    # connected to that store, a dataspace loaded already: nothing asked again
    before = len(server.calls)
    status, out = http(server, "POST", "/sources/etp", json=body)
    assert status == 200 and len(server.calls) == before


# ---------------------------------------------------------------- loaded, the catalogue, the store's list
def test_an_object_asked_for_is_not_loaded_until_its_read_ends(server):
    server.slow = True
    server.state.ui_load_progress = {"running": True}
    out = server.controller.session_show([U1])
    assert out["loading"] is True and [r["loaded"] for r in out["objects"]] == [False]
    server.state.ui_load_progress = {"running": False}
    server.state.ui_loaded_rep_paths = [A]
    out = server.controller.session_objects()
    assert out["loading"] is False and [r["loaded"] for r in out["objects"]] == [True]


def test_a_show_waits_for_its_reads_when_asked(server):
    server.slow = True
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    session_endpoint.register(server)

    async def go():
        async with TestClient(TestServer(web.Application())) as client:
            # the read ends half a second after the request
            async def later():
                await asyncio.sleep(0.5)
                server.state.ui_loaded_rep_paths = [A]
            pending = asyncio.ensure_future(later())
            r = await client.post("/objects?wait=5", json={"uuids": [U1, GONE]})
            await pending
            return r.status, await r.json()
    status, out = asyncio.run(go())
    assert status == 200 and [r["loaded"] for r in out["objects"]] == [True] and out["missing"] == [GONE]
    # not waited for: answered at once, still loading
    server.state.ui_loaded_rep_paths = []
    status, out = http(server, "POST", "/objects", json={"uuids": [U2]})
    assert status == 200 and [r["loaded"] for r in out["objects"]] == [False, False]
    status, out = http(server, "POST", "/objects?wait=999", json={"uuids": [U2]})
    assert status == 400 and "wait" in out["error"]


def test_the_catalogue_lists_every_object_read_or_not(server):
    server.state.selected_paths = [A]
    server.state.visible_paths__view_1 = [A]
    out = server.controller.session_catalogue()
    assert out["total"] == 2 and out["truncated"] is False
    assert out["objects"] == [
        {"uuid": U1, "type": "Grid2dRepresentation", "title": "Top", "read": True, "shown": True},
        {"uuid": U2, "type": "ContinuousProperty", "title": "Depth", "read": False, "shown": False}]
    status, out = http(server, "GET", "/catalogue?type=continuousproperty")
    assert status == 200 and [r["uuid"] for r in out["objects"]] == [U2]
    status, out = http(server, "GET", "/catalogue?q=TO&limit=0")
    assert status == 200 and out["objects"] == [] and out["total"] == 1 and out["truncated"] is True
    status, out = http(server, "GET", "/catalogue?limit=many")
    assert status == 400 and "limit" in out["error"]


def test_the_store_says_the_dataspaces_it_lists(server):
    server.state.ui_etp_endpoint = {"url": "ws://h:9002/", "partition": "osdu"}
    server.state.etp_connected = True
    server.state.etp_dataspaces = ["eml:///dataspace('demo/Drogon')", "eml:///dataspace('demo/Volve')"]
    assert server.controller.session_sources()["etp"]["available"] == server.state.etp_dataspaces
    server.state.etp_connected = False
    assert server.controller.session_sources()["etp"]["available"] == []
