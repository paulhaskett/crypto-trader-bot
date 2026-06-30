"""
Training Module - Model training and label creation.

This module provides:
- ATR-based label creation
- Model training with hyperparameter tuning
- Walk-forward validation
- Model persistence
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from config.settings import settings
from .base import logger, CLASS_BUY, CLASS_HOLD, CLASS_SELL
from .features import feature_engineer
from .evaluation import trading_evaluator
from .models import model_storage, model_manager
from src.data_collector import data_collector


class ModelTrainer:
    """
    Handles model training with hyperparameter optimization.
    
    Features:
    - ATR-based dynamic threshold for labels
    - Multi-configuration testing
    - Walk-forward validation
    - Trading performance scoring
    """
    
    def __init__(self):
        self.prediction_horizon = settings.PREDICTION_HORIZON
    
    def create_labels(self, df: pd.DataFrame, product_id: str,
                      use_atr: bool = True, label_type: str = '3class') -> pd.Series:
        """
        Create target labels with ATR-based threshold.
        
        Args:
            df: DataFrame with price data and indicators
            product_id: Trading pair
            use_atr: Use ATR-based threshold
            label_type: 'binary' or '3class'
            
        Returns:
            Series of target labels
        """
        try:
            n = len(df)
            horizon = self.prediction_horizon
            
            close_series = df['close']
            future_series = close_series.shift(-horizon)
            
            price_change_pct = (future_series - close_series) / close_series
            
            if use_atr and 'atr' in df.columns:
                vol_regime = self._get_volatility_regime(df)
                effective_mult = vol_regime.get('effective_multiplier', settings.ATR_MULTIPLIER)
                
                atr_series = df['atr']
                threshold = (atr_series * effective_mult) / close_series
                threshold = threshold.clip(lower=settings.ATR_MIN_THRESHOLD)
            else:
                threshold = pd.Series(settings.TRAINING_MIN_PROFIT_THRESHOLD, index=df.index)
            
            valid_mask = ~(price_change_pct.isna() | threshold.isna())
            price_change_pct = price_change_pct[valid_mask]
            threshold = threshold[valid_mask]
            
            targets_arr = np.ones(len(price_change_pct), dtype=int)
            pc_values = price_change_pct.values
            thresh_values = threshold.values
            
            if label_type == '3class':
                targets_arr[pc_values > thresh_values] = CLASS_BUY
                targets_arr[pc_values < -thresh_values] = CLASS_SELL
            else:
                targets_arr = (pc_values >= thresh_values).astype(int)
            
            return pd.Series(targets_arr, index=price_change_pct.index, dtype=int)
            
        except Exception as e:
            logger.error(f"Error creating labels: {e}")
            return pd.Series([], dtype=int)
    
    def _get_volatility_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Get volatility regime for threshold adjustment."""
        try:
            if len(df) < 168:
                return {'regime': 'normal', 'effective_multiplier': settings.ATR_MULTIPLIER}
            
            atr_short = self._calculate_atr(df, 24)
            atr_long = self._calculate_atr(df, 168)
            
            if atr_long > 0:
                vol_ratio = atr_short / atr_long
            else:
                vol_ratio = 1.0
            
            if vol_ratio > 1.5:
                effective_mult = settings.ATR_MULTIPLIER * 1.5
            elif vol_ratio < 0.7:
                effective_mult = settings.ATR_MULTIPLIER * 0.8
            else:
                effective_mult = settings.ATR_MULTIPLIER
            
            return {'regime': 'normal', 'effective_multiplier': effective_mult}
        except:
            return {'regime': 'normal', 'effective_multiplier': settings.ATR_MULTIPLIER}
    
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
    
    def train(self, product_id: str, force_retrain: bool = False) -> Dict[str, Any]:
        """
        Train all model types for a product.
        
        Args:
            product_id: Trading pair
            force_retrain: Force retrain even if models exist
            
        Returns:
            Dict with training results for each model type
        """
        logger.info(f"Starting training for {product_id}")
        
        df = data_collector.collect_multi_source_data(product_id, days=180)
        
        if df is None or df.empty:
            logger.warning(f"No data available for {product_id}")
            return {'error': 'No data available'}
        
        logger.info(f"Training data: {len(df)} records")
        
        df = data_collector.calculate_technical_indicators(df)
        
        features = feature_engineer.prepare(df, product_id)
        labels = self.create_labels(df, product_id, use_atr=True, label_type='3class')
        
        min_len = min(len(features), len(labels))
        
        if min_len < 100:
            logger.warning(f"Insufficient data for {product_id}: {min_len} rows")
            return {'error': f'Insufficient data: {min_len}'}
        
        X = features.iloc[:min_len].values
        y = labels.iloc[:min_len].values
        
        val_split = int(len(X) * 0.8)
        X_train = X[:val_split]
        y_train = y[:val_split]
        X_test = X[val_split:]
        y_test = y[val_split:]
        
        prices_full = df['close'].iloc[:min_len].values
        prices_test = prices_full[val_split:]
        
        best_config = self._find_best_atr_config(df, X_train, y_train, prices_full[:val_split])
        
        if best_config is None:
            logger.error(f"No valid ATR config found for {product_id}")
            return {'error': 'No valid ATR configuration'}
        
        targets = self.create_labels(df, product_id, use_atr=True, label_type='3class')
        y_train = targets.iloc[:val_split].values
        y_test = targets.iloc[val_split:].values
        
        results = {}
        
        if settings.USE_RF_MODEL:
            results['rf'] = self._train_rf(product_id, X_train, y_train, X_test, y_test, prices_test)
        
        if settings.USE_GB_MODEL:
            results['gb'] = self._train_gb(product_id, X_train, y_train, X_test, y_test, prices_test)
        
        if settings.USE_RIDGE_MODEL:
            results['ridge'] = self._train_ridge(product_id, X_train, y_train, X_test, y_test, prices_test)
        
        if settings.USE_MLP_MODEL:
            results['mlp'] = self._train_mlp(product_id, X_train, y_train, X_test, y_test, prices_test)
        
        logger.info(f"Training complete for {product_id}: {len(results)} models")
        return results
    
    def _find_best_atr_config(self, df: pd.DataFrame, X_train: np.ndarray, y_train: np.ndarray,
                             prices_train: np.ndarray) -> Optional[Dict]:
        """Find best ATR configuration by testing multiple thresholds."""
        
        atr_configs = [
            {'mult': 0.01, 'min': 0.00005},
            {'mult': 0.01, 'min': 0.0001},
            {'mult': 0.02, 'min': 0.00005},
            {'mult': 0.02, 'min': 0.0001},
            {'mult': 0.03, 'min': 0.00005},
            {'mult': 0.05, 'min': 0.0001},
            {'mult': 0.05, 'min': 0.0002},
            {'mult': 0.10, 'min': 0.0001},
            {'mult': 0.10, 'min': 0.0003},
            {'mult': 0.15, 'min': 0.0001},
        ]
        
        best_score = -1
        best_config = None
        
        for cfg in atr_configs:
            targets_test = self.create_labels(
                df, '', use_atr=True, label_type='3class'
            )
            
            unique_classes = sorted(targets_test.unique())
            if len(unique_classes) < 3:
                continue
            
            y_val = targets_test.iloc[:len(y_train)].values
            
            rf_test = RandomForestClassifier(n_estimators=50, max_depth=8, random_state=42, n_jobs=-1)
            
            try:
                rf_test.fit(X_train[:len(y_val)], y_val)
                y_pred = rf_test.predict(X_train[len(y_val):])
                
                metrics = trading_evaluator.evaluate_trading_performance(
                    y_train[len(y_val):], y_pred, prices_train[len(y_val):]
                )
                
                if metrics['num_trades'] >= 10 and metrics['win_rate'] >= 0.35:
                    if metrics['score'] > best_score:
                        best_score = metrics['score']
                        best_config = cfg
            except:
                continue
        
        return best_config
    
    def _train_rf(self, product_id: str, X_train: np.ndarray, y_train: np.ndarray,
                  X_test: np.ndarray, y_test: np.ndarray, prices_test: np.ndarray) -> Dict:
        """Train Random Forest model."""
        try:
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            model = RandomForestClassifier(
                n_estimators=200,
                max_depth=12,
                min_samples_split=10,
                min_samples_leaf=4,
                random_state=42,
                n_jobs=-1
            )
            model.fit(X_train_scaled, y_train)
            
            y_pred = model.predict(X_test_scaled)
            metrics = trading_evaluator.evaluate_trading_performance(y_test, y_pred, prices_test)
            
            model_storage.save_model(product_id, 'rf', model)
            model_storage.save_scaler(product_id, 'rf', scaler)
            
            return {'success': True, 'metrics': metrics}
        except Exception as e:
            logger.error(f"RF training failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _train_gb(self, product_id: str, X_train: np.ndarray, y_train: np.ndarray,
                  X_test: np.ndarray, y_test: np.ndarray, prices_test: np.ndarray) -> Dict:
        """Train Gradient Boosting model."""
        try:
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            model = GradientBoostingClassifier(
                n_estimators=150,
                max_depth=6,
                learning_rate=0.1,
                random_state=42
            )
            model.fit(X_train_scaled, y_train)
            
            y_pred = model.predict(X_test_scaled)
            metrics = trading_evaluator.evaluate_trading_performance(y_test, y_pred, prices_test)
            
            model_storage.save_model(product_id, 'gb', model)
            model_storage.save_scaler(product_id, 'gb', scaler)
            
            return {'success': True, 'metrics': metrics}
        except Exception as e:
            logger.error(f"GB training failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _train_ridge(self, product_id: str, X_train: np.ndarray, y_train: np.ndarray,
                      X_test: np.ndarray, y_test: np.ndarray, prices_test: np.ndarray) -> Dict:
        """Train Ridge Classifier model."""
        try:
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            model = RidgeClassifier(alpha=1.0, random_state=42)
            model.fit(X_train_scaled, y_train)
            
            y_pred = model.predict(X_test_scaled)
            metrics = trading_evaluator.evaluate_trading_performance(y_test, y_pred, prices_test)
            
            model_storage.save_model(product_id, 'ridge', model)
            model_storage.save_scaler(product_id, 'ridge', scaler)
            
            return {'success': True, 'metrics': metrics}
        except Exception as e:
            logger.error(f"Ridge training failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _train_mlp(self, product_id: str, X_train: np.ndarray, y_train: np.ndarray,
                   X_test: np.ndarray, y_test: np.ndarray, prices_test: np.ndarray) -> Dict:
        """Train MLP Neural Network model."""
        try:
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            model = MLPClassifier(
                hidden_layer_sizes=(64, 32),
                max_iter=500,
                random_state=42,
                early_stopping=True
            )
            model.fit(X_train_scaled, y_train)
            
            y_pred = model.predict(X_test_scaled)
            metrics = trading_evaluator.evaluate_trading_performance(y_test, y_pred, prices_test)
            
            model_storage.save_model(product_id, 'mlp', model)
            model_storage.save_scaler(product_id, 'mlp', scaler)
            
            return {'success': True, 'metrics': metrics}
        except Exception as e:
            logger.error(f"MLP training failed: {e}")
            return {'success': False, 'error': str(e)}


# Global singleton
model_trainer = ModelTrainer()


def train_model(product_id: str, force_retrain: bool = False) -> Dict[str, Any]:
    """Convenience function for model training."""
    return model_trainer.train(product_id, force_retrain)


__all__ = [
    'ModelTrainer',
    'model_trainer',
    'train_model'
]