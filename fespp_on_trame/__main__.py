r"""Entry point: ``python -m fespp_on_trame``.

    pvpython -m fespp_on_trame \
        --fespp-plugin-path <...>/Fespp.dll \
        [--local-epc-file-path <...>.epc] \
        --server --port <port> --timeout 0

In the container the launcher runs ``pvpython /deploy/fespp_on_trame``
(directory mode): trame then lives in the PV_VENV virtual environment, which
only the ``paraview.web.venv`` import makes visible. Without PV_VENV (a local
run) that import does nothing.
"""
import importlib

importlib.import_module("paraview.web.venv")

import io as _io
import os as _os
import sys as _sys

# sys.stdout / sys.stderr written straight to the process's file descriptors
# 1 and 2, line by line. pvpython replaces both with a
# vtkPythonStdStreamCaptureHelper which, from ParaView 6.1 (VTK 9.6), holds
# every write until the process ends, flush() or not, trame's "App running
# at" line included. The wslink launcher waits for that line on the session's
# stdout (its ready_line, within a timeout): held back, it never arrives in
# time, the session is declared dead and the browser gets a 503. The
# descriptors are what the launcher and the session log read; VTK's own C++
# output still goes to fd 2 (tee'd by engine/vtk_log).
for _name, _fd in (("stdout", 1), ("stderr", 2)):
    if type(getattr(_sys, _name)).__name__ == "vtkPythonStdStreamCaptureHelper":
        setattr(_sys, _name, _io.TextIOWrapper(
            _io.FileIO(_fd, "w", closefd=False), encoding="utf-8",
            errors="backslashreplace", line_buffering=True))
# paraview.web.venv printed this through the capture helper, which holds it:
# say it again on the real stdout
if _os.environ.get("PV_VENV"):
    print("[fespp] Python venv:", _os.environ["PV_VENV"])

# FESPP_STRICT: report the exceptions that the application's silent handlers
# swallow. Armed FIRST, before anything else is imported, so that it also
# sees a failure during boot. Off unless the variable is set; see
# engine/strict.py.
from fespp_on_trame.engine import strict as _strict

_strict.install()

from trame.app import get_server
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import client as trame_client
from trame.widgets import html
from trame.widgets import vuetify3 as v3

from fespp_on_trame.app.boot import boot_engine
from fespp_on_trame.app.features import osdu_etp
from fespp_on_trame.app.views import about
from fespp_on_trame.app.views.view_manager import MultiView
from trame_fespp_icon.widgets import FpIcon
from trame_fespp_newview.widgets import NewViewDialog, ViewsDoor
from trame_fespp_upload.widgets.upload_data import UploadData, UploadFile, UploadOsdu
from trame_fespp_session.widgets import LeaveGuard, SessionDoor


def _enable_vtk_threads():
    """Let VTK's filters use the machine's cores.

    A stock ParaView superbuild compiles both the Sequential and the STDThread
    backends of ``vtkSMPTools`` but defaults to Sequential, where every filter
    runs on ONE thread whatever the machine has. build.bash makes STDThread
    the compiled default; this call selects it for an image built otherwise.

    The gain is SELECTIVE: filters that go through vtkSMPTools
    (``vtkThreshold``, ``vtkWarpScalar``) run several times faster, while
    ``vtkContourFilter`` does not use it and is unchanged. So the Thresholds
    card gains and the contours do not, and the speed-up stays well below the
    core count: the threads share one memory bus.

    Nothing silent: the backend actually in use is printed once, whichever it
    is. ``FESPP_VTK_THREADS=0`` keeps the single thread, the baseline to
    compare a multi-threaded run against.
    """
    import os
    if os.environ.get("FESPP_VTK_THREADS", "") == "0":
        print("[fespp] VTK filters: one thread (FESPP_VTK_THREADS=0)", flush=True)
        return
    try:
        from vtkmodules.vtkCommonCore import vtkSMPTools
    except Exception as exc:
        print("[fespp] VTK filters: no vtkSMPTools —", exc, flush=True)
        return
    vtkSMPTools.SetBackend("STDThread")
    print(f"[fespp] VTK filters: {vtkSMPTools.GetBackend()},"
          f" {vtkSMPTools.GetEstimatedNumberOfThreads()} thread(s)", flush=True)


def main():
    """Boot the engine, enable every widget bundle, build the page and serve it."""
    _enable_vtk_threads()
    server = get_server(client_type="vue3")
    server.cli.add_argument("--fespp-plugin-path", required=True)
    server.cli.add_argument("--local-epc-file-path", default=None)
    args = server.cli.parse_known_args()[0]

    boot_engine(server, fespp_plugin_path=args.fespp_plugin_path)

    # The per-view widgets are created LAZILY (a dockview panel is added at
    # runtime via the `ready` event / the "+" button), so their JS modules must
    # be enabled NOW — before server.start — or the client never receives their
    # bundles and <view-toolbar> / <data-explorer-tree> / <floating-card> /
    # <attributes-panel> render blank inside the panel.
    from trame_fespp_view_tools import module as _vt_module
    from trame_fespp_view_card import module as _vc_module
    from trame_fespp_tree import module as _tree_module
    from trame_fespp_attributes import module as _attr_module
    from trame_fespp_slicers import module as _slicers_module
    from trame_fespp_thresholds import module as _thr_module
    from trame_fespp_colormap import module as _cmap_module
    from trame_fespp_timereal import module as _timereal_module
    # Kitware's colour/opacity node graph (the Colormap card's editor).
    from trame_color_opacity_editor import module as _coe_module
    # trame_plotly powers the charts of the Statistics view (a lazy panel): enabled
    # eagerly so that its JS bundle is in the initial client payload before
    # the panel mounts.
    from trame_plotly import module as _plotly_module
    # trame_welllog powers the Well log correlation view (a lazy panel), same
    # eager rule: enabling it when its panel opens is too late, the client
    # never gets the bundle and the panel comes up blank.
    from trame_welllog import module as _welllog_module
    # trame_fespp_navigation is a per-view TOOL CARD: the first view is built
    # after the client mounts, so enabling it on instantiation is already too
    # late for the initial payload: same eager rule as the panels above.
    from trame_fespp_navigation import module as _nav_module
    # the cross-plot, calculator and stratigraphy panels: lazy panels again,
    # same eager rule, their bundles must be in the initial payload
    from trame_fespp_calculator import module as _calc_module
    from trame_fespp_crossplot import module as _xplot_module
    from trame_fespp_stratigraphy import module as _strati_module
    # trame_fespp_xmlviewer is mounted BOTH by the Attributes card (a tool
    # card, built after the client mounts) and by the XML explorer (a lazy
    # panel): eager for both reasons at once.
    from trame_fespp_xmlviewer import module as _xmlview_module
    # the Log ↔ Grid table: a lazy panel, same eager rule
    from trame_fespp_reconcile import module as _reconcile_module
    from trame_fespp_health import module as _health_module
    # trame_fespp_volumetrics is a per-view TOOL CARD (same eager rule as
    # the navigation card)
    from trame_fespp_volumetrics import module as _volumetrics_module
    # the Statistics view: a lazy panel, same eager rule
    from trame_fespp_compare import module as _compare_module
    # two per-view TOOL CARDS (same eager rule as the navigation card)
    from trame_fespp_globe import module as _globe_module
    from trame_fespp_camlink import module as _camlink_module
    # the camera strip of every 3D view's title bar
    from trame_fespp_title3dview import module as _title3d_module
    # the "New 3D view" dialog: empty, or a copy of an open view
    from trame_fespp_newview import module as _newview_module
    # the Session door: save the state to a .fespp.json file, open one
    from trame_fespp_session import module as _session_module
    # the Assistant: a lazy panel, same eager rule. Not offered yet: None
    # unless FESPP_ASSISTANT=1 (app/core/previews) and its package is there,
    # and then it has no door. The start line of the log says which.
    _assistant_module = _assistant_bundle()
    # in the page from the start: what the layout builds before anyone
    # opens anything (the tree, the doors, the 3D view's cards)
    _modules = [_vt_module, _vc_module, _tree_module, _attr_module,
                _slicers_module, _thr_module, _cmap_module, _coe_module,
                _timereal_module, _nav_module, _volumetrics_module,
                _globe_module, _camlink_module, _title3d_module,
                _newview_module, _session_module]
    for _m in _modules:
        server.enable_module(_m)
    # loaded by the browser at the first opening of their view, each tag an
    # async component (app/core/lazy_modules; measured 21/10: Plotly alone
    # ran 375 ms of JavaScript before the page showed, for no chart)
    from fespp_on_trame.app.core import lazy_modules as _lazy_modules
    _lazy = [(_plotly_module, ["trame-plotly"]),
             (_welllog_module, ["well-log-correlation", "well-log-zones"]),
             (_calc_module, ["calculator-panel"]),
             (_xplot_module, ["crossplot-controls"]),
             # the time-depth model's card of the 3D view: loaded at its
             # first render, the bundle of the column
             (_strati_module, ["stratigraphic-column", "time-depth-law"]),
             (_xmlview_module, ["xml-viewer"]),
             (_reconcile_module, ["reconcile-panel"]),
             (_health_module, ["health-panel"]),
             (_compare_module, ["compare-panel"])]
    if _assistant_module is not None:
        _lazy.append((_assistant_module, ["assistant-panel"]))

    # the page that embeds FesTrame talks to it by postMessage (widgets/embed)
    from fespp_on_trame.app.features import session_api as _session_api
    _check_widget_bundles(_modules + _lazy_modules.register(server, _lazy)
                          + _session_api.enable_embed(server))

    # F2I-Consulting charter: the logo's dark blue #00436D as primary, its
    # green #8FC31F as accent, in the Vuetify theme (sliders, buttons, icons)
    # and the app bar; the custom widgets carry the same blue in their CSS.
    f2i_theme = {
        "theme": {
            "defaultTheme": "f2i",
            "themes": {
                "f2i": {
                    "dark": False,
                    "colors": {
                        "primary": "#00436D",
                        "secondary": "#8FC31F",
                        "accent": "#8FC31F",
                        "info": "#1E88E5",
                    },
                },
            },
        },
    }
    # assets/logo.png (the F2I mark), served by trame's local file manager,
    # shown in the app bar.
    from pathlib import Path
    from trame.assets.local import LocalFileManager
    assets = LocalFileManager(str(Path(__file__).resolve().parent / "assets"))
    assets.url("logo", "logo.png")

    with SinglePageLayout(server, vuetify_config=f2i_theme) as layout:
        # the application's name: Fespp with "on Trame" in superscript
        # ("Fespp on Trame" in the tab and the About), as tall as the F2I mark
        # beside it
        layout.title.clear()
        with layout.title:
            with html.A(href="https://github.com/F2I-Consulting/fespp-on-trame",
                        target="_blank", rel="noopener", title="Fespp on Trame on GitHub",
                        style="color: inherit; text-decoration: none;"):
                html.Span("Fespp", style="font-size: 30px; line-height: 34px;"
                                         " letter-spacing: 0.05em; vertical-align: middle;")
                html.Span("on Trame", style="font-size: 14px; line-height: 14px;"
                                           " letter-spacing: 0.03em; margin-left: 2px;"
                                           " vertical-align: 14px;")
        # the app bar stays WHITE with the title, the Z slider and
        # the reload button in the F2I blue; the blue also carries the
        # widgets, the dockview tab rows and the Vuetify primary controls
        layout.title.classes = "text-primary font-weight-bold"
        # its own width: the views' buttons stand right after it
        layout.title.style = "flex: 0 0 auto; margin-right: 16px;"
        # the F2I mark leads to the company's site, in a new tab: the nav
        # icon is a Vuetify button, and a button with an href is a link;
        # target/rel go in as raw attributes (the layout built the element,
        # so raw_attrs= is out of reach): `_attributes` holds them rendered
        layout.icon.href = "https://www.f2i-consulting.com/"
        layout.icon._attributes["target"] = 'target="_blank" rel="noopener" title="F2I-Consulting"'
        with layout.icon:
            v3.VImg(src=assets["logo"], height="34", width="34",
                    classes="ml-2 rounded", style="background:#fff; padding:2px;")
        layout.footer.hide()  # drop the default "Powered by trame" footer
        # the browser tab: the application's name and the F2I mark instead
        # of trame's defaults (trame-client reads both from the state)
        server.state.trame__title = "Fespp on Trame"
        server.state.trame__favicon = assets["logo"]

        # Data import is SESSION-level (a loaded file is shared by every view),
        # so it lives in the layout toolbar, not among the per-view tools. The
        # UploadData shell owns its button and its dialog, which shows the two
        # import sources side by side (this computer | OSDU over ETP).
        with layout.toolbar:
            # the Assistant (widgets/assistant): built before the doors, its
            # own is offered only when it could be built
            assistant_ctl = _wire_assistant(server, _assistant_module is not None)
            assistant_door = ((
                ("mdi-chat-processing-outline", "Assistant",
                 server.controller.open_assistant, None),
            ) if assistant_ctl is not None else ())
            # Session-level panels open from here: their data comes from the
            # loaded files, not from any view or scene object. A panel whose
            # data is not there (no file, no property, no wellbore...) could
            # only show an empty state, so its button is DISABLED with the
            # reason in its tooltip, never a door that opens on nothing
            # (app/views/top_gates, the PO 28/10).
            from fespp_on_trame.app.views.top_gates import gate

            def _top_button(title, click, disabled=False, **props):
                return v3.VBtn(variant="text", color="primary", size="small",
                               title=title, disabled=disabled, click=click, **props)

            server.state.setdefault("ui_open_view_kinds", [])

            def _view_button(icon, title, kind, need, caption=None, opens=None):
                """A view's button: it opens it, and closes it (`view_door`),
                its look saying it is open; `opens` a door of its own, for what
                only opens; `caption` a word under the icon, where the drawing
                alone would say something else."""
                # the tooltip is a JS expression: single-quoted, the titles
                # carry no quote of their own
                off, tip = gate(title, need)
                click = opens or (server.controller.view_door, f"['{kind}']")
                extra = {"active": (f"(ui_open_view_kinds || []).includes('{kind}')",)} if kind else {}
                if not icon.startswith("fespp-"):
                    _top_button(tip, click, off, icon=icon, **extra)
                    return
                # a Vuetify button takes its icon as a PROP, which can only
                # be a NAME: a button that draws an object of the model
                # nests the drawing instead. Monochrome, like the glyphs
                # beside it: a toolbar has no object families to sort.
                with _top_button(tip, click, off, icon=True, **extra):
                    if icon == "fespp-file-health":
                        # objects displayed with no geometry (the store served
                        # empty coordinates): a badge says where to look
                        with v3.VBadge(
                            content=("Object.keys(ui_empty_geometry || {}).length",),
                            model_value=("Object.keys(ui_empty_geometry || {}).length > 0",),
                            color="error",
                            floating=True,
                        ):
                            FpIcon(icon=icon, size=20, mono=True)
                    elif caption:
                        with html.Div(classes="fp-top-cap"):
                            FpIcon(icon=icon, size=20, mono=True)
                            html.Span(caption)
                    else:
                        FpIcon(icon=icon, size=20, mono=True)

            # in the middle, the views of the work
            v3.VSpacer()
            # the 3D views, shown or hidden each, and a new one (widgets/newview)
            ViewsDoor(views=("fespp_render_panels", []), active=("fespp_active_panel_id", ""),
                      activate=(server.controller.view_focus, "[$event]"),
                      toggle=(server.controller.view_hidden_toggle, "[$event]"),
                      add=server.controller.ask_new_render_view)
            from fespp_on_trame.app.core import previews
            for entry in (
                ("fespp-globe", "Globe — what the 3D view in use shows, placed on the Earth",
                 "globe", "crs"),
                ("fespp-values", "Values — what the node active in the 3D view in use holds, its table and its map",
                 "values", None),
                # the Explorer: the objects and the references between
                # them, a drawing of its own, not the 3D view's tree
                # (the PO, 16/10; the letters XML before)
                ("fespp-explorer",
                 "Explorer — browse the RESQML objects and the references between them",
                 "xml", None),
                ("fespp-statistics",
                 "Statistics — count, mean, spread and percentiles of the properties"
                 " you tick, side by side, their distributions and cross-plot",
                 "compare", "properties"),
                ("fespp-calculator", "Calculator — derived properties",
                 "calculator", "properties"),
                ("fespp-stratigraphic-column",
                 "Stratigraphy — the column declared by the loaded data",
                 "stratigraphy", None),
                # T->D alone reads as the view's Depth/Time switch
                ("fespp-time-depth",
                 "Time-depth model — the velocity model that converts time to depth, and back",
                 "timedepth", None, "Model"),
                ("fespp-log-view",
                 "Log view — correlate wellbore logs and markers",
                 "welllog", "wells"),
                ("fespp-log-vs-grid",
                 "Log ↔ Grid — where the model contradicts the logs,"
                 " by property kind, zone by zone",
                 "reconcile", "logs_and_grid"),
            ):
                if previews.offered(entry[2]):
                    _view_button(*entry)
            for icon, title, opens, need in assistant_door:
                _view_button(icon, title, "assistant", need, opens=opens)
            # at the right, what is about the data: import, save, reload,
            # then its health
            v3.VSpacer()
            etp_bindings = osdu_etp.widget_bindings(server.controller)
            UploadData(
                session_id=("upload_session_id", ""),
                accept=".epc,.h5",
                # the files this session has already read. The dialog is
                # rebuilt on every open: without this list it would reopen on
                # an empty drop zone and say nothing of what the session
                # holds, while a file listed as read is one the reader will
                # NOT import a second time.
                loaded_files=("ui_loaded_files", []),
                # an empty session opens the door by itself, once, on mount
                # (UploadData.mounted): there is nothing else to do until
                # something is in, and every panel button says so.
                has_data=("ui_has_data", False),
                # a transfer that never reached the server (network, a 500)
                # is the widget's to report: it lands on the red snackbar
                error="load_error = $event",
                **etp_bindings,
            )
            # the Session door (widgets/session): the state of the whole
            # application to a .fespp.json file, and back; the data itself is
            # loaded again, through the drop zone of its dialog
            from trame_fespp_session.controller import SessionController
            from fespp_on_trame.app.session_host import FesppSessionHost
            session_host = FesppSessionHost(server)
            session_ctl = SessionController(server, session_host)
            # the document as the application's language (app/features/
            # session_api): a document applied, the state as one, the
            # page's query (?epc=, ?uuid=, ?state=) opened at mount
            from fespp_on_trame.app.features import session_api
            session_api.register(server, session_ctl, session_host)
            session_api.mount(server)
            # the session gestures as controllers: the headless scenarios
            # (session_roundtrip) and any other door reach them by name
            server.controller.session_save = session_ctl.save
            server.controller.session_open = session_ctl.open
            server.controller.session_apply = session_ctl.apply
            server.controller.session_reset = session_ctl.reset
            server.controller.session_autosave = session_ctl.autosave_now
            # the autosave follows every change: every render of a view, every
            # load or unload (a pure state change with no render)
            _sch = getattr(server.context, "render_scheduler", None)
            if _sch is not None:
                _sch.add_flush_listener(lambda _vids: session_ctl.touch())

            @server.state.change("selected_paths", "ui_loaded_files")
            def _session_touch(**_):
                session_ctl.touch()
            # the browser's Back asks before a loaded session is left
            LeaveGuard(armed=("ui_has_data", False))
            with SessionDoor(
                has_data=("ui_has_data", False),
                status=(session_ctl.status_var, {}),
                download=(session_ctl.download_var, {}),
                save=(session_ctl.save, "[$event]"),
                open=(session_ctl.open, "[$event]"),
                apply=session_ctl.apply,
                reset=session_ctl.reset,
                autosave=(session_ctl.autosave_var, {}),
            ):
                with html.Template(v_slot_files=True):
                    UploadFile(
                        session_id=("upload_session_id", ""),
                        accept=".epc,.h5",
                        loaded=("ui_loaded_files", []),
                        error="load_error = $event",
                    )
                # a session read from OSDU / ETP: the form is prefilled from
                # the file (server, partition); the token is the reader's to
                # type, never kept in the file
                with html.Template(v_slot_etp=True):
                    UploadOsdu(
                        prefill=(session_ctl.etp_prefill_var, {}),
                        **etp_bindings,
                    )
            # A reload is a NEW session behind the launcher: the loaded
            # files, the views, the comparisons are gone with the old one.
            # The button says so before it does it; the layout memory of
            # view_manager only ever serves a single-session server.
            with _top_button("Reload the page — starts a new session: the loaded"
                             " files and every view are lost",
                             "window.confirm('Reload starts a new session: the"
                             " loaded files and every view are lost. Reload?')"
                             " && window.location.reload()",
                             icon=True):
                FpIcon(icon="fespp-reload", size=20, mono=True)
            _view_button("fespp-file-health",
                         "Data health — what is wrong with the loaded data:"
                         " partial objects, unreadable datasets, kinds, units, CRS",
                         "health", None)
            # The "New 3D view" question. Mounted once here rather than per
            # panel (adding a view is an application action), and it draws
            # itself through a Teleport, so where it sits in the tree does
            # not decide where it appears.
            NewViewDialog(
                open=("ui_newview_open", False),
                views=("fespp_render_panels", []),
                default_from=("fespp_active_panel_id", ""),
                create=(server.controller.open_render_view, "[$event]"),
                close="ui_newview_open = false",
            )
            v3.VDivider(vertical=True, inset=True, classes="mx-2")
            # the About door, last of the bar (app/views/about): the
            # version, the credits and the licences (the manager, 21/10)
            about.build(server)

        with layout.content:
            # The page-wide CSS. trame_client.Style writes a REAL <style> into
            # the document head; Vue 3 strips a <style> tag found inside a
            # component template (html.Style), so its rules would never
            # reach the page.
            trame_client.Style(
                # The pill of an unnamed wait fades in only once a round trip has lasted
                # long enough to be worth reporting. `animation` and not
                # `transition`: the element is MOUNTED by a v-if, and a
                # transition has nothing to transition from.
                "@keyframes fp-late-in { to { opacity: 1; visibility: visible; } }"
                " .fp-late { opacity: 0; visibility: hidden;"
                "   animation: fp-late-in 0s linear 400ms forwards; }"
                " @media (prefers-reduced-motion: reduce) {"
                "   .fp-late { animation-duration: 0s; } }"
                # The rules of the views' dock (`.fp-views`), never of a dock
                # inside one of its panels (`.fp-cards`).
                # Each panel's chrome (negative top offset) overflows up into
                # the dockview tab row instead of being clipped: dockview 7
                # draws a panel in a layer of its own (`dv-render-overlay`),
                # which paints only inside its box and lies under the tab row
                # — a docked one a step over it (a floating one has its own
                # z-index from dockview, over its window)
                " .fp-views :is(.dv-content-container, [class*='dv-content-container']):not(.fp-cards *)"
                " { overflow: visible !important; }"
                " .fp-views .dv-render-overlay:not(.fp-cards *) { contain: layout !important; }"
                " .fp-views .dv-render-overlay:not(.dv-render-overlay-float):not(.fp-cards *)"
                " { z-index: 2 !important; }"
                # the views' tab rows in the F2I blue (no black chrome). The tab
                # of the view in use reads as a folder tab: WHITE like the
                # view below it, joined to it, with an accent bar on top. The
                # tab shown by another group is pale blue: on screen, not in
                # use. Hidden tabs stay in the bar, their text dimmed. (The
                # visible tab used to share the bar's colour and the hidden
                # ones were lighter: with two views, the one NOT in use looked
                # selected — the PO, 15/10.) Set on the dock's shell, which
                # carries its `.dockview-theme-<name>` class: more specific,
                # so it wins whatever theme the widget picks.
                " .fp-views .dv-shell:not(.fp-cards *) {"
                "   --dv-tabs-and-actions-container-background-color: #00436D;"
                "   --dv-activegroup-visiblepanel-tab-background-color: #ffffff;"
                "   --dv-inactivegroup-visiblepanel-tab-background-color: #D3E2EE;"
                "   --dv-activegroup-hiddenpanel-tab-background-color: #00436D;"
                "   --dv-inactivegroup-hiddenpanel-tab-background-color: #00436D;"
                "   --dv-activegroup-visiblepanel-tab-color: #00436D;"
                "   --dv-activegroup-hiddenpanel-tab-color: rgba(255,255,255,0.78);"
                "   --dv-inactivegroup-visiblepanel-tab-color: #00436D;"
                "   --dv-inactivegroup-hiddenpanel-tab-color: rgba(255,255,255,0.62);"
                "   --dv-tab-divider-color: #2F6C96;"
                "   --dv-group-view-background-color: #ffffff;"
                "   --dv-separator-border: #2F6C96;"
                " }"
                # a view's cards: a lower row, pale on the view's white, the
                # navy of the views as its ink (and the buttons' icons'), so a
                # card reads as a part of its view and never as a view
                " .fp-cards .dv-shell {"
                "   --dv-tabs-and-actions-container-height: 28px;"
                "   --dv-tabs-and-actions-container-font-size: 12px;"
                "   --dv-tabs-and-actions-container-background-color: #E6EEF5;"
                "   --dv-activegroup-visiblepanel-tab-background-color: #ffffff;"
                "   --dv-inactivegroup-visiblepanel-tab-background-color: #F5F8FB;"
                "   --dv-activegroup-hiddenpanel-tab-background-color: #E6EEF5;"
                "   --dv-inactivegroup-hiddenpanel-tab-background-color: #E6EEF5;"
                "   --dv-activegroup-visiblepanel-tab-color: #00436D;"
                "   --dv-activegroup-hiddenpanel-tab-color: rgba(0,67,109,0.72);"
                "   --dv-inactivegroup-visiblepanel-tab-color: #00436D;"
                "   --dv-inactivegroup-hiddenpanel-tab-color: rgba(0,67,109,0.6);"
                "   --dv-tab-divider-color: #C9D9E6;"
                "   --dv-group-view-background-color: #ffffff;"
                "   --dv-separator-border: #C9D9E6;"
                "   --fp-chrome-ic: #00436D; --fp-chrome-ic-f2i: #5E8E12;"
                " }"
                " .fp-cards .dv-tabs-and-actions-container { border-bottom: 1px solid #C9D9E6; }"
                " .fp-cards .fp-dock-act:hover { background: rgba(0,67,109,0.1); }"
                # the view in use: an accent bar across the top of its tab,
                # and its title in bold
                " .fp-views .dv-groupview.dv-active-group:not(.fp-cards *)"
                ">.dv-tabs-and-actions-container .dv-tabs-container>.dv-tab.dv-active-tab {"
                "   box-shadow: inset 0 3px 0 #00A3E0; font-weight: 600; }"
                " .fp-views .dv-tabs-container:not(.fp-cards *)>.dv-tab.dv-inactive-tab:hover {"
                "   color: #ffffff; background-color: #2F6C96; }"
                # the card in use: the same accent, thinner
                " .fp-cards .dv-groupview.dv-active-group"
                ">.dv-tabs-and-actions-container .dv-tabs-container>.dv-tab.dv-active-tab {"
                "   box-shadow: inset 0 2px 0 #00A3E0; font-weight: 600; }"
                " .fp-cards .dv-tabs-container>.dv-tab.dv-inactive-tab:hover {"
                "   color: #00436D; background-color: #D3E2EE; }"
                # a detached view filling the dock (app/views/dock_fill)
                " .fp-views .dv-resize-container.fp-filled:not(.fp-cards *) {"
                "   top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important;"
                "   width: 100% !important; height: 100% !important; }"
                " .fp-views .dv-resize-container.fp-filled:not(.fp-cards *) > [class^='dv-resize-handle']"
                " { display: none; }"
                # it has no edge to dock to: its anchor button lets go
                " .fp-views .dv-resize-container.fp-filled .fp-dock-act:not(.fp-cards *):is("
                "[data-fp-action=left], [data-fp-action=right], [data-fp-action=top], [data-fp-action=bottom])"
                " { display: none; }"
                # a word under a top bar icon (_view_button's caption)
                " .fp-top-cap { display: flex; flex-direction: column; align-items: center; }"
                " .fp-top-cap > svg { margin: -3px 0 -4px; }"
                " .fp-top-cap > span { font: 700 8px/1 system-ui, sans-serif; letter-spacing: 0.2px; text-transform: none; }"
            )
            with html.Div(style="height:100%; width:100%; position:relative;"):
                # dockview of independent render panels; the first view is added
                # on the dockview `ready` event (client mount); each panel's
                # title bar carries its own add-view (split) icons.
                MultiView(server)

                # Snackbars: amber = selection semantics (trajectory
                # veto...), red = load/HDF5 errors surfaced by the engine.
                # Each stays as long as its text takes to read (a veto runs
                # to thirty words, notes concatenate): ~60 ms a character,
                # never under 6 s (8 s for an error) nor over 30 s, and a ×
                # closes it sooner.
                with v3.VSnackbar(
                    v_model=("empty_color_snackbar_visible", False),
                    timeout=("Math.min(30000, Math.max(6000,"
                             " 60 * (empty_color_snackbar_text || '').length))",),
                    color="amber-darken-2", location="bottom",
                ):
                    html.Span("{{ empty_color_snackbar_text }}")
                    with v3.Template(v_slot_actions=True):
                        v3.VBtn(icon="mdi-close", variant="text", size="small",
                                title="Close",
                                click="empty_color_snackbar_visible = false")
                with v3.VSnackbar(
                    v_model=("load_error_visible", False),
                    timeout=("Math.min(30000, Math.max(8000,"
                             " 60 * (load_error || '').length))",),
                    color="red-darken-2", location="bottom",
                ):
                    html.Span("{{ load_error }}")
                    with v3.Template(v_slot_actions=True):
                        v3.VBtn(icon="mdi-close", variant="text", size="small",
                                title="Close",
                                click="load_error_visible = false")

                # THE wait of the page (a view's own is its bar, view_manager),
                # one pill whatever is waited for, the
                # kit's look (panel.css, FpProgress in the widgets), in sight
                # at the bottom:
                # - a read in steps (engine/progressive_load): how far it is,
                #   and Stop, which ends the read after the object being read;
                #   what has arrived stays, the rest is unticked;
                # - a load (`ui_loading`, `view_loading_message`);
                # - `ui_work_note`, any other wait worth a sentence;
                # - else any server round trip past 400 ms (`trame__busy`).
                #   IT WAITS BEFORE IT PAINTS (`fp-late`, the Style block
                #   above). Every camera gesture ENDS WITH A ROUND TRIP: vtk.js
                #   fires EndAnimation on each mouse release, trame's client
                #   counts every `trigger` as busy, and the counter notifies
                #   immediately on the way in but only after 50 ms on the way
                #   out. A short round trip mounts and unmounts without ever
                #   being seen, while anything genuinely slow still says so.
                server.state.setdefault("ui_load_progress", {})
                server.state.setdefault("ui_work_note", "")
                server.state.setdefault("ui_loading", False)
                _reading = "(ui_load_progress && ui_load_progress.running)"
                _named_wait = f"{_reading} || ui_loading || ui_work_note"
                # The pill greys what it holds: everything under the app bar,
                # which stays reachable (upload, reload). A click on the views
                # would not answer, and a tree click during a load would act on
                # a tree about to be replaced. A read in steps holds nothing:
                # what has arrived can be looked at while the rest comes.
                html.Div(
                    v_if=(f"!{_reading} && (ui_loading || ui_work_note || trame__busy)",),
                    classes=("['fp-wait-scrim', !(ui_loading || ui_work_note) && 'fp-late']",),
                    style="position:absolute; inset:0; z-index:46;",
                    raw_attrs=["data-fp-page-wait"],
                )
                with html.Div(
                    v_if=(f"{_named_wait} || trame__busy",),
                    classes=(f"['fp-progress', !({_named_wait}) && 'fp-late']",),
                    raw_attrs=['role="progressbar"'],
                    __properties=[("data_fp_load_progress", "data-fp-load-progress")],
                    data_fp_load_progress=(f"{_reading} ? '' : null",),
                    style=("position:absolute; left:50%; bottom:22px;"
                           " transform:translateX(-50%); z-index:47;"
                           " padding:6px 12px; border-radius:18px;"
                           " background:#fff; color:#00436D;"
                           " box-shadow:0 2px 10px rgba(0,40,70,.22);"
                           " font-size:13px; font-weight:600; white-space:nowrap;"
                           " pointer-events:none;"),
                ):
                    html.Span(
                        "{{ " + _reading + " ? (ui_load_progress.stopping"
                        " ? 'Stopping after the object being read…'"
                        " : 'Loading ' + ui_load_progress.done + ' / '"
                        " + ui_load_progress.total + ' objects '"
                        " + ui_load_progress.where"
                        " + (ui_load_progress.note ? ' — ' + ui_load_progress.note + ', a long read' : '')"
                        " + '…')"
                        " : ui_loading ? view_loading_message"
                        " : ui_work_note || 'Working…' }}",
                        __properties=[("data_fp_load_count", "data-fp-load-count")],
                        data_fp_load_count=(f"{_reading} ? '' : null",),
                    )
                    html.Div(classes="fp-busy", style="flex:0 0 72px; width:72px;")
                    v3.VBtn(
                        "Stop", size="small", variant="flat", color="error",
                        rounded=True,
                        v_if=(_reading,),
                        disabled=("ui_load_progress.stopping",),
                        title="End the read after the object being read; what has"
                              " arrived stays, the rest is unticked",
                        style="pointer-events:auto;",
                        __properties=[("data_fp_load_stop", "data-fp-load-stop")],
                        data_fp_load_stop=True,
                        click=server.controller.load_stop,
                    )

            # THE confirmation box of the application, drawn once, here.
            # One gesture in any of the four trees can stand for dozens of
            # reads; above `engine/tick_confirm.MAX_TICK_LOAD` unread
            # properties the tick states its size and waits, and nothing is
            # read before the answer. Drawn in the layout rather than in a
            # panel because the data tree lives in a floating card of every
            # 3D view: one box per open card would stack scrims.
            # The classes are the shared `fp-scrim` / `fp-dialog` of
            # widgets/_shared/panel.css, which every widget bundle carries.
            with html.Div(
                v_if=("ui_tick_confirm && ui_tick_confirm.title",),
                classes="fp-scrim",
                # stepping back is what the scrim does: the box stands in
                # the way of a click nobody meant to make, so the safe
                # answer is the easy one
                __events=[("click_self", "click.self")],
                click_self=(server.controller.tick_confirm_answer, "[false]"),
            ):
                # `tabindex`: the box is opened by a CLICK, which leaves the
                # focus on the tree row behind the veil. Chrome then refuses
                # the `autofocus` of a button inserted after page load, and a
                # key pressed outside the box never reaches a listener inside
                # it. So the dialog itself is focusable, `vue:mounted` puts
                # the focus on `Cancel` as soon as the box appears, and Esc
                # is listened for HERE, where the focus then is.
                with html.Div(classes="fp-dialog", tabindex="-1",
                              __properties=["role", ("aria_modal", "aria-modal")],
                              role="dialog", aria_modal="true",
                              __events=[("keydown_esc", "keydown.esc"),
                                        ("vue_mounted", "vue:mounted")],
                              keydown_esc=(server.controller.tick_confirm_answer,
                                           "[false]"),
                              vue_mounted=(
                                  "$event.el && ($event.el.querySelector("
                                  "'.fp-dialog-foot .fp-btn') || $event.el)"
                                  ".focus()")):
                    with html.Div(classes="fp-dialog-head"):
                        html.Span("{{ ui_tick_confirm.title }}",
                                  classes="fp-title")
                        html.Button(
                            "×", classes="fp-chip-btn", title="Cancel",
                            click=(server.controller.tick_confirm_answer,
                                   "[false]"))
                    html.Div("{{ ui_tick_confirm.body }}",
                             classes="fp-dialog-body")
                    with html.Div(classes="fp-dialog-foot"):
                        # focused by the dialog's `vue:mounted` above, not by
                        # `autofocus`: a browser honours autofocus only while
                        # nothing else already holds the focus, and the click
                        # that opened the box always does
                        # a question may name its way back ("Stay in
                        # depth"): Cancel when it does not
                        html.Button(
                            "{{ ui_tick_confirm.cancel || 'Cancel' }}", classes="fp-btn",
                            click=(server.controller.tick_confirm_answer,
                                   "[false]"))
                        # a question may offer a third way (an object of
                        # the other domain converted with the law)
                        html.Button(
                            "{{ ui_tick_confirm.third }}", classes="fp-btn",
                            v_if=("ui_tick_confirm.third",),
                            click=(server.controller.tick_confirm_answer,
                                   "['third']"))
                        html.Button(
                            "{{ ui_tick_confirm.ok }}",
                            classes="fp-btn fp-primary",
                            click=(server.controller.tick_confirm_answer,
                                   "[true]"))

    if args.local_epc_file_path:
        @server.controller.add("on_server_ready")
        def _autoload(**_):
            server.controller.load_epc_file(args.local_epc_file_path)

    server.start()


def _assistant_bundle():
    """Return the Assistant's JS module (widgets/assistant), or None when the
    assistant is off.

    OFF BY DEFAULT: not offered yet (the PO, 18/10 — app/core/previews). A
    server shows it only when started with ``FESPP_ASSISTANT=1``
    (``docker run -e FESPP_ASSISTANT=1 ...``: the wslink launcher hands the
    container's environment down to every session); the visual and
    browser benches do. Only the exact value "1" switches it on: any other
    value leaves it off, and the start line says so with the value it read.
    Its command engine is home-made (fespp_on_trame/ia/nlu) and calls
    nothing outside the server.

    Off, too, when its package is not installed: an application deployed
    without the widget must not stop every new session at its first import.
    Either way the session log says ONCE, at start, whether it is on and
    how to change that, and an assistant that is off simply has no door in
    the top bar."""
    from fespp_on_trame.app.core import previews
    raw = _os.environ.get("FESPP_ASSISTANT")
    if not previews.offered("assistant"):
        said = "" if raw is None else f"; FESPP_ASSISTANT={raw!r} read, only \"1\" switches it on"
        print("[assistant] off (not offered yet) — start the server with"
              f" FESPP_ASSISTANT=1 to switch it on{said}", flush=True)
        return None
    try:
        from trame_fespp_assistant import module
    except ImportError as exc:
        print("[assistant] off — the widget package is not installed:", exc, flush=True)
        return None
    print("[assistant] on (FESPP_ASSISTANT=1; home-made command engine, no"
          " external call) — unset it to switch the assistant off", flush=True)
    return module


def _wire_assistant(server, on):
    """Build the Assistant's controller and register its gestures.

    The controller (widgets/assistant) runs on the application's adapter
    (app/assistant_host); its gestures become trame controllers, so that the
    panel (app/views/assistant_panel) and the headless scenarios (op
    ``assistant_probe``) reach them by name.

    ``open_assistant`` exists either way: it is the door's opener, and the
    one a restored session goes through (app/session_host); an assistant
    that is off opens nothing and says so. Returns the controller, or None."""
    ctrl = server.controller
    assistant_ctl = host = None
    if on:
        try:
            from trame_fespp_assistant.controller import AssistantController
            from fespp_on_trame.app.assistant_host import FesppAssistantHost
            from fespp_on_trame.ia.journal import DialogueJournal
            host = FesppAssistantHost(server)
            # a closed view's memories go with it (app/core/lifecycle)
            lifecycle = getattr(server.context, "lifecycle", None)
            if lifecycle is not None:
                lifecycle.on("view_closed", host.forget_view)
            # every exchange is kept on the server, to enrich the vocabulary
            # from what readers really type (scripts/assistant_log_report.py)
            journal = DialogueJournal.from_env()
            # the interface is English (the PO, 15/10): a request may be
            # typed in French, the panel answers and labels in English
            assistant_ctl = AssistantController(server, host, journal=journal,
                                                lang="en", reply_lang="en")
        except Exception as exc:
            print("[assistant] off — it could not be built:", exc, flush=True)
            assistant_ctl = None
    if assistant_ctl is not None:
        ctrl.assistant_ask = assistant_ctl.ask
        ctrl.assistant_choose = assistant_ctl.choose
        ctrl.assistant_undo = assistant_ctl.undo
        ctrl.assistant_clear = assistant_ctl.clear
        # the controller and its adapter on the context: a probe asks them
        # what a sentence is taken for
        server.context.assistant = assistant_ctl
        server.context.assistant_host = host

    def open_assistant():
        if assistant_ctl is None:
            print("[assistant] not opened: the assistant is off", flush=True)
            return None
        try:
            vid = ctrl.add_view(kind="assistant")
        except Exception as exc:
            print("[assistant] the panel could not be opened:", exc, flush=True)
            return None
        # the examples are built for a shown panel only (examples_wanted),
        # and the assistant names properties by kind: what a lazy ETP load
        # left on the store is read in the background (boot.lazy_read_all)
        try:
            assistant_ctl.refresh_examples()
        except Exception as exc:
            print("[assistant] examples not built:", exc, flush=True)
        try:
            ctrl.lazy_read_all()
        except Exception as exc:
            print("[assistant] no background read:", exc, flush=True)
        return vid

    ctrl.open_assistant = open_assistant
    return assistant_ctl


# The project's own widgets, whose JS has to be baked into the static www.
# Third-party trame packages (plotly, the colour-opacity editor) ship their own
# bundles and are deliberately out of scope here.
_OUR_WIDGET_PREFIXES = ("trame_fespp_", "trame_welllog")


def _check_widget_bundles(modules):
    """Report, on stderr, each enabled widget whose bundle was not baked.

    A widget enabled in main() but absent from ``www_modules`` fails only in
    the BROWSER, as ``ReferenceError: trame_fespp_X is not defined``, with
    nothing at all on the server to follow.

    Three places must agree for a widget to work: the Dockerfile glob that
    copies it, ``setup/apps.yml`` ``www_modules`` (which bakes its bundle,
    via trame.tools.www), and the enable list in main(). Only the last one
    is visible from Python, so this compares it with what actually drove the
    bake, ``/opt/trame/apps.json``, and names the missing entry.

    Silent when that file is absent: a local pvpython run has no launcher.
    """
    import json
    import os
    import sys

    apps = "/opt/trame/apps.json"
    if not os.path.isfile(apps):
        return
    try:
        with open(apps, encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return
    baked = set()
    for app in config.values():
        for entry in (app or {}).get("www_modules") or []:
            baked.add(entry.split(".", 1)[0])

    missing = sorted({
        m.__name__.split(".", 1)[0] for m in modules
        if m.__name__.split(".", 1)[0].startswith(_OUR_WIDGET_PREFIXES)
    } - baked)
    if missing:
        print("[fespp] WIDGET BUNDLE MISSING: %s enabled but not in "
              "www_modules — the browser will say 'is not defined' and the "
              "panel will be blank. Add '<name>.module' to setup/apps.yml "
              "www_modules and rebuild the image."
              % ", ".join(missing), file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()
