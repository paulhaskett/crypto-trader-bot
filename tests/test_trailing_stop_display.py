"""Regression tests for shared trailing-stop and ATR display calculations."""

from src.trailing_stop import calculate_trailing_stop


KWARGS = dict(
    current_price=105.0,
    entry_price=100.0,
    peak_price=108.0,
    regime="neutral",
    fixed_stop=0.005,
    regime_stops={"neutral": 0.005},
    atr_multiplier=2.5,
    max_stop=0.05,
    maker_fee=0.0035,
    taker_fee=0.0075,
    activation_buffer=0.0,
    min_locked_profit=0.005,
)


def test_atr_drives_effective_trailing_percentage():
    result = calculate_trailing_stop(atr=2.0, **KWARGS)

    assert result["atr_available"] is True
    assert result["atr_pct"] == 2.0 / 105.0
    assert result["atr_based_stop_pct"] == 2.0 / 105.0 * 2.5
    assert result["trailing_pct"] == result["atr_based_stop_pct"]


def test_missing_atr_falls_back_without_faking_zero_volatility():
    result = calculate_trailing_stop(atr=None, **KWARGS)

    assert result["atr_available"] is False
    assert result["atr"] is None
    assert result["atr_pct"] is None
    assert result["trailing_pct"] == 0.005


def test_stop_respects_break_even_and_locked_profit_floors():
    result = calculate_trailing_stop(atr=0.1, **KWARGS)

    assert result["trailing_stop"] >= result["break_even"] * (1 - result["trailing_pct"])
    assert result["trailing_stop"] >= result["min_trail_stop"]
    assert result["trailing_activated"] is True


def test_effective_trailing_percentage_is_capped():
    result = calculate_trailing_stop(atr=100.0, **KWARGS)

    assert result["trailing_pct"] == 0.05
