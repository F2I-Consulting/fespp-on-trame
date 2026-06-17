"""Global wellbore-marker display options — orientation + size.

FESPP exposes two GLOBAL properties on the EPC collector
(`Energistics.xml`): `MarkerOrientation` (show the marker as an oriented
DISK — by its RESQML dip angle + dip direction — vs a plain SPHERE) and
`MarkerSize` (the disk/sphere radius). They apply to EVERY marker.

The marker GEOMETRY is built by the collector and cloned per-view, so
changing either property re-extracts the geometry through every per-view
clone + per-marker extractor, then re-renders. Per-marker / per-view
variants would need C++ work (the clone doesn't rebuild markers).
"""
from paraview import simple as pvsimple


def marker_proxy_ids(scene_registry):
    """Global-IDs of every per-(marker, view) extractor proxy known to the
    scene registry, so a RAW ParaView representation (iterated straight off
    ``view.Representations``) can be recognised as a marker glyph and
    TRANSLATED in Z instead of scaled (a sphere/disk must not stretch).
    Returns a set of ints; empty on any failure."""
    ids = set()
    if scene_registry is None:
        return ids
    try:
        scenes = list(scene_registry.all_scenes())
    except Exception:
        return ids
    for scene in scenes:
        try:
            reps = list(scene.reps())
        except Exception:
            continue
        for _path, ris in reps:
            store = getattr(ris, "_marker_extractors", None)
            if not store:
                continue
            for ext in store.values():
                if ext is None:
                    continue
                try:
                    ids.add(ext.SMProxy.GetGlobalID())
                except Exception:
                    pass
    return ids


def is_marker_proxy(proxy):
    """True when `proxy` is a per-(marker, view) extractor — recognised by
    its ``mrk_`` registration-name prefix. Scene-registry-free, so the
    z-scale fan-out can translate markers (round) instead of scaling them
    wherever they surface (scene proxies OR legacy)."""
    if proxy is None:
        return False
    try:
        from paraview import servermanager as _sm
        pm = _sm.ProxyManager()
        smp = getattr(proxy, "SMProxy", proxy)
        for group in ("filters", "sources"):
            n = pm.GetProxyName(group, smp)
            if n and n.startswith("mrk_"):
                return True
    except Exception:
        pass
    return False


def apply_marker_z(disp, source, zs):
    """Place a marker glyph (sphere / oriented disk) at its Z-SCALED depth
    WITHOUT stretching its shape.

    A marker is SYMBOLIC geometry, not the real subsurface — scaling its
    display's Z (``disp.Scale = [1, 1, zs]``, as every other rep does) turns
    a sphere into an ellipsoid. Instead we TRANSLATE Z by ``(zs-1)*z_center``
    so the marker lands at the same depth as the z-scaled scene while keeping
    its shape; X/Y are left untouched (scaling them would misplace it).

    `source` is the marker's per-marker extractor — its UNSCALED output
    bounds give the marker's z centre (the display Position/Scale don't bake
    into the geometry, so re-reading is stable across z-scale changes)."""
    if disp is None:
        return
    try:
        z_center = 0.0
        if source is not None and zs != 1.0:
            try:
                source.UpdatePipeline()
                b = source.GetDataInformation().GetBounds()
                if b is not None and b[4] <= b[5]:
                    z_center = 0.5 * (b[4] + b[5])
            except Exception:
                z_center = 0.0
        # Save / restore the solid tint — a transform write can reset the
        # rep's coloring on some PV builds (markers carry a SolidColor).
        saved = {}
        for attr in ("DiffuseColor", "AmbientColor", "ColorArrayName",
                     "LookupTable", "Opacity"):
            try:
                saved[attr] = getattr(disp, attr)
            except Exception:
                pass
        disp.Scale = [1.0, 1.0, 1.0]
        # ParaView 5.13+ renamed the display "Position" property to
        # "Translation" (reading/writing the old name raises a
        # NotSupportedException — even hasattr() on it propagates). Try the
        # modern name first, fall back to the legacy one for older builds.
        translate = [0.0, 0.0, (zs - 1.0) * z_center]
        for attr_name in ("Translation", "Position"):
            try:
                setattr(disp, attr_name, translate)
                break
            except Exception:
                continue
        for attr, val in saved.items():
            try:
                if getattr(disp, attr) != val:
                    setattr(disp, attr, val)
            except Exception:
                pass
    except Exception:
        pass


def apply_marker_options(collector, scene_registry, controller, orientation, size):
    """Set the global marker orientation (bool) + size (int radius) on the
    collector, re-extract every marker across all views, then render AND
    PUSH every view so each browser shows the new geometry immediately.

    Heavy: setting MarkerSize/MarkerOrientation + UpdatePipeline re-runs the
    collector's RequestData over the WHOLE cumulative selection (each marker
    node hits `changeOrientationAndSize`). Call this on a slider RELEASE,
    not on every step."""
    src = collector.get_source() if collector is not None else None
    if src is None:
        return
    try:
        src.SetPropertyWithName("MarkerOrientation", 1 if orientation else 0)
        src.SetPropertyWithName("MarkerSize", int(size))
        src.UpdatePipelineInformation()
        src.UpdatePipeline()
    except Exception as exc:
        return

    scenes = []
    if scene_registry is not None:
        try:
            scenes = list(scene_registry.all_scenes())
        except Exception:
            scenes = []

    # Propagate the rebuilt geometry: re-clone, then re-extract every shown
    # marker, in every view; then render that view server-side.
    for scene in scenes:
        clone = getattr(scene, "clone", None)
        if clone is not None:
            try:
                clone.UpdatePipelineInformation()
                clone.UpdatePipeline()
            except Exception:
                pass
        try:
            for _rep_path, ris in scene.reps():
                if not ris._is_marker_frame():
                    continue
                for ext in ris._marker_extractors.values():
                    try:
                        ext.UpdatePipelineInformation()
                        ext.UpdatePipeline()
                    except Exception:
                        pass
        except Exception:
            pass
        pv_view = getattr(scene, "pv_view", None)
        if pv_view is not None:
            try:
                pvsimple.Render(view=pv_view)
            except Exception:
                pass

    # PUSH a fresh frame to every panel's browser (global change → all views).
    pushed = False
    update_for = getattr(controller, "view_update_for", None) if controller is not None else None
    if update_for is not None and scene_registry is not None:
        for vid in scene_registry.view_ids():
            try:
                update_for(vid)
                pushed = True
            except Exception:
                pass
    if not pushed and controller is not None:
        try:
            controller.view_update()
        except Exception:
            pass
