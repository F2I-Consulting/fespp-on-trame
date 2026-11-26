"""The colour tables of a 3D view (overhaul slice 7).

ParaView's `GetColorTransferFunction(name)` is a singleton keyed by the
array name: every display coloured by the same name would share one table,
and a colour edit in one view would bleed into every other. A view gets its
own table and opacity function per property, registered under
`<property>__<view id>` and seeded from the global one, so it starts with
the gradient in use.

ONE table per property, shared by its realizations: the `_real_<idx>`
suffix is stripped from the KEY ('SOIL_real_23' and 'SOIL_real_24' share a
table). Only the key: displays keep their suffixed array name, and the
unpinned range still rescales to each realization's data.

`ViewLuts` used to be the LUT half of the legacy `ViewScene`, which now
composes it (its `get_or_create_lut` / `get_or_create_pwf` delegate here):
the tables outlive the scene's retirement."""
from fespp_on_trame.engine.utils.naming import strip_realization_suffix

# what a duplicated view copies from its reference view: continuous
# (RGBPoints / Points), categorical (IndexedColors / IndexedOpacities /
# Annotations), and the scalar / log / vector flags commonly edited
LUT_COPIED = (
    "RGBPoints", "NanColor", "NanOpacity", "ColorSpace",
    "EnableOpacityMapping", "UseLogScale",
    "VectorMode", "VectorComponent",
    "IndexedColors", "IndexedOpacities", "Annotations",
)
PWF_COPIED = ("Points", "UseLogScale")


def draws_translucent(indexed_opacities, curve_points):
    """Whether a colour table draws something translucent: an indexed table
    (painting by code, `indexed_opacities` its codes' opacities, None when
    it is not indexed) when a code is below full opacity; else when its
    opacity curve ([x, opacity, midpoint, sharpness] per point) goes below
    full opacity somewhere."""
    if indexed_opacities is not None:
        return any(float(o) < 0.999 for o in indexed_opacities)
    return any(float(curve_points[i]) < 0.999 for i in range(1, len(curve_points), 4))


def _copy(src, dst, attrs, note):
    for attr in attrs:
        try:
            val = getattr(src, attr)
            # a new list: ParaView's vector properties must not alias the
            # other proxy's storage (an edit on one would move both)
            if isinstance(val, (list, tuple)):
                val = list(val)
            setattr(dst, attr, val)
        except Exception as exc:
            print(f"[fespp] {note}: {attr} not copied ({exc})", flush=True)


class ViewLuts:
    """The colour tables and opacity functions of one 3D view."""

    def __init__(self, view_id):
        self.view_id = view_id
        self._luts = {}    # property (no realization suffix) -> lut proxy
        self._pwfs = {}    # property -> opacity function proxy

    def _scoped(self, base):
        return f"{base}__{self.view_id}"

    def lut(self, array_name):
        """The view's table for `array_name`, made on first use (seeded from
        the global table of the same name); None for no name."""
        base = strip_realization_suffix(array_name)
        if not base:
            return None
        cached = self._luts.get(base)
        if cached is not None:
            return cached
        from paraview import simple as pvsimple
        lut = pvsimple.GetColorTransferFunction(self._scoped(base))
        try:
            template = pvsimple.GetColorTransferFunction(base)
            if template is not None and template is not lut and getattr(template, "RGBPoints", None):
                _copy(template, lut, LUT_COPIED, "color table seed")
        except Exception as exc:
            print(f"[fespp] color table seed ({self.view_id}, {base}):", exc, flush=True)
        self._luts[base] = lut
        self._settle_opacity(base)
        return lut

    def _settle_opacity(self, base):
        """The opacity mapping kept on only while the table draws something
        translucent. The reader turns it on whenever a file gives a property
        opacities, even all at 1, and the global table this one is seeded
        from carries it; VTK draws ANY table with the mapping on in its
        translucent passes — on Volve's grid a frame 5 times slower on the
        processor, 3 times on a GPU. Only ever turned off here: the card
        turns it on when an edit makes something translucent."""
        lut = self._luts.get(base)
        if lut is None:
            return
        try:
            if not int(getattr(lut, "EnableOpacityMapping", 0) or 0):
                return
            from fespp_on_trame.engine import categorical_palette
            indexed = ([c["opacity"] for c in categorical_palette.read(lut)]
                       if categorical_palette.is_indexed(lut) else None)
            pwf = self._pwfs.get(base) or getattr(lut, "ScalarOpacityFunction", None)
            curve = list(getattr(pwf, "Points", []) or []) if pwf is not None else []
            if not draws_translucent(indexed, curve):
                lut.EnableOpacityMapping = 0
        except Exception as exc:
            print(f"[fespp] opacity mapping ({self.view_id}, {base}):", exc, flush=True)

    def pwf(self, array_name):
        """The view's opacity function for `array_name`, made on first use:
        flat opacity 1 (ParaView seeds a 0→1 ramp, which would make the
        lowest value transparent and switch the opacity mapping on —
        suppressing the NaN opacity); a curve the reader drew is kept."""
        base = strip_realization_suffix(array_name)
        if not base:
            return None
        cached = self._pwfs.get(base)
        if cached is not None:
            return cached
        from paraview import simple as pvsimple
        pwf = pvsimple.GetOpacityTransferFunction(self._scoped(base))
        try:
            template = pvsimple.GetOpacityTransferFunction(base)
            if template is not None and template is not pwf and getattr(template, "Points", None):
                _copy(template, pwf, PWF_COPIED, "opacity seed")
        except Exception as exc:
            print(f"[fespp] opacity seed ({self.view_id}, {base}):", exc, flush=True)
        try:
            pts = list(getattr(pwf, "Points", []) or [])
            if (len(pts) == 8 and abs(float(pts[1])) < 1e-6
                    and abs(float(pts[-3]) - 1.0) < 1e-6):
                # only the untouched two-stop 0→1 default, its X extent kept
                pwf.Points = [float(pts[0]), 1.0, 0.5, 0.0, float(pts[-4]), 1.0, 0.5, 0.0]
        except Exception as exc:
            print(f"[fespp] opacity default ({self.view_id}, {base}):", exc, flush=True)
        self._pwfs[base] = pwf
        self._settle_opacity(base)
        return pwf

    def release(self):
        """The view's tables deleted (the global ones are not the view's)."""
        try:
            from paraview import simple as pvsimple
        except Exception as exc:
            print("[fespp] color tables not released:", exc, flush=True)
            return
        for proxy in list(self._luts.values()) + list(self._pwfs.values()):
            if proxy is None:
                continue
            try:
                pvsimple.Delete(proxy)
            except Exception as exc:
                print(f"[fespp] color table not deleted ({self.view_id}):", exc, flush=True)
        self._luts.clear()
        self._pwfs.clear()
