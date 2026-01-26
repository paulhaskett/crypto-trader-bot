"""
Currency conversion utilities for multi-currency trading bot.

This module provides:
- Real-time exchange rate fetching
- Currency conversion utilities
- Formatting functions for different currencies
- Exchange rate caching and management
"""

import logging
import time
from typing import Dict, Optional, Tuple
import requests
from config.settings import settings

logger = logging.getLogger(__name__)

class CurrencyConverter:
    """Handles currency conversion and formatting for the trading bot."""
    
    def __init__(self):
        self._exchange_rates: Dict[str, float] = {}
        self._last_update: float = 0
        self._cache_duration: int = 300  # 5 minute cache (reduced for more frequent updates)
        
        # Currency symbols and formatting
        self.CURRENCY_SYMBOLS = {
            'USD': '$',
            'GBP': '£',
            'EUR': '€'
        }
        
        # Default rates (will be overwritten by API)
        self._exchange_rates = {
            'USD': 1.0,
            'GBP': 0.80,  # Default fallback
            'EUR': 0.85   # Default fallback
        }
    
    def get_last_update(self) -> Optional[float]:
        """
        Get timestamp of last exchange rate update.

        Returns:
            Unix timestamp of last update, or None if never updated
        """
        return self._last_update if self._last_update > 0 else None

    def get_exchange_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Get exchange rate between two currencies.

        Args:
            from_currency: Source currency code (e.g., 'USD')
            to_currency: Target currency code (e.g., 'GBP')

        Returns:
            Exchange rate or None if not available
        """
        if from_currency == to_currency:
            return 1.0
            
        # Update rates if cache is expired
        if time.time() - self._last_update > self._cache_duration:
            self._update_rates()
        
        # Convert via USD as base currency
        from_usd_rate = self._exchange_rates.get(from_currency)
        to_usd_rate = self._exchange_rates.get(to_currency)
        
        if from_usd_rate is None or to_usd_rate is None:
            logger.warning(f"Exchange rate not available for {from_currency}->{to_currency}")
            return None
        
        return to_usd_rate / from_usd_rate
    
    def convert_amount(self, amount: float, from_currency: str, to_currency: str) -> float:
        """
        Convert amount from one currency to another.
        
        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code
            
        Returns:
            Converted amount or original if conversion fails
        """
        if from_currency == to_currency:
            return amount
            
        rate = self.get_exchange_rate(from_currency, to_currency)
        if rate is None:
            logger.warning(f"Failed to convert {amount} {from_currency} to {to_currency}")
            return amount
        
        return amount * rate
    
    def format_currency(self, amount: float, currency: str, include_symbol: bool = True) -> str:
        """
        Format amount with appropriate currency symbol and precision.
        
        Args:
            amount: Amount to format
            currency: Currency code
            include_symbol: Whether to include currency symbol
            
        Returns:
            Formatted currency string
        """
        symbol = self.CURRENCY_SYMBOLS.get(currency, currency)
        
        # Format with appropriate decimal places
        if currency == 'USD' or currency == 'GBP':
            formatted_amount = f"{amount:.2f}"
        else:
            formatted_amount = f"{amount:.4f}"
        
        if include_symbol:
            return f"{symbol}{formatted_amount}"
        else:
            return formatted_amount
    
    def _update_rates(self) -> bool:
        """
        Update exchange rates from API.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Use Coinbase API for exchange rates
            url = "https://api.coinbase.com/v2/exchange-rates"
            params = {'currency': 'USD'}
            
            # Configure proxy if enabled
            proxy_config = {}
            if hasattr(settings, 'USE_PROXY') and settings.USE_PROXY:
                proxy_config = {
                    'http': f'http://{settings.PROXY_HOST}:{settings.COINBASE_API_PROXY_PORT}',
                    'https': f'http://{settings.PROXY_HOST}:{settings.COINBASE_API_PROXY_PORT}'
                }
            
            response = requests.get(url, params=params, timeout=10, proxies=proxy_config if proxy_config else None)
            response.raise_for_status()
            
            data = response.json()
            rates = data.get('data', {}).get('rates', {})
            
            # Update known currencies
            for currency in ['GBP', 'EUR']:
                rate = rates.get(currency)
                if rate:
                    self._exchange_rates[currency] = float(rate)
            
            self._last_update = time.time()
            logger.info(f"Updated exchange rates: {dict(self._exchange_rates)}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update exchange rates: {e}")
            # Keep cached rates if available
            return False
    
    def get_supported_currencies(self) -> Dict[str, str]:
        """
        Get supported currencies with their symbols.
        
        Returns:
            Dictionary of currency codes to symbols
        """
        return self.CURRENCY_SYMBOLS.copy()
    
    def convert_portfolio_to_currency(self, portfolio: list, target_currency: str) -> list:
        """
        Convert a list of portfolio items to target currency.
        
        Args:
            portfolio: List of portfolio items with 'value_usd' and 'currency' fields
            target_currency: Target currency code
            
        Returns:
            Updated portfolio with converted values
        """
        converted_portfolio = []
        
        for item in portfolio:
            converted_item = item.copy()
            
            # Convert the value to target currency
            if 'value_usd' in item:
                converted_value = self.convert_amount(
                    item['value_usd'], 'USD', target_currency
                )
                converted_item['value'] = converted_value
                converted_item['formatted_value'] = self.format_currency(
                    converted_value, target_currency
                )
            
            converted_portfolio.append(converted_item)
        
        return converted_portfolio

# Global currency converter instance
currency_converter = CurrencyConverter()