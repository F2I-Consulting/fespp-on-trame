"""engine/luts: a view's colour table keeps the opacity mapping on only while
it draws something translucent — the reader turns it on for any property a
file gives opacities, even all at 1, and VTK then draws the grid in its
translucent passes (Volve's grid: a frame 5 times slower on the processor)."""
from types import SimpleNamespace

from fespp_on_trame.engine import categorical_palette
from fespp_on_trame.engine import luts

FLAT = [0.0, 1.0, 0.5, 0.0, 1.0, 1.0, 0.5, 0.0]
RAMP = [0.0, 0.0, 0.5, 0.0, 1.0, 1.0, 0.5, 0.0]


def test_a_flat_curve_is_opaque_a_dip_is_not():
    assert luts.draws_translucent(None, FLAT) is False
    assert luts.draws_translucent(None, RAMP) is True
    assert luts.draws_translucent(None, [0.0, 1.0, 0.5, 0.0, 5.0, 0.4, 0.5, 0.0, 9.0, 1.0, 0.5, 0.0]) is True
    assert luts.draws_translucent(None, []) is False


def test_an_indexed_table_reads_its_codes_opacities():
    assert luts.draws_translucent([1.0, 1.0, 1.0], RAMP) is False
    assert luts.draws_translucent([1.0, 0.3], FLAT) is True


def _view(lut, pwf):
    v = luts.ViewLuts("view_1")
    v._luts["Lithology1"] = lut
    if pwf is not None:
        v._pwfs["Lithology1"] = pwf
    return v


def test_the_mapping_the_reader_left_on_over_an_opaque_curve_is_turned_off(monkeypatch):
    monkeypatch.setattr(categorical_palette, "is_indexed", lambda lut: False)
    lut = SimpleNamespace(EnableOpacityMapping=1)
    _view(lut, SimpleNamespace(Points=list(FLAT)))._settle_opacity("Lithology1")
    assert lut.EnableOpacityMapping == 0


def test_a_translucent_curve_keeps_it_and_the_table_own_curve_is_read(monkeypatch):
    monkeypatch.setattr(categorical_palette, "is_indexed", lambda lut: False)
    lut = SimpleNamespace(EnableOpacityMapping=1)
    _view(lut, SimpleNamespace(Points=list(RAMP)))._settle_opacity("Lithology1")
    assert lut.EnableOpacityMapping == 1
    # no view curve yet: the table's own opacity function is read
    lut = SimpleNamespace(EnableOpacityMapping=1, ScalarOpacityFunction=SimpleNamespace(Points=list(FLAT)))
    _view(lut, None)._settle_opacity("Lithology1")
    assert lut.EnableOpacityMapping == 0


def test_a_code_made_translucent_keeps_it_on_and_off_stays_off(monkeypatch):
    monkeypatch.setattr(categorical_palette, "is_indexed", lambda lut: True)
    monkeypatch.setattr(categorical_palette, "read", lambda lut: [{"opacity": 1.0}, {"opacity": 0.5}])
    lut = SimpleNamespace(EnableOpacityMapping=1)
    _view(lut, SimpleNamespace(Points=list(FLAT)))._settle_opacity("Lithology1")
    assert lut.EnableOpacityMapping == 1
    off = SimpleNamespace(EnableOpacityMapping=0)
    _view(off, SimpleNamespace(Points=list(RAMP)))._settle_opacity("Lithology1")
    assert off.EnableOpacityMapping == 0
