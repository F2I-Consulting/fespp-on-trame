"""SceneRegistry — façade exposed to the engine for per-view scenes.

See `doc/REFACTOR_VIEW_SCENES.md`. The registry owns:

  - one `ViewScene` per render view (created on `add_view`, dropped
    on `remove_view`);
  - global data-layer ops (push selectors to the EPCCollector,
    apply Z-scale across all scenes, apply representation type).

For Phase 1 the registry COEXISTS with the existing
`SourceRegistry`. The engine continues to drive
data-loading / threshold / slice-clip through SourceRegistry, while
SceneRegistry only tracks the view→reps mapping. As phases
progress, methods will move from SourceRegistry to SceneRegistry.

Every state-mutating method emits a `[SCENE_REG]` log line to
stdout so the per-view bookkeeping is visible in the server log
without any client-side instrumentation. Logs are concise (one line
per mutation + a multi-line dump on demand) — easy to grep for.
"""
from typing import Optional


def _log_state(prefix: str, scenes: list, collector_source=None) -> None:
    """Multi-line dump of the current view→reps mapping. Used after
    every mutation so the server log stays self-narrating."""
    print(f"[SCENE_REG] {prefix} | views={len(scenes)}")
    for scene in scenes:
        reps = list(scene._reps.keys())
        clone_state = (
            "shared"
            if collector_source is not None and scene.clone is collector_source
            else type(scene.clone).__name__ if scene.clone is not None else "None"
        )
        print(f"[SCENE_REG]   {scene.view_id} ({len(reps)} reps) clone={clone_state}")
        for rp in reps:
            print(f"[SCENE_REG]     {rp}")


class SceneRegistry:
    """Per-view scene manager. See module docstring."""

    def __init__(self, collector, tree):
        self.collector = collector
        self.tree = tree
        self._scenes: dict = {}  # view_id -> ViewScene

    # ------------------------------------------------------------------
    # View lifecycle (called by FesppMultiView on add_view / close)

    def add_view(self, view_id, pv_view):
        """Idempotent: returns the existing scene if already created.
        The PV view is captured so the scene knows where to render
        its per-view filters (Phase 1.b)."""
        from fespp_on_trame.app.core.sources.view_scene import ViewScene
        view_id = str(view_id)
        existing = self._scenes.get(view_id)
        if existing is not None:
            print(f"[SCENE_REG] add_view({view_id}) | already present, no-op")
            return existing
        scene = ViewScene(
            view_id=view_id,
            pv_view=pv_view,
            collector=self.collector,
            tree=self.tree,
        )
        self._scenes[view_id] = scene
        _log_state(f"add_view({view_id})", list(self._scenes.values()),
                   self.collector.get_source() if self.collector is not None else None)
        return scene

    def remove_view(self, view_id) -> None:
        """Destroy the scene + every rep it owns. No-op when the
        scene doesn't exist."""
        view_id = str(view_id)
        scene = self._scenes.pop(view_id, None)
        if scene is None:
            print(f"[SCENE_REG] remove_view({view_id}) | not present, no-op")
            return
        try:
            scene.destroy()
        except Exception as exc:
            print(f"[SCENE_REG] remove_view({view_id}) destroy failed: {exc}")
        _log_state(f"remove_view({view_id})", list(self._scenes.values()),
                   self.collector.get_source() if self.collector is not None else None)

    def get_scene(self, view_id):
        return self._scenes.get(str(view_id))

    def scene_for_pv_view(self, pv_view):
        """Reverse lookup: scene whose `pv_view` proxy IS `pv_view`.
        Used by `source_resolver.apply_color_array` to find the scene
        that owns a display's view so it can swap in a per-view LUT.
        Returns None when `pv_view` doesn't belong to any scene
        (legacy / pre-Phase-1 callers passing the global active view)."""
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
        """For every scene, add a RepInScene for each loaded rep that
        isn't there yet, and remove RepInScenes whose rep_path is
        no longer loaded. Idempotent. Skips the log when no scene
        was mutated.

        Phase 3a: after `scene.add_rep(r)` we **eagerly** force the
        per-view EnergisticsExtractor creation + replicate the active
        view's ColorBy state for that rep onto the new scene. Without
        this, a split view doesn't get its per-view pipeline until the
        user clicks a property in it — and meanwhile the new view
        shows a stale legacy display (the Z-fighting / phantom-outline
        bug observed during smoke test).

        This is the minimal "view split inherits active view state"
        bootstrap for slice/clip/threshold; the full snapshot/apply
        replication (D2 from the RFC) lands in Phase 3c."""
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
        if added or removed:
            _log_state(
                f"sync_loaded_reps | +{added} added, -{removed} removed",
                list(self._scenes.values()),
                self.collector.get_source() if self.collector is not None else None,
            )

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
        # (1) Force per-view extractor (skips IjkGrid as Phase 3b territory).
        try:
            rep.source()
        except Exception as exc:
            print(f"[SCENE_REG] eager source({scene.view_id}/{rep_path}): {exc}")
            return

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
            print(f"[SCENE_REG] eager colorby({scene.view_id}/{rep_path}): {exc}")

    def _source_registry(self):
        """Lazy fetch of `source_registry` from server.context — same
        pattern the rest of the package uses to avoid a circular
        import from boot.py."""
        try:
            from trame.app import get_server
            return getattr(get_server().context, "source_registry", None)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Phase 3b — per-view IjkGrid sync
    #
    # The engine drives IjkGrid property selection through the legacy
    # `SourceRegistry.ensure_ijk_grid(rep_path, prop_node_id)` flow.
    # When that fires we fan the new property to every per-view
    # IjkGrid so split views stay in step with the active selection.
    # Without this hook, a property change updates only the legacy
    # shared IjkGrid and the per-view variants render the previous
    # property until they're recreated.

    def mirror_legacy_ijk_state(self, rep_path, legacy_ijk) -> None:
        """Copy the legacy IjkGrid's full slicer / volume / mode /
        visibility state onto every per-view IjkGrid for `rep_path`.

        Stop-gap until per-view IjkGrid SLICER divergence is wired up
        through the UI panel — for now per-view IjkGrids stay in
        lockstep with the legacy slicer config (the per-view
        divergence in Phase 3b applies to ColorBy / slice plane /
        clip plane / threshold chain, which is the bulk of the user's
        visual story). Slicer-position divergence per view requires
        the `ui_slices_*` state vars to become per-view, plus a
        republish on panel switch — separate epic. Until then, this
        mirror prevents the per-view variants from rendering stale
        slicer positions after a UI edit on the active panel."""
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
                print(f"[SCENE_REG] mirror_legacy_ijk_state"
                      f"({scene.view_id}/{rep_path}): {exc}")

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
                print(f"[SCENE_REG] refresh_per_view_ijk_for_rep"
                      f"({scene.view_id}/{rep_path}): {exc}")

    # ------------------------------------------------------------------
    # Phase 3c — view replication via snapshot/apply primitives
    #
    # Builds on `RepInScene.snapshot_*` / `apply_*`. Used by:
    #   - the "Copy from View X" buttons (when wired up in Phase 3c UI);
    #   - the view-split inheritance handler (decision D2: a new view
    #     starts with the active view's full state).
    #
    # `_eager_setup_rep_in_scene` above provides the BOOTSTRAP for new
    # reps in a new scene (per-view extractor + ColorBy replication).
    # `replicate_view` extends that with per-concern state copy: every
    # rep's slice / clip / threshold chain is mirrored from src to dst.

    def replicate_view(self, src_view_id, dst_view_id, *,
                       concerns: tuple[str, ...] = ("threshold", "slice", "clip", "ijk_slicers")) -> None:
        """Copy per-concern state from `src_view_id` to `dst_view_id`.
        Idempotent. Missing reps on the destination are added on the
        fly. Use the optional `concerns` tuple to scope a copy to a
        single concern (e.g. "Copy threshold chain from View 2" calls
        `replicate_view(2, active, concerns=("threshold",))`).

        Default concerns include `ijk_slicers` (Phase 3b full): a split
        view inherits the source view's per-view IjkGrid slicer / volume
        / mode state. Non-IjkGrid reps return empty `snapshot_ijk_slicers`
        and the apply is a no-op for them, so the concern is safe to
        include unconditionally."""
        src = self.get_scene(str(src_view_id))
        dst = self.get_scene(str(dst_view_id))
        if src is None or dst is None:
            print(f"[SCENE_REG] replicate_view({src_view_id}→{dst_view_id}):"
                  f" src/dst not found")
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
                    print(f"[SCENE_REG] replicate ijk_slicers {dst_view_id}/{rep_path}: {exc}")
            if "threshold" in concerns:
                try:
                    dst_rep.apply_threshold_chain(src_rep.snapshot_threshold_chain())
                except Exception as exc:
                    print(f"[SCENE_REG] replicate threshold {dst_view_id}/{rep_path}: {exc}")
            if "slice" in concerns:
                try:
                    dst_rep.apply_slice(src_rep.snapshot_slice())
                except Exception as exc:
                    print(f"[SCENE_REG] replicate slice {dst_view_id}/{rep_path}: {exc}")
            if "clip" in concerns:
                try:
                    dst_rep.apply_clip(src_rep.snapshot_clip())
                except Exception as exc:
                    print(f"[SCENE_REG] replicate clip {dst_view_id}/{rep_path}: {exc}")
        print(f"[SCENE_REG] replicate_view({src_view_id}→{dst_view_id})"
              f" concerns={concerns}")

    # ------------------------------------------------------------------
    # Teardown

    def release_all(self) -> None:
        for view_id in list(self._scenes.keys()):
            self.remove_view(view_id)
