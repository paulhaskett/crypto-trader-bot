"""Reusable fake exchange fixtures for trading-pipeline contract tests.

These fakes model order ambiguity and account/price availability without making
network calls or touching the live trading database. Tests can use the call
history to prove that ambiguous orders are not retried or duplicated.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class FakeCoinbaseGateway:
    """Deterministic Coinbase-like gateway with explicit response sequences."""

    order_responses: List[Dict[str, Any]] = field(default_factory=list)
    accounts: List[Dict[str, Any]] = field(default_factory=list)
    accounts_available: bool = True
    prices: Dict[str, float] = field(default_factory=dict)
    order_calls: List[Dict[str, Any]] = field(default_factory=list)

    def place_order(self, product_id: str, side: str, size: float) -> Dict[str, Any]:
        """Record one submission and return the next deterministic response."""
        self.order_calls.append({"product_id": product_id, "side": side, "size": size})
        if not self.order_responses:
            return {"success": False, "error": "No fixture response configured"}
        return self.order_responses.pop(0)

    def get_accounts(self) -> Optional[List[Dict[str, Any]]]:
        """Return accounts or None to model an unavailable account read."""
        return self.accounts if self.accounts_available else None

    def get_price(self, product_id: str) -> Optional[float]:
        """Return a configured quote or None to model unavailable market data."""
        return self.prices.get(product_id)

    @property
    def submitted_order_count(self) -> int:
        """Expose order count for duplicate-submission assertions."""
        return len(self.order_calls)


def filled_order(order_id: str = "order-1", size: float = 1.0, price: float = 100.0, fees: float = 0.1) -> Dict[str, Any]:
    """Build a verified-fill response fixture."""
    return {
        "success": True,
        "order_id": order_id,
        "status": "FILLED",
        "size": size,
        "price": price,
        "fees": fees,
    }


def ambiguous_order(order_id: str = "order-ambiguous") -> Dict[str, Any]:
    """Build an order response whose outcome requires reconciliation."""
    return {
        "success": False,
        "order_id": order_id,
        "status": "OPEN",
        "error": "Fill status unavailable",
    }


def cancelled_order(order_id: str = "order-cancelled") -> Dict[str, Any]:
    """Build a definitive failed-order fixture."""
    return {
        "success": False,
        "order_id": order_id,
        "status": "CANCELLED",
        "error": "Order cancelled",
    }
