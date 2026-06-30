"""
Price Mapper - Centralized coin ID translation service.

This module provides a unified interface for translating between
different exchange-specific coin/pair identifiers.

v1.3.0 - Added Binance mappings.

Supported Exchanges:
- Coinbase: BTC-GBP, ETH-USD, etc.
- Binance: BTCGBP, ETHGBP (SPOT symbols)
- CoinGecko: bitcoin, ethereum, etc. (coin IDs)
- Kraken: XXBTZGBP, XETHZUSD, etc.
- Chainlink: BTC/USD, ETH/USD, etc. (feed names)
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PriceMapper:
    """
    Centralized price mapping service for cross-exchange compatibility.
    
    Provides translation between different exchange-specific identifiers
    for cryptocurrencies and trading pairs.
    """
    
    # Coinbase product ID to CoinGecko coin ID
    COINBASE_TO_COINGECKO: Dict[str, str] = {
        'BTC-GBP': 'bitcoin',
        'ETH-GBP': 'ethereum',
        'SOL-GBP': 'solana',
        'LTC-GBP': 'litecoin',
        'ADA-GBP': 'cardano',
        'LINK-GBP': 'chainlink',
    }
    
    # Coinbase product ID to Binance symbol (SPOT)
    # Binance uses format like BTCGBP, ETHGBP (no separator)
    COINBASE_TO_BINANCE: Dict[str, str] = {
        'BTC-GBP': 'BTCGBP',
        'ETH-GBP': 'ETHGBP',
        'SOL-GBP': 'SOLGBP',
        'LTC-GBP': 'LTCGBP',
        'ADA-GBP': 'ADAGBP',
        'LINK-GBP': 'LINKGBP',
    }
    
    # Coinbase product ID to Kraken pair name
    # Note: Kraken uses XXBT for BTC, XETH for ETH in some pairs
    COINBASE_TO_KRAKEN: Dict[str, str] = {
        'BTC-GBP': 'XXBTZGBP',  # Kraken's main GBP pair for BTC
        'ETH-GBP': 'XETHZGBP',  # Kraken's main GBP pair for ETH
        'SOL-GBP': 'SOLGBP',
        'LTC-GBP': 'LTCGBP',
        'ADA-GBP': 'ADAGBP',
        'LINK-GBP': 'LINKGBP',
    }
    
    # Coinbase USD product ID to Kraken pair
    COINBASE_USD_TO_KRAKEN: Dict[str, str] = {
        'BTC-USD': 'XBTUSD',
        'ETH-USD': 'XETHZUSD',
    }
    
    # Coinbase USD product ID to Kraken pair
    COINBASE_USD_TO_KRAKEN: Dict[str, str] = {
        'BTC-USD': 'XBTUSD',
        'ETH-USD': 'XETHZUSD',
        'SOL-USD': 'SOLUSD',
        'LTC-USD': 'LTCUSD',
        'DOT-USD': 'DOTUSD',
        'ADA-USD': 'ADAUSD',
        'LINK-USD': 'LINKUSD',
        'UNI-USD': 'UNIUSD',
    }
    
    # Coinbase product ID to Chainlink feed name
    COINBASE_TO_CHAINLINK: Dict[str, str] = {
        'BTC-GBP': 'BTC/GBP',
        'ETH-GBP': 'ETH/GBP',
        'SOL-GBP': 'SOL/GBP',
        'BTC-USD': 'BTC/USD',
        'ETH-USD': 'ETH/USD',
        'LTC-USD': 'LTC/USD',
        'ADA-USD': 'ADA/USD',
        'LINK-USD': 'LINK/USD',
    }
    
    # Symbol to Coinbase base currency
    SYMBOL_TO_BASE: Dict[str, str] = {
        'BTC': 'BTC',
        'XBT': 'BTC',  # Kraken uses XBT
        'ETH': 'ETH',
        'SOL': 'SOL',
        'LTC': 'LTC',
        'ADA': 'ADA',
        'LINK': 'LINK',
    }
    
    # Base currency to CoinGecko ID (for batch lookups)
    BASE_TO_COINGECKO: Dict[str, str] = {
        'BTC': 'bitcoin',
        'ETH': 'ethereum',
        'SOL': 'solana',
        'LTC': 'litecoin',
        'ADA': 'cardano',
        'LINK': 'chainlink',
    }
    
    # Priority order for sources per product
    # Higher priority = more reliable/liquid for that pair
    SOURCE_PRIORITY: Dict[str, List[str]] = {
        'BTC-GBP': ['coinbase', 'binance', 'kraken', 'coingecko'],
        'ETH-GBP': ['coinbase', 'binance', 'kraken', 'coingecko'],
        'SOL-GBP': ['coinbase', 'binance', 'kraken', 'coingecko'],
        'LTC-GBP': ['coinbase', 'binance', 'kraken', 'coingecko'],
        'ADA-GBP': ['coinbase', 'binance', 'kraken', 'coingecko'],
        'LINK-GBP': ['coinbase', 'binance', 'kraken', 'coingecko'],
    }
    
    def __init__(self):
        """Initialize price mapper."""
        self._build_reverse_mappings()
        
    def _build_reverse_mappings(self):
        """Build reverse mappings for quick lookups."""
        # CoinGecko to Coinbase
        self.COINGECKO_TO_COINBASE = {v: k for k, v in self.COINBASE_TO_COINGECKO.items()}
        
        # Kraken to Coinbase
        self.KRAKEN_TO_COINBASE = {v: k for k, v in self.COINBASE_TO_KRAKEN.items()}
        self.KRAKEN_TO_COINBASE.update({v: k for k, v in self.COINBASE_USD_TO_KRAKEN.items()})
        
        # Chainlink to Coinbase
        self.CHAINLINK_TO_COINBASE = {v: k for k, v in self.COINBASE_TO_CHAINLINK.items()}
    
    def get_coingecko_id(self, product_id: str) -> Optional[str]:
        """
        Get CoinGecko coin ID from Coinbase product ID.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            CoinGecko coin ID or None
        """
        return self.COINBASE_TO_COINGECKO.get(product_id)
    
    def get_kraken_pair(self, product_id: str) -> Optional[str]:
        """
        Get Kraken pair name from Coinbase product ID.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            Kraken pair name or None
        """
        # Try GBP first
        if product_id in self.COINBASE_TO_KRAKEN:
            return self.COINBASE_TO_KRAKEN[product_id]
        
        # Try USD
        if product_id in self.COINBASE_USD_TO_KRAKEN:
            return self.COINBASE_USD_TO_KRAKEN[product_id]
        
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
    
    def get_chainlink_feed(self, product_id: str) -> Optional[str]:
        """
        Get Chainlink feed name from Coinbase product ID.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            Chainlink feed name or None
        """
        return self.COINBASE_TO_CHAINLINK.get(product_id)
    
    def get_base_currency(self, product_id: str) -> Optional[str]:
        """
        Extract base currency from product ID.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            Base currency (e.g., 'BTC') or None
        """
        if '-' in product_id:
            return product_id.split('-')[0]
        return None
    
    def get_quote_currency(self, product_id: str) -> Optional[str]:
        """
        Extract quote currency from product ID.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            Quote currency (e.g., 'GBP') or None
        """
        if '-' in product_id:
            parts = product_id.split('-')
            if len(parts) == 2:
                return parts[1]
        return None
    
    def get_usd_product(self, product_id: str) -> str:
        """
        Convert GBP product to USD equivalent for risk management.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            USD product ID: e.g., 'BTC-USD'
        """
        base = self.get_base_currency(product_id)
        if base:
            return f"{base}-USD"
        return product_id
    
    def get_source_priority(self, product_id: str) -> List[str]:
        """
        Get prioritized list of sources for a product.
        
        Args:
            product_id: e.g., 'BTC-GBP'
            
        Returns:
            List of source names in priority order
        """
        return self.SOURCE_PRIORITY.get(product_id, ['coinbase', 'coingecko', 'kraken'])
    
    def get_all_coingecko_ids(self, product_ids: List[str]) -> List[str]:
        """
        Get CoinGecko IDs for multiple products.
        
        Args:
            product_ids: List of Coinbase product IDs
            
        Returns:
            List of CoinGecko coin IDs
        """
        ids = []
        for pid in product_ids:
            cg_id = self.get_coingecko_id(pid)
            if cg_id:
                ids.append(cg_id)
        return ids
    
    def is_supported(self, product_id: str, source: str) -> bool:
        """
        Check if a product is supported by a specific source.
        
        Args:
            product_id: Coinbase product ID
            source: Source name ('coinbase', 'coingecko', 'kraken')
            
        Returns:
            True if supported
        """
        if source == 'coinbase':
            return True  # We always have Coinbase
        elif source == 'coingecko':
            return self.get_coingecko_id(product_id) is not None
        elif source == 'kraken':
            return self.get_kraken_pair(product_id) is not None
        return False
    
    def get_supported_products(self) -> List[str]:
        """Get list of all supported Coinbase product IDs."""
        return list(self.COINBASE_TO_COINGECKO.keys())
    
    def get_batch_coingecko_ids(self, base_currencies: List[str]) -> Dict[str, str]:
        """
        Get CoinGecko IDs for multiple base currencies.
        
        Args:
            base_currencies: List of base currencies (e.g., ['BTC', 'ETH'])
            
        Returns:
            Dict mapping base currency to CoinGecko ID
        """
        result = {}
        for base in base_currencies:
            if base in self.BASE_TO_COINGECKO:
                result[base] = self.BASE_TO_COINGECKO[base]
        return result


# Singleton instance
price_mapper: Optional[PriceMapper] = None


def get_price_mapper() -> PriceMapper:
    """Get or create price mapper singleton."""
    global price_mapper
    if price_mapper is None:
        price_mapper = PriceMapper()
    return price_mapper
