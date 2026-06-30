"""Tests for price_mapper."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.price_mapper import get_price_mapper


def test_coingecko_id():
    mapper = get_price_mapper()
    assert mapper.get_coingecko_id('BTC-GBP') == 'bitcoin'
    assert mapper.get_coingecko_id('ETH-GBP') == 'ethereum'


def test_quote_currency():
    mapper = get_price_mapper()
    assert mapper.get_quote_currency('BTC-GBP') == 'GBP'
    assert mapper.get_quote_currency('BTC-USD') == 'USD'


def test_kraken_pair():
    mapper = get_price_mapper()
    assert mapper.get_kraken_pair('BTC-GBP') == 'XXBTZGBP'
    assert mapper.get_kraken_pair('ETH-GBP') == 'XETHZGBP'


def test_binance_symbol():
    mapper = get_price_mapper()
    assert mapper.get_binance_symbol('BTC-GBP') == 'BTCGBP'
    assert mapper.get_binance_symbol('ETH-GBP') == 'ETHGBP'
