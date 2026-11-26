"""well ↔ model reconciliation by kind (engine/reconcile_dispatch)
pairs None = automatic pairing (by kind, else by name); a list = the
user's own, kept until they ask for the automatic ones again

(Moved out of app/boot, overhaul slice 10.)"""
from fespp_on_trame.engine.utils import csv_export


def register(core, *, _defer, _wellbore_of):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_reconcile_inputs, _refresh_reconcile)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    source_registry = core.source_registry
    _mv = core.mv
    # --- well ↔ model reconciliation by kind (engine/reconcile_dispatch) ---
    # pairs None = automatic pairing (by kind, else by name); a list = the
    # user's own, kept until they ask for the automatic ones again
    _reconcile = {"pairs": None, "step": 1.0}

    def _reconcile_inputs():
        """(wells, selected) the table reads, merged from its two doors:
        the log view's wells and the panel's own tree
        (`reconcile_dispatch.session_inputs`)."""
        from fespp_on_trame.engine import reconcile_dispatch
        return reconcile_dispatch.session_inputs(
            getattr(state, "ui_welllog_wells", None) or [],
            getattr(state, "ui_reconcile_logs", None) or [],
            getattr(state, "ui_reconcile_dropped", None) or [],
            getattr(state, "selected_paths", None) or [],
            _wellbore_of,
            lambda w: reconcile_dispatch.channel_paths(tree, w))

    def _refresh_reconcile():
        _defer("reconcile", _refresh_reconcile_now)

    def _refresh_reconcile_now():
        mv = _mv()
        if mv is None or not mv.panel_ids_of_kind("reconcile"):
            return
        from fespp_on_trame.engine import reconcile_dispatch
        try:
            wells, selected = _reconcile_inputs()
            res = reconcile_dispatch.compute(
                state, tree, source_registry,
                pairs=_reconcile["pairs"], step=_reconcile["step"],
                wells=wells, selected=selected,
                dropped=getattr(state, "ui_reconcile_dropped", None) or [])
            res["csv"] = reconcile_dispatch.csv_payload(res)
            state.ui_reconcile = res
        except Exception as exc:
            print("[fespp] reconcile error:", exc, flush=True)
            state.ui_reconcile = {"rows": [], "pairs": [], "logs": [],
                                  "props": [], "note": f"error: {exc}",
                                  "csv": dict(csv_export.EMPTY_PAYLOAD)}

    @controller.set("open_reconcile")
    def open_reconcile():
        """Open (or focus) the Log ↔ Grid table — session-level like the log
        view it reads from."""
        mv = _mv()
        if mv is None:
            return
        try:
            mv.add_view(kind="reconcile")   # singleton -> opens or focuses
        except Exception as exc:
            print("[fespp] open reconcile view error:", exc, flush=True)
        _refresh_reconcile()

    @controller.set("reconcile_compute")
    def reconcile_compute(step=None):
        try:
            if step is not None:
                _reconcile["step"] = max(0.05, float(step))
        except (TypeError, ValueError):
            print(f"[fespp] reconcile step kept at {_reconcile.get('step')!r}:"
                  f" {step!r} is not a number", flush=True)
        _refresh_reconcile()

    @controller.set("reconcile_auto_pairs")
    def reconcile_auto_pairs(*_a):
        _reconcile["pairs"] = None
        _refresh_reconcile()

    @controller.set("reconcile_set_pairs")
    def reconcile_set_pairs(pairs):
        _reconcile["pairs"] = [
            {"log": p.get("log"), "prop": p.get("prop"),
             "basis": p.get("basis") or "manual"}
            for p in (pairs or []) if p.get("log") and p.get("prop")]
        _refresh_reconcile()
    return (_reconcile_inputs, _refresh_reconcile)
