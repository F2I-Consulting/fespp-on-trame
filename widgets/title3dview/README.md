# trame-fespp-title3dview

The camera strip of a 3D view's **title bar**: interaction mode (3D / 2D),
the view's vertical exaggeration, how every block is drawn, shading on or off,
frame everything, the three axis looks, and a zoom notch.

**Shading** is on by default; the lightbulb beside "Represent by" switches the
view to **exact colours** (no lighting), because a lit surface reads a
different colour than its legend says. The glyph shows the mode the view is
in (`mdi-lightbulb-on-outline` lit, `mdi-lightbulb-off-outline` exact, which
also wears the outlined "on" look), the tooltip says the mode and what a click
does. Offered on the Earth too: it lights there as well.

## Why a widget, and why in the title bar

Framing the data or looking down an axis are **gestures**, reached for in the
middle of a drag — a card to open, move and close costs more than the gesture
is worth. So they live open in the chrome, beside the tab, and name the view
they drive by sitting on it.

It replaces Kitware's `ptc.ResetCameraButtons`, which drew a white pill of dark
icons on the F2I blue and, worse, drove the **active** view from a single
global `interaction_mode`: with two views open, one view's 2D/3D button was the
other's. Here the mode is per view and every gesture names its view.

**A narrow group** (two or three views side by side) gets less of the strip,
never a strip over its tabs: the host wraps it in a size container spanning
the row from the first tab's end to the right edge (`app/views/render_panel.py`),
and the strip's own `@container` rules drop the Z slider under 640 px (its field
stays), the style selector under 570 px, the zoom, the axis framings and the Z
under 435 px, the shading and the separators
under 240 px — the hand, the mouse, the mode and the reset framing stay to
the last. `tests/browser/probes/title_overflow.mjs` measures it.

## Contract

```
props   mode  : "3D" | "2D"   — this view's interaction mode
        globe : bool          — this view is on the Earth; the framings are
                                drawn dead with the reason in their tooltip
        rep_style / rep_styles — how every block is drawn, and the choices
        flat  : bool          — false (default) = shaded, true = exact
                                colours, no lighting
        z_scale : number      — this view's vertical exaggeration, slid (1 to
                                50) or typed (up to 100)
events  set-mode(mode) · reset() · axis("+x"|"+y"|"+z") · zoom(factor)
        set-style(name) · frame("earth") · set-flat(bool) (the wanted mode)
        set-zscale(number)
```

Stateless: the host computes every camera move (`boot`'s `nav_*` controllers),
so this strip and the Navigation card drive the same code.

## Build

```
cd vue-components && npm install && npm run build
# -> trame_fespp_title3dview/module/serve/{*.umd.js, style.css}
```

## A view drawing one thing on its own (`bare`)

The Stratigraphy panel's model tab carries a 3D of the velocity model alone
(`app/views/render_panel.py`, kind "bare"), the strip over the render's top
edge rather than in a tab row. The strip is the same, with the
`bare` prop: "Represent by" and the shading act on the data, so they are
greyed with the reason in their tooltip; the Depth / Time switch is offered
whatever the data holds, since the velocity model has both domains; the reading mouse
reads the velocity model (its interval velocity, the other vertical, the cell).
Such a view has no cards, so `linkable` adds a link button at the end of the
strip (`toggle-link`): it links the camera with the last 3D view of the data
used, `linked` naming the views it moves with.
