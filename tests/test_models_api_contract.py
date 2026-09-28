"""Contract tests for the AI models status display data.

These tests keep the browser-facing model-health contract explicit so a HOLD
signal cannot be confused with a failed model or a missing confidence value.
"""

from src.model_status import build_model_health


def test_hold_signal_exposes_consensus_and_individual_confidence():
    result = build_model_health({
        "action": "HOLD",
        "confidence": 0.0,
        "raw_confidence": 0.0,
        "rf_prediction": 1,
        "rf_confidence": 0.685,
        "gb_prediction": 1,
        "gb_confidence": 0.819,
        "ridge_prediction": 1,
        "ridge_confidence": 0.34,
        "agreement": 1.0,
    })

    assert result["confidence_kind"] == "not_actionable_hold"
    assert result["display_label"] == "HOLD consensus"
    assert result["raw_confidence"] == 0.0
    assert result["adjusted_confidence"] == 0.0
    assert result["models"]["rf"] == {
        "available": True,
        "signal": "HOLD",
        "confidence": 0.685,
        "reason": None,
    }
    assert result["models"]["gb"]["confidence"] == 0.819


def test_missing_model_is_unavailable_not_zero_confidence():
    result = build_model_health({
        "action": "HOLD",
        "confidence": 0.0,
        "raw_confidence": 0.0,
        "rf_prediction": 1,
        "rf_confidence": 0.70,
        "agreement": 0.66,
    })

    assert result["models"]["rf"]["available"] is True
    assert result["models"]["gb"]["available"] is False
    assert result["models"]["gb"]["confidence"] is None
    assert result["models"]["gb"]["reason"] == "No prediction in current signal cache"


def test_actionable_signal_exposes_raw_and_adjusted_confidence():
    result = build_model_health({
        "action": "BUY",
        "confidence": 0.84,
        "raw_confidence": 0.90,
        "rf_prediction": 2,
        "rf_confidence": 0.91,
        "gb_prediction": 2,
        "gb_confidence": 0.89,
        "ridge_prediction": 2,
        "ridge_confidence": 0.34,
        "agreement": 1.0,
    })

    assert result["confidence_kind"] == "actionable"
    assert result["display_label"] == "Adjusted confidence"
    assert result["raw_confidence"] == 0.90
    assert result["adjusted_confidence"] == 0.84
    assert result["models"]["rf"]["signal"] == "BUY"
    assert result["models"]["ridge"]["signal"] == "BUY"
