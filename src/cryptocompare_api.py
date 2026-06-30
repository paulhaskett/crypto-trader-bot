"""
CryptoCompare API wrapper — backed by CoinGecko (free, no API key).

This module provides the same interface as the original CryptoCompare wrapper
but uses CoinGecko's free API under the hood, since CryptoCompare/CoinDesk
now requires a paid API key for all endpoints.

API Documentation: https://www.coingecko.com/en/api
Free Tier: 10-30 calls/minute (no API key required)
"""

import logging
import time
from typing import Dict, List, Any, Optional

import requests

logger = logging.getLogger(__name__)


class CryptoCompareAPIError(Exception):
    """Custom exception for CryptoCompare API errors."""
    pass


class CryptoCompareAPI:
    """
    CryptoCompare-style API client backed by CoinGecko.

    Provides price data from 100+ exchanges, offering better global
    price discovery than single-exchange APIs.
    """

    # CoinGecko base URL
    BASE_URL = "https://api.coingecko.com/api/v3"

    # Symbol -> CoinGecko ID mapping
    SYMBOL_TO_COINGECKO = {
        'BTC': 'bitcoin',
        'ETH': 'ethereum',
        'SOL': 'solana',
        'LTC': 'litecoin',
        'DOT': 'polkadot',
        'ADA': 'cardano',
        'LINK': 'chainlink',
        'UNI': 'uniswap',
    }

    # Original CryptoCompare product mapping (kept for backwards compat)
    COINBASE_TO_CRYPTOCOMPARE = {
        'BTC-GBP': 'BTC',
        'ETH-GBP': 'ETH',
        'SOL-GBP': 'SOL',
        'LTC-GBP': 'LTC',
        'DOT-GBP': 'DOT',
        'ADA-GBP': 'ADA',
        'LINK-GBP': 'LINK',
        'UNI-GBP': 'UNI',
    }

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize CoinGecko-backed price client.

        Args:
            api_key: Ignored (CoinGecko free tier doesn't require a key).
                      Accepted for backwards compatibility.
        """
        self.api_key = api_key
        self.session = requests.Session()

        # Rate limiting - free tier: 10-30/min
        self._last_request_time = 0
        self._min_request_interval = 2.5  # Safe for free tier

        # Cache
        self._price_cache: Dict[str, Any] = {}
        self._cache_ttl = 30  # seconds

    def _rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make request to CoinGecko API with rate limiting."""
        self._rate_limit()

        url = f"{self.BASE_URL}{endpoint}"
        headers = {'Accept': 'application/json'}

        if self.api_key:
            headers['x-cg-demo-api-key'] = self.api_key

        try:
            response = self.session.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            # Check if it's a rate limit (429)
            if isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code == 429:
                raise CryptoCompareAPIError("Rate limit exceeded")
            raise CryptoCompareAPIError(f"Request failed: {e}")

    def _symbol_to_coingecko(self, symbol: str) -> Optional[str]:
        """Convert a crypto symbol (BTC, ETH) to CoinGecko ID (bitcoin, ethereum)."""
        return self.SYMBOL_TO_COINGECKO.get(symbol.upper())

    def get_price(self, symbol: str, currency: str = 'GBP') -> Optional[float]:
        """
        Get price for a single cryptocurrency.

        Args:
            symbol: Crypto symbol (e.g., 'BTC', 'ETH')
            currency: Target currency (default: 'GBP')

        Returns:
            Price as float or None
        """
        coin_id = self._symbol_to_coingecko(symbol)
        if not coin_id:
            logger.warning(f"No CoinGecko mapping for symbol: {symbol}")
            return None

        cache_key = f"{coin_id}_{currency.lower()}"
        if cache_key in self._price_cache:
            cached_time, cached_price = self._price_cache[cache_key]
            if (time.time() - cached_time) < self._cache_ttl:
                return cached_price

        try:
            params = {
                'ids': coin_id,
                'vs_currencies': currency.lower(),
            }

            data = self._request('/simple/price', params)

            if coin_id in data and currency.lower() in data[coin_id]:
                price = float(data[coin_id][currency.lower()])
                self._price_cache[cache_key] = (time.time(), price)
                return price

        except CryptoCompareAPIError as e:
            logger.warning(f"CoinGecko price fetch failed for {symbol}: {e}")

        return None

    def get_prices_batch(self, symbols: List[str], currencies: List[str] = None) -> Dict:
        """
        Get prices for multiple cryptocurrencies efficiently.

        Args:
            symbols: List of crypto symbols (e.g., ['BTC', 'ETH'])
            currencies: Target currencies (default: ['GBP', 'USD'])

        Returns:
            Dict mapping symbol to price data
        """
        if currencies is None:
            currencies = ['GBP', 'USD']

        # Convert symbols to CoinGecko IDs
        coin_ids = []
        valid_symbols = []
        for sym in symbols:
            cid = self._symbol_to_coingecko(sym)
            if cid:
                coin_ids.append(cid)
                valid_symbols.append(sym)

        if not coin_ids:
            return {}

        try:
            params = {
                'ids': ','.join(coin_ids),
                'vs_currencies': ','.join(c.lower() for c in currencies),
            }

            data = self._request('/simple/price', params)

            # Convert back to symbol-based result
            result = {}
            for sym, cid in zip(valid_symbols, coin_ids):
                if cid in data:
                    coin_data = data[cid]
                    entry = {
                        'price': coin_data.get(currencies[0].lower()),
                    }
                    if len(currencies) > 1:
                        entry['price_usd'] = coin_data.get(currencies[1].lower())
                    result[sym] = entry

            return result

        except CryptoCompareAPIError as e:
            logger.warning(f"CoinGecko batch price fetch failed: {e}")
            return {}

    def get_ohlc(self, symbol: str, currency: str = 'GBP', limit: int = 168) -> Optional[List]:
        """
        Get OHLC data via CoinGecko.

        Args:
            symbol: Crypto symbol (e.g., 'BTC', 'ETH')
            currency: Target currency (default: 'GBP')
            limit: Number of hourly data points (max ~168)

        Returns:
            List of [timestamp, open, high, low, close] arrays or None
        """
        coin_id = self._symbol_to_coingecko(symbol)
        if not coin_id:
            return None

        # CoinGecko OHLC is in days, not hours. Map limit to approximate days.
        days = max(1, min(limit // 24 + 1, 90))

        try:
            params = {
                'vs_currency': currency.lower(),
                'days': days,
            }

            data = self._request(f'/coins/{coin_id}/ohlc', params)

            if data and isinstance(data, list):
                return data

        except CryptoCompareAPIError as e:
            logger.warning(f"CoinGecko OHLC fetch failed for {symbol}: {e}")

        return None

    def convert_product_to_symbol(self, product_id: str) -> Optional[str]:
        """Convert Coinbase product ID to crypto symbol (e.g., 'BTC-GBP' -> 'BTC')."""
        return self.COINBASE_TO_CRYPTOCOMPARE.get(product_id)


# Singleton instance
cryptocompare_api: Optional[CryptoCompareAPI] = None


def get_cryptocompare_api() -> CryptoCompareAPI:
    """Get or create CryptoCompare API singleton."""
    global cryptocompare_api
    if cryptocompare_api is None:
        cryptocompare_api = CryptoCompareAPI()
    return cryptocompare_api
