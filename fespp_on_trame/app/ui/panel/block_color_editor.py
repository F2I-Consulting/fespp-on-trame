import ptc
from trame.app import get_server
from paraview import simple as pvsimple

server = get_server()
controller = server.controller


class BlockColorOpacityEditor(ptc.ColorOpacityEditor):
    """ColorOpacityEditor that applies color/opacity changes to BlockColors and
    BlockOpacities on the active representation.

    The active block selector is always kept in sync with the active treeview node
    via representation.BlockSelectors, so no custom lookup is needed here.
    """

    def _get_active_display_and_selector(self):
        view = pvsimple.GetActiveView()
        if not view:
            return None, None, None
        source = pvsimple.GetActiveSource()
        if not source:
            return None, None, None
        display = pvsimple.GetDisplayProperties(source, view=view)
        if not display:
            return None, None, None
        selectors = display.BlockSelectors
        selector = selectors[0] if selectors else None
        return display, view, selector

    def update_color_transfer_function(self):
        """Apply colors as BlockColors on the active block instead of global LUT."""
        display, view, selector = self._get_active_display_and_selector()
        if not display or not selector:
            super().update_color_transfer_function()
            return

        colors = self.state.colors  # [[scalar, [r, g, b]], ...]
        if not colors:
            return

        # Use the mid-point color as the solid color for this block
        mid = colors[len(colors) // 2]
        r, g, b = [c / 255.0 for c in mid[1]]

        block_colors = [
            entry for entry in (display.BlockColors or [])
            if entry[0] != selector
        ]
        block_colors.append((selector, r, g, b))
        display.BlockColors = block_colors

        pvsimple.Render(view=view)
        controller.view_update()

    def update_opacity_transfer_function(self):
        """Apply opacity as BlockOpacities on the active block instead of global OTF."""
        display, view, selector = self._get_active_display_and_selector()
        if not display or not selector:
            super().update_opacity_transfer_function()
            return

        opacities = self.state.opacities  # [[scalar, opacity], ...]
        if not opacities:
            return

        opacity_val = max(pt[1] for pt in opacities)

        block_opacities = [
            entry for entry in (display.BlockOpacities or [])
            if entry[0] != selector
        ]
        block_opacities.append((selector, opacity_val))
        display.BlockOpacities = block_opacities

        pvsimple.Render(view=view)
        controller.view_update()
