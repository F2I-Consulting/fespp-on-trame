"""Per-representation display type panel.

Wraps ptc.RepresentBy in an expansion panel inside each rep's attribute
panel. RepresentBy targets the ParaView active source, so per-rep behavior
relies on SetActiveSource(rep_source) running when the active resqml
representation changes (handled in fespp_active).
"""
from trame.app import get_server
from trame.widgets import vuetify3, html
import ptc

server = get_server()
state = server.state


class RepresentationTypePanel(html.Div):
    def __init__(self):
        super().__init__(v_if="active_representation_path && active_representation_path.length > 0")

        with self:
            with vuetify3.VExpansionPanels(v_model=("rt_panels", [0]), multiple=True, elevation=0):
                with vuetify3.VExpansionPanel(elevation=0, value=0):
                    with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                        html.Span("Representation type", classes="text-body-2 font-weight-medium")
                        vuetify3.VSpacer()
                        vuetify3.VChip(
                            "{{ representation_active || '—' }}",
                            size="x-small",
                            variant="tonal",
                            color="blue",
                            classes="font-italic mr-2",
                            v_if="representation_show",
                        )
                    with vuetify3.VExpansionPanelText(classes="pa-2"):
                        ptc.RepresentBy(
                            color="blue",
                            base_color="blue",
                            item_color="blue",
                            flat=True,
                        )
