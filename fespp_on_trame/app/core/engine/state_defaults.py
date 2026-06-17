"""Trame state defaults for the FESPP engine.

`init_state_defaults(state)` runs once at engine boot. It seeds every
state variable that the rest of the engine + UI assume to exist:
selection / visibility / coloring tracking, diff / upload / view
status flags, VTK log mirror, etc.

Centralised here so `boot.py` stays focused on lifecycle (object
construction + handler wiring) and so adding a new state var doesn't
require scrolling through hundreds of lines of handlers to find the
init block. Group order roughly matches data-flow stages
(selection → loaded → visible → coloured / threshold / diff)."""


def init_state_defaults(state):
    # --- Per-tab selection state -----------------------------------
    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])

    state.setdefault("animation_delay", 0.1)

    state.setdefault("fespp_data_selectors", [])

    # --- Visibility tracking ---------------------------------------
    # ui_loaded_rep_paths: rep paths currently materialised in
    #   ParaView (eye icon rendered next to those tree nodes).
    # ui_hidden_rep_paths: subset whose display.Visibility was
    #   toggled off via the eye. Loaded but not in this set →
    #   visible.
    state.setdefault("ui_loaded_rep_paths", [])
    state.setdefault("ui_hidden_rep_paths", [])
    # Per-view visibility: ui_hidden_rep_paths is kept as a compat
    # alias mirroring the *active* panel's hidden set (so existing
    # consumers — source_registry auto-reload logic, the legacy
    # tree render binding — keep working). The per-view map is the
    # source of truth driven by tree eye clicks that carry an
    # explicit panel_id.
    state.setdefault("ui_hidden_rep_paths_by_view", {})

    # --- Coloring tracking -----------------------------------------
    # ui_loaded_array_paths: data-array tree nodes whose data is
    #   loaded (Property / TimeSeries / MultiRealization selectors).
    # ui_active_array_by_rep: at most one entry per rep — the array
    #   currently coloring it. Absent entry → SolidColor. Kept as a
    #   mirror of the *active panel's* per-view entry so legacy
    #   consumers (Activator, solid_color_panel) keep working with
    #   the active view's state.
    state.setdefault("ui_loaded_array_paths", [])
    state.setdefault("ui_active_array_by_rep", {})
    # Per-view active arrays — source of truth for the tree's
    # per-panel eye annotation. Shape:
    #   {panel_id: {rep_path: array_path}}
    # Absence (or null) of (panel_id, rep_path) → SolidColor in
    # that view.
    state.setdefault("ui_active_array_by_rep_by_view", {})
    # Per-panel "has TimeSeries property currently active" flag,
    # derived from ui_active_array_by_rep_by_view via the change
    # handler in active_array.py. Drives the per-view TimeControl
    # visibility in FesppMultiView so a panel rendering only static
    # properties doesn't show a useless TC.
    state.setdefault("panel_has_ts_by_id", {})

    # --- Diff feature ----------------------------------------------
    state.setdefault("diff_array_a_path", None)
    state.setdefault("diff_array_b_path", None)
    state.setdefault("diff_array_choices", [])
    state.setdefault("diff_array_b_choices", [])
    state.setdefault("diff_compute_error", "")

    state.setdefault("fespp_diff_ready", False)
    state.setdefault("fespp_diff_computing", False)
    state.setdefault("diff_colors_dialog_visible", False)
    state.setdefault("fespp_diff_panel_id", None)
    state.setdefault("add_view_dialog_visible", False)
    state.setdefault("add_view_kind", "render")

    # --- Tree hierarchy --------------------------------------------
    state.setdefault("tree_hierarchy_mode", "flat")

    # --- ETP connection --------------------------------------------
    state.setdefault("etp_dataspaces", [])
    state.setdefault("etp_selected_dataspace", None)

    # --- View / app status -----------------------------------------
    state.setdefault("has_data_loaded_once", False)
    state.setdefault("view_update", False)
    state.setdefault("view_reset_camera", False)
    state.setdefault("view_loading_message", "Loading... Please wait.")

    # --- VTK log panel ---------------------------------------------
    state.setdefault("vtk_log_messages", [])
    state.setdefault("vtk_log_visible", False)

    # --- Upload progress -------------------------------------------
    state.setdefault("upload_uploading", False)
    state.setdefault("upload_progress", 0)
    state.setdefault("upload_file_count", 0)
    state.setdefault("upload_file_names", [])
    state.setdefault("upload_debug", "")
    # Filled in on_server_ready once the port is known: each
    # process looks up its own port in proxy-mapping.txt to build
    # /api/{sid}/upload.
    state.setdefault("upload_session_id", "")

    # --- Misc UI ---------------------------------------------------
    state.setdefault("ui_scale_z", 1.0)
    state.setdefault("load_mode", "auto")
