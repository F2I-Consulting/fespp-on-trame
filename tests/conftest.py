"""
conftest.py — stubs des dépendances runtime (trame, paraview) pour les tests unitaires.

Tous les modules de fespp_on_trame importent `trame` et parfois `paraview.simple`
au niveau module, ce qui empêche leur import dans un test ordinaire.
Ce fichier installe des stubs minimaux dans sys.modules AVANT que pytest
ne commence à collecter les tests, de sorte que les imports réels soient
interceptés sans lever ImportError.
"""
import sys
import types
from unittest.mock import MagicMock


def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


def _install_trame_stubs():
    """Stub trame et ses sous-modules."""
    # State/controller simulés
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
    ]:
        sys.modules.setdefault(sub, MagicMock())

    sys.modules["trame"] = trame_mod
    sys.modules["trame.app"] = trame_app


def _install_paraview_stubs():
    """Stub paraview et ses sous-modules."""
    for name in ["paraview", "paraview.simple", "vtk", "ptc"]:
        sys.modules.setdefault(name, MagicMock())


_install_trame_stubs()
_install_paraview_stubs()
