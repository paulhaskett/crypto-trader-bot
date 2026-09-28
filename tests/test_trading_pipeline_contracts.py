"""Contract tests for deterministic trading-pipeline fixtures.

Module 0 establishes reusable fixtures before behavior changes land. These
checks prove that tests can distinguish verified, ambiguous, cancelled, and
unavailable exchange states without touching live credentials or the real DB.
"""

from tests.fakes.coinbase import (
    FakeCoinbaseGateway,
    ambiguous_order,
    cancelled_order,
    filled_order,
)


def test_gateway_records_exactly_one_submitted_order():
    gateway = FakeCoinbaseGateway(order_responses=[ambiguous_order()])

    result = gateway.place_order("BTC-GBP", "buy", 0.01)

    assert result["status"] == "OPEN"
    assert gateway.submitted_order_count == 1
    assert gateway.order_calls == [{"product_id": "BTC-GBP", "side": "buy", "size": 0.01}]


def test_fixture_sequence_distinguishes_filled_and_cancelled_orders():
    gateway = FakeCoinbaseGateway(order_responses=[filled_order(), cancelled_order()])

    first = gateway.place_order("ETH-GBP", "buy", 0.1)
    second = gateway.place_order("ETH-GBP", "buy", 0.1)

    assert first["success"] is True
    assert first["status"] == "FILLED"
    assert second["success"] is False
    assert second["status"] == "CANCELLED"
    assert gateway.submitted_order_count == 2


def test_account_and_price_unavailability_are_distinguishable():
    gateway = FakeCoinbaseGateway(accounts_available=False, prices={})

    assert gateway.get_accounts() is None
    assert gateway.get_price("SOL-GBP") is None

    gateway.accounts_available = True
    gateway.accounts = [{"currency": "GBP", "available": 25.0}]
    gateway.prices["SOL-GBP"] = 90.0

    assert gateway.get_accounts() == [{"currency": "GBP", "available": 25.0}]
    assert gateway.get_price("SOL-GBP") == 90.0
