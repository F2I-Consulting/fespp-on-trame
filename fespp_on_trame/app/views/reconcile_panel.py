"""ReconcilePanel — the ``reconcile`` view kind: log channels set against the
grid properties of their KIND, sampled along each well, zone by zone —
where the model contradicts the logs.

Mount point: the table, the pairs editor and the controls are the decoupled
``trame_fespp_reconcile`` widget (``widgets/reconcile``); every value it
shows is computed by ``engine/reconcile_dispatch`` and pushed as
``ui_reconcile`` by the controllers ``boot`` wires (``reconcile_compute``,
``reconcile_auto_pairs``, ``reconcile_set_pairs``).

A view that chooses its own content, like Statistics and the well log: its
trees (``ReconcileTree``) tick log channels and grid properties into the
table, one card per family — Reservoir and Well — opened from the view's left
toolbar as a 3D view's family cards are, a family the data has nothing of
greyed (``ui_tree_families``). The table is the dock's fixed centre
(widgets/card_dock). ``reconcile_tree_open__<vid>`` lists the open cards,
``reconcile_card_layout__<vid>`` where they were left. The log view's wells
("Add to Well Log view") also feed the table; the two doors merge.

Singleton: one table for the session.
"""
from trame.widgets import html
from trame_fespp_reconcile.widgets import ReconcilePanel as _ReconcileWidget

from fespp_on_trame.app.ui.tree_icons import FAMILY_TREE_ICONS
from fespp_on_trame.app.views.tools_config import NEEDS_WHY
from fespp_on_trame.app.views.widgets import docked_tree
from fespp_on_trame.app.views.widgets.card_dock import (
    card_dock, card_slot, card_spec, center_slot,
)
from fespp_on_trame.app.views.widgets.reconcile_tree import ReconcileTree
from fespp_on_trame.engine import tree_families

# (family, icon, why its card is greyed): the 3D view's family cards
_ICONS = {"Reservoir": (FAMILY_TREE_ICONS["Reservoir"], NEEDS_WHY["tree"]),
          "Well": (FAMILY_TREE_ICONS["Well"], NEEDS_WHY["tree_well"])}


def _tools_js():
    """The toolbar's buttons: one per family, greyed when the data holds
    nothing of it."""
    held = "(ui_tree_families || [])"
    return "[" + ", ".join(
        f"{{key: '{name}', icon: '{_ICONS[name][0]}', disabled: !{held}.includes('{name}'),"
        f" title: '{name}' + ({held}.includes('{name}') ? '' : ' — {_ICONS[name][1]}')}}"
        for name in tree_families.LOG_GRID) + "]"


class ReconcilePanel:
    def __init__(self, server, view_id):
        from trame_fespp_dock.widgets import FpDockSlot
        from trame_fespp_view_card.widgets.card import FloatingCard
        from trame_fespp_view_tools.widgets.view_tools import ViewToolbar

        self.server = server
        self.view_id = vid = str(view_id)
        ctrl = server.controller
        state = server.state
        cards = f"reconcile_tree_open__{vid}"
        # closed, unless the table comes up with nothing in it: its trees are
        # then the first door in (widgets/docked_tree holds the one rule), the
        # first family the data holds
        docked_tree.seed_open(
            state, cards, vid,
            not ((getattr(state, "ui_welllog_wells", None) or [])
                 or (getattr(state, "ui_reconcile_logs", None) or [])))
        if not isinstance(state[cards], list):
            state[cards] = tree_families.open_cards(
                bool(state[cards]), tree_families.present_names(getattr(state, "assembly_xml", "") or ""),
                tree_families.LOG_GRID)
        layout = f"reconcile_card_layout__{vid}"
        if getattr(state, layout, None) is None:
            state[layout] = None
        open_list = f"({cards} || [])"

        with html.Div(style="display:flex; width:100%; height:100%;"
                            " min-height:0; background:#fff;"):
            ViewToolbar(
                tools=(_tools_js(),),
                open=(open_list,),
                toggle=f"{cards} = {open_list}.includes($event)"
                       f" ? {open_list}.filter((k) => k !== $event) : [...{open_list}, $event]")
            specs = {name: card_spec(vid, name, name, width=320) for name in tree_families.LOG_GRID}
            card_dock(vid, open_list, repr(specs),
                      f"{cards} = {open_list}.filter((k) => k !== $event)", layout)

            # the table and the trees, built once here: each moves into its
            # panel while that panel exists
            with html.Div(style="display:none;"):
                with FpDockSlot(slot_key=center_slot(vid)):
                    with html.Div(style="flex:1 1 auto; min-width:0; min-height:0;"
                                        " display:flex; flex-direction:column; height:100%;"):
                        _ReconcileWidget(
                            data=("ui_reconcile", {}),
                            compute=(ctrl.reconcile_compute, "[$event]"),
                            auto_pairs=(ctrl.reconcile_auto_pairs, "[]"),
                            set_pairs=(ctrl.reconcile_set_pairs, "[$event]"),
                        )
                for name in tree_families.LOG_GRID:
                    with FloatingCard(title=name, open=(f"{open_list}.includes('{name}')",),
                                      in_panel=True, panel_slot=card_slot(vid, name)):
                        ReconcileTree(server, vid, family=name)
        self.html_view = None  # non-render kind
