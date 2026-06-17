"""Trame client-session lifecycle hooks.

Tracks how many trame clients are connected to this process; when
the last one leaves, drops the shared upload temp directory via
`temp_dir.cleanup_temp_dir`. Wired up from `engine.py` :

    controller.on_client_connected.add(on_client_connected)
    controller.on_client_exited.add(on_client_exited)

`atexit` and the SIGTERM/SIGINT handlers in `temp_dir.py` are the
belt-and-suspenders for the case where the process is killed before
the last client cleanly disconnects."""
from .temp_dir import cleanup_temp_dir


_active_clients = 0


def on_client_connected(**kwargs):
    global _active_clients
    _active_clients += 1
    print(f"[Session] Client connected. Active sessions: {_active_clients}", flush=True)


def on_client_exited(**kwargs):
    """Drop the temp directory once the last client disconnects."""
    global _active_clients
    _active_clients = max(0, _active_clients - 1)
    print(f"[Session] Client disconnected. Active sessions: {_active_clients}", flush=True)
    if _active_clients == 0:
        print("[Session] No active client left. Cleaning up temp files...", flush=True)
        cleanup_temp_dir()
