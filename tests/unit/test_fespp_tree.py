"""
Unit tests for fespp_on_trame.engine.tree.Tree.

The fixtures reproduce the data assembly contract of the FESPP plugin:

  type      the FINE type, derived from FESAPI: "IjkGrid", "ContinuousProperty",
            "Wellbore", "Grid2d"... It is what `find_type` returns and what
            the whole application compares against.
  typeCode  the numeric code of the TreeViewNodeType enum, a much coarser
            ROLE ("Properties" covers all three property classes). It is
            what `find_role` returns, through the table the plugin publishes.

The two axes are orthogonal: the code cannot give the fine type, and the
fine type does not say whether a property belongs to a grid or is a log
channel. The tests below lock that distinction in.
"""
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine.tree import Tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assembly_ijk_with_property() -> tuple[FakeDataAssembly, dict]:
    """
    Minimal tree, one grid with one property:
      root
        IjkGrid_MyGrid           (node 1)
          Properties_Pressure    (node 2)
    """
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid1", 0, label="IjkGrid_MyGrid",
                                   type="IjkGrid", typeCode="2")
    prop = asm.add_node_with_attrs("_prop1", grid, label="Properties_Pressure",
                                   type="ContinuousProperty", typeCode="4")
    return asm, {"grid": grid, "prop": prop}


def _make_assembly_realization() -> tuple[FakeDataAssembly, dict]:
    """
    A grid with a Realization node holding two realizations:
    root
      IjkGrid_MyGrid               (node 1)
        Realization_Pressure       (node 2, type=Realization)
          _uuid_real0              (node 3, Properties, label=Pressure_real0)
          _uuid_real1              (node 4, Properties, label=Pressure_real1)
    """
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid1", 0, label="IjkGrid_MyGrid",
                                   type="IjkGrid", typeCode="2")
    real_node = asm.add_node_with_attrs(
        "_realization_Pressure", grid,
        label="Realization_Pressure", type="Realization", typeCode="13"
    )
    child0 = asm.add_node_with_attrs(
        "_uuid-real0", real_node,
        label="Pressure_real0", type="ContinuousProperty", typeCode="4"
    )
    child1 = asm.add_node_with_attrs(
        "_uuid-real1", real_node,
        label="Pressure_real1", type="ContinuousProperty", typeCode="4"
    )
    return asm, {"grid": grid, "real": real_node, "c0": child0, "c1": child1}


# ---------------------------------------------------------------------------
# set_tree / dispatch
# ---------------------------------------------------------------------------

class TestSetTree:
    def test_ijk_grid_goes_to_reservoir(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(None)
        tree.set_tree(asm)
        assert len(tree._data_hierarchy_reservoir) == 1
        assert len(tree._data_hierarchy_well) == 0
        assert len(tree._data_hierarchy_surface) == 0

    def test_wellbore_goes_to_well(self):
        asm = FakeDataAssembly()
        asm.add_node_with_attrs("_w1", 0, label="Wellbore_Well1",
                            type="Wellbore", typeCode="5")
        tree = Tree(None)
        tree.set_tree(asm)
        assert len(tree._data_hierarchy_well) == 1

    def test_grid2d_goes_to_surface(self):
        asm = FakeDataAssembly()
        asm.add_node_with_attrs("_s1", 0, label="Grid2d_Horizon1",
                            type="Grid2d", typeCode="2")
        tree = Tree(None)
        tree.set_tree(asm)
        assert len(tree._data_hierarchy_surface) == 1

    def test_set_tree_none_clears_hierarchies(self):
        asm, _ = _make_assembly_ijk_with_property()
        tree = Tree(None)
        tree.set_tree(asm)
        tree.set_tree(None)
        assert tree._data_hierarchy_reservoir == []
        assert tree._data_hierarchy_surface == []
        assert tree._data_hierarchy_well == []


# ---------------------------------------------------------------------------
# find_type, find_role, renders
# ---------------------------------------------------------------------------

class TestFindType:
    def test_find_type_is_the_fine_fesapi_name(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        assert tree.find_type(ids["grid"]) == "IjkGrid"

    def test_find_type_property_is_the_class_not_the_role(self):
        """The FINE type tells Continuous / Discrete / Categorical apart; the
        role does not, it covers all three under "Properties"."""
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        assert tree.find_type(ids["prop"]) == "ContinuousProperty"

    def test_find_role_is_the_coarse_enum_label(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        assert tree.find_role(ids["prop"]) is None      # no enum table set
        tree.set_type_enum({"2": {"label": "Representation", "mapper": "Mapper"},
                            "4": {"label": "Properties", "mapper": "Data"}})
        assert tree.find_role(ids["prop"]) == "Properties"
        assert tree.find_type(ids["prop"]) == "ContinuousProperty"

    def test_renders_asks_the_plugin_not_a_name_list(self):
        """Whether a node renders comes from the plugin's MapperType.

        A property carries data but has no geometry of its own: the plugin
        classes it as MapperType Data, not Mapper."""
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        tree.set_type_enum({"2": {"label": "Representation", "mapper": "Mapper"},
                            "4": {"label": "Properties", "mapper": "Data"}})
        assert tree.renders(ids["grid"]) is True
        assert tree.renders(ids["prop"]) is False

    def test_find_type_realization(self):
        asm, ids = _make_assembly_realization()
        tree = Tree(asm)
        assert tree.find_type(ids["real"]) == "Realization"

    def test_find_type_none_returns_none(self):
        tree = Tree(None)
        assert tree.find_type(None) is None

    def test_find_type_root_zero_returns_none(self):
        asm = FakeDataAssembly()
        tree = Tree(asm)
        assert tree.find_type(0) is None


# ---------------------------------------------------------------------------
# find_path
# ---------------------------------------------------------------------------

class TestFindPath:
    def test_path_includes_node_name(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        path = tree.find_path(ids["grid"])
        assert "_grid1" in path

    def test_path_child_includes_parent(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        path = tree.find_path(ids["prop"])
        assert "_grid1" in path
        assert "_prop1" in path


# ---------------------------------------------------------------------------
# add_subtreeview_data: Realization children, partial objects
# ---------------------------------------------------------------------------

class TestAddSubtreeviewData:
    def test_realization_children_are_folded_by_the_plugin_not_here(self):
        """Realizations are folded by the C++ plugin, not by the tree.

        The plugin creates synthetic MultiRealization nodes WITHOUT children
        (searchRealization), so a "Realization" node gets no special handling
        here: its children are listed like those of any other node."""
        asm, ids = _make_assembly_realization()
        tree = Tree(asm)
        data = tree.add_subtreeview_data(ids["grid"], 0, "reservoir")
        children = data["treeview"].get("children", [])
        assert len(children) == 2
        assert {c["title"] for c in children} == {None}   # no title attribute set

    def test_partial_node_is_flagged_and_uncheckable(self):
        """A PARTIAL object is flagged and cannot be checked.

        It carries only its title and uuid, so there is nothing to load; this
        is the one masking rule the tree applies."""
        asm = FakeDataAssembly()
        asm.add_node_with_attrs("_p1", 0, label="partial_Ghost", title="Ghost",
                                type="partial", typeCode="15")
        tree = Tree(asm)
        data = tree.add_subtreeview_data(0, 0, "unknown")
        assert data["treeview"]["title"].startswith("!!!PARTIAL!!!")

    def test_property_node_in_treeview(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        data = tree.add_subtreeview_data(0, 0, "unknown")
        assert data["treeview"]["type"] == "IjkGrid"
        assert data["treeview_type"] == "reservoir"

    def test_property_child_present_in_treeview(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        data = tree.add_subtreeview_data(0, 0, "unknown")
        children = data["treeview"].get("children", [])
        assert len(children) == 1
        assert children[0]["type"] == "ContinuousProperty"


# ---------------------------------------------------------------------------
# optimize_tree_selection (a Selector method, not a Tree one)
# ---------------------------------------------------------------------------

class TestOptimizeTreeSelection:
    """In EXPLICIT selection mode the method is the IDENTITY.

    The C++ side runs with ExplicitSelection=1 (set in app.boot), so it does
    not load the descendants of a parent path. Collapsing a selection to its
    parent would silently drop the properties checked in the tree."""

    def _make_selector(self):
        from fespp_on_trame.engine.selector import Selector
        return Selector(Tree(None))

    def test_selection_is_forwarded_verbatim(self):
        selector = self._make_selector()
        assert selector.optimize_tree_selection([2, 3]) == [2, 3]

    def test_a_single_leaf_is_not_collapsed_to_its_parent(self):
        selector = self._make_selector()
        assert selector.optimize_tree_selection([2]) == [2]

    def test_empty_selection(self):
        selector = self._make_selector()
        assert selector.optimize_tree_selection([]) == []

    def test_none_selection(self):
        selector = self._make_selector()
        result = selector.optimize_tree_selection(None)
        assert result is None or result == []
