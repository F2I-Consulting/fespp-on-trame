"""Name sanitizers: VTK array names and ParaView proxy names.

The two sanitizers look alike but serve opposite goals. Mixing them up
gives a silent mismatch that only shows later, when an array lookup or a
proxy registration misses.

`make_valid_vtk_name(s)` STRIPS every character outside `[-.0-9A-Z_a-z]`.
  It mirrors the FESPP C++ `ResqmlPropertyToVtkDataArray::MakeValidNodeName`,
  which names the VTK arrays (the assembly nodes go through an identical
  copy in `ResqmlDataRepositoryToVtkPartitionedDataSetCollection`). Use it
  to turn a RESQML title (`"Pressure (PRESSURE)"`) into the VTK array name
  the plugin attached (`"PressurePRESSURE"`). See RESQML.md, "Array name
  sanitization".

`sanitize_proxy_name(s)` REPLACES every character outside
  `[-.0-9A-Z_a-z]` with `_`. It mirrors nothing in C++: it builds ParaView
  proxy registration names from RESQML paths and property titles.
  Replacing rather than stripping keeps the name readable
  (`rep_data__31eddead-...` rather than `repdata31eddead...`).

Rule: `make_valid_vtk_name` for any name that must match one produced by
the C++ plugin, `sanitize_proxy_name` only for new proxy registration
names this application owns."""
import re


_INVALID_CHAR_RE = re.compile(r"[^\-.0-9A-Z_a-z]")


def make_valid_vtk_name(name: str) -> str:
    """The VTK array name the C++ plugin gives a RESQML title.

    Strips every character outside `[-.0-9A-Z_a-z]`, then prepends `_`
    when the result is empty or starts with something other than a letter
    or an underscore (`"123abc"` -> `"_123abc"`). It must match the FESPP
    C++ `MakeValidNodeName` (`ResqmlPropertyToVtkDataArray.cxx`) byte for
    byte, or array lookups miss without an error. After the strip, the
    only first characters that are not a letter or `_` are a digit, `-`
    and `.`, so the membership test below is the C++ condition. `""` for
    an empty or None input."""
    if not name:
        return ""
    result = _INVALID_CHAR_RE.sub("", name)
    if not result or result[0] in "-.0123456789":
        return "_" + result
    return result


def sanitize_proxy_name(name: str) -> str:
    """A readable ParaView proxy registration name from a RESQML title or
    path: every character outside `[-.0-9A-Z_a-z]` becomes `_`.

    Not the C++ `MakeValidNodeName` rule: never use it to look up a VTK
    array (see `make_valid_vtk_name`)."""
    return _INVALID_CHAR_RE.sub("_", name or "")


_REALIZATION_SUFFIX_RE = re.compile(r"_real_\d+$")


def strip_realization_suffix(array_name: str) -> str:
    """Inverse of `realization_dispatch.suffixed_array_name`:
    `'SOIL_real_23'` -> `'SOIL'`; a name without a realization suffix
    comes back unchanged.

    It sits in this dependency-free module rather than in
    `realization_dispatch` so that any module, however low in the import
    graph (`engine.sources`, `engine.blockscope`), can use it without
    risking an import cycle."""
    return _REALIZATION_SUFFIX_RE.sub("", array_name or "")
