"""engine/diverging_table: the diverging map (blue negative, white zero, red
positive) over a property's TRUE range — the stretch of the symmetric map
the range covers, never a bound made up on the other side of zero."""
import pytest

pytest.importorskip("vtkmodules.vtkRenderingCore")

from fespp_on_trame.engine import diverging_table  # noqa: E402
from fespp_on_trame.engine.utils.color_palette import DIVERGING_PRESET  # noqa: E402

WHITE = 0.865       # the preset's middle grey-white
# ParaView's "Cool to Warm" as its presets file gives it, from -1 to 1: the presets are read by pvpython,
# not by this test's interpreter
COOL_TO_WARM = ("Diverging", [(-1.0, 0.23137254902, 0.298039215686, 0.752941176471), (0.0, WHITE, WHITE, WHITE),
                              (1.0, 0.705882352941, 0.0156862745098, 0.149019607843)])


@pytest.fixture(autouse=True)
def _the_preset(monkeypatch):
    monkeypatch.setitem(diverging_table._ramps, DIVERGING_PRESET, COOL_TO_WARM)


def _nodes(pts):
    return [pts[i:i + 4] for i in range(0, len(pts), 4)]


def test_a_range_of_positive_values_is_reds_only_over_its_own_bounds():
    pts, space = diverging_table.points(4.6e6, 8.1e6)
    nodes = _nodes(pts)
    assert space == "Diverging"
    assert [n[0] for n in nodes] == [4.6e6, 8.1e6]
    (_x0, r0, g0, b0), (_x1, r1, g1, b1) = nodes
    # both red, the least value the lighter one
    assert r0 > b0 and r1 > b1 and g0 > g1


def test_a_range_across_zero_is_white_at_zero():
    nodes = _nodes(diverging_table.points(-1.0, 3.0)[0])
    assert [n[0] for n in nodes] == [-1.0, 0.0, 3.0]
    assert nodes[1][1:] == pytest.approx([WHITE] * 3, abs=1e-3)
    # -1 a third of the way to the blue of -3: bluish, lighter than the full blue
    assert nodes[0][3] > nodes[0][1]
    # 3 the full red of the map laid from -3 to 3
    assert nodes[2][1:] == pytest.approx(diverging_table.ramp()[1][-1][1:], abs=1e-3)


def test_each_code_takes_the_colour_of_its_value():
    cols = diverging_table.colours([0.0, 3.0], 0.0, 3.0)
    assert cols[:3] == pytest.approx([WHITE] * 3, abs=1e-3)
    assert cols[3] > cols[5]        # 3: red
