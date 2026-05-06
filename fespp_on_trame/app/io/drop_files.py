import atexit
import os
import gc
import shutil
import signal
import sys
from pathlib import Path
from tempfile import mkdtemp
import base64

from trame.app import get_server

server = get_server()
state = server.state

temp_dir = mkdtemp()
CHUNK_SIZE = 32 * 1024 * 1024

_active_clients = 0


def cleanup_temp_dir():
    """Remove the shared temp directory used by the upload route."""
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"[Cleanup] Temp directory removed: {temp_dir}", flush=True)
        except Exception as e:
            print(f"[Cleanup] Failed to remove {temp_dir}: {e}", flush=True)


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


def _signal_handler(sig, frame):
    print(f"[Cleanup] Signal {sig} received, cleaning up...", flush=True)
    cleanup_temp_dir()
    sys.exit(0)


atexit.register(cleanup_temp_dir)

# Catch Docker stop / Kubernetes / systemd / Ctrl+C.
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


def setup_for_large_files():
    """Tweak process-level limits for multi-GB EPC files: lift the
    memory limit, force unbuffered IO, and tune the GC threshold."""
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


def save_uploaded_files(files):
    """Persist a list of upload payloads to the shared temp directory.
    Returns the list of saved EPC paths."""
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    epc_paths = []

    for i, file_info in enumerate(files):
        file_path = None
        try:
            file_name = file_info.get("name", f"file_{i}")
            print(f"start: {file_name}")

            content = file_info.get("content")
            if not content:
                print(f"File {file_name} no content")
                continue

            file_path = os.path.join(temp_dir, file_name)

            if isinstance(content, str) and len(content) > 100 * 1024 * 1024:
                # >100MB base64 — stream-decode in chunks to avoid
                # loading the whole payload into memory at once.
                print("large file detected, use stream mode...")
                file_path = save_large_base64_stream(content, file_path)
            else:
                with open(file_path, "wb") as f:
                    if isinstance(content, bytes):
                        f.write(content)
                    elif isinstance(content, str):
                        if content.startswith('data:'):
                            base64_data = content.split('base64,')[1] if 'base64,' in content else content
                            f.write(base64.b64decode(base64_data))
                        else:
                            f.write(content.encode())

            if file_path and os.path.exists(file_path) and file_name.lower().endswith('.epc'):
                epc_paths.append(file_path)
                print(f"✓ {file_name} saved ({os.path.getsize(file_path)/(1024**3):.2f}GB)")
            del content
            gc.collect()

        except Exception as e:
            print(f"✗ Error {file_name}: {str(e)}")
            import traceback
            traceback.print_exc()
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            continue
    return epc_paths


def save_large_base64_stream(base64_content, file_path, chunk_size=4 * 1024 * 1024):
    """Decode and write a base64 payload chunk by chunk. Pads each
    chunk to a multiple of 4 bytes (base64 alignment) so b64decode
    doesn't choke on a mid-stream truncation."""
    try:
        with open(file_path, "wb") as f:
            total_length = len(base64_content)
            decoded_size_estimate = (total_length * 3) // 4

            print(f"file size: {decoded_size_estimate/(1024**3):.2f}GB")

            for i in range(0, total_length, chunk_size):
                end = min(i + chunk_size, total_length)
                chunk = base64_content[i:end]

                remainder = len(chunk) % 4
                if remainder != 0:
                    chunk += '=' * (4 - remainder)

                try:
                    decoded = base64.b64decode(chunk)
                    f.write(decoded)
                except Exception as e:
                    print(f"Error chunk decode {i}-{end}: {e}")
                    continue

                if i % (chunk_size * 100) == 0:
                    f.flush()
                    progress = (i / total_length) * 100
                    print(f"Progress: {progress:.1f}%")

            f.flush()
            os.fsync(f.fileno())

        return file_path

    except Exception as e:
        print(f"Error on save_large_base64_stream: {e}")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        return None


setup_for_large_files()
