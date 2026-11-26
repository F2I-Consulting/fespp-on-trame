"""GET /export?file=<name> — a file the session wrote for the reader to
keep (the velocity model's EPC and HDF5, engine/resqml_epc), served from
the session's own `exports` folder under the upload directory. A bare
name only: a path, or a name the folder does not hold, is a 404.

Registered on the same route registry as the upload (upload_endpoint)."""
import os

from aiohttp import web as aiohttp_web

from fespp_on_trame.engine.io.upload_endpoint import register_route


def register(server):
    async def handle_export(request):
        from fespp_on_trame.engine.io.temp_dir import temp_dir
        name = (request.query.get("file") or "").strip()
        if not name or name != os.path.basename(name) or name.startswith("."):
            return aiohttp_web.json_response({"error": "a file name is expected"}, status=404)
        path = os.path.join(temp_dir, "exports", name)
        if not os.path.isfile(path):
            return aiohttp_web.json_response({"error": f"{name} is not a file of this session"}, status=404)
        return aiohttp_web.FileResponse(path, headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Type": "application/octet-stream"})

    register_route("GET", "/export", handle_export)
