"""ViewScene — one render view's sub-pipeline.

See `doc/REFACTOR_VIEW_SCENES.md` for the full design rationale. In
short: every render panel gets its own `ViewScene` that will own:

  - a `vtkEPCCollectorClone` source proxy chained on the global
    EPCCollector (deferred to Phase 2 — until then the scene reuses
    `collector.get_source()` directly);
  - a dict of `RepInScene` instances, one per loaded rep currently
    rendered in this view, each owning the per-(rep, view) filters
    (slice / clip / threshold chain) that need to diverge across
    views.

Phase 1 status (this commit):
  - Lifecycle (`__init__`, `add_rep`, `remove_rep`, `destroy`) wired
    but the per-view PV pipeline isn't yet — `_clone` is set to the
    collector's source proxy as a transparent stand-in. RepInScene
    instances don't yet drive their own slice/clip; that comes in
    Phase 1.b once the API is validated.
"""
from typing import Optional


class ViewScene:
    """Per-render-view scene root.

    Currently a thin container that tracks which reps are loaded in
    this view; expands over phases to own the per-view pipeline."""

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

        # Phase 2: create a `vtkEPCCollectorClone` filter chained on the
        # collector. ShallowCopy passthrough — zero data duplication,
        # propagation 100% native PV (any update on the collector
        # invalidates the clone, which invalidates downstream filters
        # via the standard pipeline mechanism). The clone is NEVER
        # shown in any view: it's a structural anchor in the SM graph,
        # not a visible source. Phase 3 will chain per-(view, rep)
        # ExtractBlocks on it; for now slice / clip still chain on
        # the legacy per-rep ExtractBlock from SourceRegistry.
        self._clone = self._create_clone() if collector is not None else None

        self._reps: dict = {}  # rep_path -> RepInScene

        # Per-(scene, array) LUT / PWF proxies. Default PV behaviour
        # makes `GetColorTransferFunction(name)` a singleton keyed by
        # array name — every display ColorBy'd with the same name
        # shares the same LUT, so a COE edit in one view bleeds into
        # every other view. We register a distinct LUT (and matching
        # opacity-tf) per `(scene, base_name)` under a unique name
        # `f"{base}__{view_id}"` and re-assign each display's
        # `LookupTable` / `ScalarOpacityFunction` to it after `ColorBy`.
        # Maps below are populated lazily by `get_or_create_lut` /
        # `get_or_create_pwf`.
        self._luts: dict = {}   # base_array_name -> lut proxy
        self._pwfs: dict = {}   # base_array_name -> opacity-tf proxy

    def _create_clone(self):
        """Instantiate the per-view `vtkEPCCollectorClone` proxy. Hides it
        in every existing render view so PV's default lazy display
        (Visibility=1, Outline) never paints a phantom overlay.

        Resolution: see `_create_plugin_filter_proxy` in
        `representation.py`. The pvsimple wrapper namespace is the
        preferred fast path but PV 6.0 (at least in the Trame Docker
        container) doesn't always refresh it after `LoadPlugin` — the
        helper falls back to the `vtkSMSessionProxyManager.NewProxy`
        path which always sees freshly-loaded plugin definitions."""
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
                print(
                    f"[ViewScene {self.view_id}] EPCCollectorClone definition"
                    " missing from server — plugin dll may be out of date"
                    " or not loaded."
                )
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
            print(f"[ViewScene {self.view_id}] EPCCollectorClone create failed: {exc}")
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
                print(f"[ViewScene {self.view_id}] remove_rep({rep_path}) failed: {exc}")

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
                print(f"[ViewScene {self.view_id}] destroy rep failed: {exc}")
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
                print(f"[ViewScene {self.view_id}] clone delete failed: {exc}")
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
        this scene."""
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
        `get_or_create_lut` for the opacity side."""
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
        yet — does NOT create one."""
        return self._luts.get(base_array_name) if base_array_name else None

    def get_pwf(self, base_array_name: str):
        return self._pwfs.get(base_array_name) if base_array_name else None

    # ------------------------------------------------------------------
    # Useful accessors

    @property
    def clone(self):
        """The view-scoped scene root. In Phase 1 this is the collector
        source itself; from Phase 2 onward it's the per-view
        `vtkEPCCollectorClone` proxy chained on the collector."""
        return self._clone

    def __repr__(self) -> str:
        return f"<ViewScene view_id={self.view_id!r} reps={len(self._reps)}>"
