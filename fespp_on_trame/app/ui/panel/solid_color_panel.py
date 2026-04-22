"""Merged Colors & Opacity panel.

Drives per-representation coloring with a Property/Solid toggle:
- Solid → VColorPicker writes display.DiffuseColor + Opacity directly.
- Property → embedded ColorOpacityEditor for the active array's LUT/PWF.

Each non-IjkGrid representation is materialized as its own ParaView source
(see RepSources / ExtractBlock). This panel drives that source's display
directly via ColorBy + DiffuseColor + Opacity — no BlockColors detour.

State layout (keyed by representation path):
- solid_color_mode_by_rep  : {path: "property" | "solid"}
- solid_color_by_rep       : {path: "#RRGGBBAA"}
- last_property_array_by_rep: {path: "<array name>"} remembered so that
  toggling Property re-applies the last property the user had selected.
"""
from trame.app import get_server
from trame.widgets import vuetify3, html
from paraview import simple as pvsimple

from .color_editor import _FesppColorOpacityEditor, _apply_nan_color_to_lut

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


def _clear_color_array(display):
    """Disable scalar coloring on a display. PV6 has two regressions here:
    - pvsimple.ColorBy(display, None) raises 'invalid association string NONE'
    - display.ColorArrayName = ['', ''] is silently rejected (the proxy keeps
      the previous array name, so DiffuseColor never takes over)
    Working path: call vtkSMPVRepresentationProxy::SetScalarColoring on the
    underlying SMProxy with an empty name; that actually clears the binding."""
    sm_proxy = getattr(display, "SMProxy", None)
    if sm_proxy is not None:
        try:
            sm_proxy.SetScalarColoring("", 0)  # 0 == vtkDataObject.POINT, ignored when name is empty
            sm_proxy.UpdateVTKObjects()
            return
        except Exception as e:
            print(f"[DEBUG SolidPanel] _clear_color_array: SetScalarColoring failed: {e}")
    try:
        display.ColorArrayName = ['', '']
    except Exception:
        pass


def _apply_solid(rep_path, color_hex):
    targets = _displays_for_rep(rep_path)
    print(f"[DEBUG SolidPanel] _apply_solid path={rep_path!r} color={color_hex!r} targets={len(targets)}")
    if not targets:
        print(f"[DEBUG SolidPanel] _apply_solid: no display — abort")
        return
    r, g, b = _hex_to_rgb01(color_hex)
    a = _hex_to_alpha(color_hex)
    last_view = None
    for display, source, view in targets:
        last_view = view
        _clear_color_array(display)
        display.DiffuseColor = [r, g, b]
        display.AmbientColor = [r, g, b]
        display.Opacity = a
        print(f"[DEBUG SolidPanel] _apply_solid:  → src={source} ColorArrayName={list(display.ColorArrayName)} Visibility={display.Visibility}")
    pvsimple.Render(view=last_view)
    controller.view_update()


def _apply_property(rep_path):
    """Restore property-based coloring for this rep. If we recorded a last
    array, re-apply it; otherwise just lift the solid override."""
    targets = _displays_for_rep(rep_path)
    array_name = (state.last_property_array_by_rep or {}).get(rep_path)
    # Fallback: when the rep is activated, controller.update_color_editor may set
    # state.active_color_array_name to the same value twice in a row (once before
    # active_representation_path is set, once after) — the second call doesn't
    # fire @state.change due to value diff, so _on_active_array_change never
    # records it. Trust state.active_color_array_name as the live source of truth.
    if not array_name:
        array_name = state.active_color_array_name or None
    print(f"[DEBUG SolidPanel] _apply_property path={rep_path!r} last_array={array_name!r} targets={len(targets)}")
    if not targets:
        print(f"[DEBUG SolidPanel] _apply_property: no display — abort")
        return
    last_view = None
    for display, source, view in targets:
        last_view = view
        applied = False
        if array_name and source is not None:
            try:
                cell_info = source.GetCellDataInformation()
                point_info = source.GetPointDataInformation()
                if cell_info and cell_info.GetArray(array_name):
                    pvsimple.ColorBy(display, ("CELLS", array_name))
                    applied = True
                elif point_info and point_info.GetArray(array_name):
                    pvsimple.ColorBy(display, ("POINTS", array_name))
                    applied = True
            except Exception as e:
                print(f"[DEBUG SolidPanel] _apply_property: ColorBy failed for {source}: {e}")
                applied = False
        if not applied:
            _clear_color_array(display)
            display.Opacity = 1.0
        print(f"[DEBUG SolidPanel] _apply_property:  → src={source} applied={applied} ColorArrayName={list(display.ColorArrayName)}")
    pvsimple.Render(view=last_view)
    controller.view_update()


class SolidColorPanel(html.Div):
    """Toggle property / solid color per representation, with a color+alpha picker."""

    def __init__(self):
        super().__init__(v_if="active_representation_path && active_representation_path.length > 0")

        state.setdefault("active_representation_path", "")
        state.setdefault("active_representation_has_properties", False)
        state.setdefault("solid_color_mode_by_rep", {})
        state.setdefault("solid_color_by_rep", {})
        state.setdefault("last_property_array_by_rep", {})
        state.setdefault("solid_color_mode", "property")
        state.setdefault("solid_color", "#808080FF")

        with self:
            with vuetify3.VExpansionPanels(v_model=("sc_panels", [0]), multiple=True, elevation=0):
                with vuetify3.VExpansionPanel(elevation=0, value=0):
                    with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                        html.Span("Colors & Opacity", classes="text-body-2 font-weight-medium")
                        vuetify3.VSpacer()
                        vuetify3.VChip(
                            "{{ solid_color_mode === 'solid' ? 'Solid' : 'Property' }}",
                            size="x-small",
                            variant="tonal",
                            # Blue for default (Property, OR Solid when no property exists),
                            # orange for Solid that the user explicitly toggled on.
                            color=(
                                "(solid_color_mode === 'solid' && active_representation_has_properties)"
                                " ? 'orange' : 'blue'",
                            ),
                            classes="font-italic mr-2",
                        )
                    with vuetify3.VExpansionPanelText(classes="pa-2"):
                        with vuetify3.VBtnToggle(
                            v_if="active_representation_has_properties",
                            v_model=("solid_color_mode",),
                            mandatory=True,
                            density="comfortable",
                            color="blue",
                            divided=True,
                            classes="mb-3 w-100",
                        ):
                            vuetify3.VBtn("Property", value="property", size="small")
                            vuetify3.VBtn("Solid", value="solid", size="small")

                        # Solid mode → color+alpha picker
                        with html.Div(v_if="solid_color_mode === 'solid'"):
                            vuetify3.VColorPicker(
                                v_model=("solid_color",),
                                modes=("['hexa']",),
                                divided=True,
                                landscape=True,
                                classes="w-100",
                                max_width=300,
                            )

                        # Property mode → LUT/PWF editor for the active array
                        with html.Div(
                            v_if=(
                                "solid_color_mode !== 'solid'"
                                " && active_color_array_name"
                                " && active_color_array_name.length > 0"
                            ),
                            classes="pa-0",
                        ):
                            coe = _FesppColorOpacityEditor()

        # --- Override array-name lookup to use state instead of active source ---
        _original_get_array_name = coe.get_representation_color_array_name

        def _get_array_name_from_state():
            name = state.active_color_array_name
            if name:
                return ["CELLS", name]
            return _original_get_array_name()

        coe.get_representation_color_array_name = _get_array_name_from_state

        # --- Public controller hook (called by _activate_realization & friends) ---
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

        @state.change("active_representation_path", "active_representation_has_properties")
        def _on_path_change(active_representation_path, active_representation_has_properties, **_):
            if not active_representation_path:
                return
            stored_mode = (state.solid_color_mode_by_rep or {}).get(active_representation_path)
            # Reps without any property are solid-only — the toggle is hidden by v_if.
            if not active_representation_has_properties:
                mode = "solid"
            else:
                mode = stored_mode or "property"
            color = (state.solid_color_by_rep or {}).get(active_representation_path, "#808080FF")
            state.solid_color_mode = mode
            state.solid_color = color

        @state.change("solid_color_mode")
        def _on_mode_change(solid_color_mode, **_):
            path = state.active_representation_path
            print(f"[DEBUG SolidPanel] mode change → {solid_color_mode!r} (active_rep_path={path!r})")
            if not path:
                return
            modes = dict(state.solid_color_mode_by_rep or {})
            modes[path] = solid_color_mode
            state.solid_color_mode_by_rep = modes
            if solid_color_mode == "solid":
                _apply_solid(path, state.solid_color)
            else:
                _apply_property(path)

        @state.change("solid_color")
        def _on_color_change(solid_color, **_):
            path = state.active_representation_path
            if not path:
                return
            colors = dict(state.solid_color_by_rep or {})
            colors[path] = solid_color
            state.solid_color_by_rep = colors
            if state.solid_color_mode == "solid":
                _apply_solid(path, solid_color)

        def _record_active_array_for_rep():
            path = state.active_representation_path
            array_name = state.active_color_array_name
            if not path or not array_name:
                return
            d = dict(state.last_property_array_by_rep or {})
            if d.get(path) == array_name:
                return
            d[path] = array_name
            state.last_property_array_by_rep = d

        @state.change("active_color_array_name")
        def _on_active_array_change(active_color_array_name, **_):
            # Remember which array was last picked for the currently active rep,
            # so toggling Property later can re-apply it.
            _record_active_array_for_rep()

        @state.change("active_representation_path")
        def _on_path_change_record(**_):
            # Path may arrive AFTER active_color_array_name has already been set
            # (and a re-set with the same value won't refire @state.change).
            _record_active_array_for_rep()

        def _reapply_active_solid():
            """Re-assert Solid coloring for the active rep if the user toggled
            Solid earlier. Called after _activate_realization, which always runs
            ColorBy(...) and would otherwise revert the rendering to property."""
            path = state.active_representation_path
            if not path:
                return
            mode = (state.solid_color_mode_by_rep or {}).get(path)
            if mode != "solid":
                return
            color = (state.solid_color_by_rep or {}).get(path, "#808080FF")
            _apply_solid(path, color)

        controller.reapply_active_solid_mode = _reapply_active_solid
