"""Tests for currency_utils."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.currency_utils import CurrencyConverter


def test_same_currency_identity():
    utils = CurrencyConverter()
    assert utils.convert_amount(50.0, 'GBP', 'GBP') == 50.0
    assert utils.convert_amount(75.0, 'USD', 'USD') == 75.0


def test_gbp_to_usd_conversion():
    utils = CurrencyConverter()
    result = utils.convert_amount(100.0, 'GBP', 'USD')
    assert result > 0


def test_usd_to_gbp_conversion():
    utils = CurrencyConverter()
    result = utils.convert_amount(100.0, 'USD', 'GBP')
    assert result > 0


def test_rates_populated_after_init():
    utils = CurrencyConverter()
    rate = utils.get_exchange_rate('GBP', 'USD')
    assert isinstance(rate, float)
    assert rate > 0
