"""ViewScene — one render view's sub-pipeline.

Every render panel gets its own `ViewScene` that owns:

  - a `vtkEPCCollectorClone` source proxy chained on the global
    EPCCollector (falls back to `collector.get_source()` when the plugin
    doesn't expose the clone);
  - a dict of `RepInScene` instances, one per loaded rep currently rendered
    in this view, each owning the per-(rep, view) filters (slice / clip /
    threshold chain) that diverge across views.
"""
from typing import Optional

from fespp_on_trame.app.utils.naming import strip_realization_suffix


class ViewScene:
    """Per-render-view scene root — tracks which reps are loaded in this view
    and owns its per-view pipeline (clone + per-(rep, view) reps + LUTs)."""

    def __init__(self, view_id, pv_view, collector, tree):
        """
        view_id   : str — opaque panel id from FesppMultiView (e.g. "ptc_view_1").
        pv_view   : pvsimple RenderView proxy this scene renders to.
        collector : the global `Collector` wrapper (EPCCollector source).
        tree      : the global `Tree` instance — used by reps to resolve
                    rep_path → node id and attributes.
        """
        self.view_id = str(view_id)
        self.pv_view = pv_view
        self.collector = collector
        self.tree = tree

        # `vtkEPCCollectorClone` filter chained on the collector. ShallowCopy
        # passthrough — zero data duplication; any update on the collector
        # invalidates the clone via the standard PV pipeline. The clone is
        # NEVER shown: it's a structural anchor in the SM graph on which
        # per-(view, rep) extractors chain, not a visible source.
        self._clone = self._create_clone() if collector is not None else None

        self._reps: dict = {}  # rep_path -> RepInScene

        # Per-(scene, array) LUT / PWF proxies. PV makes
        # `GetColorTransferFunction(name)` a singleton keyed by array name, so
        # every display ColorBy'd with the same name shares one LUT and a COE
        # edit in one view would bleed into every other view. We register a
        # distinct LUT (and matching opacity-tf) per `(scene, base_name)`
        # under a unique name `f"{base}__{view_id}"` and re-assign each
        # display's `LookupTable` / `ScalarOpacityFunction` to it after
        # `ColorBy`. Populated lazily by `get_or_create_lut` /
        # `get_or_create_pwf`.
        self._luts: dict = {}   # base_array_name -> lut proxy
        self._pwfs: dict = {}   # base_array_name -> opacity-tf proxy

    def _create_clone(self):
        """Instantiate the per-view `vtkEPCCollectorClone` proxy and hide it
        in every existing render view so PV's default lazy display never
        paints a phantom Outline overlay. Built via `_create_plugin_filter_proxy`
        so it resolves even when the pvsimple wrapper namespace hasn't
        refreshed after `LoadPlugin`."""
        try:
            from paraview import simple as pvsimple
            from fespp_on_trame.app.core.sources.representation import (
                _create_plugin_filter_proxy,
            )
            reg_name = f"EPCCollector_View{self.view_id}"
            input_src = self.collector.get_source()
            clone = _create_plugin_filter_proxy(
                proxy_class="EPCCollectorClone",
                registration_name=reg_name,
                inputs={"Input": input_src},
            )
            if clone is None:
                return self.collector.get_source()

            # The clone is a structural data node, not a visual one —
            # force Visibility=0 in every view so PV's default lazy
            # display doesn't paint a phantom Outline overlay.
            try:
                for view in pvsimple.GetViews():
                    disp = pvsimple.GetDisplayProperties(clone, view=view)
                    if disp is not None:
                        disp.Visibility = 0
            except Exception:
                pass
            return clone
        except Exception as exc:
            # Fallback to the shared collector source so the scene
            # still has a non-None clone reference (downstream code
            # treats it as an opaque handle).
            return self.collector.get_source()

    # ------------------------------------------------------------------
    # Rep lifecycle within this scene

    def get_rep(self, rep_path: str):
        """Return the `RepInScene` for `rep_path`, or None when this
        view doesn't currently render that rep."""
        return self._reps.get(rep_path) if rep_path else None

    def add_rep(self, rep_path: str):
        """Idempotent: return the existing `RepInScene` if any, else
        create a fresh one. The instance is registered before its
        first PV proxy is created so concurrent callers see it
        immediately."""
        from fespp_on_trame.app.core.sources.rep_in_scene import RepInScene
        if not rep_path:
            return None
        existing = self._reps.get(rep_path)
        if existing is not None:
            return existing
        rep = RepInScene(scene=self, rep_path=rep_path)
        self._reps[rep_path] = rep
        return rep

    def remove_rep(self, rep_path: str) -> None:
        """Tear down a single rep's per-(rep, view) state. No-op when
        the rep isn't in this scene."""
        rep = self._reps.pop(rep_path, None)
        if rep is not None:
            try:
                rep.delete()
            except Exception as exc:
                pass

    def reps(self):
        """Iterable view of the (rep_path, RepInScene) pairs currently
        loaded in this scene."""
        return self._reps.items()

    # ------------------------------------------------------------------
    # Lifecycle

    def destroy(self) -> None:
        """Tear down every rep + the scene's own EPCCollectorClone
        proxy. Idempotent."""
        for rep in list(self._reps.values()):
            try:
                rep.delete()
            except Exception as exc:
                pass
        self._reps.clear()

        # Delete the per-scene LUT / PWF proxies registered under our
        # scoped names. The global LUTs (keyed by the unsuffixed array
        # name) are NOT ours — leave them alone.
        try:
            from paraview import simple as pvsimple
            for lut in list(self._luts.values()):
                if lut is not None:
                    try:
                        pvsimple.Delete(lut)
                    except Exception:
                        pass
            for pwf in list(self._pwfs.values()):
                if pwf is not None:
                    try:
                        pvsimple.Delete(pwf)
                    except Exception:
                        pass
        except Exception:
            pass
        self._luts.clear()
        self._pwfs.clear()

        # The clone is only a vtkEPCCollectorClone we created ourselves
        # when collector is present — never delete the collector's
        # own source by mistake.
        if (self._clone is not None
                and self.collector is not None
                and self._clone is not self.collector.get_source()):
            try:
                from paraview import simple as pvsimple
                pvsimple.Delete(self._clone)
            except Exception as exc:
                pass
        self._clone = None

    # ------------------------------------------------------------------
    # Per-view LUT / PWF (see `_luts` / `_pwfs` field comments)

    def _scoped_tf_name(self, base_array_name: str) -> str:
        """Registration name used for this scene's LUT / PWF for
        `base_array_name`. Unique per (scene, array)."""
        return f"{base_array_name}__{self.view_id}"

    def get_or_create_lut(self, base_array_name: str):
        """Per-scene LUT proxy for `base_array_name`. Seeds from the
        global LUT keyed by the same `base_array_name` on first
        creation so the new view starts with PV's auto-assigned
        gradient (RGBPoints, NaN colour, opacity mapping flag, …)
        instead of an empty LUT. Subsequent edits stay scoped to
        this scene.

        ONE colormap per property, shared by its realizations: the MR
        `_real_<idx>` suffix is stripped from the KEY, so
        'SOIL_real_23' and 'SOIL_real_24' resolve to the same scene
        LUT (and PWF below). Only the key is normalised — displays
        keep their suffixed `ColorArrayName`; a LUT proxy is bound
        per display and carries no array-name linkage of its own, and
        the unpinned range still rescales to each realization's data
        on apply."""
        base_array_name = strip_realization_suffix(base_array_name)
        if not base_array_name:
            return None
        cached = self._luts.get(base_array_name)
        if cached is not None:
            return cached
        from paraview import simple as pvsimple
        scoped = self._scoped_tf_name(base_array_name)
        # The first call creates the proxy + registers it under `scoped`.
        scene_lut = pvsimple.GetColorTransferFunction(scoped)
        # Seed from the global template LUT (if PV created one already
        # under the unsuffixed name) — preserves the user's previous
        # gradient when the scene is brought up after a property has
        # already been activated globally.
        try:
            template = pvsimple.GetColorTransferFunction(base_array_name)
            if (template is not None and template is not scene_lut
                    and getattr(template, "RGBPoints", None)):
                for attr in (
                    "RGBPoints", "NanColor", "NanOpacity", "ColorSpace",
                    "EnableOpacityMapping", "UseLogScale",
                    "VectorMode", "VectorComponent",
                    "IndexedColors", "IndexedOpacities", "Annotations",
                ):
                    try:
                        setattr(scene_lut, attr, getattr(template, attr))
                    except Exception:
                        pass
        except Exception:
            pass
        self._luts[base_array_name] = scene_lut
        return scene_lut

    def get_or_create_pwf(self, base_array_name: str):
        """Per-scene opacity transfer function. Mirrors
        `get_or_create_lut` for the opacity side (same realization-
        suffix key normalisation)."""
        base_array_name = strip_realization_suffix(base_array_name)
        if not base_array_name:
            return None
        cached = self._pwfs.get(base_array_name)
        if cached is not None:
            return cached
        from paraview import simple as pvsimple
        scoped = self._scoped_tf_name(base_array_name)
        scene_pwf = pvsimple.GetOpacityTransferFunction(scoped)
        try:
            template = pvsimple.GetOpacityTransferFunction(base_array_name)
            if (template is not None and template is not scene_pwf
                    and getattr(template, "Points", None)):
                for attr in ("Points", "UseLogScale"):
                    try:
                        setattr(scene_pwf, attr, getattr(template, attr))
                    except Exception:
                        pass
        except Exception:
            pass
        # Default a NEW per-scene PWF to FLAT opacity 1. ParaView seeds a
        # fresh opacity TF (and its global template) with the 0→1 ramp
        # `[0,0,0.5,0, 1,1,0.5,0]`, so the COE would render the lowest
        # scalar at opacity 0 and `on_opacities_changed` would flip
        # `EnableOpacityMapping=1` (which suppresses NaN opacity). The
        # app default is flat-1 valid-value opacity with NaN handled
        # separately by the LUT's `NanOpacity`. Flatten ONLY the
        # untouched two-stop 0→1 default; preserve the X-extent so the
        # later `RescaleTransferFunction` still maps to the data range.
        # Cached PWFs return early above, so a user's per-stop opacity
        # edits are never re-flattened.
        try:
            pts = list(getattr(scene_pwf, "Points", []) or [])
            is_default_ramp = (
                len(pts) == 8
                and abs(float(pts[1])) < 1e-6
                and abs(float(pts[-3]) - 1.0) < 1e-6
            )
            if is_default_ramp:
                pmin = float(pts[0])
                pmax = float(pts[-4])
                scene_pwf.Points = [pmin, 1.0, 0.5, 0.0, pmax, 1.0, 0.5, 0.0]
        except Exception:
            pass
        self._pwfs[base_array_name] = scene_pwf
        return scene_pwf

    # LUT / PWF property names that get cloned across scenes on
    # `replicate_tfs_from` — covers continuous (RGBPoints / Points),
    # categorical (IndexedColors / IndexedOpacities / Annotations),
    # and the scalar / log / vector flags users typically tweak.
    _LUT_REPLICATED_ATTRS = (
        "RGBPoints", "NanColor", "NanOpacity", "ColorSpace",
        "EnableOpacityMapping", "UseLogScale",
        "VectorMode", "VectorComponent",
        "IndexedColors", "IndexedOpacities", "Annotations",
    )
    _PWF_REPLICATED_ATTRS = ("Points", "UseLogScale")

    def replicate_tfs_from(self, ref_scene) -> None:
        """Mirror every LUT / PWF property from `ref_scene` onto this
        scene's matching per-(base, view) proxies. Called by
        `MultiView.add_view` right after `apply_panel_coloring` on a
        duplicated view so the new view starts with the same gradient
        the user had edited in the ref view (otherwise the new scene's
        scoped LUT is seeded from the global singleton, which only
        carries PV's auto-default — the user's edits live on the ref's
        scoped LUT).

        Forces a list copy on the way through so PV's internal vector
        properties don't end up aliased to the ref proxy's storage —
        a later edit on either side would otherwise mutate both."""
        if ref_scene is None:
            return
        for base, ref_lut in ref_scene._luts.items():
            if ref_lut is None:
                continue
            self_lut = self._luts.get(base) or self.get_or_create_lut(base)
            if self_lut is None or self_lut is ref_lut:
                continue
            for attr in self._LUT_REPLICATED_ATTRS:
                try:
                    val = getattr(ref_lut, attr)
                    if isinstance(val, (list, tuple)):
                        val = list(val)
                    setattr(self_lut, attr, val)
                except Exception:
                    pass
        for base, ref_pwf in ref_scene._pwfs.items():
            if ref_pwf is None:
                continue
            self_pwf = self._pwfs.get(base) or self.get_or_create_pwf(base)
            if self_pwf is None or self_pwf is ref_pwf:
                continue
            for attr in self._PWF_REPLICATED_ATTRS:
                try:
                    val = getattr(ref_pwf, attr)
                    if isinstance(val, (list, tuple)):
                        val = list(val)
                    setattr(self_pwf, attr, val)
                except Exception:
                    pass

    def get_lut(self, base_array_name: str):
        """Cached LUT for this (scene, array). None when none exists
        yet — does NOT create one. Same realization-suffix key
        normalisation as `get_or_create_lut`."""
        base_array_name = strip_realization_suffix(base_array_name)
        return self._luts.get(base_array_name) if base_array_name else None

    def get_pwf(self, base_array_name: str):
        base_array_name = strip_realization_suffix(base_array_name)
        return self._pwfs.get(base_array_name) if base_array_name else None

    # ------------------------------------------------------------------
    # Useful accessors

    @property
    def clone(self):
        """The view-scoped scene root — the per-view `vtkEPCCollectorClone`
        proxy chained on the collector (or the collector source itself when
        the clone couldn't be created)."""
        return self._clone

    def __repr__(self) -> str:
        return f"<ViewScene view_id={self.view_id!r} reps={len(self._reps)}>"
