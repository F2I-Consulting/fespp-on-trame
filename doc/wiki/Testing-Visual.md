# Testing — Visual Regression

Screenshot-based regression tests that exercise the app **headless,
through the real code paths** (state vars + controller methods — the same
ones the browser drives), then diff the captures against recorded
baselines.

```powershell
.\test-visual.ps1                      # run every scenario, compare to baselines
.\test-visual.ps1 -Scenario eye_cycle  # one scenario
.\test-visual.ps1 -UpdateBaselines     # re-record expected screenshots (after an INTENTIONAL UI change)
.\test-visual.ps1 -Software            # draw on the processor (default: the GPU, which the baselines are recorded with since 17/10/2026)
.\test-visual.ps1 -App <repo>\fespp_on_trame   # inject a LOCAL source tree over the image's copy
.\test-visual.ps1 -App <repo>\fespp_on_trame -Widgets   # ...and the local widget packages (widgets/*/trame_*): a NEW widget without rebuilding the image

```

## How it works

1. **Scenario mode in the app** — [`tests/visual/runner/scenario.py`](../../tests/visual/runner/scenario.py),
   armed only when the `FESPP_SCENARIO` env var points to a scenario JSON
   (hooked in `boot.py` on `on_server_ready`; completely inert otherwise).
   Steps run through the genuine pipeline: `load` → `controller.load_epc_file`,
   `check`/`uncheck` → `controller.select_paths` (a read the server has
   already decided, exempt from the R7 confirmation by design),
   `check_raw`/`uncheck_raw` → `state.selected_paths` written as the tree
   WIDGET writes it, which is the only way a scenario can reach the data
   tree's confirmation box (it logs the question and answers it when the
   step carries `"answer": true|false`), `check_kinds` (every node of the
   given kinds; with `"raw": true` through the widget's own write, so a big
   read goes in steps under `FESPP_STEP_LOCAL=1`: the `step_cost` bench reads
   each step's cost in the `[fespp] load: step of …` lines), `activate`, `eye` →
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
   records baselines (`-UpdateBaselines`) or diffs. With `-App <path>`,
   the local `fespp_on_trame` tree is copied into the container BEFORE
   start — to BOTH `/deploy/` and the venv `site-packages/` (the app's
   package imports resolve from site-packages; a `/deploy`-only copy is
   inert) — validating a fix without rebuilding the image.
3. **`tests/visual/compare.py`** — runs with pvpython in a `--rm`
   container: per-pixel diff with tolerance (default: a pixel differs
   when its max channel delta > 12/255; FAIL when > 0.5% of pixels
   differ — absorbs anti-aliasing noise). Failures get a
   `<name>_diff.png` white-on-black mask next to the candidate. A
   scenario made of probes alone (no `shot`, no baseline PNG) passes this
   step on its own checks.

Keep the string literals of `test-visual.ps1` ASCII: the file has no BOM,
so PowerShell 5.1 reads it in the ANSI code page, where an em-dash's bytes
contain a typographic quote that closes the string. Two such literals once
collapsed the whole compare block into an untaken branch — every run
reported PASS without diffing a pixel, and the baselines drifted unseen.

The `activate` and `eye` steps, and the probes that read a colour bar,
address the 3D view (`_render_vid`): the active dockview panel may be an
analysis view a probe opened, and its id names no scene.

## Layout

- `tests/visual/scenarios/*.json` — committed. Current set: `first_load`
  (camera + first paint), `eye_cycle` (geometry-eye hide/re-show),
  `ijk_modes` (full/slice/range + all-volume-eyes-closed), `colormap`
  (`colorbar_probe` — the view's visible colour bar, the Colormap card's
  header and the card's title-bar target must carry ONE text, the
  property's display name `<title> · <component> (<unit>)`, here
  `Temperature (degC)`; then below/above + min/max narrowing),
  `markers_md` (trajectory + marker set),
  `geometry_cascade` (geometry uncheck cascades its properties), `bw_family`
  (BW-first load order + family colour), `bw_grid_gone` (probes only: the
  supporting grid unloaded under a blocked wellbore, the BW unchecked and
  re-checked, the grid back — the dangling grid pointer fixed in FESPP on
  2026-10-10), `surfaces_bulk` (select-all
  surfaces visibility), `threshold_auto` (threshold gate survives a
  cross-tab activation), `release_gates` (threshold-guard veto — the property stays
  checked and the amber snackbar says why — + deterministic activation
  fallback + render-panel routing under a fake stats focus), `uncheck_veto`
  (a trajectory unchecked while its blocked wellbore is checked is pulled
  back, and the snackbar names the blocked well),
  `crossplot_multi` (Drogon: a two-Y cross-plot coloured by Facies —
  charts / axes map / trace count, then pin and focus),
  `compare_view` (Drogon: the Statistics view — three properties ticked in
  its docked tree, the matrix by kind, a folder tick cascading to its whole
  subtree and that tab's cross-plot, a folder tick ABOVE the read cap asking
  first — nothing read, nothing joined, the number in the question — and the
  step back putting the boxes as they were, a baseline, a pinned copy, then
  the histograms of a tab under its own options, each asserted),
  `stats_pin_all` (Volve: `stats_probe` on the rows of a time series, one
  pinned row per time step through `compare_set("pin_all", ...)` and back),
  `vector_component` (`vector_props.epc`: a recipe over `velocity` (3
  components) and over `stress` (6) read at each component through
  `controller.set_vector_component` — the property AND the recipe must
  MOVE between two components (compared by a digest of their values, not
  by their bounds: two components may share an envelope), a recipe that
  fails to be created or to evaluate fails the probe, the live component
  count must be published for the naming, and the Statistics row, cross-plot
  axis and distribution labels — plus, for the property the
  Colormap card edits (`activate` first), the card's label and the 3D
  colour bar's title — must carry `· X` / `· XY` … (a middle dot: VTK
  drew the brackets as parentheses on the bar) and nothing on the
  magnitude; then `value_action_guard_probe` aims the four value actions
  at the grid a pick resolves to — each must answer through the snackbar
  and open no panel),
  `pick_readout` (drogon, probes only, `pick_probe` **2026-09-15**: a click in the middle of the first 3D view in pick mode, the readout must name the cell with its index and its I J K, and the colouring property by its DISPLAY name with the value — `Geogrid  cell #6761  I 46 J 74 K 1  Total Porosity (m3/m3) = 0.258` — never by the VTK array name),
  **the nine functions the point listed as unprotected, covered headless on 2026-09-16:** `xml_explorer` (drogon, probes only: `xml_probe` opens the XML explorer on a node found by title — the uuid is the tail of its path — and requires a panel of kind `xml` holding XML that carries that uuid, or a note saying why not; then `globe_probe` requires the Globe's availability to speak — offered exactly when `ui_globe_why` is empty), `globe` (drogon: `globe_probe` with `mode: true` opens the Globe view beside the 3D view — the flag, a `GlobeScene`, the 3D view's eyes — then `mode: false` closes it, the 3D view's `PdcScene` left alone, a shot in between, and `colorbar_probe` says Facies still colours), `second_view` (drogon: `second_view_probe` opens a second render view from the first and requires the same eyes, the same camera position and a link between the two — the camera link and the second view in one), `timereal` (Volve grid: `timereal_probe` asks the Time card for step 5 then 0 and requires the card's index and the view's `ViewTime` to follow), `stratigraphy` (Volve wells after `welllog_probe`: `strati_probe` opens the Stratigraphy view and requires at least one column or a reason), `axes_grid` (drogon: the Navigation card's grid on, `DataScale` following `set_zscale`, off), `pick_readout` (picking), the ETP connect through the browser (`20-etp-wait`) and the import through every browser spec's `ensureData`;
  `panel_trees` (Volve wells, probes only, `panel_tree_probe`: the one
  grammar of the trees, ASSERTED and not merely logged — an eye is
  offered on what a 3D view could show before anything is ticked; a tick in
  the log tree asks first above the cap, then puts the wellbore in the log
  and fills the panel (curves > 0, nothing dropped); unticking one curve
  takes exactly it out of the drawing and unloads nothing, and ticking it
  back draws it again; the menu's Remove / Add to this view empty the log
  and bring it back with all its curves; a tick in the Statistics tree gives
  its row while the ACTIVE panel is the 3D view, and leaves `selected_paths` still
  holding the property and agreeing with the load channel — the invariant of
  `_apply_selection(push=True)`; the panel eye takes the row out and back with
  `visible_paths__<rvid>` unmoved; and the two panels REOPENED on a session that
  already holds their wells and rows keep every curve and every row, which is
  the path the seeding bug broke),
  `welllog_zones` (Volve wells: `welllog_probe` ticks every channel and
  marker of the first wellbore and builds the panel payload from what the
  PANEL would draw — the read paths less every `welllog_dropped__<vid>` —
  rather than from the session's selection, which made it blind to a log
  that had thrown its curves away; it fails outright if no well would be
  drawn —
  zone counts, then `cutoff_p50`: a rule at the first curve's own P50 must
  flag 25–75 % of its zone as pay, the summation must name the porosity /
  water-saturation logs it read, `phi is None ⇔ phih is None`, and Φ·h of
  that zone recomputed from the NAMED curve through `_pore_thickness` must
  equal the table's (logged as skipped when no kind names a porosity, as
  on Volve); `cutoff_missing`: a rule on a log of ANOTHER wellbore leaves
  no pay band, every pay figure `None` and `pay_na_why = {log: "unlogged"}`,
  then the payload is rebuilt with one of this well's own channels
  unticked and a rule on it must say `"unticked"` — the panel's "tick it in
  the well tree" rests on that distinction — and a rule on a ticked channel
  that yielded no sample (Volve has seven on the probe well) must say
  `"unreadable"`; every branch that does not run says so in
  `scenario.log`).
  **Added since (2026-09-20 .. 2026-09-22):** `subrep_grid_property` (Volve,
  probes only, `block_color_probe`: a grid property paints the
  SubRepresentations extracted from it, `arrays_present` requiring each
  coloured block to actually CARRY the array it colours from and
  `coloured_blocks` counting them), `crs_axes` (Volve, probes only,
  `crs_axes_probe`: the two horizontal ordinates are named by the FILE's
  `ProjectedAxisOrder` — the probe fails when the name came from the EPSG
  registry instead, which is the fallback and not the authority),
  `xml_relations` (drogon, probes only, `xml_relations_probe`: the XML
  explorer's Graph reading through the CONTROLLER, asserting a SYMMETRY that
  codes no uuid — what an object designates must designate it back),
  `zoom_wall` (drogon, probes only, `zoom_wall_probe` **2026-09-22**: 120
  wheel notches fired ON THE INTERACTOR — the path a browser wheel takes, so
  the interactor style and the wall bracketing it are both under test — must
  move the camera, must not put the eye inside the data's padded box, must
  say on the view that they stopped, and one notch the other way must take
  the line back off; measured on drogon: a box 18 233 m across, the eye
  moved 32 679 m inwards and stayed out).
  **2026-09-23:** `zoom_wall_globe` (drogon on the Earth: 220 notches, the eye
  moved 25 522 km inwards and stopped OUTSIDE a 17.6 km data box — the wall
  used to be skipped on a Globe view and one could fly through the grid),
  `cursor_readout` (drogon, plain 3D: the readout must name the two ordinates,
  the elevation AND the VTK block — the block name was silently missing),
  `cursor_globe` (drogon on the Earth: the same readout in lat / lon; before
  this the probe did not fail, it HUNG, which is what the defect was).
  `two_properties` (drogon, **2026-09-23**): a second property ticked on a grid
  that already carries one, WITH A CAMERA MOVE IN BETWEEN — the sequence a
  reader reported as "the grid loses all its colours, the legend still right".
  The `camera_move` step drives the INTERACTOR (a left-button drag, wheel
  notches, and the same count back out so the framing returns and two pixel
  counts can be compared), so the interactor style and its observers are on
  the path. `interactive_frame_probe` closes a blind spot every other colour
  probe had: SaveScreenshot always forces a STILL render, so no scenario had
  ever looked at the frame a hand actually sees while it drags. It renders
  both ways, reads the render window's own pixels back, and with
  `force_lod` drops `LODThreshold` to zero so the decimated actor is used
  even on a grid too small to trigger it by itself.
  IT PASSES, and that is the finding, not a pass to be proud of: server side
  the still frame, the interactive frame and the LOD frame are ALL correctly
  coloured at every step (anchor, per-block triplet and colour bar follow),
  so the reported defect is not reproduced on drogon here and its cause lies
  outside what this scenario can see — the reader's own file, or the client.
- `render_bench` — what one frame costs on the loaded scene, in the view as
  it is, and what the delivery settings do to it: still and interactive
  renders (best of `repeat`), the interactive render with the LOD forced and
  the view's own word on whether the LOD drew it, the still render with
  FXAA off, the delivered geometry size the LOD threshold is compared with,
  and the JPEG a still frame becomes at q100/90/80/70 (bytes, encode time).
  `view_size` sets the window to the reader's real one first — encode and
  render costs scale with the pixels, and the harness's 400x400 would answer
  a different question. Run it twice, with and without `-Software`: the settings
  that matter in software are noise on a GPU (`render_bench.json`).
- `stack_dump` (`{"op":"stack_dump","every":30}`) — faulthandler: every thread's Python stack to the scenario's `crash_stack.txt` (the container's stderr when the run did not arm faulthandler) every N seconds, and the stack on a crash. A server that never returns shows up as the same frames dump after dump; a native death shows up as nothing at all after the last dump (exit code 139 in `docker events`).
- **A scenario that "hangs" at the five-minute mark** — logs cut short, exit 0, no stack — is not the app: trame (wslink) stops the server after 300 s without a connected client, and the runner is no client. The harness launches the app with `--timeout 0` (29/10) and writes `container_state.txt` (status, exit code, OOMKilled, error) next to `app.log`; `docker events --since 3h --filter container=fespp_vis_<scenario>` says how an earlier container ended. Read those before hunting a hang.
- `tree_tick_all` (`{"op":"tree_tick_all","type":"Grid2d","vdomain":"depth"}`) — every node of a kind ticked at once, as a hand ticking a folder does; `vdomain` keeps one vertical domain (the others would ask the domain question).
- `scene_cut_step_timing`, `scene_cut_faces_check`, `scene_blocks_probe`, `isolate_cut_probe`, `timereal_card_probe` (29/10) — a step of the scene cut stage by stage (the cut's own run, what the proxies add, the representation, the render); the IJK grid's exposed faces against a hash of every face of its kept cells, and where the kept cells are; every block the view draws with its cells in the source and in the cut; the isolates of the view, their displays and the scene cuts on them; the time cut of the Time & Realizations card moved through its own controller and read back on the view.
- `visible_reps_probe` (30/10) — every display the view draws: the proxy behind it (registration name, class, global id), its cells, the array it is coloured by. The answer to "what is painted?" when the counts and the shot disagree: a cut scene drawn whole under a SOIL range was the volume's scene cut left visible under the chain's tip (`alk_range_scene_property`). A composite display also lists its selected blocks and every leaf with its cells and z range (`time_depth_convert`: a time polyline converted to depth reads in metres there). Scenarios of 30/10: `alk_property_open` (the Property slicer opened on the active property), `time_depth_convert` (Volve Horizons_Depth + Fault_Horizon_TIME, the tree's own tick `tree_tick` so the domain question is asked — a `check` is a server decision and asks nothing).
- `bounds_probe` — every partition the reader holds with its assembly path and bounds, the renderer's visible bounds and camera, and the assembly's links; `expect_partitions` asserts the count, `unique_links` that no node owns several or stale dataset indices, `strict` that no bounds are NaN, infinite or absurd. Regression `second_file_blocks`: a second EPC used to append every loaded block again (three copies of a 930 000-cell grid after one add).
- `block_vis_probe` — what ParaView was told about the composite (`BlockSelectors`, the colour triplets and tables, `BlockColors`) against what the scene believes visible; `expect_visible` asserts prefixes that must still be in the visible set.
- `cursor_sweep` — the crosshair's ray over an n×n lattice of the view as a hit map next to ParaView's hardware selection at the same pixels (the slow road, but the truth about what is drawn); fails when the ray hits fewer than half the selection's pixels. Measured 2026-09-24 on Volve: 13/49 each side, 49/49 agree.
- `lut_probe` / `rep_set` — the per-block colour pairing (triplets against tables, shared arrays, the blocks' own arrays and ghost-hidden cells, the frame's pixel colours at the centre), and setting properties or keeping/reordering triplets on the main representation by hand: the two that found `InterpolateScalarsBeforeMapping` (Engine-Lifecycle-and-State).
- Regression `wellbore_hides_grid`: grid coloured, wells EPC added, one whole wellbore ticked — the grid must stay in the visible set, keep its coloured pixels and its crosshair hits.
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
— that class is the browser smoke test's job (see below).

A scenario must end within about five minutes of the app's start: no
browser ever connects to the scenario container, so trame's client timeout
(its default, the harness passes no `--timeout`) ends the server then —
the first `step_cost` waited 420 s and died at its `wait`, with no DONE
marker. Keep the settles and waits short, or split a long bench in two.

## Browser smoke test — `test-browser.ps1`

The probes above became a suite. `test-browser.ps1` drives a real Chromium
against a container serving the LOCAL source tree, and fails on anything the
headless harness cannot see: a component that throws, a template that does not
compile, a bundle that never arrives, a panel that comes up empty.

```powershell
.\test-browser.ps1                   # every scenario, fresh container, ~1 min
.\test-browser.ps1 -Scenario tree    # one scenario
.\test-browser.ps1 -Headed           # watch the browser
.\test-browser.ps1 -Keep             # leave the container up
.\test-browser.ps1 -Reuse            # drive the container already running
```

Thirty-five spec files (71 tests), in `tests/browser/specs/`: the shell mounts on
an empty session; a file goes in through *Import data* and the tree fills, a
ticked property colouring the grid; the tree's context menu offers a
property's actions and withholds them on a folder; every tool card of the 3D
view opens with content; every panel of the top bar opens with content; the
Statistics view takes two properties through their kind tabs, the matrix, the distributions and the cross-plot; the four failure
signals are reproduced deliberately, so the suite cannot go green by
forgetting how to fail; a chart keeps its zoom across a refresh; an export
falls back to a download without a clipboard; and what the application SAYS
is read back — the Colormap card titled by the property it edits when the
grid node is active, *Add to stats* and the question an untick of it asks,
and a decimal field showing the point and reading a typed comma.

`02b-colour-after-drag` reads the PIXELS the browser holds: a property, a real
mouse drag on the render, a second property, and the grid must still be
coloured. The streamed frame is a blob `<img>`, not the WebGL canvas beside
it — that one reads back empty — so the image is drawn into an offscreen
canvas and its saturated pixels counted, the same measure the headless probes
use. It runs EARLY, on one grid with two properties and nothing else (run
late, several files are in and the tree has no single row by that name), and
it unticks again whatever it ticked: the suite shares ONE session, and the
scenarios after it were written against the tree they inherit. Measured
2026-09-23: 444 744 coloured pixels, 393 840 after the drag, 394 346 after
the second property.

`25-fluidity` measures what a drag FEELS like, where the user sits: it hooks
the one place every delivered frame goes through in the client
(`URL.createObjectURL` of an image blob), drags a slow circle for a few
seconds and prints images a second, kilobytes and resolution per image,
megabits a second, and the delay before the full-resolution still after the
release; it gates only the mechanics (frames while dragging, a still at the
resting resolution after the release). Run it against a GPU instance with a
big grid open to get the numbers that matter:

```powershell
.\tests\browser\instance.ps1 -Gpu -Port 8096 -Name fespp_fluid -Epc Volve_Demo_Reservoir_Grid_Depth.epc
$env:FESPP_SMOKE_PROPS='Fluids'; .\test-browser.ps1 -Scenario fluidity -Reuse -Port 8096 -Name fespp_fluid
.\tests\browser\instance.ps1 -Stop -Name fespp_fluid
```

Measured 2026-09-23 (GPU, Volve, 1761x1001, seven alternated passes): 12-17
images/s of 11 KB at a quarter of the pixels, 11-16 images/s of 58 KB at all
of them; the still lands 190-340 ms after the mouse-up.

Two verdicts apply after every scenario: the console said nothing (errors,
warnings other than the GPU driver's readback messages, uncaught exceptions and
failed requests all fail the run) and no hyphenated tag is left in the DOM. The
harness addresses the application by role, by visible text and by the class
markers listed in `tests/browser/lib/markers.mjs` — never by a position — and
reads `window.trame` when it needs the application's own view of what it is
showing. Traces and failure screenshots land in `tests/browser/out/`
(gitignored); `tests/browser/README.md` covers the rest, including what is
deliberately left out (the 3D view's context menu, and behaviour tests such as
the slicers, which stay server-side).

### Proving the smoke test can fail

A test that cannot fail proves nothing, so the two failures actually lived
through on this code base are replayed on the application itself, from a copy
of the code injected into the smoke container — the working tree is never
touched. `tests/browser/inject-fault.ps1 -Fault tree-undefined` rebuilds the
tree bundle with a rename that leaves one reference to the old name (the tree
throws on first render and its card is blank); `-Fault menu-attribute` makes
`data_tree.py` serialise the context-menu actions into the template attribute
(the quotes close the attribute, the template does not compile, the whole view
panel is blank). `test-browser.ps1 -Reuse` then goes red within ten seconds of
the boot scenario — `the data tree rendered nothing (no tree component in the
view)` or `the 3D view panel is blank: it holds no canvas` — each with the
console line that names the cause; `-Restore` puts the local code back and the
same run goes green (13 tests, about a minute).

What the console says while the client boots, before any scenario has started,
is charged to the first scenario of the session under an `(at boot)` label —
both real faults speak there and nowhere else — and the long waits give up as
soon as the console reports a fault, naming it instead of timing out. Full
recipe and measured durations in `tests/browser/README.md`.

### Which harness sees what

The two harnesses drive the same application through different doors, and the
line between them is where the code runs. `test-visual.ps1` runs the **Python**
of the app in a container with no browser: it proves the pipeline, the camera,
the colouring and the visibility rules by diffing server-side captures against
baselines, and can therefore never execute a widget's JavaScript — a `.vue`
component compiled into a UMD bundle only ever runs in a browser.
`test-browser.ps1` runs that **JavaScript** in a real Chromium against the same
container image serving the local tree: it proves that every component mounts,
every template compiles, every bundle arrives and every panel the human test
path opens has content, and it never inspects a pixel.

| Failure | Caught by |
| --- | --- |
| a state var or controller that no longer does what a scenario expects | `test-visual.ps1` |
| a rendering, camera, colour-map or visibility regression | `test-visual.ps1` (baseline diff) |
| a rename leaving an undefined variable in a component | `test-browser.ps1` (console, blank subtree) |
| a serialised value breaking a double-quoted template attribute | `test-browser.ps1` (`SyntaxError` at boot, blank panel) |
| a widget bundle missing from the static www | `test-browser.ps1` (`… is not defined`, boot gate never opens) |
| a component Vue cannot resolve | `test-browser.ps1` (hyphenated tag left in the DOM) |
| a panel or card that opens empty | `test-browser.ps1` |
| a frame the server renders but the browser never receives | `test-browser.ps1` (the canvas image must change when a property colours the grid) |
| a wrong value drawn correctly, or a slider that moves the wrong thing | neither — unit tests, or a `test-visual.ps1` scenario with a probe |
| a bug-shaped exception (NameError, AttributeError, KeyError…) raised inside the app and swallowed by a handler | both — the strict reporter, see below |

### The strict reporter is always armed (2026-09-16)

`engine/strict.py` observes every exception at the moment it is raised (Python 3.12 `sys.monitoring`), before any handler sees it, and prints one line per site — `[fespp-strict] NameError: … (engine/x.py:12, in f)` — so a swallowed error is visible without editing the handler that swallows it. It used to be opt-in (`FESPP_STRICT` on the host); both harnesses now arm it on every run and FAIL on a reported site. `test-visual.ps1` passes `-e FESPP_STRICT=1` to every scenario container and, after the scenario's own checks, greps `tests/visual/out/<scenario>/app.log` for site lines (`[<scenario>] STRICT: n exception site(s)…`, the first eight printed). `tests/browser/instance.ps1` starts the smoke container with the same variable; the launcher's child sessions inherit it and write their output to `/deploy/server/logs/launcher/<session>.txt`, which `test-browser.ps1` collects into `tests/browser/out/app.log` at the end of the run and greps the same way (`STRICT: …`), warning when the reporter never reported itself armed. `FESPP_STRICT=all` on the host widens the net to every exception, `FESPP_STRICT=0` switches it off for one run. Measured on 2026-09-16 with the module removals: the whole browser suite and the 27 scenarios raise no bug-shaped exception inside the app.

The static half of the same guard is `tests/unit/test_silent_handlers_ratchet.py`: it counts, module by module, the `except` handlers whose body says nothing (no print, log, state write, note, flag or raise — a heuristic, the same for every module) and refuses a count above the ceiling recorded in the test (776 sites over 73 modules on 2026-09-16, 423 of them a bare `pass`). A new silent handler fails the suite; lowering a ceiling is welcome. The audit of the point (a sentence on screen before each silent `return` on a user path) proceeds module by module from the census; the four handlers that swallowed a WHOLE user action silently (`cmap_range`, `time_index`, `time_speed`, `reconcile_compute`, all refusing a malformed number) now say so — the Colormap card in its note, the others in the log.

Neither harness runs in CI: both need Docker, the local image and the private
datasets. A change to a widget's `.vue` or to the Python that builds a widget's
template calls for `test-browser.ps1`; a change to the pipeline, the state or a
controller calls for `test-visual.ps1`; a change that touches both — a new
panel, a new tree action — calls for both.

## Before the public server takes an image — `test-before-deploy.ps1`

Nothing ran by itself before an image went to the public server: a suite was
launched by hand, or not. `test-before-deploy.ps1` (repo root) is the one
check an image passes first, in about a quarter of an hour:

1. **the image carries the working tree's code** — every `.py` of
   `fespp_on_trame` and every `.py`, `.js` and `.css` of the widget packages
   compared by md5 with the image's site-packages. The unit suite reads the
   tree: what it says is true of the image only then. A difference fails the
   check and names the first files: deploy the trial again, then check;
2. **the lint gate and the unit suite** (`test-unit.ps1`);
3. **a short list of scenarios on the image as it is**, nothing injected
   (`test-visual.ps1 -Scenario … -Image …`, no `-App`): `first_load`, `two_properties`, `colormap`, `threshold_eye`, `scene_slicer`, `markers_md`, `values_filter`, `session_roundtrip`, `stats_pin_all`, `second_view`. One per thing a swap must not
   break; a scenario that fails for a reason of its own has no place in the
   list (`$scenarios` in the script);
4. **the page in a browser** (`tests/browser/probes/page_up.mjs`, exit 0 or
   1): the client mounts, the dock shows a tab, the top bar its buttons, no
   error thrown — on the trial container, when it runs that image.

```powershell
.\test-before-deploy.ps1                 # the image the trial container (fespp_new) runs
.\test-before-deploy.ps1 -Image <tag>    # that image
.\test-before-deploy.ps1 -Quick          # code, lint and unit tests only
```

The verdict is kept by image id under `_local\checked\<id>.txt` (first line
`PASS` or `FAIL`), the whole output next to it (`.log`). The local swap script
of the public server (`deploy\caddy\crhome.ps1`, not in the repository) reads
it: an image with no verdict is checked first, an image that failed — or was
only checked with `-Quick` — is refused, `-NoCheck` passes over it.
