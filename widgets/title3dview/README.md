# trame-fespp-title3dview

The camera strip of a 3D view's **title bar**: interaction mode (3D / 2D),
how every block is drawn, shading on or off, frame everything, the three axis
looks, and a zoom notch.

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

## Contract

```
props   mode  : "3D" | "2D"   — this view's interaction mode
        globe : bool          — this view is on the Earth; the framings are
                                drawn dead with the reason in their tooltip
        rep_style / rep_styles — how every block is drawn, and the choices
        flat  : bool          — false (default) = shaded, true = exact
                                colours, no lighting
events  set-mode(mode) · reset() · axis("+x"|"+y"|"+z") · zoom(factor)
        set-style(name) · frame("earth") · set-flat(bool) (the wanted mode)
```

Stateless: the host computes every camera move (`boot`'s `nav_*` controllers),
so this strip and the Navigation card drive the same code.

## Build

```
cd vue-components && npm install && npm run build
# -> trame_fespp_title3dview/module/serve/{*.umd.js, style.css}
```
