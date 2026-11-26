from trame_client.widgets.core import AbstractElement

from trame_fespp_navigation import module


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["NavigationPanel"]


class NavigationPanel(HtmlElement):
    """3D navigation controls of ONE view.

    Pure display: every camera move is computed server-side (the widget only
    says WHAT was asked). `has_pick` / `has_active` gate the buttons that
    need a target, so a button never promises something it cannot do.

    Props:
        has_pick     bool  — a cell is picked in this view (enables Centre
                             here / Zoom here)
        has_active   bool  — a node is active in this view's tree (enables
                             Frame object)
        parallel     bool  — projection is parallel
        pivot_shown  bool  — the rotation-centre cross is shown
        axes_grid    bool  — the graduated axes grid is shown
        note         str   — feedback line of the last action
    Events:
        reset               ()            fit everything loaded in the view
        axis                '+X'|'-X'|…   axis preset, both signs
        center              bool          centre the pivot on the pick
                                          (True = also zoom in)
        frame               ()            frame the active object
        projection          bool          parallel projection on/off
        pivot_shown_change  bool          rotation-centre cross on/off
        axes_grid_change    bool          axes grid on/off
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("navigation-panel", children, **kwargs)
        self._attr_names += [
            "has_pick", "has_active", "parallel",
            ("pivot_shown", "pivotShown"), ("axes_grid", "axesGrid"), "note",
        ]
        self._event_names += [
            "reset", "axis", "center", "frame", "projection",
            ("pivot_shown_change", "pivot-shown"),
            ("axes_grid_change", "axes-grid"),
        ]
