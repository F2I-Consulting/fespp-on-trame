"""
Endpoint HTTP multipart pour l'upload de fichiers volumineux.

Stratégie : middleware aiohttp + patch AppRunner.setup() pour attraper
l'app qui sert VRAIMENT les requêtes HTTP.
"""
from pathlib import Path
from aiohttp import web as aiohttp_web


def register_upload_route(server) -> bool:
    from fespp_on_trame.app.io.drop_files import temp_dir

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
                print(f"[Upload] Réception de {filename}...", flush=True)
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
                print(f"[Upload] {filename} sauvegardé ({size_mb:.1f} Mo)", flush=True)
                if filename.lower().endswith(".epc"):
                    epc_paths.append(str(filepath))
            for path in epc_paths:
                controller.load_epc_file(path)
            state.upload_progress = 100
            state.upload_uploading = False
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
        # Log TOUTES les requêtes pour diagnostiquer quelle app sert réellement
        print(f"[Upload-MW] {request.method} {request.path} app_id={id(request.app)}", flush=True)
        if request.method == "POST" and request.path in ("/upload", "/paraview/upload"):
            return await handle_upload(request)
        return await handler(request)

    # ── Patch 1 : aiohttp.Application.__init__ ────────────────────────────────
    _orig_app_init = getattr(aiohttp_web.Application, "_fespp_orig_init", None)
    if _orig_app_init is None:
        _orig_app_init = aiohttp_web.Application.__init__

        def _patched_app_init(self, *args, **kwargs):
            middlewares = list(kwargs.pop("middlewares", []) or [])
            middlewares.insert(0, upload_middleware)
            kwargs["middlewares"] = middlewares
            _orig_app_init(self, *args, **kwargs)
            print(f"[Upload] Application créée id={id(self)}", flush=True)

        aiohttp_web.Application.__init__ = _patched_app_init
        aiohttp_web.Application._fespp_orig_init = _orig_app_init
        print("[Upload] Patch Application.__init__ installé.", flush=True)

    # ── Patch 2 : AppRunner.setup() ───────────────────────────────────────────
    # AppRunner.setup() est appelé juste avant que l'app serve vraiment.
    # On l'intercepte pour injecter les routes sur l'app effective.
    try:
        from aiohttp.web_runner import AppRunner as _AppRunner

        _orig_runner_setup = getattr(_AppRunner, "_fespp_orig_setup", None)
        if _orig_runner_setup is None:
            _orig_runner_setup = _AppRunner.setup

            async def _patched_runner_setup(self_runner, *args, **kwargs):
                app = self_runner.app
                print(f"[Upload] AppRunner.setup() app_id={id(app)} type={type(app).__name__}", flush=True)
                # Injecter le middleware si pas déjà présent
                mw_list = list(app.middlewares)
                if upload_middleware not in mw_list:
                    # Insérer via _middlewares (avant freeze)
                    try:
                        app._middlewares = (upload_middleware,) + tuple(mw_list)
                        print("[Upload] Middleware injecté dans l'app servante.", flush=True)
                    except Exception as exc:
                        print(f"[Upload] Middleware injection failed: {exc}", flush=True)
                # Injecter aussi la route (belt-and-suspenders)
                try:
                    router = app.router
                    was_frozen = getattr(router, "_frozen", False)
                    if was_frozen:
                        router._frozen = False
                    for path in ("/upload", "/paraview/upload"):
                        try:
                            router.add_post(path, _registered_handler)
                            print(f"[Upload] Route {path} injectée dans l'app servante.", flush=True)
                        except Exception:
                            pass
                    if was_frozen:
                        router._frozen = was_frozen
                except Exception as exc:
                    print(f"[Upload] Route injection failed: {exc}", flush=True)
                return await _orig_runner_setup(self_runner, *args, **kwargs)

            _AppRunner.setup = _patched_runner_setup
            _AppRunner._fespp_orig_setup = _orig_runner_setup
            print("[Upload] Patch AppRunner.setup() installé.", flush=True)
    except Exception as exc:
        print(f"[Upload] Impossible de patcher AppRunner: {exc}", flush=True)

    return True


_registered_handler = None
