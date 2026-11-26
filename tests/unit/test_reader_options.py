"""The application reads the well logs as their polylines: the readers' LogTubes off, where the plugin has it."""
from fespp_on_trame.engine.sources.reader_options import logs_as_lines


class _Reader:
    def __init__(self, has_option):
        self._has = has_option
        self.LogTubes = 1

    def GetProperty(self, name):
        return object() if self._has and name == "LogTubes" else None


def test_the_logs_are_read_as_lines_where_the_plugin_says_so():
    reader = _Reader(True)
    assert logs_as_lines(reader) is True and reader.LogTubes == 0


def test_a_plugin_without_the_option_keeps_its_tubes():
    reader = _Reader(False)
    assert logs_as_lines(reader) is False and reader.LogTubes == 1
    assert logs_as_lines(None) is False
