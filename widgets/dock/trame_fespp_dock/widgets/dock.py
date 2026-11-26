"""The dock widget: trame-dockview 2.0.1 (Kitware, MIT, see ../../LICENSE),
renamed FpDock / <fp-dock-view> so it never collides with the original."""
from trame_client.widgets.core import AbstractElement

from .. import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = [
    "FpDock",
    "FpDockSlot",
]


class FpDock(HtmlElement):
    """
    The dock component.

    Args:
      theme (string):
        Theme to use for the layout manager.
        Possible values are: [
            Abyss, AbyssSpaced, Dark, Dracula, Light,
            LightSpaced, VisualStudio,
        ]
      components (dict):
        Map of components to replate using template names.
        Possible components to override:
            watermarkComponent, rightHeaderActionsComponent,
            prefixHeaderActionsComponent, leftHeaderActionsComponent,
            defaultTabComponent
      default_renderer (string):
        Possible values: always | onlyWhenVisible
      disable_auto_resizing (bool):
        Disable the auto-resizing which is controlled through a ResizeObserver.
        Call .layout(width, height) to manually resize the container.
      disable_dnd (bool):
        Disable drag and drop.
      disable_floating_groups (bool):
        Disable floating groups.
      disable_tabs_overflow_list (bool):
        Disable tabs overflow list.
      dnd_edges (bool):
      floating_group_bounds (dict|string):
        { minimumHeightWithinViewport: number, minimumWidthWithinViewport: number } | 'boundedWithinViewport'
        (the whole window, its tab row included, stays inside the dock, and
        comes back inside when the dock shrinks).
      floating_group_drag_handle (string):
        What moves a floating window: titlebar (a bar of its own, the default) | tabbar
        (the empty part of its tab row).
      hide_borders (bool):
        Hide borders
      locked (bool):
      no_panels_overlay (string):
        Define the behaviour of the dock when there are no panels to display. Defaults to watermark.
        Options: watermark | emptyGroup
      popout_url (string):
        Popup url
      scrollbars (string):
        Select native to use built-in scrollbar behaviours and custom to use an internal implementation
        that allows for improved scrollbar overlay UX. This is only applied to the tab header section.
        Defaults to custom.
        Options: custom | native
      single_tab_mode (string):
        Options: default | fullwidth
      layout (dict):
        A layout this dock was left in (its layout_changed), restored once when
        the dock is ready, the slots of its panels made this dock's own.
      center (string):
        The slot of a fixed central panel (id "__center__"), its content an
        FpDockSlot with that slot_key:
        no tab row, nothing docks into it as a tab, it cannot be dragged nor
        closed, and it is added back if it ever disappears. It emits neither
        remove_panel nor active_panel.
      panels (list):
        Ids of the card panels that must be present. Missing ones are added
        (once their panel_specs entry exists), unlisted ones removed without
        any event. A card comes back where it was last removed from, else it
        opens as a tab right after the active card of the card group last
        made active; with no card group, on its spec's side of the center.
        Neither "__center__" nor panels of add_panel() are touched.
      panel_specs (dict):
        Card id -> {title, initialWidth, initialHeight, minimumWidth,
        minimumHeight, slot, side}: what a card is created with (sizes when
        > 0). ``slot`` makes the panel an empty div registered, with the
        panel's api, as {el, api} under that key in the shared
        ``window.__fpCardSlots`` map. ``side`` ("left", the default, "right",
        "above" or "below") is where it opens beside the center when no card
        group takes it as a tab.
      header_buttons (list):
        The buttons drawn at the right end of every group's tab row (never the
        center's), among "left", "right", "top", "bottom", "float", "close",
        always in that order. Each acts on its group's active panel: "left" ..
        "bottom" dock it along that edge of the whole dock, in a group of its
        own (from a floating window too); "float" detaches it, centred, at 60 %
        of the dock, and in a floating window anchors it back where it was
        docked before (else along the left edge); "close" closes it (a card
        asks with panel_close_request, a panel of add_panel() emits
        remove_panel). The dock's own component draws them, with the
        application's FpIcon (widgets/icon); it takes the right header actions
        over a ``components`` template given for them. Default: none.
      header_emit (list):
        The names of header_buttons emitted as header_action instead of
        performed by the dock. Default: none.

      Dragging a tab: its image stays under the pointer where the tab was
      grabbed. Dropped where no target of the dock takes it (the middle of
      the center, for one), the tab floats there, its window kept inside the
      dock; with "float" in header_emit, header_action asks for it instead.
      A drag cancelled (Esc) changes nothing.

      ready (event):
        Event emitted when the component is ready.
      active_panel (event):
        Event emitted when a panel is activated.
        The $event will be equal to the id used when creating the panel.
      remove_panel (event):
        Event emitted when a panel is removed.
        The $event will be equal to the panel id provided at the panel creation.
      layout_changed (event):
        Event emitted (debounced) whenever the layout changes.
        The $event will be equal to the serialized layout (api.toJSON()),
        which can be fed back to restore_layout().
      panel_visibility (event):
        Event emitted when a panel becomes visible or hidden.
        The $event will be equal to { id, visible }.
      panel_close_request (event):
        Event emitted instead of closing when the user closes a card panel
        (an id of ``panels``); the server removes the id from ``panels``.
        The $event will be equal to the panel id.
      header_action (event):
        Event emitted when a button of header_emit is pressed.
        The $event will be equal to {id, action, width, height, floating}: the
        group's active panel, the button's name, the dock's size in px
        (clientWidth, clientHeight) and whether the group is floating. For a
        tab dropped where nothing docks it: {id, action: "float", width,
        height, floating: false, left, top}, (left, top) where the dropped
        tab's top left corner was, in px in the dock.
    """

    _next_id = 0

    def __init__(self, **kwargs):
        super().__init__(
            "fp-dock-view",
            **kwargs,
        )
        self._attr_names += [
            "theme",
            "components",
            ("default_renderer", "defaultRenderer"),
            ("disable_auto_resizing", "disableAutoResizing"),
            ("disable_dnd", "disableDnd"),
            ("disable_floating_groups", "disableFloatingGroups"),
            ("disable_tabs_overflow_list", "disableTabsOverflowList"),
            ("dnd_edges", "dndEdges"),
            ("floating_group_bounds", "floatingGroupBounds"),
            ("floating_group_drag_handle", "floatingGroupDragHandle"),
            ("hide_borders", "hideBorders"),
            "locked",
            ("no_panels_overlay", "noPanelsOverlay"),
            ("popout_url", "popoutUrl"),
            "scrollbars",
            ("single_tab_mode", "singleTabMode"),
            "center",
            "layout",
            "reveal",
            "panels",
            ("panel_specs", "panelSpecs"),
            ("header_buttons", "headerButtons"),
            ("header_emit", "headerEmit"),
        ]
        self._event_names += [
            "ready",
            ("active_panel", "activePanel"),
            ("remove_panel", "removePanel"),
            ("layout_changed", "layoutChanged"),
            ("panel_visibility", "panelVisibility"),
            ("panel_close_request", "panelCloseRequest"),
            ("header_action", "headerAction"),
        ]

        self.__ref = kwargs.get("ref")
        if self.__ref is None:
            FpDock._next_id += 1
            self.__ref = f"_fp_dock_{FpDock._next_id}"
        self._attributes["ref"] = f'ref="{self.__ref}"'

    def add_panel(self, id, title, template_name, **add_on):
        """
        Add a new panel to the layout.
        This can only be called once the widget is ready.

        Args:
            id (string):
                Unique identifier for that panel
            title (string):
                Title showing up in the tab.
            template_name (string):
                Name of the trame layout to be placed inside the panel.
            **kwargs:
                Additional parameter to control where the panel should be added.
                (https://dockview.dev/docs/core/panels/add#positioning-the-panel)
        """
        self.server.js_call(self.__ref, "addPanel", id, title, template_name, add_on)

    def remove_panel(self, id):
        """
        Remove/Close an existing panel within the layout.
        This can only be called once the widget is ready.

        Args:
            id (string):
                Unique identifier for that panel
        """
        self.server.js_call(self.__ref, "removePanel", id)

    def active_panel(self, id):
        """
        Activate an existing panel within the layout.
        This can only be called once the widget is ready.

        Args:
            id (string):
                Unique identifier for that panel
        """
        self.server.js_call(self.__ref, "activePanel", id)

    def set_panel_title(self, id, title):
        self.server.js_call(self.__ref, "setPanelTitle", id, title)

    def move_panel_to(self, id, position):
        """
        Move an existing panel within the layout.

        Args:
            id (string):
                Unique identifier for that panel.
            position (dict):
                Same shape as add_panel's position add-on:
                ``{"referencePanel": <panel id>, "direction": <dir>}``.
                ``direction`` accepts add_panel's values ("within", "left",
                "right", "above", "below"); "within" (the default) stacks the
                panel as a tab in the reference panel's group. Without a
                referencePanel the move is relative to the panel's own group.
        """
        self.server.js_call(self.__ref, "movePanelTo", id, position)

    def restore_layout(self, layout):
        """
        Restore a layout previously captured via the layout_changed event.

        Args:
            layout (dict):
                Serialized layout as provided by the layout_changed event
                (api.toJSON()).
        """
        self.server.js_call(self.__ref, "restoreLayout", layout)


class FpDockSlot(HtmlElement):
    """What a slot panel of an FpDock shows: its children, built here once and
    moved into the panel whose ``slot`` is ``slot_key`` while that panel
    exists (the dock's centre, for one). Moved, not rebuilt: what they hold
    stays.
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("fp-dock-slot", children, **kwargs)
        self._attr_names += [("slot_key", "slotKey")]
