"""The ``compare`` view kind, the Statistics view — ONE free selection of loaded
properties (any kind, any grid or well, a realization / time step per item),
one tab per PWLS kind, each with its own baseline, sort, metrics and histogram
options and showing at once its matrix, its overlaid distributions and the
cross-plot of two of its rows. Under an item, the rows that follow it: the
property on a part of its grid, or on what a 3D view draws of it
(``engine/compare_rows``).

Mount point only: the control surface is the decoupled
``trame_fespp_compare`` widget (``widgets/compare``); every value it shows
is computed by ``engine/compare_dispatch`` and pushed by ``app/features/compare``
(``compare_set`` / ``compare_tree_paths`` / ``_refresh_compare``).

The figures stay ``trame_plotly`` widgets in the widget's ``dist`` and ``xplot``
slots — the histogram, and the cross-plot toolbar + figure of the panel id
``<vid>x`` (a cross-plot panel of its own, registered by boot). The widget
mounts them once a kind tab is open: a plotly figure sizes itself on mount, and
a figure drawn while hidden keeps a zero size.

The selection is built in the view's own trees (kind -> representation ->
property, then the parts of the grids), one card per family — Reservoir,
Surface, Well, and Other while the file has a rep outside the three — opened
from the view's left toolbar as a 3D view's family cards are, a family the
file has no property of greyed. The panel's matrix is the dock's fixed centre
(widgets/card_dock). ``compare_tree_open__<vid>`` lists the open cards (the
first family the file holds when the view first opens),
``compare_card_layout__<vid>`` where they were left. SINGLETON.
"""
from trame.widgets import html, plotly
from trame_fespp_compare.widgets import ComparePanel

from fespp_on_trame.app.ui.tree_icons import FAMILY_TREE_ICONS
from fespp_on_trame.app.views.crossplot_panel import mount_crossplot
from fespp_on_trame.app.views.widgets.card_dock import (
    card_dock, card_slot, card_spec, center_slot,
)
from fespp_on_trame.app.views.widgets.compare_tree import CompareTree
from fespp_on_trame.engine import compare_tree, node_kinds, tree_families

# (family, icon, why its card is greyed): the 3D view's family icons
_FAMILIES = (
    ("Reservoir", FAMILY_TREE_ICONS["Reservoir"], "no grid property in the data"),
    ("Surface", FAMILY_TREE_ICONS["Surface"], "no surface property in the data"),
    ("Well", FAMILY_TREE_ICONS["Well"], "no wellbore property in the data"),
    ("Seismic", FAMILY_TREE_ICONS["Seismic"], "no lattice grid property in the data"),
)


def _tools_js():
    """The toolbar's buttons: one per family, greyed when the tree holds
    nothing of it; Other only while the file has a rep of none of
    them."""
    held = "(ui_compare_tree_families || [])"
    tools = [f"{{key: '{name}', icon: '{icon}', disabled: !{held}.includes('{name}'),"
             f" title: '{name}' + ({held}.includes('{name}') ? '' : ' — {why}')}}"
             for name, icon, why in _FAMILIES]
    other = node_kinds.OTHER_FAMILY
    return (f"[{', '.join(tools)}, ...((ui_compare_tree_tabs || []).some((t) => t.name === '{other}')"
            f" ? [{{key: '{other}', icon: '{FAMILY_TREE_ICONS[other]}', title: '{other}'}}] : [])]")


class CompareViewPanel:
    """The Statistics panel of one dockview view (see the module docstring)."""

    def __init__(self, server, view_id):
        from trame_fespp_dock.widgets import FpDockSlot
        from trame_fespp_view_card.widgets.card import FloatingCard
        from trame_fespp_view_tools.widgets.view_tools import ViewToolbar

        self.server = server
        self.view_id = vid = str(view_id)
        ctrl = server.controller
        st = server.state
        cards = f"compare_tree_open__{vid}"
        if not isinstance(getattr(st, cards, None), list):
            # the family tree last on screen in any view, when the data holds it here
            present = compare_tree.families_present(getattr(st, "ui_compare_tree_xml", "") or "")
            last = getattr(server.context, "last_tree_family", None)
            st[cards] = ([last] if last in present else
                         tree_families.open_cards(True, present, compare_tree.card_names()))
        layout = f"compare_card_layout__{vid}"
        if getattr(st, layout, None) is None:
            st[layout] = None
        names = [name for name, _icon, _why in _FAMILIES] + [node_kinds.OTHER_FAMILY]
        open_list = f"({cards} || [])"

        with html.Div(style="display:flex; width:100%; height:100%;"
                            " min-height:0; background:#fff;"):
            ViewToolbar(
                tools=(_tools_js(),),
                open=(open_list,),
                toggle=f"{cards} = {open_list}.includes($event)"
                       f" ? {open_list}.filter((k) => k !== $event) : [...{open_list}, $event]")
            specs = {name: card_spec(vid, name, name, width=320) for name in names}
            card_dock(vid, open_list, repr(specs),
                      f"{cards} = {open_list}.filter((k) => k !== $event)", layout)

            # the matrix and the trees, built once here: each moves into its
            # panel while that panel exists
            with html.Div(style="display:none;"):
                with FpDockSlot(slot_key=center_slot(vid)):
                    with html.Div(style="flex:1 1 auto; min-width:0; min-height:0;"
                                        " display:flex; flex-direction:column;"
                                        " overflow:auto; height:100%;"):
                        self._matrix(ctrl)
                for name in names:
                    with FloatingCard(title=name, open=(f"{open_list}.includes('{name}')",),
                                      in_panel=True, panel_slot=card_slot(vid, name)):
                        CompareTree(server, vid, family=name)
        self.html_view = None  # non-render kind

    def _matrix(self, ctrl):
        vid = self.view_id
        with ComparePanel(
            chips=("ui_compare_chips", []),
            # one tab per kind of the selection; what follows is the
            # current kind's own state
            kinds=("ui_compare_kinds", []),
            tab=("ui_compare_tab", ""),
            baseline=("ui_compare_baseline", ""),
            blocks=("ui_compare_blocks", []),
            rows=("ui_compare_rows", {}),
            annotations=("ui_compare_annotations", {}),
            deltas=("ui_compare_deltas", {}),
            visible_metrics=("ui_compare_visible_metrics", []),
            sort_key=("ui_compare_sort_key", ""),
            sort_asc=("ui_compare_sort_asc", True),
            dist_opts=("ui_compare_dist_opts", {}),
            dist_meta=("ui_compare_dist_meta", {}),
            xplot_note=("ui_compare_xplot_note", ""),
            xplot_axes=("ui_compare_xplot_axes", {}),
            note=("ui_compare_note", ""),
            note_severity=("ui_compare_note_severity", "warn"),
            note_next=("ui_compare_note_next", ""),
            csv=("ui_compare_csv", {}),
            # ONE channel for every control: the widget names the
            # key, the server owns the routing
            set=(ctrl.compare_set, "[$event[0], $event[1]]"),
        ):
            with html.Template(raw_attrs=["v-slot:dist"]):
                widget = plotly.Figure(
                    state_variable_name="ui_compare_dist_figure",
                    display_mode_bar=("true",),
                    display_logo=("false",),
                    responsive=("true",),
                    style="height:100%; width:100%; min-height:0;",
                )
                setattr(ctrl, "update_compare_dist_figure", widget.update)
            with html.Template(raw_attrs=["v-slot:xplot"]):
                mount_crossplot(self.server, f"{vid}x")
