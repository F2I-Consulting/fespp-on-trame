"""Tests unitaires pour fespp_on_trame.app.ui.config.tree_icons"""
import pytest
from fespp_on_trame.app.ui.config.tree_icons import get_icon_for_type, TREE_ICONS


class TestGetIconForType:
    def test_exact_match_returns_icon(self):
        for node_type in TREE_ICONS:
            assert get_icon_for_type(node_type) == TREE_ICONS[node_type]

    def test_unknown_type_returns_default(self):
        result = get_icon_for_type("UnknownXYZ123")
        assert result == "mdi-folder"

    def test_realization_icon(self):
        assert get_icon_for_type("Realization") == "mdi-layers-triple"

    def test_timeseries_icon(self):
        assert get_icon_for_type("TimeSeries") == "mdi-timeline-clock"

    def test_empty_string_returns_any_icon(self):
        # "" est contenu dans toute chaîne → la recherche partielle matche le premier type connu.
        # Ce test documente le comportement actuel (pas un fallback "mdi-folder").
        result = get_icon_for_type("")
        assert isinstance(result, str)
        assert result.startswith("mdi-")
