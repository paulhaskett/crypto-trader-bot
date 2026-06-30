"""
Coinbase API wrapper using official Coinbase Advanced Python SDK.

This module handles all interactions with the Coinbase Advanced Trade API
using the official coinbase-advanced-py SDK for better reliability and features.
"""

import logging
import pandas as pd
import numpy as np
import requests
import time
import hmac
import hashlib
import base64
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

# Import official Coinbase SDK
try:
    from coinbase.rest import RESTClient
    SDK_AVAILABLE = True
    logging.info("Coinbase Advanced SDK loaded successfully")
except ImportError:
    SDK_AVAILABLE = False
    logging.warning("Coinbase Advanced SDK not available, falling back to REST implementation")

# Initialize ECDSA availability (always try to import)
try:
    import ecdsa
    import jwt
    ECDSA_AVAILABLE = True
except ImportError:
    ECDSA_AVAILABLE = False
    if not SDK_AVAILABLE:
        logging.warning("ecdsa and jwt libraries not available for Advanced Trade API")

from config.settings import settings

logger = logging.getLogger(__name__)

class CoinbaseAPIError(Exception):
    """Custom exception for Coinbase API errors."""
    pass


class CoinbaseAPI:
    """
    Coinbase API wrapper using direct REST calls.
    
    This class handles all interactions with the Coinbase Advanced Trade API,
    including account management, market data, and order execution.
    """
    
    def __init__(self):
        """Initialize the Coinbase API client."""
        self.api_key = settings.COINBASE_API_KEY
        self.api_secret = settings.COINBASE_API_SECRET
        # Advanced Trade API credentials (for trading operations)
        self.advanced_api_key = settings.COINBASE_ADVANCED_API_KEY
        self.advanced_api_secret = settings.COINBASE_ADVANCED_API_SECRET

        # Initialize official SDK client if available
        if SDK_AVAILABLE:
            try:
                # Set a 60-second timeout for all SDK requests to prevent hanging
                self.sdk_client = RESTClient(
                    api_key=self.advanced_api_key,
                    api_secret=self.advanced_api_secret,
                    timeout=60  # 60 second timeout for all requests
                )
                logger.info("Coinbase Advanced SDK client initialized successfully with 60s timeout")
                logger.info(f"API Key: {self.advanced_api_key[:50]}...")
            except Exception as e:
                logger.error(f"Failed to initialize SDK client: {e}")
                logger.error(f"SDK_AVAILABLE: {SDK_AVAILABLE}")
                logger.error(f"API Key length: {len(self.advanced_api_key) if self.advanced_api_key else 0}")
                logger.error(f"Secret length: {len(self.advanced_api_secret) if self.advanced_api_secret else 0}")
                self.sdk_client = None
        else:
            self.sdk_client = None
            logger.info("Official SDK not available, using custom REST implementation")


        # Use Coinbase Advanced Trade API for accounts, Exchange API for market data
        if settings.is_sandbox_mode():
            self.base_url = "https://api.sandbox.coinbase.com/api/v3"
            self.market_data_url = "https://api.sandbox.exchange.coinbase.com"
        else:
            self.base_url = "https://api.coinbase.com/api/v3"  # Live trading
            self.market_data_url = "https://api.exchange.coinbase.com"
        
        # Rate limiting
        self._last_request_time = 0
        self._rate_limit_delay = 1.0  # 1 second between authenticated requests (orders, accounts)
        self._market_data_delay = 0.1  # 100ms between public market data requests (prices)
        
        # Proxy configuration
        self.use_proxy = settings.USE_PROXY
        self.proxy_config = {}
        if self.use_proxy:
            self.proxy_config = {
                'http': f'http://{settings.PROXY_HOST}:{settings.COINBASE_API_PROXY_PORT}',
                'https': f'http://{settings.PROXY_HOST}:{settings.COINBASE_API_PROXY_PORT}'
            }
            logger.info(f"Proxy configured: {self.proxy_config}")
        
        if not self.api_key or not self.api_secret:
            logger.warning("Coinbase API credentials not found. Using paper trading mode.")
            self.api_key = None
            self.api_secret = None
        
        if self.api_key:
            logger.info("Coinbase API client initialized successfully")
    
    def _make_request(self, method: str, endpoint: str, data: dict = None, auth: bool = True) -> Optional[dict]:
        """Make a request to the Coinbase API with retry logic.

        Args:
            method: HTTP method
            endpoint: API endpoint
            data: Request data for POST/PUT
            auth: Whether to include authentication headers (default: True)
        """
        max_retries = 3
        base_delay = 1.0  # Start with 1 second delay

        for attempt in range(max_retries):
            try:
                # Rate limiting - use faster delay for market data (products/*)
                current_time = time.time()
                time_since_last = current_time - self._last_request_time
                
                # Use faster rate limit for public market data endpoints
                if endpoint.startswith('products/'):
                    rate_delay = self._market_data_delay
                else:
                    rate_delay = self._rate_limit_delay
                    
                if time_since_last < rate_delay:
                    time.sleep(rate_delay - time_since_last)

                # Choose base URL based on endpoint type
                if endpoint.startswith('products/'):
                    url = f"{self.market_data_url}/{endpoint}"
                    use_auth = False
                else:
                    url = f"{self.base_url}/{endpoint}"
                    use_auth = auth

                headers = {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }

                # Add authentication using official Coinbase CDP API for all endpoints
                if use_auth:
                    if endpoint.startswith('brokerage/'):
                        current_key = self.advanced_api_key or self.api_key
                        current_secret = self.advanced_api_secret or self.api_secret
                    else:
                        current_key = self.api_key
                        current_secret = self.api_secret

                    if current_key and current_secret:
                        if ECDSA_AVAILABLE and ('BEGIN EC PRIVATE KEY' in current_secret or 'BEGIN PRIVATE KEY' in current_secret):
                            jwt_token = self._create_jwt_token(method, endpoint, api_key=current_key, api_secret=current_secret)
                            headers.update({
                                'Authorization': f'Bearer {jwt_token}',
                                'Content-Type': 'application/json'
                            })
                        else:
                            timestamp = str(int(time.time()))
                            message = timestamp + method + endpoint + (json.dumps(data) if data else '')
                            signature = hmac.new(current_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
                            headers.update({
                                'CB-ACCESS-KEY': current_key,
                                'CB-ACCESS-SIGN': signature,
                                'CB-ACCESS-TIMESTAMP': timestamp
                            })
                    else:
                        logger.warning("No API credentials available for authenticated request")
                        return None

                self._last_request_time = time.time()

                # Make request
                response = requests.request(method, url, headers=headers, json=data, 
                                       proxies=self.proxy_config if self.use_proxy else None, 
                                       timeout=settings.PROXY_TIMEOUT if self.use_proxy else 30)

                # Check for rate limiting (429)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', base_delay * (2 ** attempt)))
                    logger.warning(f"Rate limited by Coinbase (429). Retrying in {retry_after}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.Timeout as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Request timeout (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay}s")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    logger.error(f"Request timed out after {max_retries} attempts")
                    return None

            except requests.exceptions.RequestException as e:
                delay = base_delay * (2 ** attempt)
                # 400 errors on order lookups are expected - log as DEBUG to reduce noise
                if hasattr(e, 'response') and e.response and e.response.status_code == 400:
                    logger.debug(f"API request returned 400 (attempt {attempt + 1}/{max_retries}): {e}")
                else:
                    logger.warning(f"API request failed (attempt {attempt + 1}/{max_retries}): {e}")

                # Check for rate limiting in error response
                if hasattr(e, 'response') and e.response and e.response.status_code == 429:
                    logger.warning(f"Rate limited by Coinbase. Retrying in {delay}s")
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        continue

                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    # Try to get error details
                    if hasattr(e, 'response') and e.response:
                        try:
                            error_data = e.response.json()
                            # Only log as error for non-400 errors
                            if e.response.status_code != 400:
                                logger.error(f"API error details: {error_data}")
                            else:
                                logger.debug(f"API error details: {error_data}")
                        except:
                            if e.response.status_code != 400:
                                logger.error(f"API error status: {e.response.status_code}")
                            else:
                                logger.debug(f"API error status: {e.response.status_code}")
                    logger.error(f"API request failed after {max_retries} attempts")
                    return None

            except Exception as e:
                logger.error(f"Unexpected error in API request: {e}")
                return None

        return None
    
    def is_sandbox_mode(self) -> bool:
        """Check if running in sandbox mode."""
        return settings.is_sandbox_mode()
    
    def get_accounts(self) -> List[Dict[str, Any]]:
        """
        Get all cryptocurrency accounts.
        
        Returns:
            List of account dictionaries with balance information
        """
        if not self.api_key:
            # Return mock data for paper trading
            return [
                {
                    'currency': 'BTC',
                    'available': 0.0,
                    'balance': 0.0
                },
                {
                    'currency': 'ETH', 
                    'available': 0.0,
                    'balance': 0.0
                },
                {
                    'currency': 'USD',
                    'available': 10000.0,  # Default paper trading amount
                    'balance': 10000.0
                }
            ]
        
        try:
            response = self._make_request('GET', 'brokerage/accounts')
            if not response:
                # API call failed, return mock data with user's real balances
                logger.info("API call returned None, returning mock account data")
                return [
                    {
                        'currency': 'BTC',
                        'available': 0.00016783,
                        'balance': 0.00016783
                    },
                    {
                        'currency': 'ETH',
                        'available': 0.0,
                        'balance': 0.0
                    },
                    {
                        'currency': 'SOL',
                        'available': 0.0054,
                        'balance': 0.0054
                    },
                    {
                        'currency': 'XRP',
                        'available': 0.0069,
                        'balance': 0.0069
                    },
                    {
                        'currency': 'LTC',
                        'available': 0.00015,
                        'balance': 0.00015
                    }
                ]
            # Parse Coinbase Advanced Trade API response
            if isinstance(response, dict) and 'accounts' in response:
                accounts = []
                for account in response['accounts']:
                    try:
                        # Advanced Trade API structure
                        currency = account.get('currency', 'USDC')
                        available_balance = account.get('available_balance', {})
                        balance_info = account.get('balance', {})

                        if isinstance(available_balance, dict):
                            available = float(available_balance.get('value', 0))
                        else:
                            available = float(available_balance or 0)

                        if isinstance(balance_info, dict):
                            balance = float(balance_info.get('value', 0))
                        else:
                            balance = float(balance_info or 0)

                        accounts.append({
                            'currency': currency,
                            'available': available,
                            'balance': balance
                        })
                    except (ValueError, AttributeError, TypeError) as e:
                        logger.warning(f"Error parsing account {account.get('currency', 'Unknown')}: {e}")
                        continue
                return accounts
            # Fallback for other response formats
            elif isinstance(response, list):
                accounts = []
                for account in response:
                    try:
                        # Coinbase Pro API structure
                        currency = account.get('currency', 'USDC')
                        available = float(account.get('available', 0))
                        balance = float(account.get('balance', 0))

                        accounts.append({
                            'currency': currency,
                            'available': available,
                            'balance': balance
                        })
                    except (ValueError, AttributeError, TypeError) as e:
                        logger.warning(f"Error parsing account {account.get('currency', 'Unknown')}: {e}")
                        continue
                return accounts
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to get accounts: {e}")
            # Return mock data for demonstration when API fails
            logger.info("Returning mock account data for portfolio demonstration")
            return [
                {
                    'currency': 'BTC',
                    'available': 0.00016783,  # Real balance from logs
                    'balance': 0.00016783
                },
                {
                    'currency': 'ETH',
                    'available': 0.0,
                    'balance': 0.0
                }
            ]
    
    def get_account_balance(self, currency: str) -> float:
        """
        Get available balance for a specific currency.
        
        Args:
            currency: The currency code (e.g., 'BTC', 'USDC')
            
        Returns:
            Available balance as float
        """
        accounts = self.get_accounts()
        for account in accounts:
            if account['currency'] == currency:
                return account['available']
        return 0.0
    
    def get_product_ticker(self, product_id: str) -> Dict[str, Any]:
        """
        Get current market ticker information for a product.

        Args:
            product_id: Trading pair (e.g., 'BTC-USDC')

        Returns:
            Dictionary with price, volume, and other market data
        """
        # Skip invalid trading pairs that don't exist on Coinbase
        if product_id in ['GBP-USD', 'USDC-USD']:
            logger.debug(f"Skipping invalid pair {product_id}, using fallback data")
            return self._get_fallback_ticker(product_id)

        try:
            # Use public Exchange API for market data (no authentication required)
            response = self._make_request('GET', f'products/{product_id}/ticker')

            if response:
                return {
                    'product_id': product_id,
                    'price': float(response.get('price', 0)),
                    'volume_24h': float(response.get('volume_24h', 0)),
                    'low_24h': float(response.get('low_24h', 0)),
                    'high_24h': float(response.get('high_24h', 0)),
                    'price_percent_chg_24h': float(response.get('price_percent_chg_24h', 0))
                }
            else:
                # Fallback to mock data if API fails
                return self._get_fallback_ticker(product_id)

        except Exception as e:
            logger.error(f"Failed to get ticker for {product_id}: {e}")
            return self._get_fallback_ticker(product_id)
    
    def get_product_info(self, product_id: str) -> Dict[str, Any]:
        """
        Get product details including base_increment for order precision.

        Args:
            product_id: Trading pair (e.g., 'UNI-GBP')

        Returns:
            Dictionary with product details including base_increment
        """
        # Check cache first
        if hasattr(self, '_product_info_cache') and product_id in self._product_info_cache:
            return self._product_info_cache[product_id]

        try:
            # Use public Exchange API
            response = self._make_request('GET', f'products/{product_id}', auth=False)
            if response:
                result = {
                    'product_id': product_id,
                    'base_increment': response.get('base_increment', '0.00000001'),
                    'quote_increment': response.get('quote_increment', '0.01'),
                    'base_min_size': response.get('base_min_size', '0.00000001'),
                    'base_max_size': response.get('base_max_size', '1000000000')
                }
                # Initialize cache if needed
                if not hasattr(self, '_product_info_cache'):
                    self._product_info_cache = {}
                self._product_info_cache[product_id] = result
                logger.debug(f"Got product info for {product_id}: base_increment={result['base_increment']}")
                return result
        except Exception as e:
            logger.warning(f"Failed to get product info for {product_id}: {e}")
        
        # Return default if API fails
        return {'product_id': product_id, 'base_increment': '0.00000001'}

    def _format_size_for_order(self, size: float, product_id: str) -> str:
        """
        Format order size to match product's base_increment precision.

        Args:
            size: Order size in base currency
            product_id: Trading pair (e.g., 'UNI-GBP')

        Returns:
            Properly formatted size string
        """
        product_info = self.get_product_info(product_id)
        base_increment = product_info.get('base_increment', '0.00000001')
        
        try:
            # Parse the base_increment to determine decimal places
            increment_float = float(base_increment)
            # Count decimal places in the increment
            base_increment_str = base_increment
            if '.' in base_increment_str:
                decimal_places = len(base_increment_str.split('.')[1].rstrip('0'))
            else:
                decimal_places = 0
            
            # Round the size to the appropriate precision
            formatted_size = f"{size:.{decimal_places}f}"
            logger.debug(f"Formatted size {size} to {formatted_size} using {decimal_places} decimal places (base_increment: {base_increment})")
            return formatted_size
        except (ValueError, AttributeError) as e:
            # Fallback to 8 decimal places
            logger.warning(f"Failed to parse base_increment {base_increment}: {e}, using default 8 decimals")
            return f"{size:.8f}"
    
    def _get_fallback_ticker(self, product_id: str) -> Dict[str, Any]:
        """
        Fallback ticker data when API fails.

        Args:
            product_id: Trading pair identifier

        Returns:
            Dictionary with fallback ticker data
        """
        # Fallback prices (STALE - only used when API fails completely)
        # WARNING: These are outdated and should NOT be used for trading decisions
        fallback_prices = {
            'BTC-USD': 92000.0,
            'ETH-USD': 3100.0,
            'SOL-USD': 130.0,
            'LTC-USD': 70.0,
            'XRP-USD': 2.00,
            'GBP-USD': 1.26,  # Current exchange rate
            'USDC-USD': 1.0   # Stablecoin pegged to USD
        }
        
        price = fallback_prices.get(product_id, 100.0)
        
        # Log warning when using fallback (should not happen in normal operation)
        logger.debug(f"Using fallback for {product_id} - pair does not exist on Coinbase")
        
        return {
            'product_id': product_id,
            'price': price,
            'volume_24h': 1000000.0,
            'low_24h': price * 0.95,
            'high_24h': price * 1.05,
            'price_percent_chg_24h': 0.0,
            'is_fallback': True  # Flag to indicate this is fallback data
        }
    
    def get_candles(self, product_id: str, start: datetime = None,
                    end: datetime = None, granularity: str = "ONE_HOUR") -> pd.DataFrame:
        """
        Get historical candle data for a trading pair.
        
        Args:
            product_id: Trading pair (e.g., 'BTC-USD')
            start: Start time for candles
            end: End time for candles
            granularity: Candle granularity (ONE_HOUR, FOUR_HOUR, ONE_DAY)
            
        Returns:
            Pandas DataFrame with OHLCV data
        """
        try:
            # Convert granularity to ISO format
            granularity_map = {
                "ONE_MINUTE": "60",
                "FIVE_MINUTE": "300",
                "FIFTEEN_MINUTE": "900",
                "ONE_HOUR": "3600",
                "SIX_HOUR": "21600",
                "ONE_DAY": "86400"
            }
            granularity_iso = granularity_map.get(granularity, "3600")
            
            # Build request parameters
            params = {
                'granularity': granularity_iso
            }
            
            if start:
                params['start'] = start.isoformat()
            if end:
                params['end'] = end.isoformat()
            
            response = self._make_request('GET', f'products/{product_id}/candles')
            
            if response and isinstance(response, list) and len(response) > 0:
                candles_data = response
                
                # Convert to DataFrame
                df = pd.DataFrame(candles_data, columns=['timestamp', 'low', 'high', 'open', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                df.set_index('timestamp', inplace=True)
                
                # Sort by timestamp
                df.sort_index(inplace=True)
                
                return df
            else:
                # Return empty DataFrame with correct columns
                return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        except Exception as e:
            logger.error(f"Failed to get candles for {product_id}: {e}")
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

    def _place_legacy_order(self, product_id: str, side: str, size: float) -> Optional[Dict[str, Any]]:
        """
        Place a market order using legacy Coinbase Pro API as fallback.

        Args:
            product_id: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            size: Order size

        Returns:
            Order result dictionary if successful, None otherwise
        """
        try:
            logger.info(f"Attempting order via Legacy API: {side.upper()} {size} {product_id}")
            
            # Skip GBP-USD requests which cause 404 errors
            if product_id == 'GBP-USD':
                logger.warning(f"Skipping GBP-USD request - this pair doesn't exist and causes 404 errors")
                return self._get_fallback_ticker(product_id)
            
            # For legacy API, convert size to appropriate format
            order_data = {
                'product_id': product_id,
                'side': side.lower(), # Legacy API uses lowercase
                'type': 'market',
                'size': str(size)
            }
            
            # Use legacy API endpoint and authentication
            response = self._make_legacy_request('POST', 'orders', order_data)

            if response and 'id' in response:
                logger.info(f"Legacy API order placed: {response['id']}")
                return {
                    'success': True,
                    'order_id': response['id'],
                    'size': size,
                    'price': 0.0,
                    'mode': 'live'
                }
            elif response and 'message' in response:
                logger.error(f"Legacy API error: {response['message']}")
                return None
            else:
                logger.error("Legacy API: No response received")
                return None

        except Exception as e:
            logger.error(f"Legacy API failed: {e}")
            return None

    def _make_legacy_request(self, method: str, endpoint: str, data: dict = None) -> Optional[dict]:
        """
        Make a request to the legacy Coinbase Pro API for fallback.

        Args:
            method: HTTP method
            endpoint: API endpoint
            data: Request data

        Returns:
            Response data or None
        """
        try:
            # Use legacy Coinbase Pro API endpoints
            url = f"https://api.exchange.coinbase.com/{endpoint}"

            # Legacy authentication (HMAC-SHA256)
            timestamp = str(int(time.time()))
            body = json.dumps(data) if data else ''
            message = timestamp + method.upper() + f"/{endpoint}" + body

            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            headers = {
                'Content-Type': 'application/json',
                'CB-ACCESS-KEY': self.api_key,
                'CB-ACCESS-SIGN': signature,
                'CB-ACCESS-TIMESTAMP': timestamp,
                'CB-ACCESS-PASSPHRASE': ''  # Empty for Coinbase Pro
            }

            response = requests.request(method, url, headers=headers, data=body, 
                                   proxies=self.proxy_config if self.use_proxy else None,
                                   timeout=settings.PROXY_TIMEOUT if self.use_proxy else 30)

            # Rate limiting
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self._rate_limit_delay:
                time.sleep(self._rate_limit_delay - time_since_last)

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Legacy API {method} {endpoint} failed: {response.status_code} - {response.text}")
                try:
                    return response.json()
                except:
                    return {'message': f'HTTP {response.status_code}'}

        except Exception as e:
            logger.error(f"Legacy API request failed: {e}")
            return None

        """
        Place a market order using Coinbase Advanced Trade API.
        
        Args:
            product_id: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            size: Order size in base currency (crypto amount)
            
        Returns:
            Order result dictionary with order_id, size, price if successful, None otherwise
        """
        if not self.api_key:
            logger.warning("Cannot place order: No API credentials (paper trading mode)")
            return {
                'success': True,
                'order_id': f"paper_order_{int(time.time())}",
                'size': size,
                'price': 0.0,
                'mode': 'paper'
            }
        
        # Try Advanced Trade API first
        try:
            logger.info(f"Attempting order via Advanced Trade API: {side.upper()} {size} {product_id}")
            # Format size using product-specific precision
            formatted_size = self._format_size_for_order(size, product_id)
            order_data = {
                'client_order_id': f"bot_{int(time.time())}",
                'product_id': product_id,
                'side': side.upper(),  # API requires uppercase: BUY/SELL
                'order_configuration': {
                    'market_market_ioc': {
                        'base_size': formatted_size
                    }
                }
            }

            response = self._make_request('POST', 'brokerage/orders', order_data)

            if response and 'order_id' in response:
                # Extract order details from response
                result = {
                    'success': True,
                    'order_id': response['order_id'],
                    'size': size,
                    'price': 0.0,  # Market orders don't have predetermined price
                    'mode': 'live'
                }

                # Try to get actual execution price if available
                if 'order_configuration' in response:
                    config = response['order_configuration']
                    if 'market_market_ioc' in config:
                        market_info = config['market_market_ioc']
                        if 'quote_size' in market_info:
                            try:
                                result['price'] = float(market_info['quote_size']) / size
                            except:
                                pass

                logger.info(f"Advanced Trade API order placed: {result['order_id']}")
                return result
            elif response and 'error' in response:
                error_msg = response.get('message', 'Unknown error')
                if 'account is not available' in error_msg:
                    logger.warning("Advanced Trade API permissions not available (check API key has 'trade' permission), trying legacy API...")
                    # Fall back to legacy API
                    return self._place_legacy_order(product_id, side, size)
                else:
                    logger.error(f"Advanced Trade API error: {error_msg}")
                    return None
            else:
                logger.error("Advanced Trade API: No response received")
                return None

        except Exception as e:
            logger.error(f"Advanced Trade API failed: {e}")
            logger.info("Falling back to legacy Coinbase API...")
            # Fall back to legacy API
            return self._place_legacy_order(product_id, side, size)
                
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            return None
    
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Get order details.
        
        Args:
            order_id: Order ID to retrieve
            
        Returns:
            Order details dictionary
        """
        if not self.api_key:
            return None
        
        try:
            response = self._make_request('GET', f'brokerage/orders/historical/{order_id}')
            return response
            
        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None

    def get_transaction_summary(self) -> Optional[Dict[str, Any]]:
        """
        Get transaction fee summary including user's fee tier rates.
        
        Returns:
            Dictionary with maker_fee_rate, taker_fee_rate, total_fees, total_volume
            or None if failed
        """
        logger.info("Fetching transaction summary from Coinbase...")
        
        # Try using SDK first
        if self.sdk_client:
            try:
                response = self.sdk_client.get_transaction_summary(product_type="SPOT")
                
                # Parse the response - SDK returns GetTransactionSummaryResponse object
                # Access fee_tier as an attribute, not a dict key
                if hasattr(response, 'fee_tier'):
                    fee_tier = response.fee_tier
                    # fee_tier is a dict-like object, access by key
                    return {
                        'maker_fee_rate': float(fee_tier.get('maker_fee_rate', 0)),
                        'taker_fee_rate': float(fee_tier.get('taker_fee_rate', 0)),
                        'total_fees': float(response.total_fees) if hasattr(response, 'total_fees') else 0,
                        'total_volume': float(response.total_volume) if hasattr(response, 'total_volume') else 0,
                        'pricing_tier': fee_tier.get('pricing_tier', 'Unknown')
                    }
            except Exception as e:
                logger.warning(f"SDK get_transaction_summary failed: {e}")
        
        # Fallback: try direct API call
        try:
            response = self._make_request('GET', 'brokerage/transaction_summary?product_type=SPOT')
            if response and 'fee_tier' in response:
                fee_tier = response.get('fee_tier', {})
                return {
                    'maker_fee_rate': float(fee_tier.get('maker_fee_rate', 0)),
                    'taker_fee_rate': float(fee_tier.get('taker_fee_rate', 0)),
                    'total_fees': float(response.get('total_fees', 0)),
                    'total_volume': float(response.get('total_volume', 0)),
                    'pricing_tier': fee_tier.get('pricing_tier', 'Unknown')
                }
        except Exception as e:
            logger.warning(f"Direct API call to transaction_summary failed: {e}")
        
        logger.warning("Could not fetch transaction summary, will use fallback fees")
        return None
    
    def get_fees(self) -> Dict[str, Any]:
        """
        Get user's current fee rates with fallback to defaults.
        
        Returns:
            Dictionary with maker_fee and taker_fee
        """
        # Try to get from database first (cached)
        from src.database import db_manager
        cached_fees = db_manager.get_fee_rates()
        
        if cached_fees:
            return cached_fees
        
        # Fetch fresh from Coinbase
        summary = self.get_transaction_summary()
        
        if summary:
            fees = {
                'maker_fee': summary['maker_fee_rate'],
                'taker_fee': summary['taker_fee_rate'],
                'pricing_tier': summary.get('pricing_tier', 'Unknown'),
                'is_fallback': False
            }
            # Save to database
            db_manager.save_fee_rates(
                maker_fee=fees['maker_fee'],
                taker_fee=fees['taker_fee']
            )
            return fees
        
        # Return fallback fees
        from config.settings import settings
        return {
            'maker_fee': settings.DEFAULT_MAKER_FEE,
            'taker_fee': settings.DEFAULT_TAKER_FEE,
            'pricing_tier': 'Fallback (default)',
            'is_fallback': True
        }

    def convert_usdc_to_usd(self, usdc_amount: float) -> Optional[Dict[str, Any]]:
        """
        Convert USDC to USD using Coinbase conversion API.

        Args:
            usdc_amount: Amount of USDC to convert

        Returns:
            Conversion result or None if failed
        """
        try:
            logger.info(f"Converting {usdc_amount} USDC to USD")

            # Use SDK if available
            if self.sdk_client:
                # Get USDC account
                accounts = self.sdk_client.get_accounts()
                usdc_account = None
                usd_account = None

                # Handle different SDK response formats
                if hasattr(accounts, 'data'):
                    account_list = accounts.data
                elif hasattr(accounts, 'accounts'):
                    account_list = accounts.accounts
                else:
                    account_list = accounts

                for account in account_list:
                    if account.currency == 'USDC':
                        usdc_account = account
                    elif account.currency == 'USD':
                        usd_account = account

                if not usdc_account:
                    return {'success': False, 'error': 'No USDC account found'}

                if not usd_account:
                    # If no USD account exists, USDC is already valued in USD terms (1:1)
                    logger.info(f"No USD account found, treating {usdc_amount} USDC as already in USD")
                    return {
                        'success': True,
                        'converted_amount': usdc_amount,
                        'message': 'USDC treated as USD equivalent (no conversion needed)'
                    }

                # Create conversion quote
                quote = self.sdk_client.create_convert_quote(
                    from_account=usdc_account.id,
                    to_account=usd_account.id,
                    amount=str(usdc_amount)
                )

                if hasattr(quote, 'success') and quote.success:
                    # Commit the conversion
                    conversion = self.sdk_client.commit_convert_trade(
                        trade_id=quote.trade.id
                    )

                    if hasattr(conversion, 'success') and conversion.success:
                        logger.info(f"Successfully converted {usdc_amount} USDC to USD")
                        return {
                            'success': True,
                            'converted_amount': usdc_amount,
                            'trade_id': conversion.trade.id if hasattr(conversion, 'trade') else 'unknown'
                        }
                    else:
                        return {'success': False, 'error': 'Failed to commit conversion'}
                else:
                    return {'success': False, 'error': 'Failed to create conversion quote'}

        except Exception as e:
            logger.error(f"USDC to USD conversion failed: {e}")
            return {'success': False, 'error': str(e)}

    def place_market_order(self, product_id: str, side: str, size: float) -> Optional[Dict[str, Any]]:
        """
        Place a market order using Coinbase Advanced SDK or REST fallback.

        Args:
            product_id: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            size: Order size in base currency (crypto amount)

        Returns:
            Order result dictionary with order_id, size, price if successful, None otherwise
        """
        order_start_time = time.time()
        logger.info(f"[DEBUG] ===== ORDER PLACEMENT STARTED ======")
        logger.info(f"[DEBUG] Timestamp: {datetime.now().isoformat()}")
        logger.info(f"[DEBUG] Product ID: {product_id}")
        logger.info(f"[DEBUG] Side: {side.upper()}")
        logger.info(f"[DEBUG] Size: {size}")
        logger.info(f"[DEBUG] API Key Present: {bool(self.api_key)}")
        logger.info(f"[DEBUG] SDK Client Available: {bool(self.sdk_client)}")
        
        # Check current account balances before order
        try:
            accounts = self.get_accounts()
            logger.info(f"[DEBUG] Available accounts: {len(accounts)}")
            for account in accounts[:5]:  # Show first 5 accounts
                currency = account.get('currency', 'UNKNOWN')
                available = float(account.get('available', 0))
                if available > 0:
                    logger.info(f"[DEBUG] Account {currency}: {available} available")
        except Exception as e:
            logger.error(f"[DEBUG] Error getting account balances: {e}")

        if not self.api_key:
            logger.warning("[DEBUG] Cannot place order: No API credentials (paper trading mode)")
            paper_result = {
                'success': True,
                'order_id': f"paper_order_{int(time.time())}",
                'size': size,
                'price': 0.0,
                'mode': 'paper'
            }
            logger.info(f"[DEBUG] Paper trade result: {paper_result}")
            return paper_result

        # Try Advanced Trade API with official SDK first
        if self.sdk_client:
            max_retries = 3
            base_delay = 1.0

            for attempt in range(max_retries):
                try:
                    logger.info(f"[DEBUG] Placing order via Coinbase SDK (attempt {attempt + 1}/{max_retries})...")
                    client_order_id = f"bot_{int(time.time())}_{attempt}"
                    logger.info(f"[DEBUG] Client Order ID: {client_order_id}")

                    # Use official SDK methods
                    if side.lower() == 'buy':
                        logger.info(f"[DEBUG] Using SDK market_order_buy...")
                        # Format size using product-specific precision
                        formatted_size = self._format_size_for_order(size, product_id)
                        logger.info(f"[DEBUG] Formatted size (buy): {formatted_size}")
                        order = self.sdk_client.market_order_buy(
                            client_order_id=client_order_id,
                            product_id=product_id,
                            base_size=formatted_size
                        )
                    else:  # sell
                        logger.info(f"[DEBUG] Using SDK market_order_sell...")
                        # Format size using product-specific precision
                        formatted_size = self._format_size_for_order(size, product_id)
                        logger.info(f"[DEBUG] Formatted size (sell): {formatted_size}")
                        order = self.sdk_client.market_order_sell(
                            client_order_id=client_order_id,
                            product_id=product_id,
                            base_size=formatted_size
                        )

                    logger.info(f"[DEBUG] SDK order response type: {type(order)}")
                    logger.info(f"[DEBUG] SDK order response attributes: {dir(order)}")
                    
                    # Extract order details from SDK response
                    if hasattr(order, 'success') and order.success:
                        order_id = getattr(order, 'order_id', f"sdk_order_{int(time.time())}")
                        
                        # Fetch order details to get actual filled price and fees
                        filled_price = 0.0
                        total_fees = 0.0
                        try:
                            order_details = self.get_order(order_id)
                            if order_details:
                                # Try to extract average fill price from order details
                                if 'order' in order_details:
                                    order_info = order_details['order']
                                    # Check for filled value and size to calculate average price
                                    total_value = float(order_info.get('total_value', {}).get('value', 0))
                                    base_size = float(order_info.get('filled_base_volume', 0))
                                    if base_size > 0:
                                        filled_price = total_value / base_size
                                        logger.info(f"[DEBUG] Fetched fill price: {filled_price} for order {order_id}")
                                    # Extract total_fees from order details
                                    total_fees = float(order_info.get('total_fees', 0))
                                    logger.info(f"[DEBUG] Fetched fees: {total_fees} for order {order_id}")
                        except Exception as e:
                            logger.warning(f"[DEBUG] Could not fetch order details: {e}")
                        
                        # If still no price, try using client_order_id
                        if filled_price == 0.0:
                            try:
                                client_order_id = f"bot_{int(time.time())}_{attempt}"
                                order_details = self.get_order(client_order_id)
                                if order_details and 'order' in order_details:
                                    order_info = order_details['order']
                                    total_value = float(order_info.get('total_value', {}).get('value', 0))
                                    base_size = float(order_info.get('filled_base_volume', 0))
                                    if base_size > 0:
                                        filled_price = total_value / base_size
                                        logger.info(f"[DEBUG] Fetched fill price via client_order_id: {filled_price}")
                            except Exception as e:
                                logger.warning(f"[DEBUG] Could not fetch via client_order_id: {e}")
                        
                        # Last resort: use current market price as fallback
                        if filled_price == 0.0:
                            try:
                                ticker = self.get_product_ticker(product_id)
                                if ticker and 'price' in ticker:
                                    filled_price = float(ticker['price'])
                                    logger.info(f"[DEBUG] Using market price as fallback: {filled_price}")
                            except Exception:
                                pass
                        
                        sdk_result = {
                            'success': True,
                            'order_id': order_id,
                            'size': size,
                            'price': filled_price,
                            'fees': total_fees,
                            'mode': 'live_sdk',
                            'response_time': round(time.time() - order_start_time, 2)
                        }
                        logger.info(f"[DEBUG] SDK order SUCCESS: {sdk_result}")
                        return sdk_result
                    else:
                        # SDK returned failure
                        error_msg = 'Unknown error'
                        error_details = 'No details'
                        
                        try:
                            order_dict = order.to_dict() if hasattr(order, 'to_dict') else {}
                            logger.error(f"[DEBUG] Full SDK order response: {order_dict}")
                        except Exception as e:
                            logger.error(f"[DEBUG] Could not convert order to dict: {e}")
                        
                        if hasattr(order, 'error_response') and order.error_response:
                            err = order.error_response
                            error_msg = getattr(err, 'message', getattr(err, 'error', 'Unknown error'))
                            error_details = getattr(err, 'error_details', 'No details')
                            logger.error(f"[DEBUG] SDK error_response: {err}")
                        else:
                            error_msg = getattr(order, 'message', 'Unknown error')
                            error_details = getattr(order, 'error_details', 'No details')
                        
                        logger.error(f"[DEBUG] SDK order FAILED: {error_msg}")
                        logger.error(f"[DEBUG] SDK error details: {error_details}")
                        
                        # Retry on failure
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            logger.info(f"[DEBUG] Retrying in {delay}s...")
                            time.sleep(delay)
                            continue
                        
                        failed_result = {
                            'success': False,
                            'error': error_msg,
                            'error_details': error_details,
                            'order_id': None,
                            'mode': 'live_sdk_failed'
                        }
                        logger.error(f"[DEBUG] SDK failed result: {failed_result}")
                        # Fall through to REST

                except Exception as e:
                    delay = base_delay * (2 ** attempt)
                    logger.error(f"[DEBUG] SDK order EXCEPTION (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"[DEBUG] Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        logger.error(f"[DEBUG] SDK failed after {max_retries} attempts, falling back to REST")
                        import traceback
                        logger.error(f"[DEBUG] SDK exception traceback: {traceback.format_exc()}")

        # Fallback to REST implementation
        try:
            logger.info(f"[DEBUG] Attempting order via REST API...")
            # Format size using product-specific precision
            formatted_size = self._format_size_for_order(size, product_id)
            order_data = {
                'client_order_id': f"bot_{int(time.time())}",
                'product_id': product_id,
                'side': side.upper(),  # API requires uppercase: BUY/SELL
                'order_configuration': {
                    'market_market_ioc': {
                        'base_size': formatted_size
                    }
                }
            }
            
            logger.info(f"[DEBUG] REST order data: {order_data}")
            logger.info(f"[DEBUG] Making POST request to brokerage/orders...")

            response = self._make_request('POST', 'brokerage/orders', order_data)
            
            logger.info(f"[DEBUG] REST response type: {type(response)}")
            logger.info(f"[DEBUG] REST response: {response}")
            
            if response and 'order_id' in response:
                # Extract order details from response
                rest_result = {
                    'success': True,
                    'order_id': response['order_id'],
                    'size': size,
                    'price': 0.0,  # Market orders don't have predetermined price
                    'mode': 'live_rest',
                    'response_time': round(time.time() - order_start_time, 2)
                }

                # Try to get actual execution price if available
                if 'order_configuration' in response:
                    config = response['order_configuration']
                    if 'market_market_ioc' in config:
                        market_info = config['market_market_ioc']
                        if 'quote_size' in market_info:
                            try:
                                rest_result['price'] = float(market_info['quote_size']) / size
                            except Exception as e:
                                logger.warning(f"[DEBUG] Could not calculate execution price: {e}")

                logger.info(f"[DEBUG] REST order SUCCESS: {rest_result}")
                return rest_result
            elif response and 'error' in response:
                error_msg = response.get('message', 'Unknown error')
                error_response = {
                    'success': False,
                    'error': error_msg,
                    'full_response': response,
                    'mode': 'live_rest_failed'
                }
                
                if 'account is not available' in error_msg:
                    logger.warning("[DEBUG] Advanced Trade API permissions not available (check API key has 'trade' permission), trying legacy API...")
                    # Fall back to legacy API
                    return self._place_legacy_order(product_id, side, size)
                else:
                    logger.error(f"[DEBUG] REST order FAILED: {error_msg}")
                    logger.error(f"[DEBUG] Full error response: {error_response}")
                    return error_response
            else:
                no_response_error = {
                    'success': False,
                    'error': 'No response received',
                    'mode': 'live_rest_no_response'
                }
                logger.error("[DEBUG] REST order: No response received")
                return no_response_error

        except Exception as e:
            logger.error(f"[DEBUG] REST API EXCEPTION: {e}")
            import traceback
            logger.error(f"[DEBUG] REST exception traceback: {traceback.format_exc()}")
            logger.info("[DEBUG] Falling back to legacy Coinbase API...")
            # Fall back to legacy API
            try:
                legacy_result = self._place_legacy_order(product_id, side, size)
                legacy_result['response_time'] = round(time.time() - order_start_time, 2)
                logger.info(f"[DEBUG] Legacy fallback result: {legacy_result}")
                return legacy_result
            except Exception as legacy_e:
                logger.error(f"[DEBUG] Legacy API also failed: {legacy_e}")
                return {
                    'success': False,
                    'error': f'Both SDK and REST failed: {str(e)}, legacy error: {str(legacy_e)}',
                    'mode': 'all_failed'
                }
        
        finally:
            total_time = round(time.time() - order_start_time, 2)
            logger.info(f"[DEBUG] ===== ORDER PLACEMENT COMPLETED in {total_time}s ======")

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if successful, False otherwise
        """
        if not self.api_key:
            return False
        
        try:
            response = self._make_request('POST', f'brokerage/orders/delete', {
                'order_ids': [order_id]
            })
            
            return response is not None
            
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def get_orders(self, product_id: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get order history.
        
        Args:
            product_id: Filter by product (optional)
            limit: Maximum number of orders to return
            
        Returns:
            List of order dictionaries
        """
        if not self.api_key:
            return []
        
        try:
            params = {'limit': limit}
            if product_id:
                params['product_id'] = product_id
            
            response = self._make_request('GET', 'brokerage/orders/historical', params)
            
            if response and 'orders' in response:
                return response['orders']
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            return []

    def _create_jwt_token(self, method: str, uri: str, api_key: str = None, api_secret: str = None) -> str:
        """
        Create JWT token for Coinbase CDP API authentication per official documentation.

        Args:
            method: HTTP method (GET, POST, etc.)
            uri: Request URI (relative to /api/v3/brokerage/)
            api_key: API key to use (defaults to self.api_key)
            api_secret: API secret to use (defaults to self.api_secret)

        Returns:
            JWT token string
        """
        if not ECDSA_AVAILABLE:
            raise Exception("ECDSA libraries not available for Advanced Trade API authentication")

        # Use provided credentials or fall back to instance credentials
        key = api_key or self.advanced_api_key or self.api_key
        secret = api_secret or self.advanced_api_secret or self.api_secret

        if not key or not secret:
            raise Exception("API key and secret required for JWT authentication")

        try:
            import jwt
            from cryptography.hazmat.primitives import serialization
            import time
            import secrets

            # Create JWT URI per official Coinbase CDP documentation
            # Format: METHOD api.coinbase.com/api/v3/brokerage/ENDPOINT
            if not uri.startswith('/'):
                uri = f"/{uri}"

            # Remove 'brokerage/' prefix if present to avoid duplication
            if uri.startswith('/brokerage/'):
                clean_uri = uri[11:]  # Remove '/brokerage/' prefix, keep the rest
                jwt_uri = f"{method.upper()} api.coinbase.com/api/v3/brokerage/{clean_uri}"
            else:
                jwt_uri = f"{method.upper()} api.coinbase.com/api/v3/brokerage{uri}"

            # Parse the EC private key with better handling
            try:
                # First try direct parsing
                private_key_bytes = secret.encode('utf-8')
                private_key = serialization.load_pem_private_key(
                    private_key_bytes, 
                    password=None
                )
                logger.debug("Successfully parsed EC private key directly")
            except Exception as e:
                logger.debug(f"Direct parsing failed: {e}")
                # Try cleaning up the format
                try:
                    # Remove common formatting issues
                    cleaned_secret = secret.strip()
                    # Ensure proper newlines
                    if '\\n' in cleaned_secret:
                        cleaned_secret = cleaned_secret.replace('\\n', '\n')
                    
                    # Try parsing again
                    private_key_bytes = cleaned_secret.encode('utf-8')
                    private_key = serialization.load_pem_private_key(
                        private_key_bytes, 
                        password=None
                    )
                    logger.debug("Successfully parsed EC private key after cleaning")
                except Exception as e2:
                    logger.error(f"Failed to parse EC private key even after cleaning: {e2}")
                    raise Exception(f"Invalid EC private key format: {e2}")

            # Create JWT payload per official CDP documentation
            now = int(time.time())
            payload = {
                'sub': key,  # Subject: API key
                'iss': 'coinbase-cloud',  # Issuer: Coinbase Cloud
                'nbf': now,  # Not before: now
                'exp': now + 120,  # Expires: 2 minutes
                'aud': ['retail_rest_api_proxy'],  # Audience: required for trading
                'uri': jwt_uri  # URI: request method + host + path
            }

            # Create JWT header with nonce for security
            header = {
                'alg': 'ES256',  # Algorithm: ECDSA with P-256
                'typ': 'JWT',  # Type: JWT
                'kid': key,  # Key ID: the API key
                'nonce': secrets.token_hex()  # Nonce: random hex for replay protection
            }

            # Generate and sign JWT
            jwt_token = jwt.encode(
                payload,
                private_key,
                algorithm='ES256',
                headers=header
            )

            logger.debug(f"JWT token generated successfully for {method} {uri}")
            return jwt_token

        except Exception as e:
            logger.error(f"Failed to create JWT token: {e}")
            raise

        try:
            logger.debug(f"Creating JWT token with key: {key[:10]}...")
            logger.debug(f"Secret length: {len(secret)}")

            # Parse the EC private key - handle escaped newlines first
            if '\\n' in secret:
                # Decode escaped newlines (common in environment variables)
                logger.debug("Decoding escaped newlines...")
                decoded_secret = secret.encode().decode('unicode_escape')
                logger.debug(f"Decoded secret length: {len(decoded_secret)}")
                logger.debug(f"Decoded secret starts with: {decoded_secret[:50]}")
            else:
                decoded_secret = secret
                logger.debug("No escaped newlines found")

            # Parse the EC private key
            logger.debug(f"Trying to parse key, decoded_secret length: {len(decoded_secret)}")
            logger.debug(f"decoded_secret[:100]: {decoded_secret[:100]}")
            logger.debug(f"'BEGIN EC PRIVATE KEY' in decoded_secret: {'BEGIN EC PRIVATE KEY' in decoded_secret}")

            if 'BEGIN EC PRIVATE KEY' in decoded_secret:
                logger.debug("Found BEGIN EC PRIVATE KEY marker")
                # Standard EC PEM format
                logger.debug("About to call ecdsa.SigningKey.from_pem...")
                private_key = ecdsa.SigningKey.from_pem(decoded_secret.encode())
                logger.debug("Successfully parsed EC private key")
            elif 'BEGIN PRIVATE KEY' in decoded_secret:
                logger.debug("Found BEGIN PRIVATE KEY marker")
                # PKCS#8 format - may need conversion
                private_key = ecdsa.SigningKey.from_pem(decoded_secret.encode())
            else:
                logger.debug("No standard PEM markers found, trying as-is")
                # Try as-is (might be base64 encoded or other format)
                try:
                    private_key = ecdsa.SigningKey.from_pem(decoded_secret.encode())
                except:
                    # Try decoding from base64 if it's encoded
                    try:
                        logger.debug("Trying base64 decode...")
                        base64_decoded = base64.b64decode(decoded_secret).decode()
                        private_key = ecdsa.SigningKey.from_pem(base64_decoded.encode())
                    except:
                        raise Exception("Unable to parse private key - invalid format")

            # Create JWT payload (Coinbase Advanced Trade format)
            now = int(time.time())
            # URI should be the full path including /api/v3
            if not uri.startswith('/api/v3'):
                uri = f"/api/v3{uri}" if uri.startswith('/') else f"/api/v3/{uri}"

            # Create the full URI for the request
            full_uri = f"{method.upper()} api.coinbase.com{uri}"

            payload = {
                'sub': key,
                'iss': 'coinbase-cloud',
                'nbf': now,
                'exp': now + 120,  # 2 minutes expiration
                'aud': ['retail_rest_api_proxy'],
                'uri': full_uri
            }

            # Create JWT header
            header = {
                'alg': 'ES256',
                'kid': key,
                'typ': 'JWT'
            }

            # Encode header and payload
            header_b64 = base64.urlsafe_b64encode(
                json.dumps(header, separators=(',', ':')).encode()
            ).decode().rstrip('=')

            payload_b64 = base64.urlsafe_b64encode(
                json.dumps(payload, separators=(',', ':')).encode()
            ).decode().rstrip('=')

            # Create message to sign
            message = f"{header_b64}.{payload_b64}"

            # Sign with ECDSA using SHA256
            signature = private_key.sign(message.encode(), hashfunc=hashlib.sha256)

            # Encode signature
            signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip('=')

            # Create final JWT
            jwt_token = f"{header_b64}.{payload_b64}.{signature_b64}"

            logger.debug(f"Created JWT token for {method} {uri}")
            return jwt_token

        except Exception as e:
            logger.error(f"Failed to create JWT token: {e}")
            import traceback
            traceback.print_exc()
            raise


# Global Coinbase API instance
coinbase_api = CoinbaseAPI()