"""
Tests unitaires pour fespp_on_trame.app.core.fespp_tree.Tree

Couvre :
  - set_tree : dispatch reservoir / surface / well
  - find_type : lecture du type d'un nœud
  - find_path : chemin d'un nœud
  - add_subtreeview_data : construction récursive, exclusion des enfants Realization
  - optimize_tree_selection : remontée optimisée de la sélection
"""
import pytest
from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.app.core.fespp_tree import Tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assembly_ijk_with_property() -> tuple[FakeDataAssembly, dict]:
    """
    Arbre minimal :
      root
        IjkGrid_MyGrid           (node 1)
          Properties_Pressure    (node 2)
    """
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid1", 0, label="IjkGrid_MyGrid", type="1")
    prop = asm.add_node_with_attrs("_prop1", grid, label="Properties_Pressure", type="4")
    return asm, {"grid": grid, "prop": prop}


def _make_assembly_realization() -> tuple[FakeDataAssembly, dict]:
    """
    root
      IjkGrid_MyGrid               (node 1)
        Realization_Pressure       (node 2, type=Realization)
          _uuid_real0              (node 3, Properties, label=Pressure_real0)
          _uuid_real1              (node 4, Properties, label=Pressure_real1)
    """
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid1", 0, label="IjkGrid_MyGrid", type="1")
    real_node = asm.add_node_with_attrs(
        "_realization_Pressure", grid,
        label="Realization_Pressure", type="13"
    )
    child0 = asm.add_node_with_attrs(
        "_uuid-real0", real_node,
        label="Pressure_real0", type="4"
    )
    child1 = asm.add_node_with_attrs(
        "_uuid-real1", real_node,
        label="Pressure_real1", type="4"
    )
    return asm, {"grid": grid, "real": real_node, "c0": child0, "c1": child1}


# ---------------------------------------------------------------------------
# Tests : set_tree / dispatch
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
        asm.add_node_with_attrs("_w1", 0, label="Wellbore_Well1", type="5")
        tree = Tree(None)
        tree.set_tree(asm)
        assert len(tree._data_hierarchy_well) == 1

    def test_grid2d_goes_to_surface(self):
        asm = FakeDataAssembly()
        asm.add_node_with_attrs("_s1", 0, label="Grid2d_Horizon1", type="1")
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
# Tests : find_type
# ---------------------------------------------------------------------------

class TestFindType:
    def test_find_type_returns_label_prefix(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        assert tree.find_type(ids["grid"]) == "IjkGrid"

    def test_find_type_property(self):
        asm, ids = _make_assembly_ijk_with_property()
        tree = Tree(asm)
        assert tree.find_type(ids["prop"]) == "Properties"

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
# Tests : find_path
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
# Tests : add_subtreeview_data — exclusion des enfants Realization
# ---------------------------------------------------------------------------

class TestAddSubtreeviewData:
    def test_realization_node_has_no_children_in_treeview(self):
        """Les enfants d'un nœud Realization ne doivent pas apparaître dans le treeview."""
        asm, ids = _make_assembly_realization()
        tree = Tree(asm)
        # Le nœud Realization est l'enfant 0 de grid
        data = tree.add_subtreeview_data(ids["grid"], 0, "reservoir")
        treeview = data["treeview"]
        assert "children" not in treeview  # enfants masqués

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
        assert children[0]["type"] == "Properties"


# ---------------------------------------------------------------------------
# Tests : optimize_tree_selection  (méthode sur Selector, pas Tree)
# ---------------------------------------------------------------------------

class TestOptimizeTreeSelection:
    def _make_selector(self):
        from fespp_on_trame.app.core.fespp_selection import Selector
        from unittest.mock import MagicMock
        ijkgrid_mock = MagicMock()
        return Selector(ijkgrid_mock, Tree(None))

    def _make_tree_data(self):
        return [
            {
                "id": 1, "title": "MyGrid",
                "children": [
                    {"id": 2, "title": "PropA"},
                    {"id": 3, "title": "PropB"},
                ]
            }
        ]

    def test_all_leaves_selected_returns_parent(self):
        selector = self._make_selector()
        tree_data = self._make_tree_data()
        result = selector.optimize_tree_selection([2, 3], tree_data)
        assert result == [1]

    def test_one_leaf_stays(self):
        selector = self._make_selector()
        tree_data = self._make_tree_data()
        result = selector.optimize_tree_selection([2], tree_data)
        assert 2 in result
        assert 1 not in result

    def test_empty_selection(self):
        selector = self._make_selector()
        result = selector.optimize_tree_selection([], [])
        assert result == []

    def test_none_selection(self):
        selector = self._make_selector()
        result = selector.optimize_tree_selection(None, [])
        assert result is None or result == []
