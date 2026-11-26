"""A call the BROWSER makes to the server must be relative to the page.

The application can be served under a prefix (``TRAME_URL_PREFIX=/fespp``
behind a reverse proxy). The container's Apache then routes
``^/fespp/api/(sid)/(rest)`` to the session and nothing else, so an absolute
``/api/{sid}/upload`` leaves the prefix and the reverse proxy hands it to
whatever else it serves: the import fails with an authentication error or
lands on another site's page. That failure is INVISIBLE to the browser
suite, which drives the application without a prefix.

So the rule is checked here, on the source: a fetch or an XMLHttpRequest in
a widget takes a URL resolved against ``window.location``, never a literal
starting with ``/``.
"""
import re
from pathlib import Path

import pytest

WIDGETS = Path(__file__).resolve().parents[2] / "widgets"

# the call itself, and the literal that must not be its target
_CALL = re.compile(r"\b(?:fetch|\.open)\s*\(\s*([^)]*)", re.MULTILINE)
_ABSOLUTE = re.compile(r"""["'`]/[a-zA-Z]""")


def _sources():
    for root in sorted(WIDGETS.glob("*/vue-components/src")):
        for path in sorted(root.rglob("*")):
            if path.suffix in (".vue", ".js") and "node_modules" not in path.parts:
                yield path
    for path in sorted((WIDGETS / "_shared").rglob("*")):
        if path.suffix in (".vue", ".js") and "node_modules" not in path.parts:
            yield path


def test_no_browser_call_targets_an_absolute_path():
    offenders = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for match in _CALL.finditer(text):
            args = match.group(1)
            if _ABSOLUTE.search(args):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(WIDGETS)}:{line}  {args.strip()[:70]}")
    assert not offenders, (
        "a browser call must resolve its URL against window.location, or the "
        "prefix the application is served under is lost:\n  "
        + "\n  ".join(offenders))


def test_the_upload_widget_resolves_against_the_page():
    """The one call of the set, named: the rule above only proves that no
    literal is passed; this proves the resolution is actually done."""
    src = (WIDGETS / "upload" / "vue-components" / "src" / "components"
           / "UploadFile.vue").read_text(encoding="utf-8")
    assert "new URL(" in src and "window.location" in src, (
        "the upload endpoint no longer resolves against the page: served "
        "under a prefix, the import would leave it")


@pytest.mark.parametrize("page,expected", [
    ("https://host/fespp/index.html", "https://host/fespp/api/S/upload"),
    ("https://host/fespp/", "https://host/fespp/api/S/upload"),
    ("http://localhost:8095/index.html", "http://localhost:8095/api/S/upload"),
])
def test_what_that_resolution_gives(page, expected):
    """The three cases that matter, computed the way a browser does."""
    from urllib.parse import urljoin

    assert urljoin(page, "api/S/upload") == expected
