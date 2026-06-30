"""
Regime Detection Module - Market regime and volatility classification.

This module provides functions to detect:
- Trend regime (uptrend, downtrend, neutral)
- Volatility regime (low, normal, high)
- Multi-level trend classification

The regime information is used to:
- Adjust model confidence scores
- Filter trading signals
- Adjust stop loss and take profit levels
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from config.settings import settings
from src.data_collector import data_collector
from .base import logger, REGIME_CACHE_TTL


class RegimeDetector:
    """
    Detects market regimes for trading pairs.
    
    Uses moving average crossovers and RSI to classify:
    - Trend: uptrend, downtrend, neutral
    - Volatility: low, normal, high
    """
    
    def __init__(self):
        self._regime_cache: Dict[str, tuple] = {}
        self._volatility_cache: Dict[str, tuple] = {}
    
    def detect(self, product_id: str, use_cache: bool = True) -> Dict[str, str]:
        """
        Detect both trend and volatility regimes.
        
        Args:
            product_id: Trading pair (e.g., 'BTC-GBP')
            use_cache: Whether to use cached results
            
        Returns:
            Dict with 'regime' and 'volatility_regime' keys
        """
        trend = self.detect_regime(product_id, use_cache)
        volatility = self.detect_volatility_regime(product_id, use_cache)
        
        return {
            'regime': trend,
            'volatility_regime': volatility
        }
    
    def detect_regime(self, product_id: str, use_cache: bool = True) -> str:
        """
        Detect trend regime using moving average crossover.
        
        Returns:
            'uptrend', 'downtrend', or 'neutral'
        """
        if use_cache and product_id in self._regime_cache:
            cached_time, cached_value = self._regime_cache[product_id]
            age = (datetime.now() - cached_time).total_seconds()
            if age < REGIME_CACHE_TTL:
                return cached_value
        
        try:
            df = data_collector.collect_historical_data(product_id, days=7)
            if df.empty or len(df) < 24:
                logger.warning(f"Insufficient data for regime detection: {product_id}")
                self._regime_cache[product_id] = (datetime.now(), 'neutral')
                return 'neutral'
            
            short_period = settings.REGIME_SHORT_MA_PERIOD  # 20
            long_period = settings.REGIME_LONG_MA_PERIOD  # 50
            
            short_ma = df['close'].rolling(short_period).mean().iloc[-1]
            long_ma = df['close'].rolling(long_period).mean().iloc[-1]
            
            if pd.isna(short_ma) or pd.isna(long_ma):
                self._regime_cache[product_id] = (datetime.now(), 'neutral')
                return 'neutral'
            
            current_price = df['close'].iloc[-1]
            
            rsi = self._calculate_rsi(df)
            rsi_value = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
            
            if current_price > short_ma and current_price > long_ma:
                regime = 'uptrend'
                logger.info(f"Regime: {product_id} = uptrend (price £{current_price:.2f} > MA{short_period}/MA{long_period}, RSI: {rsi_value:.1f})")
            elif current_price < short_ma and current_price < long_ma:
                regime = 'downtrend'
                logger.info(f"Regime: {product_id} = downtrend (price £{current_price:.2f} < MA{short_period}/MA{long_period}, RSI: {rsi_value:.1f})")
            else:
                regime = 'neutral'
                logger.info(f"Regime: {product_id} = neutral (price £{current_price:.2f} between MA{short_period}/MA{long_period}, RSI: {rsi_value:.1f})")
            
            self._regime_cache[product_id] = (datetime.now(), regime)
            return regime
            
        except Exception as e:
            logger.error(f"Error detecting regime for {product_id}: {e}")
            return 'neutral'
    
    def detect_volatility_regime(self, product_id: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Detect volatility regime using ATR ratio.
        
        Returns:
            Dict with 'regime', 'vol_ratio', 'atr_short', 'atr_long', 'effective_multiplier'
        """
        if use_cache and product_id in self._volatility_cache:
            cached_time, cached_value = self._volatility_cache[product_id]
            age = (datetime.now() - cached_time).total_seconds()
            if age < REGIME_CACHE_TTL:
                return cached_value
        
        try:
            # Use 24h (1 day) and 168h (7 days) ATR for regime detection
            df = data_collector.collect_historical_data(product_id, days=14)
            if df.empty or len(df) < 48:
                return {
                    'regime': 'normal',
                    'vol_ratio': 1.0,
                    'atr_short': 0,
                    'atr_long': 0,
                    'effective_multiplier': settings.ATR_MULTIPLIER
                }
            
            atr_short = self._calculate_atr(df, 24)
            atr_long = self._calculate_atr(df, 168)
            
            if atr_long > 0:
                vol_ratio = atr_short / atr_long
            else:
                vol_ratio = 1.0
            
            if vol_ratio > 1.5:
                regime = 'high'
                effective_mult = settings.ATR_MULTIPLIER * 1.5  # More sensitive
            elif vol_ratio < 0.7:
                regime = 'low'
                effective_mult = settings.ATR_MULTIPLIER * 0.8  # Less sensitive
            else:
                regime = 'normal'
                effective_mult = settings.ATR_MULTIPLIER
            
            result = {
                'regime': regime,
                'vol_ratio': float(vol_ratio),
                'atr_short': float(atr_short),
                'atr_long': float(atr_long),
                'effective_multiplier': float(effective_mult)
            }
            
            self._volatility_cache[product_id] = (datetime.now(), result)
            return result
            
        except Exception as e:
            logger.error(f"Error detecting volatility regime for {product_id}: {e}")
            return {
                'regime': 'normal',
                'vol_ratio': 1.0,
                'effective_multiplier': settings.ATR_MULTIPLIER
            }
    
    def detect_trend_levels(self, product_id: str) -> Dict[str, str]:
        """
        Detect multi-level trend classification.
        
        Returns:
            Dict with 'short_term', 'medium_term', 'combined', 'rsi'
        """
        try:
            df = data_collector.collect_historical_data(product_id, days=14)
            if df is None or len(df) < 50:
                return {'short_term': 'sideways', 'medium_term': 'sideways', 'combined': 'sideways', 'rsi': 50}
            
            df = df.tail(200).reset_index(drop=True) if len(df) > 200 else df
            
            rsi = self._calculate_rsi(df)
            rsi_current = rsi.iloc[-1] if len(rsi) > 0 else 50
            
            short_trend = self._classify_single_timeframe(df, 'short')
            medium_trend = self._classify_single_timeframe(df, 'medium')
            combined = self._combine_trends(short_trend, medium_trend, rsi_current)
            
            return {
                'short_term': short_trend,
                'medium_term': medium_trend,
                'combined': combined,
                'rsi': float(rsi_current)
            }
            
        except Exception as e:
            logger.error(f"Error detecting trend levels: {e}")
            return {'short_term': 'sideways', 'medium_term': 'sideways', 'combined': 'sideways', 'rsi': 50}
    
    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate RSI."""
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        
        rs = avg_gain / avg_loss.replace(0, 0.0001)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 24) -> float:
        """Calculate ATR."""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        
        return atr if not pd.isna(atr) else 0.0
    
    def _classify_single_timeframe(self, df: pd.DataFrame, timeframe: str = 'short') -> str:
        """Classify trend for a single timeframe."""
        if timeframe == 'medium':
            ma_short = settings.REGIME_SHORT_MA_PERIOD
            ma_medium = settings.REGIME_MEDIUM_MA_PERIOD
            ma_long = settings.REGIME_STRONG_MA_PERIOD
            min_periods = settings.REGIME_MIN_SWINGS
        else:
            ma_short = 8
            ma_medium = settings.REGIME_SHORT_MA_PERIOD
            ma_long = settings.REGIME_LONG_MA_PERIOD
            min_periods = 3
        
        if len(df) < ma_long + settings.REGIME_HIGHER_HIGHS_PERIOD:
            return 'sideways'
        
        closes = df['close']
        
        ma_s = closes.rolling(ma_short).mean().iloc[-1]
        ma_m = closes.rolling(ma_medium).mean().iloc[-1]
        ma_l = closes.rolling(ma_long).mean().iloc[-1]
        
        if pd.isna(ma_s) or pd.isna(ma_m) or pd.isna(ma_l):
            return 'sideways'
        
        rsi = self._calculate_rsi(df).iloc[-1]
        
        recent_closes = closes.tail(settings.REGIME_HIGHER_HIGHS_PERIOD).tolist()
        higher_highs = sum(1 for i in range(1, len(recent_closes)) if recent_closes[i] > recent_closes[i-1])
        lower_lows = sum(1 for i in range(1, len(recent_closes)) if recent_closes[i] < recent_closes[i-1])
        
        current_price = closes.iloc[-1]
        
        price_vs_long = (current_price - ma_l) / ma_l
        price_vs_medium = (current_price - ma_m) / ma_m
        
        if price_vs_long > 0 and higher_highs >= min_periods:
            if rsi > settings.REGIME_STRONG_RSI_UPPER:
                return 'strong_uptrend'
            elif rsi > settings.REGIME_WEAK_RSI_UPPER:
                return 'weak_uptrend'
        
        if price_vs_medium > 0:
            if rsi > settings.REGIME_STRONG_RSI_UPPER:
                return 'weak_uptrend'
            elif rsi > 55:
                return 'weak_uptrend'
        
        if price_vs_long < 0 and lower_lows >= min_periods:
            if rsi < settings.REGIME_STRONG_RSI_LOWER:
                return 'strong_downtrend'
            elif rsi < settings.REGIME_WEAK_RSI_LOWER:
                return 'weak_downtrend'
        
        if price_vs_medium < 0:
            if rsi < settings.REGIME_STRONG_RSI_LOWER:
                return 'weak_downtrend'
            elif rsi < 45:
                return 'weak_downtrend'
        
        if abs(price_vs_long) < settings.REGIME_SIDEWAYS_MAX_SPREAD:
            return 'sideways'
        
        return 'sideways'
    
    def _combine_trends(self, short_trend: str, medium_trend: str, rsi: float) -> str:
        """Combine short and medium trends."""
        trend_hierarchy = {
            'strong_uptrend': 4,
            'weak_uptrend': 3,
            'sideways': 2,
            'weak_downtrend': 1,
            'strong_downtrend': 0
        }
        
        short_score = trend_hierarchy.get(short_trend, 2)
        medium_score = trend_hierarchy.get(medium_trend, 2)
        
        combined_score = (short_score + medium_score * 2) / 3
        
        for trend, score in trend_hierarchy.items():
            if abs(score - combined_score) < 0.5:
                return trend
        
        return 'sideways'
    
    def clear_cache(self):
        """Clear all cached regime data."""
        self._regime_cache.clear()
        self._volatility_cache.clear()


# Global singleton
regime_detector = RegimeDetector()


def detect_regime(product_id: str) -> str:
    """Convenience function for regime detection."""
    return regime_detector.detect_regime(product_id)


def detect_volatility_regime(product_id: str) -> Dict[str, Any]:
    """Convenience function for volatility regime detection."""
    return regime_detector.detect_volatility_regime(product_id)


__all__ = [
    'RegimeDetector',
    'regime_detector',
    'detect_regime',
    'detect_volatility_regime'
]