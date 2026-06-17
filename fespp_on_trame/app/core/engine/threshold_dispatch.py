"""Threshold-chain dispatch — extracted from `boot.initialize_fespp_engine`.

The data layer (`SourceRegistry` / `IjkGrid`) owns the threshold
chain. The engine's job is to:

  1. Publish the chain to `state.ui_threshold_chain` so the UI can
     render it (depth-decorated for indentation).
  2. Forward UI events (add / delete / set_range / set_visible) into
     the data layer via controller methods.

There's no per-rep persistence dict on the state side — chains live
with their rep in the data layer until the rep is unloaded.

All functions in this module are free functions taking explicit
dependencies. boot.py registers thin closure wrappers that capture
the relevant deps from the engine init scope and forward."""
from paraview import simple as pvsimple

from fespp_on_trame.app.core.sources.ijkgrid import IjkGrid


def threshold_provider(state, source_registry):
    """Return `(provider, rep_path)` for the active grid, or
    `(None, None)` when no chain-capable rep is active.

    For IjkGrid: provider is the `IjkGrid` instance and its methods
    take no rep_path (each instance knows its own grid).
    For UnstructuredGrid / ExtractBlock: provider is the
    `SourceRegistry` instance — its compat methods (`add_threshold`,
    `set_range`, …) take rep_path as their first argument."""
    rep_type = state.ui_active_node_reservoir_type_rep
    grid_path = state.active_representation_path
    if not grid_path:
        return None, None
    if rep_type == "IjkGrid":
        ijk = source_registry.get_ijk_grid(grid_path)
        return (ijk, grid_path) if ijk is not None else (None, None)
    if rep_type == "UnstructuredGrid":
        return source_registry, grid_path
    return None, None


def hide_unused_scalar_bars():
    """Compat shim — delegates to
    `source_resolver.hide_unused_scalar_bars` (no view = active).
    Kept here so existing call sites in this module don't change."""
    from fespp_on_trame.app.core.engine import source_resolver
    source_resolver.hide_unused_scalar_bars()


def publish_threshold_chain(state, source_registry):
    """Push the active rep's chain into `state.ui_threshold_chain`
    so the UI re-renders. Idempotent — call after any chain
    mutation.

    Each entry is decorated with `_depth` (0 for roots, +1 per
    ancestor) so the UI can indent each row visually, AND the flat
    list is reordered into a DFS traversal of the implicit
    parent_name → children tree so siblings stay grouped under their
    parent's subtree — without this step, adding a child to t1 after
    a root t2 has been added would place the new entry at the tail
    of the list, making it look indented under t2 even though
    `parent_name` points to t1."""
    provider, rep_path = threshold_provider(state, source_registry)
    if provider is None:
        state.ui_threshold_chain = []
        return
    if isinstance(provider, IjkGrid):
        chain = provider.get_chain()
    else:
        chain = provider.get_chain(rep_path)
    depth_by_name = {}
    for entry in chain:
        parent = entry.get("parent_name")
        depth_by_name[entry["name"]] = (
            0 if parent is None else depth_by_name.get(parent, 0) + 1
        )
        entry["_depth"] = depth_by_name[entry["name"]]
    # DFS reorder: emit each entry right after its parent's subtree.
    # Children of the same parent keep their relative insertion order.
    children_by_parent: dict = {}
    for entry in chain:
        children_by_parent.setdefault(entry.get("parent_name"), []).append(entry)
    ordered: list = []

    def _emit(parent_name):
        for child in children_by_parent.get(parent_name, []):
            ordered.append(child)
            _emit(child["name"])

    _emit(None)
    state.ui_threshold_chain = ordered


def refresh_threshold_ui_for_active_grid(state, source_registry):
    """Republish the chain + available arrays on grid switch /
    property load."""
    provider, rep_path = threshold_provider(state, source_registry)
    if provider is None:
        state.update({
            "ui_threshold_chain": [],
            "ui_threshold_arrays_available": [],
        })
        return
    if isinstance(provider, IjkGrid):
        arrays = provider.available_arrays()
    else:
        arrays = provider.available_arrays(rep_path)
    state.ui_threshold_arrays_available = [n for _, n in arrays]
    publish_threshold_chain(state, source_registry)


def threshold_add(state, controller, source_registry, activator, view,
                  parent_name=None, array=None):
    """Add a threshold under `parent_name` (or the rep root if
    None). The array defaults to the currently visible active
    property — that's the only sensible bind point per the user
    spec (no blind threshold-on-anything VSelect)."""
    provider, rep_path = threshold_provider(state, source_registry)
    if provider is None:
        return
    if not array:
        array = state.active_color_array_name or None
    if not array:
        print("[WARNING] threshold_add: no active array to bind onto")
        return
    if isinstance(provider, IjkGrid):
        new_name = provider.add_threshold(parent_name, array)
    else:
        new_name = provider.add_threshold(rep_path, parent_name, array)
    if new_name is None:
        return
    publish_threshold_chain(state, source_registry)
    # Re-fan the active ColorBy onto the new chain proxy, then
    # sweep the view for stray bars left behind by the new
    # display's auto-coloring.
    if activator is not None:
        try:
            activator.refresh_active()
        except Exception:
            pass
    hide_unused_scalar_bars()
    pvsimple.Render(view=view)
    controller.view_update()


def threshold_delete(state, controller, source_registry, view, name):
    provider, rep_path = threshold_provider(state, source_registry)
    if provider is None or not name:
        return
    if isinstance(provider, IjkGrid):
        provider.delete_threshold(name)
    else:
        provider.delete_threshold(rep_path, name)
    publish_threshold_chain(state, source_registry)
    hide_unused_scalar_bars()
    pvsimple.Render(view=view)
    controller.view_update()


def threshold_set_range(state, controller, source_registry, view, name, low, high):
    provider, rep_path = threshold_provider(state, source_registry)
    if provider is None or not name:
        return
    try:
        low = float(low)
        high = float(high)
    except (TypeError, ValueError):
        return
    if isinstance(provider, IjkGrid):
        provider.set_range(name, low, high)
    else:
        provider.set_range(rep_path, name, low, high)
    publish_threshold_chain(state, source_registry)
    pvsimple.Render(view=view)
    controller.view_update()


def threshold_set_visible(state, controller, source_registry, activator, view,
                          name, visible):
    provider, rep_path = threshold_provider(state, source_registry)
    if provider is None or not name:
        return
    if isinstance(provider, IjkGrid):
        provider.set_visible(name, bool(visible))
    else:
        provider.set_visible(rep_path, name, bool(visible))
    publish_threshold_chain(state, source_registry)
    if activator is not None:
        try:
            activator.refresh_active()
        except Exception:
            pass
    hide_unused_scalar_bars()
    pvsimple.Render(view=view)
    controller.view_update()


def on_threshold_pending_action(state, action,
                                threshold_add, threshold_delete,
                                threshold_set_range, threshold_set_visible):
    """Single-entry-point dispatcher for UI threshold events.

    The UI writes a `{action, ...}` dict into the
    `ui_threshold_pending_action` sentinel; this handler routes it
    to the matching controller method, then clears the sentinel so
    subsequent identical actions still fire (Trame collapses no-op
    writes).

    The four `threshold_*` callables are the controller-registered
    closures from boot.py — passed in rather than re-imported so this
    module stays oblivious to the engine wiring."""
    if not action:
        return
    try:
        kind = action.get("action")
        if kind == "add":
            threshold_add(parent_name=action.get("parent"))
        elif kind == "delete":
            threshold_delete(action.get("name"))
        elif kind == "set_range":
            threshold_set_range(
                action.get("name"),
                action.get("low"),
                action.get("high"),
            )
        elif kind == "set_visible":
            threshold_set_visible(action.get("name"), action.get("visible"))
        else:
            print(f"[WARNING] unknown threshold action: {kind!r}")
    finally:
        state.ui_threshold_pending_action = None
