# Browser smoke test

What the headless harness (`test-visual.ps1`) cannot do: run the widgets'
JavaScript. Everything under `widgets/*/vue-components/src/*.vue` is compiled
into UMD bundles that only ever execute in a browser, so a rename that leaves an
undefined variable in a component, or a template attribute broken by a quote,
passes every Python test and still leaves a panel blank.

This harness opens a real Chromium on the application, loads a file, and walks
the gestures that make components render.

## Where it sits

| Harness | Executes | Sees | Blind to |
| --- | --- | --- | --- |
| `pytest tests/unit` | Python functions | logic, state transitions | rendering, the client |
| `test-visual.ps1` | the app headless, through its real controllers | pipeline, camera, colouring, visibility (pixel diff against baselines) | anything that only happens in the browser |
| `test-browser.ps1` (this) | a real Chromium on the served application | widget JavaScript, template compilation, bundle delivery, empty panels, console errors | pixel-level correctness, behaviour under interaction |

It is a **smoke** test: it proves every component renders and the console stays
silent along the human test path. It does not judge what is drawn — that is
`test-visual.ps1`'s job — and it replaces neither of the other two. A few
scenarios go one step further, because only a browser can see them at all: a
chart keeping its zoom across a refresh (plotly's `uirevision`), an export
falling back to a download when the page has no clipboard, and the numbers and
CSV files the widgets write (the shared rule in `widgets/_shared/`).

## Prerequisites

- Docker with the `fespp_on_trame:local` image (the tag `build.ps1` builds,
  see the main `README.md`).
- `node` and `npm` on the host; the driver is installed on first run.
- `data/private/vector_props.epc` (+ `.h5`). The scenarios say so and stop
  early when the file is missing.

The pass has its own container (`fespp_smoke`, port 8095), so it never collides
with another instance of the application, such as one `run.ps1` started on
8080; both can run at once.

## Running it

```powershell
.\test-browser.ps1                   # every scenario, on a fresh container
.\test-browser.ps1 -Scenario tree    # one scenario (a fragment of the file name, number left out)
.\test-browser.ps1 -Headed           # watch it happen
.\test-browser.ps1 -Keep             # leave the container up afterwards
.\test-browser.ps1 -Reuse            # drive the container already running (local code NOT re-injected)
```

Exit code 0 and `BROWSER TESTS: PASS` on green; 1 and `BROWSER TESTS: FAIL`
otherwise, with the path of the traces. An unknown `-Scenario` lists the known
names and exits 1.

| Option | Default | Use |
| --- | --- | --- |
| `-Port` | `8095` | port of the disposable container |
| `-Name` | `fespp_smoke` | its name — what `-Reuse` and `inject-fault.ps1 -Name` look for |
| `-Image` | `fespp_on_trame:local` | the image to start from |
| `-Epc` | *(none)* | a file of `data\private` opened at startup, for hand-driving with `-Keep`; the scenarios import their own file |

Environment variables read by the specs, all optional:

| Variable | Default | Meaning |
| --- | --- | --- |
| `FESPP_SMOKE_URL` | set by the launcher | where the application is — needed when running `npx playwright test` by hand from `tests/browser` |
| `FESPP_SMOKE_HEADED` | unset | any value shows the browser |
| `FESPP_SMOKE_OUT` | `out/` | where traces and screenshots go |
| `FESPP_SMOKE_DATA` | `data/private` | the folder of the driven file |
| `FESPP_SMOKE_EPC` | `vector_props.epc` | the file to drive; its `.h5` is picked up when present |
| `FESPP_SMOKE_PROPS` | `poro,velocity` | two properties of one grid: the first colours it, both feed the Statistics view |
| `FESPP_SMOKE_FOLDER` | `properties` | a folder row that must NOT get the value actions |
| `FESPP_SMOKE_CATEGORY` | unset | a RESQML `CategoricalProperty` of the driven file (one with a `StringTableLookup` — a `DiscreteProperty` such as drogon's `Facies` has no names and legitimately shows codes); `12-categories` runs only when it is set and skips out loud otherwise |

First run installs the driver (`npm install` + `npx playwright install
chromium`, ~30 s, ~700 MB under `%LOCALAPPDATA%\ms-playwright`). A full pass is
about a minute, including the container.

The container serves the **local source tree** — `instance.ps1` starts one from
`fespp_on_trame:local` and injects the app package, the widget packages and
their JS bundles, with no image rebuild. So a failure points at the working
tree, not at the image. A widget whose bundle is not built
(`widgets/<x>/trame_fespp_<x>/module/serve` missing) is skipped by the
injection, and the boot scenario reports it as `trame_fespp_<x> is not
defined`.

`instance.ps1` also works alone: `.\tests\browser\instance.ps1 [-Port] [-Name]
[-Image] [-Epc <file>]` starts such a container, `-Stop` removes it.

## What fails a scenario

Two verdicts apply to every scenario without it asking (`lib/app.mjs`):

- **the console stayed silent** — no `console.error`, no warning of the
  application's own, no uncaught exception, no failed request. The only
  warnings tolerated are the GPU driver's readback messages, which the remote
  3D view provokes and nothing in the application can prevent
  (`CONSOLE_NOISE` in `lib/markers.mjs`);
- **no hyphenated tag is left in the DOM** — the page serves the production
  build of Vue, which prints nothing when it cannot resolve a component; the
  tag left verbatim is the only trace there is.

On top of that each scenario has its own: a blank view panel (no canvas), a
tree that rendered nothing, a tree with no rows, a card that opens with neither
text nor controls, a panel that comes up empty, a tab that draws no body, a
gesture that times out.

What the console says **while the client boots** — before any scenario has
started — counts too: it is charged to the first scenario of the session and
printed with an `(at boot)` label. A `SyntaxError … at Function (<anonymous>)`
from `vue.global.js` is annotated for what it is: a template that did not
compile, which the production build of Vue reports without naming the
component.

The long waits (a file loading, a property being read) give up as soon as the
console reports a fault, and say so: `gave up waiting for <what>: the browser
console reported — …`. A component that just threw will not produce what is
being waited for, and a two-minute timeout would say nothing.

Each scenario writes what it did and what it saw to `out/<scenario>.log`, and a
screenshot of the failure next to it. `out/` is gitignored.

## Proving it can fail

The two failures actually lived through on this code base can be replayed
against a running smoke container, from a **copy** of the code — the working
tree is never touched:

```powershell
.\test-browser.ps1 -Keep                              # a container to break
.\tests\browser\inject-fault.ps1 -Fault tree-undefined
.\test-browser.ps1 -Reuse                             # FAIL: "the data tree rendered nothing"
.\tests\browser\inject-fault.ps1 -Restore
.\tests\browser\inject-fault.ps1 -Fault menu-attribute
.\test-browser.ps1 -Reuse                             # FAIL: "the 3D view panel is blank"
.\tests\browser\inject-fault.ps1 -Restore
.\test-browser.ps1 -Reuse                             # PASS
```

- `tree-undefined` renames a computed of `DataExplorerTree.vue` and leaves one
  reference to the old name, rebuilds the bundle with the widget's own
  toolchain (from a copy under `%TEMP%`) and injects it with its stylesheet.
  The tree throws on first render: verdict in ~10 s, `the data tree rendered
  nothing (no tree component in the view)` plus the console line naming
  `trame_fespp_tree.umd.js` and the computed. The script checks that each
  half of its rewrite found its line and refuses to run otherwise: a rename
  that leaves no stale reference is a working bundle, and the suite would
  then pass where it is expected to fail.
- `menu-attribute` makes `data_tree.py` serialise the context-menu actions into
  the template attribute instead of the state variable. The quotes close the
  attribute, the template does not compile, the whole view panel is blank:
  verdict in ~10 s, `the 3D view panel is blank: it holds no canvas` plus the
  annotated `SyntaxError`.

Measured on the reference machine: a green pass is 25 tests (plus one skipped
without `FESPP_SMOKE_CATEGORY`) in about 2 min wall with the container start; either fault is reported within 10 s of the
boot scenario, and a full red pass takes ~2 min because Playwright reopens the
session after each failed scenario.

A third fault lived through, now caught by `03-menu` and `08-charts`: a widget
prop named like a DOM event (`focus`) makes trame refuse to serialise the
element, which then mounts with **no bindings at all** — an empty toolbar over
an empty figure, no console error, and a panel that passes any "it rendered"
check. The tests read the X select's options and pick a Y from the widget.

## Scenarios

39 tests, run in file order on one shared browser session (one of them
skipped on the default file; two mount a widget alone in a sandbox page).

| File | What it drives |
| --- | --- |
| `01-boot` | the shell mounts on an empty session: Vue, a dockview tab, the top bar, a 3D canvas |
| `02-tree` | a file goes in through *Import data*, the tree fills, a ticked property colours the grid |
| `03-menu` | the tree's context menu: a property's actions, a folder's lack of them, and an action that opens its panel |
| `04-cards` | every tool card of the 3D view's toolbar opens with content |
| `04b-charter` | the application reads as one product: the header a panel wears, the sentence an empty one says and whether the gesture it names exists, which tree offers a bulk select, the verb on an action button, and the one confirmation box |
| `04c-components` | the invariants the shared components of `widgets/_shared/components/` exist to hold, swept over every panel and card at once: no tag Vue could not resolve, no component rendered with a required prop missing, an empty state that says what it would show and the gesture that fills it (with the words it quotes on screen in the same panel), a note that carries its severity and its ×, a button that says what it does in Title case, a right group opened by the summary and closed by the tree button, no segmented control of one, no `input[type=number]`, one confirmation box and it is the layout's, no note inside a row of controls, nothing left marked busy, the options of a histogram in the same words wherever one is drawn. It opens every panel of the top bar and every tool card, and closes again what it opened — the session is shared with the scenarios after it. What is not converted yet is held on named LEDGERS at the top of the file — the run fails on anything OFF them, and prints the lines a pass no longer meets so a conversion step can strike them off |
| `05-panels` | every panel of the top bar opens with content |
| `06-compare` | the Statistics view: its docked tree, two ticked properties, a tab per kind with its matrix, its distributions and its cross-plot; a tick that reads (a leaf, a folder under the cap, a folder over it answered yes) reads into the view and into NO 3D view — nothing in any view's own visible set, nothing under the panel's id, an open eye in the tree and nothing said about it — and the eye then takes it out and back; the tree's Reservoir / Surface / Well family tabs with their counts, an empty tab that says so, and a folder tick made under a tab that reads only what the tab shows; the right-click of a row: the baseline and the removal, the pin greyed with why on a property with nothing to keep (the pin itself is `21-stats-rows`'s) |
| `07-controls` | the four failure signals reproduced in a sandbox page, independent of the session — a smoke test that cannot fail is not a test (the two real faults are replayed on the application itself by `inject-fault.ps1`, above) |
| `08-charts` | a cross-plot opened from the tree, a Y picked in its toolbar, the badge reading `N of M pairs`; a box-drag zoom that survives a log-Y refresh and goes away on a log-X re-framing; the Statistics view's distributions keeping their zoom across a bin change |
| `09-exports` | the Data health `Copy CSV` with the page's clipboard taken away (what plain http does): a dated `health_<date>.csv` download whose first line is the `# fespp-on-trame` provenance header and whose column line follows it, the button saying `Downloaded`; then with the clipboard back, the button saying what it did; the Statistics view's `Copy CSV`, on a property of the file and on a difference made in the calculator: a `statistics_<date>.csv` with the same header, one unit per column, the weighted means and the percentiles, and a Sum on screen exactly where the block says it means something |
| `10-words` | what the application says: the Colormap card titled by the PROPERTY it edits when the grid node is the active one (its title bar, its header and the Attributes card agree), the menu of an unread property (Info alone) and *Add to stats* once it is read, the question naming the Statistics view when it is unticked, and a decimal field (the Volumetrics GOC) that is a text field showing the point and reading a typed "1250,5" as 1250.5 end to end — a `type="number"` input is written in the browser's locale, whatever `lang` it carries |
| `11-numbers` | the one number format, read where only a browser can: the Volumetrics table (unit in every volume header, every cell of the totals row matching the four-digit / thin-space / scientific rule, the barrel option saying it is a reservoir barrel) and the Colormap card (its range labels); then the card's `Symmetric around 0` button, which the server answers with a range of `[-m, +m]` |
| `12-categories` | with `FESPP_SMOKE_CATEGORY` set: a cross-plot coloured by that property carries the file's category names in its legend, not bare codes; skipped, and saying why, on the default file |
| `13-zones-export` | the well-log zones table's `Copy CSV`, mounted in a sandbox page on the working tree's bundle (the driven file has no well) with a payload shaped like the server's: the file named by the server, its header lines verbatim, raw figures, `n/a` where a zone could not be evaluated and the reason in the `note` column |
| `14-compare-export` | the matrix of the Statistics view in the same sandbox: a block's unit in its header (or `mixed units`, naming them), the unit at its power in a metric header, cells written by the number rule, and a `Copy CSV` of raw metrics with one unit per column and a unit column for a mixed block; the rows that follow an item: what they read on in place of the representation, no picker, no pin, a Distribution button, a menu that says why, the `Mean (L)` column and `mean_length_weighted` only with a row that has it, a `Sum` hidden where it means nothing, a row's note on its hover and no sentence under the block; the rows of one block that differ: a `Sum` written as a dash, with no difference and no tint, where it means nothing on the row or on the baseline, its raw figure kept in the file; the pin greyed with why where the row has nothing to keep; a `time_step` column of dates, an index only where a row has no words |
| `15-tree-grammar` | the one grammar of every tree: in the Statistics tree the checkbox is the session's load and the eye the row in the view, the 3D views untouched; an untick of what another view uses asks first and names it, Cancel changing nothing; the right-click of the tree offers the panel's acts on the side of the eye (Add to stats or Remove from stats, the baseline, the two doors out, the door to Data health), one greyed line on a representation, no menu on a kind folder |
| `21-stats-rows` | the rows that follow an item in the Statistics view: a filter in a 3D view (the Property slicer) gives a row `<property> On 3D view 1` with no gesture, which reads what the view draws and goes with the filter; a blocked wellbore's eye gives its row with `Mean (L)`, the eye closing it, its menu taking the part out; the Distribution button opens the Distribution view at the realization or the time the row reads, a part's or a view's row included; a pin keeps a row as it reads, a second one at the same coordinate is refused and said, the copy can be the baseline and goes by its own menu; a wide matrix scrolls its own table. Parts and realizations are read off `ALK_14Layers.epc` in a session of its own (`ownSession`), and step aside without the file |

## Rules the harness follows

- It addresses the application by **role** (a button of the top bar), by
  **visible text** (the tree row titled `velocity`) or by a **stable class
  marker** (`lib/markers.mjs`) — never by a position, a size or an index in a
  layout.
- It asks the application what it believes it is showing rather than guessing
  from the screen: `window.trame` exposes the shared state, so the list of
  tools a view offers, the array colouring a representation and the loaded
  properties are read from there (`state()` in `lib/app.mjs`).
- **One page for the whole pass.** Every page opened starts a ParaView session
  on the server that outlives it; the scenarios run in file order and share one
  session, and the `ensure*` helpers let any of them run alone all the same.

## Adding a scenario

Add `specs/NN-name.spec.mjs`, import `test` from `../lib/app.mjs`, and use the
`app` fixture — `app.page` is the shared page and `app.note(...)` writes the
trace. The two verdicts come for free. Keep new markers in `lib/markers.mjs`,
and the file-specific expectations in `lib/dataset.mjs`. A file that would change
what every later scenario finds goes in a session of its own (`ownSession`, which
takes the place of `app` in the helpers; the scenario ends on `holdVerdicts`).

## Probes

`probes/` holds the exploratory scripts the harness was built from — the boot
sequence timed (`boot.mjs`), the four failure signals reproduced
(`signals.mjs`), every card and panel swept with their sizes and texts
(`sweep.mjs`), the pixels a view still draws across camera gestures
(`camera_loss.mjs`, on an instance started with `-Epc drogon.epc`), a big
read in steps with Stop and a "clear all" in its middle (`stepped-read.mjs`,
on drogon). They assert nothing; they print. Run one against a live instance
when a marker stops matching: the instance's URL is the first argument
(`node probes/<probe>.mjs [url]`, from `tests/browser`), and without it
`FESPP_SMOKE_URL`, then the `instance.ps1` default.

`stepped-read.mjs` needs an instance whose container has
`FESPP_STEP_LOCAL=1` in its environment (`instance.ps1 -Epc drogon.epc
-AppEnv FESPP_STEP_LOCAL=1`): only a server read runs in steps by default,
and the variable makes a file read step too.

`components.mjs` is the exception: it does assert, and it does not need the
application. It drives **the bench** — `fixtures/index.html`, every shared
component of `widgets/_shared/components/` in every state it can be in,
including the states that are defects on purpose — and writes one screenshot
per component into `out/components/`. A component nobody has rendered is not
delivered, and the bench is where a state that never occurs in the running
application (a busy panel, an export that failed, a required prop left out)
can be looked at.

```sh
node fixtures/build.mjs        # vite + the widgets' own toolchain, borrowed from widgets/tree
node probes/components.mjs     # serves the build on 127.0.0.1:8099, drives it, screenshots it
```

The build is made twice: with the **production** Vue the application serves,
where prop validation is stripped and a missing required prop shows as the
visible accusation the component renders instead; and with the
**development** Vue, where the validators still speak — the probe prints what
they say, which is the only place that half of the "required prop" rule can be
read.

## Known limits

- The **3D view's own context menu** is not covered: a right-click on the
  canvas did not surface it in the driver, and the radial menu module is not
  enabled in this build.
- **Behaviour** is out of scope here: slicers and thresholds (two-handle
  sliders), volumetrics with contacts, a well log flattened on a marker. These
  are covered server-side by `test-visual.ps1`, and dragging a handle is slow
  and fragile from a driver.
- The pass drives a **small file** (`data/private/vector_props.epc`). Large
  datasets make the run slower, not more revealing.
- **Style** is not judged: a widget that renders unstyled (a stale
  `style.css` next to a fresh bundle) passes as long as it has content.
- **Only what the scenarios walk** is covered: a panel or card that is not
  reachable from the top bar, the view toolbar or the tree's context menu is
  never opened. Add a scenario for it.
- **Not hooked into CI**: it needs Docker, the local image and the private
  datasets, so it runs on a developer machine — as `test-visual.ps1` does.
