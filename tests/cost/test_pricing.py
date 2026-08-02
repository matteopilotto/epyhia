from datetime import date, datetime
from unittest.mock import patch

import pytest

from epyhia.cost.pricing import UnknownModel, rate_for

_FIXTURE_MODELS = {
    "test-model": {
        "tier": "checking",
        "rates": [
            {
                "effective_from": date(2026, 1, 1),
                "input": 1.0,
                "output": 2.0,
                "cache_write": 3.0,
                "cache_read": 4.0,
            },
            {
                "effective_from": date(2026, 6, 1),
                "input": 10.0,
                "output": 20.0,
                "cache_write": 30.0,
                "cache_read": 40.0,
            },
        ],
    }
}


def test_effective_dated_selection_picks_the_right_row_across_a_rate_change() -> None:
    with patch("epyhia.cost.pricing._MODELS", _FIXTURE_MODELS):
        before_change = rate_for("test-model", datetime(2026, 3, 1))
        assert before_change.input == 1.0

        on_change_day = rate_for("test-model", datetime(2026, 6, 1))
        assert on_change_day.input == 10.0

        after_change = rate_for("test-model", datetime(2026, 12, 1))
        assert after_change.input == 10.0


def test_unknown_model_raises_rather_than_costing_zero() -> None:
    with patch("epyhia.cost.pricing._MODELS", _FIXTURE_MODELS):
        with pytest.raises(UnknownModel):
            rate_for("no-such-model", datetime(2026, 6, 1))


def test_timestamp_before_any_rate_row_raises() -> None:
    with patch("epyhia.cost.pricing._MODELS", _FIXTURE_MODELS):
        with pytest.raises(UnknownModel):
            rate_for("test-model", datetime(2025, 1, 1))
