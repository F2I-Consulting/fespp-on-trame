"""Tests unitaires pour fespp_on_trame.app.ui.drawer.config.tree_selection"""
import pytest
from fespp_on_trame.app.ui.drawer.config.tree_selection import get_item_props_js, SELECTABLE_TYPES


class TestGetItemPropsJs:
    def test_returns_string(self):
        assert isinstance(get_item_props_js("reservoir"), str)

    def test_reservoir_contains_property_types(self):
        js = get_item_props_js("reservoir")
        for t in SELECTABLE_TYPES["reservoir"]:
            assert t in js

    def test_surface_contains_surface_types(self):
        js = get_item_props_js("surface")
        for t in SELECTABLE_TYPES["surface"]:
            assert t in js

    def test_unknown_category_returns_empty_condition(self):
        js = get_item_props_js("unknown_category")
        # La condition doit être vide ou le résultat doit rester une fonction JS valide
        assert "selectable:" in js

    def test_output_is_js_arrow_function(self):
        js = get_item_props_js("reservoir")
        assert js.startswith("item =>")
