"""HTTP diagnostics for the ETP path: ``GET /debug/etp``, off unless
``FESPP_DEBUG_ROUTES=1``.

The ETP flow only runs in a browser session holding the user's OSDU token,
so its server-side state is out of reach of a headless probe. This endpoint
dumps the state of the live session (ETP source output, partition layout,
assembly, per-representation extractors, views) so a developer can read it
with curl after driving the session in a browser.

Plain text, read-only, and with no authentication of its own: whoever
reaches the session's port reads the dump. So app/boot goes through
`register_debug_routes`, which registers the route only when the server's
environment sets ``FESPP_DEBUG_ROUTES=1``; a served instance never answers
it by default.
"""
import os

from aiohttp import web as aiohttp_web

SWITCH = "FESPP_DEBUG_ROUTES"


def debug_routes_enabled(environ=None) -> bool:
    """Whether the diagnostics routes are asked for: ``FESPP_DEBUG_ROUTES=1``,
    nothing else."""
    env = os.environ if environ is None else environ
    return (env.get(SWITCH) or "").strip() == "1"


def register_debug_routes(server, environ=None) -> bool:
    """Register ``GET /debug/etp`` when `debug_routes_enabled` says so;
    return whether it did."""
    if not debug_routes_enabled(environ):
        return False
    register_etp_debug_route(server)
    return True


def register_etp_debug_route(server) -> None:
    """Add ``GET /debug/etp`` to the wslink aiohttp app once the server is
    bound, whatever the environment says (`register_debug_routes` is the
    gated door); a registration failure is logged, never raised."""
    @server.controller.add("on_server_bind")
    def _bind(wslink_server, **_):
        try:
            wslink_server.app.add_routes(
                [aiohttp_web.get("/debug/etp", _make_handler(server))])
            # a diagnostics route that answers must say so in the log
            print("[etp-debug] GET /debug/etp is served (diagnostics, no"
                  " authentication)", flush=True)
        except Exception as exc:
            print("[etp-debug] route registration failed:", exc, flush=True)


def _make_handler(server):
    """The request handler; a failing dump answers with its traceback."""
    async def handle(_request):
        try:
            text = _dump(server)
        except Exception as exc:
            import traceback
            text = f"DUMP ERROR: {exc!r}\n{traceback.format_exc()}"
        return aiohttp_web.Response(text=text, content_type="text/plain")
    return handle


def _dump(server):
    """The session's ETP source, IJK extractors, extract blocks and render
    views, one fact per line."""
    from paraview import simple as pvsimple
    lines = []
    ctx = server.context

    etp = getattr(ctx, "etp_connector", None)
    lines.append(f"etp_connected={getattr(etp, 'is_connected', None)}")
    if etp is not None and etp.is_connected:
        src = etp.get_source()
        di = src.GetDataInformation()
        lines.append(f"ETP source: cells={di.GetNumberOfCells()}")
        cso = src.GetClientSideObject()
        out = cso.GetOutput() if hasattr(cso, "GetOutput") else None
        if out is not None:
            try:
                from paraview.vtk.vtkCommonDataModel import vtkCompositeDataSet
                n = out.GetNumberOfPartitionedDataSets()
                lines.append(f"output PDC: n_partitioned={n}")
                for i in range(n):
                    pds = out.GetPartitionedDataSet(i)
                    meta = out.GetMetaData(i)
                    name = (meta.Get(vtkCompositeDataSet.NAME())
                            if meta is not None and meta.Has(vtkCompositeDataSet.NAME())
                            else "?")
                    nparts = pds.GetNumberOfPartitions() if pds is not None else 0
                    first = pds.GetPartition(0) if nparts else None
                    lines.append(
                        f"  pds[{i}] name={name} partitions={nparts} "
                        f"first={type(first).__name__ if first is not None else None} "
                        f"cells={first.GetNumberOfCells() if first is not None else 0}")
            except Exception as exc:
                lines.append(f"  partition dump failed: {exc!r}")
            asm = out.GetDataAssembly()
            if asm is not None:
                from paraview.vtk.vtkCommonCore import vtkIndent
                lines.append("output assembly XML:")
                lines.append(asm.SerializeToXML(vtkIndent()))
            else:
                lines.append("output assembly: None")

    src_reg = getattr(ctx, "source_registry", None)
    if src_reg is not None:
        for p in src_reg.ijk_paths():
            ijk = src_reg.get_ijk_grid(p)
            ext = getattr(ijk, "_src_extract_init", None)
            if ext is None:
                lines.append(f"ijk {p}: no extractor")
                continue
            try:
                d = ext.GetDataInformation()
                lines.append(
                    f"ijk {p}: extractor={ext.SMProxy.GetLogNameOrDefault()} "
                    f"cells={d.GetNumberOfCells()} "
                    f"bounds={[round(b, 1) for b in d.GetBounds()]}")
            except Exception as exc:
                lines.append(f"ijk {p}: extractor introspect failed {exc!r}")
        for p in src_reg.extract_block_paths():
            eb = src_reg.get_extract_block(p)
            s = getattr(eb, "source", None)
            if s is not None:
                d = s.GetDataInformation()
                lines.append(f"eb {p}: cells={d.GetNumberOfCells()}")

    for i, v in enumerate(pvsimple.GetRenderViews()):
        vis = [r for r in v.Representations if getattr(r, "Visibility", 0)]
        lines.append(
            f"view[{i}]: reps={len(v.Representations)} visible={len(vis)} "
            f"cam={[round(c, 1) for c in v.CameraPosition]}")
        for r in vis:
            try:
                inp = r.Input
                d = inp.GetDataInformation()
                lines.append(
                    f"  vis: {inp.SMProxy.GetLogNameOrDefault()} "
                    f"cells={d.GetNumberOfCells()} "
                    f"bounds={[round(b, 1) for b in d.GetBounds()]}")
            except Exception as exc:
                lines.append(f"  vis: introspect failed {exc!r}")
    return "\n".join(lines)
