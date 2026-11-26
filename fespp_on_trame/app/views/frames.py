"""What the frames of a camera drag are made of, per rendering backend.

While the mouse is down trame streams JPEGs of the view; on release it sends
one at full resolution. trame's default drag frame is half the resolution
(a quarter of the pixels) at JPEG quality 60 — blurred on purpose, because a
rasteriser on the CPU pays per pixel. A GPU does not: at full resolution the
frame rate stays within the noise of the blurred one, and the frames are
sharp (tests/browser/specs/25-fluidity.spec.mjs measures both). So a
GPU-rendered view drags at full resolution and quality 90, a
software-rendered one keeps trame's quarter — and both say so once.

FESPP_INTERACTIVE_RATIO (0.25..1) and FESPP_INTERACTIVE_QUALITY (1..100)
force either on any backend — a deployment behind a thin link may prefer the
smaller frames — and a value that is not a number, or out of range, is said
and ignored, never silently applied.
"""
import os
import sys

# (ratio of the resting resolution, JPEG quality) of one drag frame
SOFTWARE = (0.5, 60)   # trame's default: a quarter of the pixels
GPU = (1.0, 90)        # all of them: the drag costs the render, not the pixels
_SAID = []
_BACKEND = []   # [kind] once the manager has read the OpenGL engine
_DRAG_SAID = []  # [True] once a drag frame's share could not be read


def remember_backend(kind):
    """Keep the backend kind the view manager read from the OpenGL engine.

    `kind` is "gpu", "software", or "" when the window would not say; only
    the first call counts, and the panels read it back via
    ``render_backend``.
    """
    if not _BACKEND:
        _BACKEND.append(kind)


def render_backend():
    """Return the backend kind the manager remembered, "" before it has
    read one."""
    return _BACKEND[0] if _BACKEND else ""


def drag_ratio(view):
    """Return the share of its resting resolution `view` (a view proxy) is
    drawn at: below 1 while trame streams the smaller frames of a drag, which
    the browser stretches back — and with them what is drawn a fixed size in
    pixels, a name or a pictogram —, 1 at rest or when trame follows no size
    for the view."""
    try:
        from trame_vtk.modules.paraview import HELPERS_PER_SERVER
        gid = view.GetGlobalIDAsString()
        for helper in HELPERS_PER_SERVER.values():
            root = getattr(helper, "_root_protocol", None)
            for link in (root.getLinkProtocols() if root is not None else ()):
                rest = ((getattr(link, "tracking_views", None) or {}).get(gid) or {}).get("originalSize")
                if rest and rest[0] > 0:
                    return max(0.05, min(1.0, float(view.ViewSize[0]) / float(rest[0])))
    except Exception as exc:
        if not _DRAG_SAID:
            _DRAG_SAID.append(True)
            print(f"[fespp] drag frames: the share of the resolution not read ({exc!r}) — what is drawn a fixed"
                  f" size in pixels shows larger while dragging", file=sys.stderr, flush=True)
    return 1.0


def in_drag(view):
    """Whether `view` (a view proxy) draws a frame of a camera drag. trame's
    mouse handler raises the view's UseInteractiveRenderingForScreenshots
    while a button is down and lowers it before the release is handled, so
    the frame at release is at rest; a GPU drags at full resolution (GPU
    above), which the frame's share of the resolution cannot tell. A frame
    smaller than the view at rest is a drag's too."""
    if int(getattr(view, "UseInteractiveRenderingForScreenshots", 0) or 0):
        return True
    return drag_ratio(view) < 1.0


def _forced(name, lo, hi, cast):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = cast(raw)
    except ValueError:
        print(f"[fespp] {name}={raw!r} is not a number — ignored",
              file=sys.stderr, flush=True)
        return None
    if not lo <= value <= hi:
        print(f"[fespp] {name}={raw} is outside {lo:g}..{hi:g} — ignored",
              file=sys.stderr, flush=True)
        return None
    return value


def interactive_frames(kind):
    """Return the (ratio, quality) of a drag frame for the backend `kind`.

    `kind` is "gpu", "software", or "" when the window would not say (then
    the safe, blurred default). The environment overrides apply on top, and
    the choice is printed once per session.
    """
    ratio, quality = GPU if kind == "gpu" else SOFTWARE
    why = "GPU" if kind == "gpu" else (
        "software rendering" if kind == "software" else "backend unknown")
    forced_ratio = _forced("FESPP_INTERACTIVE_RATIO", 0.25, 1.0, float)
    forced_quality = _forced("FESPP_INTERACTIVE_QUALITY", 1, 100, int)
    if forced_ratio is not None:
        ratio = forced_ratio
        why = "FESPP_INTERACTIVE_RATIO"
    if forced_quality is not None:
        quality = forced_quality
        why = "FESPP_INTERACTIVE_QUALITY" if forced_ratio is None else (
            "FESPP_INTERACTIVE_RATIO and FESPP_INTERACTIVE_QUALITY")
    if not _SAID:
        _SAID.append(True)
        pixels = "full resolution" if ratio >= 1.0 else f"{ratio:g} of the resolution"
        print(f"[fespp] drag frames: {pixels}, JPEG {quality} ({why})",
              file=sys.stderr, flush=True)
    return ratio, quality
