"""engine/derived_props — a derived property created as an A − B is marked
a difference, and stays one through an edit that keeps its formula."""
from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine.tree import Tree


class _State:
    def __init__(self, loaded):
        self.ui_loaded_array_paths = list(loaded)
        self.ui_vector_component = {}


class _Context:
    load_generation = 0


class _Server:
    context = _Context()


def _fixture():
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="IjkGrid_G", title="G",
                                   type="IjkGrid", typeCode="2")
    a = asm.add_node_with_attrs("_a", grid, label="Properties_PORO_A", title="PORO_A",
                                type="ContinuousProperty", typeCode="4")
    b = asm.add_node_with_attrs("_b", grid, label="Properties_PORO_B", title="PORO_B",
                                type="ContinuousProperty", typeCode="4")
    tree = Tree(asm)
    paths = {"grid": asm.GetNodePath(grid), "a": asm.GetNodePath(a),
             "b": asm.GetNodePath(b)}
    state = _State([paths["a"], paths["b"]])
    store = derived_props.DerivedStore(_Server())
    derived_props.set_store(store)
    return tree, paths, state, store


def test_a_difference_is_marked_and_survives_an_edit():
    tree, p, state, store = _fixture()
    try:
        err, d = store.create(state, tree, p["grid"], "delta", "PORO_A - PORO_B",
                              role="difference")
        assert not err and d["role"] == "difference"
        path = derived_props.path_for(p["grid"], "delta")
        assert derived_props.is_difference(path)
        # an ordinary recipe is not one
        err, _ = store.create(state, tree, p["grid"], "twice", "2 * PORO_A")
        assert not err
        assert not derived_props.is_difference(derived_props.path_for(p["grid"], "twice"))
        assert not derived_props.is_difference(p["a"])
        # an edit that keeps the formula (a unit, a rename) keeps the role
        err, d = store.create(state, tree, p["grid"], "delta", " PORO_A -  PORO_B ",
                              uom="v/v", editing_name="delta")
        assert not err and d["role"] == "difference"
        err, d = store.create(state, tree, p["grid"], "delta2", "PORO_A - PORO_B",
                              editing_name="delta")
        assert not err and d["role"] == "difference"
        assert derived_props.is_difference(derived_props.path_for(p["grid"], "delta2"))
        assert not derived_props.is_difference(path)
        # a new formula is not a difference any more
        err, d = store.create(state, tree, p["grid"], "delta2", "PORO_A / PORO_B",
                              editing_name="delta2")
        assert not err and d["role"] == ""
        assert not derived_props.is_difference(derived_props.path_for(p["grid"], "delta2"))
    finally:
        derived_props.set_store(None)
