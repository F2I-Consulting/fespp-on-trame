# trame-fespp-attributes

A **decoupled** Trame widget: the fespp-on-trame **per-view attributes panel**
(custom Vue, no Vuetify). Read-only, scoped to a single view:

- the active node's title,
- the array currently colouring its rep — the **colorBy is owned by the
  tree's property eyes** (open a property's eye = colour by it, close it =
  back to solid), the panel only displays it,
- a paged **Values** table (collapsed by default, loaded on open) with a
  min/max filter on the value column and, when the view's selection tool
  holds cells of the node, their rows marked and a "Selected cells only"
  filter; clicking rows (multi) asks the host to **highlight** those cells /
  points in the view.

The node's XML is not here: it is the XML explorer's, a view of its own.

Colormap editing lives in the Colormap card; the Z scale is in each 3D view's
title bar.

## Contract

**Props (in)** — bind to THIS view's state:
- `active_node` — title of the active node (empty = nothing active).
- `active_array` — array currently colouring it (`""` = solid color).
- `values` — the page of values the host read for the Values table:
  `{count, total, offset, assoc, columns, rows, picked, picked_rows, only}`
  (`rows` = one array per row, the row's id first; `picked` = the node's
  cells the 3D selection holds, `picked_rows` = those on this page), or
  `{error}` when the read failed, `{}` before the first load.

The widget has no `view_id` prop: the view id travels in the event
bindings (`"[$event, 'view-1']"`), as in the example below.

**Events (out)**:
- `load_values({offset, min, max, only})` — the Values section was opened,
  paged or filtered: the host reads that page (the optional min/max filter
  on the value column, `only` = the cells selected in 3D) into `values`.
- `highlight([row ids])` — rows were clicked (multi): the host highlights
  those cells / points in the view; `[]` clears the highlight.
- `explore()` — the **Explore** button of the XML section: open the node
  the card shows in the XML explorer (the app resolves the node).

## Build

```bash
cd vue-components
npm install
npm run build   # -> trame_fespp_attributes/module/serve/{*.umd.js, style.css}
```

Then open `demo.html` to see the panel with mock data.

## Use (in a Trame app)

```python
from trame_fespp_attributes.widgets.attributes import AttributesPanel

AttributesPanel(
    active_node=("ui_active_node_by_view['view-1']",),
    active_array=("ui_active_array_by_view['view-1']",),
    values=("ui_node_values_by_view['view-1']",),
    load_values=(ctrl.node_values, "[$event, 'view-1']"),
    highlight=(ctrl.node_highlight, "[$event, 'view-1']"),
)
```
