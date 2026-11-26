# fespp-on-trame — Per-view widget architecture (design record, 2026-06)

> **A design record.** These notes are the blueprint the multi-view was built
> from; what runs today is described on the wiki (`doc/wiki/Architecture.md`,
> `UI-Content.md`). Kept for the reasoning, not as a reference.
>
> Design notes for the rearchitecture. **No code yet** — this folder is the
> blueprint. The goal: a UI that is a **composition of self-contained widgets**,
> each with a clear `(input · behaviour · state)` contract, so the UI is easy to
> redesign and rearrange without touching the data layer.

## 1. Why V2

Before the multi-view there was **one global drawer** (the tree + the attributes card)
*retargeted* to an "active view" via `drawer_target_view_id`. But the **backend
is already per-view**: `scene_registry`, `ViewScene`, `RepInScene`, and all the
per-`(rep, view)` state (eyes, slice, clip, threshold, colouring, z-scale).

So the global UI has to **marshal** per-view backend state into a single panel —
which is exactly where the hardest, most fragile code lives:

- the `*_by_view` maps that every global panel reads/writes,
- the `_eye_slot` tree cell with its `v-for` over *all* panels + "collapse"
  logic (one tree showing N views' eyes),
- the active/target-view indirection (`drawer_target_view_id`).

**V2 aligns the UI with the already-per-view backend.** Each view (a dockview
panel) owns its own tree + attributes + legend + time control. That *removes*
the marshalling instead of adding to it.

## 2. The two layers — **session** and **view**

The boundary is **session vs view** (not a vague "global"). In Trame
`server.state` is **session-scoped** — it already *is* the per-session layer, so
this maps cleanly onto the framework, and stays correct if multi-user is ever
added ("session" = "one user's workspace").

### Per-session (the trame session — one user's workspace)
- The loaded **files** (the `Collector` / EPC sources).
- The **loaded-node set** = `fespp_data_selectors` (loaded into the
  `source_registry` **once**, shared by every view of the session).
- The `source_registry` (the data filters — load once, never per-view).
- The `data_load` pipeline (selection → loaded sources).
- **Workspace-wide options**: units / CRS, colour-palette defaults, display
  preferences (the "global options" that are genuinely session-wide).
- The **Import dialog**, the **toolbar**, the **layout / view manager**.

### Per-view (one instance per dockview panel, scoped to a `view_id`)
- The **3D render view**.
- The **data-explorer tree** (checkbox = load *[session]*, eye = show-in-this-view
  *[per-view]*). **One tree for every view kind, Globe included.** A filtered
  Globe variant was tried and dropped: a Globe has two regimes — the Earth
  framing, where it is a locator and a whole field is a single dot (measured:
  15.2 km per pixel at 5 R, so drogon's 17 km grid is 1.1 px), and the framing
  onto ONE object, where it is an ordinary 3D view that happens to be
  geolocated and every property is meaningful again. Since the second regime
  exists, a reduced tree only bought divergence: objects loaded by the session
  cascade but not shown, and folder eyes needing client-side expansion because
  a synthetic folder path is not a valid block selector. What answers the
  locator regime is the **named pin per grid and per well head**, not a
  shorter tree.
  The two regimes are reached from different places, on purpose: the Globe
  card holds *Whole Earth*, and flying onto one object is the view's
  right-click menu, because that is where the objects have names. There is no
  "zoom to the data" any more — it framed the union of everything visible, so
  with two reservoirs loaded it aimed at the midpoint between them and showed
  neither.
  **The Earth is never hidden**, at any zoom: seeing the terrain around the
  data is what the Globe is for. That used to be impossible because ParaView
  pins the near clipping plane at far/1000 over everything visible, so a
  6 378 km globe clipped away anything smaller than ~22 km and the close
  framing had to hide it. `GlobeScene._apply_camera_rule` fixes the cause
  instead: it locks `MaxClipBounds` to a cube of 50 camera-distances around
  the focal point (measured: near falls from 22 454 m to 40 m at a ±20 km
  box), and it runs from a camera observer, so the WHEEL gets it too — the
  wheel never goes through any of our controllers. The same callback sizes the
  locator boxes, which is why they stay legible from space and become the
  grid's real extent as you come in.
  A node's eye drives its whole subtree (see `TreeNode.eyeLeaves`), so a folder
  opens or closes everything under it in one round-trip.
- The **attributes panel** (slice / clip / threshold / representation / solid
  colour).
- The **colour legend** (the active array's scalar bar).
- The **time control** (only if the view holds a time-series rep).
- The **active node** (focus for the attributes panel).

### Session vs view — the option-by-option call
Some of the drawer application's "global" options are *comparison knobs* better kept **per-view**:

| Option | before | recommendation |
|---|---|---|
| Units / CRS / palette / display prefs | global | **per-session** (workspace-wide) |
| Selection (load) | global | **per-session** (load once) |
| **Z-scale** (vertical exaggeration) | global | **per-view** (compare flat vs exaggerated) |
| **Realization** (multi-realization pick) | global + per-view | **per-view** (compare realizations side by side) |
| **Time index** | per-view (+ resync) | **per-view** (compare time steps) |
| Active node / visibility / colour / slice / clip / threshold / camera | per-view | **per-view** |

**Design principle — per-view first.** Implement every option **per-view**; a
per-session version is then a trivial *broadcast / override* on top (e.g. a
"sync z-scale across all views" toggle that writes the same value to each view).
Retrofitting per-view onto a per-session option is the hard direction. So when in
doubt: **per-view.**

## 3. The key semantic: **checkbox vs eye**

This single clarification is what makes V2 simple:

| Affordance | Meaning | Scope | State it mutates |
|---|---|---|---|
| **Checkbox** (tree select) | **LOAD** this node's data | **Per-session** (loaded once) | `ui_select_node_*` → `fespp_data_selectors` |
| **Eye** (tree / legend) | **SHOW** in *this* view | **Per-view** | per-view visibility (`ui_hidden_rep_paths` scoped to `view_id`) |

All views' trees show the **same checkboxes** (the session's loaded set, reactive
— free in Trame). Each tree has **one eye column** = its own view. That kills the
`_eye_slot` per-panel `v-for` and the conflation of "loaded" vs "visible".

## 4. What the multi-view deletes from the drawer application

- `drawer_target_view_id` and all retargeting logic.
- `_eye_slot`'s `v-for` over panels + collapse logic → **one eye per node**.
- The `*_by_view` global maps **as the panels' source of truth** (each panel
  owns its own view's slice of state, keyed by its `view_id`).
- The single global **drawer** (tree + attributes move into the panels).

## 5. What V2 keeps (unchanged or light touch)

- `data_load`, `source_registry`, the **C++ FESPP** extractor — untouched.
- `scene_registry` / `ViewScene` / `RepInScene` — **already per-view**; V2 just
  gives each its dedicated UI instead of a retargeted global one. This is why
  the rearchitecture is mostly *UI*, not data.
- The analysis panels (stats / distribution / compare / diff) — already
  per-property dockview panels.

## 6. Widget catalogue

Each widget has its own spec in [`widgets/`](widgets/) with **Input**,
**Behaviour**, **Reads**, **Writes (global/back-end state-changes)**.

| Widget | Scope | Spec |
|---|---|---|
| Import dialog | global | [import-dialog.md](widgets/import-dialog.md) |
| Toolbar | global | [toolbar.md](widgets/toolbar.md) |
| Layout / view manager | global | [layout-view-manager.md](widgets/layout-view-manager.md) |
| View panel (3D + host) | per-view | [view-panel.md](widgets/view-panel.md) |
| Data-explorer tree | per-view | [data-explorer-tree.md](widgets/data-explorer-tree.md) |
| Attributes panel | per-view | [attributes-panel.md](widgets/attributes-panel.md) |
| Colour legend | per-view | [color-legend.md](widgets/color-legend.md) |
| Time control | per-view | [time-control.md](widgets/time-control.md) |
| Analysis panels | per-property | [analysis-panels.md](widgets/analysis-panels.md) |

## 7. Licensed add-on widgets (V2 hosts them, doesn't own them)

These already have their own sibling repos and plug into V2's per-view host via
a **panel-kind registry + optional plugin loader** (the hooks discussed for the
OSDU connector):

- **WellLogCorrelation** — 2D multi-well correlation view. Repo
  `e:/Dev/fespp-on-trame-welllog`. A decoupled Trame/D3 widget.
- **WellMarkerLUT** — markers rendered via one proxy + a categorical LUT keyed
  on the marker name. Planning repo `e:/Dev/fespp-on-trame-Well-Marker-LUT`.
  An in-engine rendering *strategy* + a small colour-by-name management panel.

## 8. The maintainability win

Each widget becomes a self-contained component with an explicit contract. The UI
is then a **composition** of swappable widgets — you can redesign a panel, move
it, or replace it without touching `data_load` / `source_registry` / FESPP. The
per-session layer is tiny and stable; everything visual is local to a view.

## 9. Open design decisions (to lock before building)

1. **State storage for per-view slices** — keep the `*_by_view` dicts (each
   panel reads only its `view_id` key) **or** give each panel its own suffixed
   vars (`x_<view_id>`)? (Leaning: keep the dicts; drop only the *retargeting*.)
2. **Checkbox = load is shared** — confirm every view's tree mirrors the same
   checkboxes, and the eye is the per-view affordance (Section 3).
3. **Tree duplication cost** — N trees rendered. Acceptable since each is far
   simpler (one eye, no collapse). Virtualise if needed.
4. **Per-view attributes vs a shared "active rep" focus** — does each view edit
   *its* active rep, with the active rep chosen in *that* view's tree? (Yes.)
