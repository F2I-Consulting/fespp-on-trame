"""Fixes pinned one by one: a view that draws nothing, the
address-space limit at boot, the camera a session and the Assistant put
back, the Assistant's no-loop line, the software-rendering hint.

No ParaView, no trame (the conftest stubs). The two module-level functions
whose modules cannot be imported here (temp_dir takes over SIGINT and
SIGTERM on import, view_manager needs trame's widgets) are compiled alone
from their source."""
import ast
import asyncio
import gc
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "widgets" / "assistant"))

from tests.unit.fake_assembly import FakeDataAssembly  # noqa: E402
from fespp_on_trame.app import assistant_host, session_host  # noqa: E402
from fespp_on_trame.app.session_host import FesppSessionHost  # noqa: E402
from fespp_on_trame.app.views import camera  # noqa: E402
from fespp_on_trame.engine import stats_dispatch  # noqa: E402
from fespp_on_trame.engine.tree import Tree  # noqa: E402
from trame_fespp_assistant import controller as assistant_controller  # noqa: E402


def _compiled(path, name, namespace=None, imports=False):
    """The top-level function `name` of the module at `path`, compiled alone
    into `namespace` — with the module's own top-level imports when
    `imports` is set; the module's other statements are not run."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    body = [n for n in tree.body if imports and isinstance(n, (ast.Import, ast.ImportFrom))]
    body.append(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name))
    ns = dict(namespace or {})
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), ns)
    return ns[name]


# ------------------------------------------------ a view that draws nothing
def _grid_with_porosity():
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="IjkGrid_G", title="Geogrid",
                                   type="IjkGrid", typeCode="2")
    poro = asm.add_node_with_attrs("_poro", grid, label="Properties_PORO", title="PORO",
                                   type="ContinuousProperty", typeCode="4", uom="m3/m3")
    return Tree(asm), asm.GetNodePath(poro)


def test_a_view_with_no_visible_source_resolves_to_nothing(monkeypatch):
    """A view whose displays of the representation are all hidden."""
    from trame.app import get_server
    from fespp_on_trame.engine import drawn_cells, view_resources
    tree, poro = _grid_with_porosity()
    rep = stats_dispatch._rep_path_for_array_path(tree, poro)
    monkeypatch.setattr(view_resources, "pv_view_of", lambda vid: SimpleNamespace(ViewTime=0.0))
    monkeypatch.setattr(get_server().context, "grid_isolates", {("view_1", rep): object()}, raising=False)
    monkeypatch.setattr(get_server().context, "blockscope_scenes", {}, raising=False)
    asked = []

    def hidden(iso, pv_view):
        asked.append(iso)
        return []

    monkeypatch.setattr(drawn_cells, "of_isolate", hidden)
    assert stats_dispatch._resolve_rendered_inputs(rep, "view_1")[0] == []
    assert len(asked) == 1


# ------------------------------------------------ the address-space limit at boot
GIB = 1024 ** 3
_TEMP_DIR = ROOT / "fespp_on_trame" / "engine" / "io" / "temp_dir.py"


class _FakeResource:
    """The `resource` module as _setup_for_large_files reads it."""
    RLIMIT_AS = 9

    def __init__(self, soft, hard, infinity=-1, refuse=None):
        self.RLIM_INFINITY = infinity        # -1: what Python reads on Linux
        self.limits = (soft, hard)
        self.refuse = refuse
        self.calls = []

    def getrlimit(self, which):
        assert which == self.RLIMIT_AS
        return self.limits

    def setrlimit(self, which, limits):
        if self.refuse is not None:
            raise self.refuse
        self.calls.append((which, tuple(limits)))
        self.limits = tuple(limits)


def _setup_for_large_files():
    return _compiled(_TEMP_DIR, "_setup_for_large_files", imports=True)


@pytest.mark.parametrize("soft, hard, infinity, raised_to", [
    (-1, -1, -1, None),                   # unlimited: left alone, never capped
    (8 * GIB, -1, -1, -1),                # under an unlimited hard limit: lifted
    (4 * GIB, 16 * GIB, -1, 16 * GIB),    # under a finite hard limit: up to it
    (16 * GIB, 16 * GIB, -1, None),       # already at the hard limit
    (4 * GIB, 2 ** 63 - 1, 2 ** 63 - 1, 2 ** 63 - 1),   # "unlimited" read as a large number
    (2 ** 63 - 1, 2 ** 63 - 1, 2 ** 63 - 1, None),
])
def test_the_soft_address_space_limit_is_raised_to_the_hard_one_never_lowered(
        monkeypatch, soft, hard, infinity, raised_to):
    fake = _FakeResource(soft, hard, infinity)
    monkeypatch.setitem(sys.modules, "resource", fake)
    _setup_for_large_files()()
    if raised_to is None:
        assert fake.calls == []
    else:
        assert fake.calls == [(fake.RLIMIT_AS, (raised_to, raised_to))]


def test_a_refused_raise_is_said_and_the_boot_goes_on(monkeypatch, capsys):
    fake = _FakeResource(4 * GIB, 16 * GIB, refuse=ValueError("not allowed"))
    monkeypatch.setitem(sys.modules, "resource", fake)
    _setup_for_large_files()()
    assert "could not be raised" in capsys.readouterr().out


def test_without_a_resource_module_nothing_is_done(monkeypatch):
    # None in sys.modules makes the import fail, as on Windows
    monkeypatch.setitem(sys.modules, "resource", None)
    _setup_for_large_files()()


def test_the_garbage_collector_and_the_environment_are_left_alone(monkeypatch):
    monkeypatch.setitem(sys.modules, "resource", _FakeResource(4 * GIB, 16 * GIB))
    monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)
    thresholds = gc.get_threshold()
    try:
        # marks of the test's own, whatever the interpreter's defaults or
        # what ran before
        gc.set_threshold(701, 11, 12)
        mark, environ = gc.get_threshold(), dict(os.environ)
        _setup_for_large_files()()
        assert gc.get_threshold() == mark
        assert dict(os.environ) == environ
    finally:
        gc.set_threshold(*thresholds)


# ------------------------------------------------ the camera put back
_SAVED_CAMERA = {
    "CameraPosition": [431000.0, 6469000.0, 2500.0],
    "CameraFocalPoint": [430000.0, 6470000.0, -2500.0],
    "CameraViewUp": [0.0, 0.0, 1.0],
    "CameraViewAngle": 30.0,
    "CameraParallelScale": 1200.0,
    "CameraParallelProjection": 0,
    "CenterOfRotation": [430000.0, 6470000.0, -2500.0],
}


class _FakeState(dict):
    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v

    def flush(self):
        pass


class _AnyController:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Views:
    def __init__(self, views):
        self.views = views

    def get_pv_view(self, vid):
        return self.views.get(vid)


def _session_host(views):
    from fespp_on_trame.app.scene.cards import Cards
    from fespp_on_trame.app.views.tools_config import MODE_TOOLS
    state = _FakeState()
    server = SimpleNamespace(state=state, controller=_AnyController(),
                             context=SimpleNamespace(multi_view=_Views(views), tree=None,
                                                     cards=Cards(state, MODE_TOOLS)))
    return FesppSessionHost(server)


def test_the_saved_camera_holds_the_pivot():
    assert "CenterOfRotation" in camera.CAMERA_PROPERTIES
    assert set(_SAVED_CAMERA) == set(camera.CAMERA_PROPERTIES)


def test_the_session_and_the_assistant_put_back_the_same_camera():
    assert session_host.CAMERA_PROPERTIES is camera.CAMERA_PROPERTIES
    assert assistant_host.CAMERA_PROPERTIES is camera.CAMERA_PROPERTIES
    # no private copy left to drift from it
    assert not hasattr(session_host, "_CAMERA")
    assert not hasattr(assistant_host, "_CAMERA")


def test_a_session_saves_and_restores_the_pivot():
    saved_view = SimpleNamespace(**_SAVED_CAMERA)
    cam = _session_host({"view_1": saved_view})._collect_render("view_1")["camera"]
    assert cam == _SAVED_CAMERA
    # another session: the view comes back framed elsewhere, pivot at the origin
    view = SimpleNamespace(**{p: [0.0, 0.0, 0.0] for p in camera.CAMERA_PROPERTIES})
    _session_host({"view_7": view})._restore_render("view_7", {"camera": cam},
                                                     lambda *a: None)
    assert {p: getattr(view, p) for p in camera.CAMERA_PROPERTIES} == _SAVED_CAMERA


def test_a_session_file_without_a_pivot_leaves_the_view_s_own():
    cam = {k: v for k, v in _SAVED_CAMERA.items() if k != "CenterOfRotation"}
    view = SimpleNamespace(**{p: [0.0, 0.0, 0.0] for p in camera.CAMERA_PROPERTIES})
    view.CenterOfRotation = [1.0, 2.0, 3.0]
    _session_host({"view_1": view})._restore_render("view_1", {"camera": cam},
                                                     lambda *a: None)
    assert view.CenterOfRotation == [1.0, 2.0, 3.0]
    assert view.CameraFocalPoint == _SAVED_CAMERA["CameraFocalPoint"]


# ------------------------------------------------ the Assistant without a loop
def test_the_assistant_says_once_per_process_that_no_event_loop_runs(monkeypatch, capsys):
    monkeypatch.setattr(assistant_controller, "_NO_LOOP_SAID", [])
    assert assistant_controller._running_loop() is None
    assert assistant_controller._running_loop() is None
    assert capsys.readouterr().out.count("no event loop running") == 1

    async def _inside():
        return assistant_controller._running_loop()

    assert asyncio.run(_inside()) is not None
    assert capsys.readouterr().out == ""


# ------------------------------------------------ the software-rendering hint
def test_the_software_rendering_hint_points_at_the_readme(capsys):
    window = SimpleNamespace(ReportCapabilities=lambda: (
        "OpenGL vendor string: Mesa\n"
        "OpenGL renderer string: llvmpipe (LLVM 15.0.7, 256 bits)\n"))
    view = SimpleNamespace(GetClientSideObject=lambda: SimpleNamespace(
        GetRenderWindow=lambda: window))
    remembered = []
    say = _compiled(ROOT / "fespp_on_trame" / "app" / "views" / "view_manager.py",
                    "_say_render_backend",
                    {"_BACKEND": [], "sys": sys,
                     "pvsimple": SimpleNamespace(Render=lambda view=None: None),
                     "frames": SimpleNamespace(remember_backend=remembered.append)})
    assert say(view) == "software" and remembered == ["software"]
    err = capsys.readouterr().err
    assert "SOFTWARE (llvmpipe" in err
    assert "README.md" in err and "deploy/" not in err
    # the README it names says how to pass a GPU
    assert "GPU Mode" in (ROOT / "README.md").read_text(encoding="utf-8")


# ------------------------------------------------ session restore: modes, projection
def test_a_restored_selection_card_restores_its_mode_and_the_projection():
    view = SimpleNamespace(**_SAVED_CAMERA)
    host = _session_host({"view_3": view})
    saved = {"camera": dict(_SAVED_CAMERA, CameraParallelProjection=1),
             "cards": {"open": ["frustum", "colormap"]}}
    host._restore_render("view_3", saved, lambda *a: None)
    s = host.state
    # the lit button and its mode agree
    assert s["ui_frustum_mode__view_3"] is True
    assert s["ui_pick_mode__view_3"] is False
    assert s["ui_open_tools_by_view"]["view_3"] == ["frustum", "colormap"]
    # the Navigation card says the projection the view came back in
    assert view.CameraParallelProjection == 1 and s["ui_nav_parallel__view_3"] is True


def test_a_copied_camera_carries_the_projection():
    src = SimpleNamespace(**dict(_SAVED_CAMERA, CameraParallelProjection=1))
    dst = SimpleNamespace(**{p: [0.0, 0.0, 0.0] for p in camera.CAMERA_PROPERTIES})
    dst.CameraParallelProjection = 0
    camera.copy_camera_properties(src, dst)
    assert {p: getattr(dst, p) for p in camera.CAMERA_PROPERTIES} == dict(
        _SAVED_CAMERA, CameraParallelProjection=1)
    # a vector property is copied by value, not shared
    assert dst.CameraPosition is not src.CameraPosition
