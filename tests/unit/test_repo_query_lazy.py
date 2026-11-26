"""The reply of the plugin's lazy fetch (FESPP lazy leaves, 2026-10-14)."""
from fespp_on_trame.engine import repo_query


def test_parse_lazy_reply_reads_remaining_fetched_seconds():
    assert repo_query.parse_lazy_reply(["1200|200|0.537"]) == (1200, 200, 0.537)
    assert repo_query.parse_lazy_reply(["0|17|0.1"]) == (0, 17, 0.1)


def test_parse_lazy_reply_none_on_nothing_or_garbage():
    assert repo_query.parse_lazy_reply([]) is None
    assert repo_query.parse_lazy_reply(None) is None
    assert repo_query.parse_lazy_reply(["bogus"]) is None
