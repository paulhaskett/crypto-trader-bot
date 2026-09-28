"""Module 1 tests for fail-closed account, price, and risk boundaries."""

from src import balance_manager as balance_module
from src import risk_manager as risk_module


class FailedAccounts:
    last_accounts_fetch_ok = False

    def get_accounts(self):
        return []


def make_risk_manager():
    manager = risk_module.RiskManager.__new__(risk_module.RiskManager)
    manager.portfolio_value = 0.0
    manager.portfolio_data_available = False
    manager.portfolio_data_reason = 'not_loaded'
    manager.daily_pnl = 0.0
    manager.daily_start_time = None
    manager.open_positions = {}
    return manager


def test_live_portfolio_failure_never_uses_paper_value(monkeypatch):
    monkeypatch.setattr(risk_module, 'coinbase_api', FailedAccounts())
    manager = make_risk_manager()

    manager._update_portfolio_value(is_paper_trading=False)

    assert manager.portfolio_value == 0.0
    assert manager.portfolio_data_available is False
    assert 'unavailable' in manager.portfolio_data_reason.lower()


def test_balance_manager_blocks_when_account_read_is_unavailable(monkeypatch):
    monkeypatch.setattr(balance_module, 'coinbase_api', FailedAccounts())
    manager = balance_module.BalanceManager()

    status = manager.check_gbp_balance()
    allowed, reason = manager.should_trade(10.0)

    assert status['trading_allowed'] is False
    assert status['data_status'] == 'unavailable'
    assert allowed is False
    assert 'unavailable' in reason.lower()
