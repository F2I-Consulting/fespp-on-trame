"""View-kind registry — the ONE place to add a new kind of dockview panel.

Each kind = an entry in ``VIEW_KINDS``:
    label              tab-title prefix / shown in the add-view UI
    needs_render_view  True  -> the manager creates a ParaView RenderView and
                               registers a per-view scene + state; the builder
                               gets that pv_view and must expose ``.html_view``.
                       False -> a non-3D panel (well log, statistics…):
                               no pv_view, no scene; the builder just renders.
    build(server, view_id, pv_view) -> the panel content object. A render kind
                               returns its ``ViewPanel`` (carries ``.html_view``).
    singleton          optional; True -> at most one panel of the kind, a second
                               open brings the existing one to the front.
    inherit_eyes       optional (render kinds); True -> a panel split from
                               another starts with that view's eyes.
    frames_itself      optional (render kinds); True -> the manager does not
                               frame the new view on the loaded data.
    render_view        optional; "bare" -> the manager makes a RenderView for
                               the panel too, wired bare (no scene, no eyes,
                               no tools), for what the panel draws on its
                               own; the builder gets that pv_view and
                               exposes ``.html_view`` like a render kind.

To add a kind: append an entry + write its builder. The view manager (view_manager.py) never changes."""
from fespp_on_trame.app.views.view_panel import ViewPanel


def _build_render(server, view_id, pv_view):
    # the "render" kind = a 3D ViewPanel (vertical toolbar + render + tool cards)
    return ViewPanel(server, view_id, pv_view)


def _build_globe(server, view_id, pv_view):
    # the "globe" kind = the same panel, with the tools the Earth serves
    return ViewPanel(server, view_id, pv_view, kind="globe")


def _build_welllog(server, view_id, pv_view):
    # the "welllog" kind = the trame-welllog correlation panel (D3)
    from fespp_on_trame.app.views.welllog_panel import WellLogPanel
    return WellLogPanel(server, view_id)


def _build_xml(server, view_id, pv_view):
    # the "xml" kind = the RESQML object explorer (tabs + reference walking)
    from fespp_on_trame.app.views.xml_panel import XmlPanel
    return XmlPanel(server, view_id)


def _build_values(server, view_id, pv_view):
    from fespp_on_trame.app.views.values_panel import ValuesPanel
    return ValuesPanel(server, view_id)


def _build_time_depth(server, view_id, pv_view):
    from fespp_on_trame.app.views.time_depth_panel import TimeDepthPanel
    return TimeDepthPanel(server, view_id)


def _build_stratigraphy(server, view_id, pv_view):
    # the "stratigraphy" kind = the stratigraphic column chart
    from fespp_on_trame.app.views.stratigraphy_panel import StratigraphyPanel
    return StratigraphyPanel(server, view_id, pv_view)


def _build_calculator(server, view_id, pv_view):
    # the "calculator" kind = derived-property recipes (engine/derived_props)
    from fespp_on_trame.app.views.calculator_panel import CalculatorPanel
    return CalculatorPanel(server, view_id)


def _build_reconcile(server, view_id, pv_view):
    # the "reconcile" kind = logs against the grid, by property kind
    from fespp_on_trame.app.views.reconcile_panel import ReconcilePanel
    return ReconcilePanel(server, view_id)


def _build_health(server, view_id, pv_view):
    # the "health" kind = what is wrong with the loaded data, in one table
    from fespp_on_trame.app.views.health_panel import HealthPanel
    return HealthPanel(server, view_id)


def _build_assistant(server, view_id, pv_view):
    # the "assistant" kind = the application asked in plain words, one
    # command per sentence (widgets/assistant + app/assistant_host)
    from fespp_on_trame.app.views.assistant_panel import AssistantPanel
    return AssistantPanel(server, view_id)


def _build_compare(server, view_id, pv_view):
    # the "compare" kind = the Statistics view: one selection of properties,
    # read as a matrix, overlaid distributions or a multi-Y cross-plot
    from fespp_on_trame.app.views.compare_view_panel import CompareViewPanel
    return CompareViewPanel(server, view_id)


VIEW_KINDS = {
    "render": {
        # the word of the toolbar button ("New 3D view") and of every text
        # that names one: the 2D mode of the camera card is a mode of the
        # same view, not another kind
        "label": "3D view",
        "needs_render_view": True,
        "build": _build_render,
    },
    "globe": {
        "label": "Globe",
        # the loaded data projected onto the Earth (engine/blockscope/
        # globe_scene), its scene built one turn after the view; opened from
        # the top bar beside the 3D view in use (view_doors.open_globe), its
        # camera linked to none
        "needs_render_view": True,
        "singleton": True,
        "inherit_eyes": True,
        "frames_itself": True,
        "build": _build_globe,
    },
    # A kind plugs in here without touching the manager. Each is opened from
    # its OWN door — a top-bar button, a right-click action, another panel's
    # button — which calls controller.add_view(kind=..., ...); there is no
    # global add-menu. A 3D view opens beside the current one, with its eyes
    # and its camera (boot.open_render_view).
    "welllog": {
        "label": "Well log",
        "needs_render_view": False,
        # ONE panel for every well: correlation IS the comparison, so a second
        # panel would defeat it. Opened from the layout toolbar; which wells it
        # holds is chosen in the panel's own well tree.
        "singleton": True,
        "build": _build_welllog,
    },
    "reconcile": {
        "label": "Log ↔ Grid",
        "needs_render_view": False,
        # ONE table for the session: it reads the log view's wells and the
        # loaded grid properties, both session-wide. Opened from the layout
        # toolbar (controller.open_reconcile).
        "singleton": True,
        "build": _build_reconcile,
    },
    "health": {
        "label": "Data health",
        "needs_render_view": False,
        # ONE table for the session: it reads everything loaded. Opened from
        # the layout toolbar (controller.open_health), re-read on each load.
        "singleton": True,
        "build": _build_health,
    },
    "xml": {
        "label": "Explorer",
        "needs_render_view": False,
        # ONE panel (the PO, 02/11): a reference followed from an
        # Attributes card or a row opens as a new TAB of it, and the
        # button brings it to the front — the tabs are the branches of the
        # exploration (app/features/xml_explorer).
        "singleton": True,
        "build": _build_xml,
    },
    "values": {
        "label": "Values",
        "needs_render_view": False,
        # ONE for the session: it reads the 3D view last worked in
        "singleton": True,
        "build": _build_values,
    },
    "timedepth": {
        "label": "Time-depth model",
        "needs_render_view": False,
        # ONE for the session, along the whole bottom of the layout
        "singleton": True,
        "anchored": "below",
        "height": 380,
        "build": _build_time_depth,
    },
    "stratigraphy": {
        "label": "Stratigraphy",
        "needs_render_view": False,
        # ONE panel (the PO, 02/11): the column's ranks are picked in it. A
        # panel, not a card of the 3D view: the data is session-wide and
        # the chart never touches the scene (the time-depth model, which
        # does, is a card of the 3D view since 03/11).
        "singleton": True,
        "build": _build_stratigraphy,
    },
    "calculator": {
        "label": "Calculator",
        "needs_render_view": False,
        # singleton: ONE panel manages every grid via its grid select.
        # Spawned by the tree's right-click "Derived property".
        "singleton": True,
        "build": _build_calculator,
    },
    "compare": {
        "label": "Statistics",
        "needs_render_view": False,
        # ONE selection for the session, one tab per PWLS kind, each showing
        # at once its matrix, its overlaid distributions and the cross-plot of
        # two of its rows; the selection outlives a close. Two doors: the
        # layout toolbar (controller.open_compare) and "Stats" in a data tree
        # (controller.add_to_stats, which adds the property first). Otherwise
        # the properties are picked in the view's own docked tree.
        "singleton": True,
        "build": _build_compare,
    },
    "assistant": {
        "label": "Assistant",
        "needs_render_view": False,
        # ONE conversation for the session: it speaks of everything loaded
        # and acts on the 3D view last worked in. Opened from the layout
        # toolbar (controller.open_assistant); the conversation outlives a
        # close and is not saved in a session file.
        "singleton": True,
        "build": _build_assistant,
    },
}

DEFAULT_KIND = "render"
