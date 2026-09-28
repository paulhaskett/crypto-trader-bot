"""Model-health presentation helpers for the dashboard API.

This module keeps display semantics separate from trading decisions. In
particular, a HOLD has no actionable confidence, but its contributing models
can still have useful probability estimates that must remain visible.

Safety invariants:
- Never convert an unavailable model into a zero-confidence model.
- Never calculate or invent ensemble weights in browser-facing data.
- Do not alter the confidence used by the trading gate.
"""

from typing import Any, Dict, Optional


_MODEL_TYPES = ("rf", "lr", "mlp", "gb", "ridge")


def _signal_name(prediction: Any) -> Optional[str]:
    """Map the three-class model label to the operator-facing signal name."""
    if prediction is None:
        return None
    try:
        value = int(prediction)
    except (TypeError, ValueError):
        return None
    return {0: "SELL", 1: "HOLD", 2: "BUY"}.get(value)


def build_model_health(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build truthful model-health fields from one cached signal.

    ``confidence`` remains the existing ensemble field for compatibility. The
    additional fields describe whether it is actionable and expose individual
    model values without changing the trading decision.
    """
    action = signal_data.get("action", "HOLD")
    adjusted = signal_data.get("confidence", 0) or 0
    raw = signal_data.get("raw_confidence", adjusted) or 0
    actionable = action in {"BUY", "SELL"}

    models: Dict[str, Dict[str, Any]] = {}
    for model_type in _MODEL_TYPES:
        prediction = signal_data.get(f"{model_type}_prediction")
        available = prediction is not None
        models[model_type] = {
            "available": available,
            "signal": _signal_name(prediction) if available else None,
            "confidence": (signal_data.get(f"{model_type}_confidence") or 0)
            if available else None,
            "reason": None if available else "No prediction in current signal cache",
        }

    return {
        "confidence_kind": "actionable" if actionable else "not_actionable_hold",
        "display_label": "Adjusted confidence" if actionable else "HOLD consensus",
        "raw_confidence": raw,
        "adjusted_confidence": adjusted,
        "models": models,
    }
