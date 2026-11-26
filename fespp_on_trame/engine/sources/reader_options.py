"""What the application asks of the plugin's readers (the EPC collector, the
ETP store) when it makes them."""


def logs_as_lines(proxy):
    """Turn the reader's LogTubes off: a well log is read as its polyline, one
    point per node of its frame, instead of the tube of ten sides the plugin
    makes for ParaView. The application draws every log with the well symbols
    filter (app/features/log_tracks), which makes a tube of those shown so;
    the reader's tubes cost ten times the points and their normals (Volve,
    every log of its 13 wells: 4.2 GB of tubes). A plugin without the option
    keeps its tubes, which every reader of a log in the application reads as
    well. Returns whether the option was there."""
    prop = proxy.GetProperty("LogTubes") if proxy is not None else None
    if prop is None:
        return False
    proxy.LogTubes = 0
    return True
