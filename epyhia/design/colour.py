"""How far apart two colours look, and the bar at which two palettes are one direction.

SC-001 asks whether two briefs produce distinct visual directions. The check that answered
it compared hex strings, so `#B5451B` and `#b4571f` — a burnt orange and the same burnt
orange — counted as distinct and the criterion passed on a technicality. Distance in a
perceptual space is what that comparison needed.

CIE76 rather than CIEDE2000 on purpose: the accuracy CIEDE2000 buys is at hue boundaries,
and this module is asked a same-or-different question at coarse thresholds. It would cost
either a dependency or sixty error-prone lines to make an answer that does not change.

Nothing here reads a brief or a brand doc. It takes two colours and returns a number.
"""

from collections.abc import Mapping

# Calibrated against the three sampled brand docs in specs/003-distinctive-sites/evidence.md,
# whose palettes a reader called one direction — a pale cream ground, a near-black brown, a
# burnt-orange accent. Measured across those three: grounds ΔE 1.15–2.18, accents ΔE
# 4.38–14.11. The bar has to call them the same, and the same document's drafted-and-rejected
# directions have to stay different: the dark one is ΔE 87 away by ground, the teal one 68.
#
# The accent bar alone would not do it — the dark direction's orange is only ΔE 17 from one
# sampled accent, inside the bar — which is why both must hold. A ground is the decision the
# accent is chosen against, so two palettes agreeing on the accent over different grounds are
# not one direction. Fixed here once, the design lint's precedent (lint.py): these are
# properties of perception, not of a client.
ACCENT_SAME_DELTA_E = 20.0
BG_SAME_DELTA_E = 10.0

# D65, the white point sRGB is defined against.
_WHITE = (0.95047, 1.0, 1.08883)

# sRGB (linear) → XYZ, D65.
_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)

_DELTA = 6 / 29


def _channels(colour: str) -> tuple[float, float, float]:
    """`#rrggbb` as three 0–1 floats. The brand doc schema admits no other spelling."""
    hex_digits = colour.strip().lstrip("#")
    if len(hex_digits) != 6:
        raise ValueError(f"not a six-digit hex colour: {colour!r}")
    return tuple(int(hex_digits[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _linear(channel: float) -> float:
    """Undo the sRGB transfer function, so the numbers below are light rather than bytes."""
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _f(ratio: float) -> float:
    if ratio > _DELTA**3:
        return ratio ** (1 / 3)
    return ratio / (3 * _DELTA**2) + 4 / 29


def lab(colour: str) -> tuple[float, float, float]:
    """CIELAB (D65) for one `#rrggbb` colour: lightness, green–red, blue–yellow."""
    rgb = [_linear(channel) for channel in _channels(colour)]
    x, y, z = (
        sum(coefficient * channel for coefficient, channel in zip(row, rgb, strict=True))
        / white
        for row, white in zip(_TO_XYZ, _WHITE, strict=True)
    )
    fx, fy, fz = _f(x), _f(y), _f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(first: str, second: str) -> float:
    """CIE76 distance between two `#rrggbb` colours. Symmetric, zero on identity.

    Roughly: 2.3 is the just-noticeable difference, single digits are two shades of one
    decision, and tens are two different decisions.
    """
    return sum((a - b) ** 2 for a, b in zip(lab(first), lab(second), strict=True)) ** 0.5


def same_direction(first: Mapping[str, str], second: Mapping[str, str]) -> bool:
    """Whether two palettes are one visual direction rather than two.

    Ground and accent only. `fg` follows the ground almost by construction — a light ground
    takes a dark ink — and `muted` is derived from one of the other two in every palette
    observed, so including either would count the same decision twice.
    """
    return (
        delta_e(first["accent"], second["accent"]) < ACCENT_SAME_DELTA_E
        and delta_e(first["bg"], second["bg"]) < BG_SAME_DELTA_E
    )
