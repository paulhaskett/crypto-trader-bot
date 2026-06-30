You are a senior quantitative trading engineer.

Your task is to review and validate the implementation of a trailing stop-loss system in an automated trading bot.

The goal of the system is:
- NEVER sell at a net loss after fees
- Dynamically increase the stop price as the asset price rises
- Lock in increasing profit as price moves upward
- Trigger a sell only when price falls back to the trailing stop level

Produce a technical audit of the trailing stop logic.

1. Strategy Definition  
Clearly restate the intended behavior:
- Entry price handling  
- Fee model (buy + sell fees must be included)  
- Minimum profitable sell price  
- Trailing stop mechanism (percentage or absolute)  
- When and how the stop price updates  

2. Break-even Calculation (CRITICAL)  
Verify:
- Correct calculation of total cost basis including fees  
- Minimum sell price to avoid loss  
- Whether the stop price is EVER allowed below break-even  

3. Trailing Stop Logic Review  
Analyze:
- How the highest price is tracked  
- How the trailing stop is calculated from the peak  
- Whether the stop only moves UP (never down)  
- Whether rounding or precision errors could cause unintended sells  

4. Profit Locking Behavior  
Confirm:
- As price increases, the stop price increases accordingly  
- The system locks in profit progressively  
- No scenario exists where profit is reduced due to logic errors  

5. Sell Trigger Conditions  
Detail:
- Exact condition that triggers a sell  
- Whether it uses last price, bid price, or mark price  
- Risk of premature triggering due to spread or volatility  

6. Edge Cases  
Check:
- Rapid spikes and drops (volatile candles)  
- Fee miscalculations  
- Floating point precision issues  
- API latency or stale price data  
- Partial fills  

7. Simulation Examples (REQUIRED)  
Provide step-by-step scenarios with numbers:
- Entry price + fees  
- Price rises  
- Trailing stop updates  
- Price drops  
- Final sell outcome  

Include at least:
- One profitable trade  
- One near break-even scenario  
- One volatile spike scenario  

8. Failure Modes  
Identify where the system could:
- Sell at a loss unintentionally  
- Fail to update the stop correctly  
- Lock in less profit than expected  

9. Recommendations  
Provide concrete fixes or improvements, such as:
- Enforcing a hard floor at break-even + fees  
- Using bid price instead of last price  
- Buffer margins to avoid fee slippage  
- Improved precision handling  

Constraints:
- Be precise and mathematical where needed  
- Do not assume correctness — actively try to break the logic  
- Clearly separate confirmed behavior vs assumptions  
