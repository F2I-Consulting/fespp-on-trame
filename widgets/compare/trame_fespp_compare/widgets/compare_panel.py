from trame_client.widgets.core import AbstractElement, Template

from trame_fespp_compare import module

# The widget's named slots have to be declared to trame's `Template` before a
# caller can write `v_slot_tools=True`: `Template.slot_names` is the registry
# it reads at construction (every widget library adds its own the same way),
# and an unregistered name is rendered as a plain `<template>` element into
# the DEFAULT slot — the button lands in the panel body, invisible.
Template.slot_names.add("tools")


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["ComparePanel"]


class ComparePanel(HtmlElement):
    """The Statistics view (`compare` is its internal name): one free selection
    of loaded properties, side by side.

    One tab per PWLS kind of the selection, each with its own baseline,
    sort, visible metrics and histogram options, and showing at once its
    matrix (items x metrics, with each row's difference to the kind's
    baseline), its overlaid distributions and the cross-plot of two of its
    rows.

    Pure display: every value is computed in `engine/compare_dispatch`.
    The Plotly figures (the histogram, the cross-plot toolbar and figure)
    are the host's, put in the `dist` and `xplot` slots, under the matrix.
    The `tools` slot is the END of the header bar, where the host puts the
    panel's tree button: the same Vuetify button every other panel of the
    application carries, not a lookalike of its own.
    The R numbers refer to the UI rules of
    doc/wiki/UI-Drawer-Toolbar-Shared.md.

    Props:
        chips            [{key, uid, path, title, rep, kind, uom, real, ts,
                          reals: [{title, value}], ts_opts: [{title, value}],
                          baseline, ...}] — the server's facts about
                          each item, in selection order. The widget reads
                          `kind` to keep the current tab's items and
                          `baseline` to find the item the server fell back
                          to when `baseline` below is "".
        kinds            [{kind, count}] — the kind tabs, in first-
                          appearance order
        tab              the current kind tab, a kind label
        baseline         the current kind's baseline item id, "" = its
                          first item. Every value below is the current
                          kind's own; the host keeps one set per kind.
        blocks           [{kind, keys, uom, uom_mixed, units, sum_meaningful,
                          has_length}] — the kind's block (a host feeding
                          several gets them titled). `uom` is in the metric
                          headers, `uom_mixed` draws a Unit column;
                          `sum_meaningful` False hides the Sum, `has_length`
                          draws the Mean (L)
        rows             {id: {label, title, rep, kind, uom, real, ts,
                          reals, ts_opts, pinned, metrics, profile, note,
                          value_type, real_read, ts_text, support, follows,
                          support_label, ts_label, sum_meaningful}} — one row
                          per id: an item, or a row following one (`support`:
                          the part it is read on, or "view:<vid>"). A
                          following row writes `support_label` in place of
                          `rep`, has no picker and no pin, and its menu
                          refuses what it cannot take. `real_read` and
                          `ts_text` are what a row reads, named or not;
                          `note` what it has to say, on its hover and in the
                          CSV; `sum_meaningful` False writes a dash in a
                          block that keeps its Sum
        annotations      {id: {metric: "pos"|"neg"|"eq"|"min"|"max"}}
        deltas           {id: {metric: {abs, rel}}} — each row's difference
                          to the kind's baseline, written under the cell:
                          absolute in the metric's unit, relative in percent
                          of the baseline (null when the baseline is 0)
        visible_metrics  metric keys shown, drawn in the canonical order
                         whatever the order received
        sort_key         the column the blocks are sorted by — a metric key,
                         "Total" or "Representation" — "" for selection
                         order
        sort_asc         sort direction
        dist_opts        {mode, nbins, log_y, cumulative, norm}
        dist_meta        {kept, total, note, traces} — `note` is why a row
                         could not be drawn, the one thing said over the
                         chart; the table above says the counts
        xplot_note       the items left out of the cross-plot and why
        xplot_axes       {x, y} — the rows on the cross-plot's axes, their ids
        note             what the panel did not do (a failed recompute, a
                         read that never landed) as a band under the bar
                         with a `×`; it stays until its cause goes or the reader closes it
        note_next        an error's next step, said apart in the band (R10)
        note_severity    "warn" (something was held back) or "error" (an
                         action failed)
        csv              {name, header: [str]} — the file name and the
                         provenance header lines of the Copy CSV export,
                         decided server-side; the widget writes the rows
                         from its raw metrics
    Event:
        set   [key, value]   one channel for every control:
                             tab (a kind label),
                             xplot_axis (["x" | "y", ref]),
                             baseline (ref), remove (ref),
                             pin (ref), unpin (ref),
                             pin_all ([ref, "ts" | "real"]),
                             unpin_all (ref),
                             real ([ref, int|null]), ts ([ref, int|null]),
                             visible_metrics (list),
                             sort ([column or "", asc]),
                             dist_opt ([name, value]),
                             note ("" — the reader closed the note band).
                             baseline, visible_metrics, sort,
                             xplot_axis and dist_opt act on the current kind.
                             `ref` names ONE row by its item id (its `uid`):
                             a pinned copy and its source share a property,
                             realization and time step, and stay two rows.
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("compare-panel", children, **kwargs)
        self._attr_names += [
            "chips", "kinds", "tab", "baseline", "blocks", "rows",
            "annotations", "deltas", "visible_metrics", "sort_key", "sort_asc",
            "dist_opts", "dist_meta",
            "xplot_note", "xplot_axes", "note", ("note_severity", "noteSeverity"),
            ("note_next", "noteNext"),
            "csv",
        ]
        self._event_names += ["set"]
