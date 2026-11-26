# trame-welllog

A [Trame](https://kitware.github.io/trame/) widget that renders a **well-log
correlation panel** — multi-well tracks with depth axes, log curves, correlated
markers/tops and click-to-flatten — entirely client-side with D3/SVG.

## Layout

| Path | Role |
|------|------|
| `src/correlation.js` | Framework-agnostic D3 renderer (shared by the demo and the widget). |
| `demo.html` | Standalone visual — serve the `widgets` folder over http (e.g. `npx serve widgets`) and open `/welllog/demo.html`; d3 from CDN, no build, but the renderer is an ES module a browser will not load from `file://`. |
| `vue-components/` | The Vue 3 component, built with vite into the python serve dir. |
| `trame_welllog/` | The python package: the trame module + the `WellLogCorrelation` widget. |

## Build

```bash
cd vue-components
npm install
npm run build          # writes trame_welllog/module/serve/trame_welllog.umd.js
cd ..
pip install -e .
```

## Use

```python
from trame.app import get_server
from trame_welllog.widgets.welllog import WellLogCorrelation

server = get_server(client_type="vue3")
server.state.welllog_data = {"wells": [], "markers": [], "flattenOn": None}

# inside a layout's content:
WellLogCorrelation(data=("welllog_data",), style="width:100%;height:100%;")
```

Reassign `state.welllog_data` to a **new dict** to trigger a re-render.

## Data shape

```js
{
  wells: [
    { name, color, depthRef,
      depthUnit, tvdUnit,                               // "" when no CRS states one
      mdTvd:  [ [md, tvd], ... ],                       // drawn in MD: its TVD column
      depth: { min, max },
      tracks: [ { kind, unit, logScale,
                  curves: [ { name, color, unit, range: [min, max], missing,
                              synthetic,            // from a grid: drawn dashed
                              samples: [[value | null, depth, tvd?], ...] } ] } ],
      tops:   [ { name, depth, tvd } ],
      strati: { time: [...], group: [...], rock: [...] },   // optional
      absent: { channel title: { kind, why } },         // logged, not in the panel
      pay:    [ [top, bottom], ... ],                      // under the cutoffs
      pay_na: [ curve name, ... ],                         // rule logs this well lacks
      pay_na_why: { curve name: why },                     // unticked / unreadable / unlogged
      summation: { phi, phi_candidates, phi_absent,        // logs behind Φ·h
                   sw, sw_candidates, sw_absent },
      zones:  [ { name, color, top, bottom, thickness, source,
                  net, ntg, phih, hcph, pay_na,            // only with cutoffs
                  curves: [ { name, unit, n, mean, min, max,
                              p10, p50, p90, n_pay, mean_pay } ] } ] },
    ...
  ],
  markers: [ { name, color } ],   // correlation tops, by name
  flattenOn: <marker name> | null
}
```

`zones` feeds the statistics table, a component of its own (`<well-log-zones
:data :cutoffs>`, `WellLogZones` in Python: the host places it, e.g. in a card
beside the tracks); `pay` is drawn as a band behind the curves (`pay_tvd`
when the well is laid out on TVD). Both are computed by the host from the
`cutoffs` the zones table emits (`cutoffs-change`, `[{curve, op, value}]`,
`op` one of `>=`, `<=`, `>`, `<`) — the widget only edits the rules. A well
that lacks a rule's log has
`pay_na` naming it and every pay figure (`net`, `ntg`, `phih`, `hcph`, `n_pay`,
`mean_pay`) `null`: the table shows a dash with the reason, never a zero. The
reason is the true one, from `pay_na_why`: `unticked` (the well logs it — the
channels are ticked per wellbore — and the note says to tick it in the well
tree), `unreadable` (ticked, no sample could be read) or `unlogged`. `absent`
is the host's record behind it: every channel of the well the panel does not
carry, with its property kind. The `summation` of each well names the porosity
and water-saturation logs Φ·h and Φ(1−Sw)·h were read from (`null` when no
property kind names one), the other logs that matched, and in `phi_absent` /
`sw_absent` the absent logs of the kind with why — so the report names the
porosity it would have read rather than saying there is none; the table's
header and the note under it repeat it. The notes under the table name the
columns it actually has (Φ·h only when a porosity was read somewhere), and the
summation line is shown only under a table.

The `showSynth` prop opens the "from grid" editor: the host passes
`synthChoices` (`{wells: [{title, value}], props: [{title, value, unit,
kind}]}`) and `synth` (the requests in force), the widget emits
`synth-change` with `[{well, prop, step}]`; sampling happens host-side and
comes back as dashed curves.

`align` (`"TVD"`, the default, or `"MD"`, back through `align-change`) is the
depth every well is laid out on, all wells on one depth scale: on TVD a well
drawn in MD is drawn against the TVD of its samples (`[value, md, tvd]`), tops,
pay and bands, its MD in the column beside; a well with no TVD (`mdTvd`) stays
on its MD and its header says "no TVD". `markersOff` lists the markers drawn
dimmed (back through `markers-off-change`).

## Interaction

- **Click a marker** (its correlation line or in-track tick) to flatten on it; click again to release.
- **Click a marker name** to dim that marker; click again to show it.
- **The wheel** zooms depth; with Shift it scrolls sideways.
- **Hover a track**: the pointer's depth (MD, and TVD when the well has it) and
  each curve's value there, in a box beside the pointer; a mark on the depth
  columns. Nothing while a button is down or a menu is open.

## Demo data

`WellLogCorrelation.mockData()` returns a synthetic 3-well dataset — used by `demo.html`.
