"""Camera helpers shared across the views.

`reset_camera_centered` frames the data AND pins the view's
`CenterOfRotation` to the framed focal point. vtk.js's interactor orbits
around the server view's `CenterOfRotation`; RESQML geometry lives at UTM
coordinates far from the origin, so the default (0, 0, 0) pivot swings the
data straight out of the frustum on the first rotate, and the view looks
empty until the next reset. Pinning the pivot to the reset focal point
keeps rotation orbiting the data itself.
"""
import math

from paraview import simple as pvsimple

# The view properties a saved camera is made of, the pivot included: vtk.js
# orbits around CenterOfRotation, not around the focal point, and a reset
# moves it, so a camera put back without its pivot turns around wherever the
# last reset left it. Every place that saves a camera to put it back later
# reads this one tuple.
CAMERA_PROPERTIES = ("CameraPosition", "CameraFocalPoint", "CameraViewUp",
                     "CameraViewAngle", "CameraParallelScale",
                     "CameraParallelProjection", "CenterOfRotation")


def copy_camera_properties(src_view, view):
    """Every property of `CAMERA_PROPERTIES` from one view onto another: a
    linked or copied camera is the same camera, the projection included."""
    for name in CAMERA_PROPERTIES:
        value = getattr(src_view, name)
        # a ParaView vector property is a sequence, not a list: copy its values
        if hasattr(value, "__len__") and not isinstance(value, str):
            value = list(value)
        setattr(view, name, value)


# The radius VTK frames when the visible bounds have no extent (every point
# at one place): vtkRenderer::ResetCamera puts 1.0 in place of the zero it
# computed. A frame that lands exactly there framed nothing.
_NO_EXTENT_RADIUS = 1.0

# A look for `reset_camera_centered`: where the camera stands seen from what
# it looks at, and the way up the screen. Level from the South looking
# North, Z up: East to the right, a well hangs down the screen.
FROM_THE_SOUTH = ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0))
# how much wider than the visible box a look frames
_LOOK_ROOM = 1.15


def framed_radius(cam):
    """The radius of the sphere the camera was last reset on: the parallel
    scale under parallel projection, else distance * sin(angle / 2)."""
    if cam.GetParallelProjection():
        return float(cam.GetParallelScale())
    return float(cam.GetDistance()) * math.sin(math.radians(cam.GetViewAngle()) / 2.0)


def reset_camera_centered(pv_view, look=None):
    """ResetCamera, then move CenterOfRotation onto the new focal point.
    No-op-safe: a missing view or a proxy without the properties is
    swallowed so callers can stay terse.

    `look` (FROM_THE_SOUTH) turns the camera before it frames; without it
    the camera keeps the direction it had.

    Returns True when the view was framed on something with an extent.
    Visible objects whose points all sit at ONE place (a grid a store served
    with zero coordinates: Volve_SGrid from ADME, 13/10) make VTK frame a
    one-metre sphere around that point: the camera then sits a few metres
    from a point ten kilometres from the data, and what is ticked next is
    out of sight ("il resélectionne la grille qui fonctionne et il ne la
    voit plus", the PO's manager). Such a frame is refused: the camera is
    put back where it was and False is returned, so the caller does not
    count the view as framed. So is a frame on NOTHING: with no visible
    object VTK frames a default box at the origin, kilometres from where the
    reader's camera stood."""
    if pv_view is None:
        return False
    try:
        # Realise the representations FIRST: ResetCamera frames the
        # delivered geometry bounds, and on a never-rendered view they are
        # still empty — the reset then keeps the default origin camera and
        # UTM-coordinate data stays out of the frustum.
        pvsimple.Render(view=pv_view)
    except Exception:
        pass
    before = {}
    try:
        before = {name: list(getattr(pv_view, name)) if isinstance(getattr(pv_view, name), (list, tuple))
                  else getattr(pv_view, name) for name in CAMERA_PROPERTIES}
    except Exception as exc:
        print("[fespp] camera: could not read the camera to keep it:", exc, flush=True)
        before = {}
    shown = None
    try:
        from vtkmodules.vtkCommonCore import vtkMath
        shown = list(pv_view.GetRenderer().ComputeVisiblePropBounds())
        if not vtkMath.AreBoundsInitialized(shown):
            return False
    except Exception as exc:
        print("[fespp] camera: the visible bounds not read:", exc, flush=True)
    if look is not None:
        try:
            # on the VTK camera: the reset below keeps its direction and
            # hands the result back to the proxy's properties
            cam = pv_view.GetActiveCamera()
            fp, pos = list(cam.GetFocalPoint()), list(cam.GetPosition())
            far = math.dist(fp, pos) or 1.0
            cam.SetPosition(*[fp[i] + look[0][i] * far for i in range(3)])
            cam.SetViewUp(*look[1])
        except Exception as exc:
            print("[fespp] camera: could not turn the camera before framing:", exc, flush=True)
    try:
        if look is not None and shown is not None:
            # some room around: a well's pictogram and name stand above its
            # head, and a tight frame cuts them at the edge of the view
            mid = [(shown[2 * i] + shown[2 * i + 1]) / 2.0 for i in range(3)]
            half = [(shown[2 * i + 1] - shown[2 * i]) / 2.0 * _LOOK_ROOM for i in range(3)]
            pv_view.ResetCamera([mid[i // 2] + (half[i // 2] if i % 2 else -half[i // 2])
                                 for i in range(6)])
        else:
            pv_view.ResetCamera()
    except Exception:
        return False
    cam = None
    try:
        cam = pv_view.GetActiveCamera()
        if cam is not None and abs(framed_radius(cam) - _NO_EXTENT_RADIUS) < 1e-6:
            for name, value in before.items():
                try:
                    setattr(pv_view, name, value)
                except Exception as exc:
                    print("[fespp] camera: could not put back", name, ":", exc, flush=True)
            print("[fespp] camera: nothing to frame, the visible objects have no extent"
                  " (every point at one place); the camera is kept where it was", flush=True)
            return False
    except Exception as exc:
        print("[fespp] camera extent check error:", exc, flush=True)
    try:
        # the VTK camera itself, not the proxy's CameraFocalPoint: that
        # property is only refreshed by a synchronisation the reset does
        # not always run, and read stale it is (0, 0, 0) — the pivot would
        # sit at the origin while the camera frames the data, and the first
        # drag in the browser would swing the data far out of the frustum
        focal = list(cam.GetFocalPoint()) if cam is not None else list(pv_view.CameraFocalPoint)
        pv_view.CenterOfRotation = focal
    except Exception as exc:
        print("[fespp] camera pivot error:", exc, flush=True)
    return True


def follow_z_scale(pv_view, ratio):
    """Keep the view on the data when the Z exaggeration changes by `ratio`
    (new over old). The exaggeration is the representations' Scale
    [1, 1, z] about the origin: the point the camera looked at, at Z,
    is drawn at Z * ratio afterwards. Left alone, the camera would keep
    looking at the old depth and orbiting the old pivot — the scene slides
    out of the frame and turns around a point no longer in the data. So the
    camera is TRANSLATED along Z by what its focal point moved — its
    direction and its distance are the reader's, they stay — and the pivot
    moves the same way. Returns True when the camera moved.

    Read from the VTK camera, not the proxy: CameraFocalPoint is refreshed
    only by a synchronisation that does not always run (see
    reset_camera_centered)."""
    if pv_view is None:
        return False
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        return False
    if ratio <= 0 or abs(ratio - 1.0) < 1e-12:
        return False
    cam = pv_view.GetActiveCamera()
    focal = list(cam.GetFocalPoint()) if cam is not None else list(pv_view.CameraFocalPoint)
    pos = list(cam.GetPosition()) if cam is not None else list(pv_view.CameraPosition)
    dz = focal[2] * (ratio - 1.0)
    pv_view.CameraFocalPoint = [focal[0], focal[1], focal[2] + dz]
    pv_view.CameraPosition = [pos[0], pos[1], pos[2] + dz]
    pivot = list(pv_view.CenterOfRotation)
    pv_view.CenterOfRotation = [pivot[0], pivot[1], pivot[2] * ratio]
    return True


def render(pv_view):
    """Convenience: render a view, swallowing errors."""
    if pv_view is None:
        return
    try:
        pvsimple.Render(view=pv_view)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The wall the wheel stops at
# ---------------------------------------------------------------------------
# The wheel dollies the eye toward the focal point without ever asking what
# is in the way: a few notches too many and the camera is INSIDE the grid,
# then out the other side, and the view is a blank frame with no clue how to
# get back (a zoom out from there walks back through the geometry, so the
# gesture that got you lost is the one that has to save you). The wheel
# stops at the face of the box the visible data occupies, padded a little so
# it stops BEFORE the surface rather than on it.
#
# The step is REFUSED, not corrected: the position the camera had before the
# notch is put back. Snapping the eye onto the face instead would move it in
# a gesture that was meant to be blocked, and from inside the box — where a
# reset or a growing dataset can legitimately leave it — it would teleport.
# A camera already inside is left alone: the wall keeps you from crossing,
# it does not throw you out.
#
# What the view says when it refuses a notch. The title bar's zoom buttons
# stop at the same wall as the wheel and read from the same line: two
# controls for one gesture must not disagree about where the data begins.
#
# Globe views only (14/10): on the Earth the data is a thin skin one flies
# over, and crossing it loses the viewer. In a plain 3D view the camera must
# be able to ENTER a grid (to look at a layer from inside, to follow a well),
# so the wall lets every notch through there.
WALL_NOTE = ("Zoom stopped at the edge of the data — the next notch would"
             " have put the camera inside it.")
MARGIN_RATIO = 0.02   # of the box diagonal


def visible_box(pv_view, margin_ratio=MARGIN_RATIO, data_only=False):
    """The padded box the view's visible geometry occupies, as (lo, hi), or
    None when nothing is drawn (or the view cannot be read).

    TWO ROADS, one per scene, because only one of them is right in each.

    A plain 3D view asks the RENDERER (`ComputeVisiblePropBounds`): it is the
    world box, transforms and Z exaggeration included, and everything in the
    room is data.

    A Globe view cannot: the Earth is in that room, and its box is a cube
    twelve thousand kilometres across, INSIDE WHICH THE CAMERA ALWAYS ALREADY
    IS — a wall built on it would never fire, and one could fly straight
    through the grid. It asks the REPRESENTATIONS instead, skipping the ones
    the scene marks `Pickable = 0`, which is the line globe_scene.py draws
    between the data and the planet it is painted on (the Earth and the
    wellhead marks are both unpickable on purpose). Their data information is
    what ParaView frames a camera on, and on a Globe scene it is the world
    box as well: the radial exaggeration lives inside the projection there,
    never in `rep.Scale` (globe_scene.py).

    Why not ask the props one by one in both cases: in this application every
    `vtkPVLODActor` reports VTK's empty bounds (`[1, -1, ...]`) — the actors
    are not where the geometry's extent can be read.
    """
    if pv_view is None:
        return None
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = 0
    try:
        if data_only:
            for rep in (pv_view.Representations or []):
                # ASKED THROUGH GetProperty, never attribute access. A view
                # carries more than geometry — scalar bars, text labels —
                # and reading `rep.Input` on one of those RAISES, which the
                # silent-handler gate reports and rightly: a walk that has to
                # be wrapped in a try is a walk that does not know what it is
                # walking over. A property that is absent comes back None.
                vis = rep.GetProperty("Visibility")
                inp = rep.GetProperty("Input")
                if vis is None or inp is None:
                    continue   # not a geometry representation
                if not int(vis.GetElement(0)):
                    continue
                pick = rep.GetProperty("Pickable")
                if pick is not None and not int(pick.GetElement(0)):
                    continue   # the Earth, the wellhead marks: the room
                src = inp.GetProxy(0)
                if src is None:
                    continue
                # the INPUT's data information: a representation proxy has no
                # GetDataInformation of its own, and its
                # GetRepresentedDataInformation comes back empty here.
                b = src.GetDataInformation().GetBounds()
                if b is None or len(b) < 6 or b[0] > b[1]:
                    continue
                for i in range(3):
                    lo[i] = min(lo[i], b[2 * i])
                    hi[i] = max(hi[i], b[2 * i + 1])
                seen += 1
        else:
            b = pv_view.GetClientSideObject().GetRenderer().ComputeVisiblePropBounds()
            if b is not None and len(b) >= 6 and b[0] <= b[1]:
                lo = [b[0], b[2], b[4]]
                hi = [b[1], b[3], b[5]]
                seen = 1
    except Exception as exc:
        print("[fespp] visible bounds:", exc, flush=True)
        return None
    if not seen:
        return None            # a room with nothing in it: no wall to build
    diag = sum((hi[i] - lo[i]) ** 2 for i in range(3)) ** 0.5
    if diag <= 0:
        return None            # a single point has no inside
    pad = margin_ratio * diag
    return ([v - pad for v in lo], [v + pad for v in hi])


def view_ray(pv_view, x, y):
    """The world-space ray through display pixel (x, y), as (origin,
    direction), or None when the camera cannot be read. Origin bottom-left,
    VTK's own convention.

    Unprojected from the CAMERA alone: the same pixel at the near and at the
    far plane, two matrix multiplies each. It reads no depth buffer, runs no
    pick and draws nothing, so it cannot hang and it cannot go stale —
    which is exactly why the crosshair on a Globe view is built on it.

    The two other roads do not work. ParaView's
    `ConvertDisplayToPointOnSurface` reads as a ray cast but runs a hardware
    surface SELECTION, and on a Globe scene it NEVER RETURNS, on the GPU and
    in software alike. And the depth buffer, read back outside a render, is
    neither current (its clipping range belongs to an older frame) nor
    precise: at local-CRS ranges the whole scene is crushed against the far
    plane.
    """
    if pv_view is None:
        return None
    try:
        renderer = pv_view.GetClientSideObject().GetRenderer()
        ends = []
        for depth in (0.0, 1.0):
            renderer.SetDisplayPoint(float(x), float(y), depth)
            renderer.DisplayToWorld()
            w = list(renderer.GetWorldPoint())
            if len(w) < 4 or abs(w[3]) < 1e-30:
                return None
            ends.append([w[k] / w[3] for k in range(3)])
    except Exception as exc:
        print("[fespp] view ray:", exc, flush=True)
        return None
    near, far = ends
    return near, [far[k] - near[k] for k in range(3)]


def point_is_inside(box, point):
    """Is `point` inside `box`? The one question the wall asks."""
    if box is None or point is None:
        return False
    lo, hi = box
    return all(lo[i] <= point[i] <= hi[i] for i in range(3))


def eye_is_inside(pv_view, box):
    """Is the camera position inside `box`?"""
    if box is None:
        return False
    try:
        pos = list(pv_view.GetActiveCamera().GetPosition())
    except Exception as exc:
        print("[fespp] camera position:", exc, flush=True)
        return False
    return point_is_inside(box, pos)


class WheelWall:
    """Refuses the wheel notch that would take the eye inside the data.

    Two observers on ONE interactor, on either side of the interactor
    style's own handler: `before` (priority above the style) remembers where
    the camera was and whether it was already inside, `after` (priority
    below it) puts that position back when the notch crossed in. The style
    is not reimplemented — how far a notch dollies stays VTK's business, and
    only the result is judged.

    It holds on the Earth too. There the renderer's visible box is the
    planet, a cube twelve thousand kilometres across that the camera is
    always already inside, so a wall built on it would never stop anything.
    On a Globe view the box is taken from the DATA's own representations
    instead, the ones the scene has not marked
    unpickable (the Earth and the wellhead marks are). A Globe view carrying
    nothing but the Earth has no box and therefore no wall, which is right:
    there is nothing to fly through.
    """

    def __init__(self, view_id, pv_view, state):
        self.vid = str(view_id or "")
        self.pv_view = pv_view
        self.state = state
        self._prev = None
        self._was_inside = False

    def _globe(self):
        """The wall holds on Globe views only (module note)."""
        return bool(getattr(self.state, f"ui_globe_mode__{self.vid}", False))

    def _box(self):
        """A Globe view's box is the DATA's, not the room's (visible_box)."""
        return visible_box(
            self.pv_view,
            data_only=bool(getattr(self.state, f"ui_globe_mode__{self.vid}", False)))

    @property
    def _note_key(self):
        return f"ui_zoom_note__{self.vid}"

    def _say(self, note):
        try:
            # getattr, not state[...]: the wall is hung on the view before
            # per_view_state declares the key, and a KeyError on every notch
            # would be the only thing this ever said
            if getattr(self.state, self._note_key, None) == note:
                return
            self.state[self._note_key] = note
            self.state.flush()
        except Exception as exc:
            print(f"[fespp] zoom wall note ({self.vid}):", exc, flush=True)

    def before(self, *_):
        """Remember where the camera is, and whether it is already inside."""
        if not self._globe():
            self._prev = None      # a plain 3D view: every notch goes through
            return
        try:
            self._prev = list(self.pv_view.GetActiveCamera().GetPosition())
        except Exception as exc:
            print(f"[fespp] zoom wall ({self.vid}):", exc, flush=True)
            self._prev = None
            return
        self._was_inside = eye_is_inside(self.pv_view, self._box())

    def after(self, *_):
        """Put the camera back where it was when the notch crossed in."""
        if self._prev is None:
            return
        if self._was_inside:
            self._say("")      # already in: the wall is not a door back out
            return
        if not eye_is_inside(self.pv_view, self._box()):
            self._say("")
            return
        try:
            # through the PROXY, not the vtkCamera: the proxy property is
            # what the rest of the application reads (nav_zoom_step, the
            # camera link), and setting it pushes the value down to the
            # camera as well — setting only the camera would leave the two
            # disagreeing about where the eye is.
            self.pv_view.CameraPosition = list(self._prev)
        except Exception as exc:
            print(f"[fespp] zoom wall ({self.vid}):", exc, flush=True)
            return
        render(self.pv_view)   # the style already drew the refused frame
        self._say(WALL_NOTE)

    def stepped_out(self, *_):
        """A notch the OTHER way is one the wall has no reason to refuse, so
        the refusal it printed leaves with it. Without this the line would
        sit on the view until the next notch inwards — which is the one
        gesture someone who has just been refused is not about to make."""
        self._say("")


def install_wheel_wall(view_id, pv_view, state):
    """Hang a WheelWall on `pv_view`'s interactor. Returns it (the caller
    keeps it alive: VTK holds no reference to a Python callable)."""
    if pv_view is None:
        return None
    try:
        interactor = pv_view.GetClientSideObject().GetInteractor()
    except Exception as exc:
        print(f"[fespp] zoom wall ({view_id}):", exc, flush=True)
        return None
    if interactor is None:
        print(f"[fespp] zoom wall ({view_id}): no interactor — the wheel"
              " zooms without a wall", flush=True)
        return None
    wall = WheelWall(view_id, pv_view, state)
    try:
        # 1.0 runs before the style's own handler, -1.0 after it: VTK walks
        # its observers by DECREASING priority, so this brackets the dolly
        # without touching the style.
        interactor.AddObserver("MouseWheelForwardEvent", wall.before, 1.0)
        interactor.AddObserver("MouseWheelForwardEvent", wall.after, -1.0)
        interactor.AddObserver("MouseWheelBackwardEvent", wall.stepped_out, -1.0)
    except Exception as exc:
        print(f"[fespp] zoom wall ({view_id}):", exc, flush=True)
        return None
    return wall


# ---------------------------------------------------------------- the hands on a camera
_GESTURE_EVENTS = ("LeftButtonPressEvent", "MiddleButtonPressEvent", "RightButtonPressEvent")
_RELEASE_EVENTS = ("LeftButtonReleaseEvent", "MiddleButtonReleaseEvent", "RightButtonReleaseEvent")
_WHEEL_EVENTS = ("MouseWheelForwardEvent", "MouseWheelBackwardEvent")


class CameraActivity:
    """When someone last had a hand on a camera, in ANY view. The work the
    server can put off (the background read of a lazy ETP load) waits until
    the hands are off: the views are rendered on this same loop, so a read
    while a camera turns freezes the frames (the PO, 14/10, a grid turning
    by jerks during the 20 s of the background read).

    Fed by observers on each view's interactor (install_activity_watch): the
    web protocol hands the browser's presses, releases and wheel notches to
    the interactor as VTK events. A press whose release never came (the
    mouse let go outside the page) counts for STALE seconds at most."""

    STALE = 10.0

    def __init__(self, clock=None):
        import time as _time
        self._clock = clock or _time.monotonic
        self._pressed = False
        self._last = None

    def press(self, *_):
        self._pressed = True
        self._last = self._clock()

    def release(self, *_):
        self._pressed = False
        self._last = self._clock()

    def touch(self, *_):
        self._last = self._clock()

    def moving(self, *_):
        if self._pressed:
            self._last = self._clock()

    def touched_since(self, t):
        """A press, a release, a drag or a wheel notch AFTER `t` (a reading
        of the same clock): what stops a camera flight. A button already
        held at `t` does not count by itself: the right-click that opened
        the menu the flight came from may never have sent its release."""
        return self._last is not None and self._last > t

    def quiet(self, seconds=1.5):
        """True when no camera was touched in the last `seconds` and no button
        is held (or held for longer than STALE without a sign)."""
        if self._last is None:
            return True
        idle = self._clock() - self._last
        if self._pressed and idle < self.STALE:
            return False
        return idle >= seconds


ACTIVITY = CameraActivity()


class CameraFlights:
    """The views whose camera travels to a target ("Centre / Zoom the 3D
    view on", app/features/navigation): their frames are a move's, as a
    drag's are, and what a view lays again for a camera at rest (the log
    graphs facing the screen) waits for the landing frame."""

    def __init__(self):
        self._on = set()

    def take_off(self, vid):
        self._on.add(str(vid))

    def land(self, vid):
        self._on.discard(str(vid))

    def flying(self, vid):
        return str(vid) in self._on


FLIGHTS = CameraFlights()


def flight_frame(drawn, frames, elapsed, seconds):
    """The frame a camera flight of `frames` frames over `seconds` draws
    next, `drawn` being the last one drawn and `elapsed` the time since it
    took off: the one the clock is at, and never one drawn already. A frame
    slower than its share skips the frames it overran: the flight lands on
    time instead of lasting as many frames as it has."""
    if seconds <= 0:
        return frames
    return min(frames, max(drawn + 1, int(elapsed / seconds * frames)))


def install_activity_watch(view_id, pv_view, activity=None):
    """Feed `activity` (the module's ACTIVITY) from `pv_view`'s interactor.
    Returns the callables (the caller keeps them alive: VTK holds no
    reference to a Python callable), or None."""
    activity = activity or ACTIVITY
    if pv_view is None:
        return None
    try:
        interactor = pv_view.GetClientSideObject().GetInteractor()
    except Exception as exc:
        print(f"[fespp] camera watch ({view_id}):", exc, flush=True)
        return None
    if interactor is None:
        return None
    kept = [activity.press, activity.release, activity.touch, activity.moving]
    try:
        for name in _GESTURE_EVENTS:
            interactor.AddObserver(name, activity.press, 2.0)
        for name in _RELEASE_EVENTS:
            interactor.AddObserver(name, activity.release, 2.0)
        for name in _WHEEL_EVENTS:
            interactor.AddObserver(name, activity.touch, 2.0)
        interactor.AddObserver("MouseMoveEvent", activity.moving, 2.0)
    except Exception as exc:
        print(f"[fespp] camera watch ({view_id}):", exc, flush=True)
        return None
    return kept
