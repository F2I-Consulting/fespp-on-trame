"""app/scene/displays: the off-composite displays of the 3D views, in one
registry walked by the vertical exaggeration, Represent By and the closing
of a view (slice 2 of the overhaul)."""
from fespp_on_trame.app.scene.displays import Displays


class _Disp:
    def __init__(self):
        self.Scale = [1.0, 1.0, 1.0]
        self.Representation = "Surface"


def _registry():
    logs = []
    return Displays(log=logs.append), logs


def test_the_exaggeration_reaches_every_display_that_follows_it():
    reg, _ = _registry()
    a, b, fixed = _Disp(), _Disp(), _Disp()
    seen = []
    reg.add("view_1", "extract:1", "extract", a)
    reg.add("view_2", "plane:goc", "contact_plane", b)
    reg.add("view_1", "label", "text", fixed, follows_z=False)
    reg.add("view_1", "isolate:/g", "isolate", None, zscale=seen.append)
    reg.set_zscale(3.0)
    assert a.Scale == [1.0, 1.0, 3.0] and b.Scale == [1.0, 1.0, 3.0]
    assert fixed.Scale == [1.0, 1.0, 1.0]
    assert seen == [3.0]


def test_represent_by_reaches_only_the_view_and_the_displays_that_follow_it():
    reg, _ = _registry()
    mine, other, overlay = _Disp(), _Disp(), _Disp()
    styled = []
    reg.add("view_1", "extract:1", "extract", mine, follows_style=True)
    reg.add("view_2", "extract:2", "extract", other, follows_style=True)
    reg.add("view_1", "selection_overlay", "selection", overlay)
    reg.add("view_1", "isolate:/g", "isolate", None, follows_style=True, style=styled.append)
    reg.set_style("view_1", "Wireframe")
    assert mine.Representation == "Wireframe"
    assert other.Representation == "Surface"
    assert overlay.Representation == "Surface"     # an overlay keeps its own look
    assert styled == ["Wireframe"]


def test_closing_a_view_puts_its_displays_away_and_forgets_them():
    reg, _ = _registry()
    closed = []
    reg.add("view_1", "a", "extract", _Disp(), close=lambda: closed.append("a"))
    reg.add("view_1", "b", "contact_plane", _Disp(), close=lambda: closed.append("b"))
    reg.add("view_2", "c", "extract", _Disp(), close=lambda: closed.append("c"))
    reg.close_view("view_1")
    assert sorted(closed) == ["a", "b"]
    assert reg.entries("view_1") == [] and len(reg.entries("view_2")) == 1


def test_a_close_hook_that_removes_its_own_entry_is_harmless():
    reg, _ = _registry()
    reg.add("view_1", "x", "extract", _Disp(), close=lambda: reg.remove("view_1", "x"))
    reg.close_view("view_1")
    assert reg.entries() == []


def test_a_failing_hook_is_said_and_the_walk_goes_on():
    reg, logs = _registry()
    ok = _Disp()

    def boom(_z):
        raise RuntimeError("gone")
    reg.add("view_1", "bad", "isolate", None, zscale=boom)
    reg.add("view_1", "good", "extract", ok)
    reg.set_zscale(2.0)
    assert ok.Scale == [1.0, 1.0, 2.0]
    assert any("bad" in line and "gone" in line for line in logs)
