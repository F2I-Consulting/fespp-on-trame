"""Reusable "Copy from view X" menu — shared by the slice / clip /
threshold panel headers.

Phase 3c (decision D1): per-concern on-demand state copy. Each panel
gets a small icon button that opens a dropdown listing every other
render panel; selecting one snapshots that panel's state for THIS
concern and applies it onto the active panel (the panel the panel
widget is rendered into).

Wire-up:
  - `render_copy_menu(concern)` emits a `VBtn + VMenu + VList` block
    inside whatever container is currently open. Call it from inside
    the panel's header (e.g. next to the chain count chip).
  - The trigger `copy_<concern>_from_view` is registered once per
    server (idempotent — guarded by a server-state flag) and forwards
    to `controller.copy_<concern>_from(src_view)`.

The destination defaults to `state.fespp_active_panel_id` (the
controller resolves it), so we only need to pass the source view id.
The menu is hidden when there's only one render panel — no source
to copy from."""
from trame.app import get_server
from trame.widgets import html, vuetify3


_VALID_CONCERNS = ("threshold", "slice", "clip", "ijk_slicers")


def render_copy_menu(concern: str) -> None:
    """Render the VBtn + VMenu pair into the currently-open container.
    `concern` must be one of: "threshold", "slice", "clip", "ijk_slicers"."""
    if concern not in _VALID_CONCERNS:
        raise ValueError(f"render_copy_menu: unknown concern {concern!r}")

    trigger_name = f"copy_{concern}_from_view"
    icon = {
        "threshold": "mdi-content-copy",
        "slice": "mdi-content-copy",
        "clip": "mdi-content-copy",
        "ijk_slicers": "mdi-content-copy",
    }[concern]
    label = {
        "threshold": "Copy threshold chain from view",
        "slice": "Copy slice plane from view",
        "clip": "Copy clip plane from view",
        "ijk_slicers": "Copy IJK slicers from view",
    }[concern]

    # The menu is anchored on the trigger button. Vue's `activator`
    # slot wires the open-on-click behaviour for us. The button is
    # itself hidden when there's only one render panel — there's no
    # other source to copy from then.
    with vuetify3.VMenu(location="bottom end"):
        with vuetify3.Template(v_slot_activator="{ props }"):
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props: tooltipProps }"):
                    vuetify3.VBtn(
                        v_bind="{ ...props, ...tooltipProps }",
                        icon=icon,
                        variant="text",
                        density="compact",
                        size="small",
                        v_if="(fespp_render_panels || []).length > 1",
                        style="margin: 0; min-width: 32px; width: 32px; height: 32px;",
                    )
                html.Span(label)
        with vuetify3.VList(density="compact", min_width=200):
            vuetify3.VListSubheader(label)
            with vuetify3.VListItem(
                v_for=(
                    "p in (fespp_render_panels || [])"
                    ".filter(x => x.id !== fespp_active_panel_id)"
                ),
                key="p.id",
                title=("p.title",),
                click=f"trigger('{trigger_name}', [p.id])",
            ):
                with vuetify3.Template(v_slot_prepend=True):
                    vuetify3.VIcon("mdi-eye-arrow-right", size="small")


def _wire_triggers_once():
    """Register the copy triggers once per server. Idempotent — re-imports
    of this module (panel files) all hit the same set."""
    server = get_server()
    controller = server.controller
    flag = "_fespp_copy_from_view_triggers_wired"
    if getattr(server, flag, False):
        return
    setattr(server, flag, True)

    # Map concern → controller method name. "threshold" is the odd one
    # out (named `copy_threshold_chain_from` for clarity), the rest
    # follow `copy_<concern>_from`.
    _METHODS = {
        "threshold": "copy_threshold_chain_from",
        "slice": "copy_slice_from",
        "clip": "copy_clip_from",
        "ijk_slicers": "copy_ijk_slicers_from",
    }
    for concern in _VALID_CONCERNS:
        controller_method = _METHODS[concern]

        @server.trigger(f"copy_{concern}_from_view")
        def _on_copy(src_view, *, _method=controller_method):
            fn = getattr(controller, _method, None)
            if fn is None:
                print(f"[copy {_method}] controller method missing")
                return
            try:
                fn(src_view=src_view)
            except Exception as exc:
                print(f"[copy {_method}] failed: {exc}")


_wire_triggers_once()
