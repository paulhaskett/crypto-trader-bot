"""
Ensemble Module - Voting logic and ensemble prediction.

This module provides:
- Model prediction aggregation
- Weighted voting with regime adjustments
- Confidence calculation
- Model agreement analysis
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from collections import Counter

from config.settings import settings
from .base import logger, CLASS_SELL, CLASS_HOLD, CLASS_BUY, CLASS_NAMES
from .regime import regime_detector


class EnsemblePredictor:
    """
    Ensemble prediction with weighted voting.
    
    Combines predictions from multiple model types:
    - Random Forest (RF)
    - Gradient Boosting (GB)
    - Ridge Classifier
    - MLP Neural Network
    - Logistic Regression
    
    Features:
    - Configurable vote threshold
    - Regime-adjusted confidence
    - Model agreement scoring
    - Live performance tracking
    """
    
    def __init__(self):
        self.confidence_threshold = settings.MODEL_CONFIDENCE_THRESHOLD
        self.vote_threshold = settings.ENSEMBLE_VOTE_THRESHOLD
        self.weight_mode = settings.ENSEMBLE_WEIGHT_MODE
        
        self._performance_cache: Dict[str, Dict[str, float]] = {}
    
    def predict(self, predictions: Dict[str, int], probas: Dict[str, List[float]],
                rf_model: Optional[Any] = None, product_id: str = "") -> Dict[str, Any]:
        """
        Combine predictions from multiple models into ensemble result.
        
        Args:
            predictions: Dict of model_name -> prediction
            probas: Dict of model_name -> probabilities
            rf_model: Reference RF model for class info
            product_id: Trading pair for regime adjustments
            
        Returns:
            Dict with action, confidence, prediction, regime, etc.
        """
        try:
            n_classes = 2
            if rf_model and hasattr(rf_model, 'classes_'):
                n_classes = len(rf_model.classes_)
            
            vote_list = [int(p) for p in predictions.values()]
            n_models = len(vote_list)
            
            if n_models == 0:
                return self._default_result()
            
            n_classes = max(n_classes, 2)  # At least binary
            
            if n_classes >= 3:
                result = self._predict_3class(vote_list, probas, n_models)
            else:
                result = self._predict_binary(vote_list, probas, n_models)
            
            regime = regime_detector.detect_regime(product_id)
            volatility = regime_detector.detect_volatility_regime(product_id)
            
            result['regime'] = regime
            result['volatility_regime'] = volatility
            
            result = self._apply_regime_adjustments(result, regime, volatility)
            
            return result
            
        except Exception as e:
            logger.error(f"Error in ensemble prediction: {e}")
            return self._default_result()
    
    def _predict_3class(self, vote_list: List[int], probas: Dict[str, List[float]],
                        n_models: int) -> Dict[str, Any]:
        """Predict with 3-class labels (BUY=2, SELL=0, HOLD=1)."""
        buy_votes = sum(1 for v in vote_list if v == CLASS_BUY)
        sell_votes = sum(1 for v in vote_list if v == CLASS_SELL)
        
        votes_needed = max(2, int(self.vote_threshold * n_models))
        fallback_votes_needed = max(2, int(0.66 * n_models))
        
        if buy_votes >= votes_needed:
            majority_vote = CLASS_BUY
        elif sell_votes >= votes_needed:
            majority_vote = CLASS_SELL
        elif buy_votes >= fallback_votes_needed and n_models >= 3:
            majority_vote = CLASS_BUY
        elif sell_votes >= fallback_votes_needed and n_models >= 3:
            majority_vote = CLASS_SELL
        else:
            majority_vote = CLASS_HOLD
        
        agreement = self._calculate_agreement(vote_list, n_classes=3)
        
        confidence = self._calculate_confidence(
            majority_vote, vote_list, probas, agreement
        )
        
        # Phase 3: Pass agreement info for enhanced confidence scoring
        action = self._get_action(majority_vote, confidence, agreement, n_models)
        
        return {
            'prediction': int(majority_vote),
            'confidence': float(confidence),
            'action': action,
            'agreement': float(agreement),
            'buy_votes': buy_votes,
            'sell_votes': sell_votes,
            'n_models': n_models,
            'agreement_level': self._get_agreement_level(agreement, n_models)
        }
    
    def _predict_binary(self, vote_list: List[int], probas: Dict[str, List[float]],
                        n_models: int) -> Dict[str, Any]:
        """Predict with binary labels (BUY=1, SELL=0)."""
        votes_needed = max(2, int(self.vote_threshold * n_models))
        
        buy_count = sum(vote_list)
        majority_vote = CLASS_BUY if buy_count >= votes_needed else CLASS_SELL
        
        agreement = buy_count / n_models if n_models > 0 else 0
        
        confidence = self._calculate_confidence(
            majority_vote, vote_list, probas, agreement
        )
        
        # Phase 3: Pass agreement info for enhanced confidence scoring
        action = self._get_action(majority_vote, confidence, agreement, n_models)
        
        return {
            'prediction': int(majority_vote),
            'confidence': float(confidence),
            'action': action,
            'agreement': float(agreement),
            'buy_votes': buy_count,
            'n_models': n_models,
            'agreement_level': self._get_agreement_level(agreement, n_models)
        }
    
    def _calculate_agreement(self, vote_list: List[int], n_classes: int = 3) -> float:
        """Calculate model agreement score."""
        if not vote_list:
            return 0.0
        
        n_models = len(vote_list)
        vote_counts = Counter(vote_list)
        majority = vote_counts.most_common(1)[0][0]
        
        vote_values = []
        for v in vote_list:
            if v == majority:
                vote_values.append(1.0)
            elif n_classes >= 3 and abs(v - majority) == 1:
                vote_values.append(0.75)
            else:
                vote_values.append(0.0)
        
        return sum(vote_values) / n_models if n_models > 0 else 0
    
    def _calculate_confidence(self, majority_vote: int, vote_list: List[int],
                              probas: Dict[str, List[float]], agreement: float) -> float:
        """Calculate confidence based on agreement and model probabilities."""
        if agreement >= 0.66 and len(vote_list) >= 2:
            buyer_confs = []
            seller_confs = []
            
            for model_name, pred in zip(probas.keys(), vote_list):
                try:
                    proba = np.array(probas[model_name]).flatten()
                    if majority_vote == CLASS_BUY and len(proba) > 2:
                        buyer_confs.append(float(proba[2]))
                    elif majority_vote == CLASS_SELL and len(proba) > 0:
                        seller_confs.append(float(proba[0]))
                except (IndexError, TypeError):
                    pass
            
            if majority_vote == CLASS_BUY and buyer_confs:
                return sum(buyer_confs) / len(buyer_confs)
            elif majority_vote == CLASS_SELL and seller_confs:
                return sum(seller_confs) / len(seller_confs)
        
        return float(agreement)
    
    def _get_action(self, prediction: int, confidence: float, 
                   agreement: float = 0.0, n_models: int = 3) -> str:
        """Convert prediction and confidence to action with agreement-based scoring."""
        
        # Phase 3: Enhanced confidence scoring based on model agreement
        # unanimous (all 3+ agree) = high confidence boost
        # 2/3 agree = medium confidence
        # split (1 each) = low confidence (should HOLD)
        
        agreement_level = self._get_agreement_level(agreement, n_models)
        
        # Apply agreement-based confidence adjustment
        if agreement_level == 'unanimous':
            # All models agree - boost confidence significantly
            adjusted_confidence = confidence * 1.15
            logger.debug(f"Agreement: unanimous - boosted confidence to {adjusted_confidence:.1%}")
        elif agreement_level == 'majority':
            # 2/3 agree - use as-is
            adjusted_confidence = confidence
            logger.debug(f"Agreement: majority - using confidence {adjusted_confidence:.1%}")
        else:
            # Split/mixed - reduce confidence significantly
            adjusted_confidence = confidence * 0.7
            logger.debug(f"Agreement: split - reduced confidence to {adjusted_confidence:.1%}")
        
        # Store agreement level for reporting
        result_key = f'_agreement_level'
        
        if prediction == CLASS_BUY and adjusted_confidence > self.confidence_threshold:
            return 'BUY'
        elif prediction == CLASS_SELL and adjusted_confidence > self.confidence_threshold:
            return 'SELL'
        else:
            return 'HOLD'
    
    def _get_agreement_level(self, agreement: float, n_models: int) -> str:
        """Determine agreement level for confidence adjustment."""
        if n_models >= 3:
            if agreement >= 0.9:
                return 'unanimous'
            elif agreement >= 0.6:
                return 'majority'
            else:
                return 'split'
        else:
            if agreement >= 0.8:
                return 'unanimous'
            elif agreement >= 0.5:
                return 'majority'
            return 'split'
    
    def _apply_regime_adjustments(self, result: Dict[str, Any], regime: str,
                                   volatility: Dict[str, Any]) -> Dict[str, Any]:
        """Apply regime-based confidence adjustments and model weighting."""
        action = result.get('action', 'HOLD')
        confidence = result.get('confidence', 0.5)
        
        # Phase 3: Enhanced regime-based confidence adjustments
        
        # 1. Uptrend: RF and GB are better (trend following)
        if regime == 'uptrend' and action == 'BUY':
            confidence = min(confidence * 1.20, 0.95)  # Increased boost from 1.15
            logger.info(f"Phase3: Boosted BUY confidence in uptrend: {confidence:.1%}")
        
        # 2. Downtrend: Ridge is better (mean reversion), reduce BUY
        elif regime == 'downtrend' and action == 'BUY':
            confidence = confidence * 0.65  # Increased reduction from 0.7
            logger.info(f"Phase3: Reduced BUY confidence in downtrend: {confidence:.1%}")
        
        # 3. Downtrend SELL: GB is good (momentum)
        elif regime == 'downtrend' and action == 'SELL':
            confidence = min(confidence * 1.20, 0.95)
            logger.info(f"Phase3: Boosted SELL confidence in downtrend: {confidence:.1%}")
        
        # 4. Neutral: balanced weighting
        elif regime == 'neutral':
            logger.debug(f"Phase3: Neutral regime - using standard confidence")
        
        # 5. Volatility adjustments
        vol_regime = volatility.get('regime', 'normal')
        if vol_regime == 'high':
            confidence = confidence * 0.75  # Increased reduction from 0.8
            logger.info(f"Phase3: Reduced confidence in high volatility: {confidence:.1%}")
        elif vol_regime == 'low':
            confidence = min(confidence * 1.15, 0.95)
            logger.info(f"Phase3: Boosted confidence in low volatility: {confidence:.1%}")
        
        result['confidence'] = confidence
        
        # Add regime info for dashboard
        result['regime_confidence'] = {
            'regime': regime,
            'volatility': vol_regime,
            'base_confidence': result.get('confidence', 0.5)
        }
        
        if confidence > self.confidence_threshold and action != 'HOLD':
            result['action'] = action
        else:
            result['action'] = 'HOLD'
        
        return result
    
    def _default_result(self) -> Dict[str, Any]:
        """Return default result when prediction fails."""
        return {
            'prediction': CLASS_HOLD,
            'confidence': 0.0,
            'action': 'HOLD',
            'agreement': 0.0,
            'regime': 'neutral',
            'volatility_regime': 'normal'
        }
    
    def get_model_weights(self, product_id: str) -> Dict[str, float]:
        """Get regime-adjusted model weights."""
        weights = {}
        
        base_weights = {
            'rf': 0.25,
            'gb': 0.25,
            'ridge': 0.25,
            'mlp': 0.15,
            'lr': 0.10
        }
        
        for model_name, weight in base_weights.items():
            weights[model_name] = weight
        
        if self.weight_mode == 'performance' and product_id in self._performance_cache:
            perf = self._performance_cache[product_id]
            total = sum(perf.values()) if perf else 1
            if total > 0:
                for k in weights:
                    weights[k] = perf.get(k, 0.5) / total
        
        return weights
    
    def update_performance(self, product_id: str, model_name: str, accuracy: float):
        """Update performance cache for adaptive weighting."""
        if product_id not in self._performance_cache:
            self._performance_cache[product_id] = {}
        self._performance_cache[product_id][model_name] = accuracy


# Global singleton
ensemble_predictor = EnsemblePredictor()


def ensemble_predict(predictions: Dict[str, int], probas: Dict[str, List[float]],
                     rf_model: Optional[Any] = None, product_id: str = "") -> Dict[str, Any]:
    """Convenience function for ensemble prediction."""
    return ensemble_predictor.predict(predictions, probas, rf_model, product_id)


__all__ = [
    'EnsemblePredictor',
    'ensemble_predictor',
    'ensemble_predict'
]