from trame.app import get_server
from paraview import simple as pvsimple
import time

server = get_server()
state = server.state
controller = server.controller

ETP_SOURCE_GUI_NAME = "ETP12Store"


class ETPConnector:
    """Wrapper around the ParaView ETP1.2 Store reader for OSDU RDDMS
    (RESQML) data. Handles authentication, optional proxy settings,
    dataspace selection and exposes the underlying source so the rest
    of the engine can drive selectors and rendering on it like the
    EPC collector."""

    def __init__(self):
        self._etp_source = pvsimple.ETP12Store(registrationName=ETP_SOURCE_GUI_NAME)
        self._representationType = None
        self._is_connected = False

        self.show()

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

    def connect(self, etp_url: str, data_partition: str, token: str, token_type: str = "Bearer",
                proxy_url: str = None, proxy_token: str = None, proxy_token_type: str = "Bearer") -> bool:
        """Open an authenticated ETP connection. token_type is "Bearer"
        (0 in the proxy) or "Basic" (1). Returns True on success.

        Connection is async on the C++ side: ConnectionTag flips to 0
        once the WebSocket is up, so we poll it for up to 30 s before
        timing out."""
        try:
            etp_token_type_value = 0 if token_type == "Bearer" else 1
            proxy_token_type_value = 0 if proxy_token_type == "Bearer" else 1

            props = {
                'ETPUrl': etp_url,
                'OSDUDataPartition': data_partition,
                'ETPTokenType': etp_token_type_value,
                'ETPToken': token,
                'Dataspaces': '',
            }

            if proxy_url:
                props['ProxyUrl'] = proxy_url
                if proxy_token:
                    props['ProxyTokenType'] = proxy_token_type_value
                    props['ProxyToken'] = proxy_token

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
                    return True

                time.sleep(0.5)

            self._is_connected = False
            return False

        except Exception as e:
            self._is_connected = False
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

    def set_dataspace(self, dataspace: str):
        """Select an ETP dataspace (e.g. "eml:///"). SetDataspaces
        runs in a detached thread on the C++ side, so we poll the data
        assembly until it gains a child or 10 s elapse."""
        if not self._is_connected:
            return

        try:
            self._etp_source.Set(Dataspaces=dataspace)

            try:
                client_obj = self._etp_source.GetClientSideObject()
                if hasattr(client_obj, 'SetDataspaces'):
                    client_obj.SetDataspaces(dataspace)
            except Exception as e:
                pass

            self._etp_source.UpdateVTKObjects()
            self._etp_source.MarkModified(self._etp_source)
            self._etp_source.UpdatePropertyInformation()

            for _ in range(10):
                time.sleep(1)
                self._etp_source.UpdatePropertyInformation()
                data_assembly = self._etp_source.GetDataInformation().GetDataAssembly()
                if data_assembly and data_assembly.GetNumberOfChildren(0) > 0:
                    break

            self._etp_source.UpdateVTKObjects()
            self._etp_source.UpdatePipelineInformation()

            controller.update_data_information()
        except Exception as e:
            pass

    def get_dataspaces(self):
        """Return the list of dataspace identifiers exposed by the
        FESPP ETP source through its AllDataspaceNames property."""
        if not self._is_connected:
            return []

        try:
            time.sleep(1.0)

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

            return dataspaces

        except Exception as e:
            pass

        return []

    def show(self):
        pvsimple.Show(proxy=self._etp_source, view=pvsimple.GetActiveView())
