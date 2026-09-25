# SOL Momentum-Consistent Trailing Exit Plan

> **For Hermes:** Implement task-by-task only after this plan is approved.

**Goal:** Prevent trailing-stop exits that contradict the bot's own uptrend and momentum signals, while preserving the no-loss guard and ensuring all exit decisions use one consistent market-data snapshot.

**Architecture:** Refactor trailing-stop monitoring so one fetched candle dataset supplies ATR, RSI, MA20, MA50, regime, and the trailing decision for a product/cycle. Extract the momentum decision into a pure, unit-testable helper. Apply the same helper to cycle-based monitoring and the WebSocket path where practical, with explicit logging of the decision inputs and reason.

**Tech Stack:** Python, pandas, pytest, Docker, existing multi-source pricer and SQLite database.

---

## Verified context

The SOL exit on 2026-09-25 was technically triggered at `£90.89 <= £90.90` and filled at `£91.05`, but:

- the regime log immediately before the exit reported `uptrend`, RSI `71.5`, and price `£91.03`;
- no momentum-protection log appeared for the exit cycle;
- the exit used a `1.2%` ATR trail, while the next cycle calculated approximately `2.6%–2.7%`;
- subsequent prices reached at least `£92.39`.

This indicates inconsistent or non-identical candle snapshots between regime, ATR, and momentum checks.

## Files likely to change

- Modify: `/projects/crypto-trader-bot/src/trading_engine.py`
- Modify: `/projects/crypto-trader-bot/src/data_collector.py` only if one-snapshot data access cannot be achieved through the existing API
- Modify: `/projects/crypto-trader-bot/src/ai/base.py` only if regime calculation must accept the already-fetched candle frame
- Test: `/projects/crypto-trader-bot/tests/test_momentum_protection.py`
- Test: `/projects/crypto-trader-bot/tests/test_trailing_stop_display.py` if shared stop calculations change
- Update: `/projects/crypto-trader-bot/AGENTS.md` with the snapshot-consistency rule and regression details
- Update: `/projects/crypto-trader-bot/requirements-dev.txt` only if new test tooling is needed; do not add runtime dependencies

## Task 1: Capture the current decision flow

1. Trace `monitor_positions()` from candle fetch through ATR, regime, momentum, AI SELL, trailing trigger, and order placement.
2. Trace `on_websocket_price()` separately.
3. Identify which calls fetch fresh candles and which use cached data.
4. Record whether the momentum check can see a different `hist_df` from the ATR/regime calculation.

Acceptance: the exact duplicate/stale-data path is documented before code changes.

## Task 2: Add pure momentum decision tests first

Create a helper contract such as:

```python
should_skip_trailing(
    current_price,
    rsi,
    ma20,
    ma50,
    peak_price,
) -> (bool, str)
```

Write failing tests for:

- RSI above 70 and price above both moving averages → skip;
- RSI exactly 70 → follow the chosen documented boundary consistently;
- RSI below 70 → do not skip for the RSI rule;
- price above only one moving average → do not claim strong uptrend;
- current price within 1% of peak → skip according to the existing protection;
- missing/NaN indicators → fail safe without claiming strong uptrend;
- an actual trailing stop below break-even remains blocked by the existing no-loss guard.

Run:

```bash
docker exec crypto-trader-bot python3 -m pytest -q /app/tests/test_momentum_protection.py
```

Expected initially: the new tests fail because the helper is not yet extracted.

## Task 3: Make one candle snapshot authoritative

Refactor the cycle-based monitoring path so each open product obtains one `hist_df` snapshot per monitoring pass and passes that same frame to:

- ATR calculation;
- RSI/MA20/MA50 momentum calculation;
- regime calculation, where the API permits;
- trailing-stop decision logging.

Do not silently fetch a second fresh dataset during the same decision. If a fresh fetch fails, use one clearly logged cached fallback rather than mixing fresh and cached indicators.

Acceptance: logs include one snapshot timestamp/age or equivalent identifier for ATR, regime, and momentum decisions.

## Task 4: Apply an explicit exit-priority order

Document and implement this order:

1. Wallet/position validity and current price.
2. Break-even/no-loss guard.
3. Momentum protection for strong uptrends.
4. Trailing-stop threshold.
5. AI SELL handling under the existing profit guard.
6. Verified order execution and close.

The momentum protection must not bypass the hard no-loss guard, and an AI SELL must not override the user's no-realized-loss policy.

The implementation must log one structured reason, for example:

```text
[TRAILING DECISION] SOL-GBP snapshot=... action=SKIP reason=strong_uptrend rsi=71.5 ma20=... ma50=... current=...
```

## Task 5: Protect the WebSocket path

Review whether real-time trailing checks have access to the same momentum indicators. If they do not, do not invent indicators from a single tick. Choose one of:

- maintain a short-lived, timestamped indicator snapshot updated by the cycle path; or
- require the cycle snapshot before applying momentum-sensitive protection; or
- use only the safe trailing/no-loss rules in the WebSocket path and let the cycle path own momentum protection.

The WebSocket path must never sell below break-even and must never use stale indicators without logging their age.

Add tests for stale/missing indicator snapshots and verify no duplicate sell is submitted.

## Task 6: Re-run historical SOL decision analysis

Create a deterministic test fixture from the 2026-09-25 SOL candle snapshot, including:

- entry `£88.09`;
- peak `£92.03`;
- trigger price `£90.89`;
- logged RSI `71.5`;
- MA20/MA50 values from the actual dataset;
- ATR values used before and after the cycle.

Expected result: the unified decision should report `SKIP: strong_uptrend` if the actual MA conditions satisfy the rule. If the dataset does not satisfy them, record that explicitly rather than forcing the expected answer.

## Task 7: Deploy and verify

1. Run the targeted momentum tests.
2. Run the full suite:

```bash
docker exec crypto-trader-bot python3 -m pytest -q /app/tests
```

3. Run compile and diff checks.
4. Copy changed source into the container with `docker cp`.
5. Restart the bot and verify `/api/health`.
6. Confirm logs show snapshot-consistent trailing decisions.
7. Do not alter or reopen the historical SOL position; it was already sold and correctly reconciled.
8. Monitor the next SOL-equivalent trailing decision before considering the fix complete.

## Acceptance criteria

- ATR, regime, and momentum use the same candle snapshot for a cycle decision.
- A strong uptrend with RSI above the defined threshold and price above MA20/MA50 produces an explicit trailing skip.
- Missing or stale indicator data cannot silently produce a false strong-uptrend decision or an unexplained exit.
- The WebSocket path remains no-loss protected and does not duplicate orders.
- Existing Coinbase fill verification and authoritative-size accounting remain intact.
- Targeted tests and the full 22-test suite pass.
- The next deployment is healthy and logs expose the reason for every skipped or triggered trailing decision.

---

# Full Trading Pipeline Audit Addendum

The following evidence-backed findings were added after a four-part review of the trading engine, market data, Coinbase transport, persistence, risk, scheduling, and control plane. They are part of this plan, not optional future ideas.

## P0 — fix before further live trading

1. **BUY direction inversion** — `src/trading_engine.py:543-545` treats prediction `2` as short although BUY=2. Derive direction from validated action and reject action/prediction mismatches.
2. **AI SELL can bypass fee-inclusive break-even** — `src/trading_engine.py:1133-1140` allows +1% while break-even is about +1.1%. Remove the independent profit escape hatch and use one shared `can_exit_without_loss()` guard.
3. **A verified market fill can still be below break-even** — cycle/WebSocket paths validate the trigger price but not the authoritative fill price plus fees. Reject or quarantine such fills and reconcile explicitly.
4. **Cycle and WebSocket can submit duplicate sells** — only the WebSocket path uses `_positions_lock`. Add an atomic database claim (`open → closing`) before any order; only the claimant may place it.
5. **WebSocket closes on partial fills** — apply the cycle path's quantity check to WebSocket and keep residual inventory open.
6. **Live sells use all wallet inventory** — `execute_live_trade()` replaces position size with the entire base-currency wallet balance. Reconcile wallet lots and sell only attributable bot inventory; fail closed when ownership is ambiguous.
7. **Account failures fabricate balances** — remove hardcoded balance fallbacks in `coinbase_api.py`; distinguish unavailable from zero and block live decisions when unavailable.
8. **Advanced credentials can silently act as paper mode** — live/paper selection checks the wrong credential set. Make transport credentials authoritative and fail startup on invalid live configuration.
9. **GBP daily-loss checks are bypassed** — risk sizing returns before `_check_daily_limits()`. Apply all risk gates before currency-specific sizing.
10. **Daily loss resets on restart** — reconstruct fee-inclusive realized P&L from verified fills using UTC risk days; trading process is the enforcement authority.
11. **Manual close only changes the DB** — route `api_worker.py` manual close through the common verified order path.
12. **Start/stop/emergency endpoints are cosmetic** — persist control state, enforce it in the trading subprocess before orders, and verify the state transition.
13. **Startup trades after failed wallet sync** — enter degraded/read-only mode until reconciliation succeeds.
14. **Closed positions remain active** — remove closed rows from `active_positions` or filter status in every count/product check.

## P1 — state, accounting, and data integrity

15. Scale-in accounting uses requested rather than verified size/price/fees; update transactionally from actual fills.
16. Scale-in mutates memory before checking the database update result; commit first and reload on failure.
17. Paper monitoring ignores weighted entry after scale-in; use one fee-aware cost-basis service in both modes.
18. Initial position persistence omits weighted-entry and lifecycle fields; add create/reload round-trip coverage.
19. Database loading converts numeric `remaining_size=0` back to original size; preserve zero and distinguish NULL/legacy unset.
20. FIFO P&L mixes paper and live fills; carry `trade_type`/portfolio through every fill and filter it.
21. `trading_engine.get_fifo_cost_basis()` excludes fees and proportionally caps lots; replace it with one exact fee-inclusive FIFO service.
22. Trade insertion and position closure are separate/non-idempotent; add `reconcile_fill(order_id)` as one transaction keyed by exchange order ID.
23. Position close stores trigger price instead of authoritative fill price; store both separately.
24. Open-position creation is check-then-insert without a unique open `(product_id, trade_type)` constraint.
25. Holdings upsert races and ignores trade type; add an atomic unique-key upsert.
26. Wallet sync overwrites verified historical basis or falls back to current price; preserve basis or mark `basis_unknown` and block P&L exits.
27. Zero-wallet sync can close valid positions during transient API failure; require a complete fresh account snapshot and verified evidence.
28. API resync can leave zero-wallet positions open and overwrite basis; make it transactional and basis-preserving.
29. WebSocket holds the lock across consensus, REST, DB, and order calls; claim under lock, perform I/O outside, commit by version.
30. WebSocket and cycle trailing economics differ: ATR/momentum in cycle, fixed regime stop in WebSocket. Centralise the decision.
31. WebSocket silently falls back to raw Coinbase ticks when consensus fails; fail closed or require bounded confirmation.
32. Consensus confidence threshold is loaded but not enforced; require minimum confidence and independent source count for execution.
33. Coinbase WebSocket and Coinbase REST are counted as independent sources; group by exchange family.
34. WebSocket quotes have no tick timestamp/TTL; store received time/session and reject stale feeds.
35. Historical cache keys ignore requested timeframe/window; store coverage metadata and reject insufficient history.
36. Historical DataFrames can be returned as scalar price fallbacks; separate caches and validate numeric finite quotes.
37. NaN/negative/infinite source prices can poison consensus; centralise quote validation.
38. A cycle has no coherent market snapshot and reuses the last product's price map for all dashboard updates; build/pass one snapshot per product.
39. Regime definitions differ across features, inference, and stored position context; implement one structured regime snapshot.
40. Ensemble trend/volatility/features can use different data revisions; pass one immutable frame to all detectors.
41. Three-class inference can silently fall back to binary based on observed votes; validate persisted model label schema.
42. REST order verification does not share the SDK state machine or bounded OPEN recheck.
43. Ambiguous POST timeouts can retry/fallback into duplicate orders; use stable client IDs and query outcome before any fallback.
44. SDK error dictionaries are parsed as objects; add dict/object accessors and retry classification.
45. Order sizing uses decimal places rather than exact increments; use Decimal increment/min/max validation and documented sell round-down.
46. Positive partial fills are currently treated as no fill; record filled quantity and residual order separately.
47. `get_orders()` passes GET query parameters as request body data; use the request `params` argument.
48. Market-data deduplication lacks a unique `(product_id,timestamp)` constraint; migrate duplicates and add an upsert.
49. Scheduler jobs are duplicated per Gunicorn worker; move them to one process or globally locked idempotent jobs.
50. Migrations run from multiple paths and swallow errors; use one versioned locked runner and fail startup on unexpected errors.
51. Trading mode is captured before DB settings load; load settings before engine construction and require guarded mode transitions.
52. Health/status can report healthy while the trading subprocess is dead; publish and verify a trading heartbeat.
53. Cycle timestamp writes are non-atomic; use temp file plus `os.replace()`.
54. Position writes have no version/updated-at protection; stale WS/API/cycle writes can overwrite newer state.
55. Trade cooldown is lost on restart; reconstruct it from verified fills.

## P2 — correctness and operational hardening

56. Non-GBP sizing can reference undefined `price_risk` (`risk_manager.py:229-243`); add explicit calculation/tests.
57. Minimum trade tiers can exceed configured maximum position size; reject when exchange minimum and risk maximum conflict.
58. Dashboard risk status is not authoritative; expose trading-process risk/reconciliation state.
59. Training coverage is not guaranteed to match requested history; paginate and record per-source coverage.
60. ATR warm-up semantics differ; unify implementation and require a full period for ATR-dependent labels/exits.
61. Model artifacts lack feature/class/timeframe/ATR/regime/calibration compatibility metadata; reject incompatible artifacts.
62. Quote provenance is dropped before execution; carry price timestamp, sources, confidence, spread, and snapshot ID.
63. Scale-out accepts arbitrary caller-supplied remaining size; validate bounded monotonic reductions and derive state from verified fills.
64. Underwater tracking uses hardcoded fees and a stale current price; pass effective fees/current price in one lifecycle transaction.
65. `execute_signal()` trusts malformed/stale externally supplied signal data; validate identity, action/prediction, confidence, finite values, size, and state at the execution boundary.
66. Empty-position monitoring can use an uninitialised price map; initialise/fetch it before the loop.

## Revised implementation order

### Phase A — Safety and state machine

Implement the P0 items first: shared fee-inclusive no-loss guard; action/direction validation; atomic position claims; one verified close path for cycle, WebSocket, and manual close; partial-fill handling; DB-result checks; idempotency by exchange order ID; closed-position cleanup; persisted risk and emergency controls. Live trading must remain disabled/degraded until the P0 regression suite passes.

### Phase B — Exchange and wallet reconciliation

Unify SDK/REST/legacy verification with bounded polling and timeout reconciliation. Remove fabricated balances and current-price cost-basis fallbacks. Correct live credential selection, Decimal increment sizing, account freshness, wallet-lot ownership, trade-type filtering, and fill-based P&L. Add recorded tests for filled/open/partial/cancelled/timeout/error responses.

### Phase C — Market snapshot and exits

Create one immutable product snapshot containing quote, freshness, independent sources, confidence, candles, ATR, RSI, moving averages, regime, and snapshot ID. Use it for signal validation, entry confirmation, cycle monitoring, WebSocket trailing decisions, and dashboard persistence. Enforce quote confidence, source-family independence, WebSocket TTL, cache coverage, finite prices, unified regime semantics, and identical ATR/momentum/trailing calculations.

### Phase D — Persistence, risk, and restart

Add unique market-data/holding/open-position constraints, versioned position writes, one transactional fill-reconciliation service, zero-size migration handling, exact FIFO with fees and trade type, scale-in/out fill accounting, persisted daily loss/cooldowns, startup fail-closed reconciliation, and authoritative dashboard risk/heartbeat state.

### Phase E — Scheduler, models, and operations

Consolidate schedulers outside Gunicorn imports, make migrations single-runner/versioned, add model artifact compatibility and training-coverage validation, make cycle timestamps atomic, and update `AGENTS.md` with the final invariants.

## Expanded verification matrix

Add tests for every P0/P1 item, especially:

- BUY direction and action/prediction mismatch;
- AI SELL below fee-inclusive break-even;
- slippage causing a verified fill below break-even;
- concurrent cycle/WebSocket close claim;
- WebSocket partial fill and residual inventory;
- manual close and emergency-stop enforcement;
- account API unavailable versus genuine zero;
- Advanced-only live credentials;
- GBP daily-loss enforcement and restart reconstruction;
- closed-position re-entry and zero remaining-size restart;
- scale-in/out rounding, fees, partial fills, and DB failure;
- paper/live FIFO separation;
- REST/SDK/legacy timeout and OPEN polling;
- Decimal increments/min/max sizing;
- low-confidence, stale, NaN, and same-exchange duplicate quotes;
- one-snapshot ATR/RSI/MA/regime/trailing decisions;
- stale cache/window coverage and model schema mismatch;
- duplicate schedulers, migration failure, stale heartbeat, and API control state.

Run after each phase:

```bash
python3 -m compileall -q src tests
git diff --check
docker exec crypto-trader-bot python3 -m pytest -q /app/tests
```

Before re-enabling live trading, verify that every close has an authoritative fill and successful DB reconciliation, every risk gate is persisted/enforced by the trading process, stale/unavailable market/account data fails closed, and the final test suite passes in the real container environment.
