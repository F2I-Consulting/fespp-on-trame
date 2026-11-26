"""trame client-session lifecycle hooks.

Counts the trame clients connected to this process and, when the last one
leaves, removes the shared upload temp directory with
`temp_dir.cleanup_temp_dir`. The hooks take effect once added to the
controller's client events:

    controller.on_client_connected.add(on_client_connected)
    controller.on_client_exited.add(on_client_exited)

`atexit` and the SIGTERM/SIGINT handlers in `temp_dir` cover a process
that stops before its last client disconnects cleanly."""
from .temp_dir import cleanup_temp_dir


_active_clients = 0


def on_client_connected(**kwargs):
    """Count one more connected client."""
    global _active_clients
    _active_clients += 1
    print(f"[Session] Client connected. Active sessions: {_active_clients}", flush=True)


def on_client_exited(**kwargs):
    """Count one client fewer (never below zero) and remove the temp
    directory once the last client has disconnected."""
    global _active_clients
    _active_clients = max(0, _active_clients - 1)
    print(f"[Session] Client disconnected. Active sessions: {_active_clients}", flush=True)
    if _active_clients == 0:
        print("[Session] No active client left. Cleaning up temp files...", flush=True)
        cleanup_temp_dir()
