# Trough-Confirmed BTC Entry Plan

> **For Hermes:** Implement only after Paul approves this plan. Use the crypto-trader and project-development workflows.

**Goal:** Prevent a BUY from firing while price is still falling by requiring an ATR-scaled trough-and-rebound confirmation before entry, without changing the hard no-realised-loss rule for selling.

**Architecture:** Keep the existing AI signal as the directional candidate, but add a deterministic entry confirmation gate immediately before position sizing/order execution. The gate will identify a recent local low from canonical hourly candles, then require a confirmed rebound above that low by an ATR-scaled amount and at least one completed candle/price confirmation. Pending setup state should be persisted so a restart cannot forget that a candidate is waiting for confirmation.

**Tech Stack:** Python, pandas, SQLite/SQLAlchemy database layer, existing `calculate_atr()` helper, Coinbase/multi-source pricing, pytest.

---

## Investigation findings

- The relevant live BTC trade was trade **211**, bought on **2026-09-24 08:18:31 UTC**.
- The engine validated a BTC BUY at about **£63,747.36** at 08:17 and logged **97.0% confidence**.
- The order filled/fell back at **£63,690.11** after a Coinbase request timeout and roughly 70 seconds of order handling.
- The hourly BTC market data then recorded a low of **£62,900.77** at 10:00, so the entry was about **1.25% above that later low**. The available data shows the user's observation is directionally correct: the BUY happened before the trough was confirmed.
- Current entry validation rejects BUYs in a detected `downtrend`, but a `neutral` or recovering regime can still pass while price is making lower lows. Regime classification is not a trough detector.
- ATR is currently used in the exit path (`trading_engine.py`) to widen the trailing stop. ATR is also used in model labels, but there is no ATR-based entry confirmation gate.
- Existing scale-in logic already requires a BUY signal, a discount, and confidence, but it is only for an already-open position and does not protect the initial BUY.
- The order log also exposes a separate deployment/operational concern: after a timeout, the running container still fell back to a synthetic `sdk_order_*` ID and market price. This must be verified against the current source before any entry change is deployed; a delayed or duplicate order is a different risk from buying before the trough.

## Proposed entry rule

Do not attempt to predict the exact lowest tick. Require evidence that selling pressure has stopped:

1. AI action is BUY and passes the existing raw-confidence/regime checks.
2. Build a canonical hourly OHLC window for the product.
3. Identify a candidate trough as the lowest low in a configurable lookback window, excluding the still-forming candle.
4. Require the latest completed candle to show a rebound from that trough by:
   `rebound_required = max(ENTRY_TROUGH_ATR_MULTIPLIER * ATR / price, ENTRY_TROUGH_MIN_REBOUND_PCT)`.
5. Require confirmation that is not merely one price spike. The preferred default is either:
   - two consecutive completed closes above the trough confirmation level; or
   - one completed bullish candle whose close is above the prior candle high and the rebound threshold.
6. Require the current multi-source consensus price to remain above the confirmation level immediately before order placement.
7. Expire a pending candidate after a configurable number of hours or if price makes a new lower low by more than an ATR-scaled invalidation amount.
8. If the gate fails, log `ENTRY WAIT` and retain no order side effect. The next cycle may confirm the setup after the price has bounced.

This deliberately enters after some recovery rather than attempting to buy the exact bottom. The trade-off is a potentially higher entry price in exchange for avoiding an entry while the trough is still forming. ATR should define the required confirmation distance, not be used as a claim that the exact bottom is knowable.

Initial parameters to backtest before setting production defaults:

- `ENTRY_TROUGH_LOOKBACK_HOURS`: 6, 12, and 24 candidates.
- `ENTRY_TROUGH_ATR_MULTIPLIER`: 0.5, 0.75, and 1.0.
- `ENTRY_TROUGH_MIN_REBOUND_PCT`: 0.30%, 0.50%, and 0.75%.
- `ENTRY_TROUGH_CONFIRMATION_CLOSES`: 1 versus 2 completed closes.
- `ENTRY_TROUGH_EXPIRY_HOURS`: 6 or 12.

Do not hard-code £62,000/£63,000 thresholds; BTC and each other pair need percentage/ATR-relative thresholds.

---

## Implementation tasks

### Task 1: Add a pure trough-confirmation helper

**Files:**
- Create: `/projects/crypto-trader-bot/src/entry_confirmation.py`
- Test: `/projects/crypto-trader-bot/tests/test_entry_confirmation.py`

Implement a side-effect-free function accepting completed OHLC candles, current consensus price, ATR, and configuration. It should return a structured decision containing `confirmed`, `candidate_low`, `confirmation_level`, `reason`, `atr_pct`, and candle timestamps. It must reject insufficient data, malformed/non-positive prices, still-forming candles, and lower-low invalidation.

Use the existing `calculate_atr()` semantics and document why the helper waits for a rebound instead of trying to forecast the exact bottom.

### Task 2: Add configuration constants

**Files:**
- Modify: `/projects/crypto-trader-bot/config/settings.py`

Add named settings for the lookback, ATR multiplier, minimum rebound, confirmation closes, candidate expiry, and invalidation buffer. Keep defaults conservative and make them environment/config driven only if that matches the existing settings convention.

### Task 3: Persist pending entry setups

**Files:**
- Modify: `/projects/crypto-trader-bot/src/database.py`
- Create: `/projects/crypto-trader-bot/migrations/add_entry_setups.py` (or the project's established migration location)
- Test: `/projects/crypto-trader-bot/tests/test_entry_setup_persistence.py`

Add an idempotent table or equivalent record keyed by `product_id`, containing candidate low/time, confirmation level, first-seen time, last-seen time, status, and invalidation reason. Ensure only one active setup exists per product and that stale setups expire safely.

### Task 4: Gate initial BUY execution

**Files:**
- Modify: `/projects/crypto-trader-bot/src/trading_engine.py`
- Test: `/projects/crypto-trader-bot/tests/test_trading_engine_entry_gate.py`

Call the helper only for initial BUY signals, after the existing signal/regime validation and before live/paper order execution. Do not apply it to sells, trailing stops, or the hard break-even guard. Use the same multi-source consensus price used for other execution decisions. On rejection, return no order and write a clear reason to the log/cache. On confirmation, attach the confirmation metadata to `entry_reason` and the position record for later performance analysis.

The gate must remain active in both paper and live trading so paper results are comparable with live behavior.

### Task 5: Add historical replay/backtest comparison

**Files:**
- Create or extend: `/projects/crypto-trader-bot/tools/backtest_entry_confirmation.py`
- Test: `/projects/crypto-trader-bot/tests/test_entry_confirmation_backtest.py`

Replay historical hourly BTC-GBP (then all active GBP pairs) over a representative period. Compare current behavior with each candidate parameter set using:

- entry-to-subsequent-low adverse excursion;
- entry-to-first +1.7% move rate within 24 hours;
- percentage of candidate BUYs delayed/rejected;
- average entry slippage versus the later trough;
- false confirmation rate where price makes a new lower low after confirmation;
- trade count and fees.

Do not optimise only for buying closer to the absolute low: include the existing exit hurdle and no-loss policy in the evaluation.

### Task 6: Verify the live container before deployment

**Files:**
- Inspect: `/projects/crypto-trader-bot/src/coinbase_api.py`
- Inspect: `/projects/crypto-trader-bot/docker-compose.yml`
- Inspect: `/projects/crypto-trader-bot/src/startup.py`

Before deployment, confirm the running container contains the current order-ID/fill-verification code. The 2026-09-24 log still shows timeout fallback to a synthetic order ID and market-price fallback, which conflicts with the documented fixed behavior. Resolve that discrepancy separately or block live deployment until it is understood. A trough gate must not be used to mask order-placement uncertainty.

### Task 7: Deploy safely and monitor

After approval and tests:

1. Create a git backup commit before source changes, per project policy.
2. Run unit tests and the historical replay.
3. Deploy source with `docker cp` rather than a full Pi rebuild where possible.
4. Restart the container and verify health/API status.
5. Confirm logs contain `ENTRY WAIT`/`ENTRY CONFIRMED` decisions and no orders are placed on rejected setups.
6. Keep live trading conservative or paper-only until at least two weeks of entry-confirmation outcomes are recorded.

---

## Verification commands

```bash
cd /projects/crypto-trader-bot
pytest -q tests/test_entry_confirmation.py tests/test_entry_setup_persistence.py tests/test_trading_engine_entry_gate.py
python3 tools/backtest_entry_confirmation.py --product BTC-GBP --lookback-days 60
python3 -m compileall -q src config

docker exec crypto-trader-bot python3 -c "from src.entry_confirmation import confirm_trough_rebound; print('entry helper import: OK')"
curl -fsS http://localhost:8000/api/status

docker logs --tail 200 crypto-trader-bot | grep -E 'ENTRY (WAIT|CONFIRMED)|health|error'
```

Expected results: unit tests pass; replay prints a parameter comparison with counts verified from parsed data; source compiles; the helper imports inside the running image; the API responds successfully; rejected BUY candidates produce no order-placement log.

## Risks and trade-offs

- No algorithm can know the exact future low. Waiting for confirmation reduces premature entries but can miss part of the rebound.
- Requiring two completed closes is safer but may reduce trade frequency substantially; backtest one-close versus two-close before choosing.
- A candle-based rule can be late during a fast V-shaped recovery. The consensus-price check prevents stale candle confirmation but does not eliminate latency.
- ATR is a volatility measure, not a direction predictor. The AI remains responsible for direction; the new rule only confirms price action.
- Persisted setup state adds migration and concurrency complexity. Use a unique product key and transaction-safe upsert so the trading loop and API workers cannot create duplicates.
- Existing model labels target a 1.7% move over 24 hours. The entry confirmation should be evaluated against that same economic hurdle, not a generic accuracy score.

## Acceptance criteria

- A BUY is never sent directly from an AI signal unless the trough-confirmation helper returns `confirmed=True`.
- A falling sequence with a lower low after the candidate is rejected or remains pending.
- A trough followed by the configured ATR-scaled rebound and completed-close confirmation is accepted.
- Sells, trailing-stop behavior, break-even protection, and scale-in policy remain unchanged.
- The BTC replay demonstrates the effect on the observed 2026-09-24 pattern and reports the trade-off in delayed entry versus avoided adverse excursion.
- Live logs and position records show why each BUY was waited, confirmed, or expired.
