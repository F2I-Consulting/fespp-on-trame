"""HTTP multipart endpoint that receives EPC and HDF5 files and hands the
EPCs to the reader.

trame creates several aiohttp Application instances during startup, and the
one that ends up serving requests is not necessarily the first one created.
The route is therefore installed two ways: a middleware injected into every
Application at construction, and a patch of AppRunner.setup() that adds the
middleware and the route to the application actually being served.
"""
import asyncio
from pathlib import Path
from aiohttp import web as aiohttp_web


def _assembly_node_count(state) -> int:
    """Number of nodes in the tree's assembly XML, 0 when there is none.

    Every parse re-serializes the reader's assembly into `assembly_xml`, so
    the count before and after a read tells whether the file added anything
    the user can see (fesapi keeps one object per uuid, whichever file it
    came from)."""
    xml = getattr(state, "assembly_xml", None) or ""
    if not xml:
        return 0
    try:
        import xml.etree.ElementTree as ET
        return sum(1 for _ in ET.fromstring(xml).iter())
    except Exception:
        return 0


def record_file(state, name, size_mb, added, failure):
    """Record a file handed to the reader as one entry of `ui_loaded_files`.

    This is the "Files" list of Data health, and the session's only record
    of what it holds: since the reader never reads a name twice, the session
    must be able to say which names it was given. A file recorded again
    replaces its previous entry."""
    files = [dict(f) for f in (getattr(state, "ui_loaded_files", None) or [])]
    files = [f for f in files if f.get("name") != name]
    files.append({"name": name, "size_mb": round(float(size_mb), 1),
                  "objects": int(added), "failed": bool(failure)})
    state.ui_loaded_files = files


def _loaded_names(server) -> set:
    """The basenames this session has handed to the reader.

    The reader never re-reads a path it was given once (vtkEPCCollector
    keeps every path it tried, failed or not), so a second copy under the
    same name can only be read in a new session."""
    ctx = server.context
    names = getattr(ctx, "upload_loaded_names", None)
    if names is None:
        names = ctx.upload_loaded_names = set()
    return names


def _say(state, skipped, nothing_new, h5_only, epc_beside, read_notes):
    """Tell, on the amber snackbar, what the import did NOT do.

    A file already in the session is not read again, a file whose objects
    were all there already adds nothing, an .h5 on its own loads nothing,
    and the reader may have skipped objects of a file it did read. Nothing
    is shown when there is nothing to say."""
    notes = []
    if skipped:
        notes.append(", ".join(skipped)
                     + (" is" if len(skipped) == 1 else " are")
                     + " already imported in this session — not read again."
                     " To load a changed copy, start a new session (↻) and"
                     " import again; a different file needs another name.")
    if nothing_new:
        notes.append(", ".join(nothing_new) + " added nothing to the tree:"
                     " every object it shows was there already.")
    if epc_beside:
        notes.append(" ".join(
            f"{h5} now sits beside {epc} —" for h5, epc in epc_beside)
            + " tick a property to read its values (untick it first if it"
              " was ticked while the .h5 was missing).")
    elif h5_only:
        notes.append("Only an .h5 was imported: it is read with its .epc —"
                     " import that one too.")
    notes.extend(n for n in read_notes if n)
    if not notes:
        return
    state.empty_color_snackbar_text = " ".join(notes)
    state.empty_color_snackbar_visible = False
    state.empty_color_snackbar_visible = True


async def _receive(reader, received, loaded_names, skipped, h5_files, epc_paths):
    """The files of a multipart upload written to the temp dir, each path in
    `received` from its first byte; what is read and what is skipped sorted
    into the other lists."""
    from fespp_on_trame.engine.io.temp_dir import temp_dir
    async for field in reader:
        if not field.filename:
            continue
        # SECURITY: the multipart filename is fully client-controlled.
        # Reduce it to a bare basename (defusing `../` and absolute-path
        # escapes on both `/` and `\` separators) so a POST to /upload
        # can never create a file outside temp_dir. Extensions are NOT
        # filtered here (see the EPC/.h5 split below).
        filename = (field.filename or "").replace("\\", "/").split("/")[-1]
        if not filename or filename in (".", ".."):
            continue
        filepath = Path(temp_dir) / filename
        base = Path(temp_dir).resolve()
        if base != filepath.resolve() and base not in filepath.resolve().parents:
            print(f"[Upload] rejected path escape: {filename!r}", flush=True)
            continue
        print(f"[Upload] Receiving {filename}...", flush=True)
        # A name the reader already got is not read again whatever the
        # bytes (see _loaded_names); an .h5 already on disk may be open in
        # the reader and is not overwritten under it. A file on disk that
        # never reached the reader (an import that broke before its turn)
        # is replaced and read this time.
        if filepath.exists() and (
                filename in loaded_names
                or filename.lower().endswith(".h5")):
            print(f"[Upload] File {filename} already exists, ignored.", flush=True)
            skipped.append(filename)
            continue
        received.append(filepath)
        with open(filepath, "wb") as f:
            while True:
                chunk = await field.read_chunk(512 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        size_mb = filepath.stat().st_size / 1e6   # decimal MB, as the dialog shows sizes
        print(f"[Upload] {filename} saved ({size_mb:.1f} MB)", flush=True)
        # Everything that isn't an .h5 side-file is an EPC candidate:
        # fesapi judges by content, so an EPC renamed .txt still loads,
        # and genuine junk fails the parse and surfaces through the
        # load_error snackbar.
        if filename.lower().endswith(".h5"):
            h5_files.append(filename)
        else:
            epc_paths.append(str(filepath))


def register_upload_route(server) -> bool:
    """Serve POST /upload and /paraview/upload for this trame server.

    Must run before server.start(), so the aiohttp patches are in place
    when trame builds its application. They are applied once per process:
    a second call does not stack them."""
    from fespp_on_trame.engine.io.temp_dir import temp_dir

    async def handle_upload(request: aiohttp_web.Request) -> aiohttp_web.Response:
        state = server.state
        controller = server.controller
        # Reset so a repeated failed import fires the snackbar again
        # (trame drops a write of the value a key already holds).
        state.load_error = ""
        epc_paths = []
        skipped = []        # already handed to the reader: not read again
        nothing_new = []    # read, but every object it holds was there already
        h5_files = []       # side-files received: nothing to read on their own
        read_notes = []     # what the reader skipped in a file it did read
        loaded_names = _loaded_names(server)
        # what this request has put on disk: removed if it does not arrive
        # whole, so a file cut off is never read nor kept as "already there"
        received = []
        try:
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            reader = await request.multipart()
            try:
                await _receive(reader, received, loaded_names, skipped,
                               h5_files, epc_paths)
            except BaseException:
                for path in received:
                    try:
                        path.unlink()
                    except OSError as exc:
                        print(f"[Upload] {path.name} not removed: {exc}", flush=True)
                raise
            # The C++ EPC parse blocks the event loop for seconds on a large
            # file: raise the loading veil with the file's name and yield
            # once, so the flush reaches the client BEFORE the blocking call.
            # Without the sleep(0) the veil would only ship after it.
            try:
                for path in epc_paths:
                    name = Path(path).name
                    state.view_loading_message = f"Reading {name}…"
                    state.ui_loading = True
                    state.flush()
                    await asyncio.sleep(0)
                    before = _assembly_node_count(state)
                    loaded_names.add(name)
                    report = controller.load_epc_file(path) or {}
                    added = max(0, _assembly_node_count(state) - before)
                    try:
                        size_mb = Path(path).stat().st_size / 1e6
                    except OSError:
                        size_mb = 0.0
                    record_file(state, name, size_mb, added,
                                 report.get("failure"))
                    if report.get("failure"):
                        continue
                    read_notes.append(report.get("note") or "")
                    if added == 0:
                        nothing_new.append(name)
            finally:
                state.ui_loading = False
            # An .h5 arriving AFTER its .epc (read by an earlier import):
            # fesapi opens it lazily from the same directory, so the next
            # tick of a property reads it.
            this_batch = {Path(p).name for p in epc_paths}
            epc_beside = [
                (h5, Path(h5).stem + ".epc") for h5 in h5_files
                if Path(h5).stem + ".epc" in loaded_names - this_batch]
            _say(state, skipped, nothing_new,
                 h5_only=bool(h5_files) and not epc_paths and not skipped,
                 epc_beside=epc_beside, read_notes=read_notes)
            state.flush()
            # Return basenames only — never leak absolute server temp paths.
            return aiohttp_web.json_response(
                {"status": "ok", "epc_paths": [Path(p).name for p in epc_paths],
                 "skipped": skipped})
        except Exception as exc:
            state.ui_loading = False
            if isinstance(exc, ConnectionError) or request.transport is None \
                    or request.transport.is_closing():
                # the dialog's Cancel, or a lost connection: nobody to answer
                print("[Upload] stopped by the client: what it sent is removed", flush=True)
            else:
                print(f"[Upload] error: {exc}", flush=True)
            state.flush()
            # The reason travels in the response and the upload widget puts
            # it on the red snackbar. The widget must stay its only writer:
            # writing it to the state as well would let the widget's generic
            # "Upload failed: 500" overwrite it.
            return aiohttp_web.json_response(
                {"status": "error", "message": f"Import failed: {exc}"},
                status=500)

    register_route("POST", "/upload", handle_upload)
    register_route("POST", "/paraview/upload", handle_upload)
    return True


# ---------------------------------------------------------------------------
# The HTTP routes a session serves beside trame's websocket: the upload, and
# the document routes of engine/io/session_endpoint (/apply, /state) — one
# registry, one pair of aiohttp patches, whichever module registers first.
_ROUTES = {}        # (method, path) -> handler
_PATCHED = {"done": False}


def register_route(method, path, handler):
    """Serve `handler` at `method path` on this process's trame server.
    Must run before server.start(), so the aiohttp patches are in place
    when trame builds its application; the patches are applied once per
    process, the registry read at every request."""
    _ROUTES[(method.upper(), path)] = handler
    _install_patches()


def _install_patches():
    if _PATCHED["done"]:
        return
    _PATCHED["done"] = True

    @aiohttp_web.middleware
    async def routes_middleware(request: aiohttp_web.Request, handler):
        own = _ROUTES.get((request.method, request.path))
        if own is not None:
            return await own(request)
        return await handler(request)

    # Patch 1: every aiohttp.Application created from now on gets the
    # middleware injected as its first middleware.
    _orig_app_init = aiohttp_web.Application.__init__

    def _patched_app_init(self, *args, **kwargs):
        middlewares = list(kwargs.pop("middlewares", []) or [])
        middlewares.insert(0, routes_middleware)
        kwargs["middlewares"] = middlewares
        _orig_app_init(self, *args, **kwargs)

    aiohttp_web.Application.__init__ = _patched_app_init

    # Patch 2: AppRunner.setup() runs just before the app starts serving
    # requests. Intercepting it puts the middleware AND the routes on the
    # application actually served, whichever instance trame ended up
    # using (including one created before Patch 1 was in place).
    try:
        from aiohttp.web_runner import AppRunner as _AppRunner
        _orig_runner_setup = _AppRunner.setup

        async def _patched_runner_setup(self_runner, *args, **kwargs):
            app = self_runner.app
            mw_list = list(app.middlewares)
            if routes_middleware not in mw_list:
                # Insert via _middlewares: the public list is frozen at
                # this point and the underlying tuple is the only way in.
                try:
                    app._middlewares = (routes_middleware,) + tuple(mw_list)
                except Exception as exc:
                    print(f"[fespp] routes: middleware not inserted ({exc!r})", flush=True)
            # Belt-and-suspenders: also register the routes on the router,
            # briefly unfrozen (some configurations bypass middleware).
            try:
                router = app.router
                was_frozen = getattr(router, "_frozen", False)
                if was_frozen:
                    router._frozen = False
                for (method, path), own in _ROUTES.items():
                    try:
                        router.add_route(method, path, own)
                    except Exception as exc:
                        print(f"[fespp] routes: {method} {path} not on the router ({exc!r})", flush=True)
                if was_frozen:
                    router._frozen = was_frozen
            except Exception as exc:
                print(f"[fespp] routes: router not reached ({exc!r})", flush=True)
            return await _orig_runner_setup(self_runner, *args, **kwargs)

        _AppRunner.setup = _patched_runner_setup
    except Exception as exc:
        print(f"[fespp] routes: AppRunner not patched ({exc!r})", flush=True)


def resolve_upload_session_id(server) -> None:
    """Fill `state.upload_session_id` once the trame server is bound to
    its port.

    In the trame container each session process finds its own port in
    `/opt/trame/proxy-mapping.txt`; the session id on that line builds the
    per-session `/api/{sid}/upload` URL the client posts to. The lookup is
    best-effort: outside the container (no mapping file) the id stays empty
    and the client posts to a bare `/upload`."""
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
