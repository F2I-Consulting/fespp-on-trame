"""List-based color editor for Discrete / Categorical properties.

Used in place of `_FesppColorOpacityEditor` (continuous LUT/PWF editor) when
the active property's `propKind` is DiscreteProperty or CategoricalProperty.
For these, ParaView's continuous transfer function makes little sense — each
distinct integer value is its own category and deserves an independently
chosen color. We render one row per unique value with a `VColorPicker` (hexa
+ alpha) bound to the matching slot of the LUT's `IndexedColors` /
`IndexedOpacities`. The alpha channel doubles as per-category opacity (the
NaN handling the user asked for).
"""
import colorsys
import re
import time

from trame.app import get_server
from trame.widgets import vuetify3, html
from paraview import simple as pvsimple

server = get_server()
state = server.state
controller = server.controller


# Mirror of FESPP's C++ MakeValidNodeName — see fespp_active.py for
# context. RESQML titles can contain characters (spaces, parens, ...)
# that FESPP strips when naming VTK arrays. The Trame state holds the
# original title; we may need the sanitized variant to look the array
# up.
_VTK_NAME_INVALID_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def _make_valid_vtk_name(name: str) -> str:
    if not name:
        return ""
    return _VTK_NAME_INVALID_RE.sub("", name)


def _find_array_in_store(store, name):
    if store is None or not name:
        return None
    arr = store.GetArray(name)
    if arr is not None:
        return arr
    sanitized = _make_valid_vtk_name(name)
    if sanitized != name:
        return store.GetArray(sanitized)
    return None


# Set LUT proxy properties via SMProxy directly: pvsimple's Proxy
# wrapper has a strict __setattr__ that rejects unknown names ("This
# class does not allow addition of new attributes...") — IndexedLookup,
# Annotations, IndexedColors, IndexedOpacities all trip it on PV6's
# PVLookupTable proxy in some configurations. The SMProxy path bypasses
# the wrapper.
def _set_int_property(lut, name: str, value: int) -> bool:
    if lut is None or lut.SMProxy is None:
        return False
    prop = lut.SMProxy.GetProperty(name)
    if prop is None:
        return False
    try:
        prop.SetElement(0, int(value))
        lut.SMProxy.UpdateVTKObjects()
        return True
    except Exception as e:
        print(f"[WARNING] _set_int_property({name}): {e}")
        return False


def _set_double_list_property(lut, name: str, values) -> bool:
    if lut is None or lut.SMProxy is None:
        return False
    prop = lut.SMProxy.GetProperty(name)
    if prop is None:
        return False
    try:
        prop.SetNumberOfElements(len(values))
        for i, v in enumerate(values):
            prop.SetElement(i, float(v))
        lut.SMProxy.UpdateVTKObjects()
        return True
    except Exception as e:
        print(f"[WARNING] _set_double_list_property({name}): {e}")
        return False


def _set_string_list_property(lut, name: str, values) -> bool:
    if lut is None or lut.SMProxy is None:
        return False
    prop = lut.SMProxy.GetProperty(name)
    if prop is None:
        return False
    try:
        prop.SetNumberOfElements(len(values))
        for i, v in enumerate(values):
            prop.SetElement(i, str(v))
        lut.SMProxy.UpdateVTKObjects()
        return True
    except Exception as e:
        print(f"[WARNING] _set_string_list_property({name}): {e}")
        return False


def _rgb01_to_hex(r, g, b, a=1.0):
    """Convert RGB(A) floats in [0..1] to a #RRGGBBAA hex string."""
    rr = max(0, min(255, int(round(r * 255))))
    gg = max(0, min(255, int(round(g * 255))))
    bb = max(0, min(255, int(round(b * 255))))
    aa = max(0, min(255, int(round(a * 255))))
    return f"#{rr:02X}{gg:02X}{bb:02X}{aa:02X}"


def _hex_to_rgba01(hex_str):
    h = (hex_str or "").lstrip("#")
    if len(h) < 6:
        return (0.5, 0.5, 0.5, 1.0)
    try:
        r = int(h[0:2], 16) / 255
        g = int(h[2:4], 16) / 255
        b = int(h[4:6], 16) / 255
        a = int(h[6:8], 16) / 255 if len(h) >= 8 else 1.0
        return (r, g, b, a)
    except ValueError:
        return (0.5, 0.5, 0.5, 1.0)


def _default_color_for_index(idx):
    """Distinct color per category index, golden-ratio hue distribution."""
    hue = (idx * 0.61803398875) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
    return (r, g, b, 1.0)


class CategoricalColorEditor(html.Div):
    """Per-category color list bound to LUT.IndexedColors /
    IndexedOpacities. Used in place of the continuous LUT/PWF editor
    when the active property's `propKind` is DiscreteProperty or
    CategoricalProperty — each distinct integer value is its own
    category and gets an independently-chosen colour. The alpha
    channel of each picker doubles as per-category opacity."""

    def __init__(self):
        super().__init__()
        # categorical_entries shape:
        #   [{"index": int, "value": str, "label": str, "color": "#RRGGBBAA"}, ...]
        # `index` is the slot in LUT.IndexedColors (0-based).
        state.setdefault("categorical_entries", [])
        # Sentinel pushed by VColorPicker update_modelValue:
        # {"index": ..., "color": "#RRGGBBAA"}. The handler below
        # applies it then resets the sentinel so the next colour tick
        # re-triggers the watcher (Trame ignores writes that don't
        # change the value).
        state.setdefault("cce_pending_change", None)

        with self:
            with vuetify3.VExpansionPanels(
                v_model=("cce_panels", [0]),
                multiple=True,
                elevation=0,
            ):
                with vuetify3.VExpansionPanel(elevation=0):
                    vuetify3.VExpansionPanelTitle("Categories")
                    vuetify3.VDivider()
                    with vuetify3.VExpansionPanelText(classes="pa-2"):
                        # Empty-state: nothing to show until a Discrete/Categorical
                        # property is active and its values have been resolved.
                        html.Div(
                            "No categories",
                            v_if="!categorical_entries || categorical_entries.length === 0",
                            classes="text-caption text-medium-emphasis",
                        )
                        # One row per category — VColorPicker hexa+alpha covers
                        # both color and per-category opacity in one widget.
                        with html.Div(
                            v_for="(entry, idx) in (categorical_entries || [])",
                            key="entry.index",
                            classes="d-flex align-center mb-1",
                        ):
                            with vuetify3.VMenu(close_on_content_click=False):
                                with vuetify3.Template(v_slot_activator="{ props }"):
                                    with vuetify3.VBtn(
                                        v_bind="props",
                                        elevation=0,
                                        size="small",
                                        variant="text",
                                        classes="px-1 mr-2",
                                    ):
                                        vuetify3.VIcon(
                                            "mdi-circle",
                                            color=("entry.color ? entry.color.slice(0,7) : '#808080'",),
                                        )
                                vuetify3.VColorPicker(
                                    model_value=("entry.color",),
                                    update_modelValue=(
                                        "cce_pending_change = { index: entry.index, color: $event }"
                                    ),
                                    modes=("['hexa']",),
                                    classes="w-100",
                                    divided=True,
                                    landscape=True,
                                    max_width=300,
                                )
                            html.Span(
                                "{{ entry.label }}",
                                classes="text-body-2 ml-1",
                            )
                            html.Span(
                                "({{ entry.value }})",
                                classes="text-caption text-medium-emphasis ml-2",
                                v_if="entry.label !== entry.value",
                            )

        # Default values on the kwargs: the very first Trame flush at
        # startup may pre-date the setdefault on these state vars
        # (depends on import order). Without defaults Trame raises
        # TypeError when it invokes the handler without the kwarg.
        @state.change("active_color_array_name", "active_property_kind")
        def _on_active_change(active_color_array_name=None, active_property_kind=None, **_):
            kind = active_property_kind or ""
            if kind in ("DiscreteProperty", "CategoricalProperty") and active_color_array_name:
                self._refresh(active_color_array_name)
            else:
                state.categorical_entries = []

        @state.change("cce_pending_change")
        def _on_pending_change(cce_pending_change=None, **_):
            if not cce_pending_change:
                return
            try:
                idx = int(cce_pending_change.get("index"))
                color = cce_pending_change.get("color") or ""
                self._apply_color_change(idx, color)
            except (TypeError, ValueError):
                pass
            finally:
                state.cce_pending_change = None

    def _refresh(self, array_name: str):
        """Rebuild state.categorical_entries from the active source's
        VTK array + the LUT's IndexedColors / IndexedOpacities. Seeds
        a categorical preset on the first activation if the LUT has no
        per-category colours yet."""
        if not array_name:
            state.categorical_entries = []
            return
        _t0 = time.perf_counter()

        view = pvsimple.GetActiveView()
        active_source = pvsimple.GetActiveSource()
        active_name = ""
        if active_source is not None:
            for (sid, _), s in pvsimple.GetSources().items():
                if s is active_source:
                    active_name = sid
                    break
        print(f"[PERF cce] enter array={array_name!r} active_source={active_name!r}")
        if active_source is None or view is None:
            state.categorical_entries = []
            return

        _t = time.perf_counter()
        try:
            vtk_obj = active_source.GetClientSideObject()
            vtk_out = vtk_obj.GetOutputDataObject(0) if vtk_obj else None
            if vtk_out is None:
                state.categorical_entries = []
                return
            vtk_arr = None
            for store in (
                vtk_out.GetCellData() if hasattr(vtk_out, 'GetCellData') else None,
                vtk_out.GetPointData() if hasattr(vtk_out, 'GetPointData') else None,
            ):
                arr = _find_array_in_store(store, array_name)
                if arr is not None:
                    vtk_arr = arr
                    # Use the actual VTK name (the title we got may be
                    # the un-sanitized RESQML one).
                    actual_name = arr.GetName()
                    if actual_name and actual_name != array_name:
                        array_name = actual_name
                    break
            if vtk_arr is None or vtk_arr.GetNumberOfComponents() != 1:
                print(f"[PERF cce] array {array_name!r} not found on active source — abort")
                state.categorical_entries = []
                return
            unique_vals = set()
            n = vtk_arr.GetNumberOfTuples()
            for i in range(n):
                v = vtk_arr.GetTuple1(i)
                if v != v:  # NaN
                    continue
                unique_vals.add(int(v))
            sorted_vals = sorted(unique_vals)
        except Exception as e:
            print(f"[WARNING] CategoricalColorEditor._refresh: array read failed: {e}")
            state.categorical_entries = []
            return
        _ms_scan = int((time.perf_counter() - _t) * 1000)
        print(f"[PERF cce] scan VTK array {n} cells → {len(sorted_vals)} uniques: {_ms_scan}ms")

        _t = time.perf_counter()
        lut = pvsimple.GetColorTransferFunction(array_name)
        annotations = []
        existing_colors = []
        existing_opacities = []
        if lut is not None and lut.SMProxy is not None:
            try:
                ann_prop = lut.SMProxy.GetProperty("Annotations")
                if ann_prop is not None:
                    annotations = [ann_prop.GetElement(i) for i in range(ann_prop.GetNumberOfElements())]
                col_prop = lut.SMProxy.GetProperty("IndexedColors")
                if col_prop is not None:
                    existing_colors = [col_prop.GetElement(i) for i in range(col_prop.GetNumberOfElements())]
                op_prop = lut.SMProxy.GetProperty("IndexedOpacities")
                if op_prop is not None:
                    existing_opacities = [op_prop.GetElement(i) for i in range(op_prop.GetNumberOfElements())]
            except Exception as e:
                print(f"[WARNING] read LUT props failed: {e}")

            # First-time activation: seed the LUT with a categorical
            # preset. Try a few well-known names — availability varies
            # between ParaView versions. Falls back to the golden-ratio
            # HSV palette below if no preset fills enough colours.
            if not existing_colors:
                for preset in ("Categorical 1", "Set 1", "Categorical", "Set 3"):
                    try:
                        lut.ApplyPreset(preset, True)
                        col_prop = lut.SMProxy.GetProperty("IndexedColors")
                        if col_prop is not None and col_prop.GetNumberOfElements() > 0:
                            existing_colors = [
                                col_prop.GetElement(i)
                                for i in range(col_prop.GetNumberOfElements())
                            ]
                            print(f"[PERF cce] applied preset {preset!r} ({len(existing_colors)//3} colors)")
                            break
                    except Exception:
                        continue
        ann_map = {}
        for j in range(0, len(annotations) - 1, 2):
            try:
                ann_map[int(float(annotations[j]))] = str(annotations[j + 1])
            except (ValueError, TypeError):
                pass
        _ms_read = int((time.perf_counter() - _t) * 1000)

        # Build entries; fill defaults for slots the LUT didn't have.
        _t = time.perf_counter()
        entries = []
        new_colors = []
        new_opacities = []
        new_annotations = []
        for i, v in enumerate(sorted_vals):
            label = ann_map.get(v, str(v))
            if (i + 1) * 3 <= len(existing_colors):
                r = existing_colors[i * 3]
                g = existing_colors[i * 3 + 1]
                b = existing_colors[i * 3 + 2]
            else:
                r, g, b, _ = _default_color_for_index(i)
            a = existing_opacities[i] if i < len(existing_opacities) else 1.0
            color_hex = _rgb01_to_hex(r, g, b, a)
            entries.append({
                "index": i,
                "value": str(v),
                "label": label,
                "color": color_hex,
            })
            new_colors.extend([r, g, b])
            new_opacities.append(a)
            new_annotations.extend([str(v), label])
        _ms_build = int((time.perf_counter() - _t) * 1000)

        state.categorical_entries = entries

        # Push the (possibly default-filled) colours back to the LUT
        # and switch to indexed lookup. EnableOpacityMapping=1 is
        # required for the mapper to consume IndexedOpacities;
        # without it alpha values are silently ignored and every
        # category renders fully opaque.
        _t = time.perf_counter()
        ok_lookup = _set_int_property(lut, "IndexedLookup", 1)
        ok_ann = _set_string_list_property(lut, "Annotations", new_annotations)
        ok_col = _set_double_list_property(lut, "IndexedColors", new_colors)
        ok_op = _set_double_list_property(lut, "IndexedOpacities", new_opacities)
        ok_eom = _set_int_property(lut, "EnableOpacityMapping", 1)
        _ms_push = int((time.perf_counter() - _t) * 1000)
        print(f"[PERF cce] LUT push lookup={ok_lookup} ann={ok_ann} col={ok_col} op={ok_op} eom={ok_eom}: {_ms_push}ms")

        # No Render here — the active.reservoir handler issues the
        # final Render after its own ColorBy + LUT setup. Calling
        # Render again would double the GPU paint cost.
        _ms_total = int((time.perf_counter() - _t0) * 1000)
        print(f"[PERF cce] read={_ms_read}ms build={_ms_build}ms push={_ms_push}ms TOTAL={_ms_total}ms")

    def _apply_color_change(self, index: int, hex_color: str):
        """Apply a single colour-picker change to the LUT and refresh
        the matching categorical_entries row.

        Per-category alpha (`IndexedOpacities[idx]`) only affects the
        rendered image when:
          (a) ``IndexedLookup = 1`` on the LUT (in indexed-mode lookup),
          (b) ``EnableOpacityMapping = 1``,
          (c) every display using the LUT actually re-binds it after
              the property mutation (PV's mapper caches the LUT
              snapshot).
        We re-assert (a) and (b) on every change and re-bind every
        active display's LookupTable below, otherwise the alpha edit
        silently no-ops on subsequent renders."""
        array_name = state.active_color_array_name or ""
        if not array_name:
            return
        r, g, b, a = _hex_to_rgba01(hex_color)
        lut = pvsimple.GetColorTransferFunction(array_name)
        if lut is None or lut.SMProxy is None:
            return

        col_prop = lut.SMProxy.GetProperty("IndexedColors")
        op_prop = lut.SMProxy.GetProperty("IndexedOpacities")
        colors = []
        if col_prop is not None:
            colors = [col_prop.GetElement(i) for i in range(col_prop.GetNumberOfElements())]
        ops = []
        if op_prop is not None:
            ops = [op_prop.GetElement(i) for i in range(op_prop.GetNumberOfElements())]

        if index * 3 + 2 < len(colors):
            colors[index * 3] = r
            colors[index * 3 + 1] = g
            colors[index * 3 + 2] = b
            _set_double_list_property(lut, "IndexedColors", colors)
        # Always grow the opacity list to cover the modified index;
        # PV silently treats a too-short list as fully opaque.
        while len(ops) <= index:
            ops.append(1.0)
        ops[index] = a
        _set_double_list_property(lut, "IndexedOpacities", ops)
        # Re-assert the indexed-lookup flags after every edit (PV may
        # reset them when ColorBy is re-applied elsewhere).
        _set_int_property(lut, "IndexedLookup", 1)
        _set_int_property(lut, "EnableOpacityMapping", 1)

        # Force every display currently bound to this LUT to refresh
        # its mapper. Re-assigning .LookupTable triggers PV's mapper
        # to re-read the LUT including the just-changed
        # IndexedOpacities; without this, surface rendering keeps
        # using the cached opacity vector (alpha edits look like
        # no-ops).
        view = pvsimple.GetActiveView()
        if view is not None:
            for sid, src in pvsimple.GetSources().items():
                try:
                    disp = pvsimple.GetDisplayProperties(src, view=view)
                    if disp is None:
                        continue
                    cur_lut = getattr(disp, "LookupTable", None)
                    if cur_lut is not None and cur_lut.SMProxy is lut.SMProxy:
                        disp.LookupTable = lut
                        # Color array bound to this LUT? if so, also
                        # re-set ColorArrayName to push the update
                        # through the mapper's full re-config path.
                        try:
                            ca = list(disp.ColorArrayName)
                            if ca and ca[1] == array_name:
                                disp.ColorArrayName = ca
                        except Exception:
                            pass
                except Exception:
                    continue

        entries = list(state.categorical_entries or [])
        if 0 <= index < len(entries):
            entries[index] = {**entries[index], "color": hex_color}
            state.categorical_entries = entries

        try:
            pvsimple.Render()
            controller.view_update()
        except Exception:
            pass
