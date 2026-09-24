import numpy as np

from src.ai.ensemble import EnsemblePredictor
from src.ai.evaluation import TradingEvaluator


def test_vote_threshold_uses_ceiling_without_fallback():
    ensemble = EnsemblePredictor()
    result = ensemble._predict_3class([2, 2, 0], {}, 3)
    assert result['prediction'] == 1
    assert result['action'] == 'HOLD'


def test_three_class_vote_is_detected_without_rf_model():
    ensemble = EnsemblePredictor()
    result = ensemble.predict({'gb': 2, 'ridge': 2, 'mlp': 0}, {}, rf_model=None, product_id='')
    assert result['prediction'] in (0, 1, 2)
    assert result['prediction'] != 0 or result['action'] != 'BUY'


def test_trading_evaluation_uses_prediction_horizon():
    evaluator = TradingEvaluator()
    prices = np.array([100.0] * 24 + [102.0])
    y_true = np.array([2] * len(prices))
    y_pred = np.array([2] * len(prices))
    result = evaluator.evaluate_trading_performance(y_true, y_pred, prices, horizon=24)
    assert result['num_trades'] == 1
    assert result['total_pnl'] == 0.02
