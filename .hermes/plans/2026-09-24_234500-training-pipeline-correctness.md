# Training Pipeline Correctness Fix Plan

**Goal:** Correct data leakage, invalid ATR selection, horizon-mismatched evaluation, and ensemble threshold/class handling before any model retuning.

**Priority fixes:**
1. Make ATR validation use a real chronological validation slice.
2. Make RF/GB calibration train-only and calibration-only, without fitting the base model on calibration rows first.
3. Replace random/KFold validation with `TimeSeriesSplit`.
4. Remove future-filled regime and full-dataset volatility percentile features.
5. Align features and labels by timestamp index.
6. Use ceiling for vote thresholds and fail closed on mixed class mappings.
7. Make prediction evaluation use one shared exit hurdle and exact horizon prices where feasible.
8. Add regression tests for each corrected behavior.

**Files likely affected:** `src/ai/training.py`, `src/ai/features.py`, `src/data_collector.py`, `src/ai/ensemble.py`, `src/database.py`, `src/trading_engine.py`, `tools/evaluate_predictions.py`, and tests.

**Safety:** No model retrain or live parameter change until tests pass. Existing live models remain in place during implementation.
