Refine trend classification logic to distinguish between short-term momentum and true market structure.

Tasks:

1. Replace binary "uptrend/downtrend" classification with multi-level states:

   * strong uptrend
   * weak uptrend (recovery)
   * sideways
   * downtrend

2. Define strong uptrend as:

   * consistent higher highs and higher lows
   * price above key moving averages (e.g., 100/200 MA)

3. Define weak uptrend as:

   * short-term upward movement
   * but still below major resistance or long-term moving averages

4. Ensure trend classification is based on:

   * multiple timeframes (e.g., short-term vs medium-term)
   * not just a single indicator or timeframe

5. Output both:

   * short-term trend
   * higher timeframe trend

Goal:
Prevent misclassification of temporary rebounds as full uptrends and improve trading decision accuracy.

