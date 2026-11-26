"""engine/vtk_log: fetpapi's words when the ETP session is gone, counted
from stderr (the only place fetpapi says it).

A server may close the socket some time after a read and refuse fetpapi's
reconnection; every request then fails, and without this count nothing
tells the reader the session is lost."""
from fespp_on_trame.engine import vtk_log


def _count(line):
    before = vtk_log.ETP_LOST["count"]
    vtk_log.note_etp_line(line)
    return vtk_log.ETP_LOST["count"] - before


def test_the_words_of_a_lost_session_are_counted():
    for line in (
        "on_read : error message End of file",
        "Session 3cde1439-1135-4c13-b2a4-fdf99850fa02 has been disconnected, trying to reconnect... 1/10",
        "Single error code 11 : Session not found or expired",
        "Single error code 4 : Unsupported protocol: 3",
        "Could not reconnect after 10 retries... Give up and close10/10",
        "The ETP session could not be opened in order to send again the message.",
        "[fespp] etp read aborted after its ArrayReadTimeout: the ETP session is closed, connect again",
    ):
        assert _count(line) == 1, line
    assert vtk_log.ETP_LOST["line"].startswith("[fespp] etp read aborted")


def test_ordinary_lines_are_not():
    for line in (
        "",
        "on_read : error message Operation canceled",
        "( 272.5s) [paraview] vtkOutputWindow.cxx:77 WARN| There is no dataobject in the dataspace : x",
        "[fespp] load: 28 selected (+1), 1.1 s (reader 0.9 s)",
        "Connected to ETP server: wss://admeinterop.energy.azure.com/api/reservoir-ddms-etp/v2/",
    ):
        assert _count(line) == 0, line
