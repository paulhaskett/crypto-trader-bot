"""
Feature Engineering Module - Feature preparation for ML models.

This module provides functions to:
- Prepare feature matrices from technical indicators
- Add regime features
- Add temporal features
- Handle missing values and outliers
"""

import numpy as np
import pandas as pd
from typing import List, Optional

from config.settings import settings
from .base import logger


class FeatureEngineer:
    """
    Feature engineering for trading signal prediction.
    
    Creates regime-invariant features that work across different price levels
    and currencies (USD vs GBP).
    """
    
    def __init__(self):
        self.feature_columns = self._get_feature_columns()
    
    def _get_feature_columns(self) -> List[str]:
        """Get the standard feature column list."""
        return [
            # Ratio features (price-relative, regime-invariant)
            'sma_20_ratio', 'sma_50_ratio',
            'ema_12_ratio', 'ema_26_ratio',
            # Price deviation from MAs
            'price_deviation_sma20', 'price_deviation_sma50',
            # Position indicators (0-1 scale)
            'bb_position', 'macd_normalized',
            # Regime indicators
            'rsi_regime', 'volume_ratio', 'volatility_percentile',
            # Keep existing regime-invariant features
            'rsi', 'returns', 'volatility',
            'macd', 'macd_signal', 'macd_histogram',
            # Regime one-hot encoded features
            'regime_is_uptrend', 'regime_is_downtrend', 'regime_is_neutral'
        ]
    
    def prepare(self, df: pd.DataFrame, product_id: Optional[str] = None) -> pd.DataFrame:
        """
        Prepare feature matrix from technical indicators.
        
        Args:
            df: DataFrame with technical indicators
            product_id: Trading pair (e.g., 'BTC-GBP') - needed for pair features
            
        Returns:
            DataFrame with selected features for model training
        """
        try:
            df = self._add_regime_features(df)
            
            # Get available features
            available_features = [col for col in self.feature_columns if col in df.columns]
            
            # Add log returns if enabled
            if settings.USE_LOG_RETURNS and 'log_returns' in df.columns:
                available_features.append('log_returns')
            
            # Add ATR normalization features
            if settings.USE_ATR_NORMALIZATION:
                for col in ['returns_per_atr', 'volatility_per_atr', 'atr']:
                    if col in df.columns:
                        available_features.append(col)
            
            # Add pair features if enabled
            if settings.ADD_PAIR_FEATURES and product_id:
                from src.feature_engineering import add_pair_features
                df = add_pair_features(df, product_id)
                
                from src.feature_engineering import PAIR_IDENTIFIERS
                for currency in PAIR_IDENTIFIERS:
                    if f'is_{currency}' in df.columns:
                        available_features.append(f'is_{currency}')
                
                if settings.ADD_CURRENCY_INDICATOR:
                    for col in ['is_gbp', 'is_usd']:
                        if col in df.columns:
                            available_features.append(col)
            
            # Add temporal features
            from src.feature_engineering import add_temporal_features
            df = add_temporal_features(df)
            for col in ['hour_sin', 'hour_cos', 'dow_sin', 'dow_cos']:
                if col in df.columns:
                    available_features.append(col)
            
            # Add volume-price divergence
            from src.feature_engineering import add_volume_price_divergence
            df = add_volume_price_divergence(df)
            if 'volume_price_div' in df.columns:
                available_features.append('volume_price_div')
            
            available_features = [col for col in available_features if col in df.columns]
            
            if not available_features:
                logger.warning("No technical indicators available for features")
                return pd.DataFrame()
            
            features_df = df[available_features].copy()
            features_df = features_df.ffill().fillna(0)
            features_df = features_df.replace([np.inf, -np.inf], 0)
            
            logger.info(f"Prepared {len(available_features)} features: {available_features[:5]}...")
            return features_df
            
        except Exception as e:
            logger.error(f"Error preparing features: {e}")
            return pd.DataFrame()
    
    def _add_regime_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add regime as one-hot encoded features."""
        try:
            df = df.copy()
            
            short_period = settings.REGIME_SHORT_MA_PERIOD
            long_period = settings.REGIME_LONG_MA_PERIOD
            
            sma_short = df['close'].rolling(short_period).mean()
            sma_long = df['close'].rolling(long_period).mean()
            
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=14, min_periods=14).mean()
            avg_loss = loss.rolling(window=14, min_periods=14).mean()
            rs = avg_gain / avg_loss.replace(0, 0.0001)
            rsi = 100 - (100 / (1 + rs))
            
            threshold = settings.REGIME_THRESHOLD
            
            df['regime_is_uptrend'] = 0.0
            df['regime_is_downtrend'] = 0.0
            df['regime_is_neutral'] = 1.0
            
            for i in range(long_period + 14, len(df)):
                short_ma = sma_short.iloc[i]
                long_ma = sma_long.iloc[i]
                rsi_val = rsi.iloc[i]
                
                if pd.isna(short_ma) or pd.isna(long_ma) or pd.isna(rsi_val):
                    df.iloc[i, df.columns.get_loc('regime_is_neutral')] = 1.0
                    continue
                
                ma_uptrend = short_ma > long_ma * (1 + threshold)
                ma_downtrend = short_ma < long_ma * (1 - threshold)
                
                rsi_strong_up = rsi_val > settings.REGIME_STRONG_RSI_UPPER
                rsi_strong_down = rsi_val < settings.REGIME_STRONG_RSI_LOWER
                
                if ma_uptrend or rsi_strong_up:
                    df.iloc[i, df.columns.get_loc('regime_is_uptrend')] = 1.0
                elif ma_downtrend or rsi_strong_down:
                    df.iloc[i, df.columns.get_loc('regime_is_downtrend')] = 1.0
                else:
                    df.iloc[i, df.columns.get_loc('regime_is_neutral')] = 1.0
            
            df['regime_is_uptrend'] = df['regime_is_uptrend'].bfill().fillna(0.0)
            df['regime_is_downtrend'] = df['regime_is_downtrend'].bfill().fillna(0.0)
            df['regime_is_neutral'] = df['regime_is_neutral'].bfill().fillna(1.0)
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding regime features: {e}")
            df = df.copy()
            df['regime_is_uptrend'] = 0.0
            df['regime_is_downtrend'] = 0.0
            df['regime_is_neutral'] = 1.0
            return df
    
    def get_feature_names(self) -> List[str]:
        """Get list of feature column names."""
        return self.feature_columns.copy()


# Global singleton
feature_engineer = FeatureEngineer()


def prepare_features(df: pd.DataFrame, product_id: Optional[str] = None) -> pd.DataFrame:
    """Convenience function for feature preparation."""
    return feature_engineer.prepare(df, product_id)


__all__ = [
    'FeatureEngineer',
    'feature_engineer',
    'prepare_features'
]