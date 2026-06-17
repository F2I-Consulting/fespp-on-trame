"""ETP / OSDU connection + tree-assembly refresh — extracted from
`boot.initialize_fespp_engine`.

Three controller methods wrap the `ETPConnector`'s connection
lifecycle plus one shared `update_data_information` that re-parses
the live vtkDataAssembly into the per-tab `state.ui_subtree_*` lists
(works for both Collector and ETPConnector — the data-source choice
depends on which one is currently connected).

`force_etp_refresh` re-runs UpdatePipelineInformation twice with a
short sleep in between to give the ETP reader a chance to surface
late-arriving entries (observed empirically when the server side
deferred dataspace enumeration to a background task)."""
import time as _time

from paraview import simple as pvsimple


def connect_to_etp(state, etp_connector, etp_url, data_partition, token,
                   token_type="Bearer", proxy_url=None, proxy_token=None,
                   proxy_token_type="Bearer"):
    success = etp_connector.connect(
        etp_url=etp_url,
        data_partition=data_partition,
        token=token,
        token_type=token_type,
        proxy_url=proxy_url,
        proxy_token=proxy_token,
        proxy_token_type=proxy_token_type,
    )
    if success:
        print(f"Connected to ETP server: {etp_url}")
        state.etp_dataspaces = etp_connector.get_dataspaces()
    else:
        print(f"Failed to connect to ETP server: {etp_url}")
        state.etp_dataspaces = []


def select_etp_dataspace(etp_connector, dataspace):
    if etp_connector.is_connected:
        etp_connector.set_dataspace(dataspace)
    else:
        print("Error: Not connected to ETP server")


def force_etp_refresh(state, etp_connector, collector, tree):
    if not etp_connector.is_connected:
        print("Error: Not connected to ETP server")
        return
    etp_source = etp_connector.get_source()
    etp_source.UpdatePipelineInformation()
    _time.sleep(0.5)
    etp_source.UpdatePipelineInformation()
    update_data_information(etp_connector, collector, tree)


def update_data_information(etp_connector, collector, tree):
    """Re-parse the live vtkDataAssembly into the engine's `Tree`
    (which the trame state vars `ui_subtree_*` are driven from).

    Prefer `GetLiveAssembly()` — it returns the repository's
    `_output->GetDataAssembly()` directly. After `rebuildAssembly()`
    (TreeHierarchyMode change) the live assembly is mutated without
    re-running RequestData, so the pipeline output's deep copy is
    still the previous one. `GetAssembly()` exists on the parent
    class but isn't always exposed to Python through the override;
    `GetLiveAssembly` is unique and always wrapped."""
    source = etp_connector.get_source() if etp_connector.is_connected else collector.get_source()
    client_side_object = source.GetClientSideObject()
    assembly = None
    for getter_name in ("GetLiveAssembly", "GetAssembly"):
        if hasattr(client_side_object, getter_name):
            try:
                assembly = getattr(client_side_object, getter_name)()
                if assembly is not None:
                    break
            except Exception:
                assembly = None
    if assembly is None and hasattr(client_side_object, "GetOutput"):
        output = client_side_object.GetOutput()
        if hasattr(output, "GetDataAssembly"):
            assembly = output.GetDataAssembly()
    if assembly is not None:
        tree.set_tree(assembly)
