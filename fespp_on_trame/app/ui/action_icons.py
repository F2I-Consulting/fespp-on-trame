"""The icon of each right-click action: the same drawing in the 3D view's
menu and in the data tree's, and the one of the button that opens the same
tool (the top bar's, a view toolbar's) where there is one. And their order, the
same in both menus (`ordered`).

A name is "fespp-<name>" (the app's own set, widgets/_shared/icons) or
"mdi-<name>" (Material Design Icons); the shared menu (FpMenu) draws both.
"""

ZOOM = "mdi-magnify-plus-outline"
CENTER = "mdi-image-filter-center-focus"

ACTION_ICONS = {
    "pivot": "mdi-rotate-orbit",
    "center": CENTER,
    "center-3d": CENTER,
    "zoom": ZOOM,
    "zoom-3d": ZOOM,
    "show-in-tree": "fespp-data-tree",
    "highlight-3d": "fespp-select-surface",
    "highlight-off": "mdi-selection-off",
    "xml": "fespp-explorer",
    "geometry-slicer": "fespp-slicers",
    "property-slicer": "fespp-threshold",
    "add-to-stats": "mdi-sigma",
    "calculator": "mdi-calculator-variant-outline",
    "add-to-welllog": "fespp-log-view",
    "add-selected-to-welllog": "fespp-log-view",
    "log-as-tube": "mdi-pipe",
    "log-as-graph": "mdi-chart-areaspline",
    "log-as-curve": "mdi-chart-bell-curve-cumulative",
    "graphs-larger": "mdi-arrow-expand-horizontal",
    "graphs-smaller": "mdi-arrow-collapse-horizontal",
    "markers-larger": "mdi-arrow-expand-all",
    "markers-smaller": "mdi-arrow-collapse-all",
    "marker-name-on": "mdi-label-outline",
    "marker-names-on": "mdi-label-outline",
    "marker-name-off": "mdi-label-off-outline",
    "marker-names-off": "mdi-label-off-outline",
    "use-as-cube": "mdi-layers-outline",
    "save-epc": "mdi-content-save-outline",
}


# Where the camera goes, the object's row in its tree, what is selected, the
# tools on the object, then Stats and Info, last in every menu
MENU_ORDER = ("center", "center-3d", "zoom", "zoom-3d", "pivot",
              "show-in-tree",
              "highlight-3d", "highlight-off",
              "add-to-welllog", "add-selected-to-welllog", "log-as-graph", "log-as-curve", "log-as-tube", "graphs-larger", "graphs-smaller",
              "markers-larger", "markers-smaller", "marker-name-on", "marker-names-on", "marker-name-off",
              "marker-names-off",
              "calculator", "geometry-slicer", "property-slicer",
              "use-as-cube", "save-epc",
              "add-to-stats", "xml")


def ordered(entries):
    """The menu entries {key, ...} in `MENU_ORDER`."""
    rank = {k: i for i, k in enumerate(MENU_ORDER)}
    return sorted(entries, key=lambda e: rank.get(e["key"], len(MENU_ORDER)))


def icon_of(key):
    """The icon of the action `key`, "" when it has none. The Globe's
    entries fly: to the whole Earth, or zoomed on one object."""
    if key == "globe:earth":
        return "fespp-globe"
    if key.startswith("globe:"):
        return ZOOM
    return ACTION_ICONS.get(key, "")


def entry(key, label):
    """A menu entry {key, label, icon?}."""
    out = {"key": key, "label": label}
    icon = icon_of(key)
    if icon:
        out["icon"] = icon
    return out
