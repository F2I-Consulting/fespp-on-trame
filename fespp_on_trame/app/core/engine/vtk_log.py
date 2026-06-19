"""VTK / ParaView stderr capture for the in-app log panel.

VTK and ParaView write through C-level fd 2 via vtkLogger; the
Python-level `print(..., file=sys.stderr)` / `logging` machinery
doesn't see those bytes. We tee fd 2 so VTK output reaches BOTH
docker logs (preserved for container-side debugging) AND an in-memory
queue that the UI surfaces via `state.vtk_log_messages`.

Public API:
  - `setup_stderr_tee()` — must run AFTER ParaView init, otherwise
    startup noise floods the queue.
  - `capture_vtk_messages(state, max_messages=500)` — context manager
    that slices the queue around the wrapped block, so each session
    only sees its own messages.

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

# Known-noise patterns to suppress in BOTH docker logs and the
# in-memory queue. Each is matched against the cleaned message text
# (no ANSI codes, no level prefix). Add a new entry rather than
# silence broader categories when a recurring nuisance appears.
_SUPPRESS_PATTERNS = (
    # Fires on every time-slider tick while the stats compute holds
    # the active view at None to neutralise ptc reactions. The lack
    # of an active view in that window is expected, not an error.
    re.compile(r"No active view found"),
)


def setup_stderr_tee() -> None:
    """Tee C-level stderr so VTK output reaches both docker logs and
    the in-memory queue without touching vtkOutputWindow. Idempotent
    — second and later calls are no-ops."""
    global _vtk_stderr_tee_done
    if _vtk_stderr_tee_done:
        return
    try:
        read_fd, write_fd = os.pipe()
        orig_fd = os.dup(2)
        os.dup2(write_fd, 2)
        os.close(write_fd)

        def _reader():
            buf = b""
            # A vtkLogger message spans several physical lines: only the
            # first carries the "(..s)[..]LEVEL|" prefix; the rest are
            # continuation lines (e.g. FESAPI's per-property warnings).
            # `cur_idx` is the queue entry those continuations append to
            # (-1 = none open); `suppressing` mutes a suppressed message and
            # its continuations together.
            cur_idx = -1
            suppressing = False
            with os.fdopen(read_fd, "rb", buffering=0) as src, \
                 os.fdopen(orig_fd,  "wb", buffering=0) as dst:
                while True:
                    chunk = src.read(1024)
                    if not chunk:
                        break
                    buf += chunk
                    # Drain whole lines so the suppression decision
                    # is taken line-by-line — we can't filter the raw
                    # chunk (a single read might straddle a boundary).
                    while b"\n" in buf:
                        raw_line, buf = buf.split(b"\n", 1)
                        clean = _ANSI_RE.sub(
                            "", raw_line.decode("utf-8", errors="replace")
                        ).strip()
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
                            # Forward to docker logs verbatim (ANSI codes
                            # intact so colour-aware log viewers highlight
                            # WARN/ERR).
                            dst.write(raw_line)
                            dst.write(b"\n")
                            dst.flush()
                            level_tag = m.group(1)
                            level = (
                                "error"   if "ERR"  in level_tag else
                                "warning" if "WARN" in level_tag else
                                "info"
                            )
                            _vtk_log_queue.append({"text": text, "level": level})
                            cur_idx = len(_vtk_log_queue) - 1
                        else:
                            # Continuation of the open message (or noise when
                            # none is open). Append to the open entry so the
                            # in-app log shows the FULL multi-line message, not
                            # just its first line.
                            if suppressing:
                                continue
                            dst.write(raw_line)
                            dst.write(b"\n")
                            dst.flush()
                            if clean and cur_idx >= 0:
                                _vtk_log_queue[cur_idx]["text"] += "\n" + clean

        threading.Thread(target=_reader, daemon=True).start()
        _vtk_stderr_tee_done = True
        sys.stdout.write("[VTK log] stderr tee installed\n")
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
    so a per-window `len()` snapshot alone races and duplicates)."""
    global _vtk_queue_consumed
    start_seq = len(_vtk_log_queue)
    try:
        yield
    finally:
        # Let the reader thread flush the bytes already in the pipe.
        time.sleep(0.05)
        begin = max(start_seq, _vtk_queue_consumed)
        new_messages = list(_vtk_log_queue[begin:])
        _vtk_queue_consumed = len(_vtk_log_queue)
        if new_messages:
            current = list(state.vtk_log_messages or [])
            state.vtk_log_messages = (current + new_messages)[-max_messages:]
