"""
Kraken API wrapper for market data.

This module provides access to Kraken's public market data API.
Kraken is a reputable US-based exchange with good liquidity.

API Documentation: https://docs.kraken.com/api/docs/rest-api
Public Endpoints: No authentication required for market data
Rate Limit: Reasonable usage (1s between requests recommended)
"""

import logging
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import pandas as pd
import requests

logger = logging.getLogger(__name__)


class KrakenAPIError(Exception):
    """Custom exception for Kraken API errors."""
    pass


class KrakenAPI:
    """
    Kraken API client for market data.
    
    Provides access to Kraken's exchange data including:
    - Real-time ticker information
    - OHLC candlestick data
    - Asset and pair information
    
    Note: Kraken uses XBT instead of BTC for Bitcoin.
    """
    
    BASE_URL = "https://api.kraken.com"
    
    # Coinbase product ID to Kraken pair mapping
    # Note: Kraken uses XXBT for BTC, XETH for ETH in their GBP pairs
    COINBASE_TO_KRAKEN = {
        'BTC-GBP': 'XXBTZGBP',  # Kraken's official GBP pair
        'ETH-GBP': 'XETHZGBP',  # Kraken's official GBP pair
        'SOL-GBP': 'SOLGBP',
        'LTC-GBP': 'LTCGBP',
        'DOT-GBP': 'DOTGBP',
        'ADA-GBP': 'ADAGBP',
        'LINK-GBP': 'LINKGBP',
        'UNI-GBP': 'UNIGBP',
    }
    
    # USD pairs for risk management
    COINBASE_TO_KRAKEN_USD = {
        'BTC-USD': 'XBTUSD',
        'ETH-USD': 'XETHZUSD',
        'SOL-USD': 'SOLUSD',
        'LTC-USD': 'LTCUSD',
        'DOT-USD': 'DOTUSD',
        'ADA-USD': 'ADAUSD',
        'LINK-USD': 'LINKUSD',
        'UNI-USD': 'UNIUSD',
    }
    
    # USD pairs for risk management
    COINBASE_TO_KRAKEN_USD = {
        'BTC-USD': 'XBTUSD',
        'ETH-USD': 'ETHUSD',
        'SOL-USD': 'SOLUSD',
        'LTC-USD': 'LTCUSD',
        'DOT-USD': 'DOTUSD',
        'ADA-USD': 'ADAUSD',
        'LINK-USD': 'LINKUSD',
        'UNI-USD': 'UNIUSD',
    }
    
    # Interval mapping for OHLC (in minutes)
    OHLC_INTERVALS = {
        1: 1,
        5: 5,
        15: 15,
        30: 30,
        60: 60,    # 1 hour
        240: 240,  # 4 hours
        1440: 1440, # 1 day
    }
    
    def __init__(self):
        """Initialize Kraken API client."""
        self.session = requests.Session()
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 1.0  # 1 second between requests
        
        # Cache for asset pairs
        self._pairs_cache: Optional[Dict] = None
        self._pairs_cache_time: Optional[datetime] = None
        self._pairs_cache_ttl = 3600  # 1 hour
        
    def _rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """
        Make request to Kraken API with rate limiting.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            JSON response as dictionary
        """
        self._rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Check for Kraken API errors
            if isinstance(data, dict):
                if data.get('error'):
                    error_msg = data['error']
                    if 'ESOURCEUNKNOWN' in str(error_msg):
                        raise KrakenAPIError(f"Unknown asset pair: {params.get('pair', 'unknown')}")
                    raise KrakenAPIError(f"Kraken API error: {error_msg}")
                return data.get('result', {})
            
            return data
            
        except requests.exceptions.HTTPError as e:
            raise KrakenAPIError(f"HTTP error: {e}")
        except requests.exceptions.RequestException as e:
            raise KrakenAPIError(f"Request failed: {e}")
    
    def get_server_time(self) -> Optional[Dict]:
        """Get Kraken server time."""
        try:
            return self._request('/0/public/Time')
        except KrakenAPIError as e:
            logger.warning(f"Kraken time request failed: {e}")
            return None
    
    def get_system_status(self) -> Optional[str]:
        """Get Kraken system status (online/maintenance)."""
        try:
            result = self._request('/0/public/SystemStatus')
            return result.get('status')
        except KrakenAPIError as e:
            logger.warning(f"Kraken status request failed: {e}")
            return None
    
    def get_available_pairs(self, reload: bool = False) -> Dict:
        """
        Get available trading pairs on Kraken.
        
        Args:
            reload: Force reload cache
            
        Returns:
            Dict of pair info
        """
        # Check cache
        if not reload and self._pairs_cache and self._pairs_cache_time:
            age = (datetime.now() - self._pairs_cache_time).total_seconds()
            if age < self._pairs_cache_ttl:
                return self._pairs_cache
        
        try:
            result = self._request('/0/public/AssetPairs')
            self._pairs_cache = result
            self._pairs_cache_time = datetime.now()
            return result
        except KrakenAPIError as e:
            logger.warning(f"Kraken asset pairs request failed: {e}")
            return {}
    
    def get_ticker(self, kraken_pair: str) -> Optional[Dict]:
        """
        Get ticker information for a trading pair.
        
        Args:
            kraken_pair: Kraken pair name (e.g., 'XBTGBP')
            
        Returns:
            Dict with ticker data or None
        """
        try:
            params = {'pair': kraken_pair}
            result = self._request('/0/public/Ticker', params)
            
            # Get first (and usually only) result
            if result:
                return list(result.values())[0]
                
        except KrakenAPIError as e:
            logger.warning(f"Kraken ticker request failed for {kraken_pair}: {e}")
            
        return None
    
    def get_ticker_price(self, product_id: str) -> Optional[Dict]:
        """
        Get current price for a Coinbase-style product ID.
        
        Args:
            product_id: Coinbase product ID (e.g., 'BTC-GBP')
            
        Returns:
            Dict with price data or None
        """
        kraken_pair = self.convert_product_to_kraken(product_id)
        
        if not kraken_pair:
            logger.warning(f"No Kraken mapping for {product_id}")
            return None
        
        ticker = self.get_ticker(kraken_pair)
        
        if not ticker:
            return None
        
        # Parse ticker response
        # a = ask [price, whole lot volume, lot volume]
        # b = bid [price, whole lot volume, lot volume]
        # c = last trade closed [price, lot volume]
        # v = volume [today, last 24 hours]
        # p = volume weighted average price [today, last 24 hours]
        # t = number of trades [today, last 24 hours]
        # l = low [today, last 24 hours]
        # h = high [today, last 24 hours]
        # o = today's opening price
        
        try:
            return {
                'ask': float(ticker['a'][0]) if ticker.get('a') else None,
                'bid': float(ticker['b'][0]) if ticker.get('b') else None,
                'last': float(ticker['c'][0]) if ticker.get('c') else None,
                'volume': float(ticker['v'][1]) if ticker.get('v') else None,
                'vwap': float(ticker['p'][1]) if ticker.get('p') else None,
                'high': float(ticker['h'][1]) if ticker.get('h') else None,
                'low': float(ticker['l'][1]) if ticker.get('l') else None,
                'open': float(ticker['o']) if ticker.get('o') else None,
                'trades': int(ticker['t'][1]) if ticker.get('t') else None,
            }
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"Failed to parse Kraken ticker for {kraken_pair}: {e}")
            return None
    
    def get_ohlc(self, kraken_pair: str, interval: int = 60, since: Optional[int] = None) -> Optional[pd.DataFrame]:
        """
        Get OHLC candlestick data.
        
        Args:
            kraken_pair: Kraken pair name (e.g., 'XBTGBP')
            interval: Timeframe in minutes (1, 5, 15, 30, 60, 240, 1440)
            since: Optional Unix timestamp to get data since
            
        Returns:
            DataFrame with OHLC data or None
        """
        try:
            params = {
                'pair': kraken_pair,
                'interval': self.OHLC_INTERVALS.get(interval, 60),
            }
            if since:
                params['since'] = since
                
            result = self._request('/0/public/OHLC', params)
            
            # Get data for the pair
            pair_data = None
            for key, value in result.items():
                if key != 'last' and isinstance(value, list):
                    pair_data = value
                    break
                    
            if not pair_data:
                return None
                
            # Convert to DataFrame
            columns = ['timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count']
            df = pd.DataFrame(pair_data, columns=columns)
            
            # Convert types
            for col in ['open', 'high', 'low', 'close', 'vwap', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['count'] = pd.to_numeric(df['count'], errors='coerce')
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            return df
            
        except KrakenAPIError as e:
            logger.warning(f"Kraken OHLC request failed for {kraken_pair}: {e}")
        except Exception as e:
            logger.warning(f"Failed to parse Kraken OHLC for {kraken_pair}: {e}")
            
        return None
    
    def get_ohlc_for_product(self, product_id: str, interval: int = 60, days: int = 7) -> Optional[pd.DataFrame]:
        """
        Get OHLC data for a Coinbase-style product ID.
        
        Args:
            product_id: Coinbase product ID (e.g., 'BTC-GBP')
            interval: Timeframe in minutes
            days: Number of days of history
            
        Returns:
            DataFrame with OHLC data or None
        """
        kraken_pair = self.convert_product_to_kraken(product_id)
        
        if not kraken_pair:
            return None
        
        # Calculate since timestamp (max 720 candles for 1 hour interval)
        max_candles = 720
        interval_seconds = self.OHLC_INTERVALS.get(interval, 60) * 60
        since = int(time.time()) - (max_candles * interval_seconds)
        
        return self.get_ohlc(kraken_pair, interval, since)
    
    def get_recent_trades(self, kraken_pair: str, since: Optional[int] = None) -> Optional[List]:
        """
        Get recent trades.
        
        Args:
            kraken_pair: Kraken pair name
            since: Unix timestamp
            
        Returns:
            List of trade data or None
        """
        try:
            params = {'pair': kraken_pair}
            if since:
                params['since'] = since
                
            result = self._request('/0/public/Trades', params)
            
            # Get trades for the pair
            for key, value in result.items():
                if key != 'last' and isinstance(value, list):
                    return value
                    
        except KrakenAPIError as e:
            logger.warning(f"Kraken trades request failed for {kraken_pair}: {e}")
            
        return None
    
    def convert_product_to_kraken(self, product_id: str) -> Optional[str]:
        """
        Convert Coinbase product ID to Kraken pair name.
        
        Args:
            product_id: e.g., 'BTC-GBP', 'ETH-USD'
            
        Returns:
            Kraken pair name or None
        """
        # Try GBP mapping first
        if product_id in self.COINBASE_TO_KRAKEN:
            return self.COINBASE_TO_KRAKEN[product_id]
        
        # Try USD mapping
        if product_id in self.COINBASE_TO_KRAKEN_USD:
            return self.COINBASE_TO_KRAKEN_USD[product_id]
        
        return None
    
    def is_pair_supported(self, product_id: str) -> bool:
        """
        Check if a product is supported by Kraken.
        
        Args:
            product_id: Coinbase product ID
            
        Returns:
            True if supported
        """
        return self.convert_product_to_kraken(product_id) is not None
    
    def get_supported_products(self) -> List[str]:
        """
        Get list of Coinbase-style product IDs that Kraken supports.
        
        Returns:
            List of supported product IDs
        """
        kraken_pairs = self.get_available_pairs()
        
        supported = []
        reverse_map = {v: k for k, v in self.COINBASE_TO_KRAKEN.items()}
        reverse_map.update({v: k for k, v in self.COINBASE_TO_KRAKEN_USD.items()})
        
        for kraken_pair in kraken_pairs.keys():
            if kraken_pair in reverse_map:
                supported.append(reverse_map[kraken_pair])
        
        return supported


# Singleton instance
kraken_api: Optional[KrakenAPI] = None


def get_kraken_api() -> KrakenAPI:
    """Get or create Kraken API singleton."""
    global kraken_api
    if kraken_api is None:
        kraken_api = KrakenAPI()
    return kraken_api
