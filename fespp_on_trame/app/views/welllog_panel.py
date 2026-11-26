"""WellLogPanel — the well-log correlation view (trame-welllog).

Contract
--------
Input:     ``server`` and ``view_id``.
Behaviour: renders ``WellLogCorrelation`` bound to this view's own payload
           ``welllog_data__<vid>`` — ``{wells, markers, flattenOn, csv}``, the shape
           the widget draws (see the trame-welllog README) — as the fixed
           centre of the view's own dock of cards (widgets/card_dock, the 3D
           view's), its well tree and the zone statistics (``WellLogZones``)
           cards of it, opened by the view's toolbar at the left (the 3D
           view's, widgets/view-tools). The
           panel only draws; the payload is built by ``engine/welllog_dispatch``
           from the channels and markers the reader has CHECKED.
Reads:     ``welllog_data__<vid>``, ``welllog_zoom__<vid>``,
           ``welllog_align__<vid>`` ("TVD" or "MD": the depth the wells are
           laid out on), ``welllog_markers_off__<vid>`` (the markers dimmed),
           ``welllog_dropped__<vid>`` (the read curves this log was told to
           leave out — unticking one in the panel's tree takes it out of the
           log and unloads nothing), ``welllog_zones_open__<vid>`` (the zone
           statistics card), ``welllog_cutoffs__<vid>``, ``ui_welllog_synth``
           and ``welllog_synth_choices`` (session-wide, like the wells: a
           synthetic log is an analysis product, not a view toggle; its
           editor is a preview, `previews` "log_sample").
Writes:    ``welllog_zoom__<vid>`` (the depth-scale slider, and the widget's
           own wheel echoed back so the two stay in sync),
           ``welllog_align__<vid>``, ``welllog_markers_off__<vid>``,
           ``welllog_flatten__<vid>`` (the marker the panel is flattened on —
           the widget's click, kept here so a rebuilt payload keeps it),
           ``welllog_card_layout__<vid>`` (where the cards were left in the
           view's dock), ``welllog_cutoffs__<vid>`` (the card's cutoff editor;
           the rules are evaluated server-side, so the panel reacts to them
           here — their name is per view, which a decorator in boot cannot
           spell).

The widget is vendored under ``widgets/welllog`` like every other one. Reassign
the payload to a NEW dict to redraw: the widget watches the reference.
"""
from trame.widgets import html
from trame.widgets import vuetify3 as v3

from fespp_on_trame.app.core import previews
from fespp_on_trame.app.ui.tree_icons import FAMILY_TREE_ICONS
from fespp_on_trame.app.views.widgets.card_dock import (
    card_dock, card_slot, card_spec, center_slot,
)
from fespp_on_trame.app.views.widgets.view_chrome import chrome_tools

EMPTY = {"wells": [], "markers": [], "flattenOn": None,
         "csv": {"name": "", "header": []}}

_REACTING = set()   # cutoff vars with a change handler — once per view
_CHROME = chrome_tools(140)


class WellLogPanel:
    """The well-log panel of one dockview view (contract in the module
    docstring)."""

    def __init__(self, server, view_id):
        from trame_fespp_dock.widgets import FpDockSlot
        from trame_fespp_view_tools.widgets.view_tools import ViewToolbar
        from trame_fespp_view_card.widgets.card import FloatingCard
        from trame_welllog.widgets.welllog import WellLogCorrelation, WellLogZones

        from fespp_on_trame.app.views.widgets import docked_tree
        from fespp_on_trame.app.views.widgets.welllog_tree import WellLogTree

        self.server = server
        self.view_id = vid = str(view_id)
        st = server.state
        var = f"welllog_data__{vid}"
        zoom = f"welllog_zoom__{vid}"
        align = f"welllog_align__{vid}"
        markers_off = f"welllog_markers_off__{vid}"
        tree_open = f"welllog_tree_open__{vid}"
        zones_open = f"welllog_zones_open__{vid}"
        cutoffs = f"welllog_cutoffs__{vid}"
        synth_open = f"welllog_synth_open__{vid}"
        layout = f"welllog_card_layout__{vid}"
        # declared here even when None: per_view_state.seed only runs for
        # render views, and a client can only write a key the server has
        # declared - undeclared, the widget's flatten click would stay
        # client-side and every payload rebuild would un-flatten the panel
        flatten = f"welllog_flatten__{vid}"
        st[flatten] = getattr(st, flatten, None)
        st[layout] = getattr(st, layout, None)
        # None-safe re-seeds, NOT setdefault: per_view_state.teardown sets the
        # keys back to None when the panel closes, and setdefault would keep
        # that None — the slider would come back broken on the second open.
        for key, default in ((var, dict(EMPTY)), (zoom, 1.0), (align, "TVD"),
                             (markers_off, []), (zones_open, False), (cutoffs, []),
                             (synth_open, False),
                             # the read curves this log has been told to leave
                             # out: unticking one in the panel's tree takes it
                             # out of THIS log and unloads nothing
                             (f"welllog_dropped__{vid}", [])):
            if getattr(st, key, None) is None:
                st[key] = default
        # open on the view's first open, whatever it holds: its tree is how
        # wells come in and how a log is found (widgets/docked_tree holds the rule)
        docked_tree.seed_open(st, tree_open, vid, True)
        if cutoffs not in _REACTING:
            _REACTING.add(cutoffs)

            @server.state.change(cutoffs)
            def _on_cutoffs(**_):
                server.controller.refresh_welllog()
        has_data = f"{var} && {var}.wells && {var}.wells.length"
        open_cards = (f"[...({tree_open} ? ['tree'] : []), ...({zones_open} ? ['zones'] : []),"
                      f" ...({synth_open} ? ['synth'] : [])]")
        dropped = f"welllog_dropped__{vid}"
        # the "from grid" sampling is a preview: its row and its button only
        # on a server started with its switch (a grid property sampled along
        # the trajectory, the model's log next to the measured one, dashed)
        sample = previews.offered("log_sample")

        with html.Div(classes="wlp",
                      style="position:relative; display:flex; flex-direction:column;"
                            " width:100%; height:100%;"):
            # the depth zoom and the TVD | MD choice in the tab row, as a 3D
            # view's strip (the widget teleports them there)
            html.Div(classes="wlp-chrome", style=_CHROME,
                     mousedown="$event.stopPropagation()", click="$event.stopPropagation()")
            with html.Div(style="flex:1 1 auto; display:flex;"
                                " min-height:0;"):
                # the view's toolbar, the 3D view's: one button per card, the
                # zone statistics greyed until a wellbore is in the log
                synth_tool = (", {key: 'synth', icon: 'mdi-vector-polyline', disabled: !(" + has_data + "),"
                              " title: 'Sample a loaded grid property along the trajectory'}"
                              if sample else "")
                ViewToolbar(
                    tools=(f"[{{key: 'tree', icon: '{FAMILY_TREE_ICONS['Well']}', title: 'Well'}},"
                           " {key: 'zones', icon: 'fespp-statistics', disabled: !(" + has_data + "),"
                           " title: 'Zone statistics' + ((" + has_data + ") ? ''"
                           " : ' — add a wellbore to the log first')}" + synth_tool + "]",),
                    open=(open_cards,),
                    toggle=f"$event === 'tree' ? ({tree_open} = !{tree_open})"
                           f" : $event === 'zones' ? ({zones_open} = !{zones_open})"
                           f" : ({synth_open} = !{synth_open})")
                # the tracks, the dock's fixed centre; the well tree a card at
                # the left, the zone statistics one at the bottom the first time
                specs = {"tree": card_spec(vid, "tree", "Well", width=320),
                         "zones": card_spec(vid, "zones", "Zone statistics",
                                            height=240, side="below")}
                card_dock(vid, open_cards, repr(specs),
                          f"$event === 'tree' ? ({tree_open} = false) : ({zones_open} = false)",
                          layout)

            # the tracks and the card, built once here: each moves into its
            # panel while that panel exists
            with html.Div(style="display:none;"):
                with FpDockSlot(slot_key=center_slot(vid)):
                    with html.Div(style="flex:1 1 auto; position:relative;"
                                        " overflow:hidden;"):
                        self._empty(has_data, dropped)
                        # v_if, NOT v_show: the D3 renderer is written for a
                        # non-empty dataset (hence its mockData()), and a
                        # throw in its mounted hook blanks the WHOLE subtree
                        # — placeholder included. Mount it only once there is
                        # something to draw.
                        WellLogCorrelation(
                            v_if=(has_data,),
                            data=(var, dict(EMPTY)),
                            depth_scale=(zoom, 1.0),
                            align=(align, "TVD"),
                            markers_off=(markers_off, []),
                            # the samples highlighted in the Values view, dots on their curves
                            lit=("ui_log_lit", {}),
                            # the active node of the view's tree, its graph brought to the middle
                            focus_node=(f"welllog_focus__{vid}", None),
                            # the sample under the pointer in the Values view, crossed in blue
                            pointed_at=("ui_log_pointer", None),
                            **({"show_synth": (synth_open, False)} if sample else {}),
                            synth=("ui_welllog_synth", []),
                            synth_choices=("welllog_synth_choices", {}),
                            zoom_change=f"{zoom} = $event",
                            align_change=f"{align} = $event",
                            markers_off_change=f"{markers_off} = $event",
                            synth_change="ui_welllog_synth = $event",
                            flatten_change=f"{flatten} = $event",
                            # the sample under the cursor: its row marked in the Values view
                            cursor_change=(server.controller.welllog_cursor, "[$event]"),
                            # a click on a sample: its row held in the Values view
                            pick_change=(server.controller.welllog_pick, "[$event]"),
                            style="width:100%; height:100%;")
                # This view's OWN well tree. Which wellbores the panel holds
                # is the panel's business, so the control belongs beside it
                # rather than in the session-wide explorer — ticking there
                # puts the well in THIS log and reads its curves, and the eye
                # is the 3D eye (`engine/tree_grammar`).
                with FloatingCard(title="Well", open=(tree_open,),
                                  in_panel=True, panel_slot=card_slot(vid, "tree")):
                    WellLogTree(server, vid)
                with FloatingCard(title="Zone statistics", open=(zones_open,),
                                  in_panel=True, panel_slot=card_slot(vid, "zones")):
                    WellLogZones(
                        data=(var, dict(EMPTY)),
                        cutoffs=(cutoffs, []),
                        cutoffs_change=f"{cutoffs} = $event")

    @staticmethod
    def _empty(has_data, dropped):
        """An empty-but-working panel must not look like a broken one: the D3
        renderer draws nothing without wells, and a blank rectangle says
        nothing about which of the two it is. Three states, never one
        sentence for all three: no well at all, wells whose curves the reader
        has taken out of THIS log, and wells with nothing read yet. Saying
        "no curve read from them yet" over curves the panel was told to drop
        would be a lie. What the panel shows, then the gesture that fills it
        (UI rule R8): the two halves an <fp-empty> carries, on the attributes
        the browser sweep reads — this one stays in Python because the
        widget cannot mount over an empty dataset."""
        shows = "The curves of the wellbores you pick, side by side."
        gesture = (
            "!(ui_welllog_wells && ui_welllog_wells.length)"
            " ? 'Open the Well tree with its button in the bar at"
            " the left and tick a wellbore, or"
            " right-click a wellbore in a 3D view tree and choose"
            " “Add to Well Log view”.'"
            " : ((" + dropped + " || []).length"
            "    ? (ui_welllog_wells.length === 1 ? '1 wellbore'"
            "       : ui_welllog_wells.length + ' wellbores')"
            "      + ' in this log, and every curve read from"
            " them is unticked in this panel’s tree — tick one"
            " back to draw it.'"
            "    : (ui_welllog_wells.length === 1 ? '1 wellbore'"
            "       : ui_welllog_wells.length + ' wellbores')"
            "      + ' in this log, and no curve read from them"
            " yet — tick a log or a marker frame under a wellbore"
            " in the tree.')")
        html.Div(
            "{{ '" + shows + " ' + (" + gesture + ") }}",
            v_show=(f"!({has_data})",),
            # the one empty-state class of the application; the layout
            # (centred over the D3 canvas) stays local
            classes="fp-empty",
            __properties=[("data_fp_shows", "data-fp-shows"),
                          ("data_fp_gesture", "data-fp-gesture")],
            data_fp_shows=shows,
            data_fp_gesture=(gesture,),
            style="position:absolute; inset:0; display:flex;"
                  " align-items:center; justify-content:center;"
                  " font-size:13px; text-align:center;",
        )
