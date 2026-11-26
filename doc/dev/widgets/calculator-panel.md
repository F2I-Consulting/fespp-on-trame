# Widget: Calculator (derived properties)

Formulas over the loaded properties of ONE grid — `log10(PERMX)`,
`PORO * NTG`, unit conversions, pay flags — plus the P10/P50/P90
uncertainty percentiles across an MR property's realizations.

## Scope
SINGLETON dockview panel (`VIEW_KINDS["calculator"]`), not per-view: one
panel manages every grid through its grid select. Spawned by the tree's
right-click **Derived property** (`_CONTEXT_ACTIONS` → `open_calculator`).

## Packaging
The control surface is the packaged widget `widgets/calculator`
(`trame_fespp_calculator`, plain HTML + scoped CSS — the house idiom);
`app/views/calculator_panel.py` is a mount point only. It was first written
as 262 lines of Python-generated Vuetify, which is exactly the shape the
project avoids: a `.vue` is edited and rebuilt on its own, while inline
Vuetify puts every UI tweak in the same file as the server logic and hides
template errors from review (the CSV download button shipped inert for
precisely that reason). The preview histogram stays a `trame_plotly` figure
beside the widget — a plot is not part of the control surface, and the
plotly integration is the one already proven by the cross-plot.

## The core idea
A derived property is a **RECIPE, not data**. Nothing is written into the
VTK pipeline: zero proxies, so a FESPP re-execution (checked-set change,
timestep, realization) has nothing to wipe and nothing to rebuild. Values
are computed on demand, in numpy, when a consumer asks.

## Engine
- `engine/derived_expr.py` — the safe expression engine. `parse()` walks the
  AST against a whitelist (arithmetic, comparisons, `&`/`|`, `IfExp`, a fixed
  numpy function table, numeric constants); `evaluate()` runs the compiled
  code with EMPTY builtins. Two non-obvious guards, both from a red-team pass:
  a per-function **arity table** (a ufunc's 2nd positional is its `out=` slot —
  `sqrt(a, b)` would write into `b`, corrupting a shared cache buffer), and an
  `ast.NodeTransformer` that rewrites **integer literals as floats** (`9**9**9`
  builds a 370-million-digit bignum and pegs a core before numpy is reached;
  as floats it overflows in 0.0 ms). Bindings are passed as non-writeable
  views as a second line of defence.
- `engine/derived_props.py` — `DerivedStore`: the def table keyed
  `(rep_path, name)`, identifier binding (case-insensitive, against titles AND
  their sanitized VTK names, with did-you-mean suggestions), same-support
  discipline, cycle/depth guard, `axis_caps` (MR realizations = the
  INTERSECTION of the inputs', so every offered pick is valid by construction),
  and the byte-capped LRU.
- `engine/property_values.py` — **THE seam**: `values_for()` is the single
  function every analysis consumer reads through, and the embryo of
  TARGET_ARCHITECTURE's `endpoint_resolver`.

## Identity
`derived://<rep_path>#<name>`. Deliberately NOT a tree node: the Data Explorer
renders the C++ collector's LIVE `vtkDataAssembly`, rebuilt outside our
control, so a decorated node could die server-side while the client keeps a
stale XML. Every consumer branches on `is_derived(path)` BEFORE any tree
lookup. Rep paths cannot contain `#` (C++ `MakeValidNodeName` strips it), so
`rsplit("#", 1)` is safe.

## Cache
One LRU holds BOTH results and input reads. The key carries two generations:
`load_generation` (bumped on any Selectors commit — a re-execution orphans
everything) and a store-local `_def_gen` (bumped on every create / update /
delete, so a DEPENDENT recipe's cached output can never survive its input's
edit or rename). Keystrokes bump neither, which is what keeps the
type-tweak-retype loop instant on a 1M-cell grid. The time component is
`_ts_keypart`: an explicit `ts_idx` keys itself, while a TS path read in
follow-the-slider mode keys the CURRENT time index — otherwise the first read
would freeze while native reads follow the slider.

## Consumer integration (all head branches, no rewrites)
- `stats_dispatch` — six resolution helpers; a recipe's row comes from
  `_row_stats_from_values` (pure numpy). Its conventions
  are pinned NUMERICALLY against `vtkDescriptiveStatistics` (drogon, 1e-9):
  ddof=1 spread, SAMPLE skewness `G1 = g1·√(n(n−1))/(n−2)` and SAMPLE kurtosis
  `G2 = ((n+1)·g2+6)·(n−1)/((n−2)(n−3))`, `NaN_count = total − Cardinality`.
- `crossplot_dispatch` — the relocation IS the integration: axes, colour-by,
  per-axis real/ts, log toggles and the lasso→3D selection loop all inherit it.
- `distribution_dispatch` — one branch reads through the seam; bins, overlays,
  normalisation, meta and CSV are shared code.

## Ghost cells
An IjkGrid's inactive cells are blanked via a `vtkGhostType` cell array
(bit 32) with a **0.0 FILL** in the property arrays — not NaN. VTK filters
(Threshold, DescriptiveStatistics) skip them; a raw `vtk_to_numpy` read keeps
them (271k bogus zeros on drogon). The seam masks them to NaN so every numpy
path agrees with the native filters — and the native histogram now masks them
too, which removed a bogus spike at 0 the statistics never had.

## Percentiles (P10 / P50 / P90)
A second def type: `create_percentile` reduces an MR property ACROSS its
realizations per cell. Names follow the reserves **exceedance** convention
(P90 = low case = numpy percentile 10, P10 = high case = percentile 90); the
description states the plain numpy percentile so the two can never be
confused. The realization axis is reduced away, so `axis_caps` reports
`is_mr=False` — the result is a single field with no realization selector.

## Reads / writes
- Reads `ui_loaded_array_paths` / `ui_loaded_rep_paths` **[session]**, the
  per-panel `ui_calc_*_<pid>` vars, and `ui_derived_props` (the store mirror).
- Writes the form vars only; the store lives on `server.context.derived_store`
  and OUTLIVES the panel (recipes outlive it like the rows of the Statistics view).

## Notes / open
- Phase 2 = 3D colouring: one session-wide `@smproxy` appender in the
  architecture-reserved `pv_plugins/`, with the probe-proven
  ExtractBlock+PythonCalculator isolate as the sanctioned fallback. Phase 1
  deliberately ships ZERO proxies.
- `_resolve_vtk_name` already returns the derived `vtk_name`: inert today, it
  is what makes phase-2 View rows work with no further edits.
