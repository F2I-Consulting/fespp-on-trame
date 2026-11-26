"""ViewPanel — the 3D view of the data: a RenderPanel (render_panel.py: the
title-bar chrome, the remote render with its camera handlers, the readout
box) plus a docked vertical toolbar beside the render, one floating tool
card per tool (tools_config.TOOLS), the selection modes with their rubber
band, the right-click menu on the render and the legends.

The view manager (view_manager.py) owns the scene + lifecycle; render_panel.py
says what a panel may and may not touch."""
from trame.widgets import html
from trame_fespp_dock.widgets import FpDockSlot

from trame_fespp_view_tools.widgets.view_tools import ViewToolbar
from trame_fespp_view_card.widgets.card import FloatingCard
from trame_fespp_navigation.widgets import ViewContextMenu
from trame_fespp_colormap.widgets import LegendsPanel
import os

from fespp_on_trame.app.views.render_panel import RenderPanel
from fespp_on_trame.app.views.widgets.card_dock import card_dock, card_slot, card_spec, center_slot
from fespp_on_trame.app.views.tools_config import (
    TOOLS, MODE_TOOLS, NEEDS_WHY, NO_DATA_WHY, default_open_keys, toolbar,
)

# dock columns, either side of the render: docked cards stack here
# width: set by the cards (FloatingCard.syncColumn = widest docked card) —
# min-width:0 so content can never widen it
_DOCK_CSS = ("display:flex; flex-direction:column; height:100%;"
             " flex:0 0 auto; min-width:0; overflow:hidden;")


class ViewPanel(RenderPanel):
    """The UI of the data's render panel: what RenderPanel draws, plus the
    toolbar, the selection, the menu, the legends and the tool cards."""

    def __init__(self, server, view_id, pv_view, kind="render"):
        # the cards of the tools this kind of view serves (`kinds`)
        self.tools = [t for t in TOOLS if kind in t.get("kinds", ("render", "globe"))]
        super().__init__(server, view_id, pv_view, kind)

    @property
    def _open_expr(self):
        """JS: the keys of this view's open cards (the toolbar lights them,
        the cards show on them)."""
        return (f"(ui_open_tools_by_view "
                f"&& ui_open_tools_by_view['{self.view_id}']) || []")

    @property
    def _sel_mode(self):
        """JS: a selection tool holds the left button — the hand (a surface
        pick) or the frustum."""
        return f"(ui_pick_mode__{self.view_id} || ui_frustum_mode__{self.view_id})"

    def _seed_open_tools(self):
        st = self.server.state
        cards = getattr(self.server.context, "cards", None)   # app/scene/cards
        opened = (cards.has_view(self.view_id) if cards is not None
                  else self.view_id in (st.ui_open_tools_by_view or {}))
        if not opened:
            # default_open: bool, or the view kinds it opens in. Nothing opens
            # before there is data: an empty card the toolbar cannot even
            # close is worse than no card (boot._on_has_data opens the
            # defaults on the first import).
            keys = (default_open_keys(self.tools, self.kind, getattr(st, "assembly_xml", "") or "",
                                      getattr(st, "ui_cube_grid_rows", None) or ())
                    if st.ui_has_data else [])
            if cards is not None:
                cards.set(self.view_id, keys)
            else:   # a panel built outside the app (unit tests)
                st.ui_open_tools_by_view = {**(st.ui_open_tools_by_view or {}),
                                            self.view_id: keys}
        # Declarative toolbar metadata, PER VIEW: every tool of its kind is
        # drawn; a view is built BEFORE wire_view seeds its state, so no
        # `needs` gate can be answered yet: those are greyed until
        # wire_view's _refresh_view_tools, right after, answers them.
        has_data = bool(st.ui_has_data)
        st[f"view_tools_{self.view_id}"] = toolbar(
            self.tools + (MODE_TOOLS if self.kind == "render" else []),
            lambda t: (NO_DATA_WHY if not has_data
                       else NEEDS_WHY.get(t.get("needs"), "") if t.get("needs") else ""))

    def _empty(self):
        # nothing checked in the tree
        vid = self.view_id
        return f"!(visible_paths__{vid} && visible_paths__{vid}.length)"

    def _left_taken(self):
        # the reading mouse, or a selection tool
        return f"({super()._left_taken()} || {self._sel_mode})"

    def _beside(self):
        self._seed_open_tools()
        vid = self.view_id
        # LEFT — the per-view toolbar (one button per configured tool)
        # badge: this view's time animation is playing (visible even
        # with the Time & Realizations card closed)
        tr = f"ui_timereal_player__{vid}"
        ViewToolbar(
            tools=(f"view_tools_{vid}",),
            open=(self._open_expr,),
            badges=(f"({tr} && {tr}.playing) ? ['timereal'] : []",),
            toggle=(self.server.controller.toggle_tool, f"[$event, '{vid}']"),
        )

    @property
    def _card_dock(self):
        """The cards are panels of a dock of the view's own (the render its
        fixed centre), not floating cards (those: FESPP_CARD_DOCK=0)."""
        return (os.environ.get("FESPP_CARD_DOCK") or "").strip() != "0"

    def _right(self):
        if not self._card_dock:
            return super()._right()
        vid = self.view_id
        ctrl = self.server.controller
        st = self.server.state
        # what each card's panel is made with (its slot: where the card's
        # content, kept in the reservoir below, is shown)
        st[f"ui_card_specs__{vid}"] = {
            t["key"]: card_spec(vid, t["key"], t["title"], t.get("width", 260), t.get("height", 0))
            for t in self.tools}
        keys = [t["key"] for t in self.tools]
        # where the cards were left: kept by the server, back at a reload and
        # in a saved session
        layout = f"ui_card_layout__{vid}"
        st.setdefault(layout, None)
        # which cards are on screen, and the one a button brings in front
        # when it is behind another card's tab
        reveal = f"ui_card_reveal__{vid}"
        st.setdefault(reveal, None)
        card_dock(vid, f"({self._open_expr}).filter((k) => {keys!r}.includes(k))",
                  f"ui_card_specs__{vid}", (ctrl.close_tool, f"[$event, '{vid}']"), layout,
                  visibility=(ctrl.card_visibility, f"[$event, '{vid}']"), reveal=reveal,
                  active=(ctrl.card_in_use, f"[$event, '{vid}']"))
        # the render and the cards, built once here (a closed card is hidden,
        # not destroyed): each moves into its panel while that panel exists
        with html.Div(style="display:none;"):
            with FpDockSlot(slot_key=center_slot(vid)):
                self._render_box()
            self._cards()

    def _in_render(self):
        if self._card_dock:
            return
        # the left dock column, rendered BEFORE the cards so the teleport
        # target exists when a card mounts (the right one, after the render)
        html.Div(id=f"fc-dock-left-{self.view_id}", style=_DOCK_CSS + " order:-1;")

    def _below(self):
        if self._card_dock:
            return
        # the bottom dock: a row across the view under the render, its
        # height set by the cards docked in it (FloatingCard.syncColumn)
        html.Div(id=f"fc-dock-bottom-{self.view_id}",
                 style="display:flex; flex-direction:row; width:100%; order:1;"
                       " flex:0 0 auto; min-height:0; overflow:hidden;")

    def _handlers(self):
        """RenderPanel's handlers, plus the selection modes and the
        right-click menu.

        In a selection mode the LEFT press is stopped in the capture phase
        (it runs first) so vtk.js does not rotate: the drag draws a rubber
        band (#fc-rb, plain DOM, no server traffic) and the release sends
        the rectangle — or a one-pixel region when the mouse did not move.
        Middle / right drags still pan / zoom."""
        vid = self.view_id
        ctrl = self.server.controller
        sel_mode = self._sel_mode
        h = super()._handlers()
        pick_trigger = ctrl.trigger_name(ctrl.view_pick)
        # right-click anywhere on the render: pick what is under the
        # pointer and open the menu FOR IT — the tree's actions
        # (statistics / well log …) reached
        # from the scene instead of from the tree.
        ctx_trigger = ctrl.trigger_name(ctrl.view_context_menu)
        h["__events"] = h["__events"] + [
            ("pointermove_capture", "pointermove.capture"),
            ("pointerup_capture", "pointerup.capture"), "contextmenu"]
        # NB: an inline `if`/`const` handler MUST end with ';' —
        # Vue wraps a handler without one as `$event => (expr)`,
        # and a statement there is a SyntaxError that blanks the
        # whole panel (the same trap as the pointer handlers).
        h["contextmenu"] = (
            f"$event.preventDefault();"
            f" const el = $event.currentTarget;"
            f" const r = el.getBoundingClientRect();"
            f" trigger('{ctx_trigger}',"
            f" [[$event.clientX - r.left, $event.clientY - r.top,"
            f" el.clientWidth, el.clientHeight], '{vid}']);")
        # the mouse mode's stop first (RenderPanel), then the selection
        h["pointerdown_capture"] = h["pointerdown_capture"] + (
            f" else if ({sel_mode} && $event.button === 0) {{"
            f" $event.stopPropagation();"
            f" const el = $event.currentTarget;"
            f" el.setPointerCapture($event.pointerId);"
            f" el.__fesppPd = [$event.clientX, $event.clientY]; }}")
        h["pointermove_capture"] = (
            f"if ({sel_mode} && $event.currentTarget.__fesppPd && ($event.buttons & 1)) {{"
            f" const el = $event.currentTarget; const pd = el.__fesppPd;"
            f" const rb = el.ownerDocument.getElementById('fc-rb-{vid}');"
            f" const pr = rb.parentElement.getBoundingClientRect();"
            f" rb.style.left = (Math.min(pd[0], $event.clientX) - pr.left) + 'px';"
            f" rb.style.top = (Math.min(pd[1], $event.clientY) - pr.top) + 'px';"
            f" rb.style.width = Math.abs($event.clientX - pd[0]) + 'px';"
            f" rb.style.height = Math.abs($event.clientY - pd[1]) + 'px';"
            f" rb.style.display = 'block'; }}")
        h["pointerup_capture"] = (
            f"if ({sel_mode} && $event.button === 0 && $event.currentTarget.__fesppPd) {{"
            f" const el = $event.currentTarget; const pd = el.__fesppPd; el.__fesppPd = null;"
            f" el.ownerDocument.getElementById('fc-rb-{vid}').style.display = 'none';"
            f" const r = el.getBoundingClientRect();"
            f" const moved = Math.abs($event.clientX - pd[0]) >= 4 || Math.abs($event.clientY - pd[1]) >= 4;"
            f" const x1 = moved ? $event.clientX : pd[0], y1 = moved ? $event.clientY : pd[1];"
            f" trigger('{pick_trigger}', [[pd[0] - r.left, pd[1] - r.top, x1 - r.left, y1 - r.top,"
            f" el.clientWidth, el.clientHeight], '{vid}',"
            f" ui_frustum_mode__{vid} ? 'frustum' : 'surface']); }}")
        return h

    def _readouts(self):
        # the last selection (hand / frustum) first, then RenderPanel's lines
        vid = self.view_id
        return [(f"{self._sel_mode} && ui_pick_info__{vid}",
                 f"ui_pick_info__{vid}", "")] + super()._readouts()

    def _over_render(self):
        ctrl = self.server.controller
        vid = self.view_id
        # right-click menu ON the render: picking in the scene is the
        # second way into the analysis views, the tree being the
        # first. Server-picked, so the entries always match what the
        # pointer is actually over.
        ViewContextMenu(
            menu=(f"ui_ctx_menu__{vid}", {}),
            pick=(ctrl.view_context_action, f"[$event, '{vid}']"),
            close=(ctrl.view_context_close, f"['{vid}']"),
        )
        # the legend of every table colouring the view, overlaid top
        # right (the orientation axes are bottom left, the one colour
        # bar bottom right): a row puts its table on the bar
        # (engine/legends, boot._publish_legends)
        self.server.state.setdefault(f"ui_legends__{vid}", {})
        LegendsPanel(
            view_id=vid,
            legends=(f"ui_legends__{vid} || {{}}",),
            pick=(ctrl.legend_pick, f"[$event, '{vid}']"),
        )
        # the one colour bar is a drawing of the render, bottom right: a click
        # on it opens the Colormap card (its height: how long the bar is)
        html.Div(
            v_show=(f"(ui_legends__{vid} || {{}}).bar > 0",),
            classes="fp-bar-hit",
            style=(f"{{ height: 'calc(' + 100 * ((ui_legends__{vid} || {{}}).bar || 0) + '% + 24px)' }}",),
            title="Open the Colormap card",
            click=(ctrl.legend_open, f"['{vid}']"),
        )
        if not self._card_dock:
            html.Div(id=f"fc-dock-right-{vid}", style=_DOCK_CSS + " order:1;")
        # rubber band drawn by the pointer handlers above (selection
        # modes); positioned in this container (its offsetParent)
        html.Div(id=f"fc-rb-{vid}",
                 style="position:absolute; display:none; z-index:5;"
                       " border:1.5px dashed #8FC31F;"
                       " background:rgba(143,195,31,0.12);"
                       " pointer-events:none;")
        if not self._card_dock:
            self._cards()

    def _cards(self):
        ctrl = self.server.controller
        vid = self.view_id
        in_panel = self._card_dock
        # one floating card per tool, shown when open, staggered so they
        # don't all stack on the same spot. A card that acts on
        # something names it in its title bar (boot._set_tool_target).
        target = f"ui_tool_target__{vid}"
        self.server.state.setdefault(target, {})
        # a card whose title follows what it shows
        titles = f"ui_tool_title__{vid}"
        self.server.state.setdefault(titles, {})
        # where each card was left (moved, resized, docked): kept
        # per view and per tool, so a page reload puts the cards
        # back where they were (boot.card_geometry writes it)
        geom = f"ui_card_geometry__{vid}"
        self.server.state.setdefault(geom, {})
        for i, t in enumerate(self.tools):
            g = f"(({geom} || {{}})['{t['key']}'] || {{}})"
            with FloatingCard(
                title=((f"({titles} || {{}})['{t['key']}'] || '{t['title']}'",) if t.get("retitled") else t["title"]),
                target=(f"({target} || {{}})['{t['key']}'] || ''",),
                x0=(f"{g}.x ?? {t.get('x0', 16 + i * 22)}",),
                y0=(f"{g}.y ?? {t.get('y0', 8 + i * 22)}",),
                width=(f"{g}.w ?? {t.get('width', 260)}",),
                height=(f"{g}.h ?? {t.get('height', 0)}",),
                dock0=(f"{g}.dock || '{t.get('dock', 'float')}'",),
                resizable=(str(t.get("resizable", True)).lower(),),
                open=(f"({self._open_expr}).includes('{t['key']}')",),
                dock_left=f"#fc-dock-left-{vid}",
                dock_right=f"#fc-dock-right-{vid}",
                dock_bottom=f"#fc-dock-bottom-{vid}",
                close=(ctrl.toggle_tool, f"['{t['key']}', '{vid}']"),
                geometry=(ctrl.card_geometry, f"['{t['key']}', '{vid}', $event]"),
                **({"in_panel": True, "panel_slot": card_slot(vid, t["key"])} if in_panel else {}),
            ):
                t["build"](self.server, vid)
