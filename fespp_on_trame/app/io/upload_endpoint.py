"""HTTP multipart endpoint for uploading large EPC + H5 files.

Strategy: aiohttp middleware + patch AppRunner.setup() to catch the
app that actually serves HTTP requests (Trame creates several
aiohttp.Application instances during startup; the one we want is the
one AppRunner.setup wires up — not necessarily the first one we see).
"""
import asyncio
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
                # SECURITY: the multipart filename is fully client-controlled.
                # Reduce it to a bare basename (defusing `../` and absolute-path
                # escapes on both `/` and `\` separators) and allow only the two
                # extensions this app actually consumes, so a POST to /upload can
                # never create a file outside temp_dir or of an executable type.
                filename = (field.filename or "").replace("\\", "/").split("/")[-1]
                if not filename or filename in (".", ".."):
                    continue
                if not filename.lower().endswith((".epc", ".h5")):
                    print(f"[Upload] rejected non-EPC/H5 upload: {filename!r}", flush=True)
                    continue
                filepath = Path(temp_dir) / filename
                base = Path(temp_dir).resolve()
                if base != filepath.resolve() and base not in filepath.resolve().parents:
                    print(f"[Upload] rejected path escape: {filename!r}", flush=True)
                    continue
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
            # The C++ EPC parse below BLOCKS the event loop for 1-2 s
            # (measured). Flip the overlay to "Reading EPC…" and yield ONCE so
            # the flush actually reaches the client BEFORE the blocking loop —
            # without the sleep(0) the message would only ship after it.
            state.upload_parsing = True
            state.flush()
            await asyncio.sleep(0)
            try:
                for path in epc_paths:
                    controller.load_epc_file(path)
            finally:
                state.upload_parsing = False
            state.upload_uploading = False
            state.flush()
            # Return basenames only — never leak absolute server temp paths.
            return aiohttp_web.json_response(
                {"status": "ok", "epc_paths": [Path(p).name for p in epc_paths]})
        except Exception as exc:
            state.upload_uploading = False
            state.upload_progress = 0
            print(f"[Upload] error: {exc}", flush=True)  # server-side log only
            return aiohttp_web.json_response(
                {"status": "error", "message": "upload failed"}, status=500)

    global _registered_handler
    _registered_handler = handle_upload

    @aiohttp_web.middleware
    async def upload_middleware(request: aiohttp_web.Request, handler):
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

        aiohttp_web.Application.__init__ = _patched_app_init
        aiohttp_web.Application._fespp_orig_init = _orig_app_init

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
                mw_list = list(app.middlewares)
                if upload_middleware not in mw_list:
                    # Insert via _middlewares (the public list is
                    # frozen at this point; the underlying tuple is
                    # the only way in).
                    try:
                        app._middlewares = (upload_middleware,) + tuple(mw_list)
                    except Exception as exc:
                        pass
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
                        except Exception as e:
                            pass
                    if was_frozen:
                        router._frozen = was_frozen
                except Exception as exc:
                    pass
                return await _orig_runner_setup(self_runner, *args, **kwargs)

            _AppRunner.setup = _patched_runner_setup
            _AppRunner._fespp_orig_setup = _orig_runner_setup
    except Exception as exc:
        pass

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
