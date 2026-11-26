"""The Statistics view's wiring: the docked tree, the rows that follow an item
and what makes them follow (app/features/compare, compare_tree, compare_parts).

The three modules are registered as boot does, over a fake assembly and a state
that runs its watchers on a flush; the panels' grammar and the application's
events are the real ones. The value reads are monkeypatched, what is pinned
here is who calls what.
"""
import ast
from contextlib import contextmanager
from pathlib import Path
import re
from types import SimpleNamespace

import numpy as np
import pytest

import fespp_on_trame
from fespp_on_trame.app.core.lifecycle import Lifecycle
from fespp_on_trame.app.features import compare as compare_feature
from fespp_on_trame.app.features import compare_parts as parts_feature
from fespp_on_trame.app.features import compare_tree as tree_feature
from fespp_on_trame.app.scene.panel_trees import PanelTrees
from fespp_on_trame.engine import cell_weights
from fespp_on_trame.engine import compare_dispatch as cd
from fespp_on_trame.engine import compare_tree as ct
from fespp_on_trame.engine import compare_matrix
from fespp_on_trame.engine import compare_rows
from fespp_on_trame.engine import crossplot_dispatch
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import node_facts
from fespp_on_trame.engine import stats_dispatch as sd
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine import tick_confirm
from fespp_on_trame.engine import view_resources
from tests.unit.test_compare_rows import _tree


class FakeState:
    """A trame state as the features use it: names read and written at once,
    the watchers of what changed run on `flush`."""

    def __init__(self, **seed):
        object.__setattr__(self, "_values", dict(seed))
        object.__setattr__(self, "_watchers", [])
        object.__setattr__(self, "_changed", set())

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self[name] = value

    def __setitem__(self, name, value):
        if self._values.get(name) != value or name not in self._values:
            self._changed.add(name)
        self._values[name] = value

    def __getitem__(self, name):
        return self._values.get(name)

    def setdefault(self, name, value):
        self._values.setdefault(name, value)

    def is_dirty(self, name):
        return name in self._changed

    def change(self, *names):
        def deco(fn):
            self._watchers.append((set(names), fn))
            return fn
        return deco

    def flush(self):
        for _ in range(20):
            if not self._changed:
                return
            changed = set(self._changed)
            self._changed.clear()
            for names, fn in list(self._watchers):
                if names & changed:
                    fn(**self._values)
        raise AssertionError("the watchers do not settle")


class FakeController:
    """`set` registers; a name nothing registered is a recorded no-op."""

    def __init__(self):
        self.__dict__.update(fns={}, calls=[])

    def set(self, name):
        def deco(fn):
            self.fns[name] = fn
            return fn
        return deco

    def __getattr__(self, name):
        if name in self.fns:
            return self.fns[name]

        def recorded(*args, **_kwargs):
            self.calls.append((name, args))
        return recorded

    def called(self, name):
        return [args for n, args in self.calls if n == name]


class FakeBatcher:
    def __init__(self):
        self.armed = {}

    def schedule(self, key, callback, delay=None):
        self.armed[key] = (callback, delay)

    def fire(self):
        armed, self.armed = self.armed, {}
        for callback, _delay in armed.values():
            callback()


class FakeViews:
    """The view manager: one 3D view, and the panels opened."""

    def __init__(self):
        self.opened = []

    def add_view(self, kind=None, **_kw):
        self.opened.append(kind)
        return f"{kind}_1"

    def panel_ids_of_kind(self, kind):
        return ["view_1"] if kind == "render" else [f"{kind}_1"] if kind in self.opened else []

    def view_ids(self):
        return ["view_1"]

    def title_of(self, vid):
        return "3D view 1" if vid == "view_1" else vid


class FakeIsolate:
    def __init__(self):
        self.cuts = {"mode": "range"}
        self.chain = []
        self.hide_nan_array = None
        self.hidden_codes = ()

    def snapshot(self):
        return dict(self.cuts)

    def get_chain(self):
        return list(self.chain)


class FakeRecipes:
    """The calculator's store: recipes it knows, some stale."""

    def __init__(self):
        self.defs = {}

    def add(self, rep, name):
        path = derived_props.path_for(rep, name)
        self.defs[path] = {"name": name, "rep_path": rep, "prop_kind": "ContinuousProperty", "uom": ""}
        return path

    def get(self, path):
        return self.defs.get(path)

    def active_paths(self):
        return [q for q, d in self.defs.items() if not d.get("stale")]

    def title(self, path):
        return f"F {self.defs[path]['name']}" if path in self.defs else ""

    def axis_caps(self, tree, path):
        return {"is_mr": False, "is_ts": False, "reals": []}


@pytest.fixture
def app(monkeypatch):
    """The session, the three features wired, the Statistics view open."""
    tree, p = _tree()
    recipes = FakeRecipes()
    monkeypatch.setattr(derived_props, "get_store", lambda: recipes)
    monkeypatch.setattr(cell_weights, "weights_for", lambda *a: {"note": ""})
    monkeypatch.setattr(cd, "_values_for", lambda *a, **k: np.linspace(0.1, 0.3, 11))
    monkeypatch.setattr(sd, "_resolve_rendered_inputs", lambda rep, vid: ([], None))
    monkeypatch.setattr(stats_supports, "part_values", lambda *a, **k: {
        "values": np.array([1.0, 2.0, 3.0]), "volume": None, "pore": None,
        "length": None, "missing": 0})
    state = FakeState(
        ui_compare_items=[], ui_compare_parts=[], ui_compare_session_rows=[], ui_compare_tab="",
        ui_compare_chips=[], ui_compare_rows={}, fespp_render_panels=[{"id": "view_1", "title": "3D view 1"}],
        selected_paths=[p["poro"], p["perm"], p["w1"], p["north"]],
        ui_loaded_array_paths=[p["poro"], p["perm"]], ui_loaded_rep_paths=[p["w1"], p["north"]],
        ui_vector_component={}, ui_active_realization_by_array_by_view={},
        ui_per_view_time_pulse=0, ui_compare_note="")
    state["vtk_log_messages"] = []
    views = FakeViews()
    core = SimpleNamespace(
        state=state, controller=FakeController(), tree=tree,
        ctx=SimpleNamespace(grid_isolates={}), source_registry=None,
        derived_store=recipes, panel_trees=PanelTrees(),
        lifecycle=Lifecycle(), batcher=FakeBatcher(), mv=lambda: views)
    log = SimpleNamespace(deferred=[], selections=[], crossplot=[], asked=[])

    def defer(name, fn, views=None):
        log.deferred.append(name)
        fn()

    def apply_selection(paths, **kw):
        log.selections.append((list(paths), kw))
        state.selected_paths = list(paths)

    def tree_tick(vid, kind, paths):
        """As the session's load does: what is read goes in the panel, what
        leaves the selection leaves every panel."""
        before = set(state.selected_paths)
        state.selected_paths = list(paths)
        core.panel_trees.prune([q for q in before if q not in set(paths)])
        core.panel_trees.take(kind, vid, [q for q in paths if q not in before])

    noop = lambda *a, **k: None    # noqa: E731
    # the road of a tick, which a test may replace by the session's own (`_session_road`)
    road = SimpleNamespace(apply_selection=apply_selection, tree_tick=tree_tick,
                           ask_tick=lambda count, yes, no, shown=True: log.asked.append(count))
    returned = compare_feature.register(
        core, _apply_selection=lambda *a, **k: road.apply_selection(*a, **k), _defer=defer, _drop_crossplot=noop,
        _drop_crossplot_figures=noop, _drop_tick_question=noop, _property_label=lambda q: "",
        _refresh_crossplot=lambda pid: log.crossplot.append(pid), _register_crossplot=noop,
        _sync_compare_tree_eyes=lambda: None)
    (_close, _compare, current_kind, index, item_key, items, loaded_paths, names, note, parts,
     published, request_load, resort, set_axis, tick_note, uid, kind_state, project, rebuild,
     refresh, refresh_now, refresh_rows, set_items, set_parts, sync_selection, open_compare) = returned
    add, _eyes, _panel_eyes = tree_feature.register(
        core, _ask_tick=lambda *a, **k: road.ask_tick(*a, **k),
        _compare=_compare, _tree_tick=lambda *a: road.tree_tick(*a),
        _compare_current_kind=current_kind, _compare_index=index, _compare_item_key=item_key,
        _compare_items=items, _compare_loaded_paths=loaded_paths, _compare_names=names,
        _compare_note=note, _compare_parts=parts, _compare_published=published,
        _compare_request_load=request_load, _compare_resort=resort, _compare_set_axis=set_axis,
        _compare_tick_note=tick_note, _compare_uid=uid, _kind_state=kind_state,
        _project_kind_state=project, _rebuild_compare_tree=rebuild,
        _refresh_compare=refresh, _refresh_compare_now=refresh_now,
        _set_compare_items=set_items, _set_compare_parts=set_parts,
        _sync_compare_tree_selection=sync_selection, open_compare=open_compare)
    parts_feature.register(
        core, _compare=_compare, _compare_add=add, _compare_parts=parts,
        _property_or_note=lambda path, what: path in p.values(), _rebuild_compare_tree=rebuild,
        _refresh_compare=refresh, _refresh_compare_rows=refresh_rows,
        _set_compare_parts=set_parts, _sync_compare_tree_selection=sync_selection)
    open_compare()
    state.flush()
    return SimpleNamespace(state=state, core=core, c=core.controller, p=p, tree=tree, log=log, views=views,
                           compare=_compare, compare_add=add, items=items, kind_state=kind_state,
                           refresh=refresh, rebuild=rebuild, recipes=recipes, open_compare=open_compare,
                           road=road)


def _syn(app, path):
    return next(s for s, q in app.compare["path_map"].items() if q == path)


def _eye(app, path, on=None):
    ev = {"path": _syn(app, path)}
    if on is not None:
        ev["visible"] = on
    app.c.compare_tree_eye("compare_1", ev)
    app.state.flush()


def _add(app, *paths):
    for path in paths:
        app.c.add_to_stats(path)
    app.state.flush()


def _together(app, *paths):
    """Properties opened by ONE gesture — the eyes of a 3D view's tree: every
    kind among them stays, where one added after another replaces it."""
    app.core.ctx.stats_follow_eyes(list(paths), [])
    app.state.flush()


def _row_id(app, path, support):
    uid = next(it["uid"] for it in app.items() if it["path"] == path)
    return f"{uid}@{support}"


# ---- what boot passes ----------------------------------------------------------

def test_boot_gives_every_feature_the_names_it_takes():
    """A name missing or left over would stop the application at its start, and
    no other test runs `boot_engine`."""
    app_dir = Path(fespp_on_trame.__file__).parent / "app"
    boot = ast.parse((app_dir / "boot.py").read_text(encoding="utf-8"))
    modules = {a.asname or a.name: a.name for n in ast.walk(boot)
               if isinstance(n, ast.ImportFrom) and n.module == "fespp_on_trame.app.features"
               for a in n.names}
    checked = 0
    for call in ast.walk(boot):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "register" and getattr(call.func.value, "id", "") in modules):
            continue
        feature = ast.parse((app_dir / "features" / f"{modules[call.func.value.id]}.py").read_text(encoding="utf-8"))
        args = next(n for n in feature.body if isinstance(n, ast.FunctionDef) and n.name == "register").args
        takes = {a.arg for a in args.kwonlyargs}
        needs = {a.arg for a, default in zip(args.kwonlyargs, args.kw_defaults) if default is None}
        given = {k.arg for k in call.keywords}
        assert given <= takes and needs <= given, (modules[call.func.value.id], given ^ needs)
        checked += 1
    assert checked > 20


# ---- one view -------------------------------------------------------------------

def _package_file(*names):
    return Path(fespp_on_trame.__file__).parent.joinpath(*names).read_text(encoding="utf-8")


def test_the_top_bar_has_one_door_to_the_view():
    main = _package_file("__main__.py")
    assert main.count('"compare", "properties"') == 1 and "open_stats" not in main
    assert '"fespp-statistics"' in main and "fespp-compare-view" not in main


def test_the_view_is_the_kind_compare_named_statistics():
    registry = ast.parse(_package_file("app", "views", "views_config.py"))
    kinds = next(n.value for n in registry.body if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", None) == "VIEW_KINDS" for t in n.targets))
    specs = {k.value: v for k, v in zip(kinds.keys, kinds.values)}
    assert "stats" not in specs
    labels = {k.value: v for k, v in zip(specs["compare"].keys, specs["compare"].values)}
    assert labels["label"].value == "Statistics"
    assert labels["singleton"].value is True


def test_nothing_uses_the_old_statistics_widget():
    package = Path(fespp_on_trame.__file__).parent
    users = [p.name for p in package.rglob("*.py") if "trame_fespp_statistics" in p.read_text(encoding="utf-8")]
    assert users == []
    assert "trame_fespp_statistics" not in (package.parent / "setup" / "apps.yml").read_text(encoding="utf-8")


# ---- the widget -------------------------------------------------------------------
#
# Only a browser runs a widget, and the bench holds its gestures: these read its
# source, and the bundle built from it, the file the browser runs.

WIDGETS = Path(__file__).resolve().parents[2] / "widgets"
COMPARE_PANEL = ("compare", "vue-components", "src", "ComparePanel.vue")


def _widget_source(*names):
    return WIDGETS.joinpath(*names).read_text(encoding="utf-8")


def _compare_source(name):
    return _widget_source("compare", "vue-components", "src", name)


def _bundle(widget):
    return _widget_source(widget, f"trame_fespp_{widget}", "module", "serve", f"trame_fespp_{widget}.umd.js")


def _every_bundle():
    bundles = sorted(WIDGETS.glob("*/trame_*/module/serve/*.umd.js"))
    assert len(bundles) > 20, "the bundles are not built here"
    return [(b.parent.name, b.read_text(encoding="utf-8")) for b in bundles]


def _method(source, name):
    """The body of a method of a widget's script."""
    found = re.search(rf"^    {name}\(.*?\) \{{\n(.*?)^    \}},$", source, re.MULTILINE | re.DOTALL)
    assert found, f"no method {name}"
    return found.group(1)


def _function(source, name):
    """The body of a function of a widget's module."""
    found = re.search(rf"^(?:export )?function {name}\(.*?\) \{{\n(.*?)^\}}$", source, re.MULTILINE | re.DOTALL)
    assert found, f"no function {name}"
    return found.group(1)


def test_a_row_whose_sum_means_nothing_writes_none():
    """A block keeps its Sum for the row where it means something: the others
    write a dash, and no cell is read against one; the file keeps the raw figure."""
    matrix = _compare_source("CompareMatrix.vue")
    assert 'metric !== "Sum" || row.sum_meaningful !== false' in _function(_compare_source("metrics.js"), "rowHas")
    assert "rowHas(this.row(k), m)" in _method(matrix, "metric")
    compared = _method(matrix, "compared")
    assert "rowHas(this.row(k), m)" in compared and "rowHas(this.row(this.baseKey), m)" in compared
    assert "this.compared(k, m)" in _method(matrix, "cellClass")
    assert "this.compared(k, m)" in _method(matrix, "deltaOf")
    assert "rowHas" not in _compare_source("ComparePanel.vue")


def test_the_menu_refuses_the_pin_a_row_has_no_button_for():
    acts = _compare_source("rowActs.js")
    refused = _function(acts, "pinAct")
    assert "pinnable(r)" in refused and "disabled: true" in refused and "Nothing to pin a copy at" in refused
    assert "pinAct(r)" in _function(acts, "itemActs")
    assert "pinnable(this.row)" in _compare_source("CompareRowTools.vue")


def test_the_time_step_column_of_the_file_is_in_words():
    """One nature down the column: the date a row reads, pinned or not; the
    index only where it has no words."""
    assert re.search(r'\w+\.ts_text\|\|\w+\.ts_label\|\|\(\w+\.ts\?\?""\)', _bundle("compare"))


def test_the_view_s_icon_is_the_only_one_drawn():
    icons = _widget_source("_shared", "icons", "fespp-icons.js")
    assert "compareView" not in icons and re.search(r"^  statistics: \{ parts:", icons, re.MULTILINE)
    assert [name for name, text in _every_bundle() if "M9.8 6.2a5.8 5.8" in text] == []


def test_handing_a_file_over_writes_nothing_on_the_page():
    assert "window" not in _widget_source("_shared", "csvexport.js")
    assert [name for name, text in _every_bundle() if "fpHandOver" in text] == []


def test_the_options_of_a_histogram_are_one_form():
    """The Statistics view draws the kit's form, its words and tooltips in its
    bundle; it holds no copy of them."""
    form = _widget_source("_shared", "components", "FpHistOptions.vue")
    tips = re.findall(r'title: "([^"]+)"', form)
    assert len(tips) == 6
    source = _widget_source(*COMPARE_PANEL)
    template = source.split("<script>")[0]
    assert "<fp-hist-options" in template
    assert "cumulative" not in template and "log_y" not in template and '"density"' not in source
    bundle = _bundle("compare")
    assert [tip for tip in tips if tip not in bundle] == []


def test_the_statistics_view_shapes_the_form():
    """Compact where the bar shares its width, with no Stats overlay."""
    statistics = _widget_source(*COMPARE_PANEL).split("<script>")[0]
    assert "<fp-hist-options compact" in statistics and "show_stats" not in statistics
    assert "['dist_opt', $event]" in statistics


# ---- "Add to stats" -------------------------------------------------------------

def test_add_to_stats_keeps_the_kind_last_asked_for_and_the_tab_goes_to_it(app):
    _add(app, app.p["poro"], app.p["poro_h"])
    assert [it["path"] for it in app.items()] == [app.p["poro"], app.p["poro_h"]], "one kind: both stay"
    assert app.state.ui_compare_tab == "porosity"
    _add(app, app.p["perm"])
    assert [it["path"] for it in app.items()] == [app.p["perm"]], "another kind: the rows before it leave, as an eye has them"
    assert app.state.ui_compare_tab == "permeability"
    assert [c["kind"] for c in app.state.ui_compare_chips] == ["permeability"]
    _add(app, app.p["perm"])
    assert len(app.items()) == 1, "at the same coordinates it is not doubled"
    assert app.views.opened.count("compare") >= 3, "and the view opens or comes to the front"


def test_add_to_stats_reads_what_is_not_read_born_hidden(app):
    app.state.ui_loaded_array_paths = [app.p["poro"]]
    app.state.selected_paths = [app.p["poro"]]
    _add(app, app.p["perm"])
    assert app.log.selections[-1] == ([app.p["poro"], app.p["perm"]],
                                      {"ask": False, "push": True, "shown": False})
    assert app.compare["pending"] == {app.p["perm"]: cd.LOADING}
    assert app.state.ui_compare_rows and app.items()[-1]["path"] == app.p["perm"]


def test_add_to_stats_refuses_what_is_not_a_property(app):
    app.c.add_to_stats("/not/a/node")
    app.state.flush()
    assert app.items() == []


# ---- the eyes of the docked tree -----------------------------------------------

def test_a_part_is_listed_and_its_eye_adds_it_and_keeps_all_the_rest(app):
    p = app.p
    _add(app, p["poro"], p["poro_h"])
    assert _syn(app, p["w1"]).startswith(ct.PARTS_FOLDER + "/")
    _eye(app, p["w1"])
    assert app.state.ui_compare_parts == [p["w1"]]
    assert {it["path"] for it in app.items()} == {p["poro"], p["poro_h"]}, "no property leaves, no item is made of it"
    shown = app.state["compare_tree_selected__compare_1"]
    assert {_syn(app, q) for q in (p["poro"], p["poro_h"], p["w1"])} == set(shown)
    _eye(app, p["north"])
    assert app.state.ui_compare_parts == [p["w1"], p["north"]]
    _eye(app, p["w1"])
    assert app.state.ui_compare_parts == [p["north"]], "closed, it goes"
    assert {it["path"] for it in app.items()} == {p["poro"], p["poro_h"]}


def test_an_eye_on_a_property_keeps_the_kind_rule_and_the_parts_stay(app):
    p = app.p
    _add(app, p["poro"])
    _eye(app, p["w1"])
    _eye(app, p["perm"])
    assert [it["path"] for it in app.items()] == [p["perm"]], "the kind rule"
    assert app.state.ui_compare_parts == [p["w1"]], "held parts staying"


def test_a_part_opened_is_a_row_under_each_unpinned_item_of_its_grid(app):
    p = app.p
    _add(app, p["poro"])
    _eye(app, p["w1"])
    rows = app.state.ui_compare_rows
    rid = _row_id(app, p["poro"], p["w1"])
    assert rid in rows and rows[rid]["support"] == p["w1"]
    assert rows[rid]["support_label"] == "Blocked wellbore · W1"
    assert app.state.ui_compare_blocks[0]["keys"] == [app.items()[0]["uid"], rid]
    assert app.state.ui_compare_csv["header"], "the file knows it too"
    assert any("W1" in line for line in app.state.ui_compare_csv["header"])
    _eye(app, p["w1"])
    assert rid not in app.state.ui_compare_rows


def test_the_chips_tabs_and_cross_plot_list_the_items_alone(app):
    p = app.p
    _add(app, p["poro"])
    _eye(app, p["w1"])
    assert [c["path"] for c in app.state.ui_compare_chips] == [p["poro"]]
    assert app.state.ui_compare_kinds == [{"kind": "porosity", "count": 1}]


def test_a_tick_on_a_part_reads_it_and_an_untick_unloads_it_and_its_rows_go(app):
    p = app.p
    _add(app, p["poro"])
    app.state.selected_paths = [p["poro"]]
    app.state.ui_loaded_rep_paths = []
    app.state.flush()
    syn = _syn(app, p["w1"])
    assert syn not in app.state["compare_tree_loaded__compare_1"]
    app.state.compare_tick = {"vid": "compare_1", "paths": [_syn(app, p["poro"]), syn], "t": 1}
    app.state.flush()
    assert p["w1"] in app.state.selected_paths and app.state.ui_compare_parts == [p["w1"]]
    assert syn in app.state["compare_tree_loaded__compare_1"]
    assert app.core.panel_trees.users([p["w1"]]) == ["compare_1"], "an untick elsewhere asks"
    app.state.compare_tick = {"vid": "compare_1", "paths": [_syn(app, p["poro"])], "t": 2}
    app.state.flush()
    assert p["w1"] not in app.state.selected_paths and app.state.ui_compare_parts == []
    assert [it["path"] for it in app.items()] == [p["poro"]]


def test_a_part_unloaded_from_another_tree_leaves_the_panel(app):
    p = app.p
    _add(app, p["poro"])
    _eye(app, p["w1"])
    app.core.panel_trees.prune([p["w1"]])
    app.state.flush()
    assert app.state.ui_compare_parts == [] and [it["path"] for it in app.items()] == [p["poro"]]


def test_a_read_part_says_so_on_its_leaf(app):
    p = app.p
    assert 'loadState' not in _leaf_of(app, p["w1"])
    app.state.ui_loaded_rep_paths = [p["north"]]
    app.state.flush()
    assert "unloaded" in _leaf_of(app, p["w1"]), "the tree follows what a rep read brings"
    assert "unloaded" not in _leaf_of(app, p["north"])


def _leaf_of(app, path):
    """The XML element of the leaf of `path`."""
    import re
    tag = _syn(app, path).rsplit("/", 1)[-1]
    return re.search(rf"<{tag} [^>]*>", app.state.ui_compare_tree_xml).group(0)


def test_the_properties_set_from_outside_make_no_item_of_a_part(app):
    """The assistant sends what the tree holds, plus a property."""
    p = app.p
    _add(app, p["poro"])
    _eye(app, p["w1"])
    held = list(app.state["compare_tree_selected__compare_1"])
    app.c.compare_tree_paths("compare_1", held + [_syn(app, p["perm"])])
    app.state.flush()
    assert [it["path"] for it in app.items()] == [p["poro"], p["perm"]]
    assert app.state.ui_compare_parts == [p["w1"]]


# ---- the right-click of the docked tree ----------------------------------------

def _menu(app, action, path):
    app.c.compare_tree_action("compare_1", {"action": action, "path": _syn(app, path)})
    app.state.flush()


def test_the_menu_sets_the_baseline_clears_it_and_opens_data_health(app, monkeypatch):
    p = app.p
    _axes(monkeypatch, ts=(0, 1))
    _add(app, p["poro"])
    app.c.compare_set("pin", app.items()[0]["uid"])
    app.state.flush()
    assert app.kind_state("porosity")["baseline"] == "", "plain statistics by default"
    _menu(app, "compare-baseline", p["poro"])
    assert app.kind_state("porosity")["baseline"] == app.items()[0]["uid"]
    _menu(app, "compare-baseline", p["poro"])
    assert app.kind_state("porosity")["baseline"] == "", "the same gesture on it: back to statistics"
    _menu(app, "compare-health", p["w1"])
    assert app.c.called("health_focus") == [(p["w1"],)]


# ---- a following row ------------------------------------------------------------

@pytest.fixture
def cut(app, monkeypatch):
    """PORO in the panel with W1's eye open, 3D view 1 cutting its grid."""
    p = app.p
    iso = FakeIsolate()
    rep = cd._rep_path(app.tree, p["poro"])
    app.core.ctx.grid_isolates[("view_1", rep)] = iso
    app.state["visible_paths__view_1"] = [p["poro"]]
    monkeypatch.setattr(sd, "_resolve_rendered_inputs",
                        lambda r, vid: ([object()] if r == rep and iso.cuts else [], None))
    monkeypatch.setattr(view_resources, "pv_view_of", lambda vid: SimpleNamespace(ViewTime=0.0))

    def build(state, source_registry, tree, path, rep_, vid, title):
        row = sd._row_stats_from_values(np.array([0.2, 0.25, 0.3]), "x")
        row.update(kind="view", id=vid, view_title=title, real_idx=2, ts_idx=4, ts_label="2020-01-01")
        return row

    @contextmanager
    def chain():
        yield

    monkeypatch.setattr(sd, "_build_view_row", build)
    monkeypatch.setattr(sd, "transient_chain", chain)
    monkeypatch.setattr(compare_rows, "support_values", lambda *a: np.array([0.2, 0.3]))
    _add(app, p["poro"])
    _eye(app, p["w1"])
    return iso


@pytest.mark.parametrize("key,value,says", [
    ("baseline", "{k}", "the baseline is a row of the property itself"),
    ("pin", "{k}", "follows the row above"),
    ("unpin", "{k}", "follows the row above"),
    ("unpin_all", "{k}", "follows the row above"),
    ("pin_all", ["{k}", "ts"], "follows the row above"),
    ("real", ["{k}", 1], "follows the row above"),
])
def test_a_following_row_refuses_what_is_not_for_it_and_says_why(app, cut, key, value, says):
    k = f"{app.items()[0]['uid']}@{app.p['w1']}"
    app.kind_state("porosity")["baseline"] = app.items()[0]["uid"]
    before = (app.items(), app.kind_state("porosity")["baseline"])
    app.c.compare_set(key, [k, value[1]] if isinstance(value, list) else k)
    app.state.flush()
    assert (app.items(), app.kind_state("porosity")["baseline"]) == before
    assert says in app.state.ui_compare_note


def test_remove_on_a_part_s_row_closes_it_all_its_rows_going(app, cut):
    p = app.p
    app.c.compare_set("remove", f"{app.items()[0]['uid']}@{p['w1']}")
    app.state.flush()
    assert app.state.ui_compare_parts == [] and [it["path"] for it in app.items()] == [p["poro"]]


def test_remove_on_a_view_s_row_stays_and_says_when_it_goes(app, cut):
    app.c.compare_set("remove", f"{app.items()[0]['uid']}@view:view_1")
    app.state.flush()
    assert len(app.items()) == 1 and "3D view's" in app.state.ui_compare_note


# ---- a 3D view's rows follow what it draws -------------------------------------

def _gesture(app):
    """A burst on a slider, then quiet."""
    for _ in range(3):
        app.core.lifecycle.emit("view_cuts", vid="view_1")
    assert list(app.core.batcher.armed) == ["compare:cuts"], "one read after the burst"
    app.log.deferred.clear()
    app.core.batcher.fire()
    app.state.flush()
    return app.log.deferred


def test_a_cut_moved_reads_the_rows_again_and_only_them(app, cut):
    rid = f"{app.items()[0]['uid']}@view:view_1"
    assert rid in app.state.ui_compare_rows, "the view's row is there with no gesture"
    _gesture(app)
    app.log.crossplot.clear()
    assert _gesture(app) == [], "nothing moved, nothing read"
    cut.cuts = {"mode": "range", "volumes": [[[0, 1], [0, 1], [0, 1]]]}
    assert _gesture(app) == ["compare-rows"]
    assert app.log.crossplot == [], "the cross-plot reads the items"
    assert rid in app.state.ui_compare_rows


def test_a_threshold_moved_reads_them_too(app, cut):
    _gesture(app)
    cut.chain = [{"name": "t1", "low": 0.1, "high": 0.2}]
    assert _gesture(app) == ["compare-rows"]


def test_the_row_goes_with_the_cut(app, cut):
    rid = f"{app.items()[0]['uid']}@view:view_1"
    _gesture(app)
    cut.cuts = {}
    assert _gesture(app) == ["compare-rows"]
    assert rid not in app.state.ui_compare_rows


def test_the_row_goes_with_the_eye_of_the_view(app, cut):
    rid = f"{app.items()[0]['uid']}@view:view_1"
    _gesture(app)
    app.state["visible_paths__view_1"] = []
    app.core.lifecycle.emit("session_rows", vid="view_1")
    app.core.batcher.fire()
    app.state.flush()
    assert rid not in app.state.ui_compare_rows


def test_the_time_of_the_view_reads_them_again(app, cut, monkeypatch):
    _gesture(app)
    monkeypatch.setattr(view_resources, "pv_view_of", lambda vid: SimpleNamespace(ViewTime=4.0))
    app.state.ui_per_view_time_pulse = 1
    app.log.deferred.clear()
    app.state.flush()
    app.core.batcher.fire()
    assert "compare-rows" in app.log.deferred


def test_with_the_view_closed_nothing_is_armed(app, cut):
    app.compare["views"] = []
    app.core.lifecycle.emit("view_cuts", vid="view_1")
    assert app.core.batcher.armed == {}


def test_what_changes_the_reads_refreshes_the_matrix(app):
    p = app.p
    _add(app, p["poro"])
    for name, value in (("ui_loaded_rep_paths", [p["w1"]]),
                        ("ui_active_realization_by_array_by_view", {"view_1": {p["poro"]: 2}}),
                        ("fespp_render_panels", [])):
        app.log.deferred.clear()
        app.state[name] = value
        app.state.flush()
        assert "compare" in app.log.deferred, name


# ---- the extracts ---------------------------------------------------------------

@pytest.fixture
def extract(app, monkeypatch):
    """An extract of the grid in 3D view 1."""
    rep = cd._rep_path(app.tree, app.p["poro"])
    entry = {"path": "session://view_1/x1", "title": "Kept", "rep_path": rep, "vid": "view_1"}
    ctx = SimpleNamespace(selection=SimpleNamespace(extracts={"view_1": [entry]}), multi_view=app.views)
    monkeypatch.setattr(stats_supports, "_ctx", lambda: ctx)
    app.state["ui_session_rows__view_1"] = [
        {"path": entry["path"], "parent": "/data/_gridfolder_g", "title": "Kept", "kind": "extract",
         "type": "SelectionExtract", "visible": True, "info": "kept"},
        {"path": "derived://x", "parent": "/data", "title": "F", "kind": "derived",
         "type": "ContinuousProperty", "visible": False, "info": ""}]
    app.core.lifecycle.emit("session_rows", vid="view_1")
    app.state.flush()
    return entry


def test_an_extract_is_a_row_of_the_session_under_the_folder_of_the_parts(app, extract):
    rows = app.state.ui_compare_session_rows
    assert [r["path"] for r in rows] == [extract["path"]], "a formula is a leaf of the kind tree"
    row = rows[0]
    assert row["parent"] == f"{ct.PARTS_FOLDER}/xReservoir" == ct.extract_folder(app.tree, extract["path"])
    assert row["title"] == "Kept — 3D view 1" and row["visible"] is False and row["removable"] is False
    assert '<xReservoir type="RepFolder" title="Extract" family="Reservoir" noCheck="1"' \
        in app.state.ui_compare_tree_xml, "the tree has made its folder"
    assert extract["path"] not in app.compare["path_map"].values()


def test_the_eye_of_an_extract_adds_its_rows(app, extract):
    p = app.p
    _add(app, p["poro"])
    app.c.compare_session_eye({"path": extract["path"], "n": 1}, "compare_1")
    app.state.flush()
    assert app.state.ui_compare_parts == [extract["path"]]
    assert app.state.ui_compare_session_rows[0]["visible"] is True
    rid = _row_id(app, p["poro"], extract["path"])
    assert rid in app.state.ui_compare_rows
    assert app.state.ui_compare_rows[rid]["support_label"] == "Extract · Kept — 3D view 1"
    _eye(app, p["w1"])
    assert extract["path"] in app.state.ui_compare_parts, "another part's eye leaves it"
    app.c.compare_session_eye({"path": extract["path"], "n": 2}, "compare_1")
    app.state.flush()
    assert extract["path"] not in app.state.ui_compare_parts
    assert rid not in app.state.ui_compare_rows


def test_an_extract_renamed_reads_its_rows_again(app, extract):
    _add(app, app.p["poro"])
    app.c.compare_session_eye({"path": extract["path"], "n": 1}, "compare_1")
    app.state.flush()
    extract["title"] = "Renamed"
    app.log.deferred.clear()
    app.core.lifecycle.emit("session_rows", vid="view_1")
    assert "compare" in app.log.deferred
    rid = _row_id(app, app.p["poro"], extract["path"])
    assert "Renamed" in app.state.ui_compare_rows[rid]["support_label"]


def test_an_extract_deleted_in_its_view_leaves_with_its_rows(app, extract):
    _add(app, app.p["poro"])
    app.c.compare_session_eye({"path": extract["path"], "n": 1}, "compare_1")
    app.state.flush()
    stats_supports._ctx().selection.extracts["view_1"].clear()
    app.state["ui_session_rows__view_1"] = []
    app.core.lifecycle.emit("session_rows", vid="view_1")
    app.state.flush()
    assert app.state.ui_compare_parts == [] and app.state.ui_compare_session_rows == []
    assert "xReservoir" not in app.state.ui_compare_tree_xml


# ---- a new layout, a document ---------------------------------------------------

def test_a_document_keeps_the_parts_of_the_file_and_gives_them_back(app, extract):
    p = app.p
    _add(app, p["poro"])
    _eye(app, p["w1"])
    app.c.compare_session_eye({"path": extract["path"], "n": 1}, "compare_1")
    saved = app.c.session_compare_state()
    assert saved["parts"] == [p["w1"]], "an extract is its view's"
    app.state.ui_compare_parts = []
    app.c.session_compare_restore(saved)
    assert app.state.ui_compare_parts == [p["w1"]]
    assert list(compare_matrix._METRIC_KEYS) == app.kind_state("porosity")["visible_metrics"]


def test_a_document_older_than_the_parts_shows_the_mean_along_the_hole(app):
    kept = [m for m in compare_matrix._METRIC_KEYS if m not in ("Mean (L)", "Skewness")]
    app.c.session_compare_restore({"items": [], "kinds": {"porosity": {
        "baseline": "", "xplot_x": "", "xplot_y": "", "visible_metrics": kept}}})
    shown = app.kind_state("porosity")["visible_metrics"]
    assert "Mean (L)" in shown and "Skewness" not in shown
    app.c.session_compare_restore({"items": [], "parts": [], "kinds": {"porosity": {
        "baseline": "", "xplot_x": "", "xplot_y": "", "visible_metrics": kept}}})
    assert app.kind_state("porosity")["visible_metrics"] == kept, "a later one chose"


def test_a_document_gives_back_the_parts_the_file_still_holds():
    from tests.unit.test_assistant_wiring import FakeMV, _host
    tree, p = _tree()
    mv = FakeMV(kinds=("render",))
    host, server = _host(mv)
    server.context.tree = tree
    restored = []
    server.controller.session_compare_restore = restored.append
    host._restore_panels([{"id": "v", "kind": "compare", "title": "Statistics",
                           "items": [{"path": p["poro"]}], "parts": [p["w1"], "/gone"]}],
                         {}, lambda level, text: None)
    assert restored[-1]["parts"] == [p["w1"]]
    host._restore_panels([{"id": "v", "kind": "compare", "title": "Statistics", "items": []}],
                         {}, lambda level, text: None)
    assert "parts" not in restored[-1], "older than the parts: it must still say so"


def _axes(monkeypatch, reals=(), ts=()):
    """What a property can be read at."""
    monkeypatch.setattr(crossplot_dispatch, "axis_options", lambda *a: {
        "reals": [{"value": v} for v in reals], "ts": [{"value": v} for v in ts]})


def _pinned(app):
    return [(it["real"], it["ts"]) for it in app.items() if it["pinned"]]


def test_pin_all_pins_one_row_per_value_at_the_other_coordinate_of_the_row(app, monkeypatch):
    _axes(monkeypatch, reals=(0, 1), ts=(0, 1, 2))
    _add(app, app.p["poro"])
    uid = app.items()[0]["uid"]
    app.c.compare_set("real", [uid, 1])
    app.c.compare_set("pin_all", [uid, "ts"])
    assert _pinned(app) == [(1, 0), (1, 1), (1, 2)]
    assert [it["path"] for it in app.items()] == [app.p["poro"]] * 4
    assert app.items()[0]["pinned"] is False, "the row of the property itself stays"


def test_pin_all_twice_pins_nothing_more_and_says_so(app, monkeypatch):
    _axes(monkeypatch, ts=(0, 1))
    _add(app, app.p["poro"])
    uid = app.items()[0]["uid"]
    app.c.compare_set("pin_all", [uid, "ts"])
    app.c.compare_set("pin_all", [uid, "ts"])
    assert _pinned(app) == [(None, 0), (None, 1)]
    assert "every time step is already pinned" in app.state.ui_compare_note


def test_pin_all_on_a_property_with_no_such_value_says_so(app, monkeypatch):
    _axes(monkeypatch, ts=(0, 1))
    _add(app, app.p["poro"])
    app.c.compare_set("pin_all", [app.items()[0]["uid"], "real"])
    assert _pinned(app) == []
    assert "has no realization to pin" in app.state.ui_compare_note


def test_unpin_all_takes_the_pinned_rows_of_the_property_and_no_other(app, monkeypatch):
    _axes(monkeypatch, ts=(0, 1))
    _add(app, app.p["poro"], app.p["poro_h"])
    poro, other = app.items()
    app.c.compare_set("pin_all", [poro["uid"], "ts"])
    app.c.compare_set("pin_all", [other["uid"], "ts"])
    app.c.compare_set("unpin_all", poro["uid"])
    assert [(it["path"], it["pinned"]) for it in app.items()] == [
        (app.p["poro"], False), (app.p["poro_h"], False), (app.p["poro_h"], True), (app.p["poro_h"], True)]
    app.c.compare_set("unpin_all", poro["uid"])
    assert "has no pinned row" in app.state.ui_compare_note


def test_a_document_written_by_hand_may_say_part_of_a_kind(app):
    """What it leaves out is the default, and a baseline it does not name is no
    item's."""
    app.c.session_compare_restore({
        "items": [{"path": app.p["poro"]}, {"path": app.p["perm"], "real": 1}],
        "kinds": {"porosity": {"sort_key": "Mean", "dist_opts": {"nbins": 7}}}, "tab": "porosity"})
    state = app.kind_state("porosity")
    assert state["sort_key"] == "Mean" and state["sort_asc"] is True and state["baseline"] == ""
    assert state["dist_opts"]["nbins"] == 7 and state["dist_opts"]["mode"]
    assert state["visible_metrics"] == list(compare_matrix._METRIC_KEYS)
    assert app.state.ui_compare_note == ""
    assert [it["path"] for it in app.items()] == [app.p["poro"], app.p["perm"]]
    assert all(it["uid"] for it in app.items())


def test_a_document_s_item_not_read_is_read_and_waits_for_its_values(app):
    p = app.p
    app.c.session_compare_restore({"items": [{"path": p["soil"]}], "parts": [p["w1"]]})
    assert app.log.selections[-1][0][-1] == p["soil"]
    assert app.log.selections[-1][1]["shown"] is False, "born hidden"
    assert app.compare["pending"] == {p["soil"]: cd.LOADING}
    assert [it["path"] for it in app.items()] == [p["soil"]], "it is not scrubbed meanwhile"
    app.state.ui_loaded_array_paths = app.state.ui_loaded_array_paths + [p["soil"]]
    app.state.flush()
    assert app.compare["pending"] == {} and [it["path"] for it in app.items()] == [p["soil"]]


def test_a_document_s_reads_on_their_way_are_waited_for_and_not_called_failed(app):
    """A store's read goes step by step: what the document reads is selected
    and has not reached the reader when its views come back."""
    p = app.p
    app.state.selected_paths = app.state.selected_paths + [p["soil"]]
    app.state.fespp_data_selectors = [p["poro"]]
    app.state.flush()
    app.c.session_compare_restore({"items": [{"path": p["soil"]}]})
    assert app.compare["pending"] == {p["soil"]: cd.LOADING}
    assert app.state.ui_compare_note == ""
    assert [it["path"] for it in app.items()] == [p["soil"]]


def test_a_document_s_part_not_read_is_read(app):
    p = app.p
    app.state.selected_paths = [p["poro"], p["perm"]]
    app.state.flush()
    app.c.session_compare_restore({"items": [{"path": p["poro"]}], "parts": [p["w1"]]})
    assert app.log.selections[-1][0] == [p["poro"], p["perm"], p["w1"]]
    assert app.compare["pending"] == {}


def test_what_reached_the_reader_and_was_not_read_is_said(app):
    p = app.p
    app.state.selected_paths = app.state.selected_paths + [p["soil"]]
    app.state.fespp_data_selectors = list(app.state.selected_paths)
    app.state.flush()
    app.c.session_compare_restore({"items": [{"path": p["soil"]}]})
    assert app.compare["pending"] == {p["soil"]: cd.FAILED}
    assert "never brought the values in" in app.state.ui_compare_note


def test_a_restored_baseline_follows_its_item_to_its_new_uid(app):
    saved = {"items": [{"path": app.p["poro"], "uid": "i90"}, {"path": app.p["poro"], "uid": "i91", "pinned": True}],
             "parts": [], "kinds": {"porosity": {"baseline": "i91"}}, "tab": "porosity"}
    app.c.session_compare_restore(saved)
    new = app.items()[1]["uid"]
    assert new != "i91" and app.kind_state("porosity")["baseline"] == new


def test_an_entry_is_added_at_the_coordinates_it_names(app):
    app.compare_add([{"path": app.p["soil"], "real": None, "ts": 2}, {"nope": 1}])
    assert [(it["path"], it["ts"]) for it in app.items()] == [(app.p["soil"], 2)]


def test_a_late_second_click_on_remove_takes_nothing_else(app):
    _add(app, app.p["poro"], app.p["poro_h"])
    uid = next(it["uid"] for it in app.items() if it["path"] == app.p["poro"])
    app.c.compare_set("remove", uid)
    app.c.compare_set("remove", uid)
    assert [it["path"] for it in app.items()] == [app.p["poro_h"]]


def test_what_a_view_s_rows_read_compares_by_value(app, cut):
    """It is kept from one gesture to the next."""
    item = app.items()
    read = compare_rows.cuts_read(app.state, app.tree, item, app.core.ctx.grid_isolates, {})
    again = compare_rows.cuts_read(app.state, app.tree, item, app.core.ctx.grid_isolates, {})
    assert read == again and read == {
        f"{app.p['poro']}|view_1": {"cuts": {"mode": "range"}, "chain": [], "nan": None,
                                    "codes": (), "time": 0.0, "scene": []}}


def test_a_view_that_cuts_nothing_of_the_selection_reads_nothing(app, cut):
    assert compare_rows.cuts_read(app.state, app.tree, [], app.core.ctx.grid_isolates, {}) == {}
    assert compare_rows.cuts_read(app.state, app.tree, [{"path": app.p["poro_h"]}],
                                  app.core.ctx.grid_isolates, {}) == {}


def test_a_filter_older_than_its_row_goes_with_it(app, cut):
    """The row came with a read: no gesture ever told of that filter."""
    rid = f"{app.items()[0]['uid']}@view:view_1"
    assert rid in app.state.ui_compare_rows
    cut.cuts = {}
    assert _gesture(app) == ["compare-rows"]
    assert rid not in app.state.ui_compare_rows


def test_a_filter_moved_with_the_view_closed_then_moved_back_reads_again(app, cut):
    app.compare["views"] = []
    cut.chain = [{"name": "t1", "low": 0.1, "high": 0.2}]
    app.core.lifecycle.emit("view_cuts", vid="view_1")
    assert app.core.batcher.armed == {}
    app.open_compare()
    app.state.flush()
    assert _gesture(app) == [], "the view read what it draws as it opened"
    cut.chain = []
    assert _gesture(app) == ["compare-rows"]


# ---- a formula ------------------------------------------------------------------

@pytest.fixture
def formula(app):
    """A recipe on PORO's grid in the panel, and CODE read: neither has a kind."""
    p = app.p
    path = app.recipes.add(cd._rep_path(app.tree, p["poro"]), "F")
    app.state.selected_paths = app.state.selected_paths + [p["code"]]
    app.state.ui_loaded_array_paths = app.state.ui_loaded_array_paths + [p["code"]]
    app.compare_add([{"path": path}])
    app.state.flush()
    return path


def _held(app):
    return {it["path"] for it in app.items()}


def _boxes(app):
    return list(app.state["compare_tree_loaded__compare_1"])


def test_a_formula_stays_when_an_eye_opens_its_kind(app, formula):
    _eye(app, app.p["code"])
    assert _held(app) == {formula, app.p["code"]}


def test_a_formula_stays_when_a_tick_opens_its_kind(app, formula):
    app.state.compare_tick = {"vid": "compare_1", "paths": _boxes(app) + [_syn(app, app.p["sgas"])], "t": 1}
    app.state.flush()
    assert {formula, app.p["sgas"]} <= _held(app)


def test_a_formula_goes_by_the_kind_rule_and_comes_back_by_its_eye(app, formula):
    _eye(app, app.p["poro"])
    assert _held(app) == {app.p["poro"]}
    _eye(app, formula)
    assert _held(app) == {formula, app.p["code"]}, "its eye opens its kind, as any other"


def _eyeable(app):
    return list(app.state["compare_tree_eyeable__compare_1"])


def test_a_formula_has_no_box_and_its_eye_is_offered(app, formula):
    syn = _syn(app, formula)
    assert syn not in _boxes(app) and syn in _eyeable(app)
    assert 'noCheck="1"' in _leaf_of(app, formula)
    assert formula not in app.state.selected_paths


def test_a_folder_holding_only_formulas_has_no_box(app):
    p = app.p
    path = app.recipes.add(cd._rep_path(app.tree, p["poro"]), "F")
    xml, _map = ct.kind_tree_xml(app.tree, [path, p["poro"]], loaded={path, p["poro"]})
    no_kind = re.search(r'<k\d+ type="KindFolder" title="no kind"[^>]*>', xml).group(0)
    assert 'noCheck="1"' in no_kind
    rep = re.search(r'title="no kind"[^>]*>(<r\d+ [^>]*>)', xml).group(1)
    assert 'noCheck="1"' in rep
    porosity = re.search(r'<k\d+ type="KindFolder" title="porosity"[^>]*>', xml).group(0)
    assert "noCheck" not in porosity


def test_a_folder_holding_a_formula_ticks_what_it_can_read(app, formula):
    """A folder is every leaf under it: its properties are read, the recipe is
    nothing to read, and it stays in the panel."""
    p = app.p
    folder = _syn(app, p["sgas"]).rsplit("/", 2)[0]
    app.state.compare_tick = {"vid": "compare_1", "paths": _boxes(app) + [folder], "t": 1}
    app.state.flush()
    assert p["sgas"] in app.state.selected_paths and formula not in app.state.selected_paths
    assert {formula, p["sgas"]} <= _held(app)


def test_the_eye_of_a_formula_takes_its_row_out(app, formula):
    _eye(app, formula, on=False)
    assert _held(app) == set()
    assert _syn(app, formula) in _eyeable(app), "the recipe is still there"


def test_a_formula_outlives_its_grid_and_reads_again_with_it(app, formula, monkeypatch):
    def read(state, tree, source_registry, path, rep, real_idx=None, ts_idx=None):
        if (app.recipes.get(path) or {}).get("stale"):
            raise derived_props.DerivedError("The grid of 'F' is not loaded — check it again.")
        return np.linspace(0.1, 0.3, 11)

    monkeypatch.setattr(cd, "_values_for", read)
    uid = app.items()[0]["uid"]
    app.recipes.get(formula)["stale"] = True
    app.state.ui_loaded_rep_paths = []
    app.state.flush()
    assert _held(app) == {formula}
    row = app.state.ui_compare_rows[uid]
    assert row["metrics"] == {} and "is not loaded" in row["note"]
    assert _syn(app, formula) in _eyeable(app), "its leaf stays, its eye with it"
    assert "loadState" not in _leaf_of(app, formula), "it is nothing a tick would read"
    _eye(app, app.p["code"])
    assert formula in _held(app)
    app.recipes.get(formula)["stale"] = False
    app.state.ui_loaded_rep_paths = [app.p["w1"]]
    app.state.flush()
    assert app.state.ui_compare_rows[uid]["metrics"]


def test_a_formula_the_calculator_deleted_leaves(app, formula):
    del app.recipes.defs[formula]
    app.rebuild()
    app.state.flush()
    assert _held(app) == set()


# ---- a new version of an object -------------------------------------------------

def _new_version(app, path):
    """Another version of a property in the tree, under the same folder."""
    asm = app.tree._data_assembly
    node = asm.add_node_with_attrs("_poro_v2", asm.GetFirstNodeByPath(path.rsplit("/", 1)[0]), label="PORO",
                                   typeCode="2", title="PORO", type="ContinuousProperty",
                                   propertyKind="porosity", uom="m3/m3")
    return asm.GetNodePath(node)


def test_a_row_follows_a_new_version_of_its_object(app):
    """As a velocity model moves on: the new version's file is read, the rows
    follow, the old version is unticked for the new one, whose values come."""
    p = app.p
    _add(app, p["poro"])
    uid = app.items()[0]["uid"]
    new = _new_version(app, p["poro"])
    app.core.panel_trees.move(lambda q: new if q == p["poro"] else q)
    assert [(it["uid"], it["path"]) for it in app.items()] == [(uid, new)]
    assert app.compare["pending"] == {new: cd.LOADING}
    assert _syn(app, new) in app.state["compare_tree_selected__compare_1"], "its eye is open"
    app.state.assembly_rev = 1
    app.state.selected_paths = [new if q == p["poro"] else q for q in app.state.selected_paths]
    app.core.panel_trees.prune([p["poro"]])
    app.state.ui_loaded_array_paths = [p["perm"]]
    app.state.flush()
    assert [it["path"] for it in app.items()] == [new], "it waits for its values"
    assert app.state.ui_compare_rows[uid]["load"] == cd.LOADING
    app.state.ui_loaded_array_paths = [p["perm"], new]
    app.state.flush()
    assert app.compare["pending"] == {} and [it["path"] for it in app.items()] == [new]
    assert app.state.ui_compare_rows[uid]["metrics"]


def test_a_row_follows_a_new_version_with_the_view_closed(app):
    p = app.p
    _add(app, p["poro"])
    app.state.ui_compare_parts = [p["w1"]]
    app.compare["views"] = []
    new = _new_version(app, p["poro"])
    app.core.panel_trees.move(lambda q: new if q == p["poro"] else f"{q}-v2" if q == p["w1"] else q)
    assert [it["path"] for it in app.items()] == [new]
    assert app.state.ui_compare_parts == [f"{p['w1']}-v2"]


def test_an_item_no_longer_read_does_not_wait_for_a_new_version(app):
    """Unticked with the view closed, the item stayed: nobody selects the new
    version of it, so it must not wait for that read."""
    p = app.p
    _add(app, p["poro"])
    new = f"{p['poro']}-v2"
    app.state.selected_paths = []
    app.state.flush()
    app.core.panel_trees.move(lambda q: new if q == p["poro"] else q)
    app.state.flush()
    assert new not in {it["path"] for it in app.items()}


def test_a_version_already_read_is_not_waited_for(app):
    p = app.p
    _add(app, p["perm"], p["poro"])
    app.core.panel_trees.move(lambda q: p["perm"] if q == p["poro"] else q)
    assert app.compare["pending"] == {}


def test_a_formula_stays_on_its_grid_when_the_grid_has_a_new_version(app, formula):
    rep = cd._rep_path(app.tree, app.p["poro"])
    app.core.panel_trees.move(lambda q: q.replace(rep, f"{rep}-v2"))
    assert formula in _held(app) and app.compare["pending"] == {}


def test_what_waits_goes_on_waiting_when_a_file_is_read_while_the_tree_lists_it(app):
    p = app.p
    app.compare["pending"] = {p["soil"]: cd.LOADING, "/data/_gone": cd.LOADING}
    app.state.assembly_rev = 1
    app.state.flush()
    assert app.compare["pending"] == {p["soil"]: cd.LOADING}, "what the tree no longer lists is not waited for"


# ---- one question ---------------------------------------------------------------

@pytest.fixture
def nothing_read(app, monkeypatch):
    """Nothing is read, and one property is as much as a tick reads unasked; the
    folder of the kind porosity."""
    monkeypatch.setattr(tick_confirm, "MAX_TICK_LOAD", 1)
    app.state.selected_paths = []
    app.state.ui_loaded_array_paths = []
    app.state.ui_loaded_rep_paths = []
    app.state.flush()
    return _syn(app, app.p["poro"]).rsplit("/", 2)[0]


def test_a_folder_read_on_a_yes_is_not_asked_about_again(app, nothing_read):
    p = app.p
    app.state.compare_tick = {"vid": "compare_1", "paths": [nothing_read], "t": 1}
    app.state.flush()
    assert app.log.asked == []
    assert _held(app) == {p["poro"], p["poro_mr"], p["poro_h"]}
    assert set(app.compare["pending"]) == _held(app)


def test_what_is_said_from_outside_the_tree_asks_before_reading_a_lot(app, nothing_read):
    app.c.compare_tree_paths("compare_1", [nothing_read])
    assert app.log.asked == [3] and _held(app) == set()


def _session_road(app, store=(), closed="", said=None):
    """A tick goes the session's own road (app/features/tick_question).
    `store`: the rows a store holds; `closed`: why that store cannot be read
    now; `said`: the list the snackbar's sentences go to."""
    from fespp_on_trame.app.features import tick_question
    noop = lambda *a, **k: None    # noqa: E731
    apply_selection, _ask, ask_tick, _drop, tree_tick = tick_question.register(
        SimpleNamespace(state=app.state, controller=app.c, tree=app.tree,
                        ctx=SimpleNamespace(store_closed=lambda: closed),
                        active_data_source=SimpleNamespace(
                            store_paths=lambda paths: {q for q in paths if q in set(store)}),
                        panel_trees=app.core.panel_trees,
                        mv=app.core.mv),
        _expand_blocked_well_trajectories=lambda paths: (paths, {}), _is_object_path=lambda q: True,
        _is_property_path=lambda q: node_facts.is_property(app.tree, q), _panel_reads=set(),
        _prev_selected={"paths": list(app.state.selected_paths)},
        _say=noop if said is None else said.append, _set_selectors=noop)
    app.road.apply_selection, app.road.ask_tick, app.road.tree_tick = apply_selection, ask_tick, tree_tick


def test_on_the_session_s_road_a_folder_asks_once_and_a_yes_reads_it(app, nothing_read):
    p = app.p
    _session_road(app)
    app.state.compare_tick = {"vid": "compare_1", "paths": [nothing_read], "t": 1}
    app.state.flush()
    assert app.state.ui_tick_confirm and _held(app) == set(), "nothing goes in before the answer"
    app.c.tick_confirm_answer(True)
    app.state.flush()
    assert not app.state.ui_tick_confirm, "no second question"
    assert _held(app) == {p["poro"], p["poro_mr"], p["poro_h"]}
    assert {p["poro"], p["poro_mr"], p["poro_h"]} <= set(app.state.selected_paths)


def test_on_the_session_s_road_a_no_leaves_nothing(app, nothing_read):
    _session_road(app)
    app.state.compare_tick = {"vid": "compare_1", "paths": [nothing_read], "t": 1}
    app.state.flush()
    app.c.tick_confirm_answer(False)
    app.state.flush()
    assert _held(app) == set() and app.state.selected_paths == []


_CLOSED = "Disconnected from the OSDU server: what is shown stays."


def test_a_row_of_a_closed_store_is_not_read_and_the_reader_is_told_why(app):
    p = app.p
    said = []
    _session_road(app, store=[p["sgas"], p["poro"]], closed=_CLOSED, said=said)
    before = list(app.state.selected_paths)
    app.road.apply_selection(before + [p["sgas"]], push=True)
    assert app.state.selected_paths == before, "the box goes back where it was"
    assert said == [_CLOSED]
    app.road.apply_selection([q for q in before if q != p["poro"]], push=True)
    assert p["poro"] not in app.state.selected_paths, "an untick asks nothing of the store"
    assert said == [_CLOSED]


def test_a_closed_store_refuses_no_row_of_the_files(app):
    p = app.p
    said = []
    _session_road(app, store=[p["poro"]], closed=_CLOSED, said=said)
    app.road.apply_selection(list(app.state.selected_paths) + [p["sgas"]], push=True)
    assert p["sgas"] in app.state.selected_paths and said == []


def test_an_open_store_reads_its_own_rows(app):
    p = app.p
    said = []
    _session_road(app, store=[p["sgas"]], closed="", said=said)
    app.road.apply_selection(list(app.state.selected_paths) + [p["sgas"]], push=True)
    assert p["sgas"] in app.state.selected_paths and said == []


def test_on_the_session_s_road_a_formula_stays_when_a_tick_opens_its_kind(app, formula):
    p = app.p
    _session_road(app)
    app.state.compare_tick = {"vid": "compare_1", "paths": _boxes(app) + [_syn(app, p["sgas"])], "t": 1}
    app.state.flush()
    assert {formula, p["sgas"]} <= _held(app)
    assert formula not in app.state.selected_paths, "a recipe is no node to select"
    assert _syn(app, formula) in _eyeable(app)


# ---- the baseline, a pin --------------------------------------------------------

def test_the_tree_sets_the_baseline_of_the_kind_of_the_property(app, monkeypatch):
    p = app.p
    _axes(monkeypatch, ts=(0, 1))
    _together(app, p["perm"], p["poro"])
    poro = next(it["uid"] for it in app.items() if it["path"] == p["poro"])
    app.c.compare_set("pin", poro)
    copy = app.items()[-1]["uid"]
    app.c.compare_set("baseline", copy)
    app.state.flush()
    assert app.kind_state("porosity")["baseline"] == copy
    _menu(app, "compare-baseline", p["perm"])
    assert app.kind_state("porosity")["baseline"] == copy, "the tab's own stays"
    perm = next(it["uid"] for it in app.items() if it["path"] == p["perm"])
    assert app.kind_state("permeability")["baseline"] == perm
    assert app.state.ui_compare_tab == "permeability", "its tab shows it"


def test_a_baseline_is_of_the_kind_of_its_item_whichever_tab_is_shown(app):
    p = app.p
    _together(app, p["perm"], p["poro"])
    app.state.ui_compare_tab = "porosity"       # the reader's click on that tab
    app.state.flush()
    poro = next(it["uid"] for it in app.items() if it["path"] == p["poro"])
    perm = next(it["uid"] for it in app.items() if it["path"] == p["perm"])
    app.c.compare_set("baseline", poro)
    app.c.compare_set("baseline", perm)
    app.state.flush()
    assert app.kind_state("porosity")["baseline"] == poro and app.kind_state("permeability")["baseline"] == perm
    app.c.compare_set("baseline", "no such row")
    assert app.kind_state("porosity")["baseline"] == "", "a row that is not there: the tab's own goes"
    assert app.kind_state("permeability")["baseline"] == perm


def test_every_column_of_the_matrix_sorts_the_tab(app):
    """The total count and the representation sort the tab as a metric does;
    a column the matrix does not have leaves it in selection order."""
    _add(app, app.p["poro"])
    kind = app.state.ui_compare_tab
    for key in ("Total", "Representation", "Mean"):
        app.c.compare_set("sort", [key, False])
        assert app.kind_state(kind)["sort_key"] == key
        assert app.state.ui_compare_sort_key == key and app.state.ui_compare_sort_asc is False
    app.c.compare_set("sort", ["no such column", True])
    assert app.kind_state(kind)["sort_key"] == ""


def test_a_pin_needs_a_realization_or_a_time_step(app):
    _add(app, app.p["poro"])
    app.c.compare_set("pin", app.items()[0]["uid"])
    assert _pinned(app) == [] and "nothing to pin a copy at" in app.state.ui_compare_note


def test_a_pin_at_a_coordinate_already_pinned_is_refused_and_said(app, monkeypatch):
    _axes(monkeypatch, ts=(0, 1))
    _add(app, app.p["poro"])
    uid = app.items()[0]["uid"]
    app.c.compare_set("ts", [uid, 1])
    app.c.compare_set("pin", uid)
    assert _pinned(app) == [(None, 1)]
    app.c.compare_set("pin", uid)
    assert _pinned(app) == [(None, 1)] and "has a pinned row at this" in app.state.ui_compare_note
    app.c.compare_set("ts", [uid, 0])
    app.c.compare_set("pin", uid)
    assert _pinned(app) == [(None, 1), (None, 0)]


# ---- a part let go with no view open ---------------------------------------------

def test_a_part_unloaded_with_the_view_closed_is_gone_when_it_opens(app, extract):
    p = app.p
    _add(app, p["poro"])
    _eye(app, p["w1"])
    app.c.compare_session_eye({"path": extract["path"], "n": 1}, "compare_1")
    app.state.flush()
    app.compare["views"] = []
    app.state.selected_paths = [q for q in app.state.selected_paths if q != p["w1"]]
    app.core.panel_trees.prune([p["w1"]])
    assert p["w1"] in app.state.ui_compare_parts, "no panel to let it go"
    app.open_compare()
    app.state.flush()
    assert app.state.ui_compare_parts == [extract["path"]], "an extract is its view's"
    assert _row_id(app, p["poro"], p["w1"]) not in app.state.ui_compare_rows


def test_a_document_does_not_read_again_what_the_session_let_go(app):
    p = app.p
    _eye(app, p["w1"])
    app.state.selected_paths = [q for q in app.state.selected_paths if q != p["w1"]]
    assert app.c.session_compare_state()["parts"] == []


# ---- what a feature takes, what closing writes ------------------------------------

@pytest.mark.parametrize("module", ["compare", "compare_tree", "compare_parts", "volumetrics", "node_helpers"])
def test_a_feature_takes_no_name_it_does_not_read(module):
    feature = ast.parse(_package_file("app", "features", f"{module}.py"))
    register = next(n for n in feature.body if isinstance(n, ast.FunctionDef) and n.name == "register")
    read = {n.id for n in ast.walk(register) if isinstance(n, ast.Name)}
    assert [a.arg for a in register.args.kwonlyargs if a.arg not in read] == []


def test_closing_the_view_writes_nothing_nobody_reads():
    from fespp_on_trame.app.core import state_registry
    assert "dist_kinds" not in state_registry.COMPARE_PAYLOAD


# ---- through the session door -----------------------------------------------------

def _door(restore):
    """The session door over a 3D view, with the opener it calls."""
    from tests.unit.test_assistant_wiring import FakeMV, _host
    tree, p = _tree()
    mv = FakeMV(kinds=("render",))
    host, server = _host(mv)
    server.context.tree = tree
    server.controller.session_compare_restore = restore
    return SimpleNamespace(host=host, server=server, mv=mv, p=p, said=[])


def test_the_report_calls_a_view_with_no_title_by_what_the_reader_calls_it():
    def broken(saved):
        raise ValueError("invalid literal")

    door = _door(broken)
    door.host._restore_panels([{"id": "v", "kind": "compare", "items": [{"path": door.p["poro"]}]}],
                              {}, lambda level, text: door.said.append((level, text)))
    assert ("warn", "Statistics: not restored (invalid literal).") in door.said


def _extracts_feature(monkeypatch):
    """The session's side of the extracts, over proxies that do nothing."""
    from paraview import servermanager
    from fespp_on_trame.app.features import extracts as feature

    class Proxy:
        SMProxy = None

        def UpdatePipeline(self):
            pass

        def GetClientSideObject(self):
            return SimpleNamespace(GetOutputDataObject=lambda port: None)

        def GetDataInformation(self):
            return SimpleNamespace(GetNumberOfCells=lambda: 3, GetNumberOfPoints=lambda: 0)

    noop = lambda *a, **k: None    # noqa: E731
    monkeypatch.setattr(feature, "pvsimple", SimpleNamespace(
        ExtractBlock=lambda **k: Proxy(), ExtractSelection=lambda **k: Proxy(), Show=lambda *a: Proxy(),
        Hide=noop, Delete=noop))
    monkeypatch.setattr(servermanager, "sources",
                        SimpleNamespace(CompositeDataIDSelectionSource=lambda **k: object()), raising=False)
    core = SimpleNamespace(
        state=FakeState(), controller=FakeController(), eyes=None, scheduler=None, derived_store=None,
        ctx=SimpleNamespace(assembly_index=SimpleNamespace(flat_indices=lambda rep, subtree=False: [7])),
        active_data_source=SimpleNamespace(get_display_source=Proxy), displays=SimpleNamespace(add=noop, remove=noop),
        selection=SimpleNamespace(cells={}, origin={}, extracts={}, points_of=lambda vid: set(), clear_origin=noop))
    feature.register(
        core, _derived_fanout=noop, _derived_forget=noop, _display_title=lambda *a: "Geogrid", _extract_cells=noop,
        _extract_colour=noop, _extract_layout=noop, _extract_seq=[0], _globe_scene=noop, _live_render_vids=noop,
        _nav_note=noop, _pdc_flats=lambda output, rep: [7], _publish_session_rows=noop,
        _push_active_array_label=noop, _pv_view_of=lambda vid: object(), _refresh_calculator=noop,
        _refresh_values=noop, _rep_path_of=lambda row: row, _row_of_rep=lambda rep: rep)
    return core.controller


def test_the_extracts_of_a_document_say_what_they_came_back_as(monkeypatch):
    c = _extracts_feature(monkeypatch)
    back = c.session_restore_extracts("view_1", [
        {"path": "session://view_1/x2", "row": "/g", "cells": [[0, [[1, 3]]]]},
        {"path": "session://view_1/x3", "row": "/g", "cells": [[0, [[5, 6]]]]},
        {"path": "session://view_1/x5", "row": "/g", "cells": []}])
    assert back == {"session://view_1/x2": "session://view_1/x1", "session://view_1/x3": "session://view_1/x2"}
    assert [e["path"] for e in c.session_view_extracts("view_1")] == ["session://view_1/x1", "session://view_1/x2"]


# ---- a gesture on a 3D view reads the rows of that view, and only them ----------

def test_a_gesture_on_a_view_reads_no_pinned_time_step_again(app, cut, monkeypatch):
    """The figures of the items and their curves are kept, for the matrix and
    for the overlay alike."""
    p = app.p
    cd.clear_reads()
    reads = []

    def read(state, tree, source_registry, path, rep, real_idx=None, ts_idx=None):
        reads.append((path, ts_idx))
        return np.linspace(0.1, 0.3, 11)

    monkeypatch.setattr(cd, "_values_for", read)
    _axes(monkeypatch, ts=(0, 1, 2))
    uid = app.items()[0]["uid"]
    app.c.compare_set("pin_all", [uid, "ts"])
    app.state.flush()
    assert {t for q, t in reads if q == p["poro"]} == {None, 0, 1, 2}
    reads.clear()
    cut.cuts = {"mode": "range", "volumes": [[[0, 1], [0, 1], [0, 1]]]}
    assert _gesture(app) == ["compare-rows"]
    assert reads == [], "the view's rows alone were read"
    cd.clear_reads()


def test_the_figures_of_the_overlay_follow_a_new_read_of_the_file(app, monkeypatch):
    cd.clear_reads()
    p = app.p
    reads = []

    def read(state, tree, source_registry, path, rep, real_idx=None, ts_idx=None):
        reads.append(path)
        return np.linspace(0.1, 0.3, 11)

    monkeypatch.setattr(cd, "_values_for", read)
    _add(app, p["poro"])
    assert cd.TRACES and reads
    cd.clear_reads()
    assert not cd.TRACES and not cd.READS


# ---- a cut of the whole scene ---------------------------------------------------

class _Crop:
    def __init__(self, boxes):
        self.boxes = boxes


def test_a_box_of_the_whole_scene_moved_reads_the_view_s_rows_again(app, cut):
    """A scene cut says nothing in the isolate, or there is no isolate at all."""
    scene = SimpleNamespace(crop=_Crop([[[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]]))
    app.core.ctx.blockscope_scenes = {"view_1": scene}
    assert _gesture(app) == ["compare-rows"], "the scene was cut"
    assert _gesture(app) == [], "nothing moved"
    scene.crop = _Crop([[[0.0, 2.0], [0.0, 1.0], [0.0, 1.0]]])
    assert _gesture(app) == ["compare-rows"], "a box moved"
    scene.crop = None
    assert _gesture(app) == ["compare-rows"], "the scene whole again"


def test_a_scene_cut_with_no_isolate_is_a_row_that_moves_with_its_boxes(app, cut):
    del app.core.ctx.grid_isolates[("view_1", cd._rep_path(app.tree, app.p["poro"]))]
    scene = SimpleNamespace(crop=_Crop([[[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]]))
    app.core.ctx.blockscope_scenes = {"view_1": scene}
    read = compare_rows.cuts_read(app.state, app.tree, app.items(), {}, app.core.ctx.blockscope_scenes)
    assert read == {f"{app.p['poro']}|view_1": {"scene": scene.crop.boxes, "time": 0.0}}
    assert _gesture(app) == ["compare-rows"]
    scene.crop = _Crop([[[0.0, 2.0], [0.0, 1.0], [0.0, 1.0]]])
    assert _gesture(app) == ["compare-rows"]


# ---- a folder of parts asks like a folder of properties --------------------------

def _no_part_read(app, monkeypatch):
    """Two parts of a grid are more than a tick reads unasked; nothing is read."""
    monkeypatch.setattr(tick_confirm, "MAX_TICK_LOAD", 1)
    app.state.selected_paths = []
    app.state.ui_loaded_array_paths = []
    app.state.ui_loaded_rep_paths = []
    app.state.flush()
    _session_road(app)
    return ct.PARTS_FOLDER


def test_a_tick_on_the_folder_of_the_parts_asks_before_it_reads_them(app, monkeypatch):
    folder = _no_part_read(app, monkeypatch)
    p = app.p
    app.state.compare_tick = {"vid": "compare_1", "paths": [folder], "t": 1}
    app.state.flush()
    assert app.state.ui_tick_confirm["title"] == "Read 2 objects?", "they are no properties"
    assert app.state.selected_paths == [] and app.state.ui_compare_parts == []
    app.c.tick_confirm_answer(True)
    app.state.flush()
    assert not app.state.ui_tick_confirm, "no second question"
    assert {p["w1"], p["north"]} <= set(app.state.selected_paths)
    assert set(app.state.ui_compare_parts) == {p["w1"], p["north"]}


def test_a_no_to_the_folder_of_the_parts_leaves_nothing(app, monkeypatch):
    folder = _no_part_read(app, monkeypatch)
    app.state.compare_tick = {"vid": "compare_1", "paths": [folder], "t": 1}
    app.state.flush()
    app.c.tick_confirm_answer(False)
    app.state.flush()
    assert app.state.selected_paths == [] and app.state.ui_compare_parts == []


def test_a_tick_on_a_part_asks_nothing_under_the_cap(app, monkeypatch):
    _no_part_read(app, monkeypatch)
    monkeypatch.setattr(tick_confirm, "MAX_TICK_LOAD", 20)
    p = app.p
    app.state.compare_tick = {"vid": "compare_1", "paths": [_syn(app, p["w1"])], "t": 1}
    app.state.flush()
    assert not getattr(app.state, "ui_tick_confirm", None)
    assert p["w1"] in app.state.selected_paths


def test_the_data_tree_counts_the_properties_and_not_the_parts(app, monkeypatch):
    """A tick in the data tree: a part is drawn in the 3D view it came from, no
    row maps it."""
    _no_part_read(app, monkeypatch)
    p = app.p
    app.road.apply_selection([p["w1"], p["north"]])
    assert not getattr(app.state, "ui_tick_confirm", None)


def test_the_question_says_objects_when_it_counts_more_than_properties():
    assert tick_confirm.question(25, shown=False, objects=True)["title"] == "Read 25 objects?"
    assert tick_confirm.question(25, shown=False)["title"] == "Read 25 properties?"
    assert tick_confirm.question(25, remote=True, objects=True)["title"].startswith("Download 25 objects")


def test_the_3d_view_in_use_is_given_the_eye_asked_for_last(app, monkeypatch):
    """An eye brings every property of its kind the session holds, and the 3D
    view in use paints a grid by the last it is given: the one asked for."""
    from fespp_on_trame.app.views import per_view_state
    p = app.p
    monkeypatch.setattr(per_view_state, "_LIVE", {"view_1"})
    given = []
    app.core.eyes = SimpleNamespace(get=lambda vid: [], set=lambda vid, paths: given.append(list(paths)))
    app.state.fespp_last_render_panel_id = "view_1"
    app.state.selected_paths = [p["poro"], p["poro_h"], p["perm"], p["w1"], p["north"]]
    app.state.ui_loaded_array_paths = [p["poro"], p["poro_h"], p["perm"]]
    app.state.flush()
    _eye(app, p["poro"])
    assert given, "the 3D view in use follows"
    assert set(given[-1]) == {p["poro"], p["poro_h"]}, "the kind came with it"
    assert given[-1][-1] == p["poro"], "the eye asked for is given last"


def test_the_own_velocity_model_is_listed_in_no_tree_even_read(app):
    """What `ui_model_tree_rows` holds — a velocity model the session generated — is
    not in the Statistics tree, the session holding it or not."""
    p = app.p
    hidden = p["poro_h"].rsplit("/", 2)[0]
    app.state.ui_model_tree_rows = [hidden]
    app.state.selected_paths = [p["poro"], p["poro_h"], p["perm"], p["w1"], p["north"]]
    app.state.ui_loaded_array_paths = [p["poro"], p["poro_h"], p["perm"]]
    app.rebuild(app.items())
    app.state.flush()
    listed = set(app.compare["path_map"].values())
    assert p["poro"] in listed and p["poro_h"] not in listed
