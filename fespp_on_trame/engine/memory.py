"""Memory handed back to the system.

glibc keeps what a process frees on its own lists: a session that unloads
four gigabytes of wells stayed at four gigabytes (Volve's wells, 15/11: 4 617
MiB after the untick, 400 once trimmed) although nothing was leaked.
`give_back()` collects what Python no longer holds and asks the allocator to
return its free pages; `held_mib()` and `process_mib()` say where the memory
stands, for the log and the benches. Linux with glibc only: anywhere else
these do nothing and answer None.
"""
import ctypes
import gc
import os
import sys


class _Mallinfo2(ctypes.Structure):
    _fields_ = [(name, ctypes.c_size_t) for name in (
        "arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks", "fsmblks",
        "uordblks", "fordblks", "keepcost")]


def _libc():
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.mallinfo2.restype = _Mallinfo2
        return libc
    except (OSError, AttributeError) as exc:
        print(f"[fespp] memory: neither measured nor handed back, no glibc mallinfo2 ({exc!r})", flush=True)
        return None


_LIBC = _libc()


def held_mib():
    """MiB malloc has handed out and not got back (its heap and its mapped
    blocks): what a leak makes grow, where the process's memory also counts
    what was freed and not returned."""
    if _LIBC is None:
        return None
    info = _LIBC.mallinfo2()
    return (info.uordblks + info.hblkhd) / 2 ** 20


def process_mib():
    """MiB of memory the process holds (its resident set)."""
    if not os.path.exists("/proc/self/status"):
        return None
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
    return None


def give_back():
    """What was freed goes back to the system: (process MiB before, after),
    None each where it cannot be read."""
    before = process_mib()
    gc.collect()
    if _LIBC is not None:
        _LIBC.malloc_trim(0)
    return before, process_mib()
