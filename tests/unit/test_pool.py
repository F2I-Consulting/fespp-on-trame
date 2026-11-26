"""deploy/pool/fespp_pool: the records the template and the launcher share
— a ready session taken once, the oldest first, a dead one dropped, the
Apache map one line per live child."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "deploy" / "pool" / "fespp_pool.py"
# `alive` asks the kernel with os.kill(pid, 0): on Windows that call ENDS the
# process instead of probing it — the pool runs in the Linux image only
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="os.kill(pid, 0) is Linux's")


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setenv("FESPP_POOL_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("fespp_pool", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ensure_dirs()
    return mod


def _ready(pool, port, since, pid=None):
    rec = {"id": f"id-{port}", "port": port, "secret": "s", "pid": pid or os.getpid(), "since": since}
    pool.write_record(os.path.join(pool.READY_DIR, f"{port}.json"), rec)
    return rec


def test_the_oldest_ready_session_is_taken_once(pool):
    _ready(pool, 9002, since=20.0)
    _ready(pool, 9001, since=10.0)
    first = pool.take_ready()
    assert first["id"] == "id-9001" and first["taken"] > 0
    assert pool.counts() == {"ready": 1, "taken": 1}
    assert pool.take_ready()["id"] == "id-9002"
    assert pool.take_ready() is None


def test_a_dead_ready_session_is_skipped_and_dropped(pool):
    _ready(pool, 9001, since=10.0, pid=2 ** 22 + 12345)   # no such process
    _ready(pool, 9002, since=20.0)
    assert pool.take_ready()["id"] == "id-9002"
    assert pool.counts() == {"ready": 0, "taken": 1}


def test_prune_and_the_map(pool, tmp_path):
    _ready(pool, 9001, since=10.0)
    pool.take_ready()
    pool.write_record(os.path.join(pool.TAKEN_DIR, "gone.json"),
                      {"id": "gone", "port": 9009, "pid": 2 ** 22 + 12345})
    assert pool.prune_taken() == ["gone.json"]
    proxy = tmp_path / "proxy-mapping.txt"
    pool.write_mapping(str(proxy), "0.0.0.0", [("id-9001", 9001), ("id-9002", 9002)])
    assert proxy.read_text() == "id-9001 0.0.0.0:9001\nid-9002 0.0.0.0:9002\n"


def test_the_config_gives_the_plugin_and_the_ports(pool, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"configuration": {"host": "0.0.0.0", "port": 9000},\n'
                   ' // a comment, as wslink allows\n'
                   ' "resources": [{"host": "0.0.0.0", "port_range": [9001, 9500]}],\n'
                   ' "apps": {"trame": {"cmd": ["pvpython", "--fespp-plugin-path", "/x/Fespp.so"]}}}')
    c = pool.load_config(str(cfg))
    assert pool.cmd_option(c["apps"]["trame"]["cmd"], "--fespp-plugin-path") == "/x/Fespp.so"
    assert pool.cmd_option(c["apps"]["trame"]["cmd"], "--local-epc-file-path") is None
    assert c["resources"][0]["port_range"] == [9001, 9500]


def test_the_docs_page_reads_the_openapi_document_in_swagger_ui(pool):
    html = pool.docs_html("/fespp/paraview", "/fespp/logo.png")
    assert '"/fespp/paraview/openapi.json"' in html and "swagger-ui-bundle" in html
    assert 'href="/fespp/logo.png"' in html


def test_the_openapi_names_the_routes_and_the_document(pool):
    spec = pool.openapi("/fespp/paraview")
    assert spec["openapi"].startswith("3.0") and spec["servers"] == [{"url": "/fespp/paraview"}]
    assert set(spec["paths"]) >= {"/sessions", "/sessions/{id}", "/sessions/{id}/apply",
                                  "/sessions/{id}/state", "/pool"}
    groups = spec["components"]["schemas"]["Document"]["properties"]
    assert set(groups) >= {"sources", "session", "objects", "layout", "views", "reset"}
    assert spec["paths"]["/sessions"]["post"]["responses"]["201"]
    # the PO's manager reads the schema in the POST block: the groups said key
    # by key, examples to pick from, the view's place among them
    assert set(groups["sources"]["properties"]["etp"]["properties"]) == {"url", "partition", "dataspaces"}
    assert groups["views"]["items"]["properties"]["place"]["enum"] == ["right", "below"]
    examples = spec["paths"]["/sessions"]["post"]["requestBody"]["content"]["application/json"]["examples"]
    assert "adme_demo_volve" in examples and examples["reset"]["value"] == {"reset": True}
    # the page's own door, under its own server
    door = spec["paths"]["/"]
    assert door["servers"] == [{"url": "/fespp"}]
    assert {p["name"] for p in door["get"]["parameters"]} == {"epc", "etp", "dataspace", "partition", "uuid", "state"}
    assert pool.openapi("/paraview")["paths"]["/"]["servers"] == [{"url": "/"}]


def test_the_openapi_names_the_native_resources(pool):
    spec = pool.openapi("/fespp/paraview")
    paths = spec["paths"]
    assert set(paths["/sessions/{id}/objects"]) == {"get", "post", "put", "delete"}
    assert set(paths["/sessions/{id}/objects/{uuid}"]) == {"delete"}
    assert set(paths["/sessions/{id}/sources"]) == {"get"}
    assert set(paths["/sessions/{id}/catalogue"]) == {"get"}
    assert "wait" in {p["name"] for p in paths["/sessions/{id}/objects"]["post"]["parameters"]}
    files = paths["/sessions/{id}/sources/files"]["post"]["requestBody"]["content"]
    assert set(files) == {"application/json", "multipart/form-data"}
    etp = paths["/sessions/{id}/sources/etp"]["post"]
    assert etp["security"] == [{"bearer": []}, {"basic": []}] and "401" in etp["responses"]
    assert {"Sources", "Objects"} <= {t["name"] for t in spec["tags"]}
    # every schema a route names is there
    import json
    import re
    refs = set(re.findall(r'"#/components/schemas/(\w+)"', json.dumps(spec)))
    assert refs <= set(spec["components"]["schemas"]), refs - set(spec["components"]["schemas"])


def test_the_openapi_says_what_a_row_is_named_by(pool):
    views = pool.openapi("/paraview")["components"]["schemas"]["Document"]["properties"]["views"]
    keys = views["items"]["properties"]
    # a document that names a baseline by a uid must say the uid on its item
    assert "kinds" in keys["items"]["items"]["properties"]["uid"]["description"]
    assert "baseline" in keys["kinds"]["description"]
    assert "path" in keys["extracts"]["description"]


def test_the_openapi_offers_no_kind_that_is_gone(pool):
    views = pool.openapi("/paraview")["components"]["schemas"]["Document"]["properties"]["views"]
    keys = views["items"]["properties"]
    assert not {"distribution", "crossplot"} & set(keys["kind"]["enum"])
    assert not {"context", "options", "x", "ys"} & set(keys)


def test_the_host_page_teaches_the_view_as_it_is_called():
    # the page lives with the shared notes, which a public copy of the code leaves out
    path = _SRC.parents[2] / "doc" / "notes-partagees" / "host-demo.html"
    if not path.is_file():
        pytest.skip("no shared notes here")
    page = path.read_text(encoding="utf-8")
    assert '"kind": "compare"' in page and '"kind": "stats"' not in page
    assert '"items": [{"path": "uuid:' in page



def test_single_mode_hands_the_session_already_taken(pool, monkeypatch):
    _ready(pool, 9001, since=10.0)
    _ready(pool, 9002, since=20.0)
    monkeypatch.setenv("FESPP_POOL_SINGLE", "1")
    first, again = pool.session_to_hand()
    assert first["id"] == "id-9001" and again is False
    # the tab closed and opened again, a second tab: the same session
    second, again = pool.session_to_hand()
    assert second["id"] == "id-9001" and again is True
    assert pool.counts() == {"ready": 1, "taken": 1}


def test_single_mode_takes_a_new_one_once_the_session_has_ended(pool, monkeypatch):
    monkeypatch.setenv("FESPP_POOL_SINGLE", "1")
    pool.write_record(os.path.join(pool.TAKEN_DIR, "id-9001.json"),
                      {"id": "id-9001", "port": 9001, "pid": 2 ** 22 + 12345, "taken": 5.0})
    _ready(pool, 9002, since=20.0)
    rec, again = pool.session_to_hand()
    assert rec["id"] == "id-9002" and again is False


def test_without_single_mode_each_browser_gets_its_own(pool, monkeypatch):
    monkeypatch.delenv("FESPP_POOL_SINGLE", raising=False)
    _ready(pool, 9001, since=10.0)
    _ready(pool, 9002, since=20.0)
    assert [pool.session_to_hand()[0]["id"] for _ in range(2)] == ["id-9001", "id-9002"]
    monkeypatch.setenv("FESPP_POOL_SINGLE", "0")
    assert pool.single() is False
