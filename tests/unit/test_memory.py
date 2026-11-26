"""Tests for engine/memory: where the process's memory stands, and what was
freed handed back to the system — on Linux with glibc, where it works."""
import sys

import pytest

from fespp_on_trame.engine import memory

pytestmark = pytest.mark.skipif(memory._LIBC is None or not sys.platform.startswith("linux"),
                                reason="glibc's mallinfo2 only")


def test_what_malloc_holds_grows_with_an_allocation_and_goes_back():
    before = memory.held_mib()
    block = bytearray(64 * 2 ** 20)
    assert memory.held_mib() - before > 60
    del block
    assert memory.held_mib() - before < 8


def test_give_back_says_where_the_process_stood_and_stands():
    before, after = memory.give_back()
    assert before > 0 and after > 0
    assert memory.process_mib() > 0
