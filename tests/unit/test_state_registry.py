"""app/core/state_registry: each panel's state family declared once, and
the sites that seed, wire and close a panel read that declaration."""
from fespp_on_trame.app import boot
from fespp_on_trame.app.core import state_registry as reg


def test_every_family_is_consistent():
    for fam in reg.PANEL_FAMILIES:
        assert len(set(fam.keys)) == len(fam.keys), fam.kind
        assert set(fam.settable) <= set(fam.keys), fam.kind
    assert set(reg.CROSSPLOT_AXES) <= set(reg.CROSSPLOT.keys)
    assert not set(reg.CROSSPLOT_AXES) & set(reg.CROSSPLOT.settable), "the axes are the Statistics view's"


def test_the_variable_names():
    assert reg.CROSSPLOT.vars("p1", ("x",)) == ("ui_crossplot_x_p1",)
    assert reg.CALCULATOR.var("expr", "c2") == "ui_calc_expr_c2"


def test_boot_reads_the_one_declaration():
    assert boot._COMPARE_PAYLOAD is reg.COMPARE_PAYLOAD
    assert boot._COMPARE_DIST_OPTS is reg.COMPARE_DIST_OPTS
