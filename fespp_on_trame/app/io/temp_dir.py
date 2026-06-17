"""Process-level boot side effects related to file uploads.

Importing this module:
  - creates the shared temp directory used by `upload_endpoint`,
  - registers `cleanup_temp_dir` for `atexit`, `SIGTERM`, `SIGINT`
    so the directory gets removed on any graceful (or container-
    stopped) shutdown,
  - applies process tuning suitable for multi-GB EPC uploads
    (unbuffered IO, raised RLIMIT_AS, looser GC threshold).

Session-driven cleanup (drop the directory when the last client
disconnects) lives in `session_hooks.py` — it calls
`cleanup_temp_dir` from here once the active-client counter hits
zero."""
import atexit
import gc
import os
import shutil
import signal
import sys
from tempfile import mkdtemp


# Shared temp directory. The upload endpoint writes incoming files
# here; the engine's load_epc_file reads from the path returned by
# the endpoint.
temp_dir = mkdtemp()


def cleanup_temp_dir():
    """Remove the shared temp directory used by the upload route."""
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"[Cleanup] Temp directory removed: {temp_dir}", flush=True)
        except Exception as e:
            print(f"[Cleanup] Failed to remove {temp_dir}: {e}", flush=True)


def _signal_handler(sig, frame):
    print(f"[Cleanup] Signal {sig} received, cleaning up...", flush=True)
    cleanup_temp_dir()
    sys.exit(0)


def _setup_for_large_files():
    """Tweak process-level limits for multi-GB EPC files: lift the
    memory limit, force unbuffered IO, and loosen the GC threshold."""
    os.environ['PYTHONUNBUFFERED'] = '1'

    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        new_soft = 8 * 1024**3
        if hard == resource.RLIM_INFINITY or hard > new_soft:
            resource.setrlimit(resource.RLIMIT_AS, (new_soft, hard))
    except Exception as e:
        print(f"ERROR change mem limit: {e}")

    gc.set_threshold(50, 5, 5)
    gc.enable()


# --- Boot side effects (fire on first import) -----------------------

atexit.register(cleanup_temp_dir)

# Catch Docker stop / Kubernetes / systemd / Ctrl+C.
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

_setup_for_large_files()
