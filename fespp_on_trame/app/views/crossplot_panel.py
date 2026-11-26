"""The cross-plot of the Statistics view — one row of its matrix against
another, coloured by a third property: pinned snapshots, one focused chart.

Mount point only: the control surface is the decoupled
``trame_fespp_crossplot`` widget (``widgets/crossplot``); every value it
shows is computed by ``engine/crossplot_dispatch`` and pushed by the watcher
``app/features/crossplot_panel`` wires.

The scatters are the widget's own ``trame-plotly`` figures, one per chart;
the lasso / box selection round-trip (geometry out with the chart's key,
full-resolution cell ids back, 3D highlight) comes back through the widget's
``select`` event.
"""
from trame_fespp_crossplot.widgets import CrossplotControls


def mount_crossplot(server, pid):
    """Mount the toolbar and the charts of the cross-plot panel `pid`, inside
    whatever column the caller has opened. The figures
    (`ui_crossplot_figures_<pid>`, one per chart, filled as they are read)
    and the empty state are the widget's.
    """
    ctrl = server.controller
    v = lambda name: f"ui_crossplot_{name}_{pid}"  # noqa: E731

    CrossplotControls(
        color=(v("color"), ""),
        logx=(v("logx"), False), logy=(v("logy"), False),
        choices=(v("choices"), []), meta=(v("meta"), {}),
        charts=(v("charts"), []), focus_key=(v("focus"), None),
        figures=(v("figures"), []),
        # ONE channel for every control: the widget names the key,
        # the server owns the routing (no client-side state poking)
        set=(ctrl.crossplot_set,
             f"[$event[0], $event[1], '{pid}']"),
        # lasso / box selection -> the ORIGINAL cell ids ride in each
        # point's customdata -> the shared 3D highlight lights those
        # cells in every view. The widget sends the GEOMETRY only, with
        # the key of the chart it was drawn on — never the point list, which
        # weighs megabytes of plotly point objects for a large box and
        # covers only the subsampled cloud. The server recomputes the
        # region at full resolution from the geometry alone (about a
        # hundred bytes). null (double-click) clears.
        select=(ctrl.crossplot_select, f"[$event, '{pid}']"),
    )
