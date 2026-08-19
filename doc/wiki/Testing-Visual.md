# Testing — Visual Regression

Screenshot-based regression tests that exercise the app **headless,
through the real code paths** (state vars + controller methods — the same
ones the browser drives), then diff the captures against recorded
baselines.

```powershell
.\test-visual.ps1                      # run every scenario, compare to baselines
.\test-visual.ps1 -Scenario eye_cycle  # one scenario
.\test-visual.ps1 -UpdateBaselines     # re-record expected screenshots (after an INTENTIONAL UI change)
.\test-visual.ps1 -NoGpu               # containers without --gpus all
```

## How it works

1. **Scenario mode in the app** — [`core/engine/scenario.py`](../../fespp_on_trame/app/core/engine/scenario.py),
   armed only when the `FESPP_SCENARIO` env var points to a scenario JSON
   (hooked in `boot.py` on `on_server_ready`; completely inert otherwise).
   Steps run through the genuine pipeline: `load` → `controller.load_epc_file`,
   `check`/`uncheck` → the tree-tab selection vars (`ui_select_node_*`,
   var auto-picked from the node kind), `activate`, `eye` →
   `controller.toggle_rep_visibility`, `set` (any state var),
   `volumes_fraction` / `narrow_color_range` (fraction-based so scenarios
   don't hardcode data ranges), `reset_camera`, `wait`, `shot` →
   `SaveScreenshot` at a fixed 1280×800. Each step takes an optional
   `settle` (seconds; default 1.5). The runner always ends by writing a
   `DONE` marker (+ `ERROR.txt` and `scenario.log`).
2. **`test-visual.ps1`** (repo root) — per scenario: creates a throwaway
   container of the image, mounts `data\private` read-only as
   `/tmp/testdata`, injects the scenario JSON, starts the app **directly**
   (`pvpython /deploy/fespp_on_trame --server …` — bypasses the wslink
   launcher, which only spawns app processes per browser session), polls
   for `DONE`, collects `tests\visual\out\<scenario>\`, then either
   records baselines (`-UpdateBaselines`) or diffs.
3. **`tests/visual/compare.py`** — runs with pvpython in a `--rm`
   container: per-pixel diff with tolerance (default: a pixel differs
   when its max channel delta > 12/255; FAIL when > 0.5% of pixels
   differ — absorbs anti-aliasing noise). Failures get a
   `<name>_diff.png` white-on-black mask next to the candidate.

## Layout

- `tests/visual/scenarios/*.json` — committed. Current set: `first_load`
  (camera + first paint), `eye_cycle` (geometry-eye hide/re-show),
  `ijk_modes` (full/slice/range + all-volume-eyes-closed), `colormap`
  (below/above + min/max narrowing), `markers_md` (trajectory + marker set).
- `tests/visual/baselines/<scenario>/` — **gitignored**: they depend on
  this machine's GPU rendering and on `data/private` datasets
  (`drogon.epc/.h5`). Re-record with `-UpdateBaselines` after any
  intentional visual change.
- `tests/visual/out/<scenario>/` — gitignored per-run output
  (screenshots, `scenario.log`, diff masks).

## Limits

Server-side captures catch pipeline / camera / coloring / visibility
regressions (they would have caught the NaN-transparent, legacy-overlay
and unframed-camera bugs). They do NOT catch pure client frame-delivery
bugs (the server renders right but the browser never receives the frame)
— that class needs a browser-level smoke (Playwright), kept as a v2.
