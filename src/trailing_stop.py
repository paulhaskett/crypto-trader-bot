"""Shared ATR-based trailing-stop calculations.

The trading engine and dashboard must report the same stop economics.  This
module keeps the calculation pure so it can be tested without Coinbase, DB,
or historical-data network calls.

Security/correctness invariants:
- The effective trailing percentage is capped at 5%.
- The final stop respects the break-even and minimum-locked-profit floors.
- This helper never authorises a sell; execution must still enforce the
  break-even guard against the actual trigger price.
"""

from typing import Any, Dict, Optional


def calculate_trailing_stop(
    *,
    current_price: float,
    entry_price: float,
    peak_price: float,
    regime: str,
    atr: Optional[float],
    fixed_stop: float,
    regime_stops: Dict[str, float],
    atr_multiplier: float,
    max_stop: float,
    maker_fee: float,
    taker_fee: float,
    activation_buffer: float,
    min_locked_profit: float,
) -> Dict[str, Any]:
    """Calculate display/execution stop values from one set of inputs.

    ``atr`` is optional because historical candles may be unavailable.  A
    missing ATR falls back to the fixed/regime floor and is explicitly marked
    unavailable rather than being represented as zero volatility.
    """
    current_price = max(float(current_price or 0), 0.0)
    entry_price = max(float(entry_price or 0), 0.0)
    peak_price = max(float(peak_price or entry_price), entry_price)
    atr_value = float(atr) if atr is not None and float(atr) >= 0 else None
    atr_pct = atr_value / current_price if atr_value is not None and current_price > 0 else None
    atr_based_stop_pct = atr_pct * atr_multiplier if atr_pct is not None else None

    regime_stop = float(regime_stops.get(regime, fixed_stop))
    candidates = [float(fixed_stop), regime_stop]
    if atr_based_stop_pct is not None:
        candidates.append(atr_based_stop_pct)
    trailing_pct = min(max(candidates), float(max_stop))

    total_fee = float(maker_fee) + float(taker_fee)
    break_even = entry_price * (1.0 + total_fee)
    activation_threshold = break_even * (1.0 + float(activation_buffer))
    stop_floor = break_even * (1.0 - trailing_pct)
    min_trail_stop = entry_price * (1.0 + float(min_locked_profit))
    natural_stop = peak_price * (1.0 - trailing_pct)
    trailing_stop = max(natural_stop, stop_floor, min_trail_stop)
    stop_distance = max(current_price - trailing_stop, 0.0)

    return {
        "atr": atr_value,
        "atr_available": atr_value is not None,
        "atr_pct": atr_pct,
        "atr_based_stop_pct": atr_based_stop_pct,
        "trailing_pct": trailing_pct,
        "break_even": break_even,
        "activation_threshold": activation_threshold,
        "stop_floor": stop_floor,
        "min_trail_stop": min_trail_stop,
        "trailing_stop": trailing_stop,
        "stop_distance": stop_distance,
        "stop_distance_pct": stop_distance / current_price if current_price > 0 else None,
        "trailing_activated": peak_price >= activation_threshold and current_price >= break_even,
    }
