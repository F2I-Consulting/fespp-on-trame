"""RenderPanel — what every 3D view of the application shares: the title-bar
chrome (the hand and the mouse, 2D / 3D, Depth / Time, Represent by, the
shading, the framing, the axes, the zoom), the remote render with its camera
handlers, and the readout box at the render's free corner. Nothing about
WHAT the view shows: no toolbar, no tool card, no selection, no legend.
ViewPanel (view_panel.py) inherits it for the 3D view of the data and adds
those; a view that draws one thing on its own — the velocity model in the
Stratigraphy panel's model tab — stands on this class alone, with the same
title bar.

The view manager (view_manager.py) owns the scene + lifecycle; a panel just
builds the UI and exposes its VtkRemoteView as ``self.html_view`` so the
manager can route frame-push per panel. It must NOT touch
``controller.view_update`` (that single global would be overwritten by the
last view).

A view embedded in another panel (``inside=True``) has no tab row of its
own: its chrome lies over the render's top edge, shown and hidden with it.

What a subclass draws, in the order it is drawn — each a no-op here:
    _beside()       in the row, before the render container (the toolbar)
    _in_render()    in the render container, before the remote view (the
                    teleport targets a docked card needs when it mounts)
    _over_render()  in the render container, after the remote view and the
                    readout box (menus, legends, the cards)
    _below()        under the render container, across its width (the
                    bottom dock of the cards)
and what it extends through ``super()``:
    _empty()        JS: the view shows nothing (greys the title bar)
    _left_taken()   JS: the left button is spoken for (no double-click)
    _handlers()     the remote view's event handlers
    _readouts()     the lines of the readout box"""
from trame.widgets import html
from trame.widgets import paraview as pv_widgets

from trame_fespp_title3dview.widgets import Title3dView
from fespp_on_trame.app.views.widgets.view_chrome import chrome_place
from fespp_on_trame.app.views.frames import interactive_frames, render_backend

# Crosshair sampling cadence, in milliseconds: a ray cast on cached cell
# locators (boot.cursor_hit) per sample, on hover only — never while a
# button is held, so a camera drag never waits on it.
CURSOR_MS = 60

# How every block of a view is drawn: BlockScope draws them all through ONE
# composite rep, so the style is per VIEW, offered in its title bar.
REP_STYLES = ("Surface", "Surface With Edges", "Wireframe", "Points",
              "Outline")


class RenderPanel:
    """The UI of one render panel: title-bar chrome, the remote render with
    its camera handlers, the readout box at its free corner."""

    def __init__(self, server, view_id, pv_view, kind="render", *, inside=False):
        """`kind` "bare": the view draws one thing on its own (the velocity
        model), so the title bar greys the data's settings. `inside`: the
        chrome over the render's top edge rather than in the dockview tab
        row (a view embedded in another panel)."""
        self.server = server
        self.view_id = view_id
        self.pv_view = pv_view
        self.kind = kind
        self._inside = inside
        self.html_view = None  # set in _build, read by the view manager
        self._build()

    # --- what a subclass draws (see the module docstring) ---
    def _beside(self):
        pass

    def _in_render(self):
        pass

    def _over_render(self):
        pass

    def _below(self):
        pass

    def _empty(self):
        """JS: the view shows nothing, so reading, framing and zooming act
        on nothing. Here, never: a view drawing one thing on its own draws
        it."""
        return "false"

    def _left_taken(self):
        """JS: the left button is spoken for, so a double-click must not
        centre the view — here, the reading mouse holds the scene still."""
        return f"ui_cursor_mode__{self.view_id}"

    def _build(self):
        # flex row: what stands beside the render (left) | render container (right)
        with html.Div(style="display:flex; height:100%; width:100%;"
                      " position:relative;"):
            self._chrome()
            self._beside()
            self._right()

    def _right(self):
        """RIGHT — a column: the render container, then what a subclass
        docks below it (`_below`: a card docked at the bottom ⬓). The bottom
        is written FIRST and put last by its `order`: the cards a subclass
        mounts over the render teleport into it, and a teleport needs its
        target to exist when it mounts."""
        with html.Div(style="flex:1 1 0; height:100%; min-width:0;"
                      " display:flex; flex-direction:column;"):
            self._below()
            self._render_box()

    def _render_box(self):
        """The render container: the positioning context for what floats
        over the render (a subclass's cards, clamped here). A flex ROW so a
        DOCKED card (FloatingCard ◧ / ◨) sits beside the render, which
        shrinks."""
        with html.Div(style="position:relative; overflow:hidden;"
                      " flex:1 1 0; min-height:0; height:100%;"
                      " display:flex; flex-direction:row;"):
            self._in_render()
            self._render()
            self._readout()
            self._over_render()

    def _chrome(self):
        """The title-bar chrome: over the dockview tab row (negative top +
        the .dv-content-container overflow:visible override injected in
        __main__), between the group's own tab (110 px) and the dock's
        buttons, centred; embedded (`inside`), over the render's top edge on a ground of
        its own. A size container: the strip's CSS drops its least used
        controls as it narrows."""
        ctrl = self.server.controller
        vid = self.view_id
        inside = self._inside
        place = ("position:absolute; top:4px; height:35px; left:8px; right:8px; pointer-events:none;"
                 if inside else chrome_place(110))
        with html.Div(
            classes="d-flex align-center " + ("justify-end" if inside else "justify-center"),
            style=place + " z-index:6; gap:2px; container-type:inline-size;",
            mousedown="$event.stopPropagation()",
            click="$event.stopPropagation()",
        ):
            # Every gesture names the view it acts on (two views keep their
            # own 2D/3D), through the same nav_* controllers as the
            # Navigation card. The mousedown makes this view active: the
            # chrome swallows the click that would have (else the dockview
            # tab starts dragging).
            with html.Div(
                classes="d-flex align-center",
                # over a render, the readout box's ground
                style="height:100%;" + (" background:rgba(0,67,109,0.85);"
                                        " border-radius:3px; padding:0 4px;"
                                        if inside else ""),
                mousedown=(ctrl.view_activate, f"['{vid}']"),
            ):
                self.server.state.setdefault("ui_rep_styles",
                                             list(REP_STYLES))
                self.server.state.setdefault(f"ui_rep_style__{vid}",
                                             "Surface")
                Title3dView(
                    # the hand (the scene moves) or the mouse (show
                    # position, the scene held still — the pointer
                    # handlers of the render below stop every press)
                    cursor=(f"!!ui_cursor_mode__{vid}",),
                    # nothing shown: reading, framing and zooming act
                    # on nothing
                    empty=(self._empty(),),
                    # one thing drawn on its own: the data's settings
                    # and the reading mouse are greyed with why
                    bare=self.kind == "bare",
                    # a view drawing one thing on its own has no cards:
                    # its camera is linked from its title bar
                    linkable=self.kind == "bare",
                    linked=(f"((view_links || {{}})['{vid}'] || [])"
                            f".map(i => ((fespp_link_panels || []).find(p => p.id === i) || {{}}).title || i)"
                            f".join(', ')",),
                    toggle_link=(ctrl.camlink_follow, f"['{vid}']"),
                    set_cursor=(ctrl.view_cursor_mode, f"['{vid}', $event]"),
                    mode=(f"ui_interaction_mode__{vid} || '3D'",),
                    globe=(f"!!ui_globe_mode__{vid}",),
                    rep_style=(f"ui_rep_style__{vid} || 'Surface'",),
                    rep_styles=("ui_rep_styles", []),
                    set_mode=(ctrl.view_interaction_mode,
                              f"['{vid}', $event]"),
                    reset=(ctrl.nav_reset, f"['{vid}']"),
                    # the Navigation card's door (tools_config: door "title")
                    nav_open=(f"((ui_open_tools_by_view || {{}})['{vid}'] || [])"
                              f".includes('navigation')",),
                    navigation=(ctrl.toggle_tool, f"['navigation', '{vid}']"),
                    set_style=(ctrl.set_rep_style, f"['{vid}', $event]"),
                    # exact colours (no shading) or shaded: how the view
                    # LOOKS, beside Represent by (boot._apply_flat_colors)
                    flat=(f"!!ui_flat_colors__{vid}",),
                    set_flat=(ctrl.set_flat_colors, f"['{vid}', $event]"),
                    # depth or time: the vertical domain the view draws
                    # (app/features/view_domain)
                    vdomain=(f"ui_vdomain__{vid} || 'depth'",),
                    domains=("ui_vdomains", []),
                    set_domain=(ctrl.view_domain, f"['{vid}', $event]"),
                    # this view's vertical exaggeration
                    z_scale=(f"ui_scale_z__{vid} || 1",),
                    set_zscale=(ctrl.set_zscale, f"[$event, '{vid}']"),
                    frame=(ctrl.globe_frame, f"[$event, '{vid}']"),
                )

    def _render(self):
        """The remote render, with the handlers of `_handlers`."""
        vid = self.view_id
        # drag frames per backend (views/frames.py); still frames at JPEG
        # 90, a third of the bytes of trame's 100 for no visible difference
        ratio, quality = interactive_frames(render_backend())
        self.html_view = pv_widgets.VtkRemoteView(
            self.pv_view, interactive_ratio=ratio,
            interactive_quality=quality, still_quality=90,
            # the mouse of the title bar shows as a crosshair: the
            # pointer reads, the scene does not move
            style=(f"'flex:1 1 0; min-width:0; height:100%;'"
                   f" + (ui_cursor_mode__{vid} ? ' cursor:crosshair;' : '')",),
            **self._handlers(),
        )

    def _handlers(self):
        """The remote view's event handlers, as VtkRemoteView kwargs: the
        camera link, the double-click that centres, the mouse mode of the
        title bar. A subclass extends the dict, `__events` included.

        Handlers ON the remote view itself (a wrapper div breaks its
        sizing). No `window` here — Vue template expressions can't see it —
        the scratch values live on the DOM element ($event.currentTarget).
        POINTER events in CAPTURE phase: vtk.js's interactor
        preventDefault()s + pointer-captures `pointerdown` on its
        container, which suppresses the compatibility `mousedown` (it
        never reaches this element); a press stopped here, in the capture
        phase, is one vtk.js never sees.
        NB: an inline `if`/`const` handler MUST end with ';' — Vue wraps a
        handler without one as `$event => (expr)`, and a statement there
        is a SyntaxError that blanks the whole panel."""
        vid = self.view_id
        ctrl = self.server.controller
        # the camera link, called only when there IS one (below)
        sync_trigger = ctrl.trigger_name(ctrl.camera_link_sync)
        # double-click: centre the view on what is under the pointer — not
        # while something holds the left button
        dbl_trigger = ctrl.trigger_name(ctrl.view_center_here)
        # [x, y, w, h] relative to THIS element (the event target is
        # the captured canvas container, so offsetX/Y is not reliable)
        ev_expr = ("(r => [$event.clientX - r.left, $event.clientY - r.top,"
                   " $event.currentTarget.clientWidth,"
                   " $event.currentTarget.clientHeight])"
                   "($event.currentTarget.getBoundingClientRect())")
        return {
            # camera links: ParaView's own carry the gesture; the
            # release (EndAnimation) pushes the linked views' last image
            # (view_manager._sync_camera_from). Tested client-side: an
            # unlinked view sends nothing (trame counts every trigger as
            # busy, which lights the loading bars).
            "interactor_events": ("interactor_events_default",
                                  ["EndAnimation"]),
            "EndAnimation": (
                f"if (view_links && (view_links['{vid}'] || []).length)"
                f" {{ trigger('{sync_trigger}', ['{vid}']); }}"),
            "__events": [("pointerdown_capture", "pointerdown.capture"),
                         ("wheel_capture", "wheel.capture"),
                         "mousemove", "mouseleave", "dblclick"],
            "dblclick": (
                f"if (!{self._left_taken()} && $event.button === 0) {{"
                f" const el = $event.currentTarget;"
                f" const r = el.getBoundingClientRect();"
                f" trigger('{dbl_trigger}',"
                f" [[$event.clientX - r.left, $event.clientY - r.top,"
                f" el.clientWidth, el.clientHeight], '{vid}']); }}"),
            # the mouse mode holds the scene still: every press and wheel
            # notch stopped in the capture phase, before vtk.js's
            # interactor; the right-click menu still opens (`contextmenu`
            # is an event of its own)
            "wheel_capture": (f"if (ui_cursor_mode__{vid}) {{"
                              f" $event.stopPropagation(); $event.preventDefault(); }}"),
            "pointerdown_capture": (
                f"if (ui_cursor_mode__{vid}) {{ $event.stopPropagation(); }}"),
            # the position on hover, throttled at CURSOR_MS with a
            # trailing shot so the resting position is exact; nothing
            # while a button is held (a camera drag), the first sample
            # after the release at once. `setTimeout` is reached through
            # the element's window: it is not a Vue-template global.
            "mousemove": (f"if (ui_cursor_mode__{vid}) {{"
                          f" const el = $event.currentTarget; const ev = {ev_expr};"
                          f" const w = el.ownerDocument.defaultView;"
                          f" w.clearTimeout(el.__fesppTo);"
                          f" if ($event.buttons) {{ el.__fesppLast = 0; }}"
                          f" else {{ const now = w.Date.now();"
                          f"   if (now - (el.__fesppLast || 0) > {CURSOR_MS}) {{"
                          f"     el.__fesppLast = now;"
                          f"     pos_ev__{vid} = ev; }}"
                          f"   else {{ el.__fesppTo = w.setTimeout(() => {{"
                          f"     el.__fesppLast = w.Date.now();"
                          f"     pos_ev__{vid} = ev; }}, {CURSOR_MS}); }} }} }}"),
            "mouseleave": (f"if (ui_cursor_mode__{vid}) {{"
                           f" const el = $event.currentTarget;"
                           f" el.ownerDocument.defaultView.clearTimeout(el.__fesppTo);"
                           f" ui_cursor_pos__{vid} = ''; }}"),
        }

    def _readouts(self):
        """The lines of the readout box, in the order drawn: (JS: shown
        when, the state var shown, its style or "")."""
        vid = self.view_id
        note = "color:#FFD79A; max-width:38ch; white-space:normal;"
        return [
            (f"ui_cursor_mode__{vid} && ui_cursor_pos__{vid}",
             f"ui_cursor_pos__{vid}", ""),
            # the wheel stopped at the face of the data (camera.py's
            # WheelWall), said where the gesture is; cleared on the first
            # notch not refused
            (f"ui_zoom_note__{vid}", f"ui_zoom_note__{vid}", note),
            # a note about this view (app/core/notifier), whatever the mode
            (f"ui_view_note__{vid}", f"ui_view_note__{vid}", note),
        ]

    def _readout(self):
        # overlay (bottom-right of the render's free corner): every line
        # of `_readouts` that has something to say
        lines = self._readouts()
        with html.Div(
            v_show=(" || ".join(f"({shown})" for shown, _var, _style in lines),),
            style="position:absolute; right:8px; bottom:8px; z-index:4;"
                  " background:rgba(0,67,109,0.85); color:#fff;"
                  " padding:3px 8px; border-radius:3px; font-size:12px;"
                  " font-family:ui-monospace, Consolas, monospace;"
                  " pointer-events:none; white-space:pre;",
        ):
            for shown, var, style in lines:
                html.Div("{{ " + var + " }}", v_show=(shown,),
                         **({"style": style} if style else {}))
