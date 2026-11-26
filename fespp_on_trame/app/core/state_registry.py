"""The declared state (overhaul slice 5, Q7).

The state variables of the session's panels used to be listed in several
places that had to agree: the seeding of a panel, its teardown on close,
the change handlers its options wire (`_CROSSPLOT_KEYS`, `_CROSSPLOT_WATCHED`,
`_CALC_KEYS`). Each family is declared once here, and those sites read it.

The per-view variables of the 3D views keep their inventory in
`app/views/per_view_state` (SUFFIXED_VARS, DICT_BUCKETS): seed and teardown
derive from it, and `test_per_view_cleanup` holds every key to it."""


class PanelFamily:
    """The state variables of one kind of panel: `pattern` names one of
    them for a key and a panel id. `keys` are all of them, in the order
    they are seeded; `settable` the ones the panel's widget may write (the
    others are the server's outputs)."""

    def __init__(self, kind, pattern, keys, settable=()):
        self.kind = kind
        self.pattern = pattern
        self.keys = tuple(keys)
        self.settable = tuple(settable)

    def var(self, key, panel_id):
        return self.pattern.format(key=key, pid=panel_id)

    def vars(self, panel_id, keys=None):
        return tuple(self.var(k, panel_id) for k in (self.keys if keys is None else keys))


# the cross-plot of the Statistics view; its axes are the view's to write
# (`CROSSPLOT_AXES`, app/features/compare)
CROSSPLOT = PanelFamily(
    "crossplot", "ui_crossplot_{key}_{pid}",
    keys=("x", "xreal", "xts", "ys", "color", "logx", "logy",
          "choices", "meta", "figures", "charts", "focus"),
    settable=("color", "logx", "logy", "focus"))
CROSSPLOT_AXES = ("x", "xreal", "xts", "ys")

# a calculator panel (its recipes live in the session's store, not here)
CALCULATOR = PanelFamily(
    "calculator", "ui_calc_{key}_{pid}",
    keys=("rep", "expr", "name", "uom", "kind", "status", "preview", "figure",
          "rep_choices", "prop_chips", "editing", "mr_props", "mr_pick"),
    settable=("rep", "expr"))

# the Statistics view's histogram options, and the shape a client write is
# coerced back to
COMPARE_DIST_OPTS = {"mode": "bars", "nbins": 50, "log_y": False,
                     "cumulative": False, "norm": "count"}
# what a closed Statistics view leaves behind: every server-computed payload at
# its empty default (the selection and the display settings survive: the
# view is a singleton)
COMPARE_PAYLOAD = {
    "chips": [], "blocks": [], "rows": {}, "annotations": {},
    "dist_figure": {"data": [], "layout": {}},
    "dist_meta": {}, "xplot_note": "", "tree_xml": "", "note": "",
    "note_severity": "warn",
    "csv": {"name": "", "header": []},
}

PANEL_FAMILIES = (CROSSPLOT, CALCULATOR)
