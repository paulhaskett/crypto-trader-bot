"""ATR-scaled price-action confirmation for initial long entries.

This module deliberately waits for evidence that a trough has formed instead of
trying to predict the exact low. It is pure and side-effect free so the rule can
be replayed safely in tests and historical analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from src.feature_engineering import calculate_atr


@dataclass(frozen=True)
class EntryConfirmation:
    """Decision and audit fields for an initial BUY candidate."""

    confirmed: bool
    reason: str
    candidate_low: float = 0.0
    confirmation_level: float = 0.0
    atr: float = 0.0
    atr_pct: float = 0.0
    candle_timestamp: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return JSON/log-friendly confirmation data."""
        return {
            "confirmed": self.confirmed,
            "reason": self.reason,
            "candidate_low": self.candidate_low,
            "confirmation_level": self.confirmation_level,
            "atr": self.atr,
            "atr_pct": self.atr_pct,
            "candle_timestamp": self.candle_timestamp,
        }


def _timestamp(value: Any) -> datetime | None:
    """Parse a candle timestamp and normalise it to an aware UTC datetime."""
    try:
        parsed = pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def confirm_trough_rebound(
    candles: Sequence[Mapping[str, Any]],
    current_price: float,
    *,
    lookback: int = 12,
    atr_period: int = 24,
    atr_multiplier: float = 0.75,
    min_rebound_pct: float = 0.005,
    confirmation_closes: int = 2,
    max_candle_age_hours: float = 3.0,
) -> EntryConfirmation:
    """Confirm a local trough followed by an ATR-scaled rebound.

    The final candle in ``candles`` must be a completed candle. A candidate is
    accepted only when the latest ``confirmation_closes`` closes are above the
    candidate low plus the required rebound. This makes a lower-low sequence
    remain pending rather than buying into continuing weakness.
    """
    if current_price <= 0:
        return EntryConfirmation(False, "invalid current price")
    if lookback < 3 or atr_period < 2 or confirmation_closes < 1:
        return EntryConfirmation(False, "invalid confirmation configuration")
    if atr_multiplier <= 0 or min_rebound_pct <= 0:
        return EntryConfirmation(False, "invalid rebound configuration")

    rows: list[dict[str, Any]] = []
    for candle in candles:
        try:
            row = {
                "timestamp": candle["timestamp"],
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if min(row["open"], row["high"], row["low"], row["close"]) <= 0:
            continue
        rows.append(row)

    if len(rows) < max(lookback, atr_period, confirmation_closes + 2):
        return EntryConfirmation(False, "insufficient completed candles")

    frame = pd.DataFrame(rows)
    frame["parsed_timestamp"] = frame["timestamp"].map(_timestamp)
    frame = frame.dropna(subset=["parsed_timestamp"]).sort_values("parsed_timestamp")
    if len(frame) < max(lookback, atr_period, confirmation_closes + 2):
        return EntryConfirmation(False, "insufficient valid candles")

    latest_time = frame.iloc[-1]["parsed_timestamp"]
    age_hours = (datetime.now(timezone.utc) - latest_time).total_seconds() / 3600
    if age_hours > max_candle_age_hours:
        return EntryConfirmation(False, f"latest candle is stale ({age_hours:.1f}h)")

    # ATR is calculated from all available completed candles; the candidate low
    # is found only in the recent window so old lows do not block new setups.
    atr_series = calculate_atr(frame.rename(columns={"close": "close"}), period=atr_period)
    atr = float(atr_series.iloc[-1])
    if atr <= 0:
        return EntryConfirmation(False, "ATR unavailable")

    recent = frame.tail(lookback).copy()
    trough_index = recent["low"].idxmin()
    trough_pos = recent.index.get_loc(trough_index)
    candidate_low = float(recent.loc[trough_index, "low"])
    required_rebound = max(atr_multiplier * atr / current_price, min_rebound_pct)
    confirmation_level = candidate_low * (1.0 + required_rebound)

    closes = recent["close"].tail(confirmation_closes)
    if len(closes) < confirmation_closes:
        return EntryConfirmation(False, "insufficient confirmation closes", candidate_low, confirmation_level, atr, atr / current_price)
    if trough_pos >= len(recent) - confirmation_closes:
        return EntryConfirmation(False, "trough is too recent; waiting for rebound", candidate_low, confirmation_level, atr, atr / current_price)
    if not bool((closes > confirmation_level).all()):
        return EntryConfirmation(False, "rebound not confirmed", candidate_low, confirmation_level, atr, atr / current_price)
    if current_price <= confirmation_level:
        return EntryConfirmation(False, "consensus price fell below confirmation level", candidate_low, confirmation_level, atr, atr / current_price)

    return EntryConfirmation(
        True,
        "trough rebound confirmed",
        candidate_low,
        confirmation_level,
        atr,
        atr / current_price,
        str(latest_time),
    )
