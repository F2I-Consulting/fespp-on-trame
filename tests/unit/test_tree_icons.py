"""The icon NAME a tree node kind resolves to (fespp_on_trame.app.ui.tree_icons).

Python sends a name and the widget draws it: ``fespp-*`` is a drawing of the
application's own set, ``mdi-*`` a Material glyph the host resolves. The
drawing checks are the ones that matter: a ``fespp-`` name with no drawing
behind it reaches the browser as the "unknown" mark, which only the browser
suite would otherwise notice.
"""
import re
from pathlib import Path

from fespp_on_trame.app.ui.tree_icons import (
    FALLBACK_ICON,
    TREE_ICONS,
    get_icon_for_type,
    get_primary_icon,
)

ICON_MODULE = (Path(__file__).resolve().parents[2]
               / "widgets" / "_shared" / "icons" / "fespp-icons.js")


def _drawings():
    """The keys of FESPP_ICONS, read off the module (one entry per line,
    ``  someName: { parts: [``)."""
    text = ICON_MODULE.read_text(encoding="utf-8")
    return set(re.findall(r"^  (\w+): \{ parts:", text, re.MULTILINE))


def _kebab(name):
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", name).lower()


class TestGetIconForType:
    def test_exact_match_returns_icon(self):
        for node_type in TREE_ICONS:
            assert get_icon_for_type(node_type) == TREE_ICONS[node_type]

    def test_unknown_type_returns_the_unknown_mark(self):
        # not a folder glyph, which would quietly claim the row IS a folder
        assert get_icon_for_type("UnknownXYZ123") == FALLBACK_ICON

    def test_realization_falls_back_to_the_multi_realization_drawing(self):
        # "Realization" has no entry; the substring pass finds MultiRealization
        assert get_icon_for_type("Realization") == "fespp-multi-realization"

    def test_timeseries_icon(self):
        assert get_icon_for_type("TimeSeries") == "fespp-time-series"

    def test_no_type_returns_the_unknown_mark(self):
        assert get_icon_for_type("") == FALLBACK_ICON
        assert get_icon_for_type(None) == FALLBACK_ICON

    def test_synthetic_leaf_wears_the_underlying_property_icon(self):
        assert get_primary_icon("TimeSeries", "ContinuousProperty") == "fespp-property-continuous"
        assert get_primary_icon("TimeSeries", None) == "fespp-time-series"


class TestNamesResolveToADrawing:
    def test_every_name_is_one_of_the_two_vocabularies(self):
        for node_type, icon in TREE_ICONS.items():
            assert icon.startswith(("fespp-", "mdi-")), (node_type, icon)

    def test_every_fespp_name_has_a_drawing(self):
        drawings = _drawings()
        assert len(drawings) > 20, "the icon module was not parsed"
        by_kebab = {_kebab(k): k for k in drawings}
        missing = sorted(
            f"{node_type} -> {icon}"
            for node_type, icon in TREE_ICONS.items()
            if icon.startswith("fespp-") and icon[len("fespp-"):] not in by_kebab
        )
        assert not missing, "no drawing behind these names: " + ", ".join(missing)

    def test_the_fallback_has_a_drawing(self):
        assert FALLBACK_ICON[len("fespp-"):] in {_kebab(k) for k in _drawings()}


class TestViewToolbarNames:
    """The per-view toolbar sends the same kind of name (tools_config)."""

    def test_every_fespp_tool_icon_has_a_drawing(self):
        from fespp_on_trame.app.views import tools_config

        text = Path(tools_config.__file__).read_text(encoding="utf-8")
        names = set(re.findall(r'"icon":\s*"(fespp-[\w-]+)"', text))
        assert names, "no tool of the set: the toolbar lost its drawings"
        by_kebab = {_kebab(k) for k in _drawings()}
        missing = sorted(n for n in names if n[len("fespp-"):] not in by_kebab)
        assert not missing, "no drawing behind these tool icons: " + ", ".join(missing)
