# Widget: Data-explorer tree (per-view)

The per-view RESQML tree. Replaces the v1 **global** drawer tree (which showed
every view's eyes at once). Each view panel can **open/close** its tree.

## Scope
Per-view — one instance per dockview panel, scoped to a `view_id`.

## Input
- `view_id` — the owning panel.
- The **shared** loaded assembly, partitioned per tab: `ui_subtree_reservoir`,
  `ui_subtree_surface`, `ui_subtree_well`.
- The **shared** selection (checkboxes): `ui_select_node_*` / `fespp_data_selectors`.
- This view's visibility / colouring slice (per-view).

## Behaviour
- Three tabs (**Reservoir / Surface / Well**), each a `VTreeview` of the loaded
  assembly.
- **Checkbox per node = LOAD** (shared). Toggling loads/unloads the data
  globally (loaded once); every view's tree mirrors the same checkboxes.
- **"Select ▾" bulk dropdown** (All grids / surfaces / trajectories / markers) —
  the shipped `feature/tree-bulk-select`.
- **One eye per renderable node = show/hide in THIS view.** No `v-for` over
  panels, no collapse logic (the v1 complexity disappears).
- **One active-array eye per property = colour THIS view by that array.**
- **Stats** per property, in its right-click menu, before Info — adds it to the Statistics view.
- **Layouts**: Representation, Interpretation, Feature and Kind, one per view (`ui_tree_layout__<vid>`), drawn by the widget over the same paths (`byOwner`, `byKind`, rows `layout://`): nothing is unticked or read again. Interpretation and Feature come from the plugin's attributes on a representation's top node (`interpretation`, `interpretationTitle`, `feature`, `featureTitle`), from the objects or, for a stub on the store, from the discovery's edges. The Statistics tree has its own (`ui_compare_tree_layout`): by kind the server builds it (`kind_built`), else it sends the representations with those attributes and the widget groups them.
- **Label click = activate** the node → drives this view's attributes-panel focus.

## Reads
- `ui_subtree_*`, `ui_select_node_*` **[session]**.
- `ui_loaded_rep_paths` / `ui_loaded_array_paths` / `ui_loaded_marker_paths`
  **[session]** loaded sets.
- This view's `ui_hidden_rep_paths` / `ui_active_array_by_rep` /
  `ui_visible_marker_paths` (the `view_id` slice) **[per-view]**.
- `tree_chip_color_by_path` (chip colours).

## Writes (back-end / global)
- **[session]** `ui_select_node_*` → recomputes `fespp_data_selectors` →
  `data_load.run` (load/unload the data, once, for all views).
- **[session]** `ui_compare_items` (Stats, through `controller.add_to_stats`).
- **[per-view]** this view's hidden-rep set, active-array map, visible-marker
  set, and active-node — then a render of this view.

## Notes / open
- Only the **checkbox (load)** writes shared state; **everything else is
  per-view**. That is the whole simplification.
- The eye cell collapses from an N-panel `v-for` + collapse heuristics to a
  single icon → far less template logic.
- Decision: when a node is unloaded (checkbox off) it leaves the loaded set for
  **all** views (load is shared) — confirm this is the intended UX.

## A host's rows and folders
The same widget draws the panels' trees. A node of the assembly may say
`noCheck="1"` (no box, and a tri-state does not count it: a folder of the layout
that stands for nothing to read, or a leaf with its eye and its menu and nothing
to read, a formula in the Statistics tree) and `sortLast="1"` (drawn after its siblings:
the Statistics tree's `Parts of a grid`). A row of `session_rows` inherits the
`family` of its parent, so it stays in its tab on a tree whose tabs go by family.
