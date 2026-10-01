# trame-fespp-view-tools

The **per-view toolbar** for fespp-on-trame V2: a vertical strip of **toggle
buttons** (one per tool) plus optional **action buttons**. Custom Vue, decoupled,
stateless. It's the per-view **picker** — the actual tool windows are the
**`FloatingCard`** widget, split into its own repo
[`trame-fespp-view-card`](../fespp-on-trame-view-card) so the container is
independent of the picker (toolbar OR radial menu OR …).

## `ViewToolbar`

- **Props**:
  - `tools` = `[{key, icon, title}]` — toggle buttons (open/close a card).
  - `open` = `[tool keys]` — which tools are currently open.
  - `actions` = `[{key, icon, title}]` — one-shot action buttons (e.g. reset camera).
- **Events**:
  - `toggle(tool_key)` — a tool button was clicked.
  - `action(action_key)` — an action button was clicked.
- Stateless; the host owns the open-set in **per-view** state.

## Composition (host app)

```python
from trame_fespp_view_tools.widgets.view_tools import ViewToolbar
from trame_fespp_view_card.widgets.card import FloatingCard

with html.Div(style="position:relative; overflow:hidden; height:100%;"):
    VtkRemoteView(pv_view)                       # full-bleed render
    ViewToolbar(tools=("ui_view_tools",), open=("ui_open_tools_view1",),
                toggle=(ctrl.v2_toggle_tool, "[$event, 'view-1']"))
    with FloatingCard(title="Data Explorer",
                      v_show="ui_open_tools_view1.includes('tree')",
                      close=(ctrl.v2_toggle_tool, "['tree', 'view-1']")):
        DataExplorerTree(...)                    # any decoupled tool widget
```

## Build

```bash
cd vue-components
npm install
npm run build   # -> trame_fespp_view_tools/module/serve/{*.umd.js, style.css}
```

Open `demo.html` — two views, each with a toolbar; toggling updates the open-set.
