# trame-fespp-view-card

A **decoupled** Trame widget: a **floating tool card** — draggable, resizable,
**clamped to its view**, with click-to-front z-order. Custom Vue, no Vuetify.

Split out of `trame-fespp-view-tools` so the tool **container** is independent of
the **picker**: open a card from a toolbar, a radial menu, anything. The host
just shows/hides it (`v_show`) and fills its default slot with the tool content
(Tree / COE / Transform / …).

## Contract

**Props (in)**:
- `title` — card header.
- `x0`, `y0` — initial position (px) inside the view container.
- `width`, `height` — initial size (`height` 0 = auto-fit). User can resize.
- `min_width`, `min_height` — resize floors.

**Event (out)**:
- `close`.

The parent element MUST be `position: relative; overflow: hidden` — the card is
absolutely positioned inside it and BOTH drag and resize are clamped to those
bounds (so a card in view 1 never drifts/grows over view 2).

## Use (host app)

```python
from trame_fespp_view_card.widgets.card import FloatingCard

with html.Div(style="position:relative; overflow:hidden; height:100%;"):
    VtkRemoteView(pv_view)                      # full-bleed render
    with FloatingCard(title="Data Explorer", width=340, height=520,
                      v_show="ui_open_tools_view1.includes('tree')",
                      close=(ctrl.v2_toggle_tool, "['tree', 'view-1']")):
        DataExplorerTree(...)                   # any decoupled tool widget
```

## Build

```bash
cd vue-components
npm install
npm run build   # -> trame_fespp_view_card/module/serve/{*.umd.js, style.css}
```

Open `demo.html` — drag / resize a card; it stays inside the view.
