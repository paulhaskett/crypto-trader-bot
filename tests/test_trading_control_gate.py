"""Tests for the persisted trading-active entry gate."""

from src import trading_engine


class FakeDatabase:
    def __init__(self, active):
        self.active = active

    def get_trading_active(self):
        return self.active


def make_engine():
    engine = trading_engine.TradingEngine.__new__(trading_engine.TradingEngine)
    engine.last_trade_time = {}
    engine.holdings = {}
    engine.active_positions = {}
    return engine


def test_stopped_trading_blocks_new_entries(monkeypatch):
    monkeypatch.setattr(trading_engine, "db_manager", FakeDatabase(False))

    assert make_engine()._should_trade_product("BTC-GBP") is False


def test_active_trading_can_evaluate_new_entries(monkeypatch):
    monkeypatch.setattr(trading_engine, "db_manager", FakeDatabase(True))

    assert make_engine()._should_trade_product("BTC-GBP") is True
