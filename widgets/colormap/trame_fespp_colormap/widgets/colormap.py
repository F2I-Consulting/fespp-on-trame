from trame_client.widgets.core import AbstractElement

from trame_fespp_colormap import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["ColormapPanel", "LegendsPanel"]


class ColormapPanel(HtmlElement):
    """Per-view COLORMAP controls, with the rescales.

    The colour/opacity node GRAPH goes in the panel's default SLOT (the host
    mounts Kitware's ``ColorOpacityEditor`` there, bound to the same view)
    — header on top, graph, then the controls.
    Props in = the host's projection of the view-scoped LUT of the active
    array; events out = the reader's edits. Scoped to ONE view; the host
    applies them on that view's scoped LUT / PWF through the cmap_*
    controllers.

    Props::

        cmap     {array, label, preset, min, max, data_min, data_max, scale,
                  below, below_alpha, above, above_alpha, nan, nan_opacity,
                  bar, is_ts, is_mr, note, components, component,
                  hide_nan, hide_nan_auto, hide_nan_ok, hide_nan_why,
                  hide_nan_hidden, categorical, categories, categories_note}
                 `array` = the VTK array name (the key); `label` = the
                 property's display name (title, component, unit), the
                 header — the same text as the view's colour bar; `note`
                 = what the last action had to say, "" when nothing;
                 `components` / `component` = the values per element of a
                 vector property and the one the colour reads
                 ("magnitude" when none is chosen); `hide_nan_*` = the
                 state of "Hide NaN cells": on, checked by the host at NaN
                 opacity 0, possible (else why not), cells hidden
        presets  [name, ...]
        presets_categorical  [name, ...] the qualitative presets offered on
                 a property painted by code (`cmap.categorical`), whose
                 `cmap.categories` = [{code, label, color}, ...] the
                 card lists with a picker each, and whose
                 `cmap.categories_note` says why a discrete property is
                 nevertheless painted with a ramp
        view_id

    Events::

        set_preset(name)
        set_range([lo, hi])                   custom range, pinned
        set_scale('linear'|'log'|'exp')
        set_below(['#rrggbb', alpha])         below-range colour + opacity
        set_above(['#rrggbb', alpha])         above-range colour + opacity
        set_nan(['#rrggbb', alpha])
        set_hide_nan(bool)                    remove the NaN cells so their
                                              neighbours' faces show; the
                                              host checks it itself at NaN
                                              opacity 0 (cmap.hide_nan_auto)
        set_bar(bool)                         colour bar visibility
        set_component('magnitude' | '0'..)    which component of a vector
                                              property the colour reads
        set_category_color([code, '#rrggbb']) one code's colour
        set_category_opacity([code, alpha])   one code's opacity; code null:
                                              every code
        rescale('data'|'time'|'mr'|'all'|'symmetric'|'diverging')
                                              'all' = time steps x
                                              realizations; 'symmetric' =
                                              [-m, +m] around 0; 'diverging'
                                              = the Cool to Warm preset on
                                              that symmetric range; a custom
                                              range is simply set_range
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("colormap-panel", children, **kwargs)
        self._attr_names += ["cmap", "presets", "presets_categorical", "view_id", "look"]
        self._event_names += [
            "set_preset", "set_range", "set_scale", "set_below", "set_above",
            "set_nan", "set_hide_nan", "set_bar", "rescale", "set_component",
            "set_category_color", "set_category_opacity",
            ("set_object_color", "set-object-color"), ("set_object_opacity", "set-object-opacity"),
        ]


class LegendsPanel(HtmlElement):
    """The LEGENDS of one 3D view, drawn ON the render: every coloured table
    of the view, one row each, in sections by what they paint (Grids, Wells,
    Surfaces, Other). The view shows ONE colour bar in 3D, that of the table
    the Colormap card edits; picking a row makes that table the edited one,
    hence the one whose bar is shown. Scoped to ONE view.

    Not a card: mount it directly in the view's render container (the
    ``position:relative; overflow:hidden`` row holding the VtkRemoteView).
    The root places itself top right, without a ground, at most half the
    view's height (clear of ParaView's bar at the bottom right), z-index 3
    (above the render, below the pick overlay and the floating cards), and
    lets the pointer through except on its header and its rows. It renders
    NOTHING with fewer than two tables, unless the one table has `bar_off`
    (then the list is the only legend). A header button "Legends (N)" folds
    the list; the fold is the component's own state.

    Props::

        legends  {} or {tables: [{key, title, lo, hi, stops, codes, log,
                  bar, bar_off, family, owners}, ...]} in display order
                 (the host sorts by family, then title; the order is kept
                 inside a section); `title` = the text of the table's
                 colour bar; `lo` / `hi` = the range ends, already
                 formatted; `stops` = 16 '#rrggbb' sampled left to right
                 for a continuous table, [] for a coded one; `codes` =
                 [{code, label, color}] for a table painted by code, []
                 otherwise; `log` = mapped on a log scale; `bar` = this
                 table holds the view's colour bar; `bar_off` = it would,
                 but the bar is switched off in the Colormap card;
                 `family` = "grid" | "well" | "surface" | "other" (anything
                 else is shown under Other); `owners` = [name, ...] the
                 objects the table paints, shown muted after the title
        view_id

    Events::

        pick(key)                             make this table the one the
                                              Colormap card edits and whose
                                              bar is shown; also emitted
                                              for the table already holding
                                              it
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("legends-panel", children, **kwargs)
        self._attr_names += ["legends", "view_id"]
        self._event_names += ["pick"]
