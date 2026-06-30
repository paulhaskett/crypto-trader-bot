"""
CoinGecko API wrapper for aggregated market data.

This module provides access to CoinGecko's free crypto market data API,
which aggregates prices from 100+ exchanges globally.

API Documentation: https://www.coingecko.com/en/api
Free Tier: 10-30 calls/minute (no API key required)
Demo API Key: Available from https://www.coingecko.com/en/api
"""

import logging
import os
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


class CoinGeckoAPIError(Exception):
    """Custom exception for CoinGecko API errors."""
    pass


class CoinGeckoAPI:
    """
    CoinGecko API client for aggregated market data.
    
    Provides price data from 100+ exchanges, offering better global
    price discovery than single-exchange APIs.
    """
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    # CoinGecko ID mapping for supported trading pairs
    COINBASE_TO_COINGECKO = {
        'BTC-GBP': 'bitcoin',
        'ETH-GBP': 'ethereum',
        'SOL-GBP': 'solana',
        'LTC-GBP': 'litecoin',
        'DOT-GBP': 'polkadot',
        'ADA-GBP': 'cardano',
        'LINK-GBP': 'chainlink',
        'UNI-GBP': 'uniswap',
    }
    
    # USD equivalents for risk management
    COINBASE_TO_COINGECKO_USD = {
        'BTC-USD': 'bitcoin',
        'ETH-USD': 'ethereum',
        'SOL-USD': 'solana',
        'LTC-USD': 'litecoin',
        'DOT-USD': 'polkadot',
        'ADA-USD': 'cardano',
        'LINK-USD': 'chainlink',
        'UNI-USD': 'uniswap',
    }
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize CoinGecko API client.
        
        Args:
            api_key: Optional API key for higher rate limits (demo/pro plan)
        """
        # Check for CoinGecko API key in environment
        self.api_key = api_key or os.getenv('COINGECKO_API_KEY')
        self.session = requests.Session()
        
        # Rate limiting - free tier: 10-30/min, demo: 50/min
        self._last_request_time = 0
        self._min_request_interval = 2.0  # 2 seconds between requests (safe for free tier)
        
        # Priority pairs - fetch these first
        self.priority_coins = ['bitcoin', 'ethereum', 'solana', 'litecoin']
        
        # Cache for price data
        self._price_cache: Dict[str, Any] = {}
        self._cache_ttl = 30  # 30 seconds cache for prices
        self._last_fetch: Optional[datetime] = None
        
    def _rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """
        Make request to CoinGecko API with rate limiting.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            JSON response as dictionary
        """
        self._rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            'Accept': 'application/json',
        }
        
        if self.api_key:
            headers['x-cg-demo-api-key'] = self.api_key
            
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                # Rate limited - raise without waiting to allow fast fallback
                logger.debug("CoinGecko rate limited, skipping...")
                raise CoinGeckoAPIError("Rate limit exceeded")
            raise CoinGeckoAPIError(f"HTTP error: {e}")
        except requests.exceptions.RequestException as e:
            raise CoinGeckoAPIError(f"Request failed: {e}")
    
    def get_price(self, coin_id: str, vs_currency: str = 'gbp') -> Optional[Dict[str, float]]:
        """
        Get current price for a single coin.
        
        Args:
            coin_id: CoinGecko coin ID (e.g., 'bitcoin')
            vs_currency: Target currency (gbp, usd, eur)
            
        Returns:
            Dict with price data or None if failed
        """
        cache_key = f"{coin_id}_{vs_currency}"
        
        # Check cache
        if cache_key in self._price_cache:
            cached_time, cached_data = self._price_cache[cache_key]
            if (datetime.now() - cached_time).total_seconds() < self._cache_ttl:
                return cached_data
        
        try:
            params = {
                'ids': coin_id,
                'vs_currencies': vs_currency,
                'include_24hr_vol': 'true',
                'include_24hr_change': 'true',
            }
            
            data = self._request('/simple/price', params)
            
            if coin_id in data:
                result = data[coin_id]
                price_data = {
                    'price': result.get(vs_currency),
                    'volume_24h': result.get(f'{vs_currency}_24h_vol'),
                    'change_24h': result.get(f'{vs_currency}_24h_change'),
                }
                
                # Cache result
                self._price_cache[cache_key] = (datetime.now(), price_data)
                return price_data
                
        except CoinGeckoAPIError as e:
            logger.warning(f"CoinGecko price fetch failed for {coin_id}: {e}")
            
        return None
    
    def get_prices_batch(self, coin_ids: List[str], vs_currencies: List[str] = None) -> Dict:
        """
        Get prices for multiple coins in a single request (rate limit efficient).
        
        Args:
            coin_ids: List of CoinGecko coin IDs
            vs_currencies: Target currencies (default: ['gbp', 'usd'])
            
        Returns:
            Dict mapping coin_id to price data
        """
        if vs_currencies is None:
            vs_currencies = ['gbp', 'usd']
            
        try:
            params = {
                'ids': ','.join(coin_ids),
                'vs_currencies': ','.join(vs_currencies),
                'include_24hr_vol': 'true',
                'include_24hr_change': 'true',
            }
            
            data = self._request('/simple/price', params)
            
            # Convert to structured format
            result = {}
            for coin_id, coin_data in data.items():
                result[coin_id] = {
                    'price': coin_data.get('gbp'),
                    'price_usd': coin_data.get('usd'),
                    'volume_24h': coin_data.get('gbp_24h_vol'),
                    'change_24h': coin_data.get('gbp_24h_change'),
                }
                
            return result
            
        except CoinGeckoAPIError as e:
            logger.warning(f"CoinGecko batch price fetch failed: {e}")
            return {}
    
    def get_market_data(self, coin_id: str, vs_currency: str = 'gbp') -> Optional[Dict]:
        """
        Get comprehensive market data for a coin.
        
        Args:
            coin_id: CoinGecko coin ID
            vs_currency: Target currency
            
        Returns:
            Dict with market data (market_cap, volume, ath, etc.)
        """
        try:
            params = {
                'vs_currency': vs_currency,
                'order': 'market_cap_desc',
                'per_page': 1,
                'page': 1,
                'sparkline': 'false',
            }
            
            data = self._request(f'/coins/{coin_id}/markets', params)
            
            if data and len(data) > 0:
                return data[0]
                
        except CoinGeckoAPIError as e:
            logger.warning(f"CoinGecko market data fetch failed for {coin_id}: {e}")
            
        return None
    
    def get_ohlc(self, coin_id: str, vs_currency: str = 'gbp', days: int = 7) -> Optional[List]:
        """
        Get OHLC candlestick data.
        
        Args:
            coin_id: CoinGecko coin ID
            vs_currency: Target currency
            days: Number of days of data (1-365)
            
        Returns:
            List of OHLC data [timestamp, open, high, low, close]
        """
        try:
            params = {
                'vs_currency': vs_currency,
                'days': min(days, 365),
            }
            
            data = self._request(f'/coins/{coin_id}/ohlc', params)
            
            if data and isinstance(data, list):
                return data
                
        except CoinGeckoAPIError as e:
            logger.warning(f"CoinGecko OHLC fetch failed for {coin_id}: {e}")
            
        return None
    
    def get_historical_price(self, coin_id: str, date: str, vs_currency: str = 'gbp') -> Optional[float]:
        """
        Get historical price at specific date.
        
        Args:
            coin_id: CoinGecko coin ID
            date: Date in 'dd-mm-yyyy' format
            vs_currency: Target currency
            
        Returns:
            Price as float or None
        """
        try:
            data = self._request(f'/coins/{coin_id}/history', {'date': date})
            
            if data and 'market_data' in data:
                return data['market_data']['current_price'].get(vs_currency)
                
        except CoinGeckoAPIError as e:
            logger.warning(f"CoinGecko historical price failed for {coin_id}: {e}")
            
        return None
    
    def get_supported_coins(self) -> List[Dict]:
        """
        Get list of all supported coins.
        
        Returns:
            List of coin info dicts
        """
        try:
            data = self._request('/coins/list')
            return data if isinstance(data, list) else []
        except CoinGeckoAPIError as e:
            logger.warning(f"CoinGecko coin list failed: {e}")
            return []
    
    def convert_product_to_coingecko(self, product_id: str) -> Optional[str]:
        """
        Convert Coinbase product ID to CoinGecko coin ID.
        
        Args:
            product_id: e.g., 'BTC-GBP', 'ETH-USD'
            
        Returns:
            CoinGecko coin ID or None
        """
        return self.COINBASE_TO_COINGECKO.get(product_id)


# Singleton instance
coingecko_api: Optional[CoinGeckoAPI] = None


def get_coingecko_api() -> CoinGeckoAPI:
    """Get or create CoinGecko API singleton."""
    global coingecko_api
    if coingecko_api is None:
        coingecko_api = CoinGeckoAPI()
    return coingecko_api
