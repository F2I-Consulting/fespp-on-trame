"""Representation element types — have geometry, an eye, and a per-view
source. Family defaults: REP eye, rep tracking bucket, STANDARD show/hide,
COLORABLE. (Frames live in frames.py — they subclass Representation but are
folders-for-the-tree.)"""

from .base import ElementType
from .enums import TreeRole, VisibilityPolicy, ColorPolicy, EYE_REP, BUCKET_REP


class Representation(ElementType):
    """Base of the eye-bearing renderables."""

    def tree_role(self) -> TreeRole:
        return TreeRole.REPRESENTATION

    def eye_descriptor(self):
        return EYE_REP

    def tracking_bucket(self):
        return BUCKET_REP

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.STANDARD

    def color_policy(self) -> ColorPolicy:
        return ColorPolicy.COLORABLE

    # --- visibility behaviour (paraview imported lazily) ----------------

    def refresh_primary_visibility(self, ris):
        """Standard rep: SHOW the primary source unless slice / clip / a
        visible threshold-chain tip replaces it in this view."""
        view = ris.scene.pv_view
        upstream = ris.source()
        if view is None or upstream is None:
            return
        slice_on = ris._slice_plane is not None and ris._slice_plane.enabled
        clip_on = ris._clip_plane is not None and ris._clip_plane.enabled
        chain_visible = any(e.visible for e in ris._chain) if ris._chain else False
        should_hide = slice_on or clip_on or chain_visible
        try:
            from paraview import simple as pvsimple
            if should_hide:
                pvsimple.Hide(proxy=upstream, view=view)
            else:
                pvsimple.Show(proxy=upstream, view=view)
        except Exception:
            pass

    def hide_in_view(self, ris):
        """Hide the per-view primary extractor."""
        view = ris.scene.pv_view
        ext = ris._extractor
        if view is None or ext is None:
            return
        try:
            from paraview import simple as pvsimple
            pvsimple.Hide(proxy=ext, view=view)
        except Exception:
            pass

    # --- source construction --------------------------------------------

    def ensure_source(self, ris):
        """Head proxy = the per-view EnergisticsExtractor, or the shared
        fallback source when no per-view extractor exists."""
        ext = self.ensure_extractor(ris)
        return ext if ext is not None else ris._fallback_legacy_source()

    def ensure_extractor(self, ris):
        """Lazily build the per-(rep, view) EnergisticsExtractor (the
        standard rep source), store it on `ris._extractor`, and return it.
        Returns None when the scene has only the shared collector (no real
        clone). A frame keeps its freshly-built primary HIDDEN
        (``primary_hidden()``); other reps Show it unless the engine flagged
        the rep hidden in this view."""
        if ris._extractor is not None:
            return ris._extractor
        scene = ris.scene
        clone = getattr(scene, "clone", None)
        if clone is None:
            return None
        collector = getattr(scene, "collector", None)
        if collector is not None and clone is collector.get_source():
            # No real clone — don't chain on the shared collector (id() would
            # collide across views). Fall back to the shared source.
            return None
        # If the clone hasn't executed RequestData since upload, its output
        # assembly is empty → the EnergisticsExtractor resolves ExtractPath
        # against no data and emits an empty vtkPolyData placeholder. The
        # display is then Shown but paints nothing, and (since the clone's
        # input was already up-to-date when the clone was built) no later
        # Render or camera move re-executes it — only a fresh collector
        # UpdatePipeline does. Force the clone's data pass FIRST, mirroring
        # IjkGridRep.ensure_per_view_ijk and marker_dispatch.
        try:
            clone.UpdatePipeline()
        except Exception:
            pass
        tag = f"[{type(self).__name__} {scene.view_id}/{ris.rep_path}]"
        try:
            from paraview import simple as pvsimple
            from paraview.servermanager import vtkSMPropertyHelper
            from fespp_on_trame.app.core.sources.representation import (
                _sanitize, _apply_default_tint, _create_plugin_filter_proxy,
            )
            from trame.app import get_server
            state = get_server().state
            reg_name = f"rep_{_sanitize(ris.rep_path)}_v{scene.view_id}"
            ext = _create_plugin_filter_proxy(
                proxy_class="EnergisticsExtractor",
                registration_name=reg_name,
                inputs={"Input": clone},
            )
            if ext is None:
                return None
            # ExtractPath = the rep node (frames keep this primary hidden;
            # their children render via their own per-child extractors).
            vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(ris.rep_path)
            ext.SMProxy.UpdateVTKObjects()
            ext.UpdatePipelineInformation()
            # Data pass so the extractor materialises real geometry from the
            # (now-populated) clone before the first Show — without it the
            # display renders the empty placeholder until a later load.
            ext.UpdatePipeline()
            target_view = scene.pv_view
            # A frame keeps its primary hidden; a rep flagged hidden in this
            # view's bucket is BUILT but not shown (first selection appears
            # only in the active view).
            frame_no_channel = self.primary_hidden()
            hidden_here = ris._hidden_in_scene()
            for v in pvsimple.GetViews():
                if v is not target_view:
                    try:
                        pvsimple.Hide(proxy=ext, view=v)
                    except Exception:
                        pass
            if target_view is not None:
                disp = pvsimple.GetRepresentation(proxy=ext, view=target_view)
                if disp is not None:
                    from fespp_on_trame.app.core.sources.representation import rep_type_for
                    disp.Representation = rep_type_for(state, ris.rep_path)
                    disp.Scale = [1.0, 1.0, ris._current_z_scale()]
                    grid_color = (state.solid_color_by_rep or {}).get(ris.rep_path)
                    _apply_default_tint(disp, grid_color)
                if frame_no_channel or hidden_here:
                    pvsimple.Hide(proxy=ext, view=target_view)
                else:
                    pvsimple.Show(proxy=ext, view=target_view)
                # Hide the shared fallback source's display in THIS view so it
                # doesn't Z-fight the per-view extractor (it Shows itself at
                # creation; other views never get a fallback Show).
                legacy = ris._fallback_legacy_source()
                if legacy is not None and legacy is not ext:
                    try:
                        pvsimple.Hide(proxy=legacy, view=target_view)
                    except Exception:
                        pass
            ris._extractor = ext
        except Exception:
            ris._extractor = None
        return ris._extractor

    # --- rendered / colorable source sets (source_resolver delegation) ---

    def rendered_sources(self, ris):
        """The per-view extractor, with the deepest visible threshold-chain
        leaf substituted when a chain is active. None → fall through to the
        shared-source lookup (no per-view extractor)."""
        ext = ris._ensure_extractor()
        if ext is None:
            return None
        try:
            visibles = ris.all_visible_thresholds()
        except Exception:
            visibles = []
        return [visibles[-1] if visibles else ext]

    def color_sources(self, ris):
        """The per-view extractor + every chain proxy (ColorBy fan-out).
        None → fall through to legacy."""
        ext = ris._ensure_extractor()
        if ext is None:
            return None
        out = [ext]
        try:
            out.extend(ris.all_chain_proxies())
        except Exception:
            pass
        return out

    def array_candidate_source(self, ris, array_path):
        """The array lives on the rep's primary extractor."""
        return ris._ensure_extractor()


class GridRep(Representation):
    """Reservoir grids on the standard per-view extractor path
    (UnstructuredGrid, SubRepresentation). IjkGrid is the modal subclass."""

    KINDS = ("UnstructuredGrid", "Sub")


class IjkGridRep(GridRep):
    """The only kind that goes through the modal IjkGrid pipeline (I/J/K
    slicers + volume crop + threshold chain, range vs slice mode), built
    lazily once a property is active."""

    KINDS = ("IjkGrid",)

    def is_ijk_grid(self) -> bool:
        return True

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.IJK_MODAL

    def refresh_primary_visibility(self, ris):
        """Defer to the per-view IjkGrid's own show() — it is the authority
        on which sources render for the current range/slice mode. Calling
        Show on the rep_data extractor here would clobber that and rasterise
        the un-cropped full grid."""
        view = ris.scene.pv_view
        per_view_ijk = ris._per_view_ijk
        if view is None or per_view_ijk is None:
            return
        try:
            per_view_ijk.show(view=view)
        except Exception:
            pass

    def hide_in_view(self, ris):
        """Hide every IJK source (slicers + volume + rep_data + thresholds)."""
        view = ris.scene.pv_view
        ijk = ris._per_view_ijk
        if view is None or ijk is None:
            return
        try:
            from paraview import simple as pvsimple
        except Exception:
            return
        srcs = list(ijk._all_slice_sources())
        srcs.extend(ijk._src_volumes)
        if ijk._src_extract_init is not None:
            srcs.append(ijk._src_extract_init)
        try:
            srcs.extend(ijk.all_threshold_sources())
        except Exception:
            pass
        for s in srcs:
            if s is None:
                continue
            try:
                pvsimple.Hide(proxy=s, view=view)
            except Exception:
                pass

    def ensure_extractor(self, ris):
        # IJK reps use the IjkGrid pipeline, not the standard extractor.
        return None

    def ensure_source(self, ris):
        """Head proxy = the per-view IjkGrid's rep_data extractor, or the
        legacy shared source."""
        ijk = self.ensure_per_view_ijk(ris)
        if ijk is not None and ijk.source is not None:
            return ijk.source
        return ris._fallback_legacy_source()

    def ensure_per_view_ijk(self, ris):
        """Lazily build the per-(rep, view) IjkGrid pipeline rooted on the
        scene's clone, mirroring the legacy IjkGrid's currently selected
        property so the per-view variant renders the same thing. Stored on
        ris._per_view_ijk. Returns None when the legacy IjkGrid isn't
        initialised yet (no property selected → nothing to render)."""
        if ris._per_view_ijk is not None:
            return ris._per_view_ijk
        scene = ris.scene
        clone = getattr(scene, "clone", None)
        if clone is None:
            return None
        collector = getattr(scene, "collector", None)
        if collector is not None and clone is collector.get_source():
            # No real EPCCollectorClone — fall back to the shared IjkGrid.
            return None
        # Read the shared IjkGrid's current property node id to drive
        # set_node_id on the per-view instance.
        legacy = None
        try:
            from trame.app import get_server
            ctx = get_server().context
            source_registry = getattr(ctx, "source_registry", None)
            if source_registry is not None and hasattr(source_registry, "get_ijk_grid"):
                legacy = source_registry.get_ijk_grid(ris.rep_path)
        except Exception:
            legacy = None
        if legacy is None or getattr(legacy, "_node_id", None) is None:
            return None
        prop_node_id = None
        try:
            prop_path = getattr(legacy, "_property_path", None)
            if prop_path:
                prop_node_id = scene.tree.find_node_id(prop_path)
        except Exception:
            prop_node_id = None
        if prop_node_id is None:
            return None
        try:
            # CRITICAL: the per-view IjkGrid peeks at the clone's output
            # assembly to pick the output data type (ExplicitStructuredGrid
            # vs the vtkPolyData placeholder). If the clone hasn't executed
            # since upload its assembly is empty → every slicer rejects the
            # vtkPolyData input. Force the clone to populate FIRST.
            try:
                clone.UpdatePipeline()
            except Exception:
                pass
            from fespp_on_trame.app.core.sources.ijkgrid import IjkGrid
            ris._per_view_ijk = IjkGrid(
                collector, scene.tree,
                view_id=scene.view_id,
                clone=clone,
                pv_view=scene.pv_view,
            )
            ris._per_view_ijk.set_node_id(prop_node_id)
            if ris._per_view_ijk.source is None:
                ris._per_view_ijk = None
                return None
            # Hide the legacy IjkGrid's rendered sources in THIS view so the
            # per-view pipeline doesn't double-render with the legacy ones.
            ris._hide_legacy_ijk_in_scene_view(legacy)
        except Exception:
            ris._per_view_ijk = None
        return ris._per_view_ijk

    def rendered_sources(self, ris):
        """Every proxy the per-view IjkGrid renders (slicers + volume +
        rep_data), with each upstream's visible-tip proxies substituted.
        Union branches contribute multiple tips per upstream, so all
        disjoint intervals render. None → fall through to the legacy
        shared IjkGrid."""
        ijk = ris._ensure_per_view_ijk()
        if ijk is None or ijk.source is None:
            return None
        tips = ijk._visible_leaf_tips()
        grid_sources = list(ijk._all_slice_sources())
        grid_sources.extend(ijk._src_volumes)
        if ijk._src_extract_init is not None:
            grid_sources.append(ijk._src_extract_init)
        out = []
        for s in grid_sources:
            tip_proxies = [
                p for p in (t.pv_proxies.get(id(s)) for t in tips)
                if p is not None
            ]
            out.extend(tip_proxies if tip_proxies else [s])
        return out

    def color_sources(self, ris):
        """The colorable IJK proxies = slicers + volumes + rep_data +
        threshold leaves. rep_data is the proxy rendered for the COMPLETE
        grid (full mode, and a full-extent volume in range mode), so the
        active array must ColorBy it too. None → legacy."""
        ijk = ris._ensure_per_view_ijk()
        if ijk is None or ijk.source is None:
            return None
        out = list(ijk._all_slice_sources())
        out.extend(ijk._src_volumes)
        if ijk._src_extract_init is not None:
            out.append(ijk._src_extract_init)
        try:
            out.extend(ijk.all_threshold_sources())
        except Exception:
            pass
        return out


class SurfaceRep(Representation):
    """Simple geometry: one extractor, plain show/hide + colour."""

    KINDS = ("Grid2d", "PointSet", "Polyline", "PolylineSet", "TriangulatedSet")


class WellboreGeometryRep(Representation):
    """Simple wellbore tube geometry on one extractor (Trajectory creates a
    companion Wellhead MD label on activation; Completion/Perfo similar).

    NOTE: a perforation node's RUNTIME kind is ``'Perforation'`` (C++ sets it
    explicitly via ``treeViewNodeTypeName``, bypassing SimplifyXmlTag); the
    legacy Python lists also carry the abbreviated ``'Perfo'``. Both are
    matched here so the type resolves explicitly, not via the fallback."""

    KINDS = ("Trajectory", "Completion", "Perfo", "Perforation")


class SeismicFrameRep(Representation):
    """SeismicWellboreFrame — treated as a real eye-bearing rep (NOT a folder
    like the log/marker frames). Currently on standard rep defaults."""

    KINDS = ("SeismicWellboreFrame",)


class BlockedWellboreRep(Representation):
    """BlockedWellbore — a real eye-bearing rep with its OWN geometry (the
    subset of its supporting grid's cells the wellbore is blocked in, produced
    by the FESPP BlockedWellbore mapper). It sits UNDER the grid in the tree but
    is NOT a property of it: selecting it shows only the blocked cells, not the
    full grid. Standard rep defaults."""

    KINDS = ("BlockedWellbore",)
