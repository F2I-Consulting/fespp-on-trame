# trame-fespp-crossplot

Control surface of the Statistics view's cross-plot, mounted bare under that
view's own bar: the colour-by picker and the log toggles, then the charts. X and
Y are the host's, picked over the chart among the rows of its matrix.

Each chart is a cell of its own — a plotly figure (`figures`, one per drawn
chart, keyed, filled in as they are read) under its caption line: what it
draws, the pairs it holds, the magnifier (that chart alone; again for all of
them) and the pin (a snapshot at the head of the rows, dashed; the pinned
chart's pin drops it). A chart still being read shows the busy bar under its
caption, the previous figure kept underneath (R9); one with nothing to draw
(no Y, another representation, the diagonal) keeps its cell and says why. A box
or lasso on a chart leaves as `select({chart, range, lasso})` — the geometry
with the chart's key, never the points —, a double-click as `select(null)`.

Pure display + the `set` and `select` events; every value is computed in
`engine/crossplot_dispatch`. Three components: `CrossplotStrip` (the shared
line, teleported into the bar of the host's chart), `CrossplotGrid` (the charts)
and `CrossplotControls` (the two together). The empty state says what would be
drawn and the gesture that draws it, with the server's note as its why — in the
first cell, or full width when there is no chart.

Every figure carries a `rev`: the host ships the growing list several
times during a run, and the grid hands plotly the same object for an
unchanged `rev`, so only the new charts are drawn.
