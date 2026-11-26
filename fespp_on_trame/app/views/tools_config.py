"""Per-view tools registry — the ONE place to add / remove a tool.

Each entry in ``TOOLS`` = one toolbar button + its floating card:
    key          unique id (used in the per-view open-set)
    icon         glyph shown on the toolbar button
    title        card header
    build        build(server, view_id) -> creates the card's content widget,
                 already bound to that view's state / controllers
    default_open whether the card is open when a view first appears: True, or
                 the tuple of view kinds it opens in
    width/height default card size in px (height 0 = auto-fit content); the
                 reader can resize afterwards
    x0/y0        initial card position (default: staggered by tool index)
    dock         where the card starts: "float" (default), "left", "right"
                 or "bottom"; the reader docks it elsewhere afterwards
    kinds        the view kinds the tool serves — "render" (a 3D view) and/or
                 "globe" (the Globe view); default: both. A view builds the
                 cards of its kind only.
    needs        precondition for the tool to be USABLE; until met its button
                 is greyed, its title saying why (NEEDS_WHY), never hidden: a
                 button appearing under the reader's eyes is worse than a
                 greyed one (the PO, 27/10). view_wiring._TOOL_NEEDS maps the
                 tag to a predicate. "grid" = this view has an IJK grid to act on,
                 "thresholdable" = a property is read on a representation a
                 threshold can isolate, "volume" = something with cells that
                 have a volume, "loaded" = an object is read, "values" = the
                 view's active node has values (not a folder), "property" = a
                 property is read, "series" = a time series or a
                 multi-realization property is read, "views" = another 3D
                 view to link to (the PO, 28/10: "si pas utilisable rien à
                 faire en enabled").

To add a tool: append a dict + write its build() (any decoupled trame widget).
To remove one: delete its dict. Nothing else to touch. A tool not offered yet
is listed in app/core/previews: it is dropped from TOOLS unless its switch
is on.
"""

from fespp_on_trame.app.core import previews
from fespp_on_trame.app.ui.tree_icons import FAMILY_TREE_ICONS

from fespp_on_trame.app.views.widgets.data_tree import DataTree
from fespp_on_trame.engine import tree_families


#: why a tool is greyed, by its `needs` tag
NEEDS_WHY = {
    "tree": "no reservoir grid in the data",
    "tree_surface": "no surface in the data",
    "tree_well": "no wellbore in the data",
    "tree_seismic": "no lattice grid (a velocity model, a seismic cube) in the data",
    "grid": "it needs something drawn in this view",
    "thresholdable": "it needs a property checked on a grid, a surface, a polyline or a point set",
    "volume": "it needs cells with a volume: a grid, a cell sub-representation or a blocked wellbore",
    "loaded": "check an object in the tree first",
    "property": "it needs a property read: check one in the tree",
    "series": "it needs a time series or a multi-realization property read",
    "views": "it needs a second 3D view to link to",
}
#: why every tool is greyed before any data
NO_DATA_WHY = "import a file first"


def toolbar(entries, gate):
    """The view toolbar: every tool of `entries`, in order, each drawn.
    `gate(t)` is "" when the tool can act, else why not: the button is then
    greyed with the reason after its title. A button never appears or
    disappears as data comes (the PO, 27/10). A tool whose door is the
    view's title bar has no button here."""
    out = []
    for t in entries:
        if t.get("door") == "title":
            continue
        e = toolbar_entry(t)
        why = gate(t)
        if why:
            e["title"] = f"{e['title']} — {why}"
            e["disabled"] = True
        out.append(e)
    return out


def default_open_keys(tools, kind="render", xml=None, lattice=()):
    """The cards a view of `kind` opens with — `default_open` is True, or a
    tuple of the view kinds it opens in. With `xml` (the published
    assembly), the tree opens on the first family the data holds
    (`lattice`: the rows of its lattice grids, engine/tree_families)."""
    keys = [t["key"] for t in tools
            if (t.get("default_open") is True
                or (isinstance(t.get("default_open"), tuple)
                    and kind in t["default_open"]))]
    if xml is not None and tree_families.KEYS[0] in keys:
        first = tree_families.first_present(xml, lattice)
        keys = [first if k == tree_families.KEYS[0] else k for k in keys]
    return keys


def _build_tree(server, view_id, key):
    # Self-contained widget (widgets/data_tree.py — contract in its docstring),
    # one card per family (engine/tree_families). The eye callback is
    # INJECTED: the state watcher's door of the eye service (app/scene/eyes),
    # which skips a set the last pass left.
    DataTree(server, view_id, family=key,
             on_visible_change=server.controller.on_eye_watch)


def _build_navigation(server, view_id):
    """3D navigation of THIS view — a decoupled widget (widgets/navigation);
    every camera move is computed in boot (nav_* controllers)."""
    from trame_fespp_navigation.widgets import NavigationPanel
    ctrl = server.controller
    NavigationPanel(
        has_pick=(f"!!ui_nav_has_pick__{view_id}",),
        has_active=(f"!!active_path__{view_id}",),
        parallel=(f"!!ui_nav_parallel__{view_id}",),
        pivot_shown=(f"!!ui_nav_pivot_shown__{view_id}",),
        axes_grid=(f"!!ui_nav_axes_grid__{view_id}",),
        note=(f"ui_view_note__{view_id}",),
        reset=(ctrl.nav_reset, f"['{view_id}']"),
        axis=(ctrl.nav_axis, f"['{view_id}', $event]"),
        center=(ctrl.nav_center_on_pick, f"['{view_id}', $event]"),
        frame=(ctrl.nav_zoom_active, f"['{view_id}']"),
        projection=(ctrl.nav_projection, f"['{view_id}', $event]"),
        pivot_shown_change=(ctrl.nav_pivot_toggle, f"[$event, '{view_id}']"),
        axes_grid_change=(ctrl.nav_axes_grid, f"[$event, '{view_id}']"),
    )


def _build_camlink(server, view_id):
    # one tick per OTHER render view; the toggle is symmetric (view_link_menu)
    from trame_fespp_camlink.widgets import CameraLinkPanel
    server.state.setdefault("view_links", {})
    server.state.setdefault("fespp_link_panels", [])
    CameraLinkPanel(
        view_id=view_id,
        views=("fespp_link_panels", []),
        links=("view_links", {}),
        toggle=(server.controller.camlink_toggle, f"['{view_id}', $event]"),
    )


def _build_slicers(server, view_id):
    # the Geometry slicer (app/features/geometry_slicer; the PO's manager,
    # 28/10): the shared slicer card on the I, J, K of the view's grid
    from trame_fespp_slicers.widgets import SlicersPanel
    ctrl = server.controller
    server.state.setdefault(f"ui_geometry_card__{view_id}", {})
    server.state.setdefault(f"ui_geometry_player__{view_id}", {})
    SlicersPanel(
        view_id=view_id,
        card=(f"ui_geometry_card__{view_id} || {{}}",),
        player=(f"ui_geometry_player__{view_id} || {{}}",),
        views=("fespp_render_panels || []",),
        # one gesture of the card, applied to its current state
        edit=(ctrl.geometry_slicer, f"[$event, '{view_id}']"),
        copy_from=(ctrl.slicer_copy_from, f"[$event, '{view_id}']"),
    )


def _build_thresholds(server, view_id):
    # the Property slicer (app/features/property_slicer; 28/10): the same
    # card on the properties added to it
    from trame_fespp_thresholds.widgets import ThresholdsPanel
    ctrl = server.controller
    server.state.setdefault(f"ui_property_card__{view_id}", {})
    server.state.setdefault(f"ui_property_player__{view_id}", {})
    ThresholdsPanel(
        view_id=view_id,
        card=(f"ui_property_card__{view_id} || {{}}",),
        player=(f"ui_property_player__{view_id} || {{}}",),
        edit=(ctrl.property_slicer, f"[$event, '{view_id}']"),
    )


def _build_volumetrics(server, view_id):
    # GRV → NRV → PV → HCPV of the view's active grid with fluid contacts —
    # a tool OF the view: the contacts draw in it, the grid is its active one
    from trame_fespp_volumetrics.widgets import VolumetricsPanel
    ctrl = server.controller
    v = f"ui_volumetrics__{view_id}"
    server.state.setdefault(v, {})
    VolumetricsPanel(
        data=(f"{v} || {{}}",),
        set=(ctrl.volumetrics_set, f"[$event[0], $event[1], '{view_id}']"),
        compute=(ctrl.volumetrics_compute, f"['{view_id}']"),
    )
    ctrl.volumetrics_refresh(view_id)


def _build_colormap(server, view_id):
    from trame_fespp_colormap.widgets import ColormapPanel
    ctrl = server.controller
    st = server.state
    v = f"ui_colormap__{view_id}"
    st.setdefault(v, {})
    st.setdefault("ui_colormaps", [
        "Cool to Warm", "Viridis", "Jet",
        "Rainbow Desaturated", "Grayscale", "Black-Body Radiation",
    ])
    st.setdefault("ui_colormap_presets", [])
    if not st.ui_colormap_presets:
        # Every ParaView preset name, once per session; the Attributes
        # card's short list is the fallback.
        try:
            from paraview import servermanager
            pr = servermanager.vtkSMTransferFunctionPresets.GetInstance()
            st.ui_colormap_presets = [pr.GetPresetName(i)
                                      for i in range(pr.GetNumberOfPresets())]
        except Exception:
            st.ui_colormap_presets = list(st.ui_colormaps or [])
    # the presets made to tell codes apart, for a property painted by code:
    # the ones this ParaView knows, in the palette's order
    st.setdefault("ui_colormap_presets_categorical", [])
    if not st.ui_colormap_presets_categorical:
        from fespp_on_trame.engine import categorical_palette
        known = set(st.ui_colormap_presets or [])
        st.ui_colormap_presets_categorical = [
            name for name in categorical_palette.QUALITATIVE_PRESETS
            if not known or name in known]
    # The graph: Kitware's colour/opacity node editor, two-way bound to
    # this view's node lists (boot projects the scoped LUT / PWF into them
    # and applies edits back). Only shown while an array is targeted.
    from trame.widgets import color_opacity_editor as trame_coe
    st.setdefault(f"ui_cmap_colors__{view_id}", [])
    st.setdefault(f"ui_cmap_opacities__{view_id}", [])
    # a key the template reads must exist when it mounts, or a value set
    # later never reaches it
    st.setdefault(f"ui_object_look__{view_id}", {})
    # Every prop as a JS expression, exactly like ptc's editor: the
    # component's inner NodeScaler maps `histograms` unconditionally, so a
    # missing (undefined) histograms / histogramsRange throws at render and
    # the whole editor stays blank.
    # The graph is the panel's SLOT: header on top, graph, then the controls.
    with ColormapPanel(
        view_id=view_id,
        cmap=(f"{v} || {{}}",),
        presets=("ui_colormap_presets", []),
        presets_categorical=("ui_colormap_presets_categorical", []),
        set_preset=(ctrl.cmap_preset, f"[$event, '{view_id}']"),
        set_category_color=(ctrl.cmap_category_color, f"[$event, '{view_id}']"),
        set_category_opacity=(ctrl.cmap_category_opacity, f"[$event, '{view_id}']"),
        set_range=(ctrl.cmap_range, f"[$event, '{view_id}']"),
        set_scale=(ctrl.cmap_scale, f"[$event, '{view_id}']"),
        set_component=(ctrl.cmap_component, f"[$event, '{view_id}']"),
        set_below=(ctrl.cmap_below, f"[$event, '{view_id}']"),
        set_above=(ctrl.cmap_above, f"[$event, '{view_id}']"),
        set_nan=(ctrl.cmap_nan, f"[$event, '{view_id}']"),
        set_hide_nan=(ctrl.cmap_hide_nan, f"[$event, '{view_id}']"),
        set_bar=(ctrl.cmap_bar, f"[$event, '{view_id}']"),
        rescale=(ctrl.cmap_rescale, f"[$event, '{view_id}']"),
        # the active object's own colour and opacity (app/features/object_look)
        look=(f"ui_object_look__{view_id} || {{}}",),
        set_object_color=(ctrl.object_color, f"[$event, '{view_id}']"),
        set_object_opacity=(ctrl.object_opacity, f"[$event, '{view_id}']"),
    ):
        trame_coe.ColorOpacityEditor(
            style="width: 100%; height: 12rem; padding: 0.25rem 0.5rem 0 0.5rem;",
            v_model_colorNodes=(f"ui_cmap_colors__{view_id}", []),
            v_model_opacityNodes=(f"ui_cmap_opacities__{view_id}", []),
            # the graph's axis = the DATA range (below/above bands around
            # the colormap's [min, max]) — see boot._push_colormap_state
            scalar_range=(f"({v} && {v}.array) ? [{v}.graph_min, {v}.graph_max] : [0, 1]",),
            background_shape=("'opacity'",),
            background_opacity=("true",),
            handle_radius=("7",),
            line_width=("2",),
            viewport_padding=("[8, 8]",),
            handle_color=("[0.125, 0.125, 0.125, 1]",),
            handle_border_color=("[0.75, 0.75, 0.75, 1]",),
            histograms=("[]",),
            histograms_range=("[0, 1]",),
            show_histograms=("false",),
            histograms_color=("[0, 0, 0, 0.25]",),
        )


def _build_timereal(server, view_id):
    # the Time & Realizations card (app/features/timereal_slicer; the PO,
    # 29/10): the shared slicer card on the view's time step, the
    # realizations and the vector components it shows
    from trame_fespp_timereal.widgets import TimeRealPanel
    ctrl = server.controller
    server.state.setdefault(f"ui_timereal_card__{view_id}", {})
    server.state.setdefault(f"ui_timereal_player__{view_id}", {})
    TimeRealPanel(
        view_id=view_id,
        card=(f"ui_timereal_card__{view_id} || {{}}",),
        player=(f"ui_timereal_player__{view_id} || {{}}",),
        edit=(ctrl.timereal_slicer, f"[$event, '{view_id}']"),
    )


def _build_globe(server, view_id):
    # The Globe view's card: the projected CRS as fesapi reports it (or
    # typed), the whole-Earth framing and the globe's opacity. Flying to a
    # single object lives in the view's right-click menu, which is where the
    # names are. State pushed by boot._push_globe_state; the card is the
    # decoupled trame_fespp_globe widget (widgets/globe).
    from trame_fespp_globe.widgets import GlobePanel
    ctrl = server.controller
    v = f"ui_globe__{view_id}"
    gb = f"ui_globe_busy__{view_id}"
    server.state.setdefault(v, {})
    # MUST be seeded here: view_manager builds this panel BEFORE calling
    # wire_view, which is what seeds the per-view vars.
    server.state.setdefault(gb, False)
    GlobePanel(
        globe=(f"{v} || {{}}",),
        # the scene is built one turn after the view: the card is drawn
        # first and says so, rather than sitting blank for seconds
        busy=(f"!!{gb}",),
        textures=("ui_globe_textures", []),
        texture=("ui_globe_texture", ""),
        texture_note=("ui_globe_texture_note", ""),
        epsg=(ctrl.globe_epsg, f"[$event, '{view_id}']"),
        frame=(ctrl.globe_frame, f"[$event, '{view_id}']"),
        # session-wide: two Globes of one session at different sharpness
        # would read as a bug, not as a setting
        set_texture=(ctrl.globe_texture, "[$event]"),
        opacity=(ctrl.globe_opacity, f"[$event, '{view_id}']"),
    )


# Per-view MODES: toolbar toggles that flip a state var instead of opening a
# card (boot.toggle_tool branches on these keys). They belong to the VIEW,
# hence the view toolbar — the title bar is for application-level actions, i.e.
# adding views. Plain-3D only: picking on the Earth is meaningless.
# The two selections are ONE button of the toolbar, group "select" (the
# manager, 15/10: two icons for one gesture): it turns the selection on and
# off, and while it is on a small button under it switches between ON the
# surface and THROUGH the volume (ViewToolbar draws a group so).
MODE_TOOLS = [
    {"key": "pick", "icon": "fespp-select-surface", "var": "ui_pick_mode__",
     "title": "Select cells ON the surface: click a cell, or drag a rectangle",
     "excludes": "frustum", "group": "select", "group_title": "Select cells", "needs": "loaded"},
    {"key": "frustum", "icon": "fespp-select-volume", "var": "ui_frustum_mode__",
     "title": "Select cells THROUGH the volume (hidden cells too):"
              " click or drag a rectangle",
     "excludes": "pick", "group": "select", "group_title": "Select cells",
     # the mode the group turns on first: through the volume (the PO, 16/10)
     "group_default": True, "needs": "loaded"},
    # The cursor position is not a mode of this toolbar: it is the MOUSE of
    # the view's title bar (widgets/title3dview), beside the HAND that moves
    # the scene, which tells the reader the readout holds the scene still.
]

def toolbar_entry(t, title=None):
    """What the view toolbar is sent of a tool: its key, icon, title (its
    card's: the harness finds the card by it), the button's tooltip when it
    says more (`tip`), and the group it is drawn in, if any."""
    out = {"key": t["key"], "icon": t["icon"],
           "title": title if title is not None else t["title"]}
    for k in ("tip", "group", "group_title", "group_default"):
        if k in t:
            out[k] = t[k]
    return out


TOOLS = [
    # the tree, one card per family (engine/tree_families), greyed when the
    # data holds none of it; default_open: True, or the kinds it opens in —
    # the Globe view opens with its own (small) card only, so the Earth is not
    # hidden behind a tree. A view opens the first family the data holds
    # (`default_open_keys`).
    *({"key": key, "icon": FAMILY_TREE_ICONS[title], "title": title,
       "build": (lambda server, view_id, key=key: _build_tree(server, view_id, key)),
       "default_open": ("render",) if key == "tree" else False, "width": 340,
       "height": 520, "needs": key}
      for key, title, _types in tree_families.FAMILIES),
    # the Globe view's own card, where it is driven (EPSG / framings /
    # opacity / imagery)
    {"key": "globe", "icon": "fespp-settings", "title": "Globe settings",
     "build": _build_globe, "default_open": ("globe",), "width": 380,
     "height": 300, "x0": 16, "y0": 8, "kinds": ("globe",)},
    # the session's time-depth model, under the Globe: a card docked at the
    # bottom of the 3D view — the columns' tracks, the zone, the cells and
    # the K layers; the velocity model it makes goes into the tree as a grid
    # (app/features/time_depth_law, time_depth_tree), its columns drawn in
    # the view while the card is open (time_depth_pins)
    {"key": "colormap", "icon": "fespp-colormap", "title": "Colormap", "retitled": True, "needs": "loaded",
     "build": _build_colormap, "default_open": False, "width": 340,
     "height": 500},
    # per-view isolates (slicers / thresholds) render un-projected leaf
    # displays and the camera presets are axis-aligned: render views only
    # The Geometry slicer and the Property slicer (the PO's manager, 28/10):
    # one shared widget, two cards, their icons kept. The Geometry slicer
    # keeps the cells of a grid by their place (I/J/K boxes, not a cut);
    # needs="grid": nothing to slice until this view has an object to cut
    # (I/J/K on an IJK grid, X/Y/Z on the others, 29/10).
    {"key": "slicers", "icon": "fespp-slicers", "title": "Geometry slicer", "needs": "grid",
     "build": _build_slicers, "default_open": False, "width": 300,
     "height": 380, "kinds": ("render",)},
    # needs="thresholdable": WIDER than the slicers. A crop needs a
    # structured grid, a threshold only needs a dataset carrying an array —
    # an unstructured grid and a sub-representation qualify. The threshold
    # chain lives on the same per-view isolate as the slicers.
    {"key": "thresholds", "icon": "fespp-threshold", "title": "Property slicer",
     "needs": "thresholdable", "build": _build_thresholds, "default_open": False,
     "width": 300, "height": 320, "kinds": ("render",)},
    # needs="volume": anything of the view with cells that have a volume — a
    # grid, a cell sub-representation, a blocked wellbore; the contacts draw
    # in this view
    {"key": "volumetrics", "icon": "fespp-volumetrics", "title": "Volumetrics",
     "needs": "volume", "build": _build_volumetrics, "default_open": False,
     "width": 620, "height": 440, "kinds": ("render",)},
    # the letters TS over MR (the manager, 15/10: the drawing of a
    # multi-realization time series said nothing); `tip` explains them, the
    # card keeps its title
    {"key": "timereal", "icon": "text:TS/MR",
     "title": "Time & Realizations",
     "tip": "Time & Realizations — time steps (TS) and multiple realizations (MR)",
     "build": _build_timereal, "needs": "series",
     "default_open": False, "width": 300, "height": 320},
    # render only: the Globe drives its own framing from its card
    # door "title": its button is in the view's title bar, not here
    {"key": "navigation", "icon": "fespp-navigation", "title": "Navigation", "needs": "loaded",
     "build": _build_navigation, "default_open": False, "width": 280,
     "height": 0, "kinds": ("render",), "door": "title"},
    # render only: a Globe camera lives in ECEF world coordinates — linking
    # it to a local-CRS 3D view would teleport both nowhere useful.
    {"key": "camlink", "icon": "fespp-magnet", "title": "Synchronize camera", "needs": "views",
     "build": _build_camlink, "default_open": False, "width": 260,
     "height": 0, "kinds": ("render",)},
]
# the cards not offered yet (Volumetrics, the PO 18/10): no button, no card,
# unless the server runs with their switch on (app/core/previews)
TOOLS = [t for t in TOOLS if previews.offered(t["key"])]
