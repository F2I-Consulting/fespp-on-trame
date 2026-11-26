"""app/features/view_doors: "Add to Well Log view" lights the node it sent in
the log view's own tree (`welllog_tree_active__<panel>`), unfolded to there
by the tree — a log, a frame or a wellbore, whether the log view was open or
opened by the gesture."""
import types

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.app.features import view_doors
from fespp_on_trame.engine.tree import Tree


class _Controller:
    def __init__(self):
        self.fns = {}

    def set(self, name):
        def deco(fn):
            self.fns[name] = fn
            return fn
        return deco

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class _State(dict):
    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value

    def change(self, *_names):
        return lambda fn: fn


class _Views:
    def __init__(self):
        self.panels = []

    def add_view(self, kind):
        if not self.panels:
            self.panels.append("welllog_1")

    def panel_ids_of_kind(self, kind):
        return list(self.panels) if kind == "welllog" else []


def _session():
    asm = FakeDataAssembly()
    well = asm.add_node_with_attrs("_wb1", 0, title="55/33-A-4", label="Wellbore", type="Wellbore", typeCode="1")
    frame = asm.add_node_with_attrs("_frame1", well, title="LOG", label="Frame", type="Frame", typeCode="1")
    log = asm.add_node_with_attrs("_log1", frame, title="GR", label="GR", type="ContinuousProperty", typeCode="4")
    tree = Tree(None)
    tree.set_tree(asm)
    state, ctrl, views = _State(), _Controller(), _Views()
    read = []

    def tick_read(want, on_cancel=None, on_go=None):
        read.append(list(want))
        state["selected_paths"] = sorted(set(state.get("selected_paths") or []) | set(want))
        on_go()

    core = types.SimpleNamespace(state=state, controller=ctrl, tree=tree, activation=None, mv=lambda: views)
    view_doors.register(core, _panel_tick_read=tick_read, _refresh_welllog=lambda: None,
                        _xml_open_from_path=lambda *a: None)
    paths = {name: tree.find_path(nid) for name, nid in (("well", well), ("frame", frame), ("log", log))}
    return state, ctrl.fns["add_to_welllog"], paths


def test_the_frame_sent_is_lit_in_the_log_view_it_opened():
    state, add, paths = _session()
    add(paths["frame"])
    assert state["welllog_tree_active__welllog_1"] == paths["frame"]
    assert paths["well"] in state["ui_welllog_wells"]


def test_a_log_then_its_wellbore_each_lit_in_turn():
    state, add, paths = _session()
    add(paths["log"])
    assert state["welllog_tree_active__welllog_1"] == paths["log"]
    add(paths["well"])
    assert state["welllog_tree_active__welllog_1"] == paths["well"]
