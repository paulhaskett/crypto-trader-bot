"""Tests for fail-closed manual close and reconciliation behavior."""

import asyncio

from src import api_worker
import src.database as database_module
import src.coinbase_api as coinbase_module
import src.risk_manager as risk_module


class FakeDB:
    def __init__(self, paper=False):
        self.paper = paper
        self.closed = False
        self.saved = 0

    def get_all_open_positions_detailed(self):
        return [{"position_id": "p1", "product_id": "BTC-GBP", "entry_price": 100.0, "remaining_size": 1.0}]

    def get_paper_trading(self):
        return self.paper

    def close_open_position(self, *args):
        self.closed = True
        return True

    def load_open_positions(self, trade_type='live'):
        return {"BTC-GBP": {"side": "buy", "entry_price": 100.0, "size": 1.0}}

    def save_open_position(self, data):
        self.saved += 1
        return True


class FallbackCoinbase:
    last_accounts_fetch_ok = False

    def get_product_ticker(self, product_id):
        return {"price": 200.0, "is_fallback": True, "data_status": "unavailable"}

    def get_accounts(self):
        return []


class FakeRisk:
    def close_position(self, *args):
        raise AssertionError("risk close must not run")


def test_manual_close_rejects_unavailable_price_before_order(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(database_module, "db_manager", db)
    monkeypatch.setattr(coinbase_module, "coinbase_api", FallbackCoinbase())
    monkeypatch.setattr(risk_module, "risk_manager", FakeRisk())

    result = asyncio.run(api_worker.close_position("p1"))

    assert result["status"] == "error"
    assert result["result_code"] == "price_unavailable"
    assert db.closed is False


def test_resync_rejects_account_failure_without_writes(monkeypatch):
    db = FakeDB()
    coinbase = FallbackCoinbase()
    monkeypatch.setattr(api_worker, "load_db_manager", lambda: db)
    monkeypatch.setattr(database_module, "db_manager", db)
    monkeypatch.setattr(coinbase_module, "coinbase_api", coinbase)

    result = asyncio.run(api_worker.control_action("resync"))

    assert result["status"] == "error"
    assert result["result_code"] == "account_fetch_unavailable"
    assert db.saved == 0
