"""Distinct color generation for per-representation solid colors.

The golden angle hue distribution gives maximally separated hues for any N
without ever repeating. Combined with a small (S, V) cycle, this stays
visually distinguishable for hundreds of consecutive indices, which matters
when many grids are loaded simultaneously.
"""
import colorsys

# 137.508° in [0, 1] — irrational fraction of the circle, so successive
# multiples never align. Maximizes hue separation for any sequence length.
_GOLDEN_ANGLE = 137.508 / 360.0
_S_LEVELS = (0.85, 0.70, 0.95)
_V_LEVELS = (0.85, 0.95, 0.75)


def color_for_index(i: int) -> str:
    """#RRGGBBAA hex for index i. Distinct-ish for hundreds of indices."""
    h = (i * _GOLDEN_ANGLE) % 1.0
    s = _S_LEVELS[i % 3]
    v = _V_LEVELS[(i // 3) % 3]
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}ff"
