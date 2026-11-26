"""app/views/camera.follow_z_scale: the camera follows a Z exaggeration change.

The Z exaggeration scales every Z about 0, so the point the camera looks at
moves from Z to Z * ratio. The camera is translated by the move of its focal
point, keeping its direction and distance, and the pivot follows. Without
this the scene slides out of the frame and rotates about a point that is no
longer in the data."""
from fespp_on_trame.app.views import camera


class _Camera:
    def __init__(self, focal, position):
        self.focal, self.position = list(focal), list(position)

    def GetFocalPoint(self):
        return tuple(self.focal)

    def GetPosition(self):
        return tuple(self.position)


class _View:
    def __init__(self, focal, position, pivot):
        self._cam = _Camera(focal, position)
        self.CameraFocalPoint = [0.0, 0.0, 0.0]      # stale, like the proxy's
        self.CameraPosition = [0.0, 0.0, 0.0]
        self.CenterOfRotation = list(pivot)

    def GetActiveCamera(self):
        return self._cam


def test_the_camera_and_the_pivot_follow_the_data_down():
    v = _View(focal=(430000.0, 6470000.0, -2500.0),
              position=(431000.0, 6469000.0, -1000.0),
              pivot=(430000.0, 6470000.0, -2500.0))
    assert camera.follow_z_scale(v, 2.0)
    # The focal point is where the data it looked at is drawn after scaling.
    assert v.CameraFocalPoint == [430000.0, 6470000.0, -5000.0]
    # The camera moves by the same amount: same direction, same distance.
    assert v.CameraPosition == [431000.0, 6469000.0, -3500.0]
    assert v.CenterOfRotation == [430000.0, 6470000.0, -5000.0]


def test_back_to_one_undoes_it():
    v = _View(focal=(0.0, 0.0, -5000.0), position=(0.0, -100.0, -4000.0),
              pivot=(0.0, 0.0, -5000.0))
    camera.follow_z_scale(v, 0.5)
    assert v.CameraFocalPoint == [0.0, 0.0, -2500.0]
    assert v.CameraPosition == [0.0, -100.0, -1500.0]
    assert v.CenterOfRotation == [0.0, 0.0, -2500.0]


def test_nothing_moves_without_a_change():
    v = _View(focal=(1.0, 2.0, -3.0), position=(4.0, 5.0, 6.0), pivot=(1.0, 2.0, -3.0))
    assert not camera.follow_z_scale(v, 1.0)
    assert not camera.follow_z_scale(v, 0)
    assert not camera.follow_z_scale(v, "x")
    assert not camera.follow_z_scale(None, 2.0)
    assert v.CenterOfRotation == [1.0, 2.0, -3.0]
