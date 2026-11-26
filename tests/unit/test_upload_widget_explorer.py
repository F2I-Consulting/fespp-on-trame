"""Tests for trame_fespp_upload.widgets: the OSDU upload elements carry the
dataspace explorer (the `osdu_explorer` prop and the `osdu_scan` /
`osdu_find` / `osdu_search` events), on `UploadOsdu` and on the
`UploadData` shell alike.

A name missing from `_attr_names` or `_event_names` is the one failure
trame keeps quiet about: the kwarg is dropped with a line on stdout and the
browser gets a widget with no such prop. The check runs on the element as
trame builds it (its rendered tag), on the built bundle, and on the package
version the served path is named after: `__trame_fespp_upload_<version>`
is the cache-busting the application relies on.
"""
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIDGET = ROOT / "widgets" / "upload"
sys.path.insert(0, str(WIDGET))

upload_data = pytest.importorskip("trame_fespp_upload.widgets.upload_data")

EXPLORER_PROP = "osdu_explorer"
EXPLORER_EVENTS = ("osdu_scan", "osdu_find", "osdu_search", "osdu_kinds")


def _stub_server():
    """Return the parts of a server an element touches while it renders: a
    state to register defaults in, a translator that leaves an expression
    as is, the client type, and the module hook the widget package calls."""
    class Translator:
        def translate_js_expression(self, state, expr):
            return expr

    state = types.SimpleNamespace(translator=Translator(), defaults={})
    state.setdefault = lambda name, value: state.defaults.setdefault(name, value)
    return types.SimpleNamespace(client_type="vue3", state=state, controller=None,
                                 enable_module=lambda module: None)


@pytest.mark.parametrize("cls", [upload_data.UploadOsdu, upload_data.UploadData])
def test_the_elements_carry_the_explorer_prop_and_events(cls):
    el = cls(trame_server=_stub_server())
    assert EXPLORER_PROP in el._attr_names
    for event in EXPLORER_EVENTS:
        assert event in el._event_names
    # the ETP dataspace contract stays in place beside the explorer
    assert "etp_dataspaces" in el._attr_names and "etp_select" in el._event_names
    # the step of a connection in progress, on the Connect button (13/10)
    assert "etp_step" in el._attr_names


@pytest.mark.parametrize("cls,tag", [
    (upload_data.UploadOsdu, "upload-osdu"),
    (upload_data.UploadData, "upload-data"),
])
def test_the_rendered_tag_binds_them(cls, tag):
    """The names go all the way to the tag trame writes: the prop bound to
    its state variable, the events wired to the controller triggers."""
    el = cls(trame_server=_stub_server(),
             osdu_explorer=("osdu_explorer", {}),
             osdu_scan="trigger('osdu_scan')",
             osdu_find="trigger('osdu_find', [$event])",
             osdu_search="trigger('osdu_search', [$event])",
             osdu_kinds="trigger('osdu_kinds', [$event])")
    html = el.html
    assert html.startswith(f"<{tag} ")
    assert ':osdu-explorer="osdu_explorer"' in html
    assert "@osdu-scan=\"trigger('osdu_scan')\"" in html
    assert "@osdu-find=\"trigger('osdu_find', [$event])\"" in html
    assert "@osdu-search=\"trigger('osdu_search', [$event])\"" in html
    assert "@osdu-kinds=\"trigger('osdu_kinds', [$event])\"" in html


def test_the_widget_version_is_past_the_served_build():
    """The package version stays at or above 0.4.0: the served path
    `__trame_fespp_upload_<version>` is what makes a browser fetch the
    explorer's bundle instead of a cached one without it."""
    text = (WIDGET / "trame_fespp_upload" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text)
    assert version, "no __version__ in trame_fespp_upload/__init__.py"
    assert tuple(int(v) for v in version.groups()) >= (0, 4, 0)


def test_the_bundle_carries_the_explorer():
    """The built file is what the browser runs: the explorer's own hook, the
    search box's hook and its "ranked" header tag, the find event it relays
    and the "published" badge of a result the catalogue also knows must be
    in it, and a second search box ("Search the catalogue") must not: the
    catalogue is merged into the one box's results, since two boxes read as
    two searches. A failure either way means the bundle is older than its
    source."""
    bundle = WIDGET / "trame_fespp_upload" / "module" / "serve" / "trame_fespp_upload.umd.js"
    if not bundle.exists():
        pytest.skip("the widget is not built here (npm run build in vue-components)")
    text = bundle.read_text(encoding="utf-8")
    assert "data-fp-osdu-explorer" in text
    assert "data-fp-osdu-search" in text
    assert "ranked" in text
    assert "osdu-find" in text
    assert "data-fp-osdu-published" in text
    # the Props count that reads the property kinds over ETP (2026-10-10)
    assert "data-fp-osdu-kinds" in text and "osdu-kinds" in text
    assert "published" in text
    assert "data-fp-osdu-catalogue-only" in text
    assert "Search the catalogue" not in text
    assert "data-fp-osdu-query" not in text
    # each row's scan state: the hook on the row, the line / bar over the
    # fact columns, the green dot of a row the scan has read
    assert "data-fp-osdu-scan-state" in text
    assert "data-fp-osdu-scanned" in text
    assert "data-fp-osdu-scan-bar" in text


def test_the_clicked_load_becomes_a_bar_and_a_read_dataspace_says_loaded():
    """A dataspace takes a while to reach the tree: the clicked Load becomes
    a running bar (its hook, its class, its word) so the click visibly
    registers — indeterminate, the plugin reads a dataspace in one call;
    a dataspace read in this session wears a green Loaded in place of Load,
    which reads it again when clicked (12/10, the PO's remark: the row
    turned green but the Load button stayed blue)."""
    bundle = WIDGET / "trame_fespp_upload" / "module" / "serve" / "trame_fespp_upload.umd.js"
    if not bundle.exists():
        pytest.skip("the widget is not built here (npm run build in vue-components)")
    text = bundle.read_text(encoding="utf-8")
    assert "data-fp-osdu-loading" in text
    assert "fp-progress" in text and "Loading…" in text
    assert "uox-loaded-btn" in text and '"Loaded"' in text
    assert "read in this session; click to read it again" in text
    assert "uox-spin" not in text


def test_the_loading_bar_counts_the_seconds_and_the_form_is_remembered():
    """13/10, the PO's manager on the public site: a Load of demo/Volve
    looked dead for 41 s (the server answers nothing during the plugin's
    read), and the connection form had to be typed again at every visit.
    The bar carries a count of seconds the page keeps by itself and, for a
    dataspace read before, fills at the pace of that read (`load_seconds`
    on the row); the form keeps the server, the partition, the method and
    the user in the browser's localStorage, never the token."""
    bundle = WIDGET / "trame_fespp_upload" / "module" / "serve" / "trame_fespp_upload.umd.js"
    if not bundle.exists():
        pytest.skip("the widget is not built here (npm run build in vue-components)")
    text = bundle.read_text(encoding="utf-8")
    assert "data-fp-osdu-load-elapsed" in text
    assert "data-fp-osdu-load-fill" in text
    assert "load_seconds" in text
    assert "fespp.osdu.connection" in text
    assert "data-fp-osdu-remembered" in text
    # the remembered fields, and only those: no token, no password
    assert '["url","partition","auth","user"]' in text

