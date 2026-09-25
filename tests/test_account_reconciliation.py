from src.coinbase_api import CoinbaseAPI


def test_account_api_failure_is_not_reported_as_fake_balances():
    api = CoinbaseAPI.__new__(CoinbaseAPI)
    api.api_key = "live-key"
    api.last_accounts_fetch_ok = True
    api._make_request = lambda *args, **kwargs: None

    assert api.get_accounts() == []
    assert api.last_accounts_fetch_ok is False
    assert api.get_account_balance("SOL") == 0.0
    assert api.last_accounts_fetch_ok is False


def test_valid_empty_account_response_is_a_real_zero_balance():
    api = CoinbaseAPI.__new__(CoinbaseAPI)
    api.api_key = "live-key"
    api.last_accounts_fetch_ok = False
    api._make_request = lambda *args, **kwargs: {"accounts": []}

    assert api.get_accounts() == []
    assert api.last_accounts_fetch_ok is True
    assert api.get_account_balance("SOL") == 0.0
    assert api.last_accounts_fetch_ok is True
