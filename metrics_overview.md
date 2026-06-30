Audit how win rate and performance metrics are currently calculated in the trading system.

1. Determine the source of the reported win rate:

   * Is it based on training data, validation data, backtesting, or live (forward) trades?
   * Clearly separate and label each type if multiple exist.

2. Implement clear performance tracking for live/forward trades:

   * Record each executed trade with:

     * timestamp
     * signal (BUY/SELL)
     * entry price
     * exit price
     * profit/loss (% and absolute)
   * Calculate live-only:

     * win rate
     * average win size
     * average loss size
     * profit factor (total profit / total loss)
     * total number of trades

3. Ensure separation of metrics:

   * Training/validation metrics must NOT be mixed with live performance
   * Backtest results must be clearly labeled and stored separately
   * Dashboard should explicitly distinguish:

     * Training metrics
     * Backtest metrics
     * Live trading metrics

4. Add safeguards:

   * Do not report win rate without corresponding trade count
   * Do not display performance metrics if sample size is too small (configurable threshold, e.g. < 30 trades)

5. Update dashboard:

   * Display live performance metrics clearly
   * Include trade count and timeframe
   * Ensure metrics reflect only completed trades

Goal: eliminate ambiguity so all reported performance metrics accurately reflect real trading outcomes, not training or simulated results.

