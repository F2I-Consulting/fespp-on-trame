"""The debug switches stay off unless the server's environment sets them to 1.

Two diagnostics ride on the ETP path. ``GET /debug/etp`` dumps the live
session to whoever reaches the port, with no authentication of its own;
the ETP trace appends a line for every step of a connection or a load.
Both belong to a developer's session: a served instance neither answers
the route nor writes the trace. When the trace is on, it lands in the
process's temp directory (engine/io/temp_dir), never beside the installed
package.
"""
import sys
import types
from pathlib import Path

import pytest

import fespp_on_trame
from fespp_on_trame.engine import etp_debug as trace
from fespp_on_trame.engine.io import etp_debug_endpoint as endpoint

_TEMP_MODULE = "fespp_on_trame.engine.io.temp_dir"


# --- GET /debug/etp ---------------------------------------------------------

class FakeController:
    """`server.controller` as the route registration uses it: `add(name)`
    returns a decorator that keeps the callback."""

    def __init__(self):
        self.added = {}

    def add(self, name):
        def register(func):
            self.added.setdefault(name, []).append(func)
            return func
        return register


class FakeServer:
    def __init__(self):
        self.controller = FakeController()


class FakeApp:
    """The aiohttp application of a bound wslink server."""

    def __init__(self):
        self.routes = []

    def add_routes(self, routes):
        self.routes.extend(routes)


def test_the_route_is_not_registered_by_default(monkeypatch):
    monkeypatch.delenv("FESPP_DEBUG_ROUTES", raising=False)
    server = FakeServer()
    assert endpoint.debug_routes_enabled() is False
    assert endpoint.register_debug_routes(server) is False
    assert server.controller.added == {}, "nothing waits for the server to bind"


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "on", "2", "01"])
def test_only_1_switches_the_route_on(value):
    assert endpoint.debug_routes_enabled({"FESPP_DEBUG_ROUTES": value}) is False


def test_the_switch_serves_get_debug_etp(monkeypatch):
    monkeypatch.setenv("FESPP_DEBUG_ROUTES", "1")
    server = FakeServer()
    assert endpoint.register_debug_routes(server) is True
    (bind,) = server.controller.added["on_server_bind"]
    wslink = types.SimpleNamespace(app=FakeApp())
    bind(wslink)
    assert [(r.method, r.path) for r in wslink.app.routes] == [("GET", "/debug/etp")]


def test_boot_registers_the_route_through_the_switch_only():
    boot = (Path(fespp_on_trame.__file__).resolve().parent / "app" / "boot.py"
            ).read_text(encoding="utf-8")
    assert "register_debug_routes(server)" in boot
    assert "register_etp_debug_route(" not in boot, \
        "a direct registration would answer whatever FESPP_DEBUG_ROUTES says"


# --- the ETP trace ----------------------------------------------------------

@pytest.fixture
def temp_dir(tmp_path, monkeypatch):
    """The process's temp directory, stood in for by `tmp_path`: importing
    the real engine/io/temp_dir would create a directory and install signal
    handlers in the test process."""
    fake = types.ModuleType(_TEMP_MODULE)
    fake.temp_dir = str(tmp_path)
    monkeypatch.setitem(sys.modules, _TEMP_MODULE, fake)
    return tmp_path


def test_the_trace_writes_nothing_by_default(temp_dir, monkeypatch, capsys):
    monkeypatch.delenv("FESPP_ETP_DEBUG", raising=False)

    def looked_up(*_args, **_kwargs):
        raise AssertionError("the trace touched a file while off")
    monkeypatch.setattr(trace, "trace_path", looked_up)
    # any file the module would open, wherever it is
    monkeypatch.setattr(trace, "open", looked_up, raising=False)
    trace.etp_debug("connect('wss://host/'): OK in 0.42s")
    assert list(temp_dir.iterdir()) == []
    assert capsys.readouterr().err == ""


def test_the_trace_location_owes_nothing_to_the_package_location():
    # an installed package sits in site-packages, where nothing is written
    source = Path(trace.__file__).read_text(encoding="utf-8")
    assert "__file__" not in source


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "on", "2"])
def test_only_1_switches_the_trace_on(value):
    assert trace.enabled({"FESPP_ETP_DEBUG": value}) is False


def test_on_the_trace_is_written_to_the_process_temp_dir(temp_dir, monkeypatch, capsys):
    monkeypatch.setenv("FESPP_ETP_DEBUG", "1")
    trace.etp_debug("set_dataspace('eml:///dataspace(demo)') connected=True")
    trace.etp_debug("set_dataspace: final children=3")
    log = temp_dir / "etp_debug.log"
    assert Path(trace.trace_path()) == log
    lines = log.read_text(encoding="utf-8").splitlines()
    assert [line.split("] ", 1)[1] for line in lines] == [
        "set_dataspace('eml:///dataspace(demo)') connected=True",
        "set_dataspace: final children=3"]
    assert capsys.readouterr().err.count(str(log)) == 1, \
        "the file is named on stderr once, with its first line"


def test_a_line_that_cannot_be_written_goes_to_stderr(tmp_path, monkeypatch, capsys):
    gone = tmp_path / "removed"   # a temp directory already cleaned up
    fake = types.ModuleType(_TEMP_MODULE)
    fake.temp_dir = str(gone)
    monkeypatch.setitem(sys.modules, _TEMP_MODULE, fake)
    monkeypatch.setenv("FESPP_ETP_DEBUG", "1")
    trace.etp_debug("etp_select: reconnect FAILED")
    assert "etp_select: reconnect FAILED" in capsys.readouterr().err
    assert not gone.exists(), "a removed temp directory is not made again"


def test_a_full_trace_starts_over_and_keeps_one_previous_file(temp_dir, monkeypatch):
    monkeypatch.setenv("FESPP_ETP_DEBUG", "1")
    # every line overflows: each write after the first starts the file over
    monkeypatch.setattr(trace, "MAX_BYTES", 1)
    for step in range(3):
        trace.etp_debug(f"data_load: step {step}")
    current = (temp_dir / "etp_debug.log").read_text(encoding="utf-8")
    previous = (temp_dir / "etp_debug.log.1").read_text(encoding="utf-8")
    assert "step 2" in current and "step 1" not in current
    assert "step 1" in previous and "step 0" not in previous
    assert sorted(p.name for p in temp_dir.iterdir()) == ["etp_debug.log", "etp_debug.log.1"]
