"""Vector properties through the value seam
(fespp_on_trame.engine.property_values.reduce_components / component_choice).

A property with several values per element reaches the app as an (n, c)
VTK array; every analysis consumer must see one value per element: the
chosen component, or the magnitude by default.
"""
import math

import pytest

from fespp_on_trame.engine.property_values import (
    component_choice, reduce_components,
)


class _State:
    def __init__(self, **kw):
        self.__dict__.update(kw)


VEC = [[3.0, 4.0, 0.0], [0.0, 0.0, 2.0], [1.0, 1.0, 1.0]]


class TestReduceComponents:
    def test_scalar_passes_through_flat(self):
        assert list(reduce_components([[1.0], [2.0]], None)) == [1.0, 2.0]
        assert list(reduce_components([1.0, 2.0], 0)) == [1.0, 2.0]

    def test_magnitude_by_default(self):
        out = reduce_components(VEC, None)
        assert list(out) == pytest.approx([5.0, 2.0, math.sqrt(3.0)])

    def test_one_component(self):
        assert list(reduce_components(VEC, 1)) == [4.0, 0.0, 1.0]

    def test_out_of_range_component_falls_back_to_magnitude(self):
        assert list(reduce_components(VEC, 7)) == pytest.approx([5.0, 2.0, math.sqrt(3.0)])

    def test_nan_component_makes_a_nan_magnitude(self):
        out = reduce_components([[float("nan"), 1.0, 1.0]], None)
        assert math.isnan(out[0])

    def test_one_value_per_element(self):
        assert reduce_components(VEC, None).shape == (3,)


class TestComponentChoice:
    def test_unset_is_magnitude(self):
        assert component_choice(_State(), "/data/p") is None
        assert component_choice(_State(ui_vector_component={}), "/data/p") is None

    def test_index_and_magnitude_words(self):
        st = _State(ui_vector_component={"/data/p": 2, "/data/q": "magnitude",
                                         "/data/r": "1"})
        assert component_choice(st, "/data/p") == 2
        assert component_choice(st, "/data/q") is None
        assert component_choice(st, "/data/r") == 1

    def test_garbage_is_magnitude(self):
        st = _State(ui_vector_component={"/data/p": "x"})
        assert component_choice(st, "/data/p") is None


class TestComponentLabel:
    """The component the numbers come from, named once (with the naming the
    Colormap card offers) and folded into every card, axis and chip title
    through `labelled`."""

    def _tree(self, count="3"):
        from tests.unit.fake_assembly import FakeDataAssembly
        from fespp_on_trame.engine.tree import Tree
        asm = FakeDataAssembly()
        grid = asm.add_node_with_attrs("_grid", 0, title="G", type="IjkGrid",
                                       typeCode="2")
        vec = asm.add_node_with_attrs("_vec", grid, title="velocity",
                                      type="ContinuousProperty", typeCode="4",
                                      componentCount=count)
        return Tree(asm), asm.GetNodePath(vec)

    def test_magnitude_says_nothing(self):
        from fespp_on_trame.engine.property_values import component_label
        tree, path = self._tree()
        assert component_label(_State(), tree, path) == ""

    def test_a_vector_is_named_x_y_z(self):
        from fespp_on_trame.engine.property_values import component_label
        tree, path = self._tree("3")
        for i, name in enumerate(("X", "Y", "Z")):
            st = _State(ui_vector_component={path: i})
            assert component_label(st, tree, path) == name

    def test_a_symmetric_tensor_is_named_xx_yy_zz_xy_yz_xz(self):
        from fespp_on_trame.engine.property_values import component_label
        tree, path = self._tree("6")
        names = ("XX", "YY", "ZZ", "XY", "YZ", "XZ")
        for i, name in enumerate(names):
            st = _State(ui_vector_component={path: i})
            assert component_label(st, tree, path) == name

    def test_anything_else_is_numbered(self):
        from fespp_on_trame.engine.property_values import component_label
        tree, path = self._tree("4")
        st = _State(ui_vector_component={path: 2})
        assert component_label(st, tree, path) == "Component 2"

    def test_labelled_suffixes_after_a_middle_dot(self):
        from fespp_on_trame.engine.property_values import labelled
        tree, path = self._tree("3")
        st = _State(ui_vector_component={path: 0})
        assert labelled(st, tree, path, "velocity") == "velocity · X"
        assert labelled(_State(), tree, path, "velocity") == "velocity"

    def test_axis_key_moves_with_the_component_only(self):
        # what the plotly uirevision keys are built on: the same value for
        # the magnitude spelled or unspelled, another for a component
        from fespp_on_trame.engine.property_values import axis_key
        _tree, path = self._tree("3")
        plain = axis_key(_State(), path)
        assert plain == axis_key(
            _State(ui_vector_component={path: "magnitude"}), path)
        z = axis_key(_State(ui_vector_component={path: 2}), path)
        assert z != plain
        assert z != axis_key(_State(ui_vector_component={path: 0}), path)

    def _grouped_tree(self, node_type):
        """A time-series / multi-realization leaf: the collector builds it
        itself and copies neither `componentCount` nor `uom` onto it."""
        from tests.unit.fake_assembly import FakeDataAssembly
        from fespp_on_trame.engine.tree import Tree
        asm = FakeDataAssembly()
        grid = asm.add_node_with_attrs("_grid", 0, title="G", type="IjkGrid",
                                       typeCode="2")
        vec = asm.add_node_with_attrs("_vec", grid, title="velocity",
                                      type=node_type, typeCode="12")
        return Tree(asm), asm.GetNodePath(vec)

    def test_a_grouped_property_is_named_from_the_live_count(self):
        # the count the Colormap card reads off the array is published with
        # the choice; without it the label would read "Component 1" where
        # the card the component was picked in says "Y"
        from fespp_on_trame.engine.property_values import component_label
        for node_type in ("TimeSeries", "MultiRealization",
                          "MultiRealizationTimeSeries"):
            tree, path = self._grouped_tree(node_type)
            st = _State(ui_vector_component={path: 1},
                        ui_vector_component_count={path: 3})
            assert component_label(st, tree, path) == "Y", node_type

    def test_the_live_count_wins_over_the_assembly(self):
        from fespp_on_trame.engine.property_values import component_label
        tree, path = self._tree("3")
        st = _State(ui_vector_component={path: 3},
                    ui_vector_component_count={path: 6})
        assert component_label(st, tree, path) == "XY"


class TestLabelsCarryTheComponent:
    """The consumers that title what they show name the chosen component."""

    def _fixture(self):
        from tests.unit.fake_assembly import FakeDataAssembly
        from fespp_on_trame.engine.tree import Tree
        asm = FakeDataAssembly()
        grid = asm.add_node_with_attrs("_grid", 0, title="G", type="IjkGrid",
                                       typeCode="2")
        vec = asm.add_node_with_attrs("_vec", grid, title="velocity",
                                      type="ContinuousProperty", typeCode="4",
                                      componentCount="3", uom="m/s")
        path = asm.GetNodePath(vec)
        return Tree(asm), path, _State(ui_vector_component={path: 1})

    def test_crossplot_axis_title(self):
        from fespp_on_trame.engine import crossplot_dispatch
        tree, path, st = self._fixture()
        assert crossplot_dispatch._axis_title(st, tree, path) == \
            "velocity · Y (m/s)"

    def test_compare_row_label_and_chip(self):
        from fespp_on_trame.engine import compare_dispatch
        tree, path, st = self._fixture()
        assert compare_dispatch._row_label(st, tree, path, None, None) == \
            "velocity · Y"
        assert compare_dispatch._row_label(st, tree, path, 3, None) == \
            "velocity · Y · real 3"
        chips = compare_dispatch.resolve_items(
            st, tree, [{"path": path}], "")
        assert chips[0]["title"] == "velocity · Y"
