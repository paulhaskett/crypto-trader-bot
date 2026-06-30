"""
AI Module - Modular AI/ML system for crypto trading.

This package provides a complete machine learning pipeline for generating
trading signals. It is organized into modular components:

Architecture:
- base.py       - Core utilities, types, logging
- config.py     - Configuration and settings
- regime.py     - Market regime detection
- features.py   - Feature engineering
- evaluation.py - Performance metrics
- ensemble.py   - Model ensemble voting
- models.py     - Model storage and management
- training.py   - Model training
- signals.py    - Signal generation wrapper

Usage:
    from src.ai import get_signal
    
    signal = get_signal('BTC-GBP')
    print(f"Action: {signal['action']}, Confidence: {signal['confidence']:.1%}")
"""

from typing import Dict, Any

# Base utilities and types
from .base import (
    logger,
    get_logger,
    PredictionResult,
    EnsembleResult,
    CLASS_SELL,
    CLASS_HOLD,
    CLASS_BUY,
    CLASS_NAMES,
    MODEL_TYPES,
    safe_float,
    safe_int,
    normalize_prediction,
    get_model_dir,
    get_log_dir,
    PredictionLogger,
    PerformanceTracker,
    SignalCache
)

# Regime detection
from .regime import (
    RegimeDetector,
    regime_detector,
    detect_regime,
    detect_volatility_regime
)

# Feature engineering
from .features import (
    FeatureEngineer,
    feature_engineer,
    prepare_features
)

# Evaluation
from .evaluation import (
    TradingEvaluator,
    trading_evaluator,
    evaluate_trading_performance
)

# Ensemble
from .ensemble import (
    EnsemblePredictor,
    ensemble_predictor,
    ensemble_predict
)

# Models
from .models import (
    ModelStorage,
    ModelManager,
    model_storage,
    model_manager
)

# Training
from .training import (
    ModelTrainer,
    model_trainer,
    train_model
)

# Signals
from .signals import (
    SignalGenerator,
    signal_generator,
    get_signal
)


# =============================================================================
# Main AIModel class - backward compatibility
# =============================================================================

class AIModel:
    """
    Main AI Model class for crypto price prediction.
    
    This class maintains backward compatibility with the original monolithic
    ai_model.py while using the modular internal components.
    
    For new code, consider using the individual modules directly:
        from src.ai import get_signal
        signal = get_signal('BTC-GBP')
    """
    
    def __init__(self):
        """Initialize AI Model."""
        from config.settings import settings
        from src.data_collector import data_collector
        
        self.training_pairs = settings.TRAINING_PAIRS
        self.gbp_trading_pairs = settings.PRODUCT_IDS
        
        self.prediction_horizon = settings.PREDICTION_HORIZON
        self.confidence_threshold = settings.MODEL_CONFIDENCE_THRESHOLD
        
        self.use_rf = settings.USE_RF_MODEL
        self.use_lr = settings.USE_LR_MODEL
        self.use_mlp = settings.USE_MLP_MODEL
        self.use_gb = settings.USE_GB_MODEL
        self.weight_mode = settings.ENSEMBLE_WEIGHT_MODE
        self.ensemble_enabled = settings.ENSEMBLE_ENABLED
        
        self._signal_cache = {}
        
        self.gbp_to_usd_map = {}
        for gbp_pair in self.gbp_trading_pairs:
            crypto_symbol = gbp_pair.split('-')[0]
            usd_pair = f"{crypto_symbol}-USD"
            if usd_pair in self.training_pairs:
                self.gbp_to_usd_map[gbp_pair] = usd_pair
        
        self._load_models()
    
    def _load_models(self):
        """Load all existing models."""
        from config.settings import settings
        
        model_types = []
        if settings.USE_RF_MODEL:
            model_types.append('rf')
        if settings.USE_GB_MODEL:
            model_types.append('gb')
        if settings.USE_RIDGE_MODEL:
            model_types.append('ridge')
        if settings.USE_MLP_MODEL:
            model_types.append('mlp')
        if settings.USE_LR_MODEL:
            model_types.append('lr')
        
        all_pairs = list(set(self.gbp_trading_pairs + self.training_pairs))
        model_manager.load_all_models(all_pairs, model_types)
        
        self.models = model_manager.rf_models
        self.gb_models = model_manager.gb_models
        self.ridge_models = model_manager.ridge_models
        self.mlp_models = model_manager.mlp_models
        self.lr_models = model_manager.lr_models
        
        self.scalers = model_manager.rf_scalers
        self.gb_scalers = model_manager.gb_scalers
        self.ridge_scalers = model_manager.ridge_scalers
        self.mlp_scalers = model_manager.mlp_scalers
        self.lr_scalers = model_manager.lr_scalers
    
    def get_signal(self, product_id: str, use_cache: bool = False) -> Dict:
        """Get trading signal for a product."""
        return signal_generator.generate(product_id, use_cache)
    
    def predict(self, product_id: str) -> Dict:
        """Alias for get_signal."""
        return self.get_signal(product_id)
    
    def load_existing_models(self):
        """Load existing models (backward compat)."""
        self._load_models()
    
    def load_existing_lr_models(self):
        """Load LR models (backward compat)."""
        pass
    
    def load_existing_mlp_models(self):
        """Load MLP models (backward compat)."""
        pass
    
    def load_existing_gb_models(self):
        """Load GB models (backward compat)."""
        pass
    
    def load_existing_ridge_models(self):
        """Load Ridge models (backward compat)."""
        pass
    
    def detect_regime(self, product_id: str) -> str:
        """Detect market regime."""
        return regime_detector.detect_regime(product_id)
    
    def train_model(self, product_id: str, test_size: float = 0.2, force_retrain: bool = False) -> Dict:
        """Train model for a product."""
        return model_trainer.train(product_id, force_retrain)
    
    @property
    def model_dir(self) -> str:
        """Get the model directory path."""
        from .base import get_model_dir
        return get_model_dir()
    
    def get_model_status(self) -> Dict:
        """Get status of all models."""
        from config.settings import settings
        
        status = {
            'total_models': 0,
            'loaded_models': {},
            'training_pairs': self.gbp_trading_pairs,
            'model_types': []
        }
        
        if self.use_rf:
            status['model_types'].append('rf')
            status['loaded_models']['rf'] = len(self.models) if hasattr(self, 'models') else 0
            status['total_models'] += len(self.models) if hasattr(self, 'models') else 0
        
        if self.use_gb:
            status['model_types'].append('gb')
            status['loaded_models']['gb'] = len(self.gb_models) if hasattr(self, 'gb_models') else 0
            status['total_models'] += len(self.gb_models) if hasattr(self, 'gb_models') else 0
        
        if settings.USE_RIDGE_MODEL:
            status['model_types'].append('ridge')
            status['loaded_models']['ridge'] = len(self.ridge_models) if hasattr(self, 'ridge_models') else 0
            status['total_models'] += len(self.ridge_models) if hasattr(self, 'ridge_models') else 0
        
        if self.use_mlp:
            status['model_types'].append('mlp')
            status['loaded_models']['mlp'] = len(self.mlp_models) if hasattr(self, 'mlp_models') else 0
            status['total_models'] += len(self.mlp_models) if hasattr(self, 'mlp_models') else 0
        
        return status
    
    def get_retrain_status(self) -> Dict:
        """Get retraining status."""
        from datetime import datetime
        from config.settings import settings
        from src.cache_manager import read_last_retrain_time
        
        last_date = read_last_retrain_time()
        days_since = None
        if last_date:
            try:
                last_dt = datetime.fromisoformat(last_date)
                days_since = (datetime.now() - last_dt).days
            except:
                pass
        
        return {
            'is_training': False,
            'current_product': None,
            'progress': 0,
            'last_retrain_date': last_date,
            'days_since_retrain': days_since,
            'auto_retrain_enabled': settings.AUTO_RETRAIN_ENABLED
        }
    
    def retrain_all_models(self, force: bool = False) -> Dict:
        """Retrain all models."""
        from config.settings import settings
        from .training import train_model
        
        results = {}
        for product_id in self.gbp_trading_pairs:
            try:
                result = train_model(product_id, force_retrain=force)
                results[product_id] = result
            except Exception as e:
                results[product_id] = {'success': False, 'error': str(e)}
        
        return results
    
    def _update_rolling_accuracy(self, product_id: str, predictions: Dict, actual_direction: str):
        """Update rolling accuracy tracking (no-op for now)."""
        pass
    
    def update_last_retrain_date(self):
        """Update last retrain date."""
        from datetime import datetime
        from src.cache_manager import write_last_retrain_time
        write_last_retrain_time(datetime.now().isoformat())

    def scheduled_retrain(self):
        """Scheduled retrain - called by APScheduler for auto-retrain."""
        logger.info("Auto-retrain triggered by scheduler")
        result = self.retrain_all_models(force=True)
        self.update_last_retrain_date()
        success = sum(1 for r in result.values() if isinstance(r, dict) and r.get('rf', {}).get('success', False))
        logger.info(f"Auto-retrain completed: {success}/{len(result)} models")

    def write_signals_to_file(self, signals: Dict):
        """Write signals to cache file (for dashboard sync)."""
        from src.cache_manager import write_signal_cache
        write_signal_cache(signals)
        logger.info(f"Wrote {len(signals)} signals to cache file")


# =============================================================================
# Export summary
# =============================================================================

__all__ = [
    # Main class
    'AIModel',
    
    # Signal generation (recommended)
    'get_signal',
    'signal_generator',
    'SignalGenerator',
    
    # Individual modules
    'logger',
    'regime_detector',
    'feature_engineer',
    'trading_evaluator',
    'ensemble_predictor',
    'model_storage',
    'model_manager',
    'model_trainer',
    
    # Types
    'PredictionResult',
    'EnsembleResult',
    'CLASS_SELL',
    'CLASS_HOLD',
    'CLASS_BUY',
    'CLASS_NAMES',
]


# Create global instance for backward compatibility
ai_model = AIModel()