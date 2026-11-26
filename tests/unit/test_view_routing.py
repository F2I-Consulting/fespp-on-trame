"""Which 3D view a bucket is routed to when the active panel is not one.

With a panel of another kind active — Compare, Statistics, the well-log —
the raw active id names an eye set and colour buckets no 3D view reads.
The coercion must then name the 3D view the user last worked in, not the
first one that happens to be open."""
from types import SimpleNamespace

from fespp_on_trame.engine import view_routing


def _state(active, last="", render=("view_1", "view_3")):
    return SimpleNamespace(
        fespp_active_panel_id=active,
        fespp_last_render_panel_id=last,
        fespp_render_panels=[{"id": r, "title": r} for r in render])


def test_an_active_3d_view_is_its_own_target():
    assert view_routing.resolve_active_render_panel(_state("view_3")) == "view_3"


def test_a_panel_of_another_kind_defers_to_the_view_last_worked_in():
    assert view_routing.resolve_active_render_panel(
        _state("view_2", last="view_3")) == "view_3"


def test_the_first_view_is_only_the_last_resort():
    # nothing remembered yet, or the remembered view has been closed
    assert view_routing.resolve_active_render_panel(_state("view_2")) == "view_1"
    assert view_routing.resolve_active_render_panel(
        _state("view_2", last="view_9")) == "view_1"


def test_no_3d_view_known_yet_leaves_the_id_alone():
    assert view_routing.resolve_active_render_panel(
        _state("view_2", last="view_3", render=())) == "view_2"


def _with_globe(last):
    return SimpleNamespace(
        fespp_last_render_panel_id=last,
        fespp_render_panels=[{"id": "view_1", "title": "3D view 1", "globe": False},
                             {"id": "view_2", "title": "Globe", "globe": True},
                             {"id": "view_4", "title": "3D view 2", "globe": False}])


def test_the_model_goes_with_the_3d_view_in_use():
    assert view_routing.model_view(_with_globe("view_4")) == "view_4"


def test_the_model_never_goes_to_the_globe():
    assert view_routing.model_view(_with_globe("view_2")) == "view_1"


def test_no_3d_view_no_view_for_the_model():
    state = SimpleNamespace(fespp_last_render_panel_id="view_2",
                            fespp_render_panels=[{"id": "view_2", "title": "Globe", "globe": True}])
    assert view_routing.model_view(state) == ""
    assert view_routing.model_view(SimpleNamespace()) == ""
