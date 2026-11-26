"""StateBatcher — debounce for continuous controls (z-scale, opacity, slicers).

Contract
--------
Input:     the trame ``server``; optional ``generation`` — zero-arg callable
           returning the session's current ``load_generation``. Each scheduled
           callback is stamped with the generation at schedule time; if a new
           data load started before it fires, it no-ops (stale).
Behaviour: ``schedule(key, callback)`` (re)arms an ``asyncio`` ``call_later``
           timer per key — a burst of slider events collapses to ONE firing of
           the LAST callback after ``delay`` seconds of quiet. Callbacks run
           inside ``with server.state:`` so their writes flush as one trame
           transaction; they must RE-READ state at fire time rather than trust
           values captured when an earlier event was scheduled (the last
           scheduled callback's own arguments are, by construction, the
           latest).
Reads:     the running asyncio loop; the injected generation counter.
Writes:    whatever the callback writes (inside one state transaction).
"""
import asyncio


class StateBatcher:
    def __init__(self, server, delay=0.15, generation=None):
        self._server = server
        self._delay = delay
        self._generation = generation or (lambda: 0)
        self._handles = {}  # key -> asyncio.TimerHandle

    def schedule(self, key, callback, delay=None):
        """(Re)arm the debounce timer for ``key`` with ``callback``."""
        prev = self._handles.pop(key, None)
        if prev is not None:
            prev.cancel()
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop (headless harness): apply at once, still inside
            # one state transaction.
            with self._server.state:
                callback()
            return
        stamped = self._generation()

        def _fire():
            self._handles.pop(key, None)
            if self._generation() != stamped:
                return  # a data load started after scheduling: stale, drop
            with self._server.state:
                callback()

        self._handles[key] = loop.call_later(
            self._delay if delay is None else delay, _fire)

    def cancel(self, key):
        handle = self._handles.pop(key, None)
        if handle is not None:
            handle.cancel()

    def cancel_all(self):
        for key in list(self._handles):
            self.cancel(key)
