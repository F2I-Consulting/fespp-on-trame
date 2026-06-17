"""Wellbore-frame element types — the dual nature: a FOLDER in the tree
(tri-state, no own eye, checking selects all children) BUT a Representation
in the source layer (owns the clone + render anchor; children render via
their OWN per-(child, view) extractors, so the frame's PRIMARY extractor
stays hidden). C++ side = ``MapperType::MapperSet``.

These classes also OWN the per-type child behaviour (the strategy pattern,
Option A): `RepInScene` keeps the per-(rep, view) state (the
`_channel_extractors` / `_marker_extractors` dicts, the scene), and passes
itself (`ris`) to these methods. The ONLY behavioural difference between a
log frame and a marker frame — EXCLUSIVE one-at-a-time vs MULTI — is the
`set_child_visible` override below; everything else (building a child
extractor, listing the shown ones) is shared on `FrameRep`. That override
boundary is the whole point of the hierarchy: change "one log at a time"
here and grids/surfaces/markers cannot be affected.

All ``paraview`` / ``trame`` / ``sources.*`` imports are LOCAL to the
methods so this package stays a leaf (no import cycle with the source
layer) and importable without a ParaView runtime (the tests rely on it)."""

from .representation import Representation
from .enums import TreeRole, VisibilityPolicy


class FrameRep(Representation):
    """Abstract base for wellbore frames — use Channel/Marker.

    Subclasses set ``_child_store_attr`` (the RepInScene dict holding their
    child extractors) and ``_reg_prefix`` (the proxy registration prefix)."""

    #: RepInScene attribute holding this frame's child extractors
    _child_store_attr = None
    #: registration-name prefix for a child's per-view extractor proxy
    _reg_prefix = None

    def tree_role(self) -> TreeRole:
        return TreeRole.FOLDER

    def is_grouping(self) -> bool:
        return True

    def eye_descriptor(self):
        return None

    def tracking_bucket(self):
        # The frame itself is not tracked; its children are (array/marker).
        return None

    def primary_hidden(self) -> bool:
        return True

    def refresh_primary_visibility(self, ris):
        """A frame keeps its primary HIDDEN — the children render via their
        own per-(child, view) extractors, so a generic visibility refresh
        must never Show the primary (else the C++ side surfaces the frame's
        first child in every view)."""
        view = ris.scene.pv_view
        upstream = ris.source()
        if view is None or upstream is None:
            return
        try:
            from paraview import simple as pvsimple
            pvsimple.Hide(proxy=upstream, view=view)
        except Exception:
            pass

    # --- child management (shared) --------------------------------------

    def _child_store(self, ris) -> dict:
        return getattr(ris, self._child_store_attr)

    def child_source(self, ris, child_path, create=False):
        """The per-(child, view) extractor for `child_path`, or None. With
        `create=True` it is MATERIALISED (hidden) if absent — so a COE /
        stats read of an ACTIVE-but-not-displayed child still hits a real
        proxy carrying that child's array."""
        if not child_path:
            return None
        store = self._child_store(ris)
        ext = store.get(child_path)
        if ext is None and create:
            ext = self._create_child_extractor(ris, child_path)
            if ext is not None:
                store[child_path] = ext
        return ext

    def visible_child_source(self, ris):
        """The child extractor currently SHOWN (Visibility=1) in this view —
        the single visible one for an exclusive (one-at-a-time) frame."""
        view = ris.scene.pv_view
        store = self._child_store(ris)
        if view is None or not store:
            return None
        try:
            from paraview import simple as pvsimple
        except Exception:
            return None
        for ext in store.values():
            try:
                d = pvsimple.GetDisplayProperties(ext, view=view)
                if d is not None and getattr(d, "Visibility", 0):
                    return ext
            except Exception:
                pass
        return None

    def visible_child_displays(self, ris):
        """Display proxies for every SHOWN child extractor — the SolidColor
        fan-out targets these (the frame's primary stays hidden)."""
        view = ris.scene.pv_view
        store = self._child_store(ris)
        if view is None or not store:
            return []
        try:
            from paraview import simple as pvsimple
        except Exception:
            return []
        out = []
        for ext in store.values():
            try:
                d = pvsimple.GetDisplayProperties(ext, view=view)
                if d is not None and getattr(d, "Visibility", 0):
                    out.append(d)
            except Exception:
                pass
        return out

    def _child_tint(self, ris, child_path, state):
        """SolidColor for a freshly-built child. Default = the frame's
        uniform colour; MarkerFrameRep overrides for per-marker colour."""
        return (state.solid_color_by_rep or {}).get(ris.rep_path)

    def _apply_child_z(self, ris, disp, source, zs):
        """Apply the global Z exaggeration to a child's display. Default
        (CHANNELS = real log-tube geometry following the well): scale Z.
        MarkerFrameRep overrides — markers TRANSLATE Z instead, so a sphere
        stays a sphere (not an olive)."""
        disp.Scale = [1.0, 1.0, zs]

    def _create_child_extractor(self, ris, child_path):
        """Build a per-(child, view) EnergisticsExtractor pointed at a single
        child partition (ExtractPath = the child leaf) so only that child's
        geometry + array surfaces. Clone-rooted, hidden in other views,
        representation + z-scale + tint applied. Returns None when the scene
        has no real clone (Phase 2 fallback) or the plugin proxy can't be
        built. The caller does the Show in the owning view."""
        scene = ris.scene
        clone = getattr(scene, "clone", None)
        if clone is None:
            return None
        collector = getattr(scene, "collector", None)
        if collector is not None and clone is collector.get_source():
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
            reg_name = f"{self._reg_prefix}_{_sanitize(child_path)}_v{scene.view_id}"
            ext = _create_plugin_filter_proxy(
                proxy_class="EnergisticsExtractor",
                registration_name=reg_name,
                inputs={"Input": clone},
            )
            if ext is None:
                print(f"{tag} EnergisticsExtractor not creatable — plugin missing?")
                return None
            vtkSMPropertyHelper(ext.SMProxy, "ExtractPath").Set(child_path)
            ext.SMProxy.UpdateVTKObjects()
            ext.UpdatePipelineInformation()
            target_view = scene.pv_view
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
                    self._apply_child_z(ris, disp, ext, ris._current_z_scale())
                    _apply_default_tint(disp, self._child_tint(ris, child_path, state))
            return ext
        except Exception as exc:
            print(f"{tag} create child extractor {child_path}: {exc}")
            return None


class ChannelFrameRep(FrameRep):
    """WellboreFrame of logs — ONE log shown at a time. Each channel owns its
    own per-(channel, view) EnergisticsExtractor (exclusive show); children
    are PropertyLeaf (colourable, array bucket). The source PERSISTS once
    created (hidden when a sibling is shown) so its scoped LUT / COE / stats
    read directly with no retarget."""

    KINDS = ("Frame",)
    _child_store_attr = "_channel_extractors"
    _reg_prefix = "chn"

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.ONE_AT_A_TIME

    def set_child_visible(self, ris, channel_path, visible):
        """EXCLUSIVE: showing channel B materialises its extractor and HIDES
        every OTHER channel of this frame first (one log at a time)."""
        if not channel_path:
            return
        view = ris.scene.pv_view
        try:
            from paraview import simple as pvsimple
        except Exception:
            return
        store = self._child_store(ris)
        tag = f"[ChannelFrameRep {ris.scene.view_id}/{ris.rep_path}]"
        if visible:
            ext = self.child_source(ris, channel_path, create=True)
            if ext is None:
                return
            if view is not None:
                # Exclusive: hide every OTHER channel of this frame first.
                for cp, other in store.items():
                    if cp != channel_path and other is not None:
                        try:
                            pvsimple.Hide(proxy=other, view=view)
                        except Exception:
                            pass
                try:
                    pvsimple.Show(proxy=ext, view=view)
                except Exception as exc:
                    print(f"{tag} channel show {channel_path}: {exc}")
        else:
            ext = store.get(channel_path)
            if ext is not None and view is not None:
                try:
                    pvsimple.Hide(proxy=ext, view=view)
                except Exception as exc:
                    print(f"{tag} channel hide {channel_path}: {exc}")

    def rendered_sources(self, ris):
        """The frame renders only the VISIBLE channel's own extractor (the
        primary stays hidden; the chain is N/A for logs)."""
        ch = self.visible_child_source(ris)
        return [ch] if ch is not None else []

    def color_sources(self, ris):
        ch = self.visible_child_source(ris)
        return [ch] if ch is not None else []

    def array_candidate_source(self, ris, array_path):
        """A channel's array lives on the CHANNEL's OWN extractor
        (materialised hidden so the COE resolves it even when not displayed),
        NOT the frame's primary. `array_path` is the channel leaf."""
        return self.child_source(ris, array_path, create=True)


class MarkerFrameRep(FrameRep):
    """WellboreMarkerFrame — N markers shown at once. Each marker owns its own
    per-(marker, view) extractor; children are MarkerLeaf (visibility-only),
    each independently recolourable."""

    KINDS = ("MarkerFrame",)
    _child_store_attr = "_marker_extractors"
    _reg_prefix = "mrk"

    def visibility_policy(self) -> VisibilityPolicy:
        return VisibilityPolicy.MULTI

    def set_child_visible(self, ris, marker_path, visible):
        """MULTI: show/hide one marker WITHOUT touching its siblings."""
        if not marker_path:
            return
        view = ris.scene.pv_view
        store = self._child_store(ris)
        ext = store.get(marker_path)
        tag = f"[MarkerFrameRep {ris.scene.view_id}/{ris.rep_path}]"
        try:
            from paraview import simple as pvsimple
        except Exception:
            return
        if visible:
            if ext is None:
                ext = self._create_child_extractor(ris, marker_path)
                if ext is None:
                    return
                store[marker_path] = ext
            if view is not None:
                try:
                    pvsimple.Show(proxy=ext, view=view)
                except Exception as exc:
                    print(f"{tag} marker show {marker_path}: {exc}")
        else:
            if ext is not None and view is not None:
                try:
                    pvsimple.Hide(proxy=ext, view=view)
                except Exception as exc:
                    print(f"{tag} marker hide {marker_path}: {exc}")

    def _child_tint(self, ris, marker_path, state):
        """PER-marker colour first (so a marker shown later keeps its own
        colour), falling back to the frame's uniform default."""
        by_marker = state.solid_color_by_marker or {}
        return (
            by_marker.get(marker_path)
            or (state.solid_color_by_rep or {}).get(ris.rep_path)
        )

    def _apply_child_z(self, ris, disp, source, zs):
        """Markers TRANSLATE Z (keep the sphere round) rather than scale it."""
        from fespp_on_trame.app.core.engine import marker_dispatch
        marker_dispatch.apply_marker_z(disp, source, zs)

    def set_child_color(self, ris, marker_path, color_hex):
        """SolidColor tint on ONE shown marker's display (never a ColorArray).
        No-op when that marker isn't shown — the persisted
        `solid_color_by_marker` entry covers the deferred case."""
        view = ris.scene.pv_view
        ext = self._child_store(ris).get(marker_path)
        if view is None or ext is None:
            return
        try:
            from paraview import simple as pvsimple
            from fespp_on_trame.app.core.sources.representation import _apply_default_tint
            d = pvsimple.GetDisplayProperties(ext, view=view)
            if d is not None and getattr(d, "Visibility", 0):
                _apply_default_tint(d, color_hex)
        except Exception as exc:
            print(f"[MarkerFrameRep {ris.scene.view_id}/{ris.rep_path}]"
                  f" set_marker_color {marker_path}: {exc}")
