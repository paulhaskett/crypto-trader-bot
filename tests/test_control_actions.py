"""Tests for persisted dashboard control commands."""

import asyncio

from src import api_worker


class FakeDatabase:
    def __init__(self, active=False):
        self.active = active

    def set_trading_active(self, active):
        self.active = active
        return True

    def get_trading_active(self):
        return self.active


def test_start_and_stop_are_persisted_and_read_back(monkeypatch):
    db = FakeDatabase()
    monkeypatch.setattr(api_worker, "load_db_manager", lambda: db)

    started = asyncio.run(api_worker.control_action("start"))
    stopped = asyncio.run(api_worker.control_action("stop"))

    assert started["status"] == "success"
    assert started["command_state"] == "acknowledged"
    assert started["trading_active"] is True
    assert stopped["status"] == "success"
    assert stopped["command_state"] == "acknowledged"
    assert stopped["trading_active"] is False


def test_emergency_stop_persists_inactive_state(monkeypatch):
    db = FakeDatabase(active=True)
    monkeypatch.setattr(api_worker, "load_db_manager", lambda: db)

    result = asyncio.run(api_worker.control_action("emergency_stop"))

    assert result["status"] == "success"
    assert result["command_state"] == "acknowledged"
    assert result["trading_active"] is False


def test_generic_retrain_control_is_rejected(monkeypatch):
    monkeypatch.setattr(api_worker, "load_db_manager", lambda: FakeDatabase())

    result = asyncio.run(api_worker.control_action("retrain"))

    assert result["status"] == "error"
    assert result["command_state"] == "unsupported"
    assert "/api/models/retrain" in result["message"]
