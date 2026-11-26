"""Stub the runtime dependencies (trame, ParaView) for the unit tests.

The fespp_on_trame modules import `trame`, and some import
`paraview.simple`, at module level, so they cannot be imported in a plain
Python test run. This file installs minimal stubs in sys.modules before
pytest starts collecting, so those imports resolve without ImportError.
"""
import sys
import types
from unittest.mock import MagicMock


def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


def _install_trame_stubs():
    """Stub trame and its submodules."""
    # Fake server state and controller.
    state_mock = MagicMock()
    state_mock.setdefault = lambda k, v: None

    server_mock = MagicMock()
    server_mock.state = state_mock
    server_mock.controller = MagicMock()

    trame_app = _make_stub("trame.app")
    trame_app.get_server = MagicMock(return_value=server_mock)

    trame_mod = _make_stub("trame")
    for sub in [
        "trame.app",
        "trame.widgets",
        "trame.widgets.vuetify3",
        "trame.widgets.html",
        "trame.widgets.paraview",
        "trame.widgets.client",
        "trame.ui",
        "trame.ui.vuetify3",
        "trame.assets",
        "trame.assets.local",
        "trame_server",
        # Vendored widgets: the panel builders (app/views/**) import them at
        # module level, and they are not installed for the unit tests.
        "trame_fespp_tree",
        "trame_fespp_tree.widgets",
        "trame_fespp_tree.widgets.tree",
    ]:
        sys.modules.setdefault(sub, MagicMock())

    sys.modules["trame"] = trame_mod
    sys.modules["trame.app"] = trame_app


def _install_paraview_stubs():
    """Stub paraview and its submodules.

    `paraview` must be a real module, not a MagicMock: otherwise
    `from paraview.servermanager import X` raises "'paraview' is not a
    package", because Python resolves a dotted submodule name only through
    a real package."""
    pv = _make_stub("paraview")
    pv.__path__ = []                      # a __path__ makes it a package
    sys.modules.setdefault("paraview", pv)
    for name in ["paraview.simple", "paraview.servermanager",
                 "paraview.util", "paraview.util.vtkAlgorithm",
                 "vtk", "ptc"]:
        sys.modules.setdefault(name, MagicMock())
    # The submodules must also be attributes of the package.
    for name in ["simple", "servermanager", "util"]:
        setattr(pv, name, sys.modules.get("paraview." + name, MagicMock()))


_install_trame_stubs()
_install_paraview_stubs()
