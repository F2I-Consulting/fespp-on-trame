"""The Assistant's wiring into the application.

A session saved with the Assistant open comes back with its panel and its
layout; the panel binds its four gestures; the view kind, the
FESPP_ASSISTANT switch and the three places a widget is registered agree;
the headless probe holds a reply to the expectations of its step.

No trame, no ParaView (the conftest stubs): the session adapter runs on a
fake state, dockview manager and controller; the two helpers of
`__main__` are compiled alone, because importing the module starts the
whole application."""
import ast
import asyncio
import importlib
import json
import re
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "widgets" / "session"))

from fespp_on_trame.app.session_host import FesppSessionHost  # noqa: E402
sys.path.insert(0, str(ROOT / "tests" / "visual" / "runner"))  # the driver lives with the tests (Q9)
import scenario  # noqa: E402
from fespp_on_trame.ia.nlu import catalogue  # noqa: E402
from tests.unit.fake_assembly import FakeDataAssembly  # noqa: E402


class FakeState(dict):
    """trame's state as the adapters use it.

    Attributes and items alike, None for what was never set."""

    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __missing__(self, k):
        return None

    def flush(self):
        pass

    def dirty(self, *_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


_LABELS = {"render": "3D view", "assistant": "Assistant", "health": "Data health", "compare": "Statistics"}


class FakeMV:
    """The dockview manager.

    Panel ids are `view_<n>`, a singleton kind already open is focused
    rather than opened again, a restored layout is recorded, and so is
    where a split panel was put (`placed_at`)."""

    def __init__(self, kinds=("render",), count=0):
        self._titles, self._kinds, self._n = {}, {}, count
        self._layout = None
        self._place = None
        self.restored_layout = None
        self.placed_at = {}
        for k in kinds:
            self.add_view(kind=k)

    @contextmanager
    def placed(self, direction, reference_panel_id=None):
        self._place = (direction, reference_panel_id) if direction else None
        try:
            yield
        finally:
            self._place = None

    def add_view(self, direction=None, kind="render", reference_panel_id=None):
        if kind != "render":
            for pid, k in self._kinds.items():
                if k == kind:
                    return pid
        if direction is None and self._place:
            direction, reference_panel_id = self._place
        self._n += 1
        pid = f"view_{self._n}"
        self._titles[pid] = _LABELS[kind] if kind != "render" else f"3D view {self._n}"
        self._kinds[pid] = kind
        if direction:
            self.placed_at[pid] = (direction, reference_panel_id)
        return pid

    def kind_of(self, pid):
        return self._kinds.get(pid, "render")

    def view_ids(self):
        return [p for p, k in self._kinds.items() if k == "render"]

    def panel_ids_of_kind(self, kind):
        return [p for p, k in self._kinds.items() if k == kind]

    def retitle(self, pid, title):
        self._titles[pid] = title

    def restore_layout(self, layout):
        self.restored_layout = layout

    def get_pv_view(self, vid):
        return None


class FakeCtrl:
    """Every controller the adapter calls, recorded by name.

    The openers open their panel. `assistant_on=False` is an assistant
    switched off: its opener opens nothing (`__main__._wire_assistant`)."""

    def __init__(self, mv, assistant_on=True):
        self.calls = []
        self.mv = mv
        self.assistant_on = assistant_on

    def __getattr__(self, name):
        def call(*args, **kw):
            self.calls.append(name)
        return call

    def open_assistant(self):
        self.calls.append("open_assistant")
        return self.mv.add_view(kind="assistant") if self.assistant_on else None

    def open_health(self):
        # boot's opener returns nothing: the adapter finds the new panel.
        self.calls.append("open_health")
        self.mv.add_view(kind="health")


def _host(mv, assistant_on=True):
    server = types.SimpleNamespace(state=FakeState(),
                                   context=types.SimpleNamespace(multi_view=mv, tree=None))
    server.controller = FakeCtrl(mv, assistant_on)
    return FesppSessionHost(server), server


def _layout(ids):
    """A dockview layout (`toJSON()`) placing the panels `ids` side by side."""
    return {"grid": {"root": {"type": "branch", "data": [
                {"type": "leaf", "data": {"views": [i], "activeView": i, "id": str(n)}}
                for n, i in enumerate(ids)]}},
            "panels": {i: {"id": i, "contentComponent": f"{i}_template"} for i in ids}}


def _saved_with_the_assistant():
    """What saving a session holding a 3D view and the Assistant writes."""
    mv = FakeMV(kinds=("render", "assistant"))
    mv._layout = _layout(["view_1", "view_2"])
    host, _ = _host(mv)
    return host.collect()


# ------------------------------------------------------------ session
def test_session_saved_with_the_assistant_keeps_its_place_not_its_conversation():
    doc = _saved_with_the_assistant()
    views = {v["id"]: v for v in doc["views"]}
    assert views["view_2"] == {"id": "view_2", "kind": "assistant", "title": "Assistant"}
    assert set(doc["layout"]["panels"]) == {"view_1", "view_2"}


def test_session_restore_reopens_the_assistant_through_its_door_with_the_layout():
    doc = _saved_with_the_assistant()
    # A new session: its first 3D view is open and its id counter is
    # further on than the saved one.
    mv = FakeMV(kinds=("render",), count=4)
    host, server = _host(mv)
    said = []
    host.restore(doc, lambda level, text: said.append((level, text)))
    assert server.controller.calls.count("open_assistant") == 1
    new = mv.panel_ids_of_kind("assistant")
    assert new == ["view_6"]
    # Restored without any warning, and the layout with it.
    assert [s for s in said if s[0] != "ok"] == []
    assert ("ok", "1 panel(s) restored.") in said
    assert mv.restored_layout is not None
    assert set(mv.restored_layout["panels"]) == {"view_5", "view_6"}
    assert mv.restored_layout["panels"]["view_6"]["contentComponent"] == "view_6_template"
    assert mv._titles["view_6"] == "Assistant"


def test_session_restore_says_an_assistant_switched_off_is_not_restored():
    doc = _saved_with_the_assistant()
    mv = FakeMV(kinds=("render",))
    host, _ = _host(mv, assistant_on=False)
    said = []
    host.restore(doc, lambda level, text: said.append((level, text)))
    assert mv.panel_ids_of_kind("assistant") == []
    assert ("warn", "Assistant: not restored.") in said
    assert any(level == "warn" and "come back as tabs" in text for level, text in said)
    assert mv.restored_layout is None


class _Conversation:
    """The Assistant's controller as a restore reaches it (`context.assistant`).

    Records what it was asked to forget, in order."""

    def __init__(self, keeps_messages=True):
        self.calls = []
        if keeps_messages:
            self.clear_undo = lambda: self.calls.append("clear_undo")

    def clear(self):
        self.calls.append("clear")


@pytest.mark.parametrize("keeps_messages, dropped", [(True, ["clear_undo"]), (False, ["clear"])])
def test_session_restore_drops_the_assistant_undo_of_the_views_it_overwrites(
        keeps_messages, dropped):
    """A restore drops the Assistant's undo stack before touching any view.

    The restored 3D views keep their ids, so an Undo recorded before the
    restore would write the old visibility over the restored one. The undo
    stack is dropped (the conversation too, when the controller cannot
    drop the stack alone) before the first view is touched."""
    doc = _saved_with_the_assistant()
    mv = FakeMV(kinds=("render", "assistant"))
    host, server = _host(mv)
    conv = _Conversation(keeps_messages)
    server.context.assistant = conv
    seen = []
    server.controller.session_select = lambda paths: seen.append(list(conv.calls))
    said = []
    host.restore(doc, lambda level, text: said.append((level, text)))
    assert conv.calls == dropped
    assert seen and seen[0] == dropped
    assert [s for s in said if s[0] != "ok"] == []


def test_session_restore_says_in_the_log_an_undo_it_could_not_drop(capsys):
    doc = _saved_with_the_assistant()
    mv = FakeMV(kinds=("render",))
    host, server = _host(mv)

    class Broken:
        def clear_undo(self):
            raise RuntimeError("no state")

    server.context.assistant = Broken()
    said = []
    host.restore(doc, lambda level, text: said.append((level, text)))
    assert "undo stack could not be dropped: no state" in capsys.readouterr().out
    assert ("ok", "1 panel(s) restored.") in said


def test_session_restore_opens_the_assistant_after_the_panels_that_read_data():
    mv = FakeMV(kinds=("render",))
    host, server = _host(mv)
    said = []
    out = host._restore_panels(
        [{"id": "view_7", "kind": "assistant", "title": "Assistant"},
         {"id": "view_8", "kind": "health", "title": "Data health"}],
        {}, lambda level, text: said.append((level, text)))
    calls = [c for c in server.controller.calls if c.startswith("open_")]
    assert calls == ["open_health", "open_assistant"]
    assert out == {"view_8": "view_2", "view_7": "view_3"}
    assert said == [("ok", "2 panel(s) restored.")]


def test_a_document_places_a_view_beside_the_one_before_it():
    """The PO's document of 22/10: the 3D view, Statistics to its right.
    `place` on a paragraph splits the view that precedes it in the
    document — a 2nd 3D view through the manager's own `add_view`, a
    panel through its door inside a `placed` block; the session's first
    3D view stays where it is."""
    mv = FakeMV(kinds=("render",))
    host, _ = _host(mv)
    said = []
    host.restore({"partial": True, "views": [
        {"kind": "render", "place": "below"},
        {"kind": "render", "place": "below"},
        {"kind": "health", "place": "right"}]},
        lambda level, text: said.append((level, text)))
    assert mv.placed_at == {"view_2": ("below", "view_1"), "view_3": ("right", "view_2")}
    assert [s for s in said if s[0] != "ok"] == []


# ------------------------------------------------------------ the panel
def test_the_view_kind_is_a_singleton_named_like_its_door():
    tree = ast.parse((ROOT / "fespp_on_trame/app/views/views_config.py").read_text(encoding="utf-8"))
    kinds = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", None) == "VIEW_KINDS" for t in n.targets))
    entry = next(v for k, v in zip(kinds.keys, kinds.values) if k.value == "assistant")
    spec = {k.value: v for k, v in zip(entry.keys, entry.values)}
    assert spec["label"].value == "Assistant"
    assert spec["needs_render_view"].value is False
    assert spec["singleton"].value is True
    assert spec["build"].id == "_build_assistant"
    build = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_build_assistant")
    imports = [n for n in ast.walk(build) if isinstance(n, ast.ImportFrom)]
    assert [(i.module, [a.name for a in i.names]) for i in imports] == [
        ("fespp_on_trame.app.views.assistant_panel", ["AssistantPanel"])]


def test_the_panel_binds_the_four_gestures(monkeypatch):
    seen = {}

    class Widget:
        def __init__(self, **kw):
            seen.update(kw)

    pkg = types.ModuleType("trame_fespp_assistant")
    widgets = types.ModuleType("trame_fespp_assistant.widgets")
    widgets.AssistantPanel = Widget
    pkg.widgets = widgets
    monkeypatch.setitem(sys.modules, "trame_fespp_assistant", pkg)
    monkeypatch.setitem(sys.modules, "trame_fespp_assistant.widgets", widgets)
    sys.modules.pop("fespp_on_trame.app.views.assistant_panel", None)
    try:
        assistant_panel = importlib.import_module("fespp_on_trame.app.views.assistant_panel")
        ctrl = types.SimpleNamespace(assistant_ask=object(), assistant_choose=object(),
                                     assistant_undo=object(), assistant_clear=object())
        panel = assistant_panel.AssistantPanel(types.SimpleNamespace(controller=ctrl), "view_7")
    finally:
        # The panel module was imported against the fake widget: unload it
        # so later tests import the real one.
        sys.modules.pop("fespp_on_trame.app.views.assistant_panel", None)
    assert seen == {
        "data": ("ui_assistant", {}),
        "ask": (ctrl.assistant_ask, "[$event]"),
        "choose": (ctrl.assistant_choose, "[$event]"),
        "undo": (ctrl.assistant_undo, "[$event]"),
        "clear": (ctrl.assistant_clear, "[]"),
    }
    assert panel.html_view is None and panel.view_id == "view_7"


# ------------------------------------------------------------ __main__
_MAIN = ROOT / "fespp_on_trame" / "__main__.py"


def _main_functions(*names):
    """Compile the named functions of `__main__` alone, with the module's `_os`."""
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert sorted(n.name for n in body) == sorted(names)
    mod = ast.Module(body=[*ast.parse("import os as _os").body, *body], type_ignores=[])
    ns = {}
    exec(compile(mod, str(_MAIN), "exec"), ns)
    return ns


def _fake_assistant_packages(monkeypatch, host_raises=False):
    built = {}

    class AssistantController:
        def __init__(self, server, host, prefix="ui_assistant", journal=None, lang="fr",
                     reply_lang=None):
            built.update(server=server, host=host, prefix=prefix, journal=journal)

        def ask(self, text):
            pass

        def choose(self, choice_id):
            pass

        def undo(self):
            pass

        def clear(self):
            pass

    class FesppAssistantHost:
        def __init__(self, server):
            if host_raises:
                raise RuntimeError("no tree")

    pkg = types.ModuleType("trame_fespp_assistant")
    pkg.module = types.ModuleType("trame_fespp_assistant.module")
    ctl_mod = types.ModuleType("trame_fespp_assistant.controller")
    ctl_mod.AssistantController = AssistantController
    host_mod = types.ModuleType("fespp_on_trame.app.assistant_host")
    host_mod.FesppAssistantHost = FesppAssistantHost
    monkeypatch.setitem(sys.modules, "trame_fespp_assistant", pkg)
    monkeypatch.setitem(sys.modules, "trame_fespp_assistant.module", pkg.module)
    monkeypatch.setitem(sys.modules, "trame_fespp_assistant.controller", ctl_mod)
    monkeypatch.setitem(sys.modules, "fespp_on_trame.app.assistant_host", host_mod)
    return pkg, built


def _app_server():
    opened = []

    def add_view(direction=None, kind="render", reference_panel_id=None):
        opened.append(kind)
        return "view_9"

    ctrl = types.SimpleNamespace(add_view=add_view)
    return types.SimpleNamespace(controller=ctrl, context=types.SimpleNamespace()), opened


def test_the_assistant_is_on_only_with_its_switch_and_its_package(monkeypatch):
    """Not offered yet (the PO, 18/10): off unless FESPP_ASSISTANT=1."""
    bundle = _main_functions("_assistant_bundle")["_assistant_bundle"]
    pkg, _ = _fake_assistant_packages(monkeypatch)
    monkeypatch.delenv("FESPP_ASSISTANT", raising=False)
    assert bundle() is None
    monkeypatch.setenv("FESPP_ASSISTANT", "1")
    assert bundle() is pkg.module
    monkeypatch.setenv("FESPP_ASSISTANT", "0")
    assert bundle() is None
    monkeypatch.setenv("FESPP_ASSISTANT", "1")
    monkeypatch.setitem(sys.modules, "trame_fespp_assistant", None)
    assert bundle() is None


def test_the_start_line_says_whether_the_assistant_is_on_and_how_to_switch_it(monkeypatch, capsys):
    """The start line states the Assistant's switch and how to change it.

    The Assistant is not offered yet: off by default, the start line says
    how to switch it on, and an operator who set a value other than "1"
    reads that it did not switch it on."""
    bundle = _main_functions("_assistant_bundle")["_assistant_bundle"]
    _fake_assistant_packages(monkeypatch)
    monkeypatch.delenv("FESPP_ASSISTANT", raising=False)
    bundle()
    out = capsys.readouterr().out
    assert out.count("[assistant]") == 1
    assert out.startswith("[assistant] off") and "FESPP_ASSISTANT=1" in out
    assert "FESPP_ASSISTANT='" not in out
    monkeypatch.setenv("FESPP_ASSISTANT", "true")
    bundle()
    out = capsys.readouterr().out
    assert "[assistant] off" in out
    assert "FESPP_ASSISTANT='true' read, only \"1\" switches it on" in out
    monkeypatch.setenv("FESPP_ASSISTANT", " 1 ")
    bundle()
    out = capsys.readouterr().out
    assert out.startswith("[assistant] on") and "unset it" in out


def test_the_gestures_are_controllers_and_the_door_opens_the_panel(monkeypatch):
    wire = _main_functions("_wire_assistant")["_wire_assistant"]
    _fake_assistant_packages(monkeypatch)
    server, opened = _app_server()
    ctl = wire(server, True)
    c = server.controller
    assert (c.assistant_ask, c.assistant_choose, c.assistant_undo, c.assistant_clear) == (
        ctl.ask, ctl.choose, ctl.undo, ctl.clear)
    assert server.context.assistant is ctl
    assert server.context.assistant_host is not None
    assert c.open_assistant() == "view_9" and opened == ["assistant"]


@pytest.mark.parametrize("on, host_raises", [(False, False), (True, True)])
def test_an_assistant_off_has_no_gesture_and_opens_nothing(monkeypatch, capsys, on, host_raises):
    wire = _main_functions("_wire_assistant")["_wire_assistant"]
    _fake_assistant_packages(monkeypatch, host_raises=host_raises)
    server, opened = _app_server()
    assert wire(server, on) is None
    assert not hasattr(server.controller, "assistant_ask")
    assert server.controller.open_assistant() is None and opened == []
    assert "[assistant]" in capsys.readouterr().out


def test_the_door_is_the_mdi_glyph_titled_like_the_panel():
    src = _MAIN.read_text(encoding="utf-8")
    assert re.search(r'\("mdi-chat-processing-outline", "Assistant",\s*'
                     r'server\.controller\.open_assistant(, None)?\)', src)


def test_every_widget_module_enabled_is_baked_into_the_www():
    """Every widget module enabled in `__main__` is listed in `setup/apps.yml`.

    The places a widget is registered must agree: a module enabled in
    `__main__` and absent from `setup/apps.yml` renders as a blank panel
    with `... is not defined` in the browser, and nothing on the server."""
    enabled = set(re.findall(r"from (trame_fespp_\w+|trame_welllog) import module",
                             _MAIN.read_text(encoding="utf-8")))
    baked = set(re.findall(r"^\s*-\s*(\w+)\.module\s*$",
                           (ROOT / "setup" / "apps.yml").read_text(encoding="utf-8"), re.M))
    assert "trame_fespp_assistant" in enabled
    assert enabled <= baked, sorted(enabled - baked)


# ------------------------------------------------------------ the probe
class FakeConversation:
    """The Assistant's controller as the probe sees it.

    Each sentence gets its scripted reply and applies its scripted effect
    to the state."""

    def __init__(self, state, replies, undo_effect=None):
        self.state, self.replies, self.undo_effect = state, replies, undo_effect
        state.ui_assistant = {"messages": [], "busy": False}
        self.n = 0

    def _append(self, *msgs):
        conv = dict(self.state.ui_assistant)
        conv["messages"] = list(conv["messages"]) + list(msgs)
        self.state.ui_assistant = conv

    def _msg(self, role, text, **kw):
        self.n += 1
        return {"id": self.n, "role": role, "text": text, **kw}

    def ask(self, text):
        reply, effect = self.replies[text]
        if effect:
            effect(self.state)
        self._append(self._msg("user", text), self._msg("assistant", **reply))

    def undo(self):
        if self.undo_effect:
            self.undo_effect(self.state)
        self._append(self._msg("assistant", "Annulé.", level="ok"))


class _Assembly(FakeDataAssembly):
    """The fake assembly plus the root accessor the probe's title search uses."""

    def GetRootNode(self):
        return 0


def _probe_world(replies, parsed, undo_effect=None, panels=()):
    state = FakeState()
    # The Assistant's tab is in front: the probe acts on the 3D view last
    # worked in, as the adapter does.
    state.fespp_render_panels = [{"id": "view_1"}]
    state.fespp_active_panel_id = "view_2"
    state.fespp_last_render_panel_id = "view_1"
    conv = FakeConversation(state, replies, undo_effect)
    controller = types.SimpleNamespace(assistant_ask=conv.ask, assistant_undo=conv.undo)
    host = types.SimpleNamespace(parse=lambda text: {"intent": parsed[text]})
    mv = types.SimpleNamespace(panel_ids_of_kind=lambda k: [p for p, kk in panels if kk == k])
    server = types.SimpleNamespace(context=types.SimpleNamespace(assistant_host=host, multi_view=mv))
    asm = _Assembly()
    grid = asm.add_node_with_attrs("_geogrid", 0, title="Geogrid", type="IjkGrid")
    poro = asm.add_node_with_attrs("_poro", grid, title="Total Porosity",
                                   type="ContinuousProperty", propertyKind="porosity")
    tree = types.SimpleNamespace(_data_assembly=asm, find_path=asm.GetNodePath)
    return state, controller, server, tree, asm.GetNodePath(poro)


def _probe(world, step, out):
    state, controller, server, tree, _ = world
    asyncio.run(scenario._assistant_probe(server, state, controller, tree,
                                          dict({"op": "assistant_probe", "expect_wait": 0.3}, **step),
                                          str(out)))


def test_the_probe_holds_a_threshold_and_its_undo(tmp_path):
    say = "filtre la porosité au-dessus de 0,2"

    def add(s):
        s["ui_thresholds__view_1"] = list(s["ui_thresholds__view_1"] or []) + [{"name": "t1"}]

    def remove(s):
        s["ui_thresholds__view_1"] = list(s["ui_thresholds__view_1"] or [])[:-1]

    world = _probe_world({say: ({"text": "Total Porosity de Geogrid : mailles gardées au-dessus de 0,2.",
                                 "level": "ok", "undoable": True}, add)},
                         {say: "threshold"}, undo_effect=remove)
    _probe(world, {"say": say, "expect_intent": "threshold", "expect_level": "ok",
                   "expect_threshold": True, "expect_text_contains": "0,2",
                   "then_undo": True}, tmp_path)
    log = (tmp_path / "scenario.log").read_text(encoding="utf-8")
    assert "FAIL" not in log
    assert "OK  a threshold entry was added in view_1" in log
    assert "OK  the undo took the threshold entry out" in log
    assert world[0]["ui_thresholds__view_1"] == []


def test_the_probe_reads_the_eyes_the_rows_the_panels_and_the_state(tmp_path):
    show, mean, z, stats = ("montre la porosité de Geogrid", "quelle est la porosité moyenne ?",
                            "exagération verticale x 3", "ouvre les statistiques")
    ref = {}
    world = _probe_world({
        show: ({"text": "Total Porosity est affichée.", "level": "ok"},
               lambda s: s.__setitem__("visible_paths__view_1", [ref["poro"]])),
        mean: ({"text": "Total Porosity", "level": "ok", "rows": [["Moyenne", "0,21"]]}, None),
        z: ({"text": "Exagération ×3.", "level": "ok"}, lambda s: s.__setitem__("ui_scale_z__view_1", 3.0)),
        stats: ({"text": "Statistiques ouvertes.", "level": "ok"}, None),
    }, {show: "show", mean: "value", z: "z_scale", stats: "open_panel"},
        panels=[("view_3", "compare")])
    ref["poro"] = world[4]
    _probe(world, {"say": show, "expect_intent": "show", "expect_level": "ok",
                   "expect_visible": [{"title": "Total Porosity", "under": "Geogrid"}]}, tmp_path)
    _probe(world, {"say": mean, "expect_row": ["Mean", "Moyenne"]}, tmp_path)
    _probe(world, {"say": z, "expect_state": {"ui_scale_z__view_1": 3}}, tmp_path)
    _probe(world, {"say": stats, "expect_panel": "compare"}, tmp_path)
    assert "FAIL" not in (tmp_path / "scenario.log").read_text(encoding="utf-8")


def test_the_probe_raises_on_the_first_expectation_not_met(tmp_path):
    say = "blablabla xyz"
    world = _probe_world({say: ({"text": "Voulez-vous dire… ?", "level": "ask"}, None)},
                         {say: "help"})
    with pytest.raises(RuntimeError, match="level 'error'"):
        _probe(world, {"say": say, "expect_level": "error"}, tmp_path)
    with pytest.raises(RuntimeError, match="read as 'list'"):
        _probe(world, {"say": say, "expect_intent": "list"}, tmp_path)
    with pytest.raises(RuntimeError, match="is shown in view_1"):
        _probe(world, {"say": say, "expect_visible": [{"title": "Total Porosity"}]}, tmp_path)
    assert "FAIL" in (tmp_path / "scenario.log").read_text(encoding="utf-8")


def test_the_probe_says_when_the_assistant_is_off(tmp_path):
    world = list(_probe_world({}, {}))
    world[1] = types.SimpleNamespace()
    with pytest.raises(RuntimeError, match="assistant is off"):
        _probe(world, {"say": "aide"}, tmp_path)


class _SMProp:
    """A server-manager property: a vector of ids, or a list of input proxies."""

    def __init__(self, n=0, proxies=()):
        self.n, self.proxies = n, list(proxies)

    def GetNumberOfElements(self):
        return self.n

    def GetNumberOfProxies(self):
        return len(self.proxies)

    def GetProxy(self, i):
        return self.proxies[i]


class _SMProxy:
    def __init__(self, **props):
        self.props = props

    def GetProperty(self, name):
        return self.props.get(name)


class _Source:
    """The active source as ParaView holds its selection.

    The selection is an AppendSelections over a composite id selection
    (3 numbers per id), or None once cleared."""

    def __init__(self):
        self.selection = None

    def light(self, n):
        ids = _SMProxy(IDs=_SMProp(n=3 * n))
        self.selection = None if not n else _SMProxy(Input=_SMProp(proxies=[ids]))

    def GetSelectionInput(self, port):
        return self.selection


class _ControllerFunction:
    """trame's controller entry: a proxy calling its `func`."""

    def __init__(self, func):
        self.func = func

    def __call__(self, *args):
        return self.func(*args)


_HL = "surligne les mailles où la porosité dépasse 0,2"
_CLEAR = "enlève la surbrillance"


def _highlight_world(lit, reply_text, clears=True):
    """A probe world where the Assistant is asked to highlight cells.

    The adapter calls boot's `highlight_where`, which lights `lit` cells on
    the active source and returns their count; the reply says `reply_text`.
    The clear removes the highlight, unless `clears` is False."""
    src = _Source()

    def highlight_where(payload, vid):
        src.light(lit)
        return {"count": lit, "total": 24, "valid": 24, "array": "poro", "assoc": "CELLS"}

    hw = _ControllerFunction(highlight_where)
    world = _probe_world({
        _HL: ({"text": reply_text, "level": "ok", "undoable": True},
              lambda s: hw([0.2, None], "view_1")),
        _CLEAR: ({"text": "Surbrillance enlevée.", "level": "ok"},
                 (lambda s: src.light(0)) if clears else None),
    }, {_HL: "highlight", _CLEAR: "clear_highlight"})
    world[1].highlight_where = hw
    world[2].context.active_data_source = types.SimpleNamespace(get_source=lambda: src)
    return world, hw, highlight_where, src


def test_the_probe_holds_the_cells_highlight_where_lit_and_the_clear(tmp_path):
    world, hw, inner, src = _highlight_world(9, "9 mailles sur 24 surlignées : Total Porosity ≥ 0,2.")
    _probe(world, {"say": _HL, "expect_highlight_count_min": 1}, tmp_path)
    # The controller gets its own function back once the step is over.
    assert hw.func is inner
    _probe(world, {"say": _CLEAR, "expect_highlight_cleared": True}, tmp_path)
    log = (tmp_path / "scenario.log").read_text(encoding="utf-8")
    assert "FAIL" not in log
    assert "OK  highlight_where returned 9 cell(s) lit, at least 1" in log
    assert "OK  the selection drawn on the active source holds 9 id(s), at least 1" in log
    assert "OK  no selection left on the active source (ids: 0)" in log


def test_the_probe_fails_a_highlight_that_lights_nothing_whatever_the_reply_says(tmp_path):
    """A highlight that lights no cell fails, however confident the reply.

    This is the failure the scenario guards against: a bound compared the
    wrong way, or a stale mask excluding every cell, gives an ok reply and
    a count of 0."""
    world, hw, inner, _ = _highlight_world(0, "5 mailles sur 24 surlignées : Total Porosity ≥ 0,2.")
    with pytest.raises(RuntimeError, match="highlight_where returned 0 cell"):
        _probe(world, {"say": _HL, "expect_level": "ok", "expect_highlight_count_min": 1}, tmp_path)
    assert hw.func is inner


def test_the_probe_reads_the_reply_count_when_highlight_where_cannot_be_caught(tmp_path):
    world, _, _, _ = _highlight_world(0, "0 maille sur 24 surlignée : Total Porosity ≥ 0,2.")
    world[1].highlight_where = None
    with pytest.raises(RuntimeError, match="the reply says 0 cell"):
        _probe(world, {"say": _HL, "expect_highlight_count_min": 1}, tmp_path)
    assert "could not be caught" in (tmp_path / "scenario.log").read_text(encoding="utf-8")


def test_the_probe_fails_a_count_the_view_does_not_draw(tmp_path):
    world, hw, _, _ = _highlight_world(9, "9 mailles sur 24 surlignées : Total Porosity ≥ 0,2.")
    # A count returned, nothing selected on the source.
    hw.func = lambda payload, vid: {"count": 9, "total": 24}
    with pytest.raises(RuntimeError, match="holds 0 id"):
        _probe(world, {"say": _HL, "expect_highlight_count_min": 1}, tmp_path)


def test_the_probe_fails_a_clear_that_leaves_the_cells_lit(tmp_path):
    world, _, _, src = _highlight_world(4, "Surbrillance enlevée.", clears=False)
    src.light(4)
    with pytest.raises(RuntimeError, match=r"no selection left on the active source \(ids: 4\)"):
        _probe(world, {"say": _CLEAR, "expect_level": "ok", "expect_highlight_cleared": True},
               tmp_path)


def test_the_drogon_highlight_regex_refuses_a_count_of_zero():
    steps = json.loads((ROOT / "tests/visual/scenarios/assistant_drogon.json")
                       .read_text(encoding="utf-8"))["steps"]
    hl = next(s for s in steps if s.get("expect_intent") == "highlight")
    assert hl["expect_highlight_count_min"] >= 1
    rx = re.compile(hl["expect_text_matches"])
    # the assistant answers in English (it understands French)
    assert rx.search("309\u2009638 of 655\u2009576 cells highlighted: Total Porosity ≥ 0.2.")
    assert rx.search("1 of 24 cell highlighted: Total Porosity ≥ 0.2.")
    assert not rx.search("0 of 655\u2009576 cells highlighted: Total Porosity ≥ 0.2.")
    assert not rx.search("0 of 0 cells highlighted: Total Porosity ≥ 0.2.")
    clear = next(s for s in steps if s.get("expect_intent") == "clear_highlight")
    assert clear.get("expect_highlight_cleared") is True


# ------------------------------------------------------------ the scenario
_PROBE_KEYS = {"op", "say", "settle", "expect_intent", "expect_level", "expect_text_contains",
               "expect_text_matches", "expect_row", "expect_visible", "expect_threshold",
               "expect_panel", "expect_state", "expect_highlight_count_min",
               "expect_highlight_cleared", "expect_wait", "then_undo"}


def test_the_drogon_scenario_asks_what_the_probe_reads():
    steps = json.loads((ROOT / "tests/visual/scenarios/assistant_drogon.json")
                       .read_text(encoding="utf-8"))["steps"]
    probes = [s for s in steps if s["op"] == "assistant_probe"]
    assert len(probes) == 14
    for s in probes:
        assert set(s) <= _PROBE_KEYS, set(s) - _PROBE_KEYS
        assert s.get("expect_intent") is None or s["expect_intent"] in catalogue.INTENTS
        assert s.get("expect_level") in (None, "info", "ok", "ask", "error")
    assert 'elif op == "assistant_probe":' in (ROOT / "tests/visual/runner/scenario.py").read_text(
        encoding="utf-8")


def test_the_scenario_sentences_are_read_as_it_expects():
    """The shipped model reads every scenario sentence as the scenario expects.

    Checked on the drogon dataset's titles and kinds: a sentence the engine
    reads otherwise would fail the headless run for a reason unrelated to
    the wiring."""
    from fespp_on_trame.ia.nlu.engine import parse
    g = "/Geogrid/SolidColor"
    objects = [
        {"path": g, "title": "Geogrid", "type": "IjkGrid", "kind": "", "parent": None},
        {"path": g + "/phi", "title": "Total Porosity", "type": "ContinuousProperty",
         "kind": "porosity", "parent": g},
        {"path": g + "/ntg", "title": "Net-to-Gross Ratio (PEM)", "type": "ContinuousProperty",
         "kind": "net to gross ratio", "parent": g},
        {"path": g + "/kh", "title": "Horizontal Permeability", "type": "ContinuousProperty",
         "kind": "rock permeability", "parent": g},
    ]
    steps = json.loads((ROOT / "tests/visual/scenarios/assistant_drogon.json")
                       .read_text(encoding="utf-8"))["steps"]
    for s in steps:
        if s["op"] == "assistant_probe" and s.get("expect_intent"):
            cmd = parse(s["say"], objects)
            assert (cmd["intent"], cmd["sure"]) == (s["expect_intent"], True), (s["say"], cmd["intent"])
