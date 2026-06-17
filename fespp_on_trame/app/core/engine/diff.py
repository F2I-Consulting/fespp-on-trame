"""Diff-view dispatch — extracted from `boot.initialize_fespp_engine`.

The diff feature lets the user pick two properties on the same grid
and render their algebraic difference (A − B) into a dedicated diff
panel via a `PythonCalculator` filter. The two dropdowns in the diff
dialog are driven by this module:

  - `refresh_diff_choices` (on `ui_loaded_array_paths` change) →
    builds the flat list of choices.
  - `refresh_diff_b_choices` (on A change) → filters B to "same rep
    as A, different from A".
  - `compute_diff` (controller method) → snapshots the active
    view/source, creates the calculator on the right rep, displays
    it in the diff panel, restores the active context.

Failures surface via `state.diff_compute_error` so the dialog can
display them."""
from paraview import simple as pvsimple


def build_array_choice(tree, array_path):
    """Resolve a tree array path to a `{title, value, rep_path,
    array_name}` dict for the diff dropdowns. Returns None if the
    path is not resolvable or its ancestor rep can't be found."""
    node_id = tree.find_node_id(array_path)
    if not node_id:
        return None
    array_name = (
        tree.find_attribute_value(node_id, "propTitle")
        or tree.find_title(node_id)
    )
    rep_node_id = tree.find_representation_node(node_id)
    if not rep_node_id:
        return None
    rep_path = tree.find_path(rep_node_id)
    rep_title = tree.find_title(rep_node_id) or rep_path
    return {
        "title": f"{rep_title} / {array_name}",
        "value": array_path,
        "rep_path": rep_path,
        "array_name": array_name,
    }


def refresh_diff_choices(state, tree, ui_loaded_array_paths):
    """Re-derive `state.diff_array_choices` from the loaded-array list."""
    choices = []
    for p in ui_loaded_array_paths or []:
        ch = build_array_choice(tree, p)
        if ch is not None:
            choices.append(ch)
    state.diff_array_choices = choices


def refresh_diff_b_choices(state, diff_array_a_path, diff_array_choices):
    """B must live on the same rep as A and be different from A."""
    if not diff_array_a_path:
        state.diff_array_b_choices = []
        return
    a_rep = next(
        (c["rep_path"] for c in (diff_array_choices or []) if c["value"] == diff_array_a_path),
        None,
    )
    if a_rep is None:
        state.diff_array_b_choices = []
        return
    state.diff_array_b_choices = [
        c for c in (diff_array_choices or [])
        if c["rep_path"] == a_rep and c["value"] != diff_array_a_path
    ]


def compute_diff(state, controller, server, source_registry):
    """Build (or refresh) the dedicated diff PythonCalculator on the
    rep shared by arrays A and B, then show it in the diff panel
    colored by the diff array. Snapshots the user's active source/
    view and restores them at the end — otherwise subsequent tree
    clicks (which act on `pvsimple.GetActiveView()`) would silently
    retarget the diff view."""
    state.diff_compute_error = ""
    a_path = state.diff_array_a_path
    b_path = state.diff_array_b_path
    if not a_path or not b_path:
        state.diff_compute_error = "Pick both A and B properties."
        return
    choices = state.diff_array_choices or []
    a = next((c for c in choices if c["value"] == a_path), None)
    b = next((c for c in choices if c["value"] == b_path), None)
    if a is None or b is None:
        state.diff_compute_error = "Unknown property — reload and retry."
        return
    if a["rep_path"] != b["rep_path"]:
        state.diff_compute_error = "A and B must be on the same grid."
        return
    src = source_registry.get(a["rep_path"])
    if src is None:
        state.diff_compute_error = "Source not loaded yet."
        return

    mv = server.context.multi_view
    if mv is None:
        state.diff_compute_error = "Multi-view not ready."
        return
    diff_panel_id, diff_view = mv.get_or_create_diff_view()

    # Show the per-view compute overlay before doing the work — the
    # flush makes the True state visible to the client.
    state.fespp_diff_computing = True
    try:
        state.flush()
    except Exception:
        pass

    # Snapshot the user's active source/view so we can restore them
    # at the end.
    prev_active_view = pvsimple.GetActiveView()
    prev_active_source = pvsimple.GetActiveSource()
    try:
        # Switch the active view BEFORE creating the calc so any
        # implicit pvsimple side-effects target the diff view.
        pvsimple.SetActiveView(diff_view)

        calc_name = "fespp_diff"
        existing = pvsimple.FindSource(calc_name)
        if existing is not None:
            pvsimple.Delete(existing)
        calc = pvsimple.PythonCalculator(Input=src, registrationName=calc_name)
        calc.Expression = f'{a["array_name"]} - {b["array_name"]}'
        calc.ArrayName = "fespp_diff_value"
        calc.ArrayAssociation = "Cell Data"
        calc.UpdatePipeline()

        # Defensive: ensure the calc is not displayed in any non-diff
        # view (pvsimple may still touch other views in edge cases).
        for pid, view in mv.panel_pv_views().items():
            if pid == diff_panel_id:
                continue
            try:
                pvsimple.Hide(proxy=calc, view=view)
            except Exception:
                pass

        # Hide anything previously visible in the diff view and show
        # the calc only.
        for s in pvsimple.GetSources().values():
            try:
                d = pvsimple.GetDisplayProperties(s, view=diff_view)
                if d is not None:
                    d.Visibility = 0
            except Exception:
                pass
        disp = pvsimple.Show(proxy=calc, view=diff_view)
        try:
            pvsimple.ColorBy(disp, ("CELLS", "fespp_diff_value"))
        except Exception:
            pass
        # Color bar for the diff array in the diff view only.
        try:
            disp.SetScalarBarVisibility(diff_view, True)
        except Exception:
            pass
        try:
            pvsimple.ResetCamera(view=diff_view)
        except Exception:
            pass
        pvsimple.Render(view=diff_view)
        html_view = mv.get_html_view(diff_panel_id)
        if html_view is not None:
            html_view.update()
        state.fespp_diff_ready = True

        # Refresh the diff colors editor only when the user has the
        # dialog open — its on_visible handler will refresh on next
        # open otherwise. Done with active=calc+diff_view so the
        # editor's update_scalar_range / RGBPoints reads off the
        # right proxies.
        if state.diff_colors_dialog_visible:
            pvsimple.SetActiveSource(calc)
            controller.refresh_diff_color_editor()
    finally:
        if prev_active_view is not None:
            pvsimple.SetActiveView(prev_active_view)
        if prev_active_source is not None:
            pvsimple.SetActiveSource(prev_active_source)
        state.fespp_diff_computing = False
