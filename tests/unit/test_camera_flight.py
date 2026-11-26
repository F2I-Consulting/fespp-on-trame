"""app/views/camera: a camera flight ("Center / Zoom the 3D view on") lands on time whatever its frames cost,
and the views flying are known (their log graphs keep their lay until the landing, as during a drag)."""
from fespp_on_trame.app.views import camera
from fespp_on_trame.engine import log_track

FRAMES, SECONDS = 15, 0.6


def test_a_flight_whose_frames_are_quick_draws_every_frame():
    drawn, seen = 0, []
    while drawn < FRAMES:
        # each frame drawn at its time
        drawn = camera.flight_frame(drawn, FRAMES, drawn * SECONDS / FRAMES, SECONDS)
        seen.append(drawn)
    assert seen == list(range(1, FRAMES + 1))


def test_a_flight_whose_frames_are_slow_skips_the_ones_they_overran():
    # a frame costs 0.25 s: the flight lands after 3 of them, not after 15
    drawn, clock, seen = 0, 0.0, []
    while drawn < FRAMES:
        drawn = camera.flight_frame(drawn, FRAMES, clock, SECONDS)
        seen.append(drawn)
        clock += 0.25
    assert seen[-1] == FRAMES and len(seen) <= 4
    assert seen == sorted(set(seen))


def test_a_flight_never_draws_a_frame_again_nor_past_its_last():
    assert camera.flight_frame(5, FRAMES, 0.0, SECONDS) == 6
    assert camera.flight_frame(5, FRAMES, 99.0, SECONDS) == FRAMES
    assert camera.flight_frame(0, FRAMES, 0.0, 0.0) == FRAMES


def test_the_views_flying_are_known_until_they_land():
    flights = camera.CameraFlights()
    flights.take_off("view_1")
    assert flights.flying("view_1") and not flights.flying("view_2")
    flights.land("view_1")
    flights.land("view_1")
    assert not flights.flying("view_1")


def test_the_log_graphs_keep_their_lay_while_the_camera_flies():
    # the graphs face the screen, the camera turned: laid again at rest, kept in a move (drag or flight)
    laid, screen = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
    assert log_track.faces_again(True, laid, screen, False)
    assert not log_track.faces_again(True, laid, screen, True)


def test_a_frame_of_a_move_keeps_the_lay_of_the_graphs_facing_the_screen():
    # what the view settles its logs with at each flush: during a drag or a flight, the lay they have
    laid, now = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
    assert log_track.lay_screen(now, laid, moving=True) == laid
    # at rest (the landing, the release): the camera's now, laid again once
    assert log_track.lay_screen(now, laid, moving=False) == now
    # never laid yet: the camera's now even in a move; no camera frame: the lay kept
    assert log_track.lay_screen(now, None, moving=True) == now
    assert log_track.lay_screen(None, laid, moving=False) == laid
