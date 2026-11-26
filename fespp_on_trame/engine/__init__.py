"""FESPP engine — the data layer (SourceRegistry, IjkGrid, Selector,
Activator, the BlockScope scenes) and the dispatchers `app.boot` wires
into the trame server's state / controller / view lifecycle.

Thematic modules, each holding one piece of handler logic:

  - `state_defaults` — `state.setdefault` block for every var the
    engine + UI assume to exist.
  - `vtk_log` — stderr tee + `capture_vtk_messages` context manager.
  - `panel_resolver` / `source_resolver` — multi-view + rep-path
    plumbing used across the dispatchers.
  - `data_load` — the `fespp_data_selectors` change handler.
  - `etp` — ETP connection + dataspace dispatch.
  - `visibility` — tree-eye visibility toggling.
  - `active_array` — coloring eye state + ColorBy dispatch.
  - `threshold_dispatch` — which threshold entries read a property (the
    unselect guard); the thresholds live in the per-view grid isolates.
  - `time_realization` — time slider + realization slider handlers.
  - `diff` — A/B diff feature dispatch.
  - `hierarchy` — tree hierarchy mode switch.
  - `view_ops` — view_update / view_reset_camera sentinel handlers.
  - `plugins` — where ParaView keeps the plugins loaded beside FESPP.
  - the analysis dispatchers (`stats_`, `distribution_`, `crossplot_`,
    `compare_`, `welllog_`, `reconcile_`, `volumetrics_`, `health_`…),
    each documented in `doc/wiki/Engine-Dispatchers.md`.

The live `Tree` is the server context's (`server.context.tree`, set by
`app.boot.boot_engine`), not a module attribute of this package: the
global it used to be is gone (slice 2b of the overhaul)."""
