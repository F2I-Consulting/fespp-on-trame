"""Magnet button + popup menu defining the camera-broadcast group of
a single render panel.

Each render panel owns a `ViewLinkMenu`. Clicking the magnet opens a
VMenu listing every *other* render panel; each one is a checkbox that
links / unlinks the two panels symmetrically. The current panel's
camera buttons (PerViewCameraToolbar) iterate over the panel itself
plus everything in `state.view_links[panel_id]`.

State shape:
    state.view_links: dict[panel_id, list[panel_id]]

Invariant maintained here: if A is in view_links[B], then B is in
view_links[A] (symmetric link). Orphan entries (panel closed but its
id still referenced) are filtered by the consumer
(PerViewCameraToolbar) when it iterates."""
from trame.app import get_server
from trame.widgets import html, vuetify3


class ViewLinkMenu:
    """Magnet button + checklist menu for view-to-view camera links."""

    def __init__(self, panel_id: str):
        self._panel_id = panel_id
        self._server = get_server()
        self._state = self._server.state
        self._state.setdefault("view_links", {})

    @staticmethod
    def toggle_link(state, panel_a: str, panel_b: str):
        """Symmetric toggle: if A↔B link exists, drop it on both sides;
        otherwise add it on both sides. Static so the same primitive
        can be called from the engine (e.g. on panel close to drop
        every dangling link)."""
        if panel_a == panel_b or not panel_a or not panel_b:
            return
        links = {k: list(v) for k, v in (state.view_links or {}).items()}
        a_set = set(links.get(panel_a, []))
        if panel_b in a_set:
            a_set.discard(panel_b)
            links[panel_a] = sorted(a_set)
            b_set = set(links.get(panel_b, []))
            b_set.discard(panel_a)
            links[panel_b] = sorted(b_set)
        else:
            a_set.add(panel_b)
            links[panel_a] = sorted(a_set)
            b_set = set(links.get(panel_b, []))
            b_set.add(panel_a)
            links[panel_b] = sorted(b_set)
        # Drop empty entries to keep the dict tidy.
        for k in list(links.keys()):
            if not links[k]:
                links.pop(k)
        state.view_links = links

    def _on_toggle(self, other_panel_id: str):
        self.toggle_link(self._state, self._panel_id, other_panel_id)

    def render(self):
        # Magnet color reflects whether at least one other panel is
        # currently linked to this one. Bound directly to the state
        # dict so it updates without a Python round-trip when the
        # user toggles checkboxes inside the menu.
        link_expr = (
            f"(view_links && view_links['{self._panel_id}']"
            f" && view_links['{self._panel_id}'].length > 0)"
        )
        with vuetify3.VMenu(close_on_content_click=False):
            with vuetify3.Template(v_slot_activator="{ props }"):
                with vuetify3.VTooltip(location="right"):
                    with vuetify3.Template(v_slot_activator="{ props: tt }"):
                        vuetify3.VBtn(
                            icon="mdi-magnet",
                            v_bind="{ ...props, ...tt }",
                            variant="text",
                            size="small",
                            color=(f"{link_expr} ? 'blue' : 'grey-darken-1'", "grey-darken-1"),
                        )
                    html.Span("Link cameras to other views")
            with vuetify3.VCard(min_width="240"):
                with vuetify3.VCardText(classes="pa-2"):
                    html.Div(
                        "Linked views",
                        classes="text-caption text-uppercase font-weight-bold mb-2",
                    )
                    # Empty state — shown when there's no OTHER render
                    # panel to link to. `length` test handles both the
                    # missing list and the "self is the only render
                    # panel" case (filter would yield 0 items).
                    html.Div(
                        "No other view to link to yet.",
                        v_if=(
                            f"!fespp_render_panels"
                            f" || fespp_render_panels.filter(function(x){{return x.id !== '{self._panel_id}'}}).length === 0"
                        ),
                        classes="text-caption text-medium-emphasis",
                        style="line-height: 1.2;",
                    )
                    # One VCheckbox per OTHER render panel.
                    # `fespp_render_panels` is published by
                    # FesppMultiView._publish_panels_state on every
                    # add / close / rename. The v_for sits on an outer
                    # html.Div (not the VCheckbox) so the loop variable
                    # `p` stays reactive when Vue re-evaluates the
                    # model_value binding on each view_links mutation.
                    with html.Div(
                        v_for=(
                            f"p in (fespp_render_panels || [])"
                            f".filter(function(x){{return x.id !== '{self._panel_id}'}})"
                        ),
                        key="p.id",
                    ):
                        vuetify3.VCheckbox(
                            label=("p.title",),
                            model_value=(
                                f"!!(view_links && view_links['{self._panel_id}']"
                                f" && view_links['{self._panel_id}'].indexOf(p.id) >= 0)",
                            ),
                            update_modelValue=(
                                self._on_toggle,
                                "[p.id]",
                            ),
                            density="compact",
                            hide_details=True,
                            color="blue",
                            classes="mt-0",
                        )
                    html.Div(
                        "Reset cam / orientation / 2D-3D actions on this"
                        " view propagate to every checked view (and vice versa).",
                        classes="text-caption text-medium-emphasis mt-2",
                        style="line-height: 1.2;",
                    )
