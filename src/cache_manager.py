"""
Centralized cache and file management utilities.

This module provides a single source of truth for:
- Signal cache read/write operations
- Path constants (BASE_DIR, DATA_DIR, etc.)
- Timestamp utilities
- API response helpers

All modules should import from here instead of defining paths inline.

Usage:
    from src.cache_manager import read_signal_cache, write_signal_cache, SIGNAL_CACHE_FILE
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# CENTRAL PATH CONSTANTS
# ============================================================================

BASE_DIR = Path(__file__).parent.parent.absolute()
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
MODEL_DIR = BASE_DIR / 'models'

SIGNAL_CACHE_FILE = DATA_DIR / 'signal_cache.json'
LAST_CYCLE_FILE = DATA_DIR / 'last_cycle.txt'
LAST_RETRAIN_FILE = DATA_DIR / 'last_retrain.txt'

# Date format constants
TIME_FORMAT = "%H:%M:%S"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

# Ensure directories exist on import
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# CACHE FUNCTIONS
# ============================================================================

def read_signal_cache() -> Dict[str, Any]:
    """
    Read signal cache from file.

    Returns:
        Dictionary of product_id -> signal_data mappings.
        Returns empty dict if file doesn't exist or read fails.
    """
    try:
        if SIGNAL_CACHE_FILE.exists():
            with open(SIGNAL_CACHE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read signal cache: {e}")
    return {}


def write_signal_cache(signals: Dict[str, Any]):
    """
    Write signal cache to file with proper formatting.

    Formats each signal with all required fields for dashboard display:
    - action, confidence, regime, reason, timestamp
    - Individual model predictions (rf, lr, mlp, gb)
    - Agreement metrics

    Args:
        signals: Dictionary of product_id -> signal_data mappings.
    """
    cache_data = {}
    for product_id, signal in signals.items():
        cache_data[product_id] = {
            'action': signal.get('action', 'HOLD'),
            'confidence': signal.get('confidence', 0),
            'regime': signal.get('regime', 'neutral'),
            'reason': signal.get('reason', ''),
            'timestamp': get_timestamp(),
            'rf_prediction': signal.get('rf_prediction'),
            'lr_prediction': signal.get('lr_prediction'),
            'mlp_prediction': signal.get('mlp_prediction'),
            'gb_prediction': signal.get('gb_prediction'),
            'rf_confidence': signal.get('rf_confidence', 0),
            'lr_confidence': signal.get('lr_confidence', 0),
            'mlp_confidence': signal.get('mlp_confidence', 0),
            'gb_confidence': signal.get('gb_confidence', 0),
            'ridge_prediction': signal.get('ridge_prediction'),
            'ridge_confidence': signal.get('ridge_confidence', 0),
            'agreement': signal.get('agreement', 0),
            'unanimous': signal.get('unanimous', False)
        }

    try:
        with open(SIGNAL_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, default=str)
        logger.info(f"Wrote signal cache: {len(cache_data)} products")
    except Exception as e:
        logger.error(f"Error writing signal cache: {e}")


def read_last_cycle_time() -> float:
    """
    Read last trading cycle timestamp from file.

    Returns:
        Unix timestamp of last cycle, or current time if file doesn't exist.
    """
    try:
        if LAST_CYCLE_FILE.exists():
            with open(LAST_CYCLE_FILE, 'r') as f:
                return float(f.read().strip())
    except Exception:
        pass
    return time.time()


def write_last_cycle_time(timestamp: float):
    """
    Write last trading cycle timestamp to file.

    Args:
        timestamp: Unix timestamp to write.
    """
    try:
        with open(LAST_CYCLE_FILE, 'w') as f:
            f.write(str(timestamp))
    except Exception as e:
        logger.error(f"Error writing last cycle time: {e}")


def read_last_retrain_time() -> Optional[str]:
    """
    Read last model retrain timestamp from file.

    Returns:
        ISO timestamp string, or None if file doesn't exist.
    """
    try:
        if LAST_RETRAIN_FILE.exists():
            with open(LAST_RETRAIN_FILE, 'r') as f:
                return f.read().strip()
    except Exception:
        pass
    return None


def write_last_retrain_time(timestamp: str):
    """
    Write last model retrain timestamp to file.

    Args:
        timestamp: ISO timestamp string to write.
    """
    try:
        with open(LAST_RETRAIN_FILE, 'w') as f:
            f.write(timestamp)
    except Exception as e:
        logger.error(f"Error writing last retrain time: {e}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_timestamp() -> str:
    """
    Get current ISO timestamp string.

    Returns:
        ISO format timestamp string (e.g., '2026-04-23T16:30:00.123456').
    """
    return datetime.now().isoformat()


def format_time(timestamp: float) -> str:
    """
    Format Unix timestamp to time string.

    Args:
        timestamp: Unix timestamp (seconds since epoch).

    Returns:
        Formatted time string (e.g., '16:30:00').
    """
    return datetime.utcfromtimestamp(timestamp).strftime(TIME_FORMAT)


def format_datetime(timestamp: float) -> str:
    """
    Format Unix timestamp to datetime string.

    Args:
        timestamp: Unix timestamp (seconds since epoch).

    Returns:
        Formatted datetime string (e.g., '2026-04-23 16:30:00').
    """
    return datetime.utcfromtimestamp(timestamp).strftime(DATETIME_FORMAT)


def api_response(data: Dict[str, Any], include_timestamp: bool = True) -> Dict[str, Any]:
    """
    Create standardized API response with optional timestamp.

    Args:
        data: Response data dictionary.
        include_timestamp: Whether to add timestamp field. Default True.

    Returns:
        Response dictionary with optional timestamp.
    """
    response = data.copy()
    if include_timestamp:
        response['timestamp'] = get_timestamp()
    return response