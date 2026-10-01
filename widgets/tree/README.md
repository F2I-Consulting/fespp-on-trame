# trame-fespp-tree

A **decoupled** Trame widget: the fespp-on-trame **data-explorer tree** (Reservoir
/ Surface / Well tabs), as a **custom Vue component** (no Vuetify — full UI
control, no `VTreeview` quirks). Part of the widget-first architecture: the
app composes widgets and binds their props/events; the widget knows nothing about
the engine.

## Contract

**Props (in)** — bind to your session / per-view state:
- `reservoir` / `surface` / `well` — the three tabs' node trees (nested dicts:
  `id`, `title`, `type`, `path`, `eye`, `children`).
- `selected` — list of selected node ids (session **load**).
- `loaded_reps` — list of loaded rep paths.
- `hidden_reps` — rep paths hidden in **this** view.
- `view_id` — the owning view id.

**Events (out)** — wire to your controllers:
- `toggle_select(node_id, tab)` — checkbox = load; ticking a leaf also makes it the active node.
- `toggle_eye(rep_path)` — eye = show/hide in this view.
- `activate(node_id, tab)` — label click (or a leaf tick) = active node.

The **checkbox = LOAD (session)**, the **eye = SHOW in this view (per-view)**.

## The layout strip

With a `layout` prop the toolbar carries a segmented control — **Objects** /
**Interpretation** / **Feature** — and emits `layout-change(value)` (`flat`,
`by_interpretation`, `by_feature_and_interpretation`: the plugin's
TreeHierarchyMode). The grouping rows the plugin inserts sit ABOVE a grid's
container: the block (geometry, properties, SubRep, blocked wellbores) stays
whole, so the hoist below applies under a Feature row as at the top. No
`layout` prop, no strip (the Compare tree).

## A well in the tree

The FESPP assembly lays a wellbore out like a grid (2026-09-18): the
trajectory a direct child, the log frames in a `logs` folder
(`WellboreLogsFolder`), the marker frames in `markers`, the completions in
`completions`. The component orders those children logs / markers /
completions / trajectory whatever their titles sort like.

## A grid in the tree

The FESPP assembly wraps a grid in a `GridContainer` whose `properties`
folder holds the geometry leaf (title `SolidColor`) beside the real
properties. The component hoists that leaf out as the container's first
child, titled **geometry**, then orders geometry / properties / blocked
wellbore. A grid known by reference only (the file read names it but does not
carry it: the leaf is typed `Partial` with the grid's type in `supporttype`)
is hoisted the same way, and every row of the container is greyed with the
same reason (**PARTIAL** on the geometry, **NOT IN 3D** on the rest): nothing
of it can reach the 3D view until the grid's own EPC is imported.

## Layout

| Path | Role |
|------|------|
| `vue-components/src/DataExplorerTree.vue` | tabs + roots, emits events |
| `vue-components/src/TreeNode.vue` | recursive node row (expand / checkbox / eye) |
| `trame_fespp_tree/` | python package: module + `DataExplorerTree` widget |
| `demo.html` | standalone visual (Vue CDN + built bundle + mock data) |

## Build

```bash
cd vue-components
npm install
npm run build      # -> trame_fespp_tree/module/serve/{trame_fespp_tree.umd.js, style.css}
cd ..
pip install -e .
```

Then open `demo.html` in a browser to see the tree with mock data.

## Use (in a Trame app)

```python
from trame_fespp_tree.widgets.tree import DataExplorerTree

DataExplorerTree(
    reservoir=("ui_subtree_reservoir",),
    surface=("ui_subtree_surface",),
    well=("ui_subtree_well",),
    selected=("ui_select_node_reservoir",),
    loaded_reps=("ui_loaded_rep_paths",),
    hidden_reps=("hidden_in_view",),
    view_id="view-1",
    toggle_select=(ctrl.v2_toggle_select, "[$event[0], $event[1]]"),
    toggle_eye=(ctrl.v2_toggle_eye, "[$event, 'view-1']"),
)
```
