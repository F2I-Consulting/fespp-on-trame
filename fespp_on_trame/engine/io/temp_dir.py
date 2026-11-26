"""Process-level boot side effects for file uploads.

Importing this module:
  - creates the shared temp directory `upload_endpoint` writes to,
  - registers `cleanup_temp_dir` for `atexit`, SIGTERM and SIGINT, so the
    directory is removed on any graceful shutdown, a container stop
    included,
  - lifts the address-space limit for multi-GB EPC files (see
    _setup_for_large_files).

`session_hooks` offers a session-driven cleanup as well: once hooked on the
controller's client events, it calls `cleanup_temp_dir` when the last
client disconnects."""
import atexit
import os
import shutil
import signal
import sys
from tempfile import mkdtemp


# Shared temp directory, one per process: the upload endpoint writes the
# incoming files here and hands their paths to load_epc_file.
temp_dir = mkdtemp()


def cleanup_temp_dir():
    """Remove the shared temp directory used by the upload route."""
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"[Cleanup] Temp directory removed: {temp_dir}", flush=True)
        except Exception:
            pass


def _signal_handler(sig, frame):
    """Remove the temp directory, then exit with status 0."""
    print(f"[Cleanup] Signal {sig} received, cleaning up...", flush=True)
    cleanup_temp_dir()
    sys.exit(0)


def _setup_for_large_files():
    """Raise the soft address-space limit (RLIMIT_AS) to the hard one.

    RLIMIT_AS caps the address space the process reserves, which runs well
    above the memory it actually uses (allocator arenas, mapped files, the
    renderer's buffers): a soft limit under the hard one can make a
    multi-GB EPC fail with a MemoryError while the machine still has memory
    to give. Any process may raise its soft limit up to its hard limit, so
    it is raised; it is never lowered, and the hard limit, set by whoever
    runs the process, stays the ceiling.

    POSIX only: Windows has no `resource` module and no such limit."""
    try:
        import resource
    except ImportError:
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        unlimited = resource.RLIM_INFINITY
        # "unlimited" is recognised by RLIM_INFINITY, never by size: Python
        # may read it as -1 (Linux), below every finite limit
        if soft == unlimited or (hard != unlimited and soft >= hard):
            return
        resource.setrlimit(resource.RLIMIT_AS, (hard, hard))
    except (AttributeError, ValueError, OSError) as exc:
        print("[fespp] the address-space limit could not be raised:", exc, flush=True)
        return
    print("[fespp] address-space soft limit raised from", soft, "bytes to the hard"
          " limit:", "unlimited" if hard == unlimited else f"{hard} bytes", flush=True)


# --- Boot side effects (fire on first import) -----------------------

atexit.register(cleanup_temp_dir)

# SIGTERM from a container or service stop, SIGINT from Ctrl+C.
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

_setup_for_large_files()
