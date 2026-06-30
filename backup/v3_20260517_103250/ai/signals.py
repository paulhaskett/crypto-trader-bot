"""
Signals Module - Signal generation wrapper.

This module provides the main entry point for generating trading signals:
- Coordinates regime detection, features, and ensemble prediction
- Handles caching for performance
- Provides prediction tracking
"""

import numpy as np
from typing import Dict, Any, Optional
from datetime import datetime

from .base import logger, SignalCache, PredictionLogger
from .regime import regime_detector
from .features import feature_engineer
from .ensemble import ensemble_predictor
from .models import model_manager


class SignalGenerator:
    """
    Main signal generation interface.
    
    Coordinates all components:
    - Regime detection
    - Feature preparation
    - Model predictions
    - Ensemble voting
    - Result formatting
    """
    
    def __init__(self):
        self.signal_cache = SignalCache()
        self.prediction_logger = PredictionLogger()
    
    def generate(self, product_id: str, use_cache: bool = False) -> Dict[str, Any]:
        """
        Generate trading signal for a product.
        
        Args:
            product_id: Trading pair (e.g., 'BTC-GBP')
            use_cache: Whether to use cached results
            
        Returns:
            Signal dictionary with action, confidence, regime, etc.
        """
        if use_cache:
            cached = self.signal_cache.get(product_id)
            if cached:
                return cached
        
        signal = self._generate_signal(product_id)
        
        self.signal_cache.set(product_id, signal)
        
        return signal
    
    def _generate_signal(self, product_id: str) -> Dict[str, Any]:
        """Generate signal without caching."""
        try:
            features = self._get_features(product_id)
            if features is None or features.empty:
                return self._empty_signal(product_id)
            
            X = features.tail(1).values
            
            predictions = {}
            probas = {}
            rf_model = None
            
            for model_type in ['rf', 'gb', 'ridge', 'mlp', 'lr']:
                model = model_manager.get_model(product_id, model_type)
                scaler = model_manager.get_scaler(product_id, model_type)
                
                if model is not None and scaler is not None:
                    try:
                        X_scaled = scaler.transform(X)
                        pred = model.predict(X_scaled)[0]
                        
                        predictions[model_type] = int(pred) if hasattr(pred, '__len__') else int(pred)
                        
                        if hasattr(model, 'predict_proba'):
                            proba = model.predict_proba(X_scaled)[0]
                            probas[model_type] = proba.tolist()
                        else:
                            probas[model_type] = [0.33, 0.34, 0.33]
                        
                        if model_type == 'rf':
                            rf_model = model
                    except Exception as e:
                        logger.warning(f"Error getting prediction from {model_type}: {e}")
            
            if not predictions:
                logger.error(f"No models available for {product_id}")
                return self._empty_signal(product_id)
            
            result = ensemble_predictor.predict(predictions, probas, rf_model, product_id)
            
            result['product_id'] = product_id
            result['timestamp'] = datetime.now().isoformat()
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating signal for {product_id}: {e}")
            return self._empty_signal(product_id)
    
    def _get_features(self, product_id: str):
        """Get features for a product."""
        from src.data_collector import data_collector
        
        df = data_collector.collect_historical_data(product_id, days=7)
        if df is None or df.empty:
            logger.warning(f"No data for {product_id}")
            return None
        
        df = data_collector.calculate_technical_indicators(df)
        features = feature_engineer.prepare(df, product_id)
        
        return features
    
    def _empty_signal(self, product_id: str) -> Dict[str, Any]:
        """Return empty signal."""
        return {
            'product_id': product_id,
            'action': 'HOLD',
            'confidence': 0.0,
            'prediction': 1,
            'regime': 'neutral',
            'volatility_regime': 'normal',
            'entry_price': 0.0,
            'stop_loss_price': 0.0,
            'timestamp': datetime.now().isoformat()
        }
    
    def clear_cache(self):
        """Clear signal cache."""
        self.signal_cache.clear()


# Global singleton
signal_generator = SignalGenerator()


def get_signal(product_id: str, use_cache: bool = False) -> Dict[str, Any]:
    """Convenience function for getting signals."""
    return signal_generator.generate(product_id, use_cache)


__all__ = [
    'SignalGenerator',
    'signal_generator',
    'get_signal'
]