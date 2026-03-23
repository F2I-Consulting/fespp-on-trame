from trame.app import get_server
from paraview import simple as pvsimple
import time

server = get_server()
state = server.state
controller = server.controller

ETP_SOURCE_GUI_NAME = "ETP12Store"

class ETPConnector:
    """Manages ETP connection to OSDU servers for loading RESQML data.

    This class wraps the ParaView ETP1.2 Store reader to handle:
    - Connection to ETP servers (OSDU RDDMS)
    - Authentication (Bearer/Basic tokens)
    - Proxy connection (optional)
    - Dataspace selection
    - Data loading via selectors
    """

    def __init__(self):
        """Initialize ETP connector with default values."""
        # Create ETP source (ETP 1.2 Store)
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
        """Check if currently connected to an ETP server."""
        return self._is_connected

    # == GETTER ==
    def get_source(self):
        """Get the underlying ParaView ETP source."""
        return self._etp_source

    def get_representation(self):
        """Get the ParaView representation of the ETP source."""
        return pvsimple.GetRepresentation(proxy=self._etp_source, view=pvsimple.GetActiveView())

    # == CONNECTION METHODS ==
    def connect(self, etp_url: str, data_partition: str, token: str, token_type: str = "Bearer",
                proxy_url: str = None, proxy_token: str = None, proxy_token_type: str = "Bearer") -> bool:
        """Connect to an ETP server with authentication.

        Args:
            etp_url: ETP server URL (e.g., "wss://api.example.com/etp")
            data_partition: OSDU data partition ID (e.g., "osdu")
            token: Authentication token
            token_type: Token type - "Bearer" (0) or "Basic" (1), default "Bearer"
            proxy_url: Optional proxy URL
            proxy_token: Optional proxy token
            proxy_token_type: Proxy token type - "Bearer" or "Basic", default "Bearer"

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Convert token type string to integer value (0=Bearer, 1=Basic)
            etp_token_type_value = 0 if token_type == "Bearer" else 1
            proxy_token_type_value = 0 if proxy_token_type == "Bearer" else 1

            # Set ETP connection properties using .Set() method (ParaView style)
            props = {
                'ETPUrl': etp_url,
                'OSDUDataPartition': data_partition,
                'ETPTokenType': etp_token_type_value,  # Integer: 0=Bearer, 1=Basic
                'ETPToken': token,
                'Dataspaces': '',  # Initialize empty, will be populated after connection
            }

            # Set proxy connection if provided
            if proxy_url:
                props['ProxyUrl'] = proxy_url
                if proxy_token:
                    props['ProxyTokenType'] = proxy_token_type_value  # Integer: 0=Bearer, 1=Basic
                    props['ProxyToken'] = proxy_token

            # Apply all properties at once
            self._etp_source.Set(**props)

            # Push properties to the VTK object
            self._etp_source.UpdateVTKObjects()

            # Invoke the Connect command
            self._etp_source.Connect()

            # Update VTK objects and pipeline
            self._etp_source.UpdateVTKObjects()
            self._etp_source.UpdatePipeline()

            # Wait for connection to be established by monitoring ConnectionTag
            # ConnectionTag = 1 means not connected, ConnectionTag = 0 means connected
            max_wait = 30  # Maximum wait time in seconds
            start_time = time.time()

            while time.time() - start_time < max_wait:
                # Update property information to get latest values
                self._etp_source.UpdatePropertyInformation()

                # Get ConnectionTag value
                connection_tag = self._etp_source.GetProperty("ConnectionTag").GetElement(0)

                if connection_tag == 0:
                    # Connection established
                    self._is_connected = True
                    return True

                # Wait a bit before checking again
                time.sleep(0.5)

            # Timeout - connection not established
            print(f"Error: Connection timeout after {max_wait} seconds")
            self._is_connected = False
            return False

        except Exception as e:
            print(f"Error connecting to ETP server: {e}")
            self._is_connected = False
            return False

    def disconnect(self):
        """Disconnect from the ETP server."""
        if self._is_connected:
            try:
                self._etp_source.SMProxy.InvokeCommand("disconnectionClicked")
                self._etp_source.UpdateVTKObjects()
                self._etp_source.UpdatePipelineInformation()
                self._is_connected = False
            except Exception as e:
                print(f"Error disconnecting from ETP server: {e}")

    def set_dataspace(self, dataspace: str):
        """Select a dataspace to work with.

        Args:
            dataspace: Dataspace identifier (e.g., "eml:///")
        """
        if not self._is_connected:
            print("Not connected to ETP server. Cannot set dataspace.")
            return

        try:
            # Set the Dataspaces property
            self._etp_source.Set(Dataspaces=dataspace)

            # Try to call SetDataspaces directly on the client side object
            # This triggers repository.addDataspace() in C++
            try:
                client_obj = self._etp_source.GetClientSideObject()
                if hasattr(client_obj, 'SetDataspaces'):
                    client_obj.SetDataspaces(dataspace)
            except Exception as e:
                print(f"Warning: Could not call SetDataspaces: {e}")

            # Push properties to VTK and trigger pipeline update
            self._etp_source.UpdateVTKObjects()
            self._etp_source.MarkModified(self._etp_source)
            self._etp_source.UpdatePropertyInformation()

            # SetDataspaces() runs in a detached thread - wait for async data retrieval
            for _ in range(10):
                time.sleep(1)
                self._etp_source.UpdatePropertyInformation()
                data_assembly = self._etp_source.GetDataInformation().GetDataAssembly()
                if data_assembly and data_assembly.GetNumberOfChildren(0) > 0:
                    break

            self._etp_source.UpdateVTKObjects()
            self._etp_source.UpdatePipelineInformation()

            # Update the tree after selecting a dataspace
            controller.update_data_information()
        except Exception as e:
            print(f"Error setting dataspace: {e}")
            import traceback
            traceback.print_exc()

    def get_dataspaces(self):
        """Get available dataspaces from the connected ETP server.

        Returns:
            list: List of available dataspace identifiers
        """
        if not self._is_connected:
            return []

        try:
            # Wait a bit for dataspaces to be populated after connection
            time.sleep(1.0)

            # Force update from server to get latest information
            self._etp_source.UpdatePropertyInformation()

            # Use the new AllDataspaceNames StringVectorProperty exposed in FESPP
            dataspaces_prop = self._etp_source.GetProperty("AllDataspaceNames")
            if not dataspaces_prop:
                print("Error: AllDataspaceNames property not found")
                return []

            # Read all dataspace names from the StringVectorProperty
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
            print(f"Error getting dataspaces: {e}")
            import traceback
            traceback.print_exc()

        return []

    # == SHOW ==
    def show(self):
        """Show the ETP source in the active view."""
        pvsimple.Show(proxy=self._etp_source, view=pvsimple.GetActiveView())
