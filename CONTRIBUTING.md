# Contributing to fesppOnTrame

The conventions the code is written in, for people and for coding agents
alike. What a tool already checks is only pointed at here: run the tool. The
architecture and the per-file reference are in the developer wiki
(`doc/wiki/`, start at `Home.md`); local development without Docker is in
`doc/dev/LOCAL_DEV.md`.

## Where code goes

- **`fespp_on_trame/engine/`** holds the rules: pure Python and numpy, no
  Trame, no ParaView where it can be avoided. A decision ("which rows does
  Hide NaN leave out", "which node does a tree open on") is a function here,
  with its unit tests.
- **`fespp_on_trame/app/`** wires them:
  - `boot.py` is wiring only, no logic;
  - `features/` has one feature per module, a `register(core, ...)` that sets
    its controllers and state watchers and hands back what the rest calls;
  - `scene/` is the per-view model (eyes, activation, occupancy, selection),
    one writer per piece of state;
  - `views/` mounts the panels and their widgets.
- **`widgets/<name>/`** is one Vue widget package each: its source in
  `vue-components/src`, its Python wrapper in `trame_<pkg>/`, its built bundle
  in `trame_<pkg>/module/serve` (committed). `widgets/_shared` is the kit every
  widget is written with.
- **No duplication.** A piece used twice becomes a shared helper. A kind of
  card is ONE widget, shaped by its host, never a copy: search every variant
  of a UI form before adding one.
- **No huge module.** Split by feature; keep each module to one job.

## Tests

- **Every fix comes with unit tests** (`tests/unit/`, pytest). When the rule
  sits in a ParaView closure, take it out into `engine/` (or a class with a
  fake core) so it can be tested.
- **A scene or server-side behaviour gets a visual scenario**
  (`tests/visual/scenarios/*.json`, run by `test-visual.ps1`): steps, `expect`
  checks on state, probes, and `peek` shots.
- **A UI behaviour gets a browser spec or probe** (`tests/browser/`,
  Playwright, against a container serving the working tree).
- **A display change is checked on pixels**: look at the shot or the
  screenshot; a probe that passes is not enough.
- The unit suite runs in the image (`test-unit.ps1`) with a lint gate that
  refuses bug-shaped code (flake8, bug codes only, no style).

## Widgets (Vue)

- Written in the shared components of `widgets/_shared` (`fp-btn`,
  `fp-select`, `fp-num`, `fp-range`, `fp-menu`, `FpProgress`...), under the
  widget charter R1–R18 (`doc/wiki/UI-Drawer-Toolbar-Shared.md`, §3). ESLint
  holds what it can: `widgets/lint.sh`.
- After a change in a widget's source: `npm run build` in its
  `vue-components`, AND bump `__version__` in `trame_<pkg>/__init__.py`. The
  version is in the served URL; without the bump a browser keeps the old
  bundle.
- A new component of a lazily loaded bundle needs its tag in `__main__`'s lazy
  list, or it stays unresolved.
- Every event the Vue component emits is listed in the Python wrapper's
  `_event_names`, or it reaches nobody.

## Trame and ParaView traps

- Never name a widget prop after a DOM method or property (`focus`, ...): it
  breaks silently.
- A Python list given to a widget attribute arrives as its first item: pass
  `(repr(the_list),)`.
- A named slot of one of our widgets is filled with
  `html.Template(raw_attrs=["v-slot:<name>"])`; `v_slot_<name>` is dropped.
- Two `js_call` in a row can arrive in the other order: dependent calls go in
  one message. A state key a watcher rewrites: write the final value once.
- Never `print` from a background thread in `pvpython` (its `sys.stderr` is a
  VTK helper; it deadlocked the server): use `os.write(2, ...)`.
- Frames come from the web push (the view proxy's `StillRender`); a probe that
  needs a frame calls `pvv.SMProxy.StillRender()`.
- Prefer ParaView's own mechanism, measured, before writing one.
- A per-view state key is listed in `app/views/per_view_state.py`
  (`SUFFIXED_VARS`), so a view's close clears it.

## The interface

- **No noise**: no hint line, count or button that the screen or a tree
  gesture already gives.
- A control that cannot act is shown greyed with its reason, not hidden.
- Vocabulary: a *view* is a view (3D view, Values view, Well log view); a
  *card* is a panel inside a view (the tree card, the slicer cards). A
  velocity model is a "velocity model", never a "velocity cube".
- User-facing text in English.

## Comments

- A comment says what the code does and why, for the next reader. No
  history ("used to", "fixed on"), no debug notes, no dates, no names of who
  asked.
- A module starts with what it is for; a function's docstring says what it
  takes and gives, in a sentence or two.

## Files

- Some files are CRLF (see `.gitattributes`): edit them with a tool that
  keeps their line endings (`sed -i` strips the CR).
- PowerShell scripts stay ASCII: PowerShell 5.1 reads a file without a BOM in
  the ANSI code page, and one accented character breaks the parse.
- No secret in the repository: keys, tokens and `.env` files live in `_local/`
  (ignored by git).

## Commits

- One short English title that says why; no body, no co-author, no trailer.
- Small slices: one change per commit, its tests with it.
