"""What a drag frame is made of, per backend, and that nothing about it is
silent: the choice is said once, a forced value is said, a bad one is said
and ignored."""
import fespp_on_trame.app.views.frames as frames


def _fresh(monkeypatch):
    monkeypatch.setattr(frames, "_SAID", [])
    for k in ("FESPP_INTERACTIVE_RATIO", "FESPP_INTERACTIVE_QUALITY"):
        monkeypatch.delenv(k, raising=False)


def test_a_gpu_drags_sharp_and_says_so(monkeypatch, capsys):
    _fresh(monkeypatch)
    assert frames.interactive_frames("gpu") == (1.0, 90)
    assert "drag frames: full resolution, JPEG 90 (GPU)" in capsys.readouterr().err


def test_software_and_an_unknown_backend_keep_the_quarter(monkeypatch, capsys):
    _fresh(monkeypatch)
    assert frames.interactive_frames("software") == (0.5, 60)
    assert "0.5 of the resolution, JPEG 60 (software rendering)" in capsys.readouterr().err
    _fresh(monkeypatch)
    assert frames.interactive_frames("") == (0.5, 60)
    assert "(backend unknown)" in capsys.readouterr().err


def test_it_is_said_once_per_session(monkeypatch, capsys):
    _fresh(monkeypatch)
    frames.interactive_frames("gpu")
    frames.interactive_frames("gpu")
    assert capsys.readouterr().err.count("drag frames:") == 1


def test_the_environment_forces_either_number(monkeypatch, capsys):
    _fresh(monkeypatch)
    monkeypatch.setenv("FESPP_INTERACTIVE_RATIO", "0.5")
    assert frames.interactive_frames("gpu") == (0.5, 90)
    assert "(FESPP_INTERACTIVE_RATIO)" in capsys.readouterr().err
    _fresh(monkeypatch)
    monkeypatch.setenv("FESPP_INTERACTIVE_QUALITY", "75")
    assert frames.interactive_frames("software") == (0.5, 75)
    assert "(FESPP_INTERACTIVE_QUALITY)" in capsys.readouterr().err


def test_a_bad_value_is_said_and_ignored(monkeypatch, capsys):
    _fresh(monkeypatch)
    monkeypatch.setenv("FESPP_INTERACTIVE_RATIO", "big")
    monkeypatch.setenv("FESPP_INTERACTIVE_QUALITY", "400")
    assert frames.interactive_frames("gpu") == (1.0, 90)
    err = capsys.readouterr().err
    assert "FESPP_INTERACTIVE_RATIO='big' is not a number" in err
    assert "FESPP_INTERACTIVE_QUALITY=400 is outside 1..100" in err
    assert "(GPU)" in err


class _View:
    def __init__(self, gid, size, button_down=0):
        self._gid, self.ViewSize = gid, size
        self.UseInteractiveRenderingForScreenshots = button_down

    def GetGlobalIDAsString(self):
        return self._gid


class _Root:
    def __init__(self, links):
        self._links = links

    def getLinkProtocols(self):
        return self._links


def _trame_follows(monkeypatch, tracking):
    import types
    import trame_vtk.modules.paraview as tv
    delivery = types.SimpleNamespace(tracking_views=tracking)
    helper = types.SimpleNamespace(_root_protocol=_Root([object(), delivery]))
    monkeypatch.setattr(tv, "HELPERS_PER_SERVER", {"trame": helper})


def test_a_drag_frame_is_its_share_of_the_resting_size(monkeypatch):
    _trame_follows(monkeypatch, {"7": {"originalSize": (800, 600), "ratio": 0.5}})
    assert frames.drag_ratio(_View("7", [400, 300])) == 0.5
    assert frames.drag_ratio(_View("7", [800, 600])) == 1.0


def test_a_drag_at_full_resolution_is_a_drag(monkeypatch):
    # a GPU drags at full resolution: the button down says it, not the size
    _trame_follows(monkeypatch, {"7": {"originalSize": (800, 600), "ratio": 1}})
    assert frames.in_drag(_View("7", [800, 600], button_down=1))
    assert not frames.in_drag(_View("7", [800, 600]))
    # a smaller frame is a drag's whatever the button
    assert frames.in_drag(_View("7", [400, 300]))
    # a view with no such property: its size alone
    view = _View("7", [800, 600])
    del view.UseInteractiveRenderingForScreenshots
    assert not frames.in_drag(view)


def test_a_view_trame_does_not_follow_is_at_rest(monkeypatch):
    _trame_follows(monkeypatch, {"7": {"originalSize": (800, 600)}})
    assert frames.drag_ratio(_View("9", [400, 300])) == 1.0
    _trame_follows(monkeypatch, {"7": {}})
    assert frames.drag_ratio(_View("7", [400, 300])) == 1.0
    import trame_vtk.modules.paraview as tv
    monkeypatch.setattr(tv, "HELPERS_PER_SERVER", {})
    assert frames.drag_ratio(_View("7", [400, 300])) == 1.0


def test_the_managers_backend_is_remembered_once(monkeypatch):
    monkeypatch.setattr(frames, "_BACKEND", [])
    assert frames.render_backend() == ""
    frames.remember_backend("gpu")
    frames.remember_backend("software")
    assert frames.render_backend() == "gpu"
