"""The engine package is imported by its name, never as a phantom submodule.

`fespp_on_trame.engine` carries the live tree as the package attribute
`_tree`. `from fespp_on_trame.engine import engine` names a submodule that
does not exist: the import raises, and where the site sits under an
`except` that returns None, the feature behind it dies in silence (the
unreadable-data flag, the per-channel statistics source and the per-scene
palette all read the tree). This guards the shape of the import, and the
attribute the sites read.
"""
import os
import re

import fespp_on_trame

_ROOT = os.path.dirname(fespp_on_trame.__file__)
_PHANTOM = re.compile(r"^\s*from\s+fespp_on_trame\.engine\s+import\s+engine\b", re.M)
# modules left out of the scan: none, every module of the package is part
# of the running application
_NOT_LIVE = set()


def _live_sources():
    for base, _dirs, files in os.walk(_ROOT):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, _ROOT)
            if rel in _NOT_LIVE:
                continue
            yield rel, path


def test_the_package_carries_no_tree_global():
    """The live tree is the server context's (slice 2b), not a module
    attribute any code could poke."""
    import fespp_on_trame.engine as pkg
    assert not hasattr(pkg, "_tree")


def test_no_live_module_imports_the_phantom_engine_submodule():
    offenders = []
    for rel, path in _live_sources():
        with open(path, encoding="utf-8") as fh:
            if _PHANTOM.search(fh.read()):
                offenders.append(rel)
    assert offenders == [], (
        "these modules import `engine` as a submodule of fespp_on_trame.engine;"
        " it does not exist and the import always raises: " + ", ".join(offenders))
