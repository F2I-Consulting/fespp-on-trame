"""OSDU / ETP (upload widget "OSDU" tab)
Coroutines: ParaView proxies are not thread-safe, so every call stays
on the server thread, but the waits (connect polled up to 30 s, the
dataspace fetched in two attempts) sleep on the loop, so a slow server
never freezes the other sessions of the process. trame awaits a
trigger's coroutine. The flush before the work pushes the "in flight"
state first.
Last successful credentials, kept in session memory only: OSDU servers
(ADME notably) close idle WebSockets, and vtkETPSource's ConnectionTag
never reflects the drop. The only reliable signal is a select that
yields nothing, at which point etp_select reconnects and retries once.

(Moved out of app/boot, overhaul slice 10.)"""
import asyncio
import sys
import time
from fespp_on_trame.engine import repo_query
from fespp_on_trame.engine import etp
from fespp_on_trame.engine.vtk_log import capture_vtk_messages


def widget_bindings(controller):
    """The attributes the upload door's two ETP / OSDU forms share (the
    import dialog's OSDU tab, a session's prefilled form): each binds the
    state key or the controller of its own name."""
    return dict(
        etp_connected=("etp_connected", False),
        etp_connecting=("etp_connecting", False),
        etp_step=("etp_step", ""),
        etp_dataspaces=("etp_dataspaces", []),
        etp_status=("etp_status", ""),
        etp_connect=(controller.etp_connect, "[$event]"),
        etp_select=(controller.etp_select, "[$event]"),
        etp_disconnect=controller.etp_disconnect,
        osdu_explorer=("osdu_explorer", {}),
        osdu_scan=controller.osdu_scan,
        osdu_search=(controller.osdu_search, "[$event]"),
        osdu_find=(controller.osdu_find, "[$event]"),
        osdu_kinds=(controller.osdu_kinds, "[$event]"),
    )


def register(core, *, _osdu_list, _say):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (_conn, _etp_creds, _etp_do_connect, _etp_lost, _lost_next, _plugin_rebinds, _token_expired, _watch_session)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    etp_connector = core.etp_connector
    # --- OSDU / ETP (upload widget "OSDU" tab) ---
    # Coroutines: ParaView proxies are not thread-safe, so every call stays
    # on the server thread, but the waits (connect polled up to 30 s, the
    # dataspace fetched in two attempts) sleep on the loop, so a slow server
    # never freezes the other sessions of the process. trame awaits a
    # trigger's coroutine. The flush before the work pushes the "in flight"
    # state first.
    #
    # Last successful credentials, kept in session memory only: OSDU servers
    # (ADME notably) close idle WebSockets, and vtkETPSource's ConnectionTag
    # never reflects the drop. The only reliable signal is a select that
    # yields nothing, at which point etp_select reconnects and retries once.
    _etp_creds = {}

    def _token_expired():
        """The Bearer token of the connection is past its end (engine/etp
        token_expiry): the server refuses everything from then on."""
        exp = _etp_creds.get("expiry")
        return bool(exp) and time.time() >= exp

    def _token_left_text(exp):
        """"57 min", "1 h 12 min": how long the token has left, said
        without a clock time — the server does not know the reader's zone."""
        minutes = max(0, int((exp - time.time()) // 60))
        return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"

    # The ETP session can die under the application: the server closes the
    # socket, fetpapi's own reconnection is refused, and from then on every
    # request fails; fetpapi says so on stderr only (engine/vtk_log
    # ETP_LOST). `_conn["lost_mark"]` is its count at the connection;
    # `_conn["gen"]` numbers the connections, so a watcher of an older one
    # stops.
    _conn = {"gen": 0, "lost_mark": 0, "lost_said": False}

    def _etp_lost():
        """The ETP session of this connection is gone (fetpapi said so)."""
        from fespp_on_trame.engine import vtk_log as _vl
        return etp_connector.is_connected and _vl.ETP_LOST["count"] > _conn["lost_mark"]

    # What the reader can do once the session is gone. On an OLD plugin a
    # new connection in the same page is NOT offered: FESPP's objects
    # already read keep a pointer to the session that read them (fetpapi
    # FesapiHdfProxy), so a new session leaves them pointing at a dead one:
    # a crash as soon as one of their arrays is read. A new page, resumed
    # from the Session button, reads everything again through one live
    # session. A plugin of 2026-10-10 or later REBINDS those proxies to the
    # new session (ResqmlDataRepositoryToVtkPartitionedDataSetCollection::
    # connect), so the same page reconnects — by itself when the token is
    # still valid (_watch_session), else from the Import dialog.
    _LOST_NEXT = ("What is shown stays; to read more, reload the page and resume"
                  " from the Session button, which keeps the last state.")

    def _plugin_rebinds():
        """This plugin build rebinds the HDF proxies of the objects already
        read to a new session: the inventory property dates from the same
        build, so it is the probe (hasattr is blind on these proxies)."""
        try:
            return repo_query.has_inventory(etp_connector.get_source())
        except Exception as exc:
            print(f"[fespp] etp: the plugin probe failed ({exc!r}): read as an old plugin", flush=True)
            return False

    def _lost_next():
        if _plugin_rebinds():
            return ("What is shown stays; connect again from the Import dialog (a fresh"
                    " token if the old one expired): what was read is kept and reads on.")
        return _LOST_NEXT

    def _store_closed():
        """Why nothing more can be read from the store, "" while it can: the
        reader disconnected, the token ended or the server closed the
        session. What was read stays in the tree and in the views; a read
        asked of a closed store would wait on a session that is gone."""
        if not etp_connector.is_connected:
            return ("Disconnected from the OSDU server: what is shown stays; connect again"
                    " from the Import dialog to read more.")
        if _token_expired():
            return ("The OSDU token has expired: nothing more can be read from the server."
                    " Connect again with a fresh token.")
        if _etp_lost():
            return "The connection to the OSDU server was lost. " + _lost_next()
        return ""

    core.ctx.store_closed = _store_closed

    async def _reconnect_after_loss(exp):
        """A new session in the same page, with the credentials in memory,
        once the plugin is known to rebind what was read. True when the
        server is back."""
        state.etp_status = "The connection to the server was lost: reconnecting …"
        state.flush()
        try:
            etp_connector.disconnect()
        except Exception as exc:
            print(f"[fespp] etp: disconnect before the reconnection failed: {exc}", flush=True)
        ok = await _etp_do_connect(_etp_creds["url"], _etp_creds.get("partition"),
                                   _etp_creds["token"], _etp_creds.get("token_type", "Bearer"))
        if ok:
            state.etp_status = "Reconnected to the server (it had closed the session); what was read is kept."
            _say("The OSDU server had closed the session: reconnected, what was read is kept.")
            state.flush()
            asyncio.ensure_future(_watch_session(_conn["gen"], exp))
        return ok

    async def _watch_session(gen, exp):
        """Tell the reader when the connection or its token ends.

        The loss of the connection is said within two seconds; the token's
        end five minutes before, and again when it has passed. Past either,
        every read fails: the reader must hear it from the application, not
        guess it from a load that never ends."""
        warned = False
        while _conn["gen"] == gen and etp_connector.is_connected:
            if _etp_lost() and not _conn["lost_said"]:
                _conn["lost_said"] = True
                from fespp_on_trame.engine import vtk_log as _vl
                print(f"[fespp] etp: session lost ({_vl.ETP_LOST['line']})",
                      file=sys.stderr, flush=True)
                # the plugin rebinds what was read and the token still
                # holds: a new session at once, while nothing is in flight
                # (a load or a stepped read handles its own loss)
                if (_plugin_rebinds() and _etp_creds and not _token_expired()
                        and not state.etp_connecting
                        and not (state.ui_load_progress or {}).get("running")):
                    if await _reconnect_after_loss(exp):
                        return
                    state.etp_status = ("The connection to the server was lost and could not be"
                                        " reopened. " + _lost_next())
                    _say("The connection to the OSDU server was lost and could not be reopened. "
                         + _lost_next())
                    state.flush()
                    return
                state.etp_status = "The connection to the server was lost. " + _lost_next()
                _say("The connection to the OSDU server was lost (the server closed it). "
                     + _lost_next())
                state.flush()
            if exp:
                left = exp - time.time()
                if left <= 0:
                    state.etp_status = ("The token has expired: connect again with a"
                                        " fresh one to keep reading from the server.")
                    _say("The OSDU token has expired: nothing more can be read from the"
                         " server. Connect again with a fresh token.")
                    state.flush()
                    return
                if left <= 300 and not warned:
                    warned = True
                    _say(f"The OSDU token expires in {_token_left_text(exp)}: connect again"
                         " with a fresh one to keep reading from the server.")
                    state.flush()
            await asyncio.sleep(2.0)

    async def _etp_do_connect(url, partition, token, token_type="Bearer"):
        try:
            with capture_vtk_messages(state):
                await etp.connect_to_etp(state, etp_connector, url, partition, token,
                                         token_type=token_type)
        except Exception as exc:
            print("[fespp] etp_connect error:", exc, flush=True)
        state.etp_connected = etp_connector.is_connected
        if state.etp_connected:
            # a new session: what fetpapi said of the previous one is past
            from fespp_on_trame.engine import vtk_log as _vl
            _conn["gen"] += 1
            _conn["lost_mark"] = _vl.ETP_LOST["count"]
            _conn["lost_said"] = False
        return state.etp_connected

    @controller.set("etp_connect")
    async def etp_connect(payload):
        payload = payload or {}
        url = (payload.get("url") or "").strip()
        partition = (payload.get("partition") or "").strip()
        token, token_type = etp.credentials(payload)
        if not url or not token:
            return
        state.etp_connecting = True
        state.etp_status = f"Connecting to {url} …"
        # the steps of the connection, on the Connect button (the PO's
        # manager, 13/10: "on voit juste Connecting"): the ETP session
        # first (TLS, RequestSession, the store's dataspace names: a few
        # seconds on a hosted store), then the REST list the explorer
        # starts from. The page adds "(waiting for server…)" by itself
        # when a step lasts. A flush and a turn of the loop: the step must
        # reach the browser before the plugin's call holds the loop.
        state.etp_step = "Requesting new ETP session"
        state.flush()
        await asyncio.sleep(0.05)
        t_conn = time.monotonic()
        try:
            connected = await _etp_do_connect(url, partition, token, token_type)
        finally:
            state.etp_connecting = False
        if connected:
            exp = etp.token_expiry(token, token_type)
            _etp_creds.update(url=url, partition=partition, token=token, token_type=token_type,
                              expiry=exp)
            state.ui_etp_endpoint = {"url": url, "partition": partition}
            state.etp_status = (
                f"Connected — {len(state.etp_dataspaces or [])} dataspace(s)"
                + (f" · token valid for {_token_left_text(exp)}" if exp else ""))
            if exp:
                # the end of the token only, in UTC: the token itself never
                # reaches a log
                print(f"[fespp] etp: token valid until "
                      f"{time.strftime('%H:%M', time.gmtime(exp))} UTC "
                      f"({_token_left_text(exp)})", file=sys.stderr, flush=True)
            asyncio.ensure_future(_watch_session(_conn["gen"], exp))
            state.etp_step = "Reading the dataspace list"
            state.flush()
            t_list = time.monotonic()
            try:
                await _osdu_list()
            finally:
                state.etp_step = ""
            print(f"[fespp] etp connect: session in {t_list - t_conn:.1f} s, dataspace list in "
                  f"{time.monotonic() - t_list:.1f} s", file=sys.stderr, flush=True)
        else:
            state.etp_step = ""
            state.etp_status = ("Connection failed (timeout or refused) — check URL, data partition and "
                                + ("user and password." if token_type == "Basic" else "token."))
    return (_conn, _etp_creds, _etp_do_connect, _etp_lost, _lost_next, _plugin_rebinds, _token_expired, _watch_session)
