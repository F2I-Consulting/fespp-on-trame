"""RepInScene — one RESQML representation as seen from a single view.

See `doc/REFACTOR_VIEW_SCENES.md` and `doc/REFACTOR_PER_VIEW_PHASE_3.md`
for the full design rationale.

Phase status (this module):
  - Phase 1.b — `SlicePlane` and `ClipPlane` are per-(rep, view), each
    aware of its owning `view_id` / `pv_view`. Validated.
  - Phase 2 — `vtkEPCCollectorClone` is the per-view structural
    anchor; `ViewScene._create_clone` plumbs it.
  - Phase 3a (this commit) — non-IjkGrid reps gain a per-(rep, view)
    `EnergisticsExtractor` chained on the clone, plus a per-view
    threshold chain owned here. Slice / Clip now chain on the per-view
    extractor instead of the legacy shared source. IjkGrid reps still
    delegate slice / clip / threshold to the legacy shared pipeline
    (managed by `SourceRegistry`); Phase 3b will move them over.

Naming:
  - `_extractor` — per-(rep, view) `EnergisticsExtractor` filter. None
    for IjkGrid reps (legacy stays in charge) and for non-IjkGrid reps
    until the first slice/clip/threshold/ColorBy resolves its upstream.
  - `_chain` — per-view list of `ChainEntry` (reused from
    `ExtractBlockRepresentation`). Empty for IjkGrid reps.

The "parent rep visibility" rule from Phase 1.b is preserved: enabling
slice OR clip on a rep Hides the rep's display IN THIS SCENE'S
pv_view only, so the cross-section / clipped chunk is visible. Other
scenes keep the rep visible.
"""
from typing import Optional


class RepInScene:
    """Per-(rep, view) wrapper. See module docstring."""

    def __init__(self, scene, rep_path: str):
        """
        scene    : the owning `ViewScene`.
        rep_path : the RESQML rep path (assembly node path).
        """
        self.scene = scene
        self.rep_path = rep_path

        # Phase 3a — per-(rep, view) EnergisticsExtractor chained on the
        # scene's clone. None for IjkGrid reps (handled by
        # `_per_view_ijk` below). Created lazily on first upstream
        # resolution so a rep that's never sliced/clipped/colored
        # doesn't pay the proxy creation cost.
        self._extractor = None

        # Phase 3b — per-(rep, view) IjkGrid pipeline (rep_data +
        # slicers + volume crop + threshold chain), all anchored on
        # `scene.clone`. Created lazily for IJK reps the first time
        # `source()` / slice / clip / threshold resolves an upstream.
        # The legacy shared IjkGrid (owned by `SourceRegistry`) stays
        # around to drive the property selection through the engine —
        # `_ensure_per_view_ijk` mirrors its `_node_id` to keep the
        # two in sync. We then hide the legacy IjkGrid's sources in
        # this scene's pv_view so only the per-view pipeline renders.
        self._per_view_ijk = None

        # Per-view threshold chain (non-IJK reps only — IJK reps use
        # `_per_view_ijk._chain` instead). Each entry is an
        # `ExtractBlockRepresentation.ChainEntry`.
        self._chain: list = []

        # Per-(rep, view) slice + clip filters. Created lazily on the
        # first `slice_set` / `clip_set` call.
        self._slice_plane = None
        self._clip_plane = None

        # `_is_ijk_grid()` lookup result. None = not computed yet,
        # otherwise a bool. The tree lookup is cheap but called from
        # every public method; caching keeps the dispatch hot path
        # branch-free after the first call.
        self._is_ijk_cache: Optional[bool] = None

    # ------------------------------------------------------------------
    # Rep type — IjkGrid detection
    #
    # IjkGrid reps stay on the legacy shared pipeline (rep_data extractor
    # + slicers + volume + chain owned by `IjkGrid` in `source_registry`).
    # Phase 3b moves them over to per-view as well.

    def _is_ijk_grid(self) -> bool:
        if self._is_ijk_cache is not None:
            return self._is_ijk_cache
        try:
            node_id = self.scene.tree.find_node_id(self.rep_path)
            if node_id is None:
                self._is_ijk_cache = False
                return False
            kind = self.scene.tree.find_type(node_id)
            self._is_ijk_cache = (kind == "IjkGrid")
        except Exception:
            self._is_ijk_cache = False
        return self._is_ijk_cache

    # ------------------------------------------------------------------
    # Source resolution

    def source(self):
        """Head proxy used by ColorBy and the display layer.

        Phase 3a/3b routing:
          - IjkGrid reps → per-view IjkGrid's rep_data extractor when
            available, falls back to legacy shared source otherwise.
          - Non-IjkGrid reps → per-view EnergisticsExtractor when the
            scene has a real `EPCCollectorClone`, falls back to the
            legacy shared ExtractBlock source otherwise."""
        if self._is_ijk_grid():
            ijk = self._ensure_per_view_ijk()
            if ijk is not None and ijk.source is not None:
                return ijk.source
            return self._fallback_legacy_source()
        ext = self._ensure_extractor()
        if ext is not None:
            return ext
        return self._fallback_legacy_source()

    def _ensure_per_view_ijk(self):
        """Lazily build a per-(rep, view) IjkGrid pipeline rooted on
        the scene's clone. Mirrors the legacy IjkGrid's currently
        selected property so the per-view variant renders the same
        thing on first display. Returns None for non-IJK reps or when
        the legacy IjkGrid hasn't been initialised yet (no property
        selected → nothing to render)."""
        if not self._is_ijk_grid():
            return None
        if self._per_view_ijk is not None:
            return self._per_view_ijk
        clone = getattr(self.scene, "clone", None)
        if clone is None:
            return None
        collector = getattr(self.scene, "collector", None)
        if collector is not None and clone is collector.get_source():
            # Phase 2 fallback (no real EPCCollectorClone) — stay on
            # the legacy path so we don't double-render.
            return None
        # Read the legacy IjkGrid's current property node id; we need
        # it to drive `set_node_id` on the per-view instance.
        legacy = None
        try:
            from trame.app import get_server
            ctx = get_server().context
            source_registry = getattr(ctx, "source_registry", None)
            if source_registry is not None and hasattr(source_registry, "get_ijk_grid"):
                legacy = source_registry.get_ijk_grid(self.rep_path)
        except Exception:
            legacy = None
        if legacy is None or getattr(legacy, "_node_id", None) is None:
            return None
        # Resolve the legacy IjkGrid's *property* node id (the one the
        # user activated) — IjkGrid stores `_property_path` for the
        # current property, so we round-trip path → node_id.
        prop_node_id = None
        try:
            prop_path = getattr(legacy, "_property_path", None)
            if prop_path:
                prop_node_id = self.scene.tree.find_node_id(prop_path)
        except Exception:
            prop_node_id = None
        if prop_node_id is None:
            # No property → can't drive the IjkGrid; skip until the
            # next refresh (called from the engine on property change).
            return None
        try:
            from fespp_on_trame.app.core.sources.ijkgrid import IjkGrid
            self._per_view_ijk = IjkGrid(
                collector, self.scene.tree,
                view_id=self.scene.view_id,
                clone=clone,
                pv_view=self.scene.pv_view,
            )
            self._per_view_ijk.set_node_id(prop_node_id)
            if self._per_view_ijk.source is None:
                # Creation failed — drop the half-built instance so we
                # retry on the next call.
                self._per_view_ijk = None
                return None
            # Hide the legacy IjkGrid's rendered sources in THIS view
            # so the per-view pipeline doesn't double-render with the
            # legacy slicers / rep_data.
            self._hide_legacy_ijk_in_scene_view(legacy)
        except Exception as exc:
            print(f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                  f" per-view IjkGrid create failed: {exc}")
            self._per_view_ijk = None
        return self._per_view_ijk

    def _hide_legacy_ijk_in_scene_view(self, legacy_ijk):
        """Hide every visible source of the legacy shared IjkGrid in
        this scene's pv_view (rep_data, slicers, volume crop, chain
        proxies). Called once the per-view IjkGrid is up so we don't
        Z-fight with the legacy pipeline."""
        view = self.scene.pv_view
        if view is None or legacy_ijk is None:
            return
        try:
            from paraview import simple as pvsimple
            sources = []
            if legacy_ijk._src_extract_init is not None:
                sources.append(legacy_ijk._src_extract_init)
            sources.extend(legacy_ijk._all_slice_sources())
            if legacy_ijk._src_slicer_volume is not None:
                sources.append(legacy_ijk._src_slicer_volume)
            try:
                sources.extend(legacy_ijk.all_threshold_sources())
            except Exception:
                pass
            for src in sources:
                if src is None:
                    continue
                try:
                    pvsimple.Hide(proxy=src, view=view)
                except Exception:
                    pass
        except Exception:
            pass

    def refresh_per_view_ijk_property(self, prop_node_id):
        """Re-target the per-view IjkGrid at a new property node id.
        Called by the engine when the user activates a different
        property on the same IJK rep (the legacy IjkGrid's
        `set_node_id` is called too, by the existing engine flow —
        this keeps the per-view variant in step). No-op if the
        per-view IjkGrid hasn't been built yet (it'll pick the new
        property on first lazy creation)."""
        if self._per_view_ijk is None:
            return
        try:
            self._per_view_ijk.set_node_id(prop_node_id)
        except Exception as exc:
            print(f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                  f" per-view IjkGrid refresh failed: {exc}")

    def _ensure_extractor(self):
        """Lazily create the per-(rep, view) EnergisticsExtractor. Non-IjkGrid
        only. Returns None when:
          - the rep is IjkGrid (handled by the legacy pipeline);
          - the scene's `clone` is the shared collector source (Phase 2
            fallback path, e.g. plugin DLL out of date) — chaining a
            per-view extractor on the shared collector would still
            collide on id() across views, so we just stay on legacy.

        Hides the freshly-created extractor in every view EXCEPT
        `self.scene.pv_view` so a default-`Visibility=1` display
        proxy doesn't paint a phantom outline elsewhere."""
        if self._is_ijk_grid():
            return None
        if self._extractor is not None:
            return self._extractor
        clone = getattr(self.scene, "clone", None)
        if clone is None:
            return None
        collector = getattr(self.scene, "collector", None)
        if collector is not None and clone is collector.get_source():
            # Phase 2 fallback — scene didn't get a real clone. Don't
            # chain a per-view filter on the shared collector; the
            # divergence wouldn't be real.
            return None
        try:
            from paraview import simple as pvsimple
            from paraview.servermanager import vtkSMPropertyHelper
            from fespp_on_trame.app.core.sources.representation import (
                _sanitize, _apply_default_tint, _create_plugin_filter_proxy,
            )
            from trame.app import get_server
            state = get_server().state
            reg_name = f"rep_{_sanitize(self.rep_path)}_v{self.scene.view_id}"
            # Use the robust plugin-proxy helper — see
            # PARAVIEW.md "LoadPlugin doesn't always refresh pvsimple
            # namespace". `EnergisticsExtractor` is usually in the
            # cache (older filter) but the fallback path costs
            # nothing when it is and saves the rep when it isn't.
            ext = _create_plugin_filter_proxy(
                proxy_class="EnergisticsExtractor",
                registration_name=reg_name,
                inputs={"Input": clone},
            )
            if ext is None:
                print(
                    f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                    " EnergisticsExtractor not creatable — plugin missing?"
                )
                return None
            # ExtractPath is `panel_visibility="never"` in the XML but
            # still settable via the SMProperty API.
            vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(self.rep_path)
            ext.SMProxy.UpdateVTKObjects()
            ext.UpdatePipelineInformation()

            # Hide in every other view, then Show in the owning view
            # with the user's representation type + tint already
            # applied (PV defaults to Outline + grey, which would
            # look broken until the next refresh).
            target_view = self.scene.pv_view
            for v in pvsimple.GetViews():
                if v is not target_view:
                    try:
                        pvsimple.Hide(proxy=ext, view=v)
                    except Exception:
                        pass
            if target_view is not None:
                disp = pvsimple.GetRepresentation(proxy=ext, view=target_view)
                if disp is not None:
                    disp.Representation = state.representation_active or "Surface"
                    zs = self._current_z_scale()
                    disp.Scale = [1.0, 1.0, zs]
                    grid_color = (state.solid_color_by_rep or {}).get(self.rep_path)
                    _apply_default_tint(disp, grid_color)
                pvsimple.Show(proxy=ext, view=target_view)
                # The legacy `ExtractBlockRepresentation` Shows itself
                # in the active view at creation time. With Phase 3a
                # the per-view extractor renders the same data with the
                # per-view ColorBy applied — the legacy EB's display in
                # this view becomes a visual duplicate (worst case:
                # Z-fighting with the per-view extractor). Hide it
                # here so only the per-view extractor renders. Other
                # views never get a legacy-EB Show() so they're
                # implicitly safe; calling Hide() on a view that has
                # no display proxy is a no-op.
                legacy = self._fallback_legacy_source()
                if legacy is not None and legacy is not ext:
                    try:
                        pvsimple.Hide(proxy=legacy, view=target_view)
                    except Exception:
                        pass
            self._extractor = ext
        except Exception as exc:
            print(
                f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                f" extractor create failed: {exc}"
            )
            self._extractor = None
        return self._extractor

    def _fallback_legacy_source(self):
        """Locate the legacy per-rep source via the engine's existing
        registry. Phase 3a uses this for IjkGrid reps unconditionally
        and for non-IjkGrid reps when the per-view extractor can't be
        built."""
        try:
            from trame.app import get_server
            ctx = get_server().context
            legacy = getattr(ctx, "source_registry", None)
            if legacy is None:
                return None
            return legacy.get(self.rep_path)
        except Exception:
            return None

    def _current_z_scale(self) -> float:
        try:
            from trame.app import get_server
            return float(getattr(get_server().state, "ui_scale_z", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0

    # ------------------------------------------------------------------
    # Lifecycle

    def delete(self) -> None:
        """Tear down per-(rep, view) state in dependency order:
        chain first (children-first within the chain), then slice +
        clip (they may chain on the extractor's output), then the
        extractor / per-view IjkGrid itself."""
        # Chain proxies first — they hold Inputs on the extractor.
        self._delete_chain()

        if self._slice_plane is not None:
            try:
                self._slice_plane.delete()
            except Exception as exc:
                print(f"[RepInScene {self.scene.view_id}/{self.rep_path}] slice delete: {exc}")
            self._slice_plane = None
        if self._clip_plane is not None:
            try:
                self._clip_plane.delete()
            except Exception as exc:
                print(f"[RepInScene {self.scene.view_id}/{self.rep_path}] clip delete: {exc}")
            self._clip_plane = None

        if self._per_view_ijk is not None:
            # IjkGrid has a `set_node_id(None)` teardown path that
            # deletes every proxy it owns (slicers, volume, chain).
            try:
                self._per_view_ijk.set_node_id(None)
            except Exception as exc:
                print(
                    f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                    f" per-view IjkGrid teardown: {exc}"
                )
            self._per_view_ijk = None

        if self._extractor is not None:
            try:
                from paraview import simple as pvsimple
                if self.scene.pv_view is not None:
                    pvsimple.Hide(proxy=self._extractor, view=self.scene.pv_view)
                pvsimple.Delete(self._extractor)
            except Exception as exc:
                print(
                    f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                    f" extractor delete: {exc}"
                )
            self._extractor = None

    # ------------------------------------------------------------------
    # Slice — owned per-(rep, view)

    def _ensure_slice(self):
        if self._slice_plane is not None:
            return self._slice_plane
        upstream = self.source()
        if upstream is None:
            return None
        from fespp_on_trame.app.core.sources.slice_plane import SlicePlane
        from trame.app import get_server
        self._slice_plane = SlicePlane(
            rep_path=self.rep_path,
            upstream=upstream,
            state=get_server().state,
            view_id=self.scene.view_id,
            view_pv=self.scene.pv_view,
        )
        return self._slice_plane

    def slice_state(self) -> dict:
        sp = self._ensure_slice()
        if sp is None:
            return {"enabled": False, "axis": "X", "offset": 0.0,
                    "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]}
        return sp.to_dict()

    def slice_set(self, enabled=None, axis=None, offset=None):
        sp = self._ensure_slice()
        if sp is None:
            return
        was_enabled = sp.enabled
        sp.set(enabled=enabled, axis=axis, offset=offset)
        if sp.enabled != was_enabled:
            self._refresh_parent_rep_visibility()
            self._refresh_chain_visibility()

    # ------------------------------------------------------------------
    # Clip — owned per-(rep, view)

    def _ensure_clip(self):
        if self._clip_plane is not None:
            return self._clip_plane
        upstream = self.source()
        if upstream is None:
            return None
        from fespp_on_trame.app.core.sources.clip_plane import ClipPlane
        from trame.app import get_server
        self._clip_plane = ClipPlane(
            rep_path=self.rep_path,
            upstream=upstream,
            state=get_server().state,
            view_id=self.scene.view_id,
            view_pv=self.scene.pv_view,
        )
        return self._clip_plane

    def clip_state(self) -> dict:
        cp = self._ensure_clip()
        if cp is None:
            return {"enabled": False, "axis": "X", "offset": 0.0,
                    "inside_out": False,
                    "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]}
        return cp.to_dict()

    def clip_set(self, enabled=None, axis=None, offset=None, inside_out=None):
        cp = self._ensure_clip()
        if cp is None:
            return
        was_enabled = cp.enabled
        cp.set(enabled=enabled, axis=axis, offset=offset, inside_out=inside_out)
        if cp.enabled != was_enabled:
            self._refresh_parent_rep_visibility()
            self._refresh_chain_visibility()

    def clip_output(self):
        """The Clip filter proxy (used by source_resolver to include
        the clipped output in ColorBy fan-out). None when clip isn't
        enabled / created."""
        if self._clip_plane is None:
            return None
        return self._clip_plane.output

    def slice_output(self):
        """The Slice filter proxy. Mirrors `clip_output()` — used by
        stats dispatch so the slice's visible output is included in
        the per-view rendered sources list. None when slice isn't
        enabled / created."""
        if self._slice_plane is None:
            return None
        return self._slice_plane.output

    def refresh_planes_after_property_change(self):
        """Re-apply slice + clip so a fresh ColorBy on the rep picks
        them up (clip inherits display props at creation time and
        doesn't auto-track later edits). Also re-asserts parent rep
        visibility and chain visibility."""
        if self._clip_plane is not None and self._clip_plane.enabled:
            self._clip_plane.set()  # no-op patch → re-applies
        if self._slice_plane is not None and self._slice_plane.enabled:
            self._slice_plane.set()
        self._refresh_parent_rep_visibility()
        self._refresh_chain_visibility()

    # ------------------------------------------------------------------
    # Parent rep visibility — per-view

    def _refresh_parent_rep_visibility(self):
        """Hide this rep's primary source in THIS scene's pv_view when
        slice or clip is enabled — each "replaces" the rep visually in
        that view. Per-(rep, view) by design: each scene decides
        independently.

        Phase 3a: the primary source for non-IjkGrid is the per-view
        `_extractor`; for IjkGrid it's the legacy shared source. The
        chain visibility resolver (`_refresh_chain_visibility`) takes
        care of substituting chain leaves when a chain is active —
        this method only manages the rep's primary visibility."""
        view = getattr(self.scene, "pv_view", None)
        if view is None:
            return
        upstream = self.source()
        if upstream is None:
            return
        slice_on = self._slice_plane is not None and self._slice_plane.enabled
        clip_on = self._clip_plane is not None and self._clip_plane.enabled
        chain_visible = any(e.visible for e in self._chain) if self._chain else False
        should_hide = slice_on or clip_on or chain_visible
        try:
            from paraview import simple as pvsimple
            if should_hide:
                pvsimple.Hide(proxy=upstream, view=view)
            else:
                # Only show again if the user hasn't hidden the rep
                # for this view via the per-view eye chip.
                try:
                    from trame.app import get_server
                    hidden_by_view = (
                        get_server().state.ui_hidden_rep_paths_by_view or {}
                    )
                    panel_hidden = hidden_by_view.get(self.scene.view_id, []) or []
                    if self.rep_path in panel_hidden:
                        return
                except Exception:
                    pass
                pvsimple.Show(proxy=upstream, view=view)
        except Exception as exc:
            print(
                f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                f" parent visibility refresh: {exc}"
            )

    # ==================================================================
    # Threshold chain — per-(rep, view), non-IjkGrid only.
    #
    # Mirrors `ExtractBlockRepresentation`'s chain implementation
    # (same `ChainEntry` dataclass, same effective-input resolution,
    # same visibility rules) but:
    #   - upstream is `self._extractor` (per-view) instead of a shared
    #     `ExtractBlock`;
    #   - registration name suffixes `_v{view_id}` so chains from
    #     different views don't collide on PV's proxy registry;
    #   - Show/Hide targets `self.scene.pv_view`, not the active view.
    #
    # IjkGrid reps delegate to the legacy instance through the
    # `_legacy_instance()` accessor below — Phase 3b changes that.

    def _ijk_provider(self):
        """Resolve the IjkGrid instance to forward threshold ops to:
        the per-view one when available (Phase 3b), legacy fallback
        otherwise. Returns None for non-IJK reps."""
        if not self._is_ijk_grid():
            return None
        ijk = self._ensure_per_view_ijk()
        if ijk is not None:
            return ijk
        return self._legacy_instance()

    def get_chain(self):
        if self._is_ijk_grid():
            ijk = self._ijk_provider()
            if ijk is None or not hasattr(ijk, "get_chain"):
                return []
            return ijk.get_chain()
        return [e.to_dict() for e in self._chain]

    def add_threshold(self, parent_name, array):
        if self._is_ijk_grid():
            ijk = self._ijk_provider()
            if ijk is None or not hasattr(ijk, "add_threshold"):
                return None
            return ijk.add_threshold(parent_name, array)
        return self._add_threshold_local(parent_name, array)

    def delete_threshold(self, name):
        if self._is_ijk_grid():
            ijk = self._ijk_provider()
            if ijk is not None and hasattr(ijk, "delete_threshold"):
                ijk.delete_threshold(name)
            return
        self._delete_threshold_local(name)

    def set_range(self, name, low, high):
        if self._is_ijk_grid():
            ijk = self._ijk_provider()
            if ijk is not None and hasattr(ijk, "set_range"):
                ijk.set_range(name, low, high)
            return
        for e in self._chain:
            if e.name == name:
                e.low = float(low)
                e.high = float(high)
                try:
                    e.proxy.LowerThreshold = e.low
                    e.proxy.UpperThreshold = e.high
                    e.proxy.UpdatePipeline()
                except Exception as exc:
                    print(f"[RepInScene {self.scene.view_id}/{self.rep_path}] set_range({name}): {exc}")
                return

    def set_visible(self, name, visible):
        if self._is_ijk_grid():
            ijk = self._ijk_provider()
            if ijk is not None and hasattr(ijk, "set_visible"):
                ijk.set_visible(name, visible)
            return
        for e in self._chain:
            if e.name == name:
                e.visible = bool(visible)
                break
        else:
            return
        self._refresh_chain_visibility()

    def available_arrays(self):
        if self._is_ijk_grid():
            ijk = self._ijk_provider()
            if ijk is None or not hasattr(ijk, "available_arrays"):
                return []
            return ijk.available_arrays()
        src = self._ensure_extractor() or self._fallback_legacy_source()
        return _arrays_from_source(src)

    def array_data_range(self, array_name):
        if self._is_ijk_grid():
            ijk = self._ijk_provider()
            if ijk is None or not hasattr(ijk, "array_data_range"):
                return None
            return ijk.array_data_range(array_name)
        src = self._ensure_extractor() or self._fallback_legacy_source()
        return _array_range_from_source(src, array_name)

    def all_visible_thresholds(self):
        """Visible threshold proxies in chain order — used by callers
        that want the rendered tips of the chain. Empty for IjkGrid
        (caller falls back to the legacy IjkGrid API)."""
        if self._is_ijk_grid():
            return []
        return [e.proxy for e in self._chain if e.visible]

    def all_chain_proxies(self):
        """Every threshold proxy in this view's chain (visible or
        not). Empty for IjkGrid."""
        if self._is_ijk_grid():
            return []
        return [e.proxy for e in self._chain]

    def deepest_visible_threshold(self):
        visibles = self.all_visible_thresholds()
        return visibles[-1] if visibles else None

    # ------------------------------------------------------------------
    # Threshold — local (non-IjkGrid) implementation

    def _add_threshold_local(self, parent_name, array):
        if not array:
            return None
        upstream_root = self._ensure_extractor() or self._fallback_legacy_source()
        if upstream_root is None:
            return None
        if parent_name is not None and not any(e.name == parent_name for e in self._chain):
            print(f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                  f" add_threshold: unknown parent {parent_name!r}")
            return None
        assoc = self._resolve_assoc(array)
        if not assoc:
            return None

        from fespp_on_trame.app.core.sources.representation import _sanitize
        from fespp_on_trame.app.core.sources.extract_block import (
            ChainEntry, resolve_chain_kind,
        )
        rep_token = _sanitize(self.rep_path)
        view_token = _sanitize(str(self.scene.view_id))
        if parent_name is None:
            base_name = f"thr_{rep_token}_{_sanitize(array)}_v{view_token}"
        else:
            base_name = f"{parent_name}_{_sanitize(array)}"

        existing_names = {e.name for e in self._chain}
        if base_name in existing_names:
            suffix = 2
            while f"{base_name}_{suffix}" in existing_names:
                suffix += 1
            base_name = f"{base_name}_{suffix}"

        rng = self.array_data_range(array) or (0.0, 1.0)
        upstream = self._effective_input_for_parent(parent_name)
        try:
            from paraview import simple as pvsimple
            proxy = pvsimple.Threshold(
                registrationName=base_name,
                Input=upstream,
            )
            proxy.Scalars = [assoc, array]
            proxy.LowerThreshold = float(rng[0])
            proxy.UpperThreshold = float(rng[1])
            proxy.UpdatePipeline()
        except Exception as exc:
            print(f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                  f" Threshold create {base_name}: {exc}")
            return None

        # Resolve property kind (Continuous / Discrete / Categorical)
        # + unique values (for Discrete / Categorical ticks) + LUT
        # labels (Categorical only). Drives the threshold panel's
        # slider variant via `to_dict()`.
        kind, unique_values, labels = resolve_chain_kind(
            self.scene.tree, self.rep_path, array,
            upstream_root, assoc,
        )

        entry = ChainEntry(
            name=base_name,
            parent_name=parent_name,
            array=array,
            assoc=assoc,
            proxy=proxy,
            visible=True,
            low=float(rng[0]),
            high=float(rng[1]),
            data_range=(float(rng[0]), float(rng[1])),
            kind=kind,
            unique_values=unique_values,
            labels=labels,
        )
        self._chain.append(entry)

        # Inherit display props from upstream so the new chain proxy
        # mirrors its parent visually from the moment it appears.
        self._inherit_display(proxy, upstream)
        self._refresh_chain_visibility()
        return base_name

    def _delete_threshold_local(self, name):
        idx = next((i for i, e in enumerate(self._chain) if e.name == name), -1)
        if idx < 0:
            return False
        target = self._chain[idx]
        for e in self._chain:
            if e.parent_name == name:
                e.parent_name = target.parent_name
        self._chain.pop(idx)
        try:
            from paraview import simple as pvsimple
            if self.scene.pv_view is not None:
                pvsimple.Hide(proxy=target.proxy, view=self.scene.pv_view)
            pvsimple.Delete(target.proxy)
        except Exception:
            pass
        self._refresh_chain_visibility()
        return True

    def _delete_chain(self):
        """Tear down every chain proxy. Children-first to avoid
        dangling Inputs."""
        if not self._chain:
            return
        try:
            from paraview import simple as pvsimple
        except Exception:
            self._chain = []
            return
        for entry in reversed(self._chain):
            try:
                if self.scene.pv_view is not None:
                    pvsimple.Hide(proxy=entry.proxy, view=self.scene.pv_view)
            except Exception:
                pass
            try:
                pvsimple.Delete(entry.proxy)
            except Exception:
                pass
        self._chain = []

    def _resolve_assoc(self, array_name):
        for a, n in self.available_arrays():
            if n == array_name:
                return a
        return None

    def _entry_by_name(self, name):
        for e in self._chain:
            if e.name == name:
                return e
        return None

    def _effective_input_for_parent(self, parent_name):
        """Resolve the upstream a new/refreshed child reads from.
        parent_name=None → the per-view extractor (or legacy fallback).
        Otherwise walk up skipping hidden ancestors."""
        if parent_name is None:
            return self._ensure_extractor() or self._fallback_legacy_source()
        cursor = self._entry_by_name(parent_name)
        while cursor is not None and not cursor.visible:
            cursor = self._entry_by_name(cursor.parent_name)
        if cursor is None:
            return self._ensure_extractor() or self._fallback_legacy_source()
        return cursor.proxy

    def _has_visible_descendant(self, name):
        for child in (e for e in self._chain if e.parent_name == name):
            if child.visible:
                return True
            if self._has_visible_descendant(child.name):
                return True
        return False

    def _refresh_chain_visibility(self):
        """Recompute Input wiring + Visibility for every chain entry.
        Display rules:
          - entry shown iff entry.visible AND no visible descendant;
          - rep source hidden when a chain tip is shown OR slice/clip
            is enabled OR the user hid the rep via the eye chip.

        Show/Hide targets `self.scene.pv_view` — per-(rep, view) by
        design."""
        if self._is_ijk_grid():
            return
        view = self.scene.pv_view
        if view is None:
            return
        try:
            from paraview import simple as pvsimple
        except Exception:
            return

        try:
            from trame.app import get_server
            hidden_by_view = get_server().state.ui_hidden_rep_paths_by_view or {}
            panel_hidden = hidden_by_view.get(self.scene.view_id, []) or []
        except Exception:
            panel_hidden = []
        rep_hidden_by_user = self.rep_path in panel_hidden
        rep_hidden_by_slice = self._slice_plane is not None and self._slice_plane.enabled
        rep_hidden_by_clip = self._clip_plane is not None and self._clip_plane.enabled
        rep_hidden = (rep_hidden_by_user or rep_hidden_by_slice or rep_hidden_by_clip)

        any_shown = False
        for entry in self._chain:
            upstream = self._effective_input_for_parent(entry.parent_name)
            try:
                if entry.proxy.Input is not upstream:
                    entry.proxy.Input = upstream
                    entry.proxy.UpdatePipeline()
            except Exception as exc:
                print(f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                      f" chain rewire {entry.name}: {exc}")
            try:
                tip = entry.visible and not self._has_visible_descendant(entry.name)
                show = tip and not rep_hidden
                if show:
                    pvsimple.Show(proxy=entry.proxy, view=view)
                    any_shown = True
                else:
                    pvsimple.Hide(proxy=entry.proxy, view=view)
            except Exception:
                pass

        # Re-assert primary source visibility now that we know whether
        # a chain tip is shown.
        primary = self._ensure_extractor() or self._fallback_legacy_source()
        if primary is None:
            return
        try:
            if rep_hidden or any_shown:
                pvsimple.Hide(proxy=primary, view=view)
            else:
                pvsimple.Show(proxy=primary, view=view)
        except Exception:
            pass

    def _inherit_display(self, thr_proxy, upstream):
        """Copy Representation / Scale / ColorArrayName / LookupTable /
        DiffuseColor / Opacity from upstream's display in this scene's
        view onto the new threshold proxy's display. Mirrors the same
        helper in `ExtractBlockRepresentation`."""
        view = self.scene.pv_view
        if view is None:
            return
        try:
            from paraview import simple as pvsimple
            src_disp = pvsimple.GetDisplayProperties(upstream, view=view)
            thr_disp = pvsimple.GetRepresentation(proxy=thr_proxy, view=view)
            if src_disp is None or thr_disp is None:
                return
            for attr, as_list in (
                ("Representation", False),
                ("Scale", True),
                ("ColorArrayName", True),
                ("LookupTable", False),
                ("DiffuseColor", True),
                ("AmbientColor", True),
                ("Opacity", False),
            ):
                try:
                    val = getattr(src_disp, attr)
                    if as_list:
                        val = list(val)
                    setattr(thr_disp, attr, val)
                except Exception:
                    pass
        except Exception:
            pass

    # ==================================================================
    # Phase 3c — snapshot / apply primitives per concern
    #
    # Each concern (threshold chain, slice, clip) exposes a pair:
    #   - `snapshot_*()  → dict`   — serialise the current state
    #   - `apply_*(snap)`          — restore state from a snapshot
    #
    # Snapshots are plain json-safe dicts (lists, strings, floats,
    # bools). Roundtrip invariant: `apply(snapshot(x)) ≈ x` visually
    # — chain entry names will differ across views (suffixed with
    # view_id) so name-equality is NOT preserved but parent-child
    # structure IS.
    #
    # Used by `SceneRegistry.replicate_view(src, dst)` for view-split
    # inheritance (decision D2) and by future per-concern "Copy from
    # View X" buttons (decision D1). IjkGrid reps return / accept
    # empty snapshots in Phase 3a (legacy IjkGrid stays in charge
    # until Phase 3b).

    def snapshot_threshold_chain(self) -> dict:
        """Serialise the threshold chain in DFS / insertion order so
        `apply_threshold_chain` can replay each entry with its parent
        already present.

        IjkGrid: snapshot the per-view IjkGrid's chain. Reads ONLY
        from the per-view instance (never legacy) so a copy never
        captures stale shared state. Returns empty when the per-view
        IjkGrid isn't built yet."""
        if self._is_ijk_grid():
            ijk = self._ensure_per_view_ijk()
            if ijk is None or not hasattr(ijk, "get_chain"):
                return {"entries": []}
            return {
                "entries": [
                    {
                        "name": e.get("name"),
                        "parent_name": e.get("parent_name"),
                        "array": e.get("array"),
                        "visible": bool(e.get("visible", True)),
                        "low": float(e.get("low", 0.0)),
                        "high": float(e.get("high", 1.0)),
                    }
                    for e in ijk.get_chain()
                ],
            }
        return {
            "entries": [
                {
                    "name": e.name,
                    "parent_name": e.parent_name,
                    "array": e.array,
                    "assoc": e.assoc,
                    "visible": bool(e.visible),
                    "low": float(e.low),
                    "high": float(e.high),
                }
                for e in self._chain
            ],
        }

    def apply_threshold_chain(self, snap: dict | None) -> None:
        """Replace this view's threshold chain with the snapshot's.
        Names in the snapshot are SOURCE-view names; we map them to
        DESTINATION-view names as we add entries so `parent_name`
        references resolve correctly.

        IjkGrid: replay onto the per-view IjkGrid only (never legacy
        — a stray write there would mutate state shared by every
        scene). Tear-down uses `delete_threshold` per existing entry
        — IjkGrid's `delete_threshold` rewires children onto the
        deleted entry's parent, so iterating in any order is safe."""
        if not snap:
            return
        entries = snap.get("entries") or []
        if self._is_ijk_grid():
            ijk = self._ensure_per_view_ijk()
            if ijk is None or not hasattr(ijk, "add_threshold"):
                return
            for e in list(ijk.get_chain()):
                try:
                    ijk.delete_threshold(e.get("name"))
                except Exception:
                    pass
            old_to_new: dict = {}
            for entry in entries:
                old_parent = entry.get("parent_name")
                new_parent = old_to_new.get(old_parent) if old_parent else None
                try:
                    new_name = ijk.add_threshold(new_parent, entry.get("array"))
                except Exception as exc:
                    print(f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                          f" ijk apply add_threshold: {exc}")
                    continue
                if new_name is None:
                    continue
                old_to_new[entry.get("name")] = new_name
                try:
                    ijk.set_range(new_name, entry.get("low", 0.0), entry.get("high", 1.0))
                except Exception:
                    pass
                try:
                    ijk.set_visible(new_name, bool(entry.get("visible", True)))
                except Exception:
                    pass
            return
        # Tear down current chain so apply == replace, not merge.
        self._delete_chain()
        old_to_new: dict = {}
        for entry in entries:
            old_parent = entry.get("parent_name")
            new_parent = old_to_new.get(old_parent) if old_parent else None
            new_name = self._add_threshold_local(new_parent, entry.get("array"))
            if new_name is None:
                continue
            old_to_new[entry.get("name")] = new_name
            try:
                self.set_range(new_name, entry.get("low", 0.0), entry.get("high", 1.0))
            except Exception:
                pass
            try:
                self.set_visible(new_name, bool(entry.get("visible", True)))
            except Exception:
                pass

    def snapshot_slice(self) -> dict:
        """Plain dict with the SlicePlane descriptor — same shape as
        `slice_state()` (enabled, axis, offset, bounds)."""
        if self._slice_plane is None:
            return {}
        try:
            return dict(self._slice_plane.to_dict())
        except Exception:
            return {}

    def apply_slice(self, snap: dict | None) -> None:
        """Restore a slice snapshot. `bounds` is informational (driven
        by upstream geometry), so we only replay enabled/axis/offset."""
        if not snap:
            return
        self.slice_set(
            enabled=snap.get("enabled"),
            axis=snap.get("axis"),
            offset=snap.get("offset"),
        )

    def snapshot_clip(self) -> dict:
        if self._clip_plane is None:
            return {}
        try:
            return dict(self._clip_plane.to_dict())
        except Exception:
            return {}

    def apply_clip(self, snap: dict | None) -> None:
        if not snap:
            return
        self.clip_set(
            enabled=snap.get("enabled"),
            axis=snap.get("axis"),
            offset=snap.get("offset"),
            inside_out=snap.get("inside_out"),
        )

    def snapshot_ijk_slicers(self) -> dict:
        """Phase 3b — snapshot the per-view IjkGrid's slicer / volume /
        mode / visibility state. Reuses `IjkGrid.to_ui_state()` whose
        shape is the same flat dict the UI state vars consume, which
        keeps `apply_ijk_slicers` symmetric and removes a serialisation
        hop.

        Returns `{}` for non-IjkGrid reps and when no per-view IjkGrid
        has been built yet (no property selected on this view). Reads
        ONLY from the per-view IjkGrid — never the legacy shared one,
        whose slicer state goes stale once Phase 3b owns per-view
        edits and would leak across views if returned here."""
        if not self._is_ijk_grid():
            return {}
        ijk = self._ensure_per_view_ijk()
        if ijk is None or not hasattr(ijk, "to_ui_state"):
            return {}
        snap = ijk.to_ui_state()
        return dict(snap) if snap else {}

    def apply_ijk_slicers(self, snap: dict | None) -> None:
        """Restore the slicer / volume / mode state from a snapshot.

        Mirror of `IjkGrid.apply_*` calls in dependency order:
        positions (rebuilds slicer proxies) → visibility → range
        (sets volume crop extent) → mode (flips active upstream set,
        rebuilds chain attachments) → volume visibility. A final
        `show()` re-publishes Visibility on every proxy.

        No-op for non-IjkGrid reps and when the per-view IjkGrid
        isn't built yet — the dest scene's per-view will pick the
        right state via `_eager_setup_rep_in_scene` + the standard
        panel-switch republish. We deliberately do NOT fall back to
        the legacy IjkGrid here: a stray write would mutate state
        shared by every scene."""
        if not snap or not self._is_ijk_grid():
            return
        ijk = self._ensure_per_view_ijk()
        if ijk is None:
            return
        try:
            if all(k in snap for k in ("ui_slices_i_list", "ui_slices_j_list", "ui_slices_k_list")):
                ijk.apply_slice_positions(
                    snap.get("ui_slices_i_list") or [],
                    snap.get("ui_slices_j_list") or [],
                    snap.get("ui_slices_k_list") or [],
                )
            if all(k in snap for k in (
                "ui_slices_i_visible_list",
                "ui_slices_j_visible_list",
                "ui_slices_k_visible_list",
            )):
                ijk.apply_slice_visibility(
                    snap.get("ui_slices_i_visible_list") or [],
                    snap.get("ui_slices_j_visible_list") or [],
                    snap.get("ui_slices_k_visible_list") or [],
                )
            ri = snap.get("ui_slices_range_i")
            rj = snap.get("ui_slices_range_j")
            rk = snap.get("ui_slices_range_k")
            if ri and rj and rk:
                ijk.apply_range(ri, rj, rk)
            mode = snap.get("ui_slices_range_mode")
            if mode:
                ijk.apply_mode(mode)
            if "ui_slices_volume_visible" in snap:
                ijk.apply_volume_visible(snap.get("ui_slices_volume_visible"))
            if hasattr(ijk, "show"):
                ijk.show()
        except Exception as exc:
            print(
                f"[RepInScene {self.scene.view_id}/{self.rep_path}]"
                f" apply_ijk_slicers: {exc}"
            )

    # ------------------------------------------------------------------
    # Helpers

    def _legacy_instance(self):
        """The legacy per-rep wrapper (IjkGrid or
        ExtractBlockRepresentation) that still owns shared state for
        IjkGrid reps. For non-IjkGrid reps in Phase 3a this is also
        used as a fallback when the per-view extractor can't be built
        (Phase 2 fallback path)."""
        try:
            from trame.app import get_server
            ctx = get_server().context
            legacy = getattr(ctx, "source_registry", None)
            if legacy is None:
                return None
            ijk = legacy.get_ijk_grid(self.rep_path) if hasattr(legacy, "get_ijk_grid") else None
            if ijk is not None:
                return ijk
            eb = legacy.get_extract_block(self.rep_path) if hasattr(legacy, "get_extract_block") else None
            return eb
        except Exception:
            return None

    def __repr__(self) -> str:
        return (
            f"<RepInScene view={self.scene.view_id!r} rep_path={self.rep_path!r}>"
        )


# ------------------------------------------------------------------
# Array introspection helpers — duplicated from ExtractBlockRepresentation
# so this module doesn't import from the soon-to-be-deprecated one.

def _arrays_from_source(src):
    """Return [(assoc, name), ...] for a PV proxy's CellData /
    PointData. Same shape as ExtractBlockRepresentation.available_arrays."""
    if src is None:
        return []
    out, seen = [], set()
    for store_attr, assoc in (("CellData", "CELLS"), ("PointData", "POINTS")):
        try:
            store = getattr(src, store_attr)
            for i in range(store.GetNumberOfArrays()):
                a = store.GetArray(i)
                if a is None:
                    continue
                name = a.Name
                key = (assoc, name)
                if name and key not in seen:
                    seen.add(key)
                    out.append(key)
        except Exception:
            pass
    return out


def _array_range_from_source(src, array_name):
    """Return (min, max) for the named array on a PV proxy, or None."""
    if src is None or not array_name:
        return None
    for store_attr in ("CellData", "PointData"):
        try:
            store = getattr(src, store_attr)
            for i in range(store.GetNumberOfArrays()):
                a = store.GetArray(i)
                if a is not None and a.Name == array_name:
                    rng = a.GetRange()
                    return (float(rng[0]), float(rng[1]))
        except Exception:
            pass
    return None
