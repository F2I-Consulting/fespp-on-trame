"""ETP 1.2 connection to an OSDU RDDMS server through the FESPP ETP reader."""
import asyncio
import os
import time

from trame.app import get_server
from paraview import simple as pvsimple

from fespp_on_trame.engine.etp_debug import etp_debug
from fespp_on_trame.engine.sources.reader_options import logs_as_lines


def _read_timeout_seconds():
    """FESPP_ETP_READ_TIMEOUT as a number of seconds, 0 when unset or not a
    number: the bound the plugin puts on one read over ETP."""
    raw = os.environ.get("FESPP_ETP_READ_TIMEOUT", "0") or "0"
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        print(f"[fespp] etp: FESPP_ETP_READ_TIMEOUT={raw!r} is not a number of seconds: no read bound", flush=True)
        return 0


# How the plugin reads the store, from the environment of this process to
# the properties of the ETP source: (variable, property, parser). The plugin
# used to read these variables itself; they are its properties now, and the
# container keeps setting them the same way.
_STORE_OPTIONS = (
    ("FESPP_ETP_LEAN", "LeanLoad", lambda v: 0 if v == "0" else 1),
    ("FESPP_ETP_LAZY_LEAVES", "LazyLeaves", lambda v: 1 if v == "1" else 0),
    ("FESPP_ETP_LAZY_SKELETON", "LazySkeleton", lambda v: 0 if v == "0" else 1),
    ("FESPP_ETP_PARALLEL", "ParallelRequests", lambda v: max(1, min(8, int(v)))),
    ("FESPP_ETP_PING_SECONDS", "PingSeconds", lambda v: max(0, int(v))),
    ("FESPP_ETP_VERBOSE", "Verbose", lambda v: 1 if v == "1" else 0),
    ("FESPP_ETP_CACHE", "DiskCache", lambda v: 1 if v == "1" else 0),
    ("FESPP_ETP_CACHE_DIR", "DiskCacheDirectory", lambda v: v),
    ("FESPP_ETP_CACHE_HOURS", "DiskCacheHours", lambda v: max(1, int(v))),
    ("FESPP_ETP_CACHE_MB", "DiskCacheMegabytes", lambda v: max(1, int(v))),
)


def _store_options(source):
    """The store-reading properties of the ETP source `source` that the
    environment sets, `{property: value}`: only the variables that are set,
    only the properties the loaded plugin has."""
    props = {}
    for variable, prop, parse in _STORE_OPTIONS:
        raw = os.environ.get(variable)
        if raw is None or raw == "" or source.GetProperty(prop) is None:
            continue
        try:
            props[prop] = parse(raw)
        except (TypeError, ValueError):
            print(f"[fespp] etp: {variable}={raw!r} is not a valid value for {prop}: left to the plugin's default", flush=True)
    return props

server = get_server()
state = server.state
controller = server.controller

ETP_SOURCE_GUI_NAME = "ETP12Store"


class ETPConnector:
    """Wrapper around the FESPP ETP 1.2 Store reader for OSDU RDDMS
    (RESQML) data.

    Handles authentication, optional proxy settings and dataspace
    selection, and exposes the underlying source so the rest of the
    engine can drive selectors and rendering on it like the EPC
    collector."""

    def __init__(self):
        self._etp_source = pvsimple.ETP12Store(registrationName=ETP_SOURCE_GUI_NAME)
        logs_as_lines(self._etp_source)
        self._representationType = None
        self._is_connected = False


    @property
    def representationType(self):
        return self._representationType

    @representationType.setter
    def representationType(self, value):
        if value != self._representationType:
            self._representationType = value

    @property
    def is_connected(self):
        return self._is_connected

    def get_source(self):
        return self._etp_source

    def get_representation(self):
        return pvsimple.GetRepresentation(proxy=self._etp_source, view=pvsimple.GetActiveView())

    async def connect(self, etp_url: str, data_partition: str, token: str, token_type: str = "Bearer",
                      proxy_url: str = None, proxy_token: str = None, proxy_token_type: str = "Bearer") -> bool:
        """Open an authenticated ETP connection. Returns True on success.

        token_type is "Bearer" (0 in the proxy) or "Basic" (1).

        Connection is async on the C++ side: ConnectionTag flips to 0
        once the WebSocket is up, so it is polled for up to 30 s before
        timing out. A coroutine on purpose: the polls sleep on the server
        loop (`asyncio.sleep`), so the other sessions of the process and
        this one's own state pushes keep running while a slow server
        answers; a `time.sleep` would block every session for the whole
        wait. ParaView is still driven from the one server thread."""
        try:
            etp_token_type_value = 0 if token_type == "Bearer" else 1
            proxy_token_type_value = 0 if proxy_token_type == "Bearer" else 1

            # Never reset 'Dataspaces' to '' here: on a reconnect ConnectionTag
            # is still 0 (the C++ side does not reset it when the connection
            # drops), so pushing '' fires the C++ SetDataspaces("") whose
            # detached progress-bar thread outlives its stack frame
            # (use-after-free, the process crashes).
            props = {
                'ETPUrl': etp_url,
                'OSDUDataPartition': data_partition,
                'ETPTokenType': etp_token_type_value,
                'ETPToken': token,
            }

            if proxy_url:
                props['ProxyUrl'] = proxy_url
                if proxy_token:
                    props['ProxyTokenType'] = proxy_token_type_value
                    props['ProxyToken'] = proxy_token
            # A bound on one pipeline read (FESPP_ETP_READ_TIMEOUT seconds,
            # 0 = none): past it the plugin closes the session, the read
            # fails instead of holding the server for ever, and the
            # application reconnects. Only a plugin that has the property.
            timeout = _read_timeout_seconds()
            if timeout and self._etp_source.GetProperty("ArrayReadTimeout") is not None:
                props['ArrayReadTimeout'] = timeout
            props.update(_store_options(self._etp_source))

            self._etp_source.Set(**props)

            self._etp_source.UpdateVTKObjects()

            self._etp_source.Connect()

            self._etp_source.UpdateVTKObjects()
            self._etp_source.UpdatePipeline()

            # Poll ConnectionTag: 1 = not connected, 0 = connected.
            max_wait = 30
            start_time = time.time()

            while time.time() - start_time < max_wait:
                self._etp_source.UpdatePropertyInformation()

                connection_tag = self._etp_source.GetProperty("ConnectionTag").GetElement(0)

                if connection_tag == 0:
                    self._is_connected = True
                    etp_debug(f"connect({etp_url!r}): OK in {time.time() - start_time:.2f}s")
                    return True

                await asyncio.sleep(0.5)

            self._is_connected = False
            etp_debug(f"connect({etp_url!r}): TIMEOUT after {max_wait}s")
            return False

        except Exception as e:
            self._is_connected = False
            etp_debug(f"connect({etp_url!r}): EXCEPTION {type(e).__name__}: {e}")
            return False

    def disconnect(self):
        if self._is_connected:
            try:
                self._etp_source.SMProxy.InvokeCommand("disconnectionClicked")
                self._etp_source.UpdateVTKObjects()
                self._etp_source.UpdatePipelineInformation()
                self._is_connected = False
            except Exception as e:
                pass

    def assembly_child_count(self) -> int:
        """Number of children of the pipeline OUTPUT's assembly root.

        vtkETPSource is NOT Python-wrapped (the client-side object degrades
        to its wrapped base vtkPartitionedDataSetCollectionAlgorithm, which
        has no GetAssembly), so the output PDC, refreshed by UpdatePipeline,
        is the only readable surface. Relies on vtkETPSource::RequestData
        producing the assembly even when no selector is set, like
        vtkEPCCollector."""
        try:
            client_obj = self._etp_source.GetClientSideObject()
            output = client_obj.GetOutput() if hasattr(client_obj, "GetOutput") else None
            assembly = output.GetDataAssembly() if output is not None else None
            return assembly.GetNumberOfChildren(0) if assembly is not None else 0
        except Exception:
            return 0

    async def set_dataspace(self, dataspace: str) -> bool:
        """Select an ETP dataspace (e.g. "eml:///").

        The C++ SetDataspaces fetches the dataspace content into the
        repository synchronously (only its progress bar is threaded), so on
        success the live assembly has children as soon as the call returns.

        The command is fired with a forced property update, deliberately:
        - a plain SM property push only fires the command on a CHANGED value
          (a reconnect retry re-sends the same name, so it would be a silent
          no-op);
        - a Set(Dataspaces='') "reset" is lethal: SetDataspaces("") returns
          at once and its detached progress-bar thread outlives the stack
          frame it captures by reference (use-after-free, access violation).

        Returns True when the assembly gained content. The caller decides
        how to react to False: the server may have silently closed the
        WebSocket, in which case the fetch yields nothing."""
        etp_debug(f"set_dataspace({dataspace!r}) connected={self._is_connected}")
        if not self._is_connected:
            return False

        try:
            # vtkETPSource is not Python-wrapped, so everything goes through
            # the ServerManager layer. UpdateProperty(name, force=1) fires the
            # XML command even when the value is unchanged; a plain
            # UpdateVTKObjects would silently skip a reconnect retry that
            # re-sends the same dataspace name.
            etp_debug(f"set_dataspace: children before={self.assembly_child_count()}")
            # The value is SET on the property without a push, then pushed
            # ONCE, forced. `Set(Dataspaces=...)` pushed by itself on a changed
            # value, and the forced push below fired the command a second
            # time: every first load of a dataspace discovered, fetched and
            # deserialized it TWICE (measured 2026-10-10 on the plugin's own
            # timing line — two "[fespp] etp load" lines per load).
            self._etp_source.SMProxy.GetProperty("Dataspaces").SetElement(0, dataspace)
            t0 = time.time()
            self._etp_source.SMProxy.UpdateProperty("Dataspaces", 1)
            etp_debug(f"set_dataspace: SetDataspaces command fired, "
                      f"{time.time() - t0:.2f}s")
            # The C++ fetch filled the repository, but SetDataspaces does not
            # bump the VTK MTime (only AssemblyTag++), so UpdatePipeline
            # alone serves a CACHED pass and the output keeps 0 children.
            # vtkObject::Modified comes from the wrapped base class: call it
            # on the client-side object to force a real RequestData.
            count = 0
            for attempt in range(2):
                self._etp_source.GetClientSideObject().Modified()
                self._etp_source.UpdatePipeline()
                count = self.assembly_child_count()
                if count > 0:
                    break
                await asyncio.sleep(0.5)
            etp_debug(f"set_dataspace: final children={count}")
            if count == 0:
                return False
            controller.update_data_information()
            return True
        except Exception as exc:
            etp_debug(f"set_dataspace: EXCEPTION {type(exc).__name__}: {exc}")
            return False

    async def get_dataspaces(self):
        """Return the dataspace identifiers exposed by the FESPP ETP source
        through its AllDataspaceNames property.

        The server enumerates them shortly after the connection, so the read
        first waits one second, on the event loop rather than the thread."""
        if not self._is_connected:
            return []

        try:
            await asyncio.sleep(1.0)

            self._etp_source.UpdatePropertyInformation()

            dataspaces_prop = self._etp_source.GetProperty("AllDataspaceNames")
            if not dataspaces_prop:
                return []

            num_elements = dataspaces_prop.GetNumberOfElements()

            if num_elements == 0:
                return []

            dataspaces = []
            for i in range(num_elements):
                dataspace = dataspaces_prop.GetElement(i)
                if dataspace:
                    dataspaces.append(dataspace)

            etp_debug(f"get_dataspaces: {dataspaces}")
            return dataspaces

        except Exception as e:
            pass

        return []
