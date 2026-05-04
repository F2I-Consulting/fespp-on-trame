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


def _rep_display(rep_path):
    source = controller.get_rep_source(rep_path) if hasattr(controller, "get_rep_source") else None
    if source is None:
        return None, None, None
    view = pvsimple.GetActiveView()
    if view is None:
        return None, None, source
    display = pvsimple.GetDisplayProperties(source, view=view)
    return display, view, source


def _ijkgrid_displays():
    """For IjkGrid reps there is no ExtractBlock — display is fanned out across
    several ParaView sources (slicervolume, sliceri/j/k_*, IjkGrid_*). Return
    [(display, source), ...] for every one of them present in the active view."""
    view = pvsimple.GetActiveView()
    if view is None:
        return [], None
    out = []
    for source_id, src in pvsimple.GetSources().items():
        name = source_id[0]
        if name == 'slicervolume' or name.startswith(('sliceri_', 'slicerj_', 'slicerk_', 'IjkGrid_')):
            disp = pvsimple.GetDisplayProperties(src, view=view)
            if disp is not None:
                out.append((disp, src))
    return out, view


def _displays_for_rep(rep_path):
    """Resolve every (display, source, view) the active rep is rendered through.
    Single entry for ExtractBlock-backed reps, multiple for IjkGrid."""
    if state.ui_active_node_reservoir_type_rep == 'IjkGrid':
        pairs, view = _ijkgrid_displays()
        return [(d, s, view) for (d, s) in pairs]
    display, view, source = _rep_display(rep_path)
    if display is None:
        return []
    return [(display, source, view)]


def _apply_solid(rep_path, color_hex):
    """Push DiffuseColor + Opacity onto every display rendering rep_path.
    Never touches ColorArrayName — that's owned by ui_active_array_by_rep
    (the eye state). When the eye is open on a data-array, ColorBy wins
    and the diffuse color is dormant; when the eye is barred, this color
    is what the user sees."""
    targets = _displays_for_rep(rep_path)
    if not targets:
        return
    r, g, b = _hex_to_rgb01(color_hex)
    a = _hex_to_alpha(color_hex)
    last_view = None
    for display, source, view in targets:
        last_view = view
        display.DiffuseColor = [r, g, b]
        display.AmbientColor = [r, g, b]
        display.Opacity = a
    pvsimple.Render(view=last_view)
    controller.view_update()


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
        state.setdefault("solid_color_next_idx", 0)
        state.setdefault("solid_color", "#808080FF")
        # Drives the per-tree-node color chip. Read by tree_views.py templates.
        # Maps rep_path → "#color" (no array active on the rep, i.e. SolidColor)
        # or "PROPERTY" (an array eye is open on the rep).
        state.setdefault("tree_chip_color_by_path", {})

        # "active node is a data-array" if the active_color_array_name is
        # non-empty. We use that as the panel-mode selector.
        _is_array_active = (
            "active_color_array_name && active_color_array_name.length > 0"
        )

        with self:
            with vuetify3.VExpansionPanels(v_model=("sc_panels", [0]), multiple=True, elevation=0):
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

        # --- Override array-name lookup to use state instead of active source ---
        _original_get_array_name = coe.get_representation_color_array_name

        def _get_array_name_from_state():
            name = state.active_color_array_name
            if name:
                return ["CELLS", name]
            return _original_get_array_name()

        coe.get_representation_color_array_name = _get_array_name_from_state

        # --- Public controller hook ---
        def _update_color_editor(array_name):
            state.active_color_array_name = array_name
            try:
                coe.update_scalar_range()
            except Exception:
                pass
            lut = pvsimple.GetColorTransferFunction(array_name)
            if lut:
                _apply_nan_color_to_lut(lut)
                if len(lut.RGBPoints) >= 4:
                    smin = lut.RGBPoints[0]
                    smax = lut.RGBPoints[-4]
                    all_opaque = [smin, 1.0, 0.5, 0.0, smax, 1.0, 0.5, 0.0]
                    coe.update_colors(lut.RGBPoints)
                    coe.update_opacities(all_opaque)

        controller.update_color_editor = _update_color_editor

        @state.change("active_representation_path")
        def _on_path_change(active_representation_path, **_):
            # Sync the picker value to whatever solid color this rep has
            # (default tint assigned at load if none picked yet).
            if not active_representation_path:
                return
            color = (state.solid_color_by_rep or {}).get(active_representation_path, "#808080FF")
            state.solid_color = color

        @state.change("solid_color")
        def _on_color_change(solid_color, **_):
            path = state.active_representation_path
            if not path:
                return
            colors = dict(state.solid_color_by_rep or {})
            colors[path] = solid_color
            state.solid_color_by_rep = colors
            _apply_solid(path, solid_color)

        @state.change("solid_color_by_rep", "ui_active_array_by_rep")
        def _refresh_tree_chip_colors(solid_color_by_rep, ui_active_array_by_rep, **_):
            # Tree chip:
            # - "PROPERTY" sentinel (rainbow gradient) when an array is the
            #   active eye on the rep (i.e. the rep is colored by data).
            # - Solid hex color otherwise.
            colors = solid_color_by_rep or {}
            active_map = ui_active_array_by_rep or {}
            chips = {}
            for path, color in colors.items():
                if path in active_map:
                    chips[path] = "PROPERTY"
                else:
                    chips[path] = color
            state.tree_chip_color_by_path = chips
