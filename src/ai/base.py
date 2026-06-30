"""
AI Base Module - Core utilities, types, and configuration.

This module provides the foundational components for the AI trading system:
- Type definitions and constants
- Logger setup
- Base exception classes
- Common utility functions
"""

import logging
import os
import csv
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

import numpy as np
import pandas as pd


# =============================================================================
# Logger Setup
# =============================================================================

def get_logger(name: str) -> logging.Logger:
    """Get a configured logger for the AI module."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


logger = get_logger(__name__)


# =============================================================================
# Type Definitions
# =============================================================================

class PredictionResult:
    """Container for model prediction results."""
    
    def __init__(self, prediction: int, confidence: float, probas: List[float],
                 model_name: str = "unknown"):
        self.prediction = prediction
        self.confidence = confidence
        self.probas = probas
        self.model_name = model_name
    
    def __repr__(self):
        return f"PredictionResult({self.model_name}: pred={self.prediction}, conf={self.confidence:.2f})"


class EnsembleResult:
    """Container for ensemble prediction results."""
    
    def __init__(self, action: str, confidence: float, prediction: int,
                 regime: str = "neutral", volatility_regime: str = "normal",
                 agreement: float = 0.0, details: Dict = None):
        self.action = action
        self.confidence = confidence
        self.prediction = prediction
        self.regime = regime
        self.volatility_regime = volatility_regime
        self.agreement = agreement
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'action': self.action,
            'confidence': self.confidence,
            'prediction': self.prediction,
            'regime': self.regime,
            'volatility_regime': self.volatility_regime,
            'agreement': self.agreement,
            **self.details
        }


# =============================================================================
# Constants
# =============================================================================

# Model prediction classes
CLASS_SELL = 0
CLASS_HOLD = 1
CLASS_BUY = 2

CLASS_NAMES = {
    CLASS_SELL: 'SELL',
    CLASS_HOLD: 'HOLD',
    CLASS_BUY: 'BUY'
}

# Default model types
MODEL_TYPES = ['rf', 'gb', 'ridge', 'mlp', 'lr']

# Cache TTL settings (in seconds)
SIGNAL_CACHE_TTL = 300  # 5 minutes
REGIME_CACHE_TTL = 300  # 5 minutes


# =============================================================================
# Utility Functions
# =============================================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int."""
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def normalize_prediction(pred: Any, n_classes: int = 3) -> int:
    """Normalize prediction to valid class range."""
    try:
        pred_int = int(pred) if not hasattr(pred, '__len__') else int(np.asarray(pred).flat[0])
        return max(0, min(pred_int, n_classes - 1))
    except (TypeError, ValueError):
        return CLASS_HOLD


def get_model_dir() -> str:
    """Get the models directory path."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'models')


def get_log_dir() -> str:
    """Get the logs directory path."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'logs')


# =============================================================================
# Prediction Logging
# =============================================================================

class PredictionLogger:
    """
    Handles logging of predictions to CSV for analysis.
    
    This enables tracking model performance over time and identifying
    patterns in successful vs failed predictions.
    """
    
    def __init__(self, log_file: Optional[str] = None, buffer_size: int = 50):
        self.log_file = log_file or os.path.join(get_log_dir(), 'predictions.csv')
        self.buffer_size = buffer_size
        self._buffer: List[Dict] = []
        self._headers_written = False
        
        # Ensure log directory exists
        log_dir = os.path.dirname(self.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # Check if file exists
        self._headers_written = os.path.exists(self.log_file)
    
    def log(self, product_id: str, predictions: Dict[str, int],
            probas: Dict[str, List[float]], ensemble_result: Dict[str, Any],
            features: Optional[Dict] = None, future_return: Optional[float] = None):
        """Log a single prediction."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'product_id': product_id,
            'features': json.dumps(features) if features else '{}',
            'rf_prediction': predictions.get('rf'),
            'lr_prediction': predictions.get('lr'),
            'mlp_prediction': predictions.get('mlp'),
            'gb_prediction': predictions.get('gb'),
            'ridge_prediction': predictions.get('ridge'),
            'rf_confidence': probas.get('rf', [0, 0, 0])[2] if len(probas.get('rf', [])) > 2 else 0,
            'lr_confidence': probas.get('lr', [0, 0, 0])[2] if len(probas.get('lr', [])) > 2 else 0,
            'mlp_confidence': probas.get('mlp', [0, 0, 0])[2] if len(probas.get('mlp', [])) > 2 else 0,
            'gb_confidence': probas.get('gb', [0, 0, 0])[2] if len(probas.get('gb', [])) > 2 else 0,
            'ridge_confidence': probas.get('ridge', [0, 0, 0])[2] if len(probas.get('ridge', [])) > 2 else 0,
            'ensemble_prediction': ensemble_result.get('prediction'),
            'ensemble_confidence': ensemble_result.get('confidence', 0),
            'action': ensemble_result.get('action', 'HOLD'),
            'regime': ensemble_result.get('regime', 'neutral'),
            'volatility_regime': ensemble_result.get('volatility_regime', 'normal'),
            'future_return': future_return if future_return is not None else ''
        }
        
        self._buffer.append(entry)
        
        if len(self._buffer) >= self.buffer_size:
            self.flush()
    
    def flush(self):
        """Write buffered entries to file."""
        if not self._buffer:
            return
        
        try:
            fieldnames = [
                'timestamp', 'product_id', 'features',
                'rf_prediction', 'lr_prediction', 'mlp_prediction', 'gb_prediction', 'ridge_prediction',
                'rf_confidence', 'lr_confidence', 'mlp_confidence', 'gb_confidence', 'ridge_confidence',
                'ensemble_prediction', 'ensemble_confidence', 'action',
                'regime', 'volatility_regime', 'future_return'
            ]
            
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                if not self._headers_written:
                    writer.writeheader()
                    self._headers_written = True
                
                for entry in self._buffer:
                    writer.writerow(entry)
            
            self._buffer.clear()
        except Exception as e:
            logger.error(f"Error flushing prediction log: {e}")
    
    def __del__(self):
        """Ensure buffer is flushed on cleanup."""
        self.flush()


# =============================================================================
# Performance Tracking
# =============================================================================

class PerformanceTracker:
    """
    Tracks model prediction performance for adaptive weighting.
    
    Maintains rolling statistics of predictions vs actual outcomes
    to dynamically adjust model weights in the ensemble.
    """
    
    def __init__(self, horizon: int = 30):
        self.horizon = horizon
        self._data: Dict[str, Dict[str, List[Dict]]] = {}
    
    def record(self, product_id: str, model_name: str, prediction: int,
               actual_direction: int, correct: bool):
        """Record a prediction outcome."""
        if product_id not in self._data:
            self._data[product_id] = {m: [] for m in MODEL_TYPES}
        
        self._data[product_id][model_name].append({
            'prediction': prediction,
            'actual': actual_direction,
            'correct': correct,
            'timestamp': datetime.now()
        })
        
        # Trim to horizon
        if len(self._data[product_id][model_name]) > self.horizon:
            self._data[product_id][model_name] = self._data[product_id][model_name][-self.horizon:]
    
    def get_accuracy(self, product_id: str, model_name: str) -> float:
        """Get accuracy for a model on a product."""
        if product_id not in self._data:
            return 0.5  # Default neutral
        
        history = self._data[product_id].get(model_name, [])
        if not history:
            return 0.5
        
        correct_count = sum(1 for h in history if h['correct'])
        return correct_count / len(history)
    
    def get_all_accuracies(self, product_id: str) -> Dict[str, float]:
        """Get all model accuracies for a product."""
        return {
            m: self.get_accuracy(product_id, m)
            for m in MODEL_TYPES
        }


# =============================================================================
# Signal Cache
# =============================================================================

class SignalCache:
    """Simple TTL cache for signals."""
    
    def __init__(self, ttl: int = SIGNAL_CACHE_TTL):
        self.ttl = ttl
        self._cache: Dict[str, Tuple[Dict, datetime]] = {}
    
    def get(self, product_id: str) -> Optional[Dict]:
        """Get cached signal if not expired."""
        if product_id in self._cache:
            signal, timestamp = self._cache[product_id]
            age = (datetime.now() - timestamp).total_seconds()
            if age < self.ttl:
                return signal
            else:
                del self._cache[product_id]
        return None
    
    def set(self, product_id: str, signal: Dict):
        """Set cached signal."""
        self._cache[product_id] = (signal, datetime.now())
    
    def clear(self):
        """Clear all cached signals."""
        self._cache.clear()


# =============================================================================
# Export
# =============================================================================

__all__ = [
    'logger',
    'get_logger',
    'PredictionResult',
    'EnsembleResult',
    'CLASS_SELL',
    'CLASS_HOLD', 
    'CLASS_BUY',
    'CLASS_NAMES',
    'MODEL_TYPES',
    'safe_float',
    'safe_int',
    'normalize_prediction',
    'get_model_dir',
    'get_log_dir',
    'PredictionLogger',
    'PerformanceTracker',
    'SignalCache'
]