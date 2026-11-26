"""Multi-view — a dockview of panels, one per VIEW KIND (views_config.py).

Built on the application's dock (``widgets/dock``, ``FpDock``). Each panel's content is built by
its kind's builder; the ``"render"`` kind owns a ParaView RenderView + a ViewPanel
(vertical toolbar + render + tool cards). Data load is session-global (a loaded
rep appears in every render view); visibility, coloring and camera are per-view.
A kind marked ``render_view: "bare"`` (views_config) gets a RenderView too, wired
bare — no scene, no eyes, no tools — for what its panel draws on its own (the
Stratigraphy panel's velocity model); it stays out of ``view_ids`` (the data's
views) and is reached through ``bare_view_ids`` and ``get_pv_view``.

The engine (SceneRegistry / data_load / visibility / source_resolver) is
per-view aware; this class is the dockview glue:

- tracks ``{panel_id -> pv_view}`` and ``{panel_id -> html_view}``,
- registers each render view's scene + per-view state/handlers,
- routes frame-push per panel — it NEVER overwrites ``controller.view_update``;
  the engine reaches the live views via ``server.context.multi_view`` (this).

Add-view UI: one button in the app toolbar. Adding a view is an application
action, so it is offered once, not once per existing panel: no ptc "+" or
"Create RenderView" watermark.
"""
import os
import sys
from contextlib import contextmanager

from paraview import simple as pvsimple
from trame.ui.html import DivLayout
from trame.widgets import paraview
from trame_fespp_dock.widgets import FpDock

from fespp_on_trame.app.views.camera import (
    copy_camera_properties, install_activity_watch, install_wheel_wall)
from fespp_on_trame.app.views import per_view_state
from fespp_on_trame.app.views.views_config import VIEW_KINDS, DEFAULT_KIND
from fespp_on_trame.app.views import frames
from fespp_on_trame.app.views.dock_fill import DockFill
from fespp_on_trame.app.views.widgets.view_chrome import HEADER_BUTTONS, fill_on_double_click
from fespp_on_trame.app.views.widgets.view_wait import view_wait

# the backend kind, read and said once per process by _say_render_backend:
# [kind] with kind "software", "gpu", or "" when unreadable
_BACKEND = []


def _say_render_backend(pv_view):
    """Say, ONCE, which OpenGL implementation is really drawing, and return
    its kind: "software", "gpu", or "" when the window would not say.

    Nothing silent. A container reached by no GPU renders in software, which
    is not broken (it is what it can do) but is well over an order of
    magnitude slower on a real grid, and whoever finds the 3D sluggish
    should READ why in the session log instead of guessing.

    The name comes from the render window itself, not from the presence of a
    device: what matters is what ended up drawing, and the fall back to
    software is silent everywhere else in the stack.
    """
    if _BACKEND:
        return _BACKEND[0]
    kind = ""
    name = ""
    try:
        pvsimple.Render(view=pv_view)
        caps = pv_view.GetClientSideObject().GetRenderWindow().ReportCapabilities()
        for line in (caps or "").splitlines():
            if "OpenGL renderer" in line:
                name = line.split(":", 1)[-1].strip()
                break
    except Exception as exc:
        print(f"[fespp] 3D rendering: could not read the OpenGL engine ({exc})",
              file=sys.stderr, flush=True)
        _BACKEND.append(kind)
        frames.remember_backend(kind)
        return kind
    if not name:
        print("[fespp] 3D rendering: the render window names no OpenGL engine",
              file=sys.stderr, flush=True)
    elif any(k in name.lower() for k in ("llvmpipe", "softpipe", "swrast")):
        kind = "software"
        print(f"[fespp] 3D rendering: SOFTWARE ({name}) — no GPU reached this"
              " container. Passing one makes the render ~70x faster on a large"
              " grid: run the container with GPU access (GPU mode in README.md).",
              file=sys.stderr, flush=True)
    else:
        kind = "gpu"
        print(f"[fespp] 3D rendering: GPU ({name})", file=sys.stderr, flush=True)
    _BACKEND.append(kind)
    frames.remember_backend(kind)
    return kind


# ParaView's interactive LOD, in SOFTWARE rendering only. trame turns the LOD
# off for every view (RenderViewSettings.LODThreshold = 102400 MB, set by
# trame_vtk's paraview module): on a GPU that costs nothing visible, in
# software it makes a drag on a large grid about four times slower. Above
# this many MB of delivered geometry a software-rendered view drags a
# decimated copy and draws the full one on release, which is what ParaView
# itself does from 20 MB. FESPP_LOD_MB forces a threshold on any backend
# (0 = always, 102400 = never), which is how to compare the two.
SOFTWARE_LOD_MB = 20.0
_LOD_SAID = []


def _tune_lod(pv_view, kind):
    """Give `pv_view` the LOD threshold its backend deserves — and the
    settings every later view is born from — and say so, once."""
    forced = os.environ.get("FESPP_LOD_MB", "").strip()
    if forced:
        try:
            mb = float(forced)
        except ValueError:
            print(f"[fespp] FESPP_LOD_MB={forced!r} is not a number — ignored",
                  file=sys.stderr, flush=True)
            return
        why = "FESPP_LOD_MB"
    elif kind == "software":
        mb = SOFTWARE_LOD_MB
        why = "software rendering"
    else:
        return
    try:
        pvsimple.GetSettingsProxy("RenderViewSettings").LODThreshold = mb
        pv_view.LODThreshold = mb
    except Exception as exc:
        print(f"[fespp] interactive LOD: could not set the threshold ({exc})",
              file=sys.stderr, flush=True)
        return
    if not _LOD_SAID:
        _LOD_SAID.append(True)
        print(f"[fespp] interactive LOD: on above {mb:g} MB of geometry ({why})"
              f" — a drag draws a decimated copy, the release the full one",
              file=sys.stderr, flush=True)


_DOCK_REF = "fespp_dock"


class MultiView(FpDock):
    """The dockview of the application's panels (see the module docstring),
    reachable by the engine as `server.context.multi_view`."""

    def __init__(self, server, **kwargs):
        self._html_views = {}
        self._titles = {}
        self._kinds = {}
        # the number in a panel's title, counted per KIND among the open
        # panels: "3D view 2" is the second 3D view open, whatever else
        # was opened in between (the PO, 02/11)
        self._numbers = {}
        self._pv_internal = {}
        # the RenderViews of the panels drawing one thing on their own
        # (`render_view: "bare"`): never in `view_ids`, the data's views
        self._pv_bare = {}
        # one WheelWall per render view, kept alive here (see the install)
        self._wheel_walls = {}
        # per panel, the callables feeding camera.ACTIVITY (kept alive here)
        self._camera_watch = {}
        # (view a, view b) -> the name of ParaView's own camera link between
        # them (`_apply_camera_links`)
        self._camera_links = {}
        self._view_count = 0
        self._active_panel_id = None
        self._first_adopted = False
        # the last layout dockview reported (its own toJSON): what a page
        # reload restores, so the panels come back where they were and not
        # as a row of tabs
        self._layout = None
        # the place a `placed` block gives the panels opened inside it
        self._place = None
        # the panels on screen, not behind another tab
        self._on_screen = set()
        # the panels leaving the dock to come back, and where: they do not close
        self._moving = {}
        self._tab_places = {}
        # the 3D views hidden from the top bar's 3D button: out of the dock,
        # alive, their state kept, back where they were when shown again
        self._hidden = set()
        super().__init__(
            active_panel=(self._on_view_activated, "[$event]"),
            remove_panel=(self._on_view_closed, "[$event]"),
            layout_changed=(self._on_layout_changed, "[$event]"),
            panel_visibility=(self._on_panel_visibility, "[$event]"),
            ready=self._on_ready,
            theme="Dracula",
            # the views' dock: what the page's CSS and the double click aim
            # at, never a dock inside one of its panels (`fp-cards`)
            classes="fp-views",
            # a view is detached by its own button; Maj + drag would take its
            # whole group, at a size to work in nothing
            disable_floating_groups=True,
            # a detached view moves by the empty part of its tab row
            floating_group_drag_handle="tabbar",
            # its whole window, tab row included, stays inside the dock
            floating_group_bounds="boundedWithinViewport",
            # the buttons of every tab row; detached and anchored by the
            # server, which centres it and remembers where it was; a tab
            # dropped where nothing docks it comes with the drop point
            header_buttons=(repr(HEADER_BUTTONS),),
            header_emit=("['float']",),
            header_action=(server.controller.view_float,
                           "[$event.id, $event.width, $event.height,"
                           " $event.left, $event.top]"),
            __events=["dblclick"],
            dblclick=fill_on_double_click(server),
            ref=_DOCK_REF,
            **kwargs,
        )
        self.fill = DockFill(self)
        server.state.setdefault("ui_floating_views", [])
        paraview.initialize(server)
        # panel_resolver + the engine fan-out reach the live views through here.
        server.context.multi_view = self
        server.controller.add_view = self.add_view
        # camera links: ParaView's own (vtkSMCameraLink) carry every frame of
        # a gesture; each ViewPanel's VtkRemoteView binds its EndAnimation
        # (mouse release) to the final copy and image push.
        server.controller.camera_link_sync = self._sync_camera_from
        server.state.change("view_links")(
            lambda **_: self._apply_camera_links())

    # --- registry accessors used by panel_resolver / engine fan-out ---
    def get_pv_view(self, panel_id):
        pvv = self._pv_internal.get(panel_id)
        return pvv if pvv is not None else self._pv_bare.get(panel_id)

    def get_html_view(self, panel_id):
        return self._html_views.get(panel_id)

    def kind_of(self, panel_id):
        return self._kinds.get(panel_id, DEFAULT_KIND)

    def panel_ids(self):
        """Every open panel, of any kind."""
        return list(self._titles)

    def title_of(self, panel_id):
        """The tab title of an open panel, or its id when it has none."""
        return self._titles.get(panel_id, panel_id)

    def retitle(self, panel_id, title):
        """A new tab title for an open panel — what a panel that follows a
        property says when the property changes."""
        if panel_id not in self._titles:
            return
        self._titles[panel_id] = title
        self.set_panel_title(panel_id, title)

    def panel_ids_of_kind(self, kind):
        """Panels of a given kind, render or not — `view_ids` only knows the
        ones with a ParaView view, so a welllog panel is invisible to
        it and its per-view state var could never be found."""
        return [pid for pid, k in self._kinds.items() if k == kind]

    def view_ids(self):
        return list(self._pv_internal.keys())

    def bare_view_ids(self):
        """The panels drawing one thing on their own (`render_view: "bare"`)."""
        return list(self._pv_bare.keys())

    def html_views(self):
        return list(self._html_views.values())

    # --- lifecycle ---
    def _on_layout_changed(self, layout):
        # every move, split, resize or close the reader makes, as dockview
        # serialises it — kept server-side for the next reload
        self._keep_layout(layout)
        # the panel it has active: activations a tick apart may have overtaken
        # each other on their way here
        active = self._active_in(layout)
        if active and active != self._active_panel_id and active in self._titles:
            self._set_active(active)

    def _keep_layout(self, layout):
        if isinstance(layout, dict) and layout.get("panels"):
            self._layout = layout
            self.server.state.ui_floating_views = [
                pid for group in layout.get("floatingGroups") or ()
                for pid in (group.get("data") or {}).get("views") or ()]

    @staticmethod
    def _active_in(layout):
        """The active panel of the active group of a dockview layout, or None."""
        if not isinstance(layout, dict):
            return None
        wanted = layout.get("activeGroup")

        def groups(node):
            if node.get("type") == "leaf":
                yield node.get("data") or {}
            elif node.get("type") == "branch":
                for child in node.get("data") or ():
                    yield from groups(child)
        root = (layout.get("grid") or {}).get("root") or {}
        floats = (g.get("data") or {} for g in layout.get("floatingGroups") or ())
        for group in (*groups(root), *floats):
            if group.get("id") == wanted:
                return group.get("activeView")
        return None

    def _on_panel_visibility(self, event):
        if isinstance(event, dict) and event.get("id"):
            (self._on_screen.add if event.get("visible") else self._on_screen.discard)(event["id"])

    def on_screen(self, panel_id):
        """The panel is in sight, not behind another tab."""
        return panel_id in self._on_screen

    def _put_back(self, panel_id, **place):
        """`panel_id` taken out of the dock and, once it is out, put back at
        `place`, its content and its state kept: the wrapper has no other way to a
        floating group."""
        self._moving[panel_id] = place
        self.remove_panel(panel_id)

    def _tab_place(self, panel_id):
        """The tabs of its group before and after `panel_id`, to find its place
        again; None alone in its group."""
        def groups(node):
            if node.get("type") == "leaf":
                yield (node.get("data") or {}).get("views") or []
            elif node.get("type") == "branch":
                for child in node.get("data") or ():
                    yield from groups(child)
        root = ((self._layout or {}).get("grid") or {}).get("root") or {}
        for tabs in groups(root):
            if panel_id in tabs and len(tabs) > 1:
                at = tabs.index(panel_id)
                return tabs[:at], tabs[at + 1:]
        return None

    def hidden(self):
        """The 3D views hidden (`hide_panel`)."""
        return set(self._hidden)

    def hide_panel(self, panel_id):
        """`panel_id` out of the dock, alive: its scene, its eyes, its camera
        and its cards kept for `show_panel`, which puts it back among the
        tabs it left. Another view becomes the active one."""
        if panel_id not in self._titles or panel_id in self._hidden:
            return
        floating = getattr(self.server.state, "ui_floating_views", None) or ()
        if panel_id not in floating:
            self._tab_places[panel_id] = self._tab_place(panel_id)
        self._hidden.add(panel_id)
        self.remove_panel(panel_id)
        if self._active_panel_id == panel_id:
            shown = [p for p in self._pv_internal if p not in self._hidden]
            others = [p for p in self._titles if p not in self._hidden]
            self._set_active(next(iter(shown), None) or next(iter(others), None))
        self._publish_render_panels()

    def show_panel(self, panel_id):
        """A hidden 3D view back in the dock, where it was, and active."""
        if panel_id not in self._hidden or panel_id not in self._titles:
            return
        self._hidden.discard(panel_id)
        present = [p for p in self._titles if p not in self._hidden and p != panel_id]
        self.add_panel(panel_id, self._titles.get(panel_id, panel_id), f"{panel_id}_template",
                       **self._anchor_place(panel_id, present))
        self._set_active(panel_id)
        self._publish_render_panels()

    def focus_panel(self, panel_id):
        """`panel_id` the active view, its tab in front: shown again first
        when hidden."""
        if panel_id not in self._titles:
            return
        if panel_id in self._hidden:
            self.show_panel(panel_id)
            return
        self._set_active(panel_id)
        try:
            self.active_panel(panel_id)
        except Exception as exc:
            print(f"[fespp] view {panel_id}: its tab not brought to the front ({exc})", flush=True)

    def detach_panel(self, panel_id, room_w, room_h, left=None, top=None):
        """`panel_id` floating over the others, at a size to work in: centred
        in the dock, or its top left corner at (`left`, `top`) in the dock,
        kept inside it. A view already floating keeps the tabs it left."""
        floating = getattr(self.server.state, "ui_floating_views", None) or ()
        if panel_id not in floating:
            self._tab_places[panel_id] = self._tab_place(panel_id)
        room_w, room_h = int(room_w), int(room_h)
        width, height = int(room_w * 0.6), int(room_h * 0.6)
        if left is None or top is None:
            left, top = (room_w - width) // 2, (room_h - height) // 2
        else:
            left = max(0, min(int(left), room_w - width))
            top = max(0, min(int(top), room_h - height))
        self._put_back(panel_id, floating={"position": {"left": left, "top": top},
                                           "width": width, "height": height})

    def anchor_panel(self, panel_id):
        """`panel_id` back in the dock: among the tabs it left while one of them
        is there, else where its kind opens. In a window filling the dock, the
        window lets go first, and only the view that detached it is anchored."""
        if self.fill.owner:
            self.fill.leave(anchor=panel_id if panel_id == self.fill.owner else None)
        else:
            self._put_back(panel_id, **self._anchor_place(panel_id))

    def _anchor_place(self, panel_id, among=None):
        before, after = self._tab_places.pop(panel_id, None) or ((), ())
        floating = getattr(self.server.state, "ui_floating_views", None) or ()
        still = [p for p in (*before, *after) if p in self._titles and p not in floating
                 and (among is None or p in among)]
        if still:
            index = sum(p in still for p in before)
            return {"position": {"direction": "within", "referencePanel": still[0], "index": index}}
        return self._place_of_kind(panel_id, among)

    def _place_of_kind(self, panel_id, among=None):
        """Where `panel_id` goes in the dock with no other place to go to, as
        `add_panel` arguments. `among`: the panels the dock holds by then, when
        others are still on their way (a reference to one of those is refused)."""
        spec = VIEW_KINDS.get(self._kinds.get(panel_id)) or {}
        beside = getattr(self.server.state, "fespp_last_render_panel_id", "") or None
        floating = getattr(self.server.state, "ui_floating_views", None) or ()
        docked = [p for p in self._titles if p != panel_id and p not in floating
                  and (among is None or p in among)]
        if spec.get("anchored"):
            return {"position": {"direction": spec["anchored"]}, "initialHeight": spec.get("height")}
        if beside in docked:
            return {"position": {"direction": "right", "referencePanel": beside}}
        if docked:
            return {"position": {"direction": "within", "referencePanel": docked[0]}}
        return {"position": {"direction": "right"}}

    def in_order(self, *calls):
        """Calls on the dock, each `(method, *args)`, in one message: two messages
        may overtake each other on their way to the browser."""
        self.server.protocol.push_actions(
            [{"type": "method", "ref": _DOCK_REF, "method": method, "args": list(args)}
             for method, *args in calls])

    def come_back(self, layout, anchor=None):
        """The dock as `layout` has it; the panels it does not know where their
        kind opens, `anchor` where it left the dock; each placed against the
        panels the dock holds when it comes, not those added after it."""
        self._keep_layout(layout)
        present = set(self._layout_panel_ids(layout))
        calls = [("restoreLayout", layout)]
        for pid in self.panel_ids():
            if pid in present or pid in self._hidden:
                continue
            place = (self._anchor_place(pid, present) if pid == anchor
                     else self._place_of_kind(pid, present))
            calls.append(("addPanel", pid, self._titles[pid], f"{pid}_template", place))
            present.add(pid)
        if self._active_panel_id:
            calls.append(("activePanel", self._active_panel_id))
        self.in_order(*calls)

    def _on_ready(self):
        # Adding panels only takes effect once the dockview is MOUNTED client-side
        # (this event). First load: create the default view. Reload: the client
        # re-mounts empty — put the panels back WHERE THEY WERE from the last
        # layout dockview reported, then re-attach any panel that layout does
        # not know (opened after the last report), as a tab.
        if self._titles:
            placed = set()
            if self._layout:
                known = set(self._layout_panel_ids(self._layout))
                if known and known <= set(self._titles):
                    try:
                        self.restore_layout(self._layout)
                        placed = known
                    except Exception:
                        placed = set()
            for pid in list(self._titles):
                if pid in placed or pid in self._hidden:
                    continue
                try:
                    self.add_panel(pid, self._titles.get(pid, pid),
                                   f"{pid}_template")
                except Exception:
                    pass
            self._set_active(self._active_panel_id or next(iter(self._titles), None))
        else:
            self.add_view()

    @staticmethod
    def _layout_panel_ids(layout):
        """The panel ids a dockview layout names (`toJSON().panels`)."""
        try:
            return list((layout.get("panels") or {}).keys())
        except Exception:
            return []

    @contextmanager
    def placed(self, direction, reference_panel_id=None):
        """Within the block, a panel opened by a door that gives no place
        is split `direction` ("right" or "below") of `reference_panel_id`
        (else the active panel) instead of opening as a tab.

        A session document says where its panels go (`place`, "3D view on
        the left, Statistics on the right"); the doors — open_compare,
        open_welllog... — do not, and they keep their signatures. A
        panel already open stays where it is."""
        self._place = ((direction, reference_panel_id)
                       if direction in ("right", "below") else None)
        try:
            yield
        finally:
            self._place = None

    def add_view(self, direction=None, kind=DEFAULT_KIND, reference_panel_id=None):
        """Open a panel of `kind` and return its id.

        `direction` ("right" or "below") splits `reference_panel_id`, else
        the active panel; without one the panel opens as a tab — or where
        the `placed` block it runs in says. A singleton kind already open
        is brought to the front instead."""
        spec = VIEW_KINDS.get(kind) or VIEW_KINDS[DEFAULT_KIND]
        # singleton kinds (e.g. compare): focus the existing one instead of a 2nd.
        if spec.get("singleton"):
            existing = next((pid for pid, k in self._kinds.items() if k == kind), None)
            if existing is not None:
                self._set_active(existing)
                # and its dockview tab comes to the front: left behind
                # another tab, the toolbar button would seem to do nothing
                try:
                    self.active_panel(existing)
                except Exception:
                    pass
                return existing
        if direction is None and self._place:
            direction, reference_panel_id = self._place
        self._view_count += 1
        panel_id = f"view_{self._view_count}"
        # A SINGLETON wears its plain name: "Statistics 3" on the only
        # statistics panel of the session numbers something the reader
        # cannot count. A kind that may be opened twice keeps a number, the
        # lowest one no open panel of the kind wears, so its tabs are told
        # apart and the numbers stay small.
        label = spec.get("label", "3D view")
        taken = {self._numbers.get(pid) for pid, k in self._kinds.items() if k == kind}
        number = 1
        while number in taken:
            number += 1
        title = label if spec.get("singleton") else f"{label} {number}"
        template_name = f"{panel_id}_template"
        self._titles[panel_id] = title
        self._kinds[panel_id] = kind
        self._numbers[panel_id] = number

        # render kinds get a ParaView view + per-view scene/state; a bare
        # kind the view alone, for what its panel draws itself; others nothing.
        pv_view = None
        bare = spec.get("render_view") == "bare"
        if spec.get("needs_render_view") or bare:
            ctx = self.server.context
            if (not bare and not self._first_adopted
                    and getattr(ctx, "render_view", None) is not None):
                pv_view = ctx.render_view  # adopt the engine's pre-created view
                self._first_adopted = True
            else:
                pv_view = pvsimple.CreateRenderView()
                pv_view.MakeRenderWindowInteractor(True)
            # the classic orientation axes, bottom left (boot names them after
            # the data's CRS): the top right is the Legends overlay's
            pv_view.OrientationAxesVisibility = 1
            (self._pv_bare if bare else self._pv_internal)[panel_id] = pv_view
            _tune_lod(pv_view, _say_render_backend(pv_view))
            # the wheel stops at the face of the data instead of flying
            # through it. Kept on the manager because VTK holds no reference
            # to a Python callable: dropped here, the observers would be
            # collected and the wall would silently stop existing.
            wall = install_wheel_wall(panel_id, pv_view, self.server.state)
            if wall is not None:
                self._wheel_walls[panel_id] = wall
            # the hands on this camera: what the server can put off waits for them
            watch = install_activity_watch(panel_id, pv_view)
            if watch is not None:
                self._camera_watch[panel_id] = watch
            # the view's colour tables and clone (engine/view_resources):
            # the data's views only
            vr = getattr(ctx, "view_resources", None)
            if vr is not None and not bare:
                vr.add_view(panel_id, pv_view)

        with DivLayout(self.server, template_name) as ui:
            ui.root.style = "height:100%; width:100%; position:relative;"
            view_wait(self.server, panel_id)
            content = spec["build"](self.server, panel_id, pv_view)
        html_view = getattr(content, "html_view", None)
        if html_view is not None:
            self._html_views[panel_id] = html_view

        # per-view state vars + handlers (visibility/colour) for render
        # views; a bare view gets its state and its axes, nothing of the data.
        if pv_view is not None:
            wire = (self.server.controller.wire_bare_view if bare
                    else self.server.controller.wire_view)
            if wire.exists():
                wire(panel_id, pv_view, kind)
            # a kind marked `inherit_eyes` starts with the eyes of the view it
            # was split from (boot.inherit_eyes)
            inherit = self.server.controller.inherit_eyes
            if spec.get("inherit_eyes") and reference_panel_id and inherit.exists():
                try:
                    inherit(panel_id, reference_panel_id)
                except Exception:
                    pass

        # split relative to the view that asked (the adder's own view), else the
        # active panel; else a plain tab.
        ref = reference_panel_id or self._active_panel_id
        if self.fill.owner:
            # under the window filling the dock it would be out of reach
            self.add_panel(panel_id, title, template_name,
                           position={"direction": "within", "referencePanel": self.fill.owner})
        elif spec.get("anchored"):
            # against the layout itself: along its whole edge
            self.add_panel(panel_id, title, template_name, position={"direction": spec["anchored"]},
                           initialHeight=spec.get("height"))
        elif direction in ("right", "below") and ref:
            self.add_panel(panel_id, title, template_name,
                           position={"direction": direction, "referencePanel": ref})
        else:
            self.add_panel(panel_id, title, template_name)
        self._set_active(panel_id)

        self._publish_render_panels()
        # frame the new render panel on whatever is already loaded, then push
        # (a kind marked `frames_itself` did its own framing in wire_view; a
        # bare view is framed on the velocity model it draws, by time_depth_view).
        if pv_view is not None:
            try:
                if (self.server.state.ui_loaded_rep_paths
                        and not spec.get("frames_itself") and not bare):
                    from fespp_on_trame.app.views.camera import reset_camera_centered
                    reset_camera_centered(pv_view)
                pvsimple.Render(view=pv_view)
                if html_view is not None:
                    html_view.update()
            except Exception:
                pass
        return panel_id

    def _on_view_closed(self, panel_id):
        self._on_screen.discard(panel_id)
        if panel_id in self._hidden:
            return      # hidden, not closed: it comes back with `show_panel`
        if panel_id in self._moving:
            self.add_panel(panel_id, self._titles.get(panel_id, panel_id), f"{panel_id}_template",
                           **self._moving.pop(panel_id))
            self._set_active(panel_id)
            return
        self._tab_places.pop(panel_id, None)
        ctx = self.server.context
        # let boot tear down the per-panel state bound to this id (cross-plot
        # pins, the Statistics view's registration) so nothing keeps recomputing
        # for a panel that is gone.
        cb = self.server.controller.on_panel_closed
        if cb.exists():
            try:
                cb(panel_id)
            except Exception:
                pass
        vr = getattr(ctx, "view_resources", None)
        if vr is not None and panel_id in self._pv_internal:
            vr.remove_view(panel_id)
        # blockscope: release this view's composite rep before its pv_view dies.
        scenes = getattr(ctx, "blockscope_scenes", None)
        if scenes is not None:
            scene = scenes.pop(panel_id, None)
            if scene is not None:
                try:
                    scene.release()
                except Exception:
                    pass
        pv_view = self._pv_internal.pop(panel_id, None)
        if pv_view is None:
            pv_view = self._pv_bare.pop(panel_id, None)
        self._html_views.pop(panel_id, None)
        self._titles.pop(panel_id, None)
        self._kinds.pop(panel_id, None)
        self._numbers.pop(panel_id, None)
        self.fill.panel_closed(panel_id)
        self._wheel_walls.pop(panel_id, None)
        self._camera_watch.pop(panel_id, None)
        if self.server.state.fespp_last_render_panel_id == panel_id:
            self.server.state.fespp_last_render_panel_id = ""
        # drop the closed view from every camera-link group — a future view
        # must not inherit a stale link set through a recycled id.
        self.drop_links_for(panel_id)
        self._publish_render_panels()
        # symmetric per-view state teardown: marks the vid dead (guards the
        # never-unregistered per-view handlers), nulls the suffixed vars and
        # pops every *_by_view bucket (per_view_state.DICT_BUCKETS).
        per_view_state.teardown(self.server.state, panel_id)
        if pv_view is not None:
            try:
                pvsimple.Delete(pv_view)
            except Exception:
                pass
        if self._active_panel_id == panel_id:
            self._set_active(next(iter(self._pv_internal), None)
                             or next(iter(self._titles), None))

    def _publish_render_panels(self):
        """{id, title, globe} of every render view — the camera-link card's
        checklist (widgets/view_link_menu.py) renders from this. `globe`
        marks the Globe view (ECEF camera): the lists of views to link or
        copy from leave it out."""
        state = self.server.state
        # the kinds open: their buttons of the top bar say so
        self.server.state.ui_open_view_kinds = sorted(set(self._kinds.values()))
        self.server.state.fespp_render_panels = [
            {"id": pid, "title": self._titles.get(pid, pid),
             "globe": self._kinds.get(pid) == "globe", "hidden": pid in self._hidden}
            for pid in self._pv_internal
        ]
        # the camera-link card's list: the data's views, then the views
        # drawing one thing on their own (the Stratigraphy panel's 3D)
        state.fespp_link_panels = list(state.fespp_render_panels) + [
            {"id": pid, "title": f"{self._titles.get(pid, pid)} · model 3D"}
            for pid in self._pv_bare]

    def publish_render_panels(self):
        """Republish the render views' list (see `_publish_render_panels`)."""
        self._publish_render_panels()

    def drop_links_for(self, panel_id):
        """Remove `panel_id` from every camera-link group (a view closed)."""
        links = {k: list(v) for k, v in
                 (self.server.state.view_links or {}).items()}
        if not links:
            return
        links.pop(panel_id, None)
        for k in list(links.keys()):
            if panel_id in links[k]:
                links[k] = [p for p in links[k] if p != panel_id]
            if not links[k]:
                links.pop(k)
        self.server.state.view_links = links
        # now, not at the next flush: a closing view's proxy goes right after
        self._apply_camera_links()

    def _apply_camera_links(self):
        """ParaView's own camera links, one per linked pair of
        `state.view_links`: the linked view follows every frame of a drag,
        a wheel burst or a camera flight, as in ParaView (the manager and
        the PO, 16/10: the views followed only on the mouse release). A link
        renders its other view at each render of the first (measured: one
        render per render) and carries the position, focal point, view up,
        view angle, parallel projection and scale and the CenterOfRotation;
        ParaView web pushes the image of every view whose camera moved
        while a gesture lasts. A Globe view never takes part: an ECEF camera
        and a local-CRS one must not cross. Called on every change of
        `view_links`, and at once when a view leaves them."""
        state = self.server.state
        want = set()
        for a, others in (state.view_links or {}).items():
            for b in others or []:
                if a == b or self.get_pv_view(a) is None or self.get_pv_view(b) is None:
                    continue
                if "globe" in (self._kinds.get(a), self._kinds.get(b)):
                    continue
                want.add(tuple(sorted((a, b))))
        for pair in [p for p in self._camera_links if p not in want]:
            name = self._camera_links.pop(pair)
            try:
                pvsimple.RemoveCameraLink(name)
                print(f"[fespp] camera link {pair[0]} <-> {pair[1]}: removed", flush=True)
            except Exception as exc:
                print(f"[fespp] camera link {name}: not removed: {exc}", flush=True)
        for pair in sorted(want - set(self._camera_links)):
            name = f"fespp_camera_link_{pair[0]}_{pair[1]}"
            try:
                pvsimple.AddCameraLink(self.get_pv_view(pair[0]),
                                       self.get_pv_view(pair[1]), name)
                self._camera_links[pair] = name
                print(f"[fespp] camera link {pair[0]} <-> {pair[1]}: ParaView's own",
                      flush=True)
            except Exception as exc:
                print(f"[fespp] camera link {name}: not created: {exc}", flush=True)

    def apply_camera_links(self):
        """`_apply_camera_links`, for the engine: the Link cameras card's
        tick takes effect at once, not at the next state flush."""
        self._apply_camera_links()

    def _sync_camera_from(self, panel_id, *_args, **_kwargs):
        """Copy the camera of `panel_id`'s view to every view linked to it
        (`state.view_links[panel_id]`) and push a fresh image of each.

        ParaView's camera links (`_apply_camera_links`) carry the camera
        during a gesture; this runs on the mouse RELEASE (each VtkRemoteView's
        vtk.js EndAnimation) because the linked view's last render of the
        gesture is pushed by nothing else, and after a camera move made by
        code (navigation buttons, flights), whose properties the link only
        carries at the next render of the moved view. CenterOfRotation is
        part of the copy: vtk.js orbits around it, not the focal point."""
        if self.get_pv_view(panel_id) is None:
            return
        state = self.server.state
        # an ECEF camera and a local-CRS camera never cross
        if self._kinds.get(panel_id) == "globe":
            return
        links = (state.view_links or {}).get(panel_id, [])
        if not links:
            return
        for pid in links:
            if pid == panel_id or self._kinds.get(pid) == "globe":
                continue
            self.copy_camera(panel_id, pid)

    def copy_camera(self, from_panel_id, to_panel_id):
        """The camera of one 3D view onto another, once, and a fresh image
        of the target: what a camera link does on every mouse release, and
        what a second view takes on opening so it starts where its
        reference stands. CenterOfRotation is part of the copy: vtk.js
        orbits around it, not around the focal point."""
        src_view = self.get_pv_view(from_panel_id)
        view = self.get_pv_view(to_panel_id)
        if src_view is None or view is None or src_view is view:
            return
        try:
            copy_camera_properties(src_view, view)
            # the target's Navigation card says the projection it now has
            self.server.state[f"ui_nav_parallel__{to_panel_id}"] = bool(
                getattr(view, "CameraParallelProjection", 0))
            # html.update() already renders (StillRenderToString): an
            # explicit Render first would double the cost. A bare Render
            # only when no client view exists.
            html = self._html_views.get(to_panel_id)
            if html is not None:
                html.update()
            else:
                pvsimple.Render(view=view)
        except Exception:
            pass

    def _on_view_activated(self, panel_id):
        self._set_active(panel_id)

    def _set_active(self, panel_id):
        self._active_panel_id = panel_id
        self.server.state.fespp_active_panel_id = panel_id or ""
        pv_view = self._pv_internal.get(panel_id) if panel_id else None
        if pv_view is not None:
            # the 3D view a colour or an eye set is routed to while a panel
            # of another kind has the focus (view_routing.resolve_active_render_panel)
            self.server.state.fespp_last_render_panel_id = panel_id
            try:
                pvsimple.SetActiveView(pv_view)
            except Exception:
                pass
