"""FESPP_STRICT: make the app's silent exception handlers speak.

WHY THIS EXISTS
---------------
Most of the app's exception handlers catch ``Exception`` and report nothing.
Most of them are legitimate: a ``rep.Pickable = 0`` on a proxy that may not
carry the property, a ParaView call that fails harmlessly on an empty
pipeline. The cost is that a PROGRAMMING error becomes indistinguishable
from an expected quirk: a ``NameError`` inside an ``except Exception: pass``
is swallowed on every call, the block it guards never runs, and nothing
ever says so.

Rewriting every handler is not realistic. Observing the raise is: Python
3.12's ``sys.monitoring`` reports an exception at the moment it is RAISED,
before any handler sees it, so a swallowed error is visible without editing
the handler that swallows it.

USE
---
    FESPP_STRICT=1     report the exception types that mean "bug" (default)
    FESPP_STRICT=all   report every exception raised inside the app
    FESPP_STRICT=0     off, which is also what happens when unset

Each distinct (file, line, type) is printed ONCE, live, then only counted; a
summary lands at exit, busiest first. Without that, one bad line inside a
per-node loop would print thousands of times and be worse than silence.

COST
----
Opt-in, and it does not touch the handlers, so nothing about the app's
behaviour changes: an exception that was swallowed is still swallowed. The
callback fires for every exception in the process, ParaView's included, and
filters by filename with a memo: one dict lookup per raise. It must NOT use
``sys.monitoring.DISABLE`` to skip foreign code: that is illegal for RAISE
and removes the callback outright, leaving a reporter that says nothing
while it still looks armed (see the self-check in `install`).
"""
import atexit
import os
import sys

#: Exception types that almost always mean the code is wrong, rather than the
#: data or ParaView being awkward. UnboundLocalError is a subclass of
#: NameError; both are listed for clarity.
BUG_TYPES = (
    NameError, UnboundLocalError, AttributeError, TypeError,
    IndexError, KeyError, ZeroDivisionError, AssertionError,
    ImportError, RecursionError, UnicodeDecodeError,
)

_APP = "fespp_on_trame"
_seen = {}          # (file, line, type) -> count
_installed = [False]


def _mode():
    """The mode FESPP_STRICT asks for: None (off), "bugs" or "all"."""
    raw = (os.environ.get("FESPP_STRICT") or "").strip().lower()
    if raw in ("", "0", "false", "off", "no"):
        return None
    return "all" if raw in ("all", "2", "verbose") else "bugs"


def _report():
    """The exit summary on stderr, busiest site first."""
    if not _seen:
        print("[fespp-strict] no exception was raised inside the app",
              file=sys.stderr, flush=True)
        return
    print("\n[fespp-strict] exceptions raised inside the app, busiest first "
          "(they were caught — this is what the handlers did not tell you):",
          file=sys.stderr)
    for (where, line, kind), n in sorted(_seen.items(), key=lambda kv: -kv[1]):
        print("  %6d x  %-24s %s:%d" % (n, kind, where, line), file=sys.stderr)
    print("[fespp-strict] %d distinct sites\n" % len(_seen), file=sys.stderr,
          flush=True)


def install():
    """Arm the reporter when FESPP_STRICT asks for it. Safe to call twice, and
    a no-op on a Python without ``sys.monitoring`` (3.11 and older)."""
    mode = _mode()
    if mode is None or _installed[0]:
        return False
    mon = getattr(sys, "monitoring", None)
    if mon is None:
        print("[fespp-strict] FESPP_STRICT needs Python 3.12+ "
              "(sys.monitoring); ignored on %s" % sys.version.split()[0],
              file=sys.stderr, flush=True)
        return False

    tool = mon.DEBUGGER_ID
    try:
        mon.use_tool_id(tool, "fespp-strict")
    except ValueError:
        # a debugger already owns the slot: say so rather than fight it
        print("[fespp-strict] the debugger tool id is taken; not arming",
              file=sys.stderr, flush=True)
        return False

    want_all = mode == "all"

    ours = {}          # co_filename -> is it ours? (the check, memoised)

    def line_of(code, offset):
        """The line that actually raised, not the function's first line.

        co_lines() yields (start, end, lineno) over bytecode offsets; the
        monitoring callback hands us the offset, so the two meet here. Falls
        back to the function's own line if the tables disagree."""
        try:
            for start, end, lineno in code.co_lines():
                if lineno is not None and start <= offset < end:
                    return lineno
        except Exception:
            pass
        return code.co_firstlineno

    def on_raise(code, offset, exc):
        filename = code.co_filename
        mine = ours.get(filename)
        if mine is None:
            mine = ours[filename] = _APP in filename
        if not mine:
            # Foreign code, the bulk of the traffic. It must be filtered HERE,
            # in Python: returning sys.monitoring.DISABLE is illegal for RAISE
            # ("Cannot disable RAISE events. Callback removed.") and would tear
            # this tool down at the first ParaView exception, silently. The
            # memo above keeps the cost to one dict lookup per raise.
            return None
        if not want_all and not isinstance(exc, BUG_TYPES):
            return None
        key = (filename.split(_APP, 1)[-1].lstrip("/\\"),
               line_of(code, offset), type(exc).__name__)
        n = _seen.get(key, 0) + 1
        _seen[key] = n
        if n == 1:
            print("[fespp-strict] %s: %s  (%s:%d, in %s)"
                  % (key[2], str(exc)[:160], key[0], key[1], code.co_name),
                  file=sys.stderr, flush=True)
        return None

    mon.register_callback(tool, mon.events.RAISE, on_raise)
    mon.set_events(tool, mon.events.RAISE)

    # SELF-CHECK: prove that a foreign raise does not tear the callback down.
    # Should the callback ever return sys.monitoring.DISABLE for foreign code,
    # Python would remove it at the first ParaView exception and the tool
    # would report nothing while still printing "armed"; this catches that
    # failure at startup.
    try:
        exec(compile("raise ValueError('self-check')", "<foreign>", "exec"),
             {"__name__": "foreign"})
    except ValueError:
        pass
    # get_events() is the wrong probe: the event MASK survives; it is the
    # callback Python removes. register_callback() returns the previous one,
    # so re-registering tells us whether ours was still there.
    survivor = mon.register_callback(tool, mon.events.RAISE, on_raise)
    _seen.clear()          # the self-check is ours, not the app's
    if survivor is None:
        mon.set_events(tool, 0)
        print("[fespp-strict] DISARMED by a foreign exception — the callback "
              "was torn down, so nothing would be reported. This is a bug in "
              "engine/strict.py, not in your session.", file=sys.stderr,
              flush=True)
        return False

    atexit.register(_report)
    _installed[0] = True
    print("[fespp-strict] armed (%s). Every exception raised inside the app "
          "is reported once per site, even the ones a handler swallows."
          % ("all types" if want_all else "bug-shaped types only"),
          file=sys.stderr, flush=True)
    return True


def snapshot():
    """``{(file, line, type): count}`` so far, for a test or a health panel
    that wants the numbers without waiting for exit."""
    return dict(_seen)
