"""Tests for the canonical non-double-counted ledger response."""

import asyncio

from src import api_worker


class FakeLedgerDB:
    def get_trades(self, limit=500):
        return [{
            "id": 7,
            "order_id": "order-7",
            "product_id": "BTC-GBP",
            "side": "sell",
            "size": 0.1,
            "price": 50000,
            "fees": 1.2,
            "pnl": 12.3,
            "status": "filled",
            "trade_type": "live",
            "timestamp": "2026-09-28T12:00:00",
        }]

    def get_closed_positions(self, limit=500):
        return [{
            "position_id": "position-1",
            "product_id": "BTC-GBP",
            "side": "buy",
            "size": 0.1,
            "entry_price": 49000,
            "exit_price": 50000,
            "pnl": 98.8,
            "exit_reason": "manual_close",
            "trade_type": "live",
            "opened_at": "2026-09-27T12:00:00",
            "closed_at": "2026-09-28T12:00:01",
        }]


def test_ledger_separates_fills_and_position_lifecycles(monkeypatch):
    monkeypatch.setattr(api_worker, "load_db_manager", lambda: FakeLedgerDB())

    result = asyncio.run(api_worker.get_canonical_ledger())

    assert result["status"] == "success"
    assert result["summary"]["fill_count"] == 1
    assert result["summary"]["position_lifecycle_count"] == 1
    assert result["summary"]["realized_pnl"] == 98.8
    assert result["fills"][0]["row_type"] == "fill"
    assert result["position_lifecycles"][0]["row_type"] == "position_lifecycle"
    assert result["fills"][0]["row_id"] != result["position_lifecycles"][0]["row_id"]


def test_ledger_does_not_add_fill_and_lifecycle_pnl_together(monkeypatch):
    monkeypatch.setattr(api_worker, "load_db_manager", lambda: FakeLedgerDB())

    result = asyncio.run(api_worker.get_canonical_ledger())

    assert result["summary"]["realized_pnl"] == 98.8
    assert result["summary"]["realized_pnl"] != 98.8 + 12.3
