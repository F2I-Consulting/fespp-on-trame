"""Selection / load-mode dispatch — extracted from
`boot.initialize_fespp_engine`.

The treeview's per-tab checkbox arrays (`ui_select_node_reservoir`,
`ui_select_node_surface`, `ui_select_node_well`) drive what gets
loaded into the ParaView pipeline. Two load modes coexist:

  - "auto" — each toggle pushes the new per-tab selection immediately.
    The on-change handlers below call into `Selector` straight away.
  - "manual" — the toggles only stage selection state; the toolbar
    Load button pushes the aggregated selection in one shot via
    `apply_pending_selection`.

Switching from manual back to auto flushes whatever the user staged."""


def on_change_ui_select_node_surface(state, selector):
    """Surface tab toggle — push immediately in auto mode."""
    if selector is not None and state.load_mode == "auto":
        selector.select_node_surface()


def on_change_ui_select_node_well(state, selector):
    """Well tab toggle — push immediately in auto mode."""
    if selector is not None and state.load_mode == "auto":
        selector.select_node_well()


def on_change_ui_select_node_reservoir(state, selector):
    """Reservoir tab toggle — push immediately in auto mode."""
    if selector is not None and state.load_mode == "auto":
        selector.select_node_reservoir()


def apply_pending_selection(selector, activator):
    """Toolbar Load button entry point — push the aggregated per-tab
    selections to the pipeline. Used only in load_mode == "manual";
    in "auto" the per-tab handlers above already pushed on every
    toggle.

    Re-runs the active-node handlers afterwards: in manual mode the
    active change happened BEFORE the Load click (when the user
    checked the box), so the rep didn't exist yet and the activator
    short-circuited. We re-run the same logic now via
    `Activator.refresh_active()` — calling state vars directly would
    get coalesced into a no-op by Trame's flush batching."""
    if selector is None:
        return
    selector.select_node_reservoir()
    selector.select_node_surface()
    selector.select_node_well()
    if activator is not None:
        activator.refresh_active()


def on_load_mode_change(selector, activator, load_mode):
    """Switching from "manual" back to "auto" must flush any pending
    selection the user staged in manual mode."""
    if load_mode == "auto" and selector is not None:
        apply_pending_selection(selector, activator)
