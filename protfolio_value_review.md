Investigate a discrepancy between reported P&L and actual portfolio value.

Observed issue:

* Previous total portfolio value (GBP + crypto): £45
* Current total portfolio value: £42
* Reported P&L: +£2.40

This indicates a mismatch between profit calculations and actual portfolio valuation.

Tasks:

1. Verify how P&L is calculated:

   * Is it realized, unrealized, or combined?
   * What price source is used for valuation (per-exchange vs aggregated)?
   * Is P&L calculated per trade, per asset, or globally?

2. Audit portfolio valuation:

   * How is total portfolio value computed?
   * Are crypto holdings converted to GBP using current market prices?
   * Are all assets included (cash + crypto balances)?

3. Check for timing inconsistencies:

   * Are P&L and portfolio value using the same timestamped prices?
   * Is there lag between trade execution and valuation updates?

4. Investigate fees and costs:

   * Are trading fees deducted from P&L?
   * Are fees reflected in portfolio balances?
   * Are spread/slippage costs included anywhere?

5. Identify price discrepancies:

   * Compare prices used for P&L vs prices used for portfolio valuation
   * Check for differences between exchanges or stale data

6. Check for accounting errors:

   * Double counting or missing trades
   * Incorrect position sizing or balance updates
   * Rounding or precision issues

7. Output:

   * Clear explanation of the discrepancy
   * Breakdown of expected vs actual portfolio value
   * Identification of root cause(s)
   * Suggested fix to align P&L with true portfolio value

Goal:
Ensure that reported P&L accurately reflects real changes in total portfolio value.

