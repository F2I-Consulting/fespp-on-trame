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
        except Exception as exc:
            print(f"[{type(self).__name__} {ris.scene.view_id}/{ris.rep_path}]"
                  f" parent visibility refresh: {exc}")

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
        """Head proxy = the per-view EnergisticsExtractor, or the legacy
        shared source as a Phase-2 fallback."""
        ext = self.ensure_extractor(ris)
        return ext if ext is not None else ris._fallback_legacy_source()

    def ensure_extractor(self, ris):
        """Lazily build the per-(rep, view) EnergisticsExtractor (the
        standard rep source), store it on `ris._extractor`, and return it.
        Returns None when the scene has only the shared collector (Phase 2
        fallback). A frame keeps its freshly-built primary HIDDEN
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
            # Phase 2 fallback — no real clone; don't chain on the shared
            # collector (id() would collide across views). Stay on legacy.
            return None
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
                print(f"{tag} EnergisticsExtractor not creatable — plugin missing?")
                return None
            # ExtractPath = the rep node (frames keep this primary hidden;
            # their children render via their own per-child extractors).
            vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(ris.rep_path)
            ext.SMProxy.UpdateVTKObjects()
            ext.UpdatePipelineInformation()
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
                    disp.Representation = state.representation_active or "Surface"
                    disp.Scale = [1.0, 1.0, ris._current_z_scale()]
                    grid_color = (state.solid_color_by_rep or {}).get(ris.rep_path)
                    _apply_default_tint(disp, grid_color)
                if frame_no_channel or hidden_here:
                    pvsimple.Hide(proxy=ext, view=target_view)
                else:
                    pvsimple.Show(proxy=ext, view=target_view)
                # Hide the legacy ExtractBlock's display in THIS view so it
                # doesn't Z-fight the per-view extractor (it Shows itself at
                # creation; other views never get a legacy Show).
                legacy = ris._fallback_legacy_source()
                if legacy is not None and legacy is not ext:
                    try:
                        pvsimple.Hide(proxy=legacy, view=target_view)
                    except Exception:
                        pass
            ris._extractor = ext
        except Exception as exc:
            print(f"{tag} extractor create failed: {exc}")
            ris._extractor = None
        return ris._extractor

    # --- rendered / colorable source sets (source_resolver delegation) ---

    def rendered_sources(self, ris):
        """The per-view extractor, with the deepest visible threshold-chain
        leaf substituted when a chain is active. None → fall through to
        legacy (no per-view extractor / Phase 2)."""
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

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.IJK_MODAL

    def refresh_primary_visibility(self, ris):
        """Defer to the per-view IjkGrid's own show() — it is the authority
        on which sources render for the current range/slice mode. Calling
        Show on the rep_data extractor here would clobber that and rasterise
        the un-cropped full grid (the red SolidColor Z-fight bug)."""
        view = ris.scene.pv_view
        per_view_ijk = ris._per_view_ijk
        if view is None or per_view_ijk is None:
            return
        try:
            per_view_ijk.show(view=view)
        except Exception as exc:
            print(f"[IjkGridRep {ris.scene.view_id}/{ris.rep_path}]"
                  f" per-view IjkGrid show: {exc}")

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
        if ijk._src_slicer_volume is not None:
            srcs.append(ijk._src_slicer_volume)
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
            # Phase 2 fallback (no real EPCCollectorClone) — stay on legacy.
            return None
        # Read the legacy IjkGrid's current property node id to drive
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
        except Exception as exc:
            print(f"[IjkGridRep {scene.view_id}/{ris.rep_path}]"
                  f" per-view IjkGrid create failed: {exc}")
            ris._per_view_ijk = None
        return ris._per_view_ijk

    def rendered_sources(self, ris):
        """Every proxy the per-view IjkGrid renders (slicers + volume +
        rep_data), with the deepest-visible-leaf proxy substituted. None →
        fall through to the legacy shared IjkGrid."""
        ijk = ris._ensure_per_view_ijk()
        if ijk is None or ijk.source is None:
            return None
        deepest_leaf = ijk._deepest_visible_leaf()
        grid_sources = list(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            grid_sources.append(ijk._src_slicer_volume)
        if ijk._src_extract_init is not None:
            grid_sources.append(ijk._src_extract_init)
        out = []
        for s in grid_sources:
            proxy = deepest_leaf.pv_proxies.get(id(s)) if deepest_leaf is not None else None
            out.append(proxy if proxy is not None else s)
        return out

    def color_sources(self, ris):
        """The colorable IJK proxies = slicers + volume + threshold leaves
        (NOT the rep_data extractor — it's hidden upstream). None → legacy."""
        ijk = ris._ensure_per_view_ijk()
        if ijk is None or ijk.source is None:
            return None
        out = list(ijk._all_slice_sources())
        if ijk._src_slicer_volume is not None:
            out.append(ijk._src_slicer_volume)
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
    like the log/marker frames). ⚠ Behaviour to be confirmed; kept on
    standard defaults for now (see TYPES_PARTICULARITES debt)."""

    KINDS = ("SeismicWellboreFrame",)
