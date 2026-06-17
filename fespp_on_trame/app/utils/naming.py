"""Centralized name-sanitization helpers.

Two distinct sanitizers live here on purpose — they look similar but
serve OPPOSITE goals. Always pick the one that matches your use case;
mixing them produces silent mismatches that surface only at array
lookup or proxy registration time, much later.

`make_valid_vtk_name(s)` — STRIP every char outside `[-.0-9A-Z_a-z]`.
  Exact mirror of FESPP C++
  `ResqmlDataRepositoryToVtkPartitionedDataSetCollection::MakeValidNodeName`
  which produces the names actually attached to VTK arrays. Use this
  when you have a RESQML title (e.g. `"Pressure (PRESSURE)"`) and need
  to find the corresponding VTK array name (e.g. `"PressurePRESSURE"`).
  See RESQML.md "Array name sanitization" for the documented contract.

`sanitize_proxy_name(s)` — REPLACE every char outside `[-.0-9A-Z_a-z]`
  with `_`. NOT a mirror of C++. Used to derive ParaView SM
  registration names from RESQML paths and property titles. We replace
  instead of stripping because PV proxy names are valid with `_` and
  the replace form keeps the result human-readable
  (`rep_data__31eddead-...` vs the stripped `repdata31eddead...`).

Don't centralize a third "compatibility" variant — when in doubt about
which to use, prefer `make_valid_vtk_name` for ANYTHING that needs to
round-trip with a C++-produced name, and `sanitize_proxy_name` ONLY for
generating fresh proxy registration names that you own."""
import re


_INVALID_CHAR_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def make_valid_vtk_name(name: str) -> str:
    """Strip every char outside `[-.0-9A-Z_a-z]`, then prepend `_` when
    the result is empty or its first surviving char is not a letter /
    underscore (i.e. a digit, `-` or `.`).

    BYTE-FOR-BYTE mirror of FESPP C++ `MakeValidNodeName`
    (`ResqmlPropertyToVtkDataArray.cxx`): C++ builds the actual VTK array
    name this way, so Python MUST match exactly or array lookups silently
    miss for titles like `"123abc"` → `"_123abc"`. The only post-strip
    first chars that are NOT a-z/A-Z/`_` are digits, `-` and `.`, so the
    membership test below is equivalent to the C++ branch. Returns `""`
    on empty / None input. See RESQML.md "Array name sanitization"."""
    if not name:
        return ""
    result = _INVALID_CHAR_RE.sub("", name)
    if not result or result[0] in "-.0123456789":
        return "_" + result
    return result


def sanitize_proxy_name(name: str) -> str:
    """Replace every char outside `[-.0-9A-Z_a-z]` with `_`. NOT a
    mirror of C++ MakeValidNodeName — purpose is generating readable
    ParaView SM proxy registration names from arbitrary RESQML
    titles / paths. Use ONLY for proxy reg-names; never for VTK
    array name lookup."""
    return _INVALID_CHAR_RE.sub("_", name or "")
