"""Where ParaView keeps the plugins the engine loads beside FESPP.

`resolve_esg_plugin(fallback)` locates the bundled ExplicitStructuredGrid
plugin under the ParaView install instead of hardcoding one version and
layout, so a different ParaView build or OS still finds it: it searches
the ``TRAME_PARAVIEW`` root and the ParaView package's install root for
``lib/paraview-*/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.*``
(``bin/paraview-*`` on the Windows binary release), and falls back to
`fallback`.
"""
import os
from pathlib import Path


def resolve_esg_plugin(fallback):
    roots = []
    env_root = os.environ.get("TRAME_PARAVIEW")
    if env_root:
        roots.append(Path(env_root))
    try:
        import paraview
        # paraview pkg: <root>/lib/pythonX.Y/site-packages/paraview/__init__.py
        roots.append(Path(paraview.__file__).resolve().parents[4])
    except Exception:
        pass
    for root in roots:
        for pattern in (
            "lib/paraview-*/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.*",
            "bin/paraview-*/plugins/ExplicitStructuredGrid/ExplicitStructuredGrid.*",
        ):
            try:
                for hit in sorted(root.glob(pattern)):
                    if hit.suffix in (".so", ".dll", ".dylib"):
                        return str(hit)
            except Exception:
                pass
    return fallback
