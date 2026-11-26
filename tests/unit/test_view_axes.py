"""engine/view_axes: one rule for the realization a view shows."""
from fespp_on_trame.engine import realization_dispatch, view_axes


class _State:
    def __init__(self, by_view=None):
        self.ui_active_realization_by_array_by_view = by_view or {}


def test_the_view_s_choice_then_the_first_available(monkeypatch):
    monkeypatch.setattr(realization_dispatch, "available_realization_indices",
                        lambda tree, path: [3, 5, 8])
    st = _State({"v1": {"/poro": 5}})
    assert view_axes.real_for(st, None, "v1", "/poro") == 5
    assert view_axes.real_for(st, None, "v2", "/poro") == 3      # no choice: the first
    assert view_axes.real_for(st, None, "", "/poro") == 3        # no view: the first


def test_a_single_realization_property_has_none(monkeypatch):
    monkeypatch.setattr(realization_dispatch, "available_realization_indices",
                        lambda tree, path: [])
    assert view_axes.real_for(_State(), None, "v1", "/facies") is None
