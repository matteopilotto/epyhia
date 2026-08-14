"""The perceptual distance, checked against the sample that motivated it.

The palettes below are measurements, not client data: they are the ground and accent of the
three brand docs recorded in `specs/003-distinctive-sites/evidence.md`, kept here because a
threshold nothing calibrates it against is a number somebody liked the look of. No business
name, price or currency reaches this file, and nothing here reads a brief.
"""

import pytest

from epyhia.design.colour import (
    ACCENT_SAME_DELTA_E,
    BG_SAME_DELTA_E,
    delta_e,
    lab,
    same_direction,
)

# The three sampled directions a reader called one direction: warm cream ground, near-black
# brown ink, burnt-orange accent.
SAMPLED = (
    {"bg": "#F3EBDF", "fg": "#241C16", "accent": "#B5451B", "muted": "#6B5D50"},
    {"bg": "#f3eee3", "fg": "#1b1916", "accent": "#b4571f", "muted": "#6a6154"},
    {"bg": "#F1EDE4", "fg": "#1B1A17", "accent": "#B23A16", "muted": "#5F5B51"},
)

# Two directions the same evidence records as drafted and rejected: a dark ground with a
# brighter orange, and a single saturated teal with a yellow accent.
DARK = {"bg": "#14161A", "fg": "#E8E4DC", "accent": "#E4762B", "muted": "#8A8F98"}
TEAL = {"bg": "#0F4F44", "fg": "#F2F5F0", "accent": "#F0C64A", "muted": "#7FA79C"}


def test_the_extremes_span_the_lightness_axis() -> None:
    """White to black is the full L* range, which is what fixes the scale every threshold
    here is expressed on.

    The tolerance is 1e-3 rather than exact because the D65 white point is written to five
    decimals, which leaves white a ten-thousandth off neutral. That is four orders below the
    smallest difference an eye can see and six below any threshold here.
    """
    assert lab("#ffffff") == pytest.approx((100.0, 0.0, 0.0), abs=1e-3)
    assert lab("#000000") == pytest.approx((0.0, 0.0, 0.0), abs=1e-3)
    assert delta_e("#ffffff", "#000000") == pytest.approx(100.0, abs=1e-3)


def test_a_colour_is_zero_from_itself_however_it_is_spelled() -> None:
    assert delta_e("#B5451B", "#b5451b") == 0.0
    assert delta_e("B5451B", "#B5451B") == 0.0


def test_distance_is_symmetric() -> None:
    for first, second in ((SAMPLED[0], SAMPLED[1]), (SAMPLED[0], TEAL)):
        for slot in ("bg", "fg", "accent", "muted"):
            assert delta_e(first[slot], second[slot]) == pytest.approx(
                delta_e(second[slot], first[slot])
            )


@pytest.mark.parametrize("index", (1, 2))
def test_the_three_sampled_palettes_are_one_direction(index: int) -> None:
    """The calibration. Whatever bar this module picks, it has to agree with the reading
    those three samples already got — otherwise the measurement is answering a question
    nobody asked."""
    assert same_direction(SAMPLED[0], SAMPLED[index])
    assert same_direction(SAMPLED[index], SAMPLED[0])


@pytest.mark.parametrize("other", (DARK, TEAL), ids=("dark", "teal"))
def test_a_rejected_direction_is_not_the_committed_one(other: dict[str, str]) -> None:
    for sample in SAMPLED:
        assert not same_direction(sample, other)


def test_the_ground_is_what_separates_the_dark_direction() -> None:
    """Its accent is inside the accent bar — ΔE 17 from one sampled orange — so a check on
    the accent alone would call a dark poster the same direction as a cream page."""
    assert delta_e(SAMPLED[1]["accent"], DARK["accent"]) < ACCENT_SAME_DELTA_E
    assert delta_e(SAMPLED[1]["bg"], DARK["bg"]) > BG_SAME_DELTA_E


def test_a_six_digit_hex_is_the_only_spelling_accepted() -> None:
    """The brand doc schema admits no other, and silently reading a three-digit colour as
    something else would put a wrong number into a report that looks right."""
    with pytest.raises(ValueError):
        delta_e("#fff", "#000000")
