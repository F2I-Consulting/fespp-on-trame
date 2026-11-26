"""widgets/title3dview: the HAND and the MOUSE of a 3D view's title bar.

The hand moves the scene; the mouse reads what is under the pointer and
holds the scene still. The element carries the `cursor` prop and the
`set-cursor` event (a name missing from `_attr_names` or `_event_names` is
dropped by trame with a line on stdout, and the browser gets a strip with
no such prop), and the built bundle carries both buttons. The cursor
position is not a toolbar mode: the toolbar's modes are pick and frustum."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIDGET = ROOT / "widgets" / "title3dview"
sys.path.insert(0, str(WIDGET))

title3dview = pytest.importorskip("trame_fespp_title3dview.widgets.title3dview")


def test_the_element_carries_the_pointer_prop_and_event():
    src = Path(title3dview.__file__).read_text(encoding="utf-8")
    assert '"cursor"' in src
    assert '("set_cursor", "set-cursor")' in src


def test_the_bundle_carries_the_hand_and_the_mouse():
    bundle = WIDGET / "trame_fespp_title3dview" / "module" / "serve" / "trame_fespp_title3dview.umd.js"
    if not bundle.exists():
        pytest.skip("the widget is not built here (npm run build in vue-components)")
    text = bundle.read_text(encoding="utf-8")
    assert "data-t3-hand" in text and "data-t3-mouse" in text
    assert "fespp-view-hand" in text and "fespp-view-mouse" in text
    assert "set-cursor" in text


def test_the_cursor_is_no_longer_a_toolbar_mode():
    # tools_config imports every widget package it builds a card from
    for w in sorted((ROOT / "widgets").iterdir()):
        if w.is_dir() and str(w) not in sys.path:
            sys.path.append(str(w))
    tools_config = pytest.importorskip("fespp_on_trame.app.views.tools_config")
    MODE_TOOLS = tools_config.MODE_TOOLS
    assert [m["key"] for m in MODE_TOOLS] == ["pick", "frustum"]
