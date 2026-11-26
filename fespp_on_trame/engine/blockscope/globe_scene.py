"""GlobeScene — a PdcScene rendering the shared PDC ON THE EARTH.

Contract
--------
Input:     the same as PdcScene (view id, pv_view, the ActiveSource facade,
           the scheduler) + the Earth texture path.
Behaviour: the composite rep's source is ``GeoSource`` — one ProgrammableFilter
           per globe view re-projecting the active PDC (projected CRS,
           EPSG code) to Earth-centred coordinates (engine/geo.py), rebound
           when the active source flips (ETP connect) exactly like the plain
           scene self-heals. The Z exaggeration is RADIAL: applied to the
           elevation inside the projection, never through ``rep.Scale``.
           Also owns the textured WGS84 globe; the marks (``set_marks`` from
           boot, which knows the tree) — one screen-space pin + name per
           object and, for a grid, the twelve edges of its extent, all in a
           single producer; and the camera framings: the whole Earth above
           the data, or ONE object flown onto (never the union of several).
Reads:     the projected data bounds (camera) and the projected-CRS extent of
           each block (the boxes).
Writes:    its own reps only — never trame state.
"""
import numpy as np
from paraview import simple as pvsimple

from fespp_on_trame.engine import geo
from fespp_on_trame.engine.blockscope.pdc_scene import PdcScene

# Colour of the marks: grid boxes, leaders and pins.
F2I_GREEN = (0.56, 0.76, 0.12)

# Constants of the camera rule (GlobeScene._apply_camera_rule).
# Smallest half-size of the locked clip box, in metres.
_CLIP_MIN_HALF = 5000.0
# Earth opacity in a close framing: translucent, not hidden, because the
# data is below the ellipsoid.
EARTH_OPACITY_CLOSE = 0.35
# How many pixels across a mark must stay to be findable.
_MARK_PIXELS = 16.0
# tan(15 deg): half of the view's 30 deg angle.
_TAN_HALF_FOV = 0.26794919243112270


# One texture proxy per image, for the whole session and every Globe view.
# NEVER delete one: ParaView does not release the image memory (see
# GlobeScene.set_texture), so a create-and-delete cycle is a pure leak, and
# a 16 384 px image is 402 MB before mipmaps.
_EARTH_TEXTURES = {}


def _earth_texture_proxy(path):
    """The shared texture proxy of the image at `path`, created on first use;
    None for no path."""
    if not path:
        return None
    proxy = _EARTH_TEXTURES.get(path)
    if proxy is None:
        proxy = pvsimple.CreateTexture(path)
        _EARTH_TEXTURES[path] = proxy
    return proxy


class GeoSource:
    """Source provider (``get_source()`` duck-type of ActiveSource) = the
    active PDC re-projected to ECEF by one ProgrammableFilter."""

    def __init__(self, active):
        self._active = active
        self._filter = None
        self._bound = None
        self.epsg = 0
        self.zscale = 1.0

    def get_source(self):
        # re-projects what displays chain on (the derived-arrays filter),
        # so a computed property reaches the Earth like the others
        from fespp_on_trame.engine.derived_arrays import display_source_of
        src = display_source_of(self._active)
        if src is None:
            return None
        if self._filter is None:
            self._filter = pvsimple.ProgrammableFilter(Input=src)
            self._filter.OutputDataSetType = "vtkPartitionedDataSetCollection"
            self._bound = src
            self._apply()
        elif self._bound is not src:
            self._filter.Input = src
            self._bound = src
        return self._filter

    def configure(self, epsg=None, zscale=None) -> bool:
        """Set the projected CRS (EPSG code) and/or the radial Z
        exaggeration; True when either changed (the filter script is then
        rewritten). A non-positive exaggeration is ignored."""
        changed = False
        if epsg is not None:
            try:
                code = int(epsg)
            except (TypeError, ValueError):
                code = 0
            if code != self.epsg:
                self.epsg = code
                changed = True
        if zscale is not None:
            try:
                zs = float(zscale)
            except (TypeError, ValueError):
                zs = 0.0
            if zs > 0 and zs != self.zscale:
                self.zscale = zs
                changed = True
        if changed and self._filter is not None:
            self._apply()
        return changed

    def _apply(self):
        self._filter.Script = geo.PROJECT_FILTER_SCRIPT % {
            "epsg": self.epsg, "zscale": self.zscale}

    def release(self):
        f, self._filter = self._filter, None
        self._bound = None
        if f is not None:
            try:
                pvsimple.Delete(f)
            except Exception:
                pass


class GlobeScene(PdcScene):
    """A PdcScene drawn on the Earth: data, globe, marks and camera framings
    (see the module docstring)."""

    def __init__(self, view_id, pv_view, active, scheduler=None, texture=None):
        self.geo = GeoSource(active)
        self._active = active
        super().__init__(view_id, pv_view, self.geo, scheduler)
        self._texture = texture
        self._earth = self._earth_rep = None
        self._marks = {}      # selector -> {text, trep} (the name billboard)
        # every box, leader and pin of the view in ONE producer: the geometry
        # is rebuilt in numpy, so no proxy is created or destroyed when the
        # eyes, the EPSG or the exaggeration change
        self._marks_src = self._marks_rep = None
        self._mark_spec = {}  # last (labels, shown) — replayed on a re-project
        self._framed = None   # selector the camera is framed on, if any
        self._min_span = 0.0  # ground size a mark must reach to be legible
        self._in_cam = False
        self.mode = "earth"
        self.earth_opacity = 1.0

    @property
    def epsg(self):
        return self.geo.epsg

    def _show_composite(self, src):
        # The EPCCollector renders as a surface only thanks to the plugin's
        # <RepresentationType view="RenderView" type="Surface"/> hint
        # (Energistics.xml). The Globe shows the GeoSource filter INSTEAD of
        # the collector, and a ProgrammableFilter carries no such hint — so
        # ParaView falls back to its size heuristic and hands back "Outline"
        # past a few hundred MB: the grid then appears on the Earth as a bare
        # white bounding box. Pin the type rather than inherit that default.
        rep = super()._show_composite(src)
        if rep is not None:
            try:
                rep.Representation = "Surface"
            except Exception as exc:
                print(f"[fespp] globe rep type error ({self.view_id}):", exc,
                      flush=True)
        return rep

    # ------------------------------------------------------------------
    # projection parameters

    def set_zscale(self, z) -> None:
        # radial exaggeration lives in the projection; rep.Scale stays 1
        if self.geo.configure(zscale=z):
            self._rebuild_marks()
            self._mark_dirty()

    def set_epsg(self, code) -> None:
        if self.geo.configure(epsg=code):
            self.reconcile()
            self._rebuild_marks()
            self._mark_dirty()

    # ------------------------------------------------------------------
    # the Earth + the locator

    def ensure_earth(self):
        if self._earth_rep is not None or self.pv_view is None:
            return
        from fespp_on_trame.engine.sources import leaf_rep
        self._earth = pvsimple.ProgrammableSource(
            Script=geo.EARTH_SOURCE_SCRIPT, OutputDataSetType="vtkPolyData")
        rep = leaf_rep.show_composite(self._earth, self.pv_view)
        rep.ColorArrayName = ["POINTS", ""]
        if self._texture:
            try:
                rep.Texture = _earth_texture_proxy(self._texture)
            except Exception as exc:
                print(f"[fespp] globe texture error ({self.view_id}):", exc, flush=True)
        rep.Interpolation = "Gouraud"
        # Without these the texture is sampled nearest-neighbour and reads as
        # blocks the moment the camera leaves the whole-Earth framing.
        # Mipmaps also kill the shimmer on the limb, where a texel is edge-on.
        for prop, value in (("InterpolateTextures", 1), ("UseMipmapTextures", 1)):
            try:
                setattr(rep, prop, value)
            except Exception:
                pass
        rep.Opacity = self.earth_opacity
        # translucent globe (data framing): only the near surface must show
        # through — without culling the far side of the Earth (its inside
        # faces) reads through the ground as an upside-down antipode
        try:
            rep.BackfaceRepresentation = "Cull Backface"
        except Exception:
            pass
        self._earth_rep = rep
        try:
            rep.Pickable = 0
        except Exception:
            pass

    def set_texture(self, path) -> None:
        """Swap the Earth imagery — the quality selector.

        Goes through the shared cache: `pvsimple.Delete` on a texture proxy
        does NOT give the image memory back. Creating one per switch and
        deleting the previous grows the process by the size of the image at
        every switch until it dies on std::bad_alloc, which reaches the
        browser as "Connection closed". Each level is therefore built at most
        once per session and simply re-bound after that."""
        if path == self._texture:
            return
        self._texture = path
        if self._earth_rep is None:
            return
        try:
            self._earth_rep.Texture = _earth_texture_proxy(path)
        except Exception as exc:
            print(f"[fespp] globe texture ({self.view_id}):", exc, flush=True)
        self._mark_dirty()

    # ------------------------------------------------------------------
    # marks: a screen-space pin + name for every object, plus the extent box
    # of every grid — all of them in ONE producer (see set_marks)

    def set_marks(self, labels, shown=None) -> None:
        """``labels`` = {selector: (title, is_grid)} of everything MARKABLE
        (loaded); ``shown`` = the subset currently visible, or None for "all".

        A grid gets the twelve edges of its extent — the real one, its corners
        taken in the projected CRS and put through the data's own transform.
        Everything gets a pin on the ellipsoid above it and its name.

        The pin, not the box, is what says "here" from space: at the
        whole-Earth framing a 5 km grid is a third of a pixel, and at its true
        depth it is sealed inside the Earth mesh, which is inscribed and sags
        nearly 2 km below the surface. The pin is sized in PIXELS, so it makes
        no claim about how big anything is.

        All the boxes, leaders and pins of the view live in ONE producer, so
        an eye click rebuilds a numpy array instead of creating and deleting
        ParaView proxies per mark (tens of milliseconds each)."""
        self._mark_spec = {"labels": dict(labels or {}), "shown": shown}
        self._rebuild_marks()

    def _rebuild_marks(self) -> None:
        from fespp_on_trame.engine.sources import leaf_rep
        labels = self._mark_spec.get("labels") or {}
        shown = self._mark_spec.get("shown")
        bounds = self._each_block_bounds_projected(list(labels)) if labels else {}
        # Geometry for what is SHOWN; labels for everything LOADED. The
        # geometry is one numpy rebuild, so filtering it costs nothing — but a
        # label is two ParaView proxies, slow to create, so an eye click only
        # hides or shows a label, never destroys it.
        marks, anchored = [], []
        for sel, (title, is_grid) in labels.items():
            b = bounds.get(sel)
            if b is None:
                continue
            anchor = ((b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0)
            anchored.append((sel, title, anchor))
            if shown is None or sel in shown:
                marks.append((b if is_grid else None, anchor))
        pd = geo.marks_polydata(marks, self.geo.epsg, self.geo.zscale,
                                self._min_span)
        if self._marks_src is None:
            # Nothing to draw yet (no data, or no usable CRS): do NOT create
            # the proxy. ParaView cannot build a representation for a trivial
            # producer that has no output, and it raises rather than saying so.
            if pd.GetNumberOfPoints() == 0:
                return
            self._marks_src = pvsimple.TrivialProducer(
                registrationName=f"fesppGlobeMarks_{self.view_id}")
            self._publish(pd)
            rep = leaf_rep.show_composite(self._marks_src, self.pv_view)
            rep.ColorArrayName = ["POINTS", ""]
            rep.DiffuseColor = list(F2I_GREEN)
            rep.AmbientColor = list(F2I_GREEN)
            rep.Ambient = 0.4
            rep.LineWidth = 2
            # a pickable non-PDC source resolves through the flat-index lookup
            # to the FIRST loaded block — a silent wrong answer, not an error
            rep.Pickable = 0
            self._marks_rep = rep
        else:
            self._publish(pd)
        self._sync_labels(anchored, shown)
        self._set_marks_visible(self.mode == "earth")
        self._mark_dirty()

    # ------------------------------------------------------------------
    # the camera rule — what makes "on the Earth" work at every zoom

    # NO OBSERVER ON THE CAMERA. A Python observer here is a segfault, and the
    # body it runs is irrelevant — an empty lambda crashes just the same.
    # On one wheel notch:
    #   ProgrammableFilter in the pipeline + camera observer + a Selectors
    #   re-commit                                        -> SIGSEGV
    #   any one of those three removed                   -> survives
    # A Globe view is the only view that has a Python ProgrammableFilter in
    # the rendered pipeline (GeoSource) AND wants to react to the camera.
    # Selecting anything re-commits Selectors, so the projection filter is
    # dirty; the next wheel notch dollies AND renders inside ONE interactor
    # callback, so the filter's Python script re-executes while the camera's
    # ModifiedEvent re-enters the interpreter through vtkPythonCommand. The
    # interpreter state is corrupted and the process dies — which reaches the
    # browser as "Connection closed".
    # The rule is therefore driven from frame() only, which is our own code.

    def _on_camera(self):
        if self._in_cam:
            return
        self._in_cam = True
        try:
            self._apply_camera_rule()
        except Exception as exc:
            print(f"[fespp] globe camera rule ({self.view_id}):", exc, flush=True)
        finally:
            self._in_cam = False

    def _apply_camera_rule(self):
        """Clipping and mark size for the framing we just landed in.

        Sized from the DATA, not from where the camera happens to be: with no
        observer this runs once per framing, so it has to hold across the
        whole range the wheel can then reach from there.

        ParaView pins near = far/1000 over everything visible, so with the
        6 378 km Earth drawn the near plane sits at ~22 km and anything
        smaller is clipped. Hiding the globe would avoid that, but would empty
        "show this view's data on the Earth" of its point. Locking the clip
        bounds to a box around the data fixes the cause instead: a ±20 km box
        brings the near plane down to about 40 m.
        """
        cam = self.pv_view.GetActiveCamera()
        if cam is None:
            return
        fp, pos = cam.GetFocalPoint(), cam.GetPosition()
        d = float(np.linalg.norm(np.array(pos) - np.array(fp)))
        if d <= 0.0:
            return
        if self.mode == "earth":
            # The whole planet is in frame and the data is 25 000 km away, so
            # a 38 km near plane clips nothing. Locking here would be actively
            # wrong: a box around the data has its far plane closer than the
            # Earth's limb, which would cut the disc's edge off.
            self.pv_view.LockBounds = 0
        else:
            b = self.visible_bounds() or self.data_bounds()
            diag = (float(np.linalg.norm([b[1] - b[0], b[3] - b[2], b[5] - b[4]]))
                    if b else 0.0)
            # `half` sets BOTH how close the wheel can get (the near plane
            # lands at roughly half/400) and how much Earth is drawn around
            # the object (out to roughly 2.5 * half). Scaling it to the object
            # keeps that ratio right at any size: on a 1 km block (`half` held
            # at _CLIP_MIN_HALF), about 12 m and 12 km of ground; on a 17 km
            # field, 170 m and 170 km.
            half = max(_CLIP_MIN_HALF, 4.0 * diag)
            self.pv_view.MaxClipBounds = [
                fp[0] - half, fp[0] + half, fp[1] - half, fp[1] + half,
                fp[2] - half, fp[2] + half]
            self.pv_view.LockBounds = 1
        # MARK SIZE. A 5 km field is a third of a pixel from space, so a mark
        # must not be smaller than a legible patch of screen. Past the
        # crossover the real extent is bigger and wins on its own.
        span = _MARK_PIXELS * 2.0 * d * _TAN_HALF_FOV / max(
            float(getattr(self.pv_view, "ViewSize", [900, 700])[1]), 1.0)
        if self._min_span <= 0 or abs(span - self._min_span) > 0.15 * self._min_span:
            self._min_span = span
            self._rebuild_marks()

    def _publish(self, pd):
        """Hand new geometry to the producer. All three calls are needed: the
        client-side swap alone leaves the ServerManager layer holding the old
        bounds, so the camera framing and the near plane are computed against
        geometry that is no longer drawn."""
        self._marks_src.GetClientSideObject().SetOutput(pd)
        self._marks_src.MarkModified(self._marks_src)
        self._marks_src.UpdatePipeline()

    def _sync_labels(self, anchored, shown):
        """One billboard per LOADED object, on its pin. Kept alive when the
        eye closes and merely hidden — see _rebuild_marks."""
        from fespp_on_trame.engine.sources import leaf_rep
        keep = {sel for sel, _t, _a in anchored}
        for sel in [s for s in self._marks if s not in keep]:
            self._delete_mark(self._marks.pop(sel))
        pins = geo.pin_points([a for _s, _t, a in anchored], self.geo.epsg)
        for k, (sel, title, _anchor) in enumerate(anchored):
            m = self._marks.get(sel)
            if m is None:
                text = pvsimple.Text(Text=title or "")
                trep = leaf_rep.show_composite(text, self.pv_view)
                trep.TextPropMode = "Billboard 3D Text"
                trep.Justification = "Left"
                trep.DisplayOffset = [14, 6]
                trep.Color = [1.0, 1.0, 1.0]
                trep.Bold = 1
                # No Pickable here, unlike the box rep: a TextSourceRepresentation
                # does not carry the property, and a Text source has no cells for
                # SelectSurfaceCells to hit — so a label cannot be picked in the
                # first place.
                m = {"text": text, "trep": trep}
                self._marks[sel] = m
            m["text"].Text = title or ""
            m["want"] = 1 if (shown is None or sel in shown) else 0
            if k < len(pins):
                m["trep"].BillboardPosition = [float(v) for v in pins[k]]

    def _set_marks_visible(self, on):
        """Names on the whole-Earth framing only — a dozen billboards over one
        field is a thicket. The boxes stay drawn at every zoom: they ARE what
        locates the data from space and what measures it up close."""
        for m in self._marks.values():
            m["trep"].Visibility = (m.get("want", 1) if on else 0)
        if self._marks_rep is not None:
            self._marks_rep.Visibility = 1

    @staticmethod
    def _delete_mark(m):
        for k in ("trep", "text"):
            try:
                pvsimple.Delete(m[k])
            except Exception:
                pass

    def _each_block_bounds(self, selectors):
        """{selector: [xmin..zmax]} in ECEF — what the CAMERA aims at."""
        return self._bounds_of(self.geo.get_source(), selectors)

    def _each_block_bounds_projected(self, selectors):
        """The same, in the PROJECTED CRS — what a BOX must be built from.

        Read off the shared collector, not the projection filter: the ECEF
        bounding box of a patch of ground is aligned to the Earth's axes, so
        it is both tilted off the horizon and far too tall (at 58°N, a 200 m
        thick grid gets a box about 2.8 km tall, 32° out). Also cheaper — every
        other view has already updated the collector, whereas asking the geo
        filter forces a full re-projection."""
        return self._bounds_of(self._active.get_source(), selectors)

    def _narrow_to(self, selector):
        """Draw ONLY ``selector`` (None = whatever the eyes say).

        Not a visibility nicety: the renderer recomputes the near clipping
        plane as far/1000 over every visible representation, and the composite
        draws every visible block through ONE actor whose bounds are their
        union. Framing a 5 km grid with a second field 7 500 km away puts the
        near plane at 7.5 km — in front of the grid — and the view goes black.
        ``reconcile()`` restores the eye-driven list."""
        rep = getattr(self, "main_rep", None)
        if rep is None:
            return
        if not selector:
            self.reconcile()
            return
        try:
            rep.BlockSelectors = [selector]
            rep.SMProxy.UpdateProperty("BlockSelectors", 1)
        except Exception as exc:
            print(f"[fespp] globe narrow error ({self.view_id}):", exc,
                  flush=True)

    @staticmethod
    def _bounds_of(src, selectors):
        """{selector: [xmin..zmax]} over the non-empty datasets of each
        selector's subtree in the output of `src`; unknown selectors are
        left out."""
        out = {}
        try:
            src.UpdatePipeline()
            pdc = src.GetClientSideObject().GetOutputDataObject(0)
            asm = pdc.GetDataAssembly()
        except Exception:
            return out
        if asm is None:
            return out
        for sel in selectors:
            if not sel:
                continue
            node = asm.GetFirstNodeByPath(sel)
            if node is None or node < 0:
                continue
            b = None
            for i in asm.GetDataSetIndices(node, True):
                pds = pdc.GetPartitionedDataSet(i)
                for j in range(pds.GetNumberOfPartitions() if pds is not None else 0):
                    ds = pds.GetPartition(j)
                    if ds is None or ds.GetNumberOfPoints() == 0:
                        continue
                    db = ds.GetBounds()
                    b = list(db) if b is None else [
                        min(b[0], db[0]), max(b[1], db[1]), min(b[2], db[2]),
                        max(b[3], db[3]), min(b[4], db[4]), max(b[5], db[5])]
            if b is not None and b[0] <= b[1]:
                out[sel] = b
        return out

    def _selector_bounds(self, selectors):
        """Union of those selectors' ECEF bounds, or None."""
        out = None
        for b in self._each_block_bounds(selectors).values():
            out = list(b) if out is None else [
                min(out[0], b[0]), max(out[1], b[1]), min(out[2], b[2]),
                max(out[3], b[3]), min(out[4], b[4]), max(out[5], b[5])]
        return out

    def set_earth_opacity(self, value) -> None:
        try:
            self.earth_opacity = min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return
        if self._earth_rep is not None:
            self._earth_rep.Opacity = self.earth_opacity
            self._mark_dirty()
        # applied whatever the current framing, the close one included

    # ------------------------------------------------------------------
    # where the data is

    def data_bounds(self):
        """ECEF bounds of the re-projected data (every loaded block), or
        None."""
        try:
            src = self.geo.get_source()
            b = src.GetDataInformation().GetBounds() if src is not None else None
            if b is not None and b[0] <= b[1]:
                return list(b)
        except Exception:
            pass
        return None

    @staticmethod
    def _center_of(b):
        """Centre of the bounds `b`, or None when there are none or it sits
        at the Earth's centre (no usable data)."""
        if b is None:
            return None
        c = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
        return c if np.linalg.norm(c) > 1.0 else None

    def data_center(self):
        return self._center_of(self.data_bounds())

    def visible_bounds(self):
        """Bounds of the blocks CURRENTLY SHOWN in this view, or None when no
        eye is open — what the data framing should actually fit."""
        return self._selector_bounds(
            sorted(self.shown_selectors() - self.isolated))

    def geographic_center(self):
        """(lon, lat, h) — degrees / metres above the ellipsoid — of the
        data centre, or None."""
        c = self.data_center()
        if c is None:
            return None
        return geo.geodetic_of(*c)

    def projected_bounds(self):
        """Bounds of the data as FESPP delivers it (projected CRS), or None."""
        try:
            b = self._active.get_source().GetDataInformation().GetBounds()
            if b is not None and b[0] <= b[1]:
                return list(b)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # camera framings

    def frame(self, mode="earth", selector=None) -> None:
        """``mode="earth"`` = the whole planet above the data. Anything else =
        fly ONTO ``selector`` (or onto what is visible when it is None).

        Framing ONE object is the only close framing offered: the union of
        every visible block puts the camera between two reservoirs, looking
        at neither."""
        if self.pv_view is None:
            return
        self.ensure_earth()
        cam = self.pv_view.GetActiveCamera()
        b = None
        if mode != "earth" and selector:
            b = self._each_block_bounds([selector]).get(selector)
        if b is None:
            # Frame what is ACTUALLY SHOWN, not every loaded block, so hiding
            # objects and framing again moves the camera.
            b = self.visible_bounds() or self.data_bounds()
        c = self._center_of(b)
        if mode != "earth" and c is not None and b is not None:
            d = c / np.linalg.norm(c)
            north = np.array([0.0, 0.0, 1.0]) - d[2] * d
            if np.linalg.norm(north) < 1e-6:
                north = np.array([0.0, 1.0, 0.0])
            north /= np.linalg.norm(north)
            # look straight down at the data, north up, then fit its bounds
            cam.SetFocalPoint(*c)
            cam.SetPosition(*(c + d * 1000.0))
            cam.SetViewUp(*north)
            self.pv_view.ResetCamera(b)
            self.pv_view.CenterOfRotation = [float(v) for v in c]
            self._set_marks_visible(False)
            # The Earth STAYS. Seeing the terrain around the data is the whole
            # point of putting a view on the Earth, so it is made translucent
            # rather than hidden — the reservoir is below the ellipsoid and an
            # opaque globe would seal it in. The clipping a drawn Earth causes
            # is handled by the camera rule, not by hiding anything.
            if self._earth_rep is not None:
                self._earth_rep.Visibility = 1
                self._earth_rep.Opacity = EARTH_OPACITY_CLOSE
            # The composite draws every visible block through ONE actor whose
            # bounds are their union, and that still feeds the far plane.
            # Narrow it to what we flew to; the Earth framing restores it.
            self._narrow_to(selector)
            self._framed = selector or None
            self.mode = "block" if selector else "data"
        else:
            d = c / np.linalg.norm(c) if c is not None else np.array([1.0, 0.0, 0.0])
            up = [0.0, 0.0, 1.0] if abs(d[2]) < 0.95 else [0.0, 1.0, 0.0]
            # Focal point ON THE DATA, not on the origin. The wheel dollies the
            # camera 21% toward its focal point per notch, so an origin focal
            # point would aim every scroll at the Earth's CORE: a few hundred
            # kilometres up, one more notch puts the camera hundreds of
            # kilometres UNDERGROUND, with no position in between — the data
            # cannot be approached by scrolling at all. The image is the same
            # as with a focal point on the origin: the origin, the data centre
            # and the camera are collinear by construction (the position below
            # is d * 5R and d = c / |c|), so only the focal DISTANCE moves.
            # Guarded on |c| < 5R: a broken CRS or a Z not in metres (the card
            # already warns past 20 km) can put the data BEYOND the camera, and
            # a focal point behind the eye turns the view inside out.
            focus = c if (c is not None
                          and np.linalg.norm(c) < 5.0 * geo._A) else None
            cam.SetFocalPoint(*(focus if focus is not None else (0.0, 0.0, 0.0)))
            # 5 R: the whole disc (23°) sits inside the 30° view angle with a margin
            cam.SetPosition(*(d * 5.0 * geo._A))
            cam.SetViewUp(*up)
            self.pv_view.CenterOfRotation = [0.0, 0.0, 0.0]
            self._set_marks_visible(True)
            if self._earth_rep is not None:
                self._earth_rep.Visibility = 1
                self._earth_rep.Opacity = self.earth_opacity
            self._narrow_to(None)
            self._framed = None
            self.mode = "earth"
        self._on_camera()      # clipping + mark size for where we just landed
        self._mark_dirty()

    # ------------------------------------------------------------------

    def release(self):
        super().release()
        for p in (self._earth_rep, self._earth):
            if p is None:
                continue
            try:
                pvsimple.Delete(p)
            except Exception:
                pass
        self._earth = self._earth_rep = None
        for m in self._marks.values():
            self._delete_mark(m)
        self._marks = {}
        for p in (self._marks_rep, self._marks_src):
            if p is None:
                continue
            try:
                pvsimple.Delete(p)
            except Exception:
                pass
        self._marks_src = self._marks_rep = None
        self.geo.release()
