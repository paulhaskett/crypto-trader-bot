"""
Trading Pairs Configuration Loader.

This module loads and provides access to the trading_pairs.yaml configuration.
All trading pairs and their settings are defined in config/trading_pairs.yaml.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

# Singleton config instance
_config: Optional[Dict[str, Any]] = None


def load_trading_pairs_config() -> Dict[str, Any]:
    """
    Load trading pairs configuration from YAML file.
    
    Returns:
        Dict containing trading_pairs and position_sizing config
    """
    global _config
    
    if _config is not None:
        return _config
    
    config_path = Path(__file__).parent / 'trading_pairs.yaml'
    
    try:
        with open(config_path, 'r') as f:
            _config = yaml.safe_load(f)
        logger.info(f"Loaded trading pairs config: {len(_config.get('trading_pairs', {}))} pairs")
        return _config
    except FileNotFoundError:
        logger.error(f"Trading pairs config not found: {config_path}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"Error parsing trading pairs config: {e}")
        return {}


def get_active_pairs() -> List[str]:
    """
    Get list of active trading pairs (Coinbase format).
    
    Returns:
        List of product IDs e.g., ['BTC-GBP', 'ETH-GBP']
    """
    config = load_trading_pairs_config()
    trading_pairs = config.get('trading_pairs', {})
    
    pairs = []
    for pair_id, pair_config in trading_pairs.items():
        # Return Coinbase ID format
        coinbase_id = pair_config.get('coinbase_id', pair_id)
        pairs.append(coinbase_id)
    
    return pairs


def get_active_base_currencies() -> List[str]:
    """
    Get list of base currencies for active pairs.
    
    Returns:
        List of base currencies e.g., ['BTC', 'ETH']
    """
    config = load_trading_pairs_config()
    trading_pairs = config.get('trading_pairs', {})
    
    currencies = []
    for pair_id, pair_config in trading_pairs.items():
        base = pair_config.get('base_currency')
        if base:
            currencies.append(base)
    
    return currencies


def get_pair_config(product_id: str) -> Optional[Dict[str, Any]]:
    """
    Get configuration for a specific trading pair.
    
    Args:
        product_id: e.g., 'BTC-GBP'
        
    Returns:
        Dict with pair configuration or None
    """
    config = load_trading_pairs_config()
    return config.get('trading_pairs', {}).get(product_id)


def get_pair_symbol(product_id: str, exchange: str) -> Optional[str]:
    """
    Get symbol for a pair on a specific exchange.
    
    Args:
        product_id: e.g., 'BTC-GBP'
        exchange: e.g., 'binance', 'kraken', 'coingecko'
        
    Returns:
        Symbol for the exchange or None
    """
    pair_config = get_pair_config(product_id)
    if not pair_config:
        return None
    
    # Map exchange names to config keys
    exchange_key_map = {
        'binance': 'binance_symbol',
        'kraken': 'kraken_symbol',
        'coinbase': 'coinbase_id',
        'coingecko': 'coingecko_id',
    }
    
    key = exchange_key_map.get(exchange, exchange)
    return pair_config.get(key)


def get_position_sizing_config() -> Dict[str, float]:
    """
    Get position sizing configuration.
    
    Returns:
        Dict with max_per_pair_percent, max_total_deployed, min_cash_reserve
    """
    config = load_trading_pairs_config()
    return config.get('position_sizing', {
        'max_per_pair_percent': 0.45,
        'max_total_deployed': 0.90,
        'min_cash_reserve': 0.10
    })


def get_max_position_percent() -> float:
    """
    Get maximum position size percentage per pair.
    Automatically calculated based on number of active pairs.
    
    Returns:
        Percentage as float (e.g., 0.45 for 45%)
    """
    sizing = get_position_sizing_config()
    return sizing.get('max_per_pair_percent', 0.45)


def get_data_source_config() -> Dict[str, Any]:
    """
    Get data source configuration.
    
    Returns:
        Dict with source enabled status and weights
    """
    config = load_trading_pairs_config()
    return config.get('data_sources', {})


def get_source_weights() -> Dict[str, float]:
    """
    Get data source weights for price aggregation.
    
    Returns:
        Dict mapping source name to weight
    """
    data_sources = get_data_source_config()
    default_weights = {
        'coinbase': 0.40,
        'binance': 0.30,
        'kraken': 0.20,
        'coingecko': 0.10,
    }
    
    if not data_sources:
        return default_weights
    
    weights = {}
    for source, default in default_weights.items():
        if source in data_sources:
            weights[source] = data_sources[source].get('weight', default)
        else:
            weights[source] = default
    
    return weights


def reload_config():
    """Reload configuration from file (for testing)."""
    global _config
    _config = None
    return load_trading_pairs_config()


# Initialize on module load
load_trading_pairs_config()