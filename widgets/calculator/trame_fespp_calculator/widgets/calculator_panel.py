from trame_client.widgets.core import AbstractElement

from trame_fespp_calculator import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["CalculatorPanel"]


class CalculatorPanel(HtmlElement):
    """Derived-property calculator of one grid.

    Pure display: every formula is parsed, bound and evaluated server-side
    (`engine/derived_props`); the widget only reports what was asked.

    Props:
        rep            str    selected grid (rep path)
        rep_choices    list   [{title, value}] grids carrying >= 1 property
        prop_chips     list   [{label, ident, uom, derived}] clickable inputs
        mr_props       list   [{title, value}] multi-realization properties
        mr_pick        str    the MR property the percentile row acts on
        expr/name/uom/kind    the form
        editing        str    name being edited ("" = creating)
        status         dict   {ok, error, summary}
        preview        dict   {n, nan, nan_pct, min, mean, max, p10, p90}
        derived_props  list   every recipe of the session (filtered by rep)
        axes           dict   {ident: {reals: [{title, value}],
                              ts: [{title, value}]}} the realizations and
                              time steps an A − B side can pin
    Events:
        set-rep / set-name / set-uom / set-kind / set-expr / set-mr-pick
        append            str        append this token to the formula
        template          [expr, uom] fill the form from a template
        create / cancel-edit / make-percentiles
        act               [what, path]  stats|edit|delete
        diff              [expr, name, uom]  set the form to A − B and
                                             create it
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("calculator-panel", children, **kwargs)
        self._attr_names += [
            "rep", ("rep_choices", "repChoices"), ("prop_chips", "propChips"),
            ("mr_props", "mrProps"), ("mr_pick", "mrPick"),
            "expr", "name", "uom", "kind", "editing", "status", "preview",
            ("derived_props", "derivedProps"), "axes",
        ]
        self._event_names += [
            ("set_rep", "set-rep"), ("set_name", "set-name"),
            ("set_uom", "set-uom"), ("set_kind", "set-kind"),
            ("set_expr", "set-expr"), ("set_mr_pick", "set-mr-pick"),
            "append", "template", "create",
            ("cancel_edit", "cancel-edit"),
            ("make_percentiles", "make-percentiles"), "act", "diff",
        ]
