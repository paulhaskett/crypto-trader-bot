"""
CryptoCompare API wrapper for aggregated market data.

This module provides access to CryptoCompare's free crypto market data API,
which aggregates prices from 100+ exchanges globally.

API Documentation: https://www.cryptocompare.com/api
Free Tier: No API key required for basic usage
Rate Limit: ~100-200 calls/day (free), higher with key
"""

import logging
import time
from typing import Dict, List, Any, Optional
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class CryptoCompareAPIError(Exception):
    """Custom exception for CryptoCompare API errors."""
    pass


class CryptoCompareAPI:
    """
    CryptoCompare API client for aggregated market data.
    
    Provides price data from 100+ exchanges, good alternative to CoinGecko.
    """
    
    BASE_URL = "https://min-api.cryptocompare.com/data"
    
    # CryptoCompare ID mapping
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
        Initialize CryptoCompare API client.
        
        Args:
            api_key: Optional API key for higher rate limits
        """
        import os
        self.api_key = api_key or os.getenv('CRYPTOCOMPARE_API_KEY')
        self.session = requests.Session()
        
        self._last_request_time = 0
        self._min_request_interval = 0.6  # ~100 calls/minute safe limit
        
    def _rate_limit(self):
        """Apply rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make request to CryptoCompare API."""
        self._rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}
        
        if self.api_key:
            params['api_key'] = self.api_key
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('Response') == 'Error':
                raise CryptoCompareAPIError(data.get('Message', 'Unknown error'))
            
            return data
            
        except requests.exceptions.RequestException as e:
            raise CryptoCompareAPIError(f"Request failed: {e}")
    
    def get_price(self, symbol: str, currency: str = 'GBP') -> Optional[float]:
        """
        Get price for a single cryptocurrency.
        
        Args:
            symbol: Crypto symbol (e.g., 'BTC')
            currency: Target currency (default: 'GBP')
            
        Returns:
            Price as float or None
        """
        try:
            params = {
                'fsym': symbol.upper(),
                'tsyms': currency.upper(),
            }
            
            data = self._request('/price', params)
            
            if currency.upper() in data:
                return float(data[currency.upper()])
                
        except CryptoCompareAPIError as e:
            logger.warning(f"CryptoCompare price fetch failed for {symbol}: {e}")
            
        return None
    
    def get_prices_batch(self, symbols: List[str], currencies: List[str] = None) -> Dict:
        """
        Get prices for multiple cryptocurrencies efficiently.
        
        Args:
            symbols: List of crypto symbols
            currencies: Target currencies (default: ['GBP', 'USD'])
            
        Returns:
            Dict mapping symbol to price data
        """
        if currencies is None:
            currencies = ['GBP', 'USD']
            
        try:
            params = {
                'fsyms': ','.join([s.upper() for s in symbols]),
                'tsyms': ','.join([c.upper() for c in currencies]),
            }
            
            data = self._request('/pricemulti', params)
            
            # Convert to structured format
            result = {}
            for symbol, currency_data in data.items():
                if isinstance(currency_data, dict):
                    result[symbol] = {
                        'price': currency_data.get('GBP'),
                        'price_usd': currency_data.get('USD'),
                    }
                
            return result
            
        except CryptoCompareAPIError as e:
            logger.warning(f"CryptoCompare batch fetch failed: {e}")
            return {}
    
    def get_ohlc(self, symbol: str, currency: str = 'GBP', limit: int = 168) -> Optional[List]:
        """
        Get OHLC data.
        
        Args:
            symbol: Crypto symbol
            currency: Target currency
            limit: Number of data points (max ~168 for hourly)
            
        Returns:
            List of OHLC data
        """
        try:
            params = {
                'fsym': symbol.upper(),
                'tsym': currency.upper(),
                'limit': min(limit, 168),
            }
            
            data = self._request('/v2/histohour', params)
            
            if 'Data' in data and 'Data' in data['Data']:
                return data['Data']['Data']
                
        except CryptoCompareAPIError as e:
            logger.warning(f"CryptoCompare OHLC fetch failed for {symbol}: {e}")
            
        return None
    
    def convert_product_to_symbol(self, product_id: str) -> Optional[str]:
        """Convert Coinbase product ID to CryptoCompare symbol."""
        return self.COINBASE_TO_CRYPTOCOMPARE.get(product_id)


# Singleton instance
cryptocompare_api: Optional[CryptoCompareAPI] = None


def get_cryptocompare_api() -> CryptoCompareAPI:
    """Get or create CryptoCompare API singleton."""
    global cryptocompare_api
    if cryptocompare_api is None:
        cryptocompare_api = CryptoCompareAPI()
    return cryptocompare_api
