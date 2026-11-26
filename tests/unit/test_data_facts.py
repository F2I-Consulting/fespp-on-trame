"""What the loaded data holds, for the top bar's gates (engine/data_facts,
app/views/top_gates): a panel whose data is not there is greyed, with why
(the PO, 28/10)."""
from fespp_on_trame.app.views import top_gates
from fespp_on_trame.engine import data_facts
from fespp_on_trame.engine.tree import Tree
from tests.unit.fake_assembly import FakeDataAssembly


def _tree(with_wells=True, with_grid=True):
    asm = FakeDataAssembly()
    if with_grid:
        cont = asm.add_node_with_attrs("_gridfolder_g", 0, type="GridContainer", title="grid")
        props = asm.add_node_with_attrs("_propsfolder_g", cont, type="PropertiesFolder")
        asm.add_node_with_attrs("_g", props, type="IjkGrid", title="SolidColor")
        asm.add_node_with_attrs("_poro", props, type="ContinuousProperty", title="PORO")
    if with_wells:
        well = asm.add_node_with_attrs("_w", 0, type="Wellbore", title="W-1")
        frame = asm.add_node_with_attrs("_f", well, type="Frame", title="logs")
        asm.add_node_with_attrs("_gr", frame, type="ContinuousProperty", title="GR")
    return Tree(asm)


def test_the_facts_count_properties_wells_logs_and_grid_properties():
    assert data_facts.facts(_tree()) == {"properties": 2, "wells": 1, "logs": 1, "grid_properties": 1}
    assert data_facts.facts(_tree(with_wells=False)) == {
        "properties": 1, "wells": 0, "logs": 0, "grid_properties": 1}


def test_a_gate_greys_on_a_fact_that_is_zero_never_on_one_it_lacks():
    off, tip = top_gates.gate("Log view", "wells")
    assert off == ("!ui_has_data || (ui_data_facts || {}).wells === 0",)
    assert "the loaded data has no wellbore" in tip[0] and "import a file first" in tip[0]
    # no need: the data alone, as every panel button before
    assert top_gates.gate("Explorer")[0] == ("!ui_has_data",)
    # the Globe's reason is the session's own, read when the tooltip shows
    off, tip = top_gates.gate("Globe", "crs")
    assert off == ("!ui_has_data || !ui_globe_ok",)
    assert "'Globe — ' + ui_globe_why" in tip[0]
