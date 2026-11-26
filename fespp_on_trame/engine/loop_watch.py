"""Where the server is when its loop stalls.

The browser sees a frozen view whenever the server's event loop is held:
a load, a recompute, a render that does not return. Nothing says so on
the screen when the hold was not a round trip the browser was waiting on,
and the session log then shows the load's own timing at best. This watch
says it in the log: a heartbeat task on the loop stamps the time every
quarter of a second, a thread checks the stamp; once the loop has been
held longer than the threshold it prints the loop thread's Python stack
(where it is), and when the loop is free again how long the hold lasted
and where it was last seen. One report per hold.

That thread needs the interpreter's lock to read the stack: a call that
keeps the lock while it runs (a loop in C++) silences it for as long as it
lasts. A hold of a minute is therefore also written by faulthandler's own
thread, which takes no lock: "Timeout (0:01:00)!" and the Python stack of
every thread.

FESPP_LOOP_WATCH=0 switches it off; FESPP_LOOP_WATCH_SECONDS sets the
threshold (1.5 s by default)."""
import asyncio
import faulthandler
import os
import sys
import threading
import time
import traceback

_PERIOD = 0.25
_LONG = 60.0        # s: a hold that long is written without the interpreter's lock


def _log(text):
    """Straight to file descriptor 2 (the session log): pvpython's
    sys.stderr is a VTK capture helper, and written from this thread while
    the loop thread holds VTK it could wait on it for ever — the very hold
    being reported (the harness's stack_dump writes to fd 2 for the same
    reason)."""
    try:
        os.write(2, (text.rstrip("\n") + "\n").encode("utf-8", "replace"))
    except OSError as exc:
        # nowhere left to say it: the count is kept for a debugger to read
        _log.lost = getattr(_log, "lost", 0) + 1
        _log.last_error = exc


def _stack(thread_id, limit=18):
    frame = sys._current_frames().get(thread_id)
    if frame is None:
        return "    (no frame)\n"
    return "".join(traceback.format_stack(frame, limit=limit))


def start():
    """Start the watch from the loop's own thread (an `on_server_ready`
    handler); returns False when it is switched off or already running."""
    if os.environ.get("FESPP_LOOP_WATCH", "1") == "0" or getattr(start, "_on", False):
        return False
    raw = os.environ.get("FESPP_LOOP_WATCH_SECONDS", "1.5")
    try:
        threshold = float(raw)
    except ValueError:
        _log(f"[fespp] loop watch: FESPP_LOOP_WATCH_SECONDS={raw!r} is no number, 1.5 s")
        threshold = 1.5
    loop_thread = threading.get_ident()
    beat = {"t": time.monotonic()}

    async def _heart():
        armed = None
        while True:
            beat["t"] = time.monotonic()
            if armed is None or beat["t"] - armed > _LONG / 6:
                # put off for as long as the loop turns: it fires within _LONG of
                # its last turn
                faulthandler.dump_traceback_later(_LONG, file=2)
                armed = beat["t"]
            await asyncio.sleep(_PERIOD)

    asyncio.ensure_future(_heart())

    def _watch():
        held_since, last = None, ""
        while True:
            time.sleep(_PERIOD)
            lag = time.monotonic() - beat["t"]
            if lag > threshold:
                last = _stack(loop_thread)
                if held_since is None:
                    held_since = beat["t"]
                    _log(f"[fespp] server loop held {lag:.1f} s so far, in:\n{last}")
            elif held_since is not None:
                _log(f"[fespp] server loop free again after"
                     f" {time.monotonic() - held_since - lag:.1f} s, last seen in:\n{last}")
                held_since, last = None, ""

    threading.Thread(target=_watch, name="fespp-loop-watch", daemon=True).start()
    start._on = True
    _log(f"[fespp] loop watch: a hold over {threshold:g} s is written here with"
         " its stack (FESPP_LOOP_WATCH=0 switches it off)")
    return True
