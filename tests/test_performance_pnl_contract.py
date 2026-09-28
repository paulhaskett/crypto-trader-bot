"""Tests for canonical realized-P&L fields on the performance API."""

import asyncio
from datetime import datetime

from src import api_worker
import src.database as database_module


class FakePerformanceDB:
    def get_trades(self, limit=10000):
        return [{
            "id": 1,
            "product_id": "BTC-GBP",
            "side": "sell",
            "size": 0.1,
            "price": 50000,
            "fees": 1.2,
            "pnl": 15.0,
            "status": "filled",
            "trade_type": "live",
            "timestamp": datetime(2026, 9, 28, 12, 0),
        }]

    def get_closed_positions(self, limit=10000):
        return [{
            "position_id": "position-1",
            "product_id": "BTC-GBP",
            "pnl": 98.8,
            "trade_type": "live",
        }]


def test_performance_uses_lifecycle_pnl_not_fill_pnl(monkeypatch):
    monkeypatch.setattr(database_module, "db_manager", FakePerformanceDB())

    result = asyncio.run(api_worker.get_performance(min_trades=1))

    assert result["financials"]["realized_pnl"] == 98.8
    assert result["financials"]["fees"] == 1.2
    assert result["financials"]["pnl_source"] == "closed position lifecycle"
    assert result["summary"]["total_pnl"] == 98.8
