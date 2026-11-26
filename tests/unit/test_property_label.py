"""Tests for engine/property_values.display_label, the single on-screen
name of a property.

The colour bar, the Colormap card (and its title bar) and the plot axes
all spell "<RESQML title> · <component> (<uom>)" the same way. The unit is
left out when the tree carries none, the component when the magnitude is
shown.
"""
from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine.property_values import display_label
from fespp_on_trame.engine.tree import Tree


class _State:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _tree():
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, title="Geogrid", type="IjkGrid",
                                   typeCode="2")
    temp = asm.add_node_with_attrs("_temp", grid, title="Temperature",
                                   type="ContinuousProperty", typeCode="4",
                                   uom="K")
    poro = asm.add_node_with_attrs("_poro", grid, title="Total_Porosity",
                                   type="ContinuousProperty", typeCode="4")
    vel = asm.add_node_with_attrs("_vel", grid, title="velocity",
                                  type="ContinuousProperty", typeCode="4",
                                  componentCount="3", uom="m/s")
    # the FESPP reader's multi-realization grouping node: the property's name
    # sits in propTitle, and it carries no unit
    mr = asm.add_node_with_attrs("_multireal_PORO", grid, title="PORO",
                                 type="MultiRealization", typeCode="12",
                                 propTitle="PORO")
    paths = {k: asm.GetNodePath(n) for k, n in
             (("grid", grid), ("temp", temp), ("poro", poro), ("vel", vel),
              ("mr", mr))}
    return Tree(asm), paths


def test_title_and_unit():
    tree, p = _tree()
    assert display_label(_State(), tree, p["temp"]) == "Temperature (K)"


def test_no_unit_no_parentheses():
    tree, p = _tree()
    assert display_label(_State(), tree, p["poro"]) == "Total_Porosity"


def test_component_between_title_and_unit():
    tree, p = _tree()
    st = _State(ui_vector_component={p["vel"]: 1})
    assert display_label(st, tree, p["vel"]) == "velocity · Y (m/s)"


def test_magnitude_says_no_component():
    tree, p = _tree()
    assert display_label(_State(), tree, p["vel"]) == "velocity (m/s)"


def test_multirealization_node_is_named_by_its_property():
    tree, p = _tree()
    assert display_label(_State(), tree, p["mr"]) == "PORO"


def test_unknown_path_falls_back_to_the_given_name():
    tree, _p = _tree()
    assert display_label(_State(), tree, "/data/nowhere", fallback="PORO_real_3") \
        == "PORO_real_3"
    assert display_label(_State(), tree, "/data/nowhere") == ""
    assert display_label(_State(), tree, None, fallback="Temperature") \
        == "Temperature"


def test_derived_property_carries_its_own_unit():
    class _Ctx:
        load_generation = 0

    class _Server:
        context = _Ctx()

    tree, p = _tree()
    st = _State(ui_loaded_array_paths=[p["temp"]], ui_vector_component={})
    store = derived_props.DerivedStore(_Server())
    derived_props.set_store(store)
    try:
        err, _d = store.create(st, tree, p["grid"], "hot", "Temperature - 273",
                               uom="degC")
        assert not err, err
        path = derived_props.path_for(p["grid"], "hot")
        assert display_label(st, tree, path) == "ƒ hot (degC)"
    finally:
        derived_props.set_store(None)


def test_crossplot_axis_and_colour_bar_agree():
    """The cross-plot axis is the same text plus its own realization /
    time suffix: one rule, not two."""
    from fespp_on_trame.engine import crossplot_dispatch
    tree, p = _tree()
    st = _State(ui_vector_component={p["vel"]: 2})
    assert crossplot_dispatch._axis_title(st, tree, p["vel"]) == \
        display_label(st, tree, p["vel"]) == "velocity · Z (m/s)"
    assert crossplot_dispatch._axis_title(st, tree, p["vel"], real_idx=4) == \
        "velocity · Z (m/s) — real 4"


def test_a_value_readout_takes_the_name_and_the_unit_apart():
    # the pick and the cursor write "Temperature = 312 K": the unit once,
    # after the number it qualifies, so the name must come without it
    from fespp_on_trame.engine.property_values import name_and_unit
    tree, p = _tree()
    assert name_and_unit(_State(), tree, p["temp"]) == ("Temperature", "K")
    assert name_and_unit(_State(), tree, p["poro"]) == ("Total_Porosity", "")
    st = _State(ui_vector_component={p["vel"]: 1})
    assert name_and_unit(st, tree, p["vel"]) == ("velocity · Y", "m/s")
