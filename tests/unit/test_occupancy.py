"""app/scene/occupancy: who draws a grid in a view, decided in one place —
an extract or a formula's copy, else the isolate while needed and seen,
else the composite (slice 3 of the overhaul; 04-verification D7, N8)."""
from fespp_on_trame.app.scene.occupancy import (
    COMPOSITE, HIDDEN, ISOLATE, REPLACED, Occupancy)

G = "/data/_g"


class _Scene:
    def __init__(self, visible=(G,), other_domain=()):
        self.isolated = set()
        self._visible = set(visible)
        self._other = set(other_domain)

    def set_isolated(self, sel, on):
        (self.isolated.add if on else self.isolated.discard)(sel)

    def visible_selectors(self):
        return set(self._visible)

    def shown_selectors(self):
        return set(self._visible) - self._other


class _Iso:
    def __init__(self, needed):
        self.needed = needed
        self.calls = []

    def needs_isolation(self):
        return self.needed

    def show(self):
        self.calls.append("show")

    def hide_all(self):
        self.calls.append("hide")


def _occ(scene, iso=None, replaced=False):
    return Occupancy(lambda vid: scene, lambda vid, rp: iso, lambda vid, sel: replaced)


def test_an_extract_or_a_formula_copy_draws_the_grid_and_nothing_else_does():
    scene, iso = _Scene(), _Iso(needed=True)
    assert _occ(scene, iso, replaced=True).settle("view_1", G) == REPLACED
    assert G in scene.isolated and iso.calls == ["hide"]


def test_a_needed_isolate_draws_while_the_eye_is_open_and_hides_when_closed():
    scene, iso = _Scene(), _Iso(needed=True)
    assert _occ(scene, iso).settle("view_1", G) == ISOLATE
    assert G in scene.isolated and iso.calls == ["show"]
    closed = _Scene(visible=())
    iso2 = _Iso(needed=True)
    assert _occ(closed, iso2).settle("view_1", G) == HIDDEN
    assert G in closed.isolated and iso2.calls == ["hide"]


def test_slice_off_gives_the_grid_back_to_the_composite_and_never_paints_it_twice():
    """N8: an isolate no longer needed hides, the composite draws."""
    scene, iso = _Scene(), _Iso(needed=False)
    scene.isolated.add(G)
    assert _occ(scene, iso).settle("view_1", G) == COMPOSITE
    assert G not in scene.isolated and iso.calls == ["hide"]


def test_no_isolate_and_no_extract_is_the_composite():
    scene = _Scene()
    scene.isolated.add(G)
    assert _occ(scene).settle("view_1", G) == COMPOSITE
    assert G not in scene.isolated


def test_a_view_without_a_scene_decides_nothing():
    assert Occupancy(lambda v: None, lambda v, r: None, lambda v, s: False).settle("v", G) == ""


def test_a_grid_of_the_other_domain_keeps_its_eye_and_is_not_drawn():
    # a time grid in a view switched to depth (the PO, 28/10)
    scene, iso = _Scene(other_domain=(G,)), _Iso(needed=True)
    assert _occ(scene, iso).settle("view_1", G) == HIDDEN
    assert G in scene.isolated and iso.calls == ["hide"]
