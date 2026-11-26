"""VTK / ParaView stderr capture for the in-app log panel.

VTK and ParaView write through C-level fd 2 via vtkLogger; the
Python-level `print(..., file=sys.stderr)` / `logging` machinery
does not see those bytes. fd 2 is teed so VTK output reaches BOTH the
process's original stderr (console or container logs, kept for
debugging) AND an in-memory queue that the UI surfaces via
`state.vtk_log_messages`.

Public API:
  - `setup_stderr_tee()` — must run AFTER ParaView init, otherwise
    startup noise floods the queue.
  - `capture_vtk_messages(state, max_messages=500)` — context manager
    that slices the queue around the wrapped block, so each session
    only sees its own messages.
  - `ETP_LOST` / `note_etp_line` — a count of the fetpapi lines that say
    the ETP session is gone, which the tee feeds line by line.

Module-level state is intentional: there is exactly one stderr fd
per process, so a single queue + tee thread is the right shape."""
import contextlib
import os
import re
import sys
import threading
import time


_vtk_log_queue: list = []
_vtk_queue_consumed = 0  # high-water mark: queue entries already surfaced
_vtk_stderr_tee_done = False

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHJA-Z]")
# vtkLogger line format: "(  29.2s) [thread] file.cxx:67  ERR| message"
_VTK_LINE_RE = re.compile(r"\([\d. ]+s\)\s*\[.*?\].*?\b([A-Z]{3,})\|\s*(.*)")

# Known-noise patterns to suppress in BOTH the forwarded stderr and the
# in-memory queue. Each is matched against the cleaned message text
# (no ANSI codes, no level prefix). Add a new entry rather than
# silence broader categories when a recurring nuisance appears.
_SUPPRESS_PATTERNS = (
    # Fires on every time-slider tick while the stats compute holds
    # the active view at None to neutralise ptc reactions. The lack
    # of an active view in that window is expected, not an error.
    re.compile(r"No active view found"),
)

# fetpapi's own words, on stderr, when the ETP session is gone: the server
# closed the socket ("End of file"), fetpapi's reconnection is refused (it
# replays the old session request, which an OSDU server such as ADME
# answers with "Session not found or expired"), then every request is
# refused by a server that no longer knows the session ("Unsupported
# protocol: 3"). A server can drop an idle session within minutes while
# the token is still valid, and nothing else reports it: without this
# count, the next dataspace would "load" with nothing in it.
_ETP_LOST_RE = re.compile(
    r"on_read : error message End of file"
    r"|has been disconnected, trying to reconnect"
    r"|Session not found or expired"
    r"|Unsupported protocol: \d+"
    r"|Could not reconnect after"
    r"|ETP session could not be opened"
    # the plugin's own read watch closed the session (ArrayReadTimeout)
    r"|etp read aborted after its ArrayReadTimeout")
#: How many such lines the process has printed, and the last one: the
#: application notes the count at each connection and compares.
ETP_LOST = {"count": 0, "line": ""}


def note_etp_line(text):
    """Count `text` when it says the ETP session is gone (the tee calls it
    for every line of stderr)."""
    if text and _ETP_LOST_RE.search(text):
        ETP_LOST["count"] += 1
        ETP_LOST["line"] = text
        return True
    return False


def setup_stderr_tee() -> None:
    """Tee C-level stderr so VTK / FESAPI output reaches both the original
    stderr (console / docker logs) and the in-memory queue, without touching
    vtkOutputWindow. Idempotent — second and later calls are no-ops.

    fd 2 is redirected to a TEMP FILE, not an ``os.pipe()``. A pipe's fixed
    (~64KB) kernel buffer overflows when a native FESAPI/VTK burst (e.g. an
    IjkGrid property's per-cell WARN flood) exceeds it, parking the C++
    ``write(2)`` on the full pipe — and the Python reader that would drain it
    cannot run because the GIL-holding native call has not returned: a
    deadlock at 0 % CPU that freezes the whole application. A file never
    back-pressures, so the native write always returns; a daemon reader
    tails the file into the queue and best-effort-forwards each line to the
    real stderr."""
    global _vtk_stderr_tee_done
    if _vtk_stderr_tee_done:
        return
    try:
        import tempfile
        _TEE_MAX = 8 * 1024 * 1024  # cap the temp file over a long noisy session
        tf = tempfile.NamedTemporaryFile(
            prefix="fespp_vtk_", suffix=".log", delete=False)
        tee_path = tf.name
        tf.close()
        # Writer side append-only, so the reader can truncate-when-caught-up
        # coherently (the next native write always lands at the new EOF).
        cap_fd = os.open(tee_path, os.O_WRONLY | os.O_APPEND)
        orig_fd = os.dup(2)
        os.dup2(cap_fd, 2)
        os.close(cap_fd)

        def _reader():
            # A vtkLogger message spans several physical lines: only the first
            # carries the "(..s)[..]LEVEL|" prefix; the rest are continuation
            # lines (e.g. FESAPI's per-property warnings). `cur_idx` is the
            # queue entry those continuations append to (-1 = none open);
            # `suppressing` mutes a suppressed message and its continuations.
            cur_idx = -1
            suppressing = False
            buf = b""
            src = open(tee_path, "rb")
            dst = os.fdopen(orig_fd, "wb", buffering=0)

            def _forward(payload):
                # Best-effort echo to the real stderr; a stalled console
                # consumer must NEVER wedge the tail loop (that would be
                # the very back-pressure stall the temp file avoids).
                try:
                    dst.write(payload)
                    dst.flush()
                except OSError:
                    pass

            while True:
                chunk = src.read(65536)
                if not chunk:
                    # Caught up with the writer: tail-wait. Bound the temp file
                    # so a long session of floods can't grow it without limit.
                    try:
                        if src.tell() > _TEE_MAX:
                            os.truncate(tee_path, 0)
                            src.seek(0)
                    except OSError:
                        pass
                    time.sleep(0.05)
                    continue
                buf += chunk
                # Drain whole lines so the suppression decision is taken
                # line-by-line — a single read might straddle a boundary.
                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    clean = _ANSI_RE.sub(
                        "", raw_line.decode("utf-8", errors="replace")
                    ).strip()
                    note_etp_line(clean)
                    m = _VTK_LINE_RE.search(clean) if clean else None
                    if m:
                        # New vtkLogger message — opens a fresh entry.
                        text = m.group(2).strip()
                        suppressing = any(
                            p.search(text) for p in _SUPPRESS_PATTERNS
                        )
                        if suppressing:
                            cur_idx = -1
                            continue
                        _forward(raw_line + b"\n")
                        level_tag = m.group(1)
                        level = (
                            "error"   if "ERR"  in level_tag else
                            "warning" if "WARN" in level_tag else
                            "info"
                        )
                        _vtk_log_queue.append({"text": text, "level": level})
                        cur_idx = len(_vtk_log_queue) - 1
                    else:
                        # Continuation of the open message (or noise when none
                        # is open). Append to the open entry so the in-app log
                        # shows the FULL multi-line message, not just line 1.
                        if suppressing:
                            continue
                        _forward(raw_line + b"\n")
                        if clean and cur_idx >= 0:
                            _vtk_log_queue[cur_idx]["text"] += "\n" + clean

        threading.Thread(target=_reader, daemon=True).start()
        _vtk_stderr_tee_done = True
        sys.stdout.write("[VTK log] stderr tee installed (file-backed)\n")
        sys.stdout.flush()
    except Exception as exc:
        sys.stdout.write(f"[VTK log] stderr tee failed: {exc}\n")
        sys.stdout.flush()


@contextlib.contextmanager
def capture_vtk_messages(state, max_messages: int = 500):
    """Capture VTK messages emitted during the block into
    `state.vtk_log_messages`. Consumes the shared queue past a monotonic
    high-water mark so two overlapping/sequential capture windows never
    surface the same entry twice (the reader thread appends asynchronously,
    so a per-window `len()` snapshot alone races and duplicates).

    Yields the list of the entries captured by THIS block, filled when the
    block ends. Callers read that list rather than diffing the length of
    `state.vtk_log_messages`: the latter is capped at `max_messages`, so
    once the cap is reached it shows nothing new, and a failed import after
    a warning flood would find no error to report."""
    global _vtk_queue_consumed
    start_seq = len(_vtk_log_queue)
    captured = []
    try:
        yield captured
    finally:
        # Give the reader thread time to tail the bytes already written to
        # the temp file.
        time.sleep(0.05)
        begin = max(start_seq, _vtk_queue_consumed)
        new_messages = list(_vtk_log_queue[begin:])
        _vtk_queue_consumed = len(_vtk_log_queue)
        captured.extend(new_messages)
        if new_messages:
            current = list(state.vtk_log_messages or [])
            state.vtk_log_messages = (current + new_messages)[-max_messages:]
            _flag_invalid_nodes(state, new_messages)


# FESPP names the object it could not read in two wordings: "Error when
# initialize uuid: <uuid>" when a property's values cannot be opened (the
# .h5 is missing, or its element count does not match the grid) and "Error
# when rendering uuid: <uuid>" when a mapper cannot materialise. Both carry
# fesapi's own explanation on the next line.
_INVALID_UUID_RE = re.compile(
    r"Error when (?:rendering|initializ\w*) uuid:\s*([0-9a-fA-F-]{36})")
_INVALID_HEADER_RE = re.compile(r"^Error when (?:rendering|initializ\w*) uuid")


def _session_temp_dir():
    """The upload directory, so a message can name a file by its name and
    not by the server's temporary path."""
    try:
        from fespp_on_trame.engine.io.temp_dir import temp_dir
        return temp_dir
    except Exception:
        return ""


def _flag_invalid_nodes(state, new_messages):
    """Uncheck, badge and announce the tree nodes whose data could not be
    read.

    A failing rep RE-LOGS its error on every subsequent render of
    anything, flooding the log and drowning real errors: unchecking the
    node stops the loop at its source. The node keeps its error in
    `ui_invalid_node_errors` (Data health lists it) and its id in
    `ui_invalid_node_ids`; the user is told through the `load_error`
    snackbar with fesapi's own wording, the temporary path stripped.
    Re-checking the node simply re-runs this if the data is still
    unreadable."""
    try:
        uuids = {
            m
            for msg in new_messages or []
            for m in _INVALID_UUID_RE.findall(str(msg.get("text") or ""))
        }
        if not uuids:
            return
        from trame.app import get_server
        tree = getattr(get_server().context, "tree", None)
        if tree is None:
            return
        from fespp_on_trame.engine.io import read_report
        temp_dir = _session_temp_dir()
        invalid = list(state.ui_invalid_node_ids or [])
        errors = dict(state.ui_invalid_node_errors or {})
        toast = []
        drop_paths = set()
        for uuid in sorted(uuids):
            try:
                nid = tree._data_assembly.FindFirstNodeWithName("_" + uuid)
            except Exception:
                nid = -1
            if nid is None or nid < 0:
                continue
            if nid not in invalid:
                invalid.append(nid)
            # Keep FESAPI/VTK's OWN wording — it names the exact dataset
            # that failed, far more actionable than a generic sentence.
            # Drop the header by line PREFIX — never by uuid presence: the
            # detail line ("The HDF5 dataset /RESQML/<uuid>/… could not be
            # opened.") contains the uuid too, in its dataset path.
            detail = ""
            for msg in new_messages or []:
                text = str(msg.get("text") or "")
                if uuid not in text:
                    continue
                lines = [
                    ln.strip() for ln in text.splitlines()
                    if ln.strip() and not _INVALID_HEADER_RE.match(ln.strip())
                ]
                if lines:
                    detail = read_report.strip_paths(" ".join(lines), temp_dir)[:300]
                    break
            errors[str(nid)] = detail or "Dataset could not be read."
            try:
                drop = set(tree.find_all_descendant_ids(nid))
            except Exception:
                drop = set()
            drop.add(nid)
            for i in drop:
                try:
                    p = tree.find_path(i)
                except Exception:
                    p = None
                if p:
                    drop_paths.add(p)
            toast.append((tree.find_title(nid) or uuid, str(nid)))
        # The selection is the session's `selected_paths`: taking the paths
        # out of it unchecks the boxes and unloads the data through the
        # one pipeline every tick uses.
        cur = list(getattr(state, "selected_paths", None) or [])
        kept = [p for p in cur if p not in drop_paths]
        if len(kept) != len(cur):
            state.selected_paths = kept
        if (getattr(state, "active_path", "") or "") in drop_paths:
            # the node just removed was the active one: a clean "nothing
            # active" instead of some still-checked node promoted without
            # a click
            state.active_path = ""
        # and in every 3D view: the cards must not keep naming an object no
        # longer read (03 §6.2, SA — app/scene/activation)
        act = getattr(get_server().context, "activation", None)
        if act is not None:
            act.clear(drop_paths)
        state.ui_invalid_node_ids = invalid
        state.ui_invalid_node_errors = errors
        if toast:
            # The notification IS fesapi's message, verbatim — no
            # "Deselected …" preamble: its wording names what failed.
            _title, nid_key = sorted(set(toast))[0]
            state.load_error = (
                errors.get(nid_key) or "Dataset could not be read."
            )
    except Exception:
        pass


