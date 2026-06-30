"""
AI Model module for crypto trading bot - Backward Compatibility Wrapper.

This module is now a thin wrapper that imports from the modular ai/ package.
For new development, import directly from src.ai:

    from src.ai import get_signal
    signal = get_signal('BTC-GBP')

The modular structure provides:
- base.py       - Core utilities, types, logging
- regime.py     - Market regime detection  
- features.py  - Feature engineering
- evaluation.py - Performance metrics
- ensemble.py  - Model ensemble voting
- models.py    - Model storage
- training.py  - Model training
- signals.py   - Signal generation

This file maintains backward compatibility with existing imports.
"""

# Re-export everything from the new modular package
from src.ai import (
    # Main class
    AIModel,
    
    # Signal generation (recommended)
    get_signal,
    signal_generator,
    SignalGenerator,
    
    # Individual modules
    logger,
    regime_detector,
    feature_engineer,
    trading_evaluator,
    ensemble_predictor,
    model_storage,
    model_manager,
    model_trainer,
    
    # Types
    PredictionResult,
    EnsembleResult,
    CLASS_SELL,
    CLASS_HOLD,
    CLASS_BUY,
    CLASS_NAMES,
    
    # Performance tracking
    PerformanceTracker,
    PredictionLogger,
    SignalCache
)


# Create global instance for backward compatibility
ai_model = AIModel()


__all__ = [
    'AIModel',
    'get_signal',
    'signal_generator',
    'SignalGenerator',
    'logger',
    'regime_detector', 
    'feature_engineer',
    'trading_evaluator',
    'ensemble_predictor',
    'model_storage',
    'model_manager',
    'model_trainer',
    'PredictionResult',
    'EnsembleResult',
    'CLASS_SELL',
    'CLASS_HOLD',
    'CLASS_BUY',
    'CLASS_NAMES',
    'PerformanceTracker',
    'PredictionLogger',
    'SignalCache',
    'ai_model'
]