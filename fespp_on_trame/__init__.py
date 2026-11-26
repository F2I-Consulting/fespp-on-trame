"""fespp-on-trame: a multi-view web viewer for RESQML data, with per-view
widgets, on the ParaView/FESPP engine.

Layout at a glance:
  - ``app``     the application: ``app.boot`` wires the state to the engine,
                ``app.views`` hosts the dockview multi-view, ``app.ui``
                holds the shared server-side UI builders.
  - ``engine``  the ParaView/FESPP engine: ``app.boot`` initializes it, the
                dispatchers and ``data_load`` drive it, ``engine.sources``,
                ``engine.element_type`` and ``engine.tree`` model the data,
                ``engine.io`` moves files; ``engine.blockscope`` (opt-in)
                and ``engine.wire`` implement the target architecture.
  - ``ia``      the Assistant's home-made command engine (``ia.nlu``), its
                dialogue journal and the client of the optional local AI
                service (``ia.llm``); pure Python and numpy.
  - ``widgets/`` (repository root, beside this package) the decoupled Vue
                components (``trame-fespp-*``), each testable on its own.

See doc/dev/ARCHITECTURE.md and doc/dev/TARGET_ARCHITECTURE.md.
"""
from trame_client.utils.version import get_version

__version__ = get_version("fespp-on-trame")
