# trame-fespp-tree — backlog

Future work, captured as it comes up. Nothing here is built yet — these are
requirements from user feedback for a production-grade tree.

---

## 1. Tree filtering (HIGH — real datasets can reach ~1e9 objects)

Big petroleum software always offers tree filtering, because in practice an EPC
can hold **up to ~1 billion objects**. We must be able to narrow the tree:

- **Filter by name** — regexp, or at minimum a wildcard `*` (glob).
- **Filter by kind** — the node `type` (IjkGrid, TriangulatedSet, Wellbore, …).
- (later) combine filters (name AND kind).

UI: a search/filter box per tab (or one global), debounced; clears to full tree.

**Status: client-side filter shipped.** Per-tab toolbar in `DataExplorerTree.vue`:
a debounced **name** box (glob `* ?`, case-insensitive, substring) **AND** a
**kind** dropdown (present types incl. properties, with counts). Matches and
their ancestors are kept (a matching node keeps its full subtree; non-matching
branches are pruned) and auto-expanded via the new `TreeNode.forceOpen`; the
user's manual expand state is untouched. Empty → "No matches."; switching tab
resets the filter. Combine (name AND kind) is done. **Still client-side only** —
the host still passes the whole tab tree as props; see virtualization below.

Implications:
- Pairs with **virtualization** (windowed / lazy rendering). At 1e9 nodes you
  cannot render — or even hold — the full tree client-side. The engine must feed
  only the **visible / filtered slice** (server-side filter + paged subtree);
  the widget renders a window. This is the real architectural cost of the
  "1 billion objects" requirement, not the filter box itself.

---

## 2. Hierarchical bulk-select ("Select ▾" per tab, with nested submenus)

**Status: kind-level shipped.** A data-driven "Select ▾" menu now exists per tab
(`DataExplorerTree.vue`): "Select all" + per-family / per-kind entries built from
the `type`s actually present (with live counts). Families collapse to a single
entry when only one of their types is present; unknown types fall back to a flat
"All <type>s" entry. The widget emits the **intent** `bulk-select({tab, kinds,
mode})` and the host resolves which objects to load. Taxonomy is overridable via
the `select_groups` prop.

Deliberate scope decisions:
- **No "Deselect all".** With one source per (representation, view), a bulk
  unload can be very expensive — unloading stays a per-node action.
- **Properties (`*Property`) are excluded** from bulk-select (menu + "Select
  all" count): they load with their parent representation, not in bulk.
  Individual property checkboxes are unaffected.
- "Select all" emits the explicit list of present bulkable `kinds` (not a `null`
  catch-all), so it stays consistent with the property exclusion.

**Still TODO:** the nested `of horizons` / `of faults` / `on feature` sub-levels
below — they need the extra node metadata noted in the Prerequisites, which the
engine's `tree.set_tree` does not expose yet. Proposed full structure:

### Select Reservoir
- All Grids
  - All IJK Grids
  - All unstructured grids

### Select Surface
- All surfaces
  - All 2D grids                      ← no horizon/fault sub-level
  - All polyline sets
    - of horizons
    - of faults
  - All point sets
    - of horizons
    - of faults
  - All triangulations
    - of horizons
    - of faults

### Select Wellbore
- All markers
  - On feature → combobox to pick the geologic feature

### Prerequisites / notes
- `of horizons` / `of faults` and `on feature` need **extra metadata on nodes**
  beyond `type`: the **geologic role** (horizon vs fault, derived from the
  represented interpretation/feature) and the marker's **feature**. The engine's
  `tree.set_tree` must expose these (e.g. `role`, `feature`) so the widget can
  group/filter by them — without that metadata, only the kind-level entries
  (All 2D grids / All triangulations / …) are implementable.
- "All X" entries map to a bulk **load** (checkbox = session load), reusing the
  pre-expand-deps-then-load-once approach so `data_load` runs a single time.

---

## 3. Tree UX — pro-tool affordances (shipped)

Inspired by Petrel / GOCAD-SKUA / RMS / ResInsight object trees. All pure-widget
(prop in / event out), so the host wires them to the engine:

- **Per-type icons** (`TreeNode`) — monochrome glyph per `type`, overridable via
  the `kind_icons` prop; unknown types fall back to "•".
- **State glyphs** — optional node `state: 'loading' | 'error'` renders a trailing
  ⏳ / ⚠ (error tinted red, tooltip from `info`).
- **Active node** — `active` prop (the focused node id) → bold + highlight; the
  `activate` event already feeds it.
- **Right-click context menu** — items are **host-provided** via `context_actions`
  (`{key, label, types?, danger?, separatorBefore?}`); `types` restricts an
  action to those node types. Emits `context-action({action, id, tab, path})`.
- **Colour swatch** — optional node `color` renders a clickable chip; emits
  `color-request({id, tab, path})` (host opens its picker / colormap editor).
- **Roll-up badge** — a folder shows the count of loaded (selected) nodes below it.
- **Metadata tooltip** — hover shows `type`, `path`, and any of
  `crs/dims/count/units/info` the engine provides.
- **Keyboard nav** — roving focus: ↑/↓/Home/End move, →/← expand/collapse or
  jump to child/parent, Space toggles load, Enter activates.

**Deliberately deferred:**
- **Multi-select for batch context actions** — conflicts with the existing
  "checkbox = load" meaning; needs a separate *marking* model (anchor + shift
  range) distinct from the load set. Worth its own design pass.
- **Drag & drop** (object → 3D view, property → grid) — heavy under Trame.
- **True tri-state folder checkboxes** with subtree load/unload — held back given
  the "unload is expensive" constraint; the roll-up badge covers the read-only
  need for now.
- **Colormap legend / colour table editor**, **realizations/ensembles** — engine
  + viewer work beyond the tree.
