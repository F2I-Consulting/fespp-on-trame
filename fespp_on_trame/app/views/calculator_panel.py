"""The ``calculator`` view kind — derived-property recipes over one grid.

Mount point only: the whole control surface is the decoupled
``trame_fespp_calculator`` widget (``widgets/calculator``), and every
formula is parsed / bound / evaluated server-side in
``engine.derived_props``, wired by ``app.boot`` (``_refresh_calculator``,
``calc_*`` controllers).

The preview histogram is a ``trame_plotly`` figure alongside the widget:
the plot is not part of the control surface, and the Statistics view's
charts use the same plotly integration.

SINGLETON: one panel manages every grid through its grid select.
"""
from trame.widgets import html, plotly
from trame_fespp_calculator.widgets import CalculatorPanel as CalculatorWidget


class CalculatorPanel:
    def __init__(self, server, view_id):
        self.server = server
        self.view_id = pid = str(view_id)
        ctrl = server.controller
        v = lambda name: f"ui_calc_{name}_{pid}"  # noqa: E731

        with html.Div(style="height:100%; width:100%; overflow:auto;"
                            " background:#fff; display:flex;"
                            " flex-direction:column;"):
            CalculatorWidget(
                rep=(v("rep"), ""),
                rep_choices=(v("rep_choices"), []),
                prop_chips=(v("prop_chips"), []),
                mr_props=(v("mr_props"), []),
                mr_pick=(v("mr_pick"), ""),
                expr=(v("expr"), ""),
                name=(v("name"), ""),
                uom=(v("uom"), ""),
                kind=(v("kind"), "ContinuousProperty"),
                editing=(v("editing"), ""),
                status=(v("status"), {}),
                preview=(v("preview"), {}),
                derived_props=("ui_derived_props", []),
                axes=(v("axes"), {}),
                diff=(ctrl.calc_diff, f"['{pid}', $event[0], $event[1], $event[2]]"),
                set_rep=f"{v('rep')} = $event",
                set_name=f"{v('name')} = $event",
                set_uom=f"{v('uom')} = $event",
                set_kind=f"{v('kind')} = $event",
                set_expr=f"{v('expr')} = $event",
                set_mr_pick=f"{v('mr_pick')} = $event",
                # append lands at the END of the formula: robust everywhere a
                # caret reference is not (the panel floats in dockview)
                append=(f"{v('expr')} = (({v('expr')} || '') "
                        f"&& ({v('expr')} || '') + ' ') + $event"),
                template=(f"{v('expr')} = $event[0];"
                          f" {v('uom')} = $event[1] || {v('uom')}"),
                create=(ctrl.calc_create, f"['{pid}']"),
                cancel_edit=(ctrl.calc_cancel_edit, f"['{pid}']"),
                make_percentiles=(ctrl.calc_make_percentiles,
                                  f"['{pid}', {v('mr_pick')}]"),
                act=(ctrl.calc_act, f"[$event[0], $event[1], '{pid}']"),
            )
            with html.Div(style="flex:0 0 220px; min-height:220px;"):
                widget = plotly.Figure(
                    state_variable_name=v("figure"),
                    display_mode_bar=("false",), responsive=("true",),
                    style="height:100%; width:100%;",
                )
                setattr(ctrl, f"update_calc_figure_{pid}", widget.update)
        self.html_view = None  # non-render kind
