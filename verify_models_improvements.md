Audit and refactor the full trading system to ensure correct ensemble evaluation, consistency, and measurable performance tracking across all models (Random Forest, Gradient Boosting, Neural Network, Logistic Regression).

1. Verify preprocessing consistency:

   * Ensure identical feature engineering is applied to all models.
   * Confirm shared transformations (returns, ATR scaling, normalization).
   * Remove any model-specific preprocessing pipelines.

2. Verify training consistency:

   * All models must use identical datasets and time-series splits (walk-forward or equivalent).
   * Ensure no leakage or divergence between model training pipelines.

3. Verify inference consistency:

   * Each model must receive identical input features.
   * Ensure all model predictions are generated BEFORE any ensemble aggregation.

4. Implement mandatory prediction logging:
   For every timestamp, store:

   * Features (X)
   * Individual model predictions (RF, GBM, NN, LR)
   * Ensemble prediction
   * Confidence scores (if available)
   * Future realized return (used later for labeling)
   * Final trade decision (BUY/SELL/HOLD if applicable)

5. Implement proper evaluation methodology:

   * Do NOT rely on accuracy or F1 as primary metrics.
   * Evaluate each model individually by simulating:

     * Profit factor
     * Precision on executed trades only
     * Expectancy per trade
     * Max drawdown
   * Evaluate ensemble as a separate trading agent using the same metrics.

6. Ensure label generation correctness:

   * Labels must be derived from future returns with a defined threshold.
   * Confirm consistency across all models.

7. Review ensemble weighting logic:

   * Identify whether RF dominance (e.g. 50%) is due to bias or performance.
   * Replace static weights with either:

     * performance-based weighting, OR
     * stacking model (meta-model trained on base model predictions)

8. If stacking is used:

   * Use Logistic Regression or simple Gradient Boosting as meta-model
   * Train meta-model on logged base model predictions
   * Ensure meta-model is evaluated strictly on out-of-sample data

Goal: transform ensemble from a black-box voting system into a fully auditable trading system where each model’s contribution to profit, risk, and decision quality is measurable and comparable.

