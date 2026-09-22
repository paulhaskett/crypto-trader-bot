"""Regression tests for GBP wallet valuation."""

import pytest

from src.portfolio_utils import account_value_gbp


def test_gbp_balance_is_unchanged():
    assert account_value_gbp("GBP", 139.97, 0.75, 0.85) == pytest.approx(139.97)


def test_usdc_is_converted_to_gbp():
    assert account_value_gbp("USDC", 1.0, 0.75, 0.85) == pytest.approx(0.75)


def test_eur_is_converted_to_gbp():
    assert account_value_gbp("EUR", 10.0, 0.75, 0.85) == pytest.approx(8.5)


def test_unsupported_currency_is_not_silently_valued():
    with pytest.raises(ValueError):
        account_value_gbp("BTC", 1.0, 0.75, 0.85)
