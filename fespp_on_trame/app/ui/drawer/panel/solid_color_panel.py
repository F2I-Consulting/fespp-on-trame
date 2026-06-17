"""Colors & Opacity panel — driven by the active tree node.

Two modes, derived from the active node type (no manual toggle):
- Active node = a representation → VColorPicker for solid color + opacity
  (writes display.DiffuseColor / Opacity; never touches ColorArrayName,
  which is owned by the eye state in ui_active_array_by_rep).
- Active node = a data-array (Property/TimeSeries/MultiRealization/...)
  → embedded ColorOpacityEditor for that array's LUT/PWF. The editor
  edits the global LUT for the array name, so the changes apply
  whenever the eye is open (now or later).

State (keyed by rep path):
- solid_color_by_rep : {path: "#RRGGBBAA"} — solid color picked by the user.
"""
from trame.app import get_server
from trame.widgets import vuetify3, html
from paraview import simple as pvsimple

from .color_editor import _FesppColorOpacityEditor, _apply_nan_color_to_lut
from .categorical_color_editor import CategoricalColorEditor

from fespp_on_trame.app.core.engine import source_resolver

server = get_server()
state = server.state
controller = server.controller


def _hex_to_rgb01(hex_str):
    h = (hex_str or "").lstrip("#")
    if len(h) < 6:
        return (0.5, 0.5, 0.5)
    try:
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
    except ValueError:
        return (0.5, 0.5, 0.5)


def _hex_to_alpha(hex_str):
    h = (hex_str or "").lstrip("#")
    if len(h) >= 8:
        try:
            return int(h[6:8], 16) / 255
        except ValueError:
            return 1.0
    return 1.0


def _displays_for_rep(rep_path):
    """Resolve every (display, source, view) the active rep is rendered through,
    via the PER-VIEW resolver in the drawer-target view — the same path
    ColorBy uses (visibility → apply_color_array → displays_for_rep_path).

    This is the proxy set that actually PAINTS the rep in the target panel:
    the per-(rep, view) EnergisticsExtractor (+ its threshold chain + clip
    output) for non-IjkGrid reps (e.g. a WellboreTrajectory polyline), and the
    per-view slicers/volume/threshold leaves for IjkGrid reps. The shared
    ExtractBlock source from `controller.get_rep_source` is `Hide()`n in the
    render view by `RepInScene._ensure_extractor`, so the tint must go on the
    per-view proxies to be visible."""
    from trame.app import get_server as _gs
    source_registry = getattr(_gs().context, "source_registry", None)
    if source_registry is None:
        return []
    pv_view, _panel = source_resolver.target_view_and_panel()
    if pv_view is None:
        pv_view = pvsimple.GetActiveView()
    if pv_view is None:
        return []
    displays = source_resolver.displays_for_rep_path(
        source_registry, rep_path, view=pv_view,
    )
    return [(d, None, pv_view) for d in displays]


def _apply_solid(rep_path, color_hex):
    """Push DiffuseColor + Opacity onto every display rendering rep_path.
    Never touches ColorArrayName — that's owned by ui_active_array_by_rep
    (the eye state). When the eye is open on a data-array, ColorBy wins
    and the diffuse color is dormant; when the eye is barred, this color
    is what the user sees."""
    targets = _displays_for_rep(rep_path)
    # MarkerFrame: the display(s) `_displays_for_rep` returns are the
    # frame's MAIN extractor, permanently hidden for a marker frame
    # (`_channelless_frame`). The VISIBLE markers render via SEPARATE
    # per-marker extractors — the tint must fan onto those too. Markers
    # shown LATER pick up `solid_color_by_rep` at creation in
    # MarkerFrameRep._create_child_extractor.
    pv_view, _panel = source_resolver.target_view_and_panel()
    if pv_view is None:
        pv_view = pvsimple.GetActiveView()
    ris = source_resolver._scene_rep_for_view(rep_path, pv_view) if pv_view is not None else None
    if ris is not None:
        try:
            for d in ris.visible_marker_displays():
                targets.append((d, None, pv_view))
        except Exception:
            pass
    if not targets:
        return
    r, g, b = _hex_to_rgb01(color_hex)
    a = _hex_to_alpha(color_hex)
    for display, _source, _view in targets:
        display.DiffuseColor = [r, g, b]
        display.AmbientColor = [r, g, b]
        display.Opacity = a
    # Render + push on the drawer target view (pinned mode pushes
    # to the wrong panel via `view_update` alone).
    source_resolver.render_and_push_target(controller)


# ------------------------------------------------------------------
# Per-marker SolidColor — markers display MULTIPLE at a time, each
# independently recolourable. `active_representation_path` collapses a
# marker to its MarkerFrame, so the SINGLE-marker identity is read from
# `ui_active_node_well[0]`; the MARKER SET (frame) node recolours all.

def _engine_tree():
    from fespp_on_trame.app.core import engine as _engine_pkg
    return getattr(_engine_pkg, "_tree", None)


def _active_marker_path():
    """Path of the active well node WHEN it is a single 'Marker', else
    None (frame/set or any non-marker active node)."""
    tree = _engine_tree()
    nodes = state.ui_active_node_well or []
    if tree is None or not nodes:
        return None
    nid = nodes[0]
    try:
        if (tree.find_type(nid) or "") != "Marker":
            return None
        return tree.find_path(nid)
    except Exception:
        return None


def _is_marker_frame_path(path):
    tree = _engine_tree()
    if tree is None or not path:
        return False
    try:
        nid = tree.find_node_id(path)
        return (tree.find_type(nid) or "") == "MarkerFrame"
    except Exception:
        return False


def _markers_of_frame(frame_path):
    """Loaded marker paths whose MarkerFrame rep is `frame_path`."""
    tree = _engine_tree()
    if tree is None or not frame_path:
        return []
    out = []
    for m in (state.ui_loaded_marker_paths or []):
        try:
            nid = tree.find_node_id(m)
            r_id = tree.find_representation_node(nid) if nid is not None else None
            if r_id is not None and tree.find_path(r_id) == frame_path:
                out.append(m)
        except Exception:
            pass
    return out


def _apply_marker_solid(rep_path, marker_path, color_hex):
    """Push a SolidColor tint onto ONE marker's display in the drawer
    target view (the persisted `solid_color_by_marker` entry covers the
    not-yet-shown case via MarkerFrameRep._create_child_extractor)."""
    pv_view, _panel = source_resolver.target_view_and_panel()
    if pv_view is None:
        pv_view = pvsimple.GetActiveView()
    ris = source_resolver._scene_rep_for_view(rep_path, pv_view) if pv_view is not None else None
    if ris is not None:
        try:
            ris.set_marker_color(marker_path, color_hex)
        except Exception:
            pass
    source_resolver.render_and_push_target(controller)


class SolidColorPanel(html.Div):
    """Colors & Opacity panel.

    Visible whenever the user has an active node on a loaded representation.
    The panel content is selected by the *type* of the active node:
    - Active = the rep itself → solid color picker (DiffuseColor + Opacity).
    - Active = a data-array (Property/TimeSeries/...) → that array's
      LUT/PWF editor.
    """

    def __init__(self):
        super().__init__(v_if="active_representation_path && active_representation_path.length > 0")

        state.setdefault("active_representation_path", "")
        state.setdefault("active_representation_has_properties", False)
        state.setdefault("solid_color_by_rep", {})
        # Per-marker solid colour {marker_path: "#RRGGBBAA"} — markers
        # are recoloured individually; falls back to solid_color_by_rep
        # [frame] (uniform default) when a marker has no own colour.
        state.setdefault("solid_color_by_marker", {})
        state.setdefault("solid_color_next_idx", 0)
        state.setdefault("solid_color", "#808080FF")
        # Drives the per-tree-node color chip. Read by tree_views.py templates.
        # Maps rep_path → "#color" (no array active on the rep, i.e. SolidColor)
        # or "PROPERTY" (an array eye is open on the rep).
        state.setdefault("tree_chip_color_by_path", {})
        # True when the active node is a marker / MarkerFrame — drives the
        # global "Marker display" panel (orientation + size) visibility.
        state.setdefault("sc_active_is_marker", False)

        # "active node is a data-array" if the active_color_array_name is
        # non-empty. We use that as the panel-mode selector.
        _is_array_active = (
            "active_color_array_name && active_color_array_name.length > 0"
        )

        with self:
            with vuetify3.VExpansionPanels(v_model=("sc_panels", [0, 1]), multiple=True, elevation=0):
                with vuetify3.VExpansionPanel(elevation=0, value=0):
                    with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                        html.Span("Colors & Opacity", classes="text-body-2 font-weight-medium")
                        vuetify3.VSpacer()
                        vuetify3.VChip(
                            f"{{{{ ({_is_array_active}) ? 'LUT/PWF' : 'Solid' }}}}",
                            size="x-small",
                            variant="tonal",
                            color=(f"({_is_array_active}) ? 'purple' : 'blue'",),
                            classes="font-italic mr-2",
                        )
                    with vuetify3.VExpansionPanelText(classes="pa-2"):
                        # Active node = rep → solid color picker
                        with html.Div(v_if=f"!({_is_array_active})"):
                            vuetify3.VColorPicker(
                                v_model=("solid_color",),
                                modes=("['hexa']",),
                                divided=True,
                                landscape=True,
                                classes="w-100",
                                max_width=300,
                            )

                        # Active node = data-array → LUT/PWF editor.
                        # Continuous: classic LUT/PWF editor (gradients).
                        # Discrete/Categorical: per-category VColorPicker list
                        # bound to LUT.IndexedColors / IndexedOpacities.
                        _is_categorical = (
                            "active_property_kind === 'DiscreteProperty'"
                            " || active_property_kind === 'CategoricalProperty'"
                        )
                        with html.Div(
                            v_if=f"({_is_array_active}) && !({_is_categorical})",
                            classes="pa-0",
                        ):
                            coe = _FesppColorOpacityEditor()
                        with html.Div(
                            v_if=f"({_is_array_active}) && ({_is_categorical})",
                            classes="pa-0",
                        ):
                            CategoricalColorEditor()

                # Marker display options (orientation + size). Shown only in
                # a marker context. GLOBAL — clearly flagged so the user
                # knows it applies to EVERY marker in EVERY view.
                with vuetify3.VExpansionPanel(
                    elevation=0, value=1, v_if="sc_active_is_marker",
                ):
                    with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                        html.Span("Marker display", classes="text-body-2 font-weight-medium")
                        vuetify3.VSpacer()
                        vuetify3.VChip(
                            "global",
                            size="x-small",
                            variant="tonal",
                            color="deep-orange",
                            classes="font-italic mr-2",
                        )
                    with vuetify3.VExpansionPanelText(classes="pa-2"):
                        html.Div(
                            "Applies to ALL markers (in every view).",
                            classes="text-caption text-medium-emphasis mb-3",
                        )
                        vuetify3.VSwitch(
                            v_model=("marker_orientation",),
                            label="Orientation (disc oriented by dip/azimuth, otherwise sphere)",
                            density="compact",
                            hide_details=True,
                            color="deep-orange",
                            classes="mb-3",
                        )
                        vuetify3.VSlider(
                            v_model=("marker_size",),
                            label="Size",
                            min=1, max=200, step=1,
                            thumb_label=True,
                            density="compact",
                            hide_details=True,
                            color="deep-orange",
                            # Apply on RELEASE only (rebuilding markers re-runs
                            # the collector over the whole selection).
                            end=(controller.apply_marker_options,),
                        )

        # --- Override array-name lookup to use state instead of active source ---
        # The state-driven name carries the property TITLE for MR
        # properties (e.g. "VOIL"), because other consumers
        # (threshold_dispatch, stats) expect the title there, while the
        # actual VTK LUT for an MR property is keyed by the suffixed
        # name ("VOIL_real_23"). Both `_update_color_editor` (refresh
        # writer) and `_get_array_name_from_state` (ptc's
        # `on_colors_changed` uses it to find the LUT to write back to)
        # share the SAME resolver, so the writeback round-trips through
        # the SAME LUT.
        _original_get_array_name = coe.get_representation_color_array_name

        def _target_panel_id():
            return (
                getattr(state, "drawer_target_view_id", "") or ""
                or getattr(state, "fespp_active_panel_id", "") or ""
            )

        def _target_scene():
            from trame.app import get_server as _gs
            sr = getattr(_gs().context, "scene_registry", None)
            if sr is None:
                return None
            return sr.get_scene(_target_panel_id())

        def _resolve_base_array_name(raw_name):
            """Step 1: title → REAL VTK array name on the per-view source,
            suffixed for MR properties. The render path keys its per-view
            scoped LUT on whichever name actually exists — the SANITIZED
            name for grid / surface properties, but the RAW title for a
            wellbore CHANNEL (its POINT array is named with the verbatim
            title). The COE MUST resolve the SAME key, else the continuous
            editor reads a different, never-coloured LUT (empty graph).
            `source_resolver.real_base_name` probes the source so both
            cases converge."""
            if not raw_name:
                return raw_name
            from fespp_on_trame.app.core import engine as _engine_pkg
            from fespp_on_trame.app.core.engine import realization_dispatch
            pv_view, _panel = source_resolver.target_view_and_panel()
            base = source_resolver.real_base_name(
                raw_name, state.active_representation_path or "", pv_view,
            )
            tree = getattr(_engine_pkg, "_tree", None)
            if tree is None:
                return base
            active_nodes = state.ui_active_node_reservoir or []
            if not active_nodes:
                return base
            try:
                array_path = tree.find_path(active_nodes[0])
            except Exception:
                array_path = None
            if not array_path:
                return base
            if not realization_dispatch.is_multirealization_property(tree, array_path):
                return base
            panel_id = _target_panel_id()
            idx = realization_dispatch.get_active_realization_for_view(
                state, panel_id, array_path,
            )
            if idx is None:
                idx = realization_dispatch.default_realization_for(
                    state, tree, array_path,
                )
            if idx is None:
                return base
            return realization_dispatch.suffixed_array_name(base, int(idx))

        def _resolve_coe_lut(raw_name):
            """Resolve raw_name → (base_name, scoped_lut, scoped_name)
            for the drawer target view's scene.

            `base_name` — what `ColorArrayName` is set to on the
              display (MR-suffixed or the raw name).
            `scoped_lut` — the per-(scene, base) LUT proxy, created
              and seeded from the global template on demand.
            `scoped_name` — the registration name PV uses for that
              LUT, returned so the COE writeback path can look it up
              via `GetColorTransferFunction(scoped_name)`.

            Returns `(base_name, None, base_name)` when no scene owns
            the target view (bootstrap) — caller falls back to the
            global LUT singleton."""
            base = _resolve_base_array_name(raw_name)
            scene = _target_scene()
            if scene is None or not base:
                return base, None, base
            scene_lut = scene.get_or_create_lut(base)
            scene.get_or_create_pwf(base)
            return base, scene_lut, scene._scoped_tf_name(base)

        def _get_array_name_from_state():
            """Used by ptc's `on_colors_changed` to resolve which LUT
            to write back to. Return the SCOPED name so PV's
            `GetColorTransferFunction(scoped_name)` returns the per-
            view LUT we registered (not the global singleton). The
            display's `ColorArrayName` itself is still the base name
            (set by `ColorBy` and unrelated to LUT identity)."""
            name = state.active_color_array_name
            if not name:
                return _original_get_array_name()
            _base, _scene_lut, scoped = _resolve_coe_lut(name)
            return ["CELLS", scoped]

        coe.get_representation_color_array_name = _get_array_name_from_state

        def _data_range_for_active_array(base_name):
            """VTK data range for the rep's array currently bound to
            the active node. Walk the rep's source proxy + cell data
            info — gives us the real range whether or not PV has
            ColorBy'd it yet (the scope LUT seeded from PV's singleton
            may still be at [0, 1] when `update_color_editor` runs
            BEFORE the eye-toggle's `apply_color_array`). Returns `None`
            when the array isn't found (non-property nodes, MR
            realization not picked yet, etc.).

            Prefers the **target scene's** `RepInScene.source()`
            (per-view EnergisticsExtractor) so MR `_real_<idx>` arrays
            are visible — the shared `ExtractBlock` from
            `source_registry.get` doesn't expose those."""
            if not base_name:
                return None
            try:
                rep_path = state.active_representation_path or ""
                if not rep_path:
                    return None
                from trame.app import get_server as _gs
                ctx = _gs().context
                # Wellbore channel: read its OWN per-channel extractor
                # (materialised even when hidden) — the frame's primary
                # source() carries no channel array. None for non-channels
                # → fall through to the normal per-view / legacy source.
                source = source_resolver.channel_source_for(
                    getattr(state, "active_color_array_path", "") or ""
                )
                scene_registry = (
                    getattr(ctx, "scene_registry", None) if source is None else None
                )
                if scene_registry is not None:
                    panel_id = (
                        getattr(state, "drawer_target_view_id", "") or ""
                        or getattr(state, "fespp_active_panel_id", "") or ""
                    )
                    if panel_id:
                        scene = scene_registry.get_scene(panel_id)
                        if scene is not None:
                            rep_in_scene = scene.get_rep(rep_path)
                            if rep_in_scene is not None:
                                try:
                                    source = rep_in_scene.source()
                                except Exception:
                                    source = None
                if source is None:
                    source_registry = getattr(ctx, "source_registry", None)
                    if source_registry is not None:
                        source = source_registry.get(rep_path)
                if source is None:
                    return None
                source.UpdatePipelineInformation()
                info = source.GetDataInformation()
                if info is None:
                    return None
                for getter in (
                    info.GetCellDataInformation,
                    info.GetPointDataInformation,
                ):
                    try:
                        di = getter()
                        if di is None:
                            continue
                        ai = di.GetArrayInformation(base_name)
                        if ai is not None:
                            r = ai.GetComponentRange(0)
                            if r and r[0] < r[1]:
                                return (float(r[0]), float(r[1]))
                    except Exception:
                        continue
            except Exception:
                pass
            return None

        # --- Public controller hook ---
        def _update_color_editor(array_name):
            """Programmatic refresh on property activation / target view
            switch / realization change. Push the target view's
            per-(scene, array) LUT's RGBPoints into the COE state so
            the gradient displayed in the panel matches the LUT
            actually applied in that view's displays.

            Both read (`scene_lut.RGBPoints` here) and writeback (via
            `_get_array_name_from_state` → ptc's
            `GetColorTransferFunction(scoped_name)`) hit the same
            per-view LUT, keeping the round-trip lossless.

            Range guard: a scope LUT freshly created from a global
            singleton (before `apply_color_array` has rescaled it on
            first MR activation) carries PV's default [0, 1] range. We
            compute the data range from the VTK array and rescale the
            scope LUT BEFORE pushing, so ptc's `on_colors_changed`
            writeback doesn't lock in those default values."""
            state.active_color_array_name = array_name
            try:
                coe.update_scalar_range()
            except Exception:
                pass
            base, scene_lut, scoped = _resolve_coe_lut(array_name)
            lut = scene_lut if scene_lut is not None else pvsimple.GetColorTransferFunction(scoped)
            if lut is None:
                return
            data_range = _data_range_for_active_array(base)
            if data_range is not None:
                # Widen a degenerate range (constant / all-NaN→0 log) so
                # the LUT/PWF aren't rescaled to zero width — which would
                # make the COE gradient divide by zero (addColorStop
                # non-finite). Keep it in lockstep with update_scalar_range.
                data_range = source_resolver.nondegenerate_range(
                    data_range[0], data_range[1],
                )
            if data_range is not None and len(lut.RGBPoints) >= 4:
                try:
                    cur_min = float(lut.RGBPoints[0])
                    cur_max = float(lut.RGBPoints[-4])
                    # Rescale ONLY when the scope LUT is still at PV's
                    # default [0, 1] range (fresh GetColorTransferFunction
                    # creates a Cool-to-Warm preset spanning [0, 1]).
                    # Once the range carries data values — whether from a
                    # prior ColorBy auto-rescale or a user COE edit —
                    # leave its RGBPoints alone so we don't wipe the
                    # user's custom stops.
                    is_default_range = (cur_min == 0.0 and cur_max == 1.0)
                    if is_default_range and data_range != (0.0, 1.0):
                        lut.RescaleTransferFunction(data_range[0], data_range[1])
                        # Rescale the matching PWF in lockstep — a PWF
                        # stuck at the default [0, 1] positions while
                        # the LUT is at scalar data range causes the
                        # COE component's opacity-shaped background to
                        # sample out-of-range, rendering as a solid
                        # leftmost-stop colour.
                        try:
                            scene_for_pwf_rescale = _target_scene()
                            if scene_for_pwf_rescale is not None:
                                scoped_pwf = scene_for_pwf_rescale.get_or_create_pwf(base)
                                if scoped_pwf is not None:
                                    pwf_pts = list(getattr(scoped_pwf, "Points", []) or [])
                                    pwf_default = (
                                        len(pwf_pts) >= 8
                                        and float(pwf_pts[0]) == 0.0
                                        and float(pwf_pts[-4]) == 1.0
                                    )
                                    if pwf_default and data_range != (0.0, 1.0):
                                        scoped_pwf.RescaleTransferFunction(
                                            data_range[0], data_range[1],
                                        )
                        except Exception:
                            pass
                except Exception:
                    pass
            _apply_nan_color_to_lut(lut)
            if len(lut.RGBPoints) >= 4:
                # Push the LUT's actual RGBPoints + the PWF's actual
                # Points so the COE state mirrors the rendered transfer
                # functions. Read opacities from the per-scene PWF when
                # available (pushing a fixed all-opaque ramp would wipe
                # the user's per-stop opacity edits on every target /
                # realization / eye change); fall back to an all-opaque
                # ramp only when no PWF is wired yet.
                smin = lut.RGBPoints[0]
                smax = lut.RGBPoints[-4]
                scene_for_pwf = _target_scene()
                opacity_points = None
                if scene_for_pwf is not None:
                    try:
                        scene_pwf = scene_for_pwf.get_or_create_pwf(base)
                        if scene_pwf is not None and getattr(scene_pwf, "Points", None):
                            opacity_points = list(scene_pwf.Points)
                    except Exception:
                        opacity_points = None
                if not opacity_points or len(opacity_points) < 8:
                    opacity_points = [
                        smin, 1.0, 0.5, 0.0,
                        smax, 1.0, 0.5, 0.0,
                    ]
                coe.update_colors(lut.RGBPoints)
                coe.update_opacities(opacity_points)

        controller.update_color_editor = _update_color_editor

        @state.change(
            "drawer_target_view_id",
            "ui_active_realization_by_array_by_view",
            "ui_active_array_by_rep_by_view",
        )
        def _refresh_coe_on_target_or_realization_change(**_):
            """Re-push the COE whenever:
              - the drawer target view changes (target-view picker),
              - any view's MR realization changes (MR picker),
              - any view's per-rep colored array changes (the eye
                toggle in the tree — first ColorBy on a property only
                runs THEN, so the scoped LUT only gets its data-range
                gradient at that point).
            Fires for ALL active properties (MR or not) because per-
            view LUT isolation is universal — view-1's COE state
            isn't valid in view-2 even for plain single-realization
            properties."""
            name = state.active_color_array_name
            if not name:
                return
            _update_color_editor(name)

        @state.change("active_representation_path", "ui_active_node_well")
        def _on_path_change(active_representation_path, **_):
            # Sync the picker value to whatever solid color the active
            # node has. Also fires on `ui_active_node_well` so switching
            # between markers of the SAME frame (active_representation_path
            # stays the frame) re-seeds the wheel from the marker's own
            # colour. Default tint assigned at load if none picked yet.
            path = state.active_representation_path
            # Marker context (a MarkerFrame selected, or a single Marker leaf)
            # → show the global Marker-display panel (orientation + size).
            state.sc_active_is_marker = bool(
                path and (_is_marker_frame_path(path) or _active_marker_path() is not None)
            )
            if not path:
                return
            marker_path = _active_marker_path()
            if marker_path is not None:
                by_marker = state.solid_color_by_marker or {}
                frame_default = (state.solid_color_by_rep or {}).get(path, "#808080FF")
                state.solid_color = by_marker.get(marker_path, frame_default)
                return
            state.solid_color = (state.solid_color_by_rep or {}).get(path, "#808080FF")

        @state.change("solid_color")
        def _on_color_change(solid_color, **_):
            path = state.active_representation_path
            if not path:
                return
            marker_path = _active_marker_path()
            if marker_path is not None:
                # SINGLE marker active → recolour ONLY this marker.
                by_marker = dict(state.solid_color_by_marker or {})
                by_marker[marker_path] = solid_color
                state.solid_color_by_marker = by_marker
                _apply_marker_solid(path, marker_path, solid_color)
                return
            if _is_marker_frame_path(path):
                # MARKER SET active → recolour ALL its markers uniformly
                # (the frame colour is the default for markers shown later).
                colors = dict(state.solid_color_by_rep or {})
                colors[path] = solid_color
                state.solid_color_by_rep = colors
                by_marker = dict(state.solid_color_by_marker or {})
                for m in _markers_of_frame(path):
                    by_marker[m] = solid_color
                state.solid_color_by_marker = by_marker
                _apply_solid(path, solid_color)   # fans onto every visible marker
                return
            # Non-marker rep.
            colors = dict(state.solid_color_by_rep or {})
            colors[path] = solid_color
            state.solid_color_by_rep = colors
            _apply_solid(path, solid_color)

        @state.change("solid_color_by_rep", "ui_active_array_by_rep", "solid_color_by_marker")
        def _refresh_tree_chip_colors(solid_color_by_rep, ui_active_array_by_rep, **_):
            # Tree chip:
            # - "PROPERTY" sentinel (rainbow gradient) when an array is the
            #   active eye on the rep (i.e. the rep is colored by data).
            # - "MULTICOLOR" sentinel on a MarkerFrame whose child markers
            #   carry 2+ distinct colours; the shared colour when uniform.
            # - Solid hex color otherwise.
            colors = solid_color_by_rep or {}
            active_map = ui_active_array_by_rep or {}
            by_marker = state.solid_color_by_marker or {}
            chips = {}
            for path, color in colors.items():
                if path in active_map:
                    chips[path] = "PROPERTY"
                else:
                    chips[path] = color
            # MarkerFrame nodes: uniform-vs-multicolor from the EFFECTIVE
            # colour of every loaded marker (explicit per-marker colour, or
            # the frame default for un-edited ones). Only frames that have
            # at least one individually-coloured marker are recomputed; a
            # frame with no per-marker entry keeps its existing single
            # solid_color_by_rep swatch above.
            tree = _engine_tree()
            if tree is not None and by_marker:
                frames = set()
                for m_path in by_marker:
                    try:
                        nid = tree.find_node_id(m_path)
                        r_id = tree.find_representation_node(nid) if nid is not None else None
                        if r_id is None or (tree.find_type(r_id) or "") != "MarkerFrame":
                            continue
                        f_path = tree.find_path(r_id)
                    except Exception:
                        continue
                    if f_path:
                        frames.add(f_path)
                for f_path in frames:
                    frame_default = colors.get(f_path) or "#808080FF"
                    eff = set(
                        (by_marker.get(m) or frame_default)
                        for m in _markers_of_frame(f_path)
                    )
                    if len(eff) >= 2:
                        chips[f_path] = "MULTICOLOR"
                    elif len(eff) == 1:
                        chips[f_path] = next(iter(eff))
            state.tree_chip_color_by_path = chips
