"""SceneRegistry — façade exposed to the engine for per-view scenes.

The registry owns:

  - one `ViewScene` per render view (created on `add_view`, dropped
    on `remove_view`);
  - global data-layer ops (push selectors to the EPCCollector,
    apply Z-scale across all scenes, apply representation type).
"""
from typing import Optional


class SceneRegistry:
    """Per-view scene manager. See module docstring."""

    def __init__(self, collector, tree):
        self.collector = collector
        self.tree = tree
        self._scenes: dict = {}  # view_id -> ViewScene

    # ------------------------------------------------------------------
    # View lifecycle (called by FesppMultiView on add_view / close)

    def add_view(self, view_id, pv_view):
        """Idempotent: returns the existing scene if already created. The PV
        view is captured so the scene knows where to render its per-view
        filters."""
        from fespp_on_trame.app.core.sources.view_scene import ViewScene
        view_id = str(view_id)
        existing = self._scenes.get(view_id)
        if existing is not None:
            return existing
        scene = ViewScene(
            view_id=view_id,
            pv_view=pv_view,
            collector=self.collector,
            tree=self.tree,
        )
        self._scenes[view_id] = scene
        return scene

    def remove_view(self, view_id) -> None:
        """Destroy the scene + every rep it owns. No-op when the
        scene doesn't exist."""
        view_id = str(view_id)
        scene = self._scenes.pop(view_id, None)
        if scene is None:
            return
        try:
            scene.destroy()
        except Exception:
            pass

    def get_scene(self, view_id):
        return self._scenes.get(str(view_id))

    def scene_for_pv_view(self, pv_view):
        """Reverse lookup: scene whose `pv_view` proxy IS `pv_view`. Used by
        `source_resolver.apply_color_array` to find the scene that owns a
        display's view so it can swap in a per-view LUT. Returns None when
        `pv_view` doesn't belong to any scene (a caller passing the global
        active view)."""
        if pv_view is None:
            return None
        for scene in self._scenes.values():
            if scene.pv_view is pv_view:
                return scene
        return None

    def has_view(self, view_id) -> bool:
        return str(view_id) in self._scenes

    def view_ids(self) -> list:
        return list(self._scenes.keys())

    def all_scenes(self):
        return list(self._scenes.values())

    # ------------------------------------------------------------------
    # Per-(view, rep) accessor — the main facade for the future
    # per-view dispatchers (slice / clip / threshold).

    def get_rep(self, view_id, rep_path):
        scene = self.get_scene(view_id)
        if scene is None:
            return None
        return scene.get_rep(rep_path)

    def ensure_rep(self, view_id, rep_path):
        """Get-or-create the RepInScene for (view_id, rep_path)."""
        scene = self.get_scene(view_id)
        if scene is None:
            return None
        return scene.add_rep(rep_path)

    # ------------------------------------------------------------------
    # Bookkeeping helpers — keep the scenes in sync with the loaded
    # reps set. Called by the engine after a data_load run.

    def sync_loaded_reps(self, loaded_rep_paths) -> None:
        """For every scene, add a RepInScene for each loaded rep that isn't
        there yet, and remove RepInScenes whose rep_path is no longer loaded.
        Idempotent. Skips the log when no scene was mutated.

        After `scene.add_rep(r)` it eagerly forces per-view
        EnergisticsExtractor creation and replicates the active view's ColorBy
        state for that rep onto the new scene, so a split view paints its
        per-view pipeline immediately instead of waiting for the user to click
        a property in it (and showing a stale legacy display meanwhile)."""
        loaded = set(loaded_rep_paths or [])
        added = 0
        removed = 0
        for scene in self._scenes.values():
            existing = set(scene._reps.keys())
            for r_path in loaded - existing:
                rep = scene.add_rep(r_path)
                added += 1
                self._eager_setup_rep_in_scene(scene, rep, r_path)
            for r_path in existing - loaded:
                scene.remove_rep(r_path)
                removed += 1

    def _eager_setup_rep_in_scene(self, scene, rep, rep_path) -> None:
        """Make a freshly-added (scene, rep_path) pair render
        immediately:

          1. Force per-view extractor creation (Hides the legacy EB in
             scene.pv_view so we don't Z-fight with it).
          2. Replicate the active panel's ColorBy onto the new scene
             so the new view paints the same property the user is
             currently looking at, instead of starting blank / default
             tinted.

        Best-effort: every exception is swallowed (the worst case is a
        view that still needs an explicit click to color)."""
        if rep is None or not rep_path:
            return
        # (1) Force per-view extractor.
        try:
            rep.source()
        except Exception as exc:
            return

        # (1b) A rep the engine flagged hidden in THIS view's bucket (every
        # NON-active panel at first load) is BUILT above but must not RENDER
        # here, so a newly-selected rep appears only in the active view. The
        # non-IJK extractor already honoured the bucket inside
        # `_ensure_extractor`; this also covers the IJK per-view pipeline
        # (whose `IjkGrid.show()` always re-shows its slicers).
        try:
            if rep._hidden_in_scene():
                rep.hide_in_scene_view()
        except Exception as exc:
            pass

        # (2) Replicate the active view's ColorBy for this rep onto
        #     the new scene. The bind point per rep is stored in
        #     `ui_active_array_by_rep_by_view[active_panel_id][rep_path]`.
        try:
            from trame.app import get_server
            server = get_server()
            state = server.state
            active_panel = getattr(state, "fespp_active_panel_id", "") or ""
            if not active_panel:
                return
            by_view = state.ui_active_array_by_rep_by_view or {}
            active_array_path = (by_view.get(active_panel, {}) or {}).get(rep_path)
            if not active_array_path:
                return
            # Mirror the active array binding into the new view's
            # bucket so subsequent panel switches / republishes find it.
            new_bucket_key = scene.view_id
            new_panel_map = dict(by_view.get(new_bucket_key, {}) or {})
            new_panel_map[rep_path] = active_array_path
            new_by_view = dict(by_view)
            new_by_view[new_bucket_key] = new_panel_map
            state.ui_active_array_by_rep_by_view = new_by_view

            # Wellbore frame: SHOW the active channel in the new view via
            # its OWN per-channel extractor (exclusive) so a split inherits
            # the displayed log; apply_color_array then ColorBy's the
            # now-visible channel extractor. Gated on the hidden-in-scene
            # bucket so a FIRST selection's channel appears only in the
            # active view (non-active panels build but don't render it).
            try:
                if rep._is_wellbore_frame() and not rep._hidden_in_scene():
                    rep.set_channel_visible(active_array_path, True)
            except Exception:
                pass

            # Fan ColorBy onto the new view's per-view extractor +
            # chain. Mirrors the per-realization handling so the
            # right `_real_<idx>` suffixed array is picked.
            by_view_real = state.ui_active_realization_by_array_by_view or {}
            realization_idx = (by_view_real.get(new_bucket_key, {}) or {}).get(active_array_path)
            from fespp_on_trame.app.core.engine import source_resolver
            source_resolver.apply_color_array(
                self._source_registry(),
                self.tree,
                rep_path,
                active_array_path,
                view=scene.pv_view,
                realization_idx=realization_idx,
            )
        except Exception as exc:
            pass

    def _source_registry(self):
        """Lazy fetch of `source_registry` from server.context — same
        pattern the rest of the package uses to avoid a circular
        import from boot.py."""
        try:
            from trame.app import get_server
            return getattr(get_server().context, "source_registry", None)
        except Exception:
            return None

    def apply_visible_markers(self, view_id) -> None:
        """Show every marker listed in `ui_visible_marker_paths_by_view`
        for `view_id` in that scene — used after a view split so the new
        view inherits the source view's visible markers (each rendered
        via its own per-marker EnergisticsExtractor). No-op when the
        bucket is empty."""
        view_id = str(view_id)
        scene = self.get_scene(view_id)
        if scene is None:
            return
        try:
            from trame.app import get_server
            state = get_server().state
            markers = list(
                (state.ui_visible_marker_paths_by_view or {}).get(view_id, []) or []
            )
        except Exception:
            markers = []
        if not markers:
            return
        for marker_path in markers:
            try:
                n_id = self.tree.find_node_id(marker_path)
                r_id = self.tree.find_representation_node(n_id) if n_id is not None else None
                r_path = self.tree.find_path(r_id) if r_id is not None else None
            except Exception:
                r_path = None
            if not r_path:
                continue
            rep = scene.get_rep(r_path) or scene.add_rep(r_path)
            if rep is None:
                continue
            try:
                rep.set_marker_visible(marker_path, True)
            except Exception as exc:
                pass

    # ------------------------------------------------------------------
    # Per-view IjkGrid sync
    #
    # The engine drives IjkGrid property selection through
    # `SourceRegistry.ensure_ijk_grid(rep_path, prop_node_id)`. When that
    # fires we fan the new property to every per-view IjkGrid so split views
    # stay in step with the active selection; otherwise the per-view variants
    # would render the previous property until recreated.

    def mirror_legacy_ijk_state(self, rep_path, legacy_ijk) -> None:
        """Copy the legacy IjkGrid's full slicer / volume / mode / visibility
        state onto every per-view IjkGrid for `rep_path`.

        Per-view IjkGrids stay in lockstep with the legacy slicer config
        (per-view divergence covers ColorBy / slice plane / clip plane /
        threshold chain). This mirror keeps the per-view variants from
        rendering stale slicer positions after a UI edit on the active
        panel."""
        if not rep_path or legacy_ijk is None:
            return
        for scene in self._scenes.values():
            rep = scene.get_rep(rep_path)
            ijk = getattr(rep, "_per_view_ijk", None) if rep is not None else None
            if ijk is None:
                continue
            try:
                ijk.apply_slice_positions(
                    legacy_ijk._slices_i_list,
                    legacy_ijk._slices_j_list,
                    legacy_ijk._slices_k_list,
                )
                ijk.apply_slice_visibility(
                    legacy_ijk._slices_i_visible_list,
                    legacy_ijk._slices_j_visible_list,
                    legacy_ijk._slices_k_visible_list,
                )
                if legacy_ijk._slices_range_i and legacy_ijk._slices_range_j and legacy_ijk._slices_range_k:
                    ijk.apply_range(
                        legacy_ijk._slices_range_i,
                        legacy_ijk._slices_range_j,
                        legacy_ijk._slices_range_k,
                    )
                ijk.apply_mode(legacy_ijk._range_mode)
                ijk.apply_volume_visible(legacy_ijk._volume_visible)
                ijk.show()
            except Exception as exc:
                pass

    def refresh_per_view_ijk_for_rep(self, rep_path, prop_node_id) -> None:
        """For each scene that has a RepInScene for `rep_path`, call
        `refresh_per_view_ijk_property(prop_node_id)` so the per-view
        IjkGrid retargets at the new property. No-op for non-IJK reps
        and for scenes whose per-view IjkGrid hasn't been built yet
        (lazy: it'll pick the new property on first creation)."""
        if not rep_path:
            return
        for scene in self._scenes.values():
            rep = scene.get_rep(rep_path)
            if rep is None:
                continue
            try:
                rep.refresh_per_view_ijk_property(prop_node_id)
            except Exception as exc:
                pass

    # ------------------------------------------------------------------
    # View replication via snapshot/apply primitives
    #
    # Builds on `RepInScene.snapshot_*` / `apply_*`. Used by the "Copy from
    # View X" buttons and the view-split inheritance handler (a new view
    # starts with the active view's full state).
    #
    # `_eager_setup_rep_in_scene` above bootstraps new reps in a new scene
    # (per-view extractor + ColorBy replication). `replicate_view` extends
    # that with per-concern state copy: every rep's slice / clip / threshold
    # chain is mirrored from src to dst.

    def replicate_view(self, src_view_id, dst_view_id, *,
                       concerns: tuple[str, ...] = ("threshold", "slice", "clip", "ijk_slicers")) -> None:
        """Copy per-concern state from `src_view_id` to `dst_view_id`.
        Idempotent. Missing reps on the destination are added on the
        fly. Use the optional `concerns` tuple to scope a copy to a
        single concern (e.g. "Copy threshold chain from View 2" calls
        `replicate_view(2, active, concerns=("threshold",))`).

        The `ijk_slicers` concern makes a split view inherit the source
        view's per-view IjkGrid slicer / volume / mode state. Non-IjkGrid reps
        return an empty `snapshot_ijk_slicers` and the apply is a no-op for
        them, so the concern is safe to include unconditionally."""
        src = self.get_scene(str(src_view_id))
        dst = self.get_scene(str(dst_view_id))
        if src is None or dst is None:
            return
        if src is dst:
            return
        for rep_path, src_rep in list(src.reps()):
            dst_rep = dst.get_rep(rep_path) or dst.add_rep(rep_path)
            if dst_rep is None:
                continue
            # ijk_slicers FIRST: the per-view IjkGrid threshold chain
            # attaches its proxies to whichever slicers are currently
            # active. Applying slicers before thresholds means
            # `apply_threshold_chain` builds chain entries on the
            # correct (post-replicate) upstream set.
            if "ijk_slicers" in concerns:
                try:
                    dst_rep.apply_ijk_slicers(src_rep.snapshot_ijk_slicers())
                except Exception as exc:
                    pass
            if "threshold" in concerns:
                try:
                    dst_rep.apply_threshold_chain(src_rep.snapshot_threshold_chain())
                except Exception as exc:
                    pass
            if "slice" in concerns:
                try:
                    dst_rep.apply_slice(src_rep.snapshot_slice())
                except Exception as exc:
                    pass
            if "clip" in concerns:
                try:
                    dst_rep.apply_clip(src_rep.snapshot_clip())
                except Exception as exc:
                    pass

    # ------------------------------------------------------------------
    # Teardown

    def release_all(self) -> None:
        for view_id in list(self._scenes.keys()):
            self.remove_view(view_id)
