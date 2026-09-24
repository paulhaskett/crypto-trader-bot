from datetime import datetime, timedelta, timezone

from src.entry_confirmation import confirm_trough_rebound


def candles(closes, lows=None):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    lows = lows or closes
    rows = []
    for i, (close, low) in enumerate(zip(closes, lows)):
        rows.append({
            "timestamp": (now - timedelta(hours=len(closes) - 1 - i)).isoformat(),
            "open": close,
            "high": close * 1.002,
            "low": low,
            "close": close,
        })
    return rows


def test_rejects_sequence_still_making_lower_lows():
    prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91]
    result = confirm_trough_rebound(candles(prices), 91, lookback=8, atr_period=4)
    assert not result.confirmed
    assert "rebound" in result.reason or "recent" in result.reason


def test_confirms_two_closes_after_atr_scaled_rebound():
    prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 95, 96]
    rows = candles(prices, lows=[99.5, 98.5, 97.5, 96.5, 95.5, 94.5, 93.5, 92.5, 91, 94.5, 95.5])
    result = confirm_trough_rebound(
        rows,
        96,
        lookback=8,
        atr_period=4,
        atr_multiplier=0.5,
        min_rebound_pct=0.01,
        confirmation_closes=2,
    )
    assert result.confirmed
    assert result.candidate_low == 91
    assert result.confirmation_level > result.candidate_low


def test_rejects_stale_candles():
    rows = candles([100, 99, 98, 97, 96, 95, 94, 93, 92, 95, 96])
    for row in rows:
        row["timestamp"] = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
    result = confirm_trough_rebound(rows, 96, lookback=8, atr_period=4)
    assert not result.confirmed
    assert "stale" in result.reason
