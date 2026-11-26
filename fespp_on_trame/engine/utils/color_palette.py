"""Distinct solid colours, one per representation, and the diverging colours.

Hues step around the colour wheel by the golden angle, which keeps them
well apart for any number of colours without a visible repeat. Together
with a short (saturation, value) cycle, consecutive indices stay
distinguishable over hundreds of representations loaded at once.
"""
import colorsys

# The golden angle (137.508°) as a fraction of a turn: close to an
# irrational fraction, so successive multiples do not line up and the hues
# stay spread out whatever the number of indices.
_GOLDEN_ANGLE = 137.508 / 360.0
_S_LEVELS = (0.85, 0.70, 0.95)
_V_LEVELS = (0.85, 0.95, 0.75)


def color_for_index(i: int) -> str:
    """The `#RRGGBBAA` colour (opaque) of index `i`, distinct from its
    neighbours over hundreds of indices."""
    h = (i * _GOLDEN_ANGLE) % 1.0
    s = _S_LEVELS[i % 3]
    v = _V_LEVELS[(i // 3) % 3]
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}ff"


# A difference (A − B) reads on a diverging scale centred on zero: the
# ParaView preset the Colormap card applies, and the colours of the
# histogram bars below zero, above zero and across it.
DIVERGING_PRESET = "Cool to Warm"
DIVERGING_NEG = "#3b4cc0"
DIVERGING_POS = "#b40426"
DIVERGING_ZERO = "#9e9e9e"
