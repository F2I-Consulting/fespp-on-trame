"""engine/io/session_endpoint: the token of a bearer header, and nothing
else of the header — the document never carries it."""
from fespp_on_trame.engine.io.session_endpoint import bearer_token


def test_the_bearer_token_is_read_off_the_header_only():
    assert bearer_token({"Authorization": "Bearer abc.def"}) == "abc.def"
    assert bearer_token({"Authorization": "bearer  x "}) == "x"
    assert bearer_token({"Authorization": "Basic abc"}) == ""
    assert bearer_token({}) == "" and bearer_token(None) == ""
