"""HTTP multipart endpoint for uploading large EPC + H5 files.

Strategy: aiohttp middleware + patch AppRunner.setup() to catch the
app that actually serves HTTP requests (Trame creates several
aiohttp.Application instances during startup; the one we want is the
one AppRunner.setup wires up — not necessarily the first one we see).
"""
from pathlib import Path
from aiohttp import web as aiohttp_web


def register_upload_route(server) -> bool:
    from fespp_on_trame.app.io.temp_dir import temp_dir

    async def handle_upload(request: aiohttp_web.Request) -> aiohttp_web.Response:
        state = server.state
        controller = server.controller
        state.upload_uploading = True
        state.upload_progress = 0
        epc_paths = []
        total_size = int(request.headers.get("X-File-Size", 0))
        received = 0
        try:
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            reader = await request.multipart()
            async for field in reader:
                if not field.filename:
                    continue
                filename = field.filename
                filepath = Path(temp_dir) / filename
                print(f"[Upload] Receiving {filename}...", flush=True)
                if filepath.exists():
                    print(f"[Upload] File {filename} already exists, ignored.", flush=True)
                    continue
                with open(filepath, "wb") as f:
                    while True:
                        chunk = await field.read_chunk(512 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        if total_size > 0:
                            pct = min(99, int(received / total_size * 100))
                            if pct != state.upload_progress:
                                state.upload_progress = pct
                                state.flush()
                size_mb = filepath.stat().st_size / (1024 ** 2)
                print(f"[Upload] {filename} saved ({size_mb:.1f} MB)", flush=True)
                if filename.lower().endswith(".epc"):
                    epc_paths.append(str(filepath))
            state.upload_progress = 100
            state.flush()
            for path in epc_paths:
                controller.load_epc_file(path)
            state.upload_uploading = False
            state.flush()
            return aiohttp_web.json_response({"status": "ok", "epc_paths": epc_paths})
        except Exception as exc:
            import traceback
            traceback.print_exc()
            state.upload_uploading = False
            state.upload_progress = 0
            return aiohttp_web.json_response({"status": "error", "message": str(exc)}, status=500)

    global _registered_handler
    _registered_handler = handle_upload

    @aiohttp_web.middleware
    async def upload_middleware(request: aiohttp_web.Request, handler):
        print(f"[Upload-MW] {request.method} {request.path} app_id={id(request.app)}", flush=True)
        if request.method == "POST" and request.path in ("/upload", "/paraview/upload"):
            return await handle_upload(request)
        return await handler(request)

    # Patch 1: every aiohttp.Application created from now on gets the
    # upload middleware injected as its first middleware.
    _orig_app_init = getattr(aiohttp_web.Application, "_fespp_orig_init", None)
    if _orig_app_init is None:
        _orig_app_init = aiohttp_web.Application.__init__

        def _patched_app_init(self, *args, **kwargs):
            middlewares = list(kwargs.pop("middlewares", []) or [])
            middlewares.insert(0, upload_middleware)
            kwargs["middlewares"] = middlewares
            _orig_app_init(self, *args, **kwargs)
            print(f"[Upload] Application created id={id(self)}", flush=True)

        aiohttp_web.Application.__init__ = _patched_app_init
        aiohttp_web.Application._fespp_orig_init = _orig_app_init
        print("[Upload] Patch Application.__init__ installed.", flush=True)

    # Patch 2: AppRunner.setup() runs just before the app starts
    # serving requests. Intercepting it lets us inject the middleware
    # AND the route into the *effective* serving app, even when Trame
    # swapped the application instance after Patch 1 ran.
    try:
        from aiohttp.web_runner import AppRunner as _AppRunner

        _orig_runner_setup = getattr(_AppRunner, "_fespp_orig_setup", None)
        if _orig_runner_setup is None:
            _orig_runner_setup = _AppRunner.setup

            async def _patched_runner_setup(self_runner, *args, **kwargs):
                app = self_runner.app
                print(f"[Upload] AppRunner.setup() app_id={id(app)} type={type(app).__name__}", flush=True)
                mw_list = list(app.middlewares)
                if upload_middleware not in mw_list:
                    # Insert via _middlewares (the public list is
                    # frozen at this point; the underlying tuple is
                    # the only way in).
                    try:
                        app._middlewares = (upload_middleware,) + tuple(mw_list)
                        print("[Upload] Middleware injected into serving app.", flush=True)
                    except Exception as exc:
                        print(f"[Upload] Middleware injection failed: {exc}", flush=True)
                # Belt-and-suspenders: also register the route on the
                # router (some configurations bypass middleware).
                try:
                    router = app.router
                    was_frozen = getattr(router, "_frozen", False)
                    if was_frozen:
                        router._frozen = False
                    for path in ("/upload", "/paraview/upload"):
                        try:
                            router.add_post(path, _registered_handler)
                            print(f"[Upload] Route {path} injected into serving app.", flush=True)
                        except Exception as e:
                            print(f"[Upload] Failed to inject route {path}: {e}", flush=True)
                    if was_frozen:
                        router._frozen = was_frozen
                except Exception as exc:
                    print(f"[Upload] Route injection failed: {exc}", flush=True)
                return await _orig_runner_setup(self_runner, *args, **kwargs)

            _AppRunner.setup = _patched_runner_setup
            _AppRunner._fespp_orig_setup = _orig_runner_setup
            print("[Upload] Patch AppRunner.setup() installed.", flush=True)
    except Exception as exc:
        print(f"[Upload] Unable to patch AppRunner: {exc}", flush=True)

    return True


_registered_handler = None


def resolve_upload_session_id(server) -> None:
    """Fill `state.upload_session_id` once the trame server is bound
    to its port. Each process looks up its own port in
    `/opt/trame/proxy-mapping.txt` to build the per-session
    `/api/{sid}/upload` URL the client posts to.

    The lookup is best-effort — running outside the trame container
    (the file doesn't exist) leaves the session id empty, which the
    client falls back to a no-prefix `/upload` for."""
    state = server.state
    port = getattr(server, "_running_port", None) or getattr(server, "port", None)
    sid = ""
    try:
        with open("/opt/trame/proxy-mapping.txt") as _f:
            for _ln in _f:
                parts = _ln.strip().split()
                if len(parts) == 2 and parts[1].endswith(f":{port}"):
                    sid = parts[0]
                    break
    except Exception:
        pass
    state.upload_session_id = sid
    print(f"[Upload] session_id={sid!r} (port={port})", flush=True)
