"""The application's typed context (overhaul slice 10, decision Q10, option A
chosen by the PO on 18/10).

`Core` holds the services every feature shares — the trame server and its
state and controller, the assembly mirror, the sources, the render and state
plumbing, the app's events and its one way to tell the reader, and the
scene's single owners (eyes, active nodes, cards, the displays drawn outside
a composite, the selection of the 3D views, the panels whose tree follows
the one tick / eye grammar, the derived-property store). `boot_engine` makes it once, after
the start-up phases, and hands it to each feature's `register(core, *, …)`;
what a feature calls in ANOTHER feature stays an explicit keyword argument of
its `register`, so the order of the registrations in `boot` still says who
needs whom.

A feature reads the services it uses at the top of its `register`
(`state = core.state`), its body unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # the types only: no import at run time
    from fespp_on_trame.app.core.lifecycle import Lifecycle
    from fespp_on_trame.app.core.notifier import Notifier
    from fespp_on_trame.app.scene.activation import Activation
    from fespp_on_trame.app.scene.cards import Cards
    from fespp_on_trame.app.scene.displays import Displays
    from fespp_on_trame.app.scene.eyes import Eyes
    from fespp_on_trame.app.scene.panel_trees import PanelTrees
    from fespp_on_trame.app.scene.selection import Selection
    from fespp_on_trame.engine.derived_props import DerivedStore
    from fespp_on_trame.engine.selector import Selector
    from fespp_on_trame.engine.sources.collector import Collector
    from fespp_on_trame.engine.sources.etp_connector import ETPConnector
    from fespp_on_trame.engine.sources.source_registry import ActiveSource, SourceRegistry
    from fespp_on_trame.engine.tree import Tree
    from fespp_on_trame.engine.view_resources import ViewResourcesRegistry
    from fespp_on_trame.engine.wire.render_scheduler import RenderScheduler
    from fespp_on_trame.engine.wire.state_batcher import StateBatcher


@dataclass(frozen=True)
class Core:
    # trame
    server: Any
    state: Any
    controller: Any
    ctx: Any                                  # server.context
    # the data
    tree: Tree
    collector: Collector
    etp_connector: ETPConnector
    active_data_source: ActiveSource
    source_registry: SourceRegistry
    # each render view's colour tables and clone (engine/view_resources)
    view_resources: ViewResourcesRegistry
    selector: Selector
    # the plumbing
    scheduler: RenderScheduler
    batcher: StateBatcher
    lifecycle: Lifecycle
    notifier: Notifier
    # the scene's single owners
    eyes: Eyes
    activation: Activation
    cards: Cards
    displays: Displays
    selection: Selection
    panel_trees: PanelTrees
    derived_store: DerivedStore
    # the multi-view (frames pushed per panel), None before it exists
    mv: Callable[[], Any]
