"""ETP / OSDU connection steps + tree-assembly refresh.

Three connection steps (`connect_to_etp`, `select_etp_dataspace`,
`force_etp_refresh`) wrap the `ETPConnector`'s lifecycle, and one shared
`update_data_information` re-parses the live vtkDataAssembly into the
engine's `Tree` (for both the Collector and the ETPConnector: the data
source is whichever one is connected). `credentials`, `token_expiry` and
`said_empty` are the pure helpers around them.

`force_etp_refresh` re-runs UpdatePipelineInformation twice with a
short sleep in between to give the ETP reader a chance to surface
late-arriving entries (the server may defer dataspace enumeration to a
background task).

The three connection steps are coroutines: their waits (a connection
polled for up to 30 s, a dataspace fetched in two attempts, the dataspace
list a second after the connection) sleep on the server loop instead of
the server thread, so a slow OSDU server does not freeze the other
sessions of the process. ParaView is still called from the one server
thread."""
import asyncio
import base64
import json
import sys


def credentials(payload):
    """(token, token_type) for the ETP connection, from the OSDU / ETP dialog:
    a Bearer token as typed, or Basic: "user:password" in base64, which is
    what FESPP puts after "Basic " in the Authorization header
    (vtkETPSource: ETPTokenType + " " + ETPToken). (None, None) when
    something is missing. The password is neither kept nor logged here."""
    payload = payload or {}
    auth = str(payload.get("auth") or "Bearer").strip().lower()
    if auth == "basic":
        user = str(payload.get("user") or "").strip()
        password = str(payload.get("password") or "")   # a password may start or end with a space
        if not user or not password:
            return None, None
        return base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii"), "Basic"
    token = str(payload.get("token") or "").strip()
    return (token, "Bearer") if token else (None, None)


def token_expiry(token, token_type="Bearer"):
    """When a Bearer token stops being accepted: the `exp` claim of a JWT
    (seconds since the epoch), read WITHOUT checking the signature: the
    server does that; this only warns the reader in time. None for Basic, or
    a token that is not a JWT. The token itself is neither kept nor logged.

    Why it matters: an Entra ID token lives about an hour, and past it the
    ETP server drops the session; fetpapi then retries ten times, and every
    object still to read waits its own delay, so a load that outlives the
    token looks endless instead of failing."""
    if str(token_type or "").lower() != "bearer" or not token:
        return None
    parts = str(token).split(".")
    if len(parts) != 3:
        return None
    body = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
        exp = claims.get("exp") if isinstance(claims, dict) else None
    except (ValueError, UnicodeError):
        # an opaque token is legitimate, but no warning can come before it
        # ends: say so in the session log (never the token itself)
        print("[fespp] etp: the token is not a readable JWT, its end is unknown",
              file=sys.stderr, flush=True)
        return None
    return int(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None


def said_empty(messages, dataspace):
    """FESPP's word that `dataspace` delivered nothing ("There is no
    dataobject in the dataspace : <uri>") among captured VTK messages
    (engine/vtk_log). This message, not the tree's children, decides a
    load: a tree that already holds another dataspace has children anyway,
    so a dataspace read over a dead session would otherwise pass as
    loaded."""
    for m in messages or ():
        text = str((m or {}).get("text") or "")
        if "There is no dataobject in the dataspace" in text and dataspace in text:
            return True
    return False


async def connect_to_etp(state, etp_connector, etp_url, data_partition, token,
                         token_type="Bearer", proxy_url=None, proxy_token=None,
                         proxy_token_type="Bearer"):
    """Connect the ETPConnector, then publish the server's dataspaces in
    `state.etp_dataspaces` (an empty list when the connection fails)."""
    success = await etp_connector.connect(
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
        state.etp_dataspaces = await etp_connector.get_dataspaces()
    else:
        state.etp_dataspaces = []


async def select_etp_dataspace(etp_connector, dataspace):
    """Returns True when the dataspace actually delivered content (the
    server can silently close an idle WebSocket, in which case the fetch
    yields nothing and the caller should reconnect and retry)."""
    if etp_connector.is_connected:
        return await etp_connector.set_dataspace(dataspace)
    return False


async def force_etp_refresh(state, etp_connector, collector, tree, active=None):
    """Re-read the ETP source's pipeline information twice, half a second
    apart, then refresh the tree (see the module docstring for why twice)."""
    if not etp_connector.is_connected:
        return
    etp_source = etp_connector.get_source()
    etp_source.UpdatePipelineInformation()
    await asyncio.sleep(0.5)
    etp_source.UpdatePipelineInformation()
    update_data_information(etp_connector, collector, tree, active)


def update_data_information(etp_connector, collector, tree, active=None):
    """Re-parse the live vtkDataAssembly into the engine's `Tree`
    (which the trame state vars `ui_subtree_*` are driven from).

    Read off the pipeline OUTPUT: FESPP's readers are ClientServer-wrapped,
    never Python-wrapped, so `GetClientSideObject()` hands them back degraded
    to the wrapped base class, where `GetLiveAssembly` / `GetAssembly` are
    not reachable (engine/repo_query is the channel that does cross that
    gap)."""
    if active is not None:
        # the session's source: the readers that hold data, joined (a file
        # read or a dataspace loaded may have brought a second one in)
        active.sync()
        source = active.get_source()
    else:
        source = etp_connector.get_source() if etp_connector.is_connected else collector.get_source()
    client_side_object = source.GetClientSideObject()
    assembly = None
    if hasattr(client_side_object, "GetOutput"):
        output = client_side_object.GetOutput()
        if hasattr(output, "GetDataAssembly"):
            assembly = output.GetDataAssembly()
    if assembly is not None:
        # the plugin's own enum table, so a node's numeric typeCode can be
        # resolved without this side hard-coding what the numbers mean
        try:
            from fespp_on_trame.engine import repo_query
            tree.set_type_enum(repo_query.type_enum(source))
        except Exception:
            pass
        tree.set_tree(assembly)
