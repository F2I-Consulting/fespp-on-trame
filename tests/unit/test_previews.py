"""app/core/previews: the features not offered yet (the PO, 18/10) are shown
only when their switch is "1"; the toolbar drops a switched-off card."""
import importlib

import pytest

from fespp_on_trame.app.core import previews


def test_a_preview_shows_only_with_its_switch(monkeypatch):
    monkeypatch.delenv("FESPP_VOLUMETRICS", raising=False)
    monkeypatch.delenv("FESPP_ASSISTANT", raising=False)
    assert previews.offered("tree") and previews.offered("colormap")
    assert not previews.offered("volumetrics") and not previews.offered("assistant")
    monkeypatch.setenv("FESPP_VOLUMETRICS", "true")
    assert not previews.offered("volumetrics")
    monkeypatch.setenv("FESPP_VOLUMETRICS", " 1 ")
    assert previews.offered("volumetrics")


def test_the_toolbar_drops_a_card_whose_switch_is_off(monkeypatch):
    # tools_config imports every widget package it builds a card from
    tools_config = pytest.importorskip("fespp_on_trame.app.views.tools_config")
    try:
        monkeypatch.delenv("FESPP_VOLUMETRICS", raising=False)
        keys = [t["key"] for t in importlib.reload(tools_config).TOOLS]
        assert "volumetrics" not in keys and "colormap" in keys
        monkeypatch.setenv("FESPP_VOLUMETRICS", "1")
        keys = [t["key"] for t in importlib.reload(tools_config).TOOLS]
        assert "volumetrics" in keys
    finally:
        monkeypatch.undo()
        importlib.reload(tools_config)
