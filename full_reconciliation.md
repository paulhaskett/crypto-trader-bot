Perform a full reconciliation between P&L and portfolio value.

Observed issue:

* P&L shows profit over time
* Total portfolio value remains unchanged

Tasks:

1. Break down P&L:

   * Separate realized vs unrealized profit
   * Identify price source used for each

2. Recalculate expected portfolio value:

   * Starting value + realized P&L + unrealized P&L - fees

3. Compare against actual portfolio value:

   * Identify exact difference

4. Verify price consistency:

   * Confirm P&L and portfolio valuation use the same aggregated price source
   * Check timestamps for alignment

5. Audit fees:

   * Confirm all trading fees are included in P&L
   * Quantify total fees over the period

6. Check trade efficiency:

   * Average profit per trade
   * Compare against average fees and spread

7. Output:

   * Exact reason portfolio value is not increasing
   * Numerical breakdown of where profit is lost or offset

Constraints:

* Do NOT modify system
* Diagnostic only

Goal:
Ensure P&L reflects real, realized growth in total portfolio value.
