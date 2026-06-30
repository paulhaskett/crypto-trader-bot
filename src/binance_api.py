"""
Binance API wrapper for market data.

This module provides access to Binance's public market data API.
No authentication required for price data (public endpoints).

API Documentation: https://developers.binance/docs/
Public Endpoints: No authentication required
Rate Limit: 1200 requests/minute (public), 10/second IP-based
"""

import logging
import time
from typing import Dict, List, Optional, Any
import requests

logger = logging.getLogger(__name__)


class BinanceAPIError(Exception):
    """Custom exception for Binance API errors."""
    pass


class BinanceAPI:
    """
    Binance API client for market data (public endpoints).
    
    Provides access to:
    - Current price (24h ticker)
    - Historical candlestick data (klines)
    - Order book depth
    
    No API key required - uses public endpoints only.
    Future: API key support can be added for higher rate limits.
    """
    
    BASE_URL = "https://api.binance.com"
    
    # Coinbase product ID to Binance symbol mapping
    # Note: Binance doesn't have GBP pairs - use USDT pairs and convert
    # See: https://www.binance.com/en/trade/BTC_USDT
    COINBASE_TO_BINANCE: Dict[str, str] = {
        'BTC-GBP': 'BTCGBP',  # Doesn't exist - will fallback to USDT
        'ETH-GBP': 'ETHGBP',  # Doesn't exist - will fallback to USDT
        'SOL-GBP': 'SOLGBP',  # Doesn't exist - will fallback to USDT
        'LTC-GBP': 'LTCGBP',  # Doesn't exist - will fallback to USDT
        'DOT-GBP': 'DOTGBP',  # Doesn't exist - will fallback to USDT
        'ADA-GBP': 'ADAGBP',  # Doesn't exist - will fallback to USDT
        'LINK-GBP': 'LINKGBP',  # Doesn't exist - will fallback to USDT
        'UNI-GBP': 'UNIGBP',  # Doesn't exist - will fallback to USDT
    }
    
    # USDT pairs for GBP conversion fallback
    COINBASE_TO_BINANCE_USDT: Dict[str, str] = {
        'BTC-GBP': 'BTCUSDT',
        'ETH-GBP': 'ETHUSDT',
        'SOL-GBP': 'SOLUSDT',
        'LTC-GBP': 'LTCUSDT',
        'DOT-GBP': 'DOTUSDT',
        'ADA-GBP': 'ADAUSDT',
        'LINK-GBP': 'LINKUSDT',
        'UNI-GBP': 'UNIUSDT',
    }
    
    # Reverse mapping
    BINANCE_TO_COINBASE: Dict[str, str] = {v: k for k, v in COINBASE_TO_BINANCE.items()}
    
    # Interval mapping for klines (candlestick data)
    INTERVAL_MAP: Dict[str, str] = {
        '1m': '1m',
        '5m': '5m',
        '15m': '15m',
        '30m': '30m',
        '1h': '1h',
        '4h': '4h',
        '1d': '1d',
    }
    
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        """
        Initialize Binance API client.
        
        Args:
            api_key: Optional API key for authenticated endpoints (future use)
            secret_key: Optional secret key for authenticated endpoints (future use)
        """
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 0.1  # 100ms between requests (10req/s)
        
        # Optional API keys (for future authenticated endpoints)
        self.api_key = api_key
        self.secret_key = secret_key
        
        # Cache for recent requests
        self._price_cache: Dict[str, tuple] = {}  # symbol -> (price, timestamp)
        self._cache_ttl = 5  # 5 seconds for price cache
        
        # Health tracking
        self._health = {'success': 0, 'fail': 0, 'last_success': None}
        
        logger.info("BinanceAPI initialized (public endpoints)")
    
    def _rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Make request to Binance API with rate limiting.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            JSON response as dictionary or None on failure
        """
        self._rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Update health on success
            self._health['success'] = self._health.get('success', 0) + 1
            self._health['last_success'] = time.time()
            
            return data
            
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Binance HTTP error: {e}")
            self._health['fail'] = self._health.get('fail', 0) + 1
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Binance request failed: {e}")
            self._health['fail'] = self._health.get('fail', 0) + 1
            return None
        except Exception as e:
            logger.warning(f"Binance unexpected error: {e}")
            self._health['fail'] = self._health.get('fail', 0) + 1
            return None
    
    def get_binance_symbol(self, product_id: str) -> Optional[str]:
        """
        Get Binance symbol from Coinbase product ID.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            Binance symbol e.g., 'BTCGBP' or None
        """
        return self.COINBASE_TO_BINANCE.get(product_id)
    
    def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get 24h ticker data for a symbol.
        
        Args:
            symbol: Binance symbol e.g., 'BTCGBP'
            
        Returns:
            Dict with price data or None on failure
            {
                'symbol': 'BTCGBP',
                'lastPrice': '42500.00',
                'volume': '1234.56',
                'priceChange': '250.00',
                'priceChangePercent': '0.59',
                ...
            }
        """
        # Check cache first
        if symbol in self._price_cache:
            cached_price, cached_time = self._price_cache[symbol]
            if time.time() - cached_time < self._cache_ttl:
                return {
                    'symbol': symbol,
                    'lastPrice': str(cached_price),
                    'cached': True
                }
        
        data = self._request('/api/v3/ticker/24hr', {'symbol': symbol})
        
        if data:
            # Cache the price
            try:
                price = float(data.get('lastPrice', 0))
                self._price_cache[symbol] = (price, time.time())
            except (ValueError, TypeError):
                pass
            
            return data
        
        return None
    
    def get_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol.
        
        Args:
            symbol: Binance symbol e.g., 'BTCGBP'
            
        Returns:
            Current price as float or None on failure
        """
        # Try 24h ticker first (includes price)
        ticker = self.get_ticker(symbol)
        if ticker:
            try:
                return float(ticker.get('lastPrice', 0))
            except (ValueError, TypeError):
                pass
        
        # Fallback to price endpoint
        data = self._request('/api/v3/ticker/price', {'symbol': symbol})
        if data:
            try:
                return float(data.get('price', 0))
            except (ValueError, TypeError):
                pass
        
        return None
    
    def get_price_product(self, product_id: str) -> Optional[float]:
        """
        Get current price using Coinbase product ID.
        
        Args:
            product_id: Coinbase product ID e.g., 'BTC-GBP'
            
        Returns:
            Current price as float or None on failure
        """
        # Binance doesn't have GBP pairs - use USDT pairs and convert
        # Use implied exchange rate from crypto prices to avoid fiat rate mismatch
        usdt_symbol = self.COINBASE_TO_BINANCE_USDT.get(product_id)
        if usdt_symbol:
            usdt_price = self.get_price(usdt_symbol)
            if usdt_price and usdt_price > 0:
                # Get GBP price from Coinbase as reference
                gbp_price = self._get_reference_gbp_price(product_id)
                if gbp_price and gbp_price > 0:
                    # Calculate implied rate from reference price
                    implied_rate = usdt_price / gbp_price
                    # Apply slight smoothing (90% implied, 10% fiat for stability)
                    gbp_usd = self._get_gbp_usd_rate() or 1.26
                    smoothed_rate = implied_rate * 0.95 + gbp_usd * 0.05
                    converted = usdt_price / smoothed_rate
                    logger.info(f"Binance {product_id}: ${usdt_price} / {smoothed_rate:.4f} = £{converted:.2f} (implied: {implied_rate:.4f})")
                    return converted
        
        logger.warning(f"Binance: Could not get price for {product_id}")
        return None
    
    def _get_reference_gbp_price(self, product_id: str) -> Optional[float]:
        """Get reference GBP price from Coinbase to calculate implied rate."""
        try:
            from src.coinbase_api import coinbase_api
            ticker = coinbase_api.get_product_ticker(product_id)
            if ticker:
                return float(ticker.get('price', 0))
        except Exception as e:
            logger.debug(f"Could not get reference price for {product_id}: {e}")
        return None
    
    def _get_gbp_usd_rate(self) -> Optional[float]:
        """Get GBP-USD exchange rate from Coinbase."""
        try:
            from src.coinbase_api import coinbase_api
            ticker = coinbase_api.get_product_ticker('GBP-USD')
            if ticker:
                return float(ticker.get('price', 0))
        except Exception as e:
            logger.debug(f"Could not get GBP-USD rate: {e}")
        
        # Fallback: try Binance EUR-USDT + estimate
        try:
            eur_usd = self.get_price('EURUSDT')
            if eur_usd and eur_usd > 0:
                # Approximate GBP-EUR rate
                return 1.17  # Rough estimate
        except:
            pass
        
        return None
    
    def get_klines(
        self,
        symbol: str,
        interval: str = '1h',
        limit: int = 100
    ) -> Optional[List[List[Any]]]:
        """
        Get candlestick (kline) data.
        
        Args:
            symbol: Binance symbol e.g., 'BTCGBP'
            interval: Kline interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            limit: Number of klines to return (max 1000)
            
        Returns:
            List of klines or None on failure
            Each kline: [openTime, open, high, low, close, volume, closeTime, ...]
        """
        # Map interval
        binance_interval = self.INTERVAL_MAP.get(interval, interval)
        
        data = self._request(
            '/api/v3/klines',
            {
                'symbol': symbol,
                'interval': binance_interval,
                'limit': min(limit, 1000)
            }
        )
        
        return data if isinstance(data, list) else None
    
    def get_klines_product(
        self,
        product_id: str,
        interval: str = '1h',
        limit: int = 100
    ) -> Optional[List[List[Any]]]:
        """
        Get candlestick data using Coinbase product ID.
        
        Args:
            product_id: Coinbase product ID e.g., 'BTC-GBP'
            interval: Kline interval
            limit: Number of klines
            
        Returns:
            List of klines or None on failure
        """
        symbol = self.get_binance_symbol(product_id)
        if not symbol:
            return None
        
        return self.get_klines(symbol, interval, limit)
    
    def get_order_book(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """
        Get order book depth.
        
        Args:
            symbol: Binance symbol e.g., 'BTCGBP'
            limit: Depth limit (5, 10, 20, 50, 100, 500, 1000, 5000)
            
        Returns:
            Dict with bids/asks or None on failure
        """
        data = self._request(
            '/api/v3/depth',
            {'symbol': symbol, 'limit': limit}
        )
        
        return data
    
    def get_health(self) -> Dict:
        """Get health statistics."""
        return self._health.copy()
    
    def clear_cache(self):
        """Clear the price cache."""
        self._price_cache.clear()


# Singleton instance
binance_api: Optional[BinanceAPI] = None


def get_binance_api(api_key: Optional[str] = None, secret_key: Optional[str] = None) -> BinanceAPI:
    """
    Get or create Binance API singleton.
    
    Args:
        api_key: Optional API key (future use)
        secret_key: Optional secret key (future use)
        
    Returns:
        BinanceAPI instance
    """
    global binance_api
    if binance_api is None:
        import os
        # Check environment for API keys (future use)
        api_key = api_key or os.getenv('BINANCE_API_KEY', '')
        secret_key = secret_key or os.getenv('BINANCE_API_SECRET', '')
        binance_api = BinanceAPI(api_key=api_key if api_key else None, 
                                  secret_key=secret_key if secret_key else None)
    return binance_api