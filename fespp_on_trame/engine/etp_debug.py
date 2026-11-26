"""Append-only debug trace for the ETP/OSDU path, off unless
``FESPP_ETP_DEBUG=1``.

A browser-driven ETP session is hard to debug after the fact: the server's
stdout is pipe-buffered under a background launcher, the VTK stderr tee is
consumed as it is read, and the C++ side reports most failures as silent
no-ops. This trace is the reliable record to ``tail``; a native crash kills
the process before any Python traceback, so its last line names the step
that faulted.

Off, every call is a no-op. The caller still builds its message, so a
caller whose message costs something checks `enabled` first.

On, each line is appended to ``etp_debug.log`` in the process's temp
directory (engine/io/temp_dir), and the first line written names the file
on stderr. Never beside the package: an image installs it in site-packages,
where nothing should be written at run time. The temp directory goes with
the process on a clean stop and stays after a crash, trace included. Past
`MAX_BYTES` the file starts over, its previous content kept as
``etp_debug.log.1``. A line that cannot be written goes to stderr instead.
"""
import datetime
import importlib
import os
import sys

SWITCH = "FESPP_ETP_DEBUG"
FILE_NAME = "etp_debug.log"
MAX_BYTES = 8 * 1024 * 1024

# the trace files already named on stderr: once each
_announced = set()


def enabled(environ=None) -> bool:
    """Whether the trace is on: ``FESPP_ETP_DEBUG=1``, nothing else."""
    env = os.environ if environ is None else environ
    return (env.get(SWITCH) or "").strip() == "1"


def trace_path() -> str:
    """The trace file: ``etp_debug.log`` in the process's temp directory.

    temp_dir is looked up when a line is written, not imported with this
    module: importing it creates the directory and installs the cleanup
    handlers, which only a trace that is on should cause."""
    temp = importlib.import_module("fespp_on_trame.engine.io.temp_dir")
    return os.path.join(temp.temp_dir, FILE_NAME)


def etp_debug(msg):
    """Append `msg`, time-stamped, to the trace; a no-op while it is off."""
    if not enabled():
        return
    stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{stamp}] {msg}"
    path = None
    try:
        path = trace_path()
        if os.path.isfile(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:
        print(f"[etp-debug] {line}  (not written to {path}: {exc})",
              file=sys.stderr, flush=True)
        return
    if path not in _announced:
        _announced.add(path)
        print(f"[etp-debug] {SWITCH}=1: the ETP trace is written to {path}",
              file=sys.stderr, flush=True)
