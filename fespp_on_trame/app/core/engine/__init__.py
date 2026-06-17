"""FESPP engine — the orchestrator that wires the data layer
(SourceRegistry, IjkGrid, Selector, Activator) into the trame
server's state / controller / view lifecycle.

The original `engine.py` (~1.7k LOC god-file) has been split into a
package: `boot.py` keeps the orchestration shell (object
construction + trame decorator wiring), and the thematic modules
hold the actual handler logic. Current modules:

  - `state_defaults` — `state.setdefault` block for every var the
    engine + UI assume to exist.
  - `vtk_log` — stderr tee + `capture_vtk_messages` context manager.
  - `panel_resolver` / `source_resolver` — multi-view + rep-path
    plumbing used across the dispatchers.
  - `data_load` — the `fespp_data_selectors` change handler.
  - `etp` — ETP connection + dataspace dispatch.
  - `visibility` — tree-eye visibility toggling.
  - `active_array` — coloring eye state + ColorBy dispatch.
  - `threshold_dispatch` — threshold chain add/delete/range/visible.
  - `slicer_dispatch` — slicer / range / volume / Z-scale /
    representation dispatchers + `set_slider_value`.
  - `time_realization` — time slider + realization slider handlers.
  - `diff` — A/B diff feature dispatch.
  - `hierarchy` — tree hierarchy mode switch.
  - `selection_dispatch` — `Selector` per-tab + load_mode handlers.
  - `view_ops` — view_update / view_reset_camera sentinel handlers.

Public API:
  - `initialize_fespp_engine(server, *, fespp_plugin_path)` — call
    once at trame server startup.
  - `_tree` (mutable module attribute) — the live `Tree` instance
    built at engine init; UI code that needs to walk the assembly
    reads this attribute. Mirrored by `boot.initialize_fespp_engine`."""
from fespp_on_trame.app.core.engine.boot import initialize_fespp_engine


# Live handle on the assembly Tree, populated by
# `initialize_fespp_engine` and read by ui/app_layout.py.
_tree = None


__all__ = ["initialize_fespp_engine", "_tree"]
