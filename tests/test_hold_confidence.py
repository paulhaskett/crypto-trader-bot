from src.ai.ensemble import EnsemblePredictor


def test_hold_agreement_is_not_action_confidence():
    ensemble = EnsemblePredictor()
    result = ensemble._predict_3class(
        [1, 1, 1],
        {
            'rf': [0.1, 0.8, 0.1],
            'gb': [0.1, 0.8, 0.1],
            'ridge': [0.33, 0.34, 0.33],
        },
        3,
    )
    assert result['action'] == 'HOLD'
    assert result['confidence'] == 0.0
    assert result['agreement'] == 1.0
