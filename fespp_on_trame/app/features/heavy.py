"""the heavy recomputes run one turn later, behind the bar of their view
The matrix of the Statistics view reads every cell of a grid: seconds
on a million cells. Computed inside a state handler it blocks the event
loop, and a busy flag written just before never reaches the browser: the
frames wait for the loop that is busy computing. So each heavy publisher
runs the bar of its views (`ctx.view_busy`, the one wait of a view, drawn by
app/views/widgets/view_wait), flushes, yields the loop ONE turn (the flag goes
out), then computes; requests arriving in the same turn coalesce into one
compute, which reads the state as it is when it runs.
`controller.heavy_pending` tells the headless runner when a step's figures are
all out.

(Moved out of app/boot, overhaul slice 10.)"""
import asyncio


def register(core):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_defer, _heavy)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    lifecycle = core.lifecycle
    _heavy = {}
    _held = {}          # view id -> the works keeping its bar on

    @lifecycle.on("view_closed")
    def _forget_heavy_of(vid):
        """A closed panel's busy flags ("globe:<vid>", "crossplot:<pid>") and
        its bar."""
        for k in [k for k in _heavy if str(k).endswith(f":{vid}")]:
            _heavy.pop(k, None)
        _held.pop(str(vid), None)

    def view_busy(name, views, on):
        """The bar of `views` held by the work `name`, or let go by it wherever
        it held one: a bar runs until the last work holding it lets go."""
        if on:
            for vid in views:
                _held.setdefault(str(vid), set()).add(name)
                state[f"ui_view_busy__{vid}"] = True
            return
        for vid, works in _held.items():
            if name in works:
                works.discard(name)
                if not works:
                    state[f"ui_view_busy__{vid}"] = False

    def _defer(name, fn, views=None):
        """`fn` one turn later, the bar of `views` running until it is done —
        the views of kind `name` when None. Outside the server's loop (a unit
        test): at once."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            print(f"[fespp] {name}: no event loop, computed at once", flush=True)
            fn()
            return
        if views is None:
            mv = core.mv()
            views = mv.panel_ids_of_kind(name) if mv is not None else ()
        view_busy(name, views, True)
        if not _heavy.get(name):
            _heavy[name] = True

            async def _run():
                await asyncio.sleep(0.02)
                try:
                    with state:
                        fn()
                except Exception as exc:
                    print(f"[fespp] {name}: the recompute failed ({exc!r})", flush=True)
                finally:
                    _heavy[name] = False
                    with state:
                        view_busy(name, (), False)

            from trame.app import asynchronous
            asynchronous.create_task(_run())
        state.flush()

    @controller.set("heavy_pending")
    def heavy_pending():
        return any(_heavy.values())

    core.ctx.view_busy = view_busy
    return (_defer, _heavy)
