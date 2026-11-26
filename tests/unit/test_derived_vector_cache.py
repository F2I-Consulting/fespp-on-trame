"""Tests for engine/derived_props: a recipe over a vector input follows the
component the session reads.

A property with several values per element is read as one value: the
chosen component, or the magnitude. That choice is therefore an input of
every value the store caches, and an entry keyed without it would keep
serving the previous component to the statistics, the histogram, the
cross-plot, the Statistics view and the reconciliation.
"""
import numpy as np

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import property_values
from fespp_on_trame.engine.tree import Tree


# one vector property, three cells, three values per cell
VELOCITY = [[1.0, 10.0, 100.0], [2.0, 20.0, 200.0], [3.0, 30.0, 300.0]]


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
    vel = asm.add_node_with_attrs("_vel", grid, label="Properties_velocity",
                                  title="velocity", type="ContinuousProperty",
                                  typeCode="4", componentCount="3")
    tree = Tree(asm)
    paths = {"grid": asm.GetNodePath(grid), "velocity": asm.GetNodePath(vel)}
    state = _State([paths["velocity"]])
    store = derived_props.DerivedStore(_Server())
    return tree, paths, state, store


def _reading_seam(state):
    """Return a `values_for` that serves the vector as the value seam does:
    reduced to the component the session chose."""
    def values_for(_state, _tree, _sr, array_path, _rep, **_kw):
        comp = property_values.component_choice(state, array_path)
        return property_values.reduce_components(VELOCITY, comp)
    return values_for


def _evaluate(monkeypatch, store, tree, state, path):
    monkeypatch.setattr(property_values, "values_for", _reading_seam(state))
    return list(store.evaluate(state, tree, None, path))


def test_a_recipe_follows_the_component_of_its_input(monkeypatch):
    tree, paths, state, store = _fixture()
    err, _d = store.create(state, tree, paths["grid"], "twice", "2 * velocity")
    assert not err
    path = derived_props.path_for(paths["grid"], "twice")

    magnitude = _evaluate(monkeypatch, store, tree, state, path)
    assert magnitude[0] == 2 * np.sqrt(1.0 + 100.0 + 10000.0)

    # the Colormap card's Component row writes exactly this
    state.ui_vector_component = {paths["velocity"]: 0}
    first = _evaluate(monkeypatch, store, tree, state, path)
    assert first == [2.0, 4.0, 6.0]
    assert first != magnitude

    state.ui_vector_component = {paths["velocity"]: 2}
    third = _evaluate(monkeypatch, store, tree, state, path)
    assert third == [200.0, 400.0, 600.0]


def test_the_previous_component_is_still_cached_and_recomputed(monkeypatch):
    """Going back to a component already read gives that component's
    values, not the ones read last."""
    tree, paths, state, store = _fixture()
    store.create(state, tree, paths["grid"], "twice", "2 * velocity")
    path = derived_props.path_for(paths["grid"], "twice")
    state.ui_vector_component = {paths["velocity"]: 0}
    first = _evaluate(monkeypatch, store, tree, state, path)
    state.ui_vector_component = {paths["velocity"]: 1}
    _evaluate(monkeypatch, store, tree, state, path)
    state.ui_vector_component = {paths["velocity"]: 0}
    assert _evaluate(monkeypatch, store, tree, state, path) == first


def test_the_component_is_part_of_the_cache_key():
    tree, paths, state, store = _fixture()
    store.create(state, tree, paths["grid"], "twice", "2 * velocity")
    path = derived_props.path_for(paths["grid"], "twice")
    # the recipe keys the choices of its inputs, the input keys its own
    assert store._comp_keypart(state, paths["velocity"]) is None
    assert store._comp_keypart(state, path) == (None,)
    state.ui_vector_component = {paths["velocity"]: 1}
    assert store._comp_keypart(state, paths["velocity"]) == 1
    assert store._comp_keypart(state, path) == (1,)


def test_an_unrelated_component_choice_keeps_the_entry(monkeypatch):
    """The key holds the choices of the recipe's inputs rather than a
    global generation: a choice on another property leaves this recipe's
    key untouched."""
    tree, paths, state, store = _fixture()
    store.create(state, tree, paths["grid"], "twice", "2 * velocity")
    path = derived_props.path_for(paths["grid"], "twice")
    before = store._comp_keypart(state, path)
    state.ui_vector_component = {"/data/_grid/_stress": 4}
    assert store._comp_keypart(state, path) == before


def test_a_time_series_input_is_re_read_when_the_session_time_moves(monkeypatch):
    # a recipe over a time-series input read without a time step follows the
    # session's time: a time move is a cache miss, never the first read again
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="IjkGrid_G", title="G",
                                   type="IjkGrid", typeCode="2")
    pres = asm.add_node_with_attrs("_p", grid, label="Properties_pressure",
                                   title="pressure", type="TimeSeries",
                                   propType="ContinuousProperty", typeCode="4")
    tree = Tree(asm)
    gpath, ppath = asm.GetNodePath(grid), asm.GetNodePath(pres)
    state = _State([ppath])
    store = derived_props.DerivedStore(_Server())
    err, _d = store.create(state, tree, gpath, "twice", "2 * pressure")
    assert not err
    path = derived_props.path_for(gpath, "twice")
    now = {"t": 0.0}
    reads = []

    def values_for(_state, _tree, _sr, array_path, _rep, **_kw):
        reads.append(now["t"])
        return np.array([1.0, 2.0]) * (1.0 + now["t"])

    monkeypatch.setattr(property_values, "values_for", values_for)
    monkeypatch.setattr(derived_props, "_session_time", lambda: now["t"])
    assert list(store.evaluate(state, tree, None, path)) == [2.0, 4.0]
    assert list(store.evaluate(state, tree, None, path)) == [2.0, 4.0]
    assert reads == [0.0]                       # the second read was cached
    now["t"] = 3.0
    assert list(store.evaluate(state, tree, None, path)) == [8.0, 16.0]
    # an unknown session time is never served from the cache
    monkeypatch.setattr(derived_props, "_session_time", lambda: None)
    store.evaluate(state, tree, None, path)
    store.evaluate(state, tree, None, path)
    assert len(reads) == 4
