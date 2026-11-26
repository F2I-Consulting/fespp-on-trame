"""Realization and time as the 3D views see them (overhaul slice 7).

One rule each, read by the colours, the cards, the analysis panels and the
assistant — they used to carry their own copies:

- `real_for(state, tree, view_id, array_path)`: the realization a view
  shows for a multi-realization property — its Time & Realizations choice,
  else the first available (boot's `_real_idx_for`, the assistant's
  `_realization`);
- `session_time()`: the session's current time, the TimeKeeper's — what a
  read naming no time step gets (`compare_dispatch`, `derived_props`);
- `view_title(state, view_id)`: the title a view goes by."""

_SAID = {"real": False, "time": False}


def view_title(state, view_id):
    """The title of the 3D view `view_id`, its id when it has none."""
    for panel in getattr(state, "fespp_render_panels", None) or ():
        if isinstance(panel, dict) and panel.get("id") == view_id:
            return panel.get("title") or view_id
    return view_id


def real_for(state, tree, view_id, array_path):
    """The realization index `view_id` shows for `array_path`; None for a
    property with a single realization."""
    from fespp_on_trame.engine import realization_dispatch
    if view_id:
        idx = realization_dispatch.get_active_realization_for_view(state, view_id, array_path)
        if idx is not None:
            return idx
    try:
        return realization_dispatch.default_realization_for(state, tree, array_path)
    except Exception as exc:
        if not _SAID["real"]:
            _SAID["real"] = True
            print("[fespp] view axes: realizations not readable —", exc, flush=True)
        return None


def session_time():
    """The session's current time; None outside a ParaView session (said
    once: a unit test over a fake assembly has no time keeper)."""
    try:
        from paraview import simple as pvsimple
        return float(pvsimple.GetTimeKeeper().Time)
    except Exception as exc:
        if not _SAID["time"]:
            _SAID["time"] = True
            print("[fespp] view axes: no time keeper —", exc, flush=True)
        return None
