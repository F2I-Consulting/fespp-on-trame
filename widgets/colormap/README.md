# trame-fespp-colormap

A **decoupled** Trame widget: the fespp-on-trame **per-view colormap
controls** (custom Vue, no Vuetify): preset, min/max (auto-apply
on Enter/blur), log scale, below/above-range colours, NaN colour + opacity,
colour-bar toggle — plus the rescales: **data range**, **all time steps**,
**all realizations** (a custom range is simply the Min/Max fields, applied on
Enter/blur).

The colour/opacity **node graph** is Kitware's `trame-color-opacity-editor`
(`ColorOpacityEditor`), which the host mounts above this panel and binds to
the same view's node lists.

The widget knows nothing about ParaView: the host projects the view-scoped LUT
into the `cmap` prop and applies the events on that LUT / PWF.

The same bundle ships a second component, **`LegendsPanel`**, the legend list
drawn ON a 3D view's render: a 3D view shows ONE colour bar, that of the table
the Colormap card edits, and this list shows every coloured table of the view
so the reader can pick the one whose bar is shown (see its contract below).

## Contract — `ColormapPanel`

**Props (in)**
- `cmap` — `{array, preset, min, max, data_min, data_max, scale, below_on,
  below, below_alpha, above_on, above, above_alpha, nan, nan_opacity,
  hide_nan, hide_nan_auto, hide_nan_ok, hide_nan_why, bar,
  is_ts, is_mr}`. Empty `array` = nothing to edit.
- `presets` — available preset names.
- `view_id` — the owning view id.
- default **slot** — the node graph, rendered between the header and the
  controls.

**Events (out)**
- `set_preset(name)`, `set_range([lo, hi])`, `set_scale(linear|log|exp)`,
  `set_below([hex, alpha])`, `set_above([hex, alpha])`, `set_nan([hex, alpha])`,
  `set_hide_nan(bool)` (remove the NaN cells so the faces of their neighbours
  show; the host checks it itself at NaN opacity 0 and sets `hide_nan_auto`,
  and disables it with `hide_nan_ok: false` + `hide_nan_why` where it cannot
  apply), `set_bar(bool)`, `rescale(mode)` with mode in `data | time | mr | all`
  (`all` = every time step × every realization).

`mr` / `all` are FESPP notions, not ParaView's: the realizations of a
multi-realization property are loaded as sibling arrays named
`<name>_real_<n>`, so the host unions the ranges of every such array present
on the source; `time` / `all` step the source through the time keeper's
values (one pipeline update per step) and union the ranges.

The below / above swatches always show the EFFECTIVE out-of-range colour
(the colormap's first / last stop until the user picks one) with its opacity.
The host's node graph keeps the DATA range as its axis: the colormap
occupies `[min, max]` and flat below / above bands fill the rest.

`exp` is not a ParaView mode: the host re-spaces the colour nodes
exponentially (colour variation crowded toward the max, the mirror of the
native log scale) and restores the original positions when leaving it.

## Contract — `LegendsPanel`

An OVERLAY on the render, not a card (PO decision, 2026-09-25): a legend is
read with the picture, so it sits on it. The host mounts it directly in the
view's render container (the `position:relative; overflow:hidden` row that
holds the `VtkRemoteView`), and the component's root places itself:

- absolute, **top right** (6 px / 8 px inset), **no ground**;
- at most **half the view's height** (`calc(50% - 6px)`), so it never reaches
  the one colour bar ParaView draws at the bottom right; at most
  `min(360px, 45%)` wide;
- `z-index: 3` — above the render image (which has none), below the
  bottom-right pick / cursor overlay (4) and every floating card (5, raised
  on focus): a card dragged over the list covers it;
- `pointer-events: none` on the root, `auto` on the header and the list
  only, so the view stays draggable around it;
- white ink with a dark halo: `tokens.css` has no ink for text over the
  render (every token is written for a white panel, and the render's ground
  is whatever the scene is), and ParaView writes its own bar labels white.
  The component declares that ink once (`--flg-ink`, `--flg-ink-mute`,
  `--flg-halo`), as the title bar strip does for its own white ink.

It renders NOTHING with fewer than two tables — one table is already
legended by its own bar — except when the single table has `bar_off`: its
bar is switched off, so the list is the only legend left. There is no empty
state on the render.

**Props (in)**
- `legends` — `{}` or `{tables: [{key, title, lo, hi, stops, codes, log, bar,
  bar_off, family, owners}, ...]}`, rendered in the given order (the host
  sorts by family, then title). `key` = the table's stable id; `title` = the
  text its colour bar shows as title (may end with ` — constant <v>`);
  `lo` / `hi` = the range ends, already formatted, shown as they come;
  `stops` = 16 `#rrggbb` sampled left to right for a continuous table, `[]`
  for a coded one; `codes` = `[{code, label, color}]` for a table painted by
  code, `[]` otherwise; `log` = values mapped on a log scale (the stops are
  already sampled in log space); `bar` = this table holds the view's one
  colour bar; `bar_off` = it would, but the reader switched the bar off in
  the Colormap card; `family` = `grid | well | surface | other` (anything
  else is shown under Other); `owners` = the names of the objects the table
  paints (two wells sharing one GR scale: `["15/9-19 A", "15/9-F-1 A"]`).
- `view_id` — the owning view id (pass-through).

**Events (out)**
- `pick(key)` — the reader picked a row: make that table the one the
  Colormap card edits, hence the one whose bar is shown in 3D. Also emitted
  for the row already holding the bar (the host ignores it).

A header button, **"Legends (N)"** (class `flg-fold`, `aria-expanded`), folds
and unfolds the list; the fold is the component's own state, and folded
shows the header alone. Under it the rows, in sections **Grids**, **Wells**,
**Surfaces**, **Other** (a section's label only when it has rows; the host's
order kept inside a section). The list scrolls inside the half-height; the
header stays.

Each row: a swatch (a gradient of `stops`, or equal stripes of the code
colours), the title, the owners muted after it on the same line (they
ellipse first, then the title), `lo – hi` or "N codes", a `log` chip, a
`bar` chip (accent) or a `bar off` chip (muted). The row holding the bar is
marked by a white rule on its left and a heavier title.

The row is ONE `<fp-btn variant="bare">` (class `flg-pick`) stretched over
it, and the words sit beside the button, not inside it: they are data names,
not a label, and the charter sweep holds a button's text to Title case (the
smoke dataset's properties are `poro` and `velocity`). The button carries the
tooltip — the title, what the table paints, the range, and what a press does
— which is also its accessible name, and it starts with the title. A test
presses a row through that button (`.flg-row .flg-pick`, or
`getByRole('button', {name: /GR \(gAPI\)/})`): a click aimed at the name's
text is intercepted by the button laid over it. Tab reaches the header and
every row; Enter or Space presses them.

## Build

```bash
cd vue-components
npm install
npm run build   # -> trame_fespp_colormap/module/serve/{*.umd.js, style.css}
```

## Use (in a Trame app)

```python
from trame_fespp_colormap.widgets import ColormapPanel

ColormapPanel(
    view_id="view-1",
    cmap=("ui_colormap__view-1",),
    presets=("ui_colormap_presets", []),
    set_preset=(ctrl.v2_cmap_preset, "[$event, 'view-1']"),
    set_range=(ctrl.v2_cmap_range, "[$event, 'view-1']"),
    rescale=(ctrl.v2_cmap_rescale, "[$event, 'view-1']"),
    ...
)

from trame_fespp_colormap.widgets import LegendsPanel

# inside the view's render container (position:relative), beside the
# VtkRemoteView: the component places itself top right
LegendsPanel(
    view_id="view_1",
    legends=("ui_legends__view_1 || {}",),
    pick=(ctrl.legend_pick, "[$event, 'view_1']"),
)
```
