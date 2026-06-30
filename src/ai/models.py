"""
Models Module - Model loading, saving, and storage.

This module provides:
- Model file loading from disk
- Model saving to disk
- Scaler management
- Model validation
"""

import os
import joblib
from typing import Dict, Any, Optional, List, Tuple

from .base import logger, get_model_dir


class ModelStorage:
    """
    Manages model files on disk.
    
    Handles loading and saving of:
    - Random Forest models
    - Gradient Boosting models
    - Ridge classifiers
    - MLP neural networks
    - Feature scalers
    """
    
    def __init__(self, model_dir: Optional[str] = None):
        self.model_dir = model_dir or get_model_dir()
        os.makedirs(self.model_dir, exist_ok=True)
    
    def _get_filename(self, product_id: str, model_type: str, suffix: str = "") -> str:
        """Generate model filename."""
        clean_id = product_id.replace('-', '_')
        if suffix:
            return f"{clean_id}_{model_type}_{suffix}.joblib"
        return f"{clean_id}_{model_type}.joblib"
    
    def _get_legacy_filename(self, product_id: str, model_type: str) -> str:
        """Generate legacy model filename for backward compatibility."""
        clean_id = product_id.replace('-', '_')
        # Legacy: BTC_GBP_rf_model.joblib
        type_suffix = {'rf': 'rf', 'gb': 'gb', 'ridge': 'ridge', 'mlp': 'mlp', 'lr': 'lr'}
        return f"{clean_id}_{type_suffix.get(model_type, model_type)}_model.joblib"
    
    def load_model(self, product_id: str, model_type: str) -> Optional[Any]:
        """Load a single model from disk (tries new and legacy filenames)."""
        # Try new format first: BTC_GBP_rf.joblib
        filepath = os.path.join(self.model_dir, self._get_filename(product_id, model_type))
        
        if not os.path.exists(filepath):
            # Try legacy format: BTC_GBP_rf_model.joblib
            filepath = os.path.join(self.model_dir, self._get_legacy_filename(product_id, model_type))
        
        if not os.path.exists(filepath):
            logger.warning(f"Model not found: {product_id}_{model_type}")
            return None
        
        try:
            model = joblib.load(filepath)
            logger.info(f"Loaded {model_type} model for {product_id}")
            return model
        except Exception as e:
            logger.error(f"Error loading {model_type} model for {product_id}: {e}")
            return None
    
    def save_model(self, product_id: str, model_type: str, model: Any,
                   suffix: str = "") -> bool:
        """Save a model to disk."""
        filepath = os.path.join(self.model_dir, self._get_filename(product_id, model_type, suffix))
        
        try:
            joblib.dump(model, filepath)
            logger.info(f"Saved {model_type} model for {product_id} to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error saving {model_type} model for {product_id}: {e}")
            return False
    
    def load_scaler(self, product_id: str, model_type: str) -> Optional[Any]:
        """Load a scaler from disk."""
        filepath = os.path.join(self.model_dir, self._get_filename(product_id, model_type, "scaler"))
        
        if not os.path.exists(filepath):
            logger.warning(f"Scaler not found: {filepath}")
            return None
        
        try:
            scaler = joblib.load(filepath)
            logger.info(f"Loaded {model_type} scaler for {product_id}")
            return scaler
        except Exception as e:
            logger.error(f"Error loading {model_type} scaler for {product_id}: {e}")
            return None
    
    def save_scaler(self, product_id: str, model_type: str, scaler: Any) -> bool:
        """Save a scaler to disk."""
        filepath = os.path.join(self.model_dir, self._get_filename(product_id, model_type, "scaler"))
        
        try:
            joblib.dump(scaler, filepath)
            logger.info(f"Saved {model_type} scaler for {product_id} to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error saving {model_type} scaler for {product_id}: {e}")
            return False
    
    def model_exists(self, product_id: str, model_type: str) -> bool:
        """Check if model file exists."""
        filepath = os.path.join(self.model_dir, self._get_filename(product_id, model_type))
        return os.path.exists(filepath)
    
    def scaler_exists(self, product_id: str, model_type: str) -> bool:
        """Check if scaler file exists."""
        filepath = os.path.join(self.model_dir, self._get_filename(product_id, model_type, "scaler"))
        return os.path.exists(filepath)
    
    def get_available_models(self, product_id: str) -> Dict[str, bool]:
        """Get dict of model types and their availability."""
        model_types = ['rf', 'gb', 'ridge', 'mlp', 'lr']
        return {
            mt: self.model_exists(product_id, mt)
            for mt in model_types
        }
    
    def delete_model(self, product_id: str, model_type: str) -> bool:
        """Delete a model file."""
        filepath = os.path.join(self.model_dir, self._get_filename(product_id, model_type))
        
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Deleted {model_type} model for {product_id}")
                return True
            except Exception as e:
                logger.error(f"Error deleting {model_type} model: {e}")
                return False
        return False
    
    def list_all_models(self) -> List[Tuple[str, str]]:
        """List all model files with their product IDs."""
        models = []
        
        for filename in os.listdir(self.model_dir):
            if filename.endswith('.joblib') and not filename.endswith('_scaler.joblib'):
                parts = filename.replace('.joblib', '').split('_')
                if len(parts) >= 2:
                    product_id = parts[0] + '-' + parts[1]
                    model_type = parts[2] if len(parts) > 2 else 'unknown'
                    models.append((product_id, model_type))
        
        return models


class ModelManager:
    """
    Manages all model types for a trading system.
    
    Provides a unified interface for loading and using multiple model types
    across multiple trading pairs.
    """
    
    def __init__(self):
        self.storage = ModelStorage()
        
        self.rf_models: Dict[str, Any] = {}
        self.rf_scalers: Dict[str, Any] = {}
        
        self.gb_models: Dict[str, Any] = {}
        self.gb_scalers: Dict[str, Any] = {}
        
        self.ridge_models: Dict[str, Any] = {}
        self.ridge_scalers: Dict[str, Any] = {}
        
        self.mlp_models: Dict[str, Any] = {}
        self.mlp_scalers: Dict[str, Any] = {}
        
        self.lr_models: Dict[str, Any] = {}
        self.lr_scalers: Dict[str, Any] = {}
    
    def load_all_models(self, product_ids: List[str], model_types: List[str]):
        """Load all models for given product IDs and types."""
        from config.settings import settings
        
        for product_id in product_ids:
            if 'rf' in model_types and settings.USE_RF_MODEL:
                self.rf_models[product_id] = self.storage.load_model(product_id, 'rf')
                self.rf_scalers[product_id] = self.storage.load_scaler(product_id, 'rf')
            
            if 'gb' in model_types and settings.USE_GB_MODEL:
                self.gb_models[product_id] = self.storage.load_model(product_id, 'gb')
                self.gb_scalers[product_id] = self.storage.load_scaler(product_id, 'gb')
            
            if 'ridge' in model_types and settings.USE_RIDGE_MODEL:
                self.ridge_models[product_id] = self.storage.load_model(product_id, 'ridge')
                self.ridge_scalers[product_id] = self.storage.load_scaler(product_id, 'ridge')
            
            if 'mlp' in model_types and settings.USE_MLP_MODEL:
                self.mlp_models[product_id] = self.storage.load_model(product_id, 'mlp')
                self.mlp_scalers[product_id] = self.storage.load_scaler(product_id, 'mlp')
            
            if 'lr' in model_types and settings.USE_LR_MODEL:
                self.lr_models[product_id] = self.storage.load_model(product_id, 'lr')
                self.lr_scalers[product_id] = self.storage.load_scaler(product_id, 'lr')
    
    def save_all_models(self, product_id: str, models_dict: Dict[str, Tuple[Any, Any]]):
        """Save all model types for a product."""
        for model_type, (model, scaler) in models_dict.items():
            self.storage.save_model(product_id, model_type, model)
            if scaler is not None:
                self.storage.save_scaler(product_id, model_type, scaler)
    
    def get_model(self, product_id: str, model_type: str) -> Optional[Any]:
        """Get a model by type."""
        models_map = {
            'rf': self.rf_models,
            'gb': self.gb_models,
            'ridge': self.ridge_models,
            'mlp': self.mlp_models,
            'lr': self.lr_models
        }
        return models_map.get(model_type, {}).get(product_id)
    
    def get_scaler(self, product_id: str, model_type: str) -> Optional[Any]:
        """Get a scaler by type."""
        scalers_map = {
            'rf': self.rf_scalers,
            'gb': self.gb_scalers,
            'ridge': self.ridge_scalers,
            'mlp': self.mlp_scalers,
            'lr': self.lr_scalers
        }
        return scalers_map.get(model_type, {}).get(product_id)
    
    def get_enabled_models(self, product_id: str) -> Dict[str, Any]:
        """Get dict of all enabled models for a product."""
        from config.settings import settings
        
        models = {}
        
        if settings.USE_RF_MODEL and product_id in self.rf_models:
            models['rf'] = self.rf_models[product_id]
        if settings.USE_GB_MODEL and product_id in self.gb_models:
            models['gb'] = self.gb_models[product_id]
        if settings.USE_RIDGE_MODEL and product_id in self.ridge_models:
            models['ridge'] = self.ridge_models[product_id]
        if settings.USE_MLP_MODEL and product_id in self.mlp_models:
            models['mlp'] = self.mlp_models[product_id]
        if settings.USE_LR_MODEL and product_id in self.lr_models:
            models['lr'] = self.lr_models[product_id]
        
        return models
    
    def get_all_scalers(self, product_id: str) -> Dict[str, Any]:
        """Get dict of all scalers for a product."""
        from config.settings import settings
        
        scalers = {}
        
        if settings.USE_RF_MODEL and product_id in self.rf_scalers:
            scalers['rf'] = self.rf_scalers[product_id]
        if settings.USE_GB_MODEL and product_id in self.gb_scalers:
            scalers['gb'] = self.gb_scalers[product_id]
        if settings.USE_RIDGE_MODEL and product_id in self.ridge_scalers:
            scalers['ridge'] = self.ridge_scalers[product_id]
        if settings.USE_MLP_MODEL and product_id in self.mlp_scalers:
            scalers['mlp'] = self.mlp_scalers[product_id]
        if settings.USE_LR_MODEL and product_id in self.lr_scalers:
            scalers['lr'] = self.lr_scalers[product_id]
        
        return scalers
    
    def get_model_counts(self) -> Dict[str, int]:
        """Get count of loaded models by type."""
        return {
            'rf': len(self.rf_models),
            'gb': len(self.gb_models),
            'ridge': len(self.ridge_models),
            'mlp': len(self.mlp_models),
            'lr': len(self.lr_models)
        }


# Global singleton
model_storage = ModelStorage()
model_manager = ModelManager()


__all__ = [
    'ModelStorage',
    'ModelManager',
    'model_storage',
    'model_manager'
]