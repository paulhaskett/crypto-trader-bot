"""
Evaluation Module - Trading performance metrics.

This module provides functions to evaluate model performance:
- Trading simulation metrics (win rate, profit factor)
- Cross-validation scoring
- Signal quality assessment
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

from .base import logger, CLASS_BUY, CLASS_SELL, CLASS_HOLD


class TradingEvaluator:
    """
    Evaluates trading performance of models.
    
    Uses trading simulation to score models based on:
    - Win rate
    - Profit factor
    - Total P&L
    - Number of trades
    """
    
    def evaluate(self, y_true: np.ndarray, y_pred: np.ndarray,
                 prices: np.ndarray) -> Dict[str, Any]:
        """
        Evaluate predictions using trading simulation.
        
        Args:
            y_true: True labels
            y_pred: Predicted labels
            prices: Price series
            
        Returns:
            Dict with score, win_rate, profit_factor, total_pnl, num_trades
        """
        return self.evaluate_trading_performance(y_true, y_pred, prices)
    
    def evaluate_trading_performance(self, y_true: np.ndarray, y_pred: np.ndarray,
                                     prices: np.ndarray) -> Dict[str, Any]:
        """
        Simulate trades and calculate performance metrics.
        
        Assumes going long on BUY signals and exiting at next candle.
        
        Args:
            y_true: True labels
            y_pred: Predicted labels
            prices: Price series
            
        Returns:
            Dict with trading metrics
        """
        if len(y_true) != len(y_pred) or len(y_pred) != len(prices):
            logger.warning(f"Length mismatch: y_true={len(y_true)}, y_pred={len(y_pred)}, prices={len(prices)}")
            return {'score': 0, 'win_rate': 0, 'profit_factor': 0, 'total_pnl': 0, 'num_trades': 0}
        
        trades = []
        
        for i in range(len(y_pred) - 1):
            signal = y_pred[i]
            entry_price = prices[i]
            exit_price = prices[i + 1]
            
            if signal == CLASS_BUY:  # BUY signal → long position
                pnl_pct = (exit_price - entry_price) / entry_price
                trades.append(pnl_pct)
            elif signal == CLASS_SELL:  # SELL signal → short position
                pnl_pct = (entry_price - exit_price) / entry_price
                trades.append(pnl_pct)
        
        num_trades = len(trades)
        
        if num_trades == 0:
            return {'score': 0, 'win_rate': 0, 'profit_factor': 0, 'total_pnl': 0, 'num_trades': 0}
        
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]
        
        win_rate = len(wins) / num_trades if num_trades > 0 else 0
        total_pnl = sum(trades)
        
        gross_profit = sum(wins) if wins else 0.0001
        gross_loss = abs(sum(losses)) if losses else 0.0001
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999
        
        # Score: profit_factor 50%, win_rate 30%, total_pnl 20%
        pf_normalized = min(profit_factor, 3.0) / 3.0
        score = (pf_normalized * 0.5) + (win_rate * 0.3) + (min(total_pnl, 1.0) * 0.2)
        
        return {
            'score': score,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_pnl': total_pnl,
            'num_trades': num_trades
        }
    
    def calculate_class_weights(self, y: np.ndarray) -> Dict[int, float]:
        """Calculate class weights for imbalanced datasets."""
        if len(y) == 0:
            return {0: 1.0, 1: 1.0, 2: 1.0}
        
        unique, counts = np.unique(y, return_counts=True)
        total = len(y)
        
        weights = {}
        for cls, cnt in zip(unique, counts):
            weights[int(cls)] = total / (len(unique) * cnt)
        
        return weights
    
    def cross_validate_models(self, X: np.ndarray, y: np.ndarray,
                              models: List[Any], cv: int = 5) -> Dict[str, Dict]:
        """
        Cross-validate multiple models.
        
        Args:
            X: Features
            y: Labels
            models: List of model instances to test
            cv: Number of folds
            
        Returns:
            Dict of model_name -> metrics
        """
        from sklearn.model_selection import cross_val_score
        
        results = {}
        
        for model in models:
            name = model.__class__.__name__
            try:
                scores = cross_val_score(model, X, y, cv=cv, scoring='f1_weighted')
                results[name] = {
                    'mean_f1': float(np.mean(scores)),
                    'std_f1': float(np.std(scores)),
                    'scores': scores.tolist()
                }
            except Exception as e:
                logger.warning(f"Cross-validation failed for {name}: {e}")
                results[name] = {'error': str(e)}
        
        return results
    
    def calculate_sharpe_ratio(self, returns: List[float], risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio from returns."""
        if not returns or len(returns) < 2:
            return 0.0
        
        returns_arr = np.array(returns)
        excess_returns = returns_arr - risk_free_rate / 252  # Daily risk-free rate
        
        if np.std(excess_returns) == 0:
            return 0.0
        
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
    
    def calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """Calculate maximum drawdown from equity curve."""
        if not equity_curve:
            return 0.0
        
        peak = equity_curve[0]
        max_dd = 0.0
        
        for value in equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        
        return max_dd


# Global singleton
trading_evaluator = TradingEvaluator()


def evaluate_trading_performance(y_true: np.ndarray, y_pred: np.ndarray,
                                  prices: np.ndarray) -> Dict[str, Any]:
    """Convenience function for trading evaluation."""
    return trading_evaluator.evaluate_trading_performance(y_true, y_pred, prices)


__all__ = [
    'TradingEvaluator',
    'trading_evaluator',
    'evaluate_trading_performance'
]