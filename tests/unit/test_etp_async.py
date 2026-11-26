"""The ETP waits sleep on the server loop, never on the server thread.

A connection to an OSDU server is polled for up to 30 s and a dataspace is
fetched in two attempts. Every session of the process shares one asyncio
loop, so a `time.sleep` in those waits would freeze them all. The dispatch
functions are coroutines that await the connector's; trame awaits a
trigger's coroutine, so the "in flight" state reaches the browser and the
other sessions keep answering while the server takes its time.
"""
import asyncio
import inspect

from fespp_on_trame.engine import etp


class _State:
    def __init__(self):
        self.etp_dataspaces = None


class _Connector:
    """A connector whose waits are recorded, not slept."""

    def __init__(self, connects=True, children=1):
        self.is_connected = False
        self._connects = connects
        self._children = children
        self.calls = []

    async def connect(self, **kw):
        self.calls.append(("connect", kw["etp_url"]))
        await asyncio.sleep(0)          # the yield a real poll makes
        self.is_connected = self._connects
        return self._connects

    async def get_dataspaces(self):
        self.calls.append(("dataspaces",))
        await asyncio.sleep(0)
        return ["eml:///dataspace('a')"]

    async def set_dataspace(self, dataspace):
        self.calls.append(("set", dataspace))
        await asyncio.sleep(0)
        return self._children > 0


def test_the_dispatch_functions_are_coroutines():
    assert inspect.iscoroutinefunction(etp.connect_to_etp)
    assert inspect.iscoroutinefunction(etp.select_etp_dataspace)
    assert inspect.iscoroutinefunction(etp.force_etp_refresh)


def test_a_connection_lists_the_dataspaces_and_a_refusal_empties_them():
    state, c = _State(), _Connector(connects=True)
    asyncio.run(etp.connect_to_etp(state, c, "wss://x", "p", "t"))
    assert state.etp_dataspaces == ["eml:///dataspace('a')"]
    assert c.calls == [("connect", "wss://x"), ("dataspaces",)]

    state, c = _State(), _Connector(connects=False)
    asyncio.run(etp.connect_to_etp(state, c, "wss://x", "p", "t"))
    assert state.etp_dataspaces == []
    assert c.calls == [("connect", "wss://x")]


def test_a_dataspace_is_fetched_only_on_a_live_connection():
    c = _Connector()
    assert asyncio.run(etp.select_etp_dataspace(c, "eml:///")) is False
    assert c.calls == []
    c.is_connected = True
    assert asyncio.run(etp.select_etp_dataspace(c, "eml:///")) is True
    assert c.calls == [("set", "eml:///")]


def test_the_loop_stays_free_while_the_connector_waits():
    """Another task of the same loop runs during the connector's wait,
    which a blocking `time.sleep` would prevent for every session."""
    ticks = []

    async def other():
        for _ in range(3):
            ticks.append(1)
            await asyncio.sleep(0)

    async def both():
        state, c = _State(), _Connector()
        await asyncio.gather(etp.connect_to_etp(state, c, "wss://x", "p", "t"), other())
        return state

    state = asyncio.run(both())
    assert state.etp_dataspaces and len(ticks) == 3


def test_a_bearer_token_goes_through_as_typed():
    assert etp.credentials({"auth": "Bearer", "token": "  eyJabc  "}) == ("eyJabc", "Bearer")
    # a dialog that offers no choice of method sends no "auth": Bearer
    assert etp.credentials({"token": "eyJabc"}) == ("eyJabc", "Bearer")


def test_basic_is_user_colon_password_in_base64_as_fespp_expects():
    import base64
    token, kind = etp.credentials({"auth": "Basic", "user": " alice ", "password": " s3cr:t é "})
    assert kind == "Basic"
    # FESPP sends "Basic " + token: the standard HTTP Basic credentials; the
    # user is trimmed, the password kept as typed (spaces and ':' included)
    assert base64.b64decode(token).decode("utf-8") == "alice: s3cr:t é "


def test_missing_credentials_give_nothing_to_connect_with():
    assert etp.credentials({"auth": "Basic", "user": "alice"}) == (None, None)
    assert etp.credentials({"auth": "Basic", "password": "x"}) == (None, None)
    assert etp.credentials({"auth": "Bearer", "token": "  "}) == (None, None)
    assert etp.credentials(None) == (None, None)


def _jwt(claims):
    """A token shaped like an Entra one: header.claims.signature, base64url
    without padding (the signature is never looked at)."""
    import base64
    import json

    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return part({"alg": "RS256", "typ": "JWT"}) + "." + part(claims) + ".c2lnbmF0dXJl"


def test_the_end_of_a_bearer_token_is_read_from_its_claims():
    # an Entra token lives about an hour and the server drops the session
    # past it; reading the end lets the application warn in time
    assert etp.token_expiry(_jwt({"exp": 1790000000, "aud": "x"})) == 1790000000
    assert etp.token_expiry(_jwt({"exp": 1790000000.0}), "Bearer") == 1790000000


def test_a_token_without_an_end_has_none():
    assert etp.token_expiry(_jwt({"aud": "x"})) is None
    assert etp.token_expiry(_jwt({"exp": "soon"})) is None
    assert etp.token_expiry(_jwt({"exp": True})) is None
    assert etp.token_expiry("not-a-jwt") is None
    assert etp.token_expiry("a.%%%.c") is None
    assert etp.token_expiry("") is None


def test_basic_credentials_have_no_end():
    assert etp.token_expiry(_jwt({"exp": 1790000000}), "Basic") is None


def test_a_dataspace_that_gave_nothing_is_not_loaded():
    # a dataspace fetched over a dead session must not count as loaded
    # while the tree still holds the previous one: FESPP's own "no
    # dataobject" warning for that very dataspace decides
    uri = "eml:///dataspace('carl/decatur_horizons')"
    said = [{"text": "There is no dataobject in the dataspace : " + uri, "level": "warning"}]
    assert etp.said_empty(said, uri)
    assert not etp.said_empty(said, "eml:///dataspace('carl/decatur_faults')")
    assert not etp.said_empty([{"text": "something else", "level": "warning"}], uri)
    assert not etp.said_empty([], uri)
