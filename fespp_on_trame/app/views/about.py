"""The About door of the app bar: the application, its version, and the work
it is built on (the manager, 21/10: the credits Energistics, RESQML, Kitware,
trame).

What such a door usually holds, a desktop application's Help > About or a
web application's (i) at the end of its bar: the name and the version, the
copyright and the licence, the open-source components with their own
licence, and the notice of the trademarks named. The licence texts
themselves ship with the code (LICENSE and NOTICE at the root, each
component's own in its package): the dialog names them, it does not
reprint them."""
from trame.widgets import html
from trame.widgets import vuetify3 as v3

# (component, what it does here, licence, home page)
CREDITS = (
    ("FESAPI", "reads RESQML (EPC and HDF5 files) — F2I-CONSULTING",
     "Apache-2.0", "https://github.com/F2I-Consulting/fesapi"),
    ("FETPAPI", "the ETP client of the OSDU stores — F2I-CONSULTING",
     "Apache-2.0", "https://github.com/F2I-Consulting/fetpapi"),
    ("FESPP", "the ParaView plugin that turns RESQML into VTK — F2I-CONSULTING",
     "Apache-2.0", "https://github.com/F2I-Consulting/fespp"),
    ("ParaView", "the visualization engine — Kitware", "BSD-3-Clause",
     "https://www.paraview.org"),
    ("VTK", "the visualization toolkit — Kitware", "BSD-3-Clause", "https://vtk.org"),
    ("trame", "the web application framework — Kitware", "Apache-2.0",
     "https://kitware.github.io/trame/"),
    ("HDF5", "the binary arrays of the files — The HDF Group", "BSD-3-Clause",
     "https://www.hdfgroup.org"),
    ("Boost", "C++ libraries of FESAPI and FETPAPI", "BSL-1.0", "https://www.boost.org"),
    ("Vue.js, Vuetify", "the interface", "MIT", "https://vuejs.org"),
    ("dockview", "the panels' layout", "MIT", "https://dockview.dev"),
    ("trame-dockview", "the dock widget it started from — Kitware", "MIT",
     "https://github.com/Kitware/trame-dockview"),
    ("Plotly", "the charts", "MIT", "https://plotly.com/javascript/"),
    ("NumPy", "the computations on the values", "BSD-3-Clause", "https://numpy.org"),
)

TRADEMARKS = ("Energistics, RESQML and ETP are trademarks of Energistics, named here"
              " for the standards the application reads; their mention implies no"
              " endorsement.")


def _version():
    try:
        from fespp_on_trame import __version__
        return str(__version__ or "").strip() or "dev"
    except Exception as exc:
        print(f"[fespp] about: no version ({exc!r})", flush=True)
        return "dev"


def build(server):
    """The (i) button and its dialog, in the layout toolbar being built."""
    server.state.setdefault("ui_about_open", False)
    v3.VBtn(
        icon="mdi-information-outline",
        variant="text",
        color="primary",
        size="small",
        title="About Fespp on Trame — version, credits, licences",
        click="ui_about_open = true",
    )
    with v3.VDialog(v_model=("ui_about_open", False), max_width=620, scrollable=True):
        with v3.VCard(classes="fp-about"):
            with v3.VCardTitle(classes="d-flex align-center text-primary"):
                html.Span("FesTrame", style="font-weight: 700;")
                html.Span(f"version {_version()}", classes="text-caption ml-3 text-medium-emphasis")
            with v3.VCardText(style="font-size: 13px;"):
                html.P("RESQML models from EPC files and OSDU stores, in 3D views,"
                       " statistics and well logs, in the browser.", classes="mb-2")
                html.P("© F2I-CONSULTING — Apache License 2.0 (LICENSE and NOTICE"
                       " of the source).", classes="mb-3")
                html.Div("Built on", classes="text-overline")
                with html.Table(style="width: 100%; border-collapse: collapse;"):
                    for name, role, licence, link in CREDITS:
                        with html.Tr(style="border-bottom: 1px solid #eef1f5;"):
                            with html.Td(style="padding: 3px 8px 3px 0; white-space: nowrap;"):
                                html.A(name, href=link, target="_blank", rel="noopener",
                                       style="font-weight: 600;")
                            html.Td(role, style="padding: 3px 8px 3px 0;")
                            html.Td(licence, style="padding: 3px 0; white-space: nowrap;"
                                                   " font-family: ui-monospace, Consolas, monospace;"
                                                   " font-size: 11px;")
                html.P("Each component's licence text ships in its package.",
                       classes="text-caption text-medium-emphasis mt-2 mb-2")
                html.P(TRADEMARKS, classes="text-caption text-medium-emphasis mb-0")
            with v3.VCardActions():
                v3.VSpacer()
                v3.VBtn("Close", variant="text", color="primary",
                        click="ui_about_open = false")
