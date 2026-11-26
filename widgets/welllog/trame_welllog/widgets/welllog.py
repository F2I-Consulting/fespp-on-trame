from trame_client.widgets.core import AbstractElement

from trame_welllog import module


class HtmlElement(AbstractElement):
    """Base element: enables the widget's web module on the server it joins."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = [
    "WellLogCorrelation",
    "WellLogZones",
]


class WellLogCorrelation(HtmlElement):
    """Well-log correlation panel: the tracks.

    Pass the JSON payload ({wells, markers, flattenOn, csv}) via the ``data``
    prop, typically bound to a shared state variable::

        WellLogCorrelation(data=("welllog_data", {}))

    ``depth_scale`` exaggerates the depth axis, a whole number as a 3D view's
    Z (1 = the whole depth span fits the panel) so the host can offer a
    visible slider; the wheel and a drag-to-zoom still work and report the
    new value through ``zoom_change``.

    ``align`` ("TVD", the default, or "MD") is the depth every well is laid
    out on; the tab row's TVD | MD choice comes back through ``align_change``.
    ``markers_off`` lists the markers drawn dimmed; a click on a marker's
    name sends the new list through ``markers_off_change``.

    ``show_synth`` adds the "from grid" editor: the requests in force
    (``synth``, ``[{well, prop, step}]``) and what it may offer
    (``synth_choices``, ``{wells, props}``); edits come back through
    ``synth_change``. Clicking a marker's line emits ``flatten_change`` with
    the marker name, or None when the panel is released.
    """

    def __init__(self, **kwargs):
        super().__init__(
            "well-log-correlation",
            **kwargs,
        )
        self._attr_names += [
            "data",
            ("depth_scale", "depthScale"),
            "align",
            ("markers_off", "markersOff"),
            "lit",
            ("focus_node", "focusNode"),
            ("pointed_at", "pointedAt"),
            ("show_synth", "showSynth"),
            "synth",
            ("synth_choices", "synthChoices"),
        ]
        self._event_names += [
            ("zoom_change", "zoom-change"),
            ("align_change", "align-change"),
            ("markers_off_change", "markers-off-change"),
            ("synth_change", "synth-change"),
            ("flatten_change", "flatten-change"),
            ("cursor_change", "cursor-change"),
            ("pick_change", "pick-change"),
        ]


class WellLogZones(HtmlElement):
    """The zone statistics of the same payload: one row per well, zone and
    curve, the cutoff editor and the CSV export.

    ``data`` is the payload WellLogCorrelation draws; ``csv`` = {name,
    header: [str]} names the zones-table export and carries its provenance
    header lines, the rows being written from the raw zone figures (n/a
    where one could not be evaluated). The cutoff rules (``cutoffs``,
    ``[{curve, op, value}]``) come back through ``cutoffs_change``.
    """

    def __init__(self, **kwargs):
        super().__init__(
            "well-log-zones",
            **kwargs,
        )
        self._attr_names += [
            "data",
            "cutoffs",
        ]
        self._event_names += [
            ("cutoffs_change", "cutoffs-change"),
        ]
