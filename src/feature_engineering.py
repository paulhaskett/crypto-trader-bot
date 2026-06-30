"""
Feature engineering for dynamic threshold and advanced features.
v1.9.0 - ATR-based thresholding with walk-forward validation support.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def calculate_atr(df: pd.DataFrame, period: int = 24) -> pd.Series:
    """
    Calculate Average True Range for dynamic threshold.
    
    Args:
        df: DataFrame with high, low, close columns
        period: ATR period (default 24 for hourly data = 1 day)
    
    Returns:
        ATR series (same index as input)
    """
    if 'high' not in df.columns or 'low' not in df.columns:
        logger.warning("Missing high/low columns for ATR calculation")
        return pd.Series(0, index=df.index)
    
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    
    # True Range components
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    # True Range = max of all three
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # ATR = rolling mean of True Range
    atr = tr.rolling(window=period, min_periods=1).mean()
    
    return atr


def calculate_atr_threshold(df: pd.DataFrame, 
                            multiplier: float = 1.0,
                            min_threshold: float = 0.002) -> pd.Series:
    """
    Calculate ATR-based threshold per row.
    
    Returns threshold as percentage of price.
    
    Args:
        df: DataFrame with close and atr columns
        multiplier: ATR multiplier (k)
        min_threshold: Minimum floor threshold (default 0.2%)
    
    Returns:
        Threshold series as percentage
    """
    if 'atr' not in df.columns:
        logger.warning("ATR not in DataFrame, using fallback")
        return pd.Series(min_threshold, index=df.index)
    
    atr_threshold = (df['atr'] * multiplier) / df['close']
    
    # Apply minimum floor
    threshold = atr_threshold.clip(lower=min_threshold)
    
    return threshold


def calculate_rolling_volatility(df: pd.DataFrame, 
                                  period: int = 20,
                                  column: str = 'close') -> pd.Series:
    """
    Calculate rolling standard deviation of returns for volatility measure.
    
    Args:
        df: DataFrame with price column
        period: Rolling window period
        column: Price column to use
    
    Returns:
        Rolling std dev of returns
    """
    returns = df[column].pct_change()
    rolling_std = returns.rolling(window=period, min_periods=1).std()
    return rolling_std


def get_label_distribution(targets: pd.Series, 
                          label_type: str = '3class',
                          product_id: str = 'unknown') -> Dict[str, int]:
    """
    Log and return class distribution.
    
    Args:
        targets: Target labels series
        label_type: 'binary' or '3class'
        product_id: Trading pair for logging
    
    Returns:
        Dictionary of class counts
    """
    counts = targets.value_counts().to_dict()
    
    if label_type == '3class':
        labels = {2: 'BUY', 1: 'HOLD', 0: 'SELL'}
    else:
        labels = {1: 'BUY', 0: 'NOT_BUY'}
    
    distribution_str = ", ".join([f"{labels.get(k, k)}: {v}" for k, v in sorted(counts.items())])
    logger.info(f"[{product_id}] Label distribution: {distribution_str}")
    
    return counts


def calculate_market_regime(df: pd.DataFrame, 
                            atr_period: int = 24,
                            lookback: int = 48) -> pd.Series:
    """
    Calculate market regime based on ATR-normalized price action.
    
    Returns regime classification:
    - 'high_vol': Current volatility > 2x average
    - 'normal_vol': Current volatility within normal range  
    - 'low_vol': Current volatility < 0.5x average
    
    Args:
        df: DataFrame with close and atr
        atr_period: Period for ATR calculation
        lookback: Lookback for average comparison
    
    Returns:
        Series with regime labels
    """
    atr = calculate_atr(df, period=atr_period)
    atr_pct = atr / df['close']
    
    # Calculate average ATR over lookback
    avg_atr = atr_pct.rolling(window=lookback, min_periods=1).mean()
    
    # Compare current to average
    regime = pd.Series('normal_vol', index=df.index)
    regime[atr_pct > avg_atr * 2] = 'high_vol'
    regime[atr_pct < avg_atr * 0.5] = 'low_vol'
    
    return regime


def calculate_volatility_normalized_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add volatility-normalized versions of price-based features.
    
    These features are divided by ATR to make them regime-invariant.
    
    Args:
        df: DataFrame with price and ATR
    
    Returns:
        DataFrame with additional normalized features
    """
    result = df.copy()
    
    if 'atr' not in df.columns:
        logger.warning("Cannot calculate volatility features without ATR")
        return result
    
    atr = df['atr'].replace(0, np.nan)
    
    # Price range normalized by ATR
    if 'high' in df.columns and 'low' in df.columns:
        result['price_range_atr'] = (df['high'] - df['low']) / atr
    
    # Volume normalized by ATR (if available)
    if 'volume' in df.columns:
        result['volume_per_atr'] = df['volume'] / atr
    
    # Returns normalized by ATR
    if 'returns' in df.columns:
        result['returns_per_atr'] = df['returns'] / atr
    
    return result


# =============================================================================
# v1.9.1: Pair and Currency Features
# =============================================================================

PAIR_IDENTIFIERS = ['BTC', 'ETH', 'SOL', 'LTC', 'ADA', 'LINK', 'DOT', 'UNI']  # 8 features for model compatibility (DOT, UNI not in active trading pairs)


def add_pair_features(df: pd.DataFrame, product_id: str) -> pd.DataFrame:
    """
    Add one-hot encoded pair identity and currency indicator features.
    
    This helps the model learn pair-specific patterns and distinguish
    between GBP and USD pairs.
    
    Args:
        df: DataFrame with features
        product_id: Trading pair (e.g., 'BTC-GBP', 'ETH-USD')
    
    Returns:
        DataFrame with additional pair features
    """
    result = df.copy()
    
    # Extract base currency and quote currency
    parts = product_id.split('-')
    base_currency = parts[0] if len(parts) > 0 else 'UNKNOWN'
    quote_currency = parts[1] if len(parts) > 1 else 'UNKNOWN'
    
    # One-hot encode base currency (e.g., BTC, ETH, SOL)
    for currency in PAIR_IDENTIFIERS:
        result[f'is_{currency}'] = 1 if base_currency == currency else 0
    
    # Currency indicator (GBP vs USD)
    result['is_gbp'] = 1 if quote_currency == 'GBP' else 0
    result['is_usd'] = 1 if quote_currency == 'USD' else 0
    
    return result


def add_log_returns(df: pd.DataFrame, close_column: str = 'close') -> pd.DataFrame:
    """
    Add log returns as alternative to simple percentage returns.
    
    Log returns are preferred for financial time series because:
    - Additive across time periods
    - More normally distributed
    - Better for volatility calculations
    
    Args:
        df: DataFrame with close prices
        close_column: Name of close price column
    
    Returns:
        DataFrame with log_returns column added
    """
    result = df.copy()
    
    if close_column in df.columns:
        result['log_returns'] = np.log(df[close_column] / df[close_column].shift(1))
    
    return result


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add time-based features for linear models (Ridge) to differentiate from tree-based models.
    
    Uses sin/cos encoding to capture cyclical nature of time.
    Tree-based models (RF, GB) don't benefit much from these features,
    but linear models (Ridge, LR) can learn time-based patterns.
    
    Args:
        df: DataFrame with datetime index or timestamp column
        
    Returns:
        DataFrame with temporal features added
    """
    result = df.copy()
    
    # Determine if we have datetime index or column
    if hasattr(result.index, 'hour'):
        hours = result.index.hour
        dayofweek = result.index.dayofweek
    elif 'timestamp' in result.columns:
        timestamp = pd.to_datetime(result['timestamp'])
        hours = timestamp.dt.hour
        dayofweek = timestamp.dt.dayofweek
    else:
        # Fallback: use sequential hours
        hours = np.arange(len(result)) % 24
        dayofweek = (np.arange(len(result)) // 24) % 7
    
    # Hour of day (sin/cos encoding for cyclical nature)
    result['hour_sin'] = np.sin(2 * np.pi * hours / 24)
    result['hour_cos'] = np.cos(2 * np.pi * hours / 24)
    
    # Day of week (sin/cos encoding)
    result['dow_sin'] = np.sin(2 * np.pi * dayofweek / 7)
    result['dow_cos'] = np.cos(2 * np.pi * dayofweek / 7)
    
    return result


def add_volume_price_divergence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect when price and volume trends disagree.
    
    This feature helps linear models identify potential reversals
    that tree-based models might miss.
    
    Args:
        df: DataFrame with volume and close columns
        
    Returns:
        DataFrame with volume_price_div column added
    """
    result = df.copy()
    
    if 'volume' not in df.columns or 'close' not in df.columns:
        return result
    
    # Price direction (1=up, -1=down)
    price_dir = df['close'].diff().apply(lambda x: 1 if x > 0 else -1)
    
    # Volume direction (compared to 20-period moving average)
    volume_ma = df['volume'].rolling(20).mean()
    volume_dir = (df['volume'] > volume_ma).apply(lambda x: 1 if x else -1)
    
    # Divergence: price and volume disagree
    result['volume_price_div'] = price_dir * volume_dir
    result['volume_price_div'] = result['volume_price_div'].fillna(0)
    
    return result