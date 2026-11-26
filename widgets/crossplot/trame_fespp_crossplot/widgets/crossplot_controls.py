from trame_client.widgets.core import AbstractElement

from trame_fespp_crossplot import module


class HtmlElement(AbstractElement):
    """Base element that enables this package's Vue module on its server."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["CrossplotControls"]


class CrossplotControls(HtmlElement):
    """Toolbar and charts of the Statistics view's cross-plot: what colours
    the points and the scales, then the charts, each under its caption line.
    X and Y are the host's, picked over the chart among the rows of its matrix.

    Pure display: the figures, the subsampling, the pinned snapshots and
    the selection round-trip are computed in `engine/crossplot_dispatch`.

    Props:
        color                the colour-by property path
        logx / logy          log scales
        choices              [{title, value}] the properties on the same
                             representation
        meta                 {kept, total, unit, nan, nan_y, nonpos,
                             nonpos_y, note, selected} — the honest point
                             count and what the drawing left out
        charts               [{key, title, pinned, kept, nan_y, nonpos_y,
                             note, loading}] — one cell each, pinned
                             snapshots first; a loading one shows its mark
                             in place of the figure, kept == 0 shows its
                             note there
        focus                the chart key drawn alone, null for all of them
                             (bound as `focus_key=` on the Python side:
                             `focus` is a DOM event name to trame, which
                             would serialise the whole element as an error)
        figures              [{key, rev, data, layout}] — one plotly figure
                             per drawn chart, filled in as they are read;
                             the widget redraws a figure only when its `rev`
                             changed
    Events:
        select  {chart, range, lasso} | null — a box / lasso drawn on the
                             chart `chart` (its geometry only), or a
                             double-click that clears it
        set   [key, value]   one channel for every control: color / logx /
                             logy, the actions pin (a chart key: live:i
                             snapshots it, pin:n drops it) and focus (a
                             chart key or null)
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("crossplot-controls", children, **kwargs)
        self._attr_names += [
            "color", "logx", "logy", "choices", "meta", "charts",
            ("focus_key", "focus"), "figures",
        ]
        self._event_names += ["set", "select"]
