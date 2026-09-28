# Trading Pipeline and Engine Full Review Remediation Plan

> **For Hermes:** This plan is review-first and modular. Do not implement until Paul approves the first module. After every verified module, stop for review confirmation. Never place a live order, retrain live models, alter live settings, or mutate trading/database state as part of tests.

**Goal:** Audit and repair the complete crypto-trader execution pipeline from market data and model signal through risk validation, order placement, verified fills, durable position lifecycle, restart reconciliation, and feedback logging.

**Architecture:** Keep the trading loop, API workers, WebSocket callback, Coinbase adapter, risk manager, and SQLite state machine as separate components, but give them explicit contracts at every boundary. State-changing success requires durable read-back; unavailable account/price/order data must fail closed; ambiguous orders must be reconciled by order ID rather than retried or treated as failed.

**Hard invariants:**

- Never sell below fee-inclusive break-even.
- Never claim an order filled without verified Coinbase fill size, price, status, and fees.
- Never close a database position for an unverified order.
- Never size or place a live order using paper portfolio values, stale prices, wallet quantities as prices, or unavailable account data.
- Never allow concurrent exit paths to submit duplicate sells.
- Never replace an existing cost basis with the current market price merely because FIFO data is unavailable.
- Never treat a missing/stale cache, heartbeat, migration, model, or account response as valid empty data.

---

## Review scope and current verified baseline

Reviewed read-only:

- `/projects/crypto-trader-bot/src/trading_loop.py`
- `/projects/crypto-trader-bot/src/trading_engine.py`
- `/projects/crypto-trader-bot/src/coinbase_api.py`
- `/projects/crypto-trader-bot/src/risk_manager.py`
- `/projects/crypto-trader-bot/src/balance_manager.py`
- `/projects/crypto-trader-bot/src/database.py`
- `/projects/crypto-trader-bot/src/websocket_client.py`
- `/projects/crypto-trader-bot/src/startup.py`
- `/projects/crypto-trader-bot/src/api_worker.py`
- `/projects/crypto-trader-bot/src/cache_manager.py`
- `/projects/crypto-trader-bot/src/ai_model.py`
- `/projects/crypto-trader-bot/src/ai/`
- `/projects/crypto-trader-bot/src/data_collector.py`
- `/projects/crypto-trader-bot/src/feature_engineering.py`
- `/projects/crypto-trader-bot/config/settings.py`
- `/projects/crypto-trader-bot/migrations/`
- `/projects/crypto-trader-bot/tests/`
- `/projects/crypto-trader-bot/docker-compose.yml`

Known fixes confirmed present and not to regress:

- SDK success-response order ID extraction handles dict/object responses.
- Coinbase `OPEN` orders are rechecked rather than blindly retried.
- Unverified fills do not become market-price pseudo-fills.
- Sell paths verify order success before closing positions.
- Break-even guard applies to AI SELL, trailing, and emergency exits.
- Atomic exit claims exist for cycle/WebSocket trailing exits.
- Sell size is capped to verified wallet inventory.
- Signal cache writes use atomic replacement.
- Raw versus adjusted confidence is preserved.
- Exit-aligned labels and 24-hour prediction horizons are implemented.
- Chronological training/evaluation and leakage fixes are present.
- Manual close and resync have recent fail-closed tests.

The container currently runs the existing suite successfully. Existing sklearn/joblib compatibility and deprecation warnings remain separate maintenance items.

---

# Findings requiring remediation

## CRITICAL

### F1 — Restart sell reconciliation reads the Coinbase response at the wrong level

**Evidence:** `src/trading_engine.py` pending-sell recovery reads `get_order(order_id)` fields as if `success`, `size`, `price`, and `fees` are top-level. `src/coinbase_api.py:get_order()` returns raw response data with normalized order fields normally nested under `response['order']`; `_normalise_order_fill()` is not applied at the recovery boundary.

**Failure scenario:** A sell fills while the process is down. On restart, recovery sees no top-level fill and refuses to reconcile, leaving a filled sale as `sell_pending` and disabling trading.

**Required contract:** Normalize every order response before lifecycle decisions. Recovery must verify status, exact filled size, average price, fees, and order ID before closing the position.

### F2 — Manual close races cycle/WebSocket exits

**Evidence:** `src/api_worker.py:close_position()` reads the position and submits a sell before claiming it. `src/database.py:claim_open_position_for_exit()` exists, but the endpoint does not use it. The engine and WebSocket paths use the claim mechanism.

**Failure scenario:** Manual close, scheduled monitoring, and WebSocket trailing can submit multiple sells for one position before any path persists closure.

**Required contract:** Every exit path must atomically claim the same durable position state before order submission, persist order ID as `sell_pending`, and use one reconciliation state machine.

---

## HIGH

### F3 — Live validation can use paper portfolio risk state

**Evidence:** `src/trading_engine.py:_validate_signal()` calls `risk_manager.should_pause_trading()` without the actual mode. `src/risk_manager.py` defaults portfolio-risk checks to paper mode.

**Failure scenario:** Live wallet/risk conditions differ from the simulated portfolio, allowing an order that should be blocked.

**Fix:** Thread `self.paper_trading` through every portfolio/risk check and fail closed if live account or price data is unavailable.

### F4 — Live portfolio-value failure falls back to fictitious paper capital

**Evidence:** `src/risk_manager.py` catches live account/price failures and assigns `settings.PAPER_TRADING_PORTFOLIO_VALUE` when the portfolio value is zero.

**Failure scenario:** Coinbase outage or incomplete prices produce a nonzero live order size based on imaginary paper funds.

**Fix:** Return typed `risk_data_unavailable` with size zero in live mode. Never substitute paper capital for live capital.

### F5 — Initial wallet sync creates or closes positions with invalid prices

**Evidence:** `src/trading_engine.py:217-278` allows missing `current_price` to flow into a £1 valuation fallback and ultimately uses `wallet_balance` as an `entry_price` fallback.

**Failure scenario:** A valid wallet balance is classified as dust, or a crypto quantity becomes a GBP entry price, corrupting break-even, trailing, and P&L.

**Fix:** Require fresh positive prices for every nonzero wallet balance. Abort the entire sync without writes when required prices are missing/stale/malformed.

### F6 — Scale-in persistence ignores verified fill quantity and price

**Evidence:** `src/trading_engine.py:1010-1034` computes weighted entry and total size from requested scale-in size and the pre-order quote, checking only `success`.

**Failure scenario:** Rounding, slippage, or partial fill leaves DB size/cost basis different from Coinbase inventory.

**Fix:** Require verified fill size/price/fees; represent partial fills as pending; calculate weighted cost from actual fills; update memory only after durable DB success.

### F7 — Ambiguous entry orders are not durably tracked

**Evidence:** `src/coinbase_api.py` can return `success=False` with an order ID for an unverified order. `src/trading_engine.py:810-812` discards it and does not create a pending entry state.

**Failure scenario:** Coinbase accepted a BUY but the response timed out. The next cycle submits another BUY because no durable pending entry blocks it.

**Fix:** Persist submitted entry orders as pending before/atomically with execution state, reconcile by order ID on startup/cycle, and block duplicate entries while unresolved.

### F8 — BalanceManager fails open on unavailable account data

**Evidence:** `src/balance_manager.py:86`, `:119-133`, and exception paths return `trading_allowed=True` / `should_trade=True` after account failures.

**Failure scenario:** A caller relying on BalanceManager proceeds with an unknown or zero balance.

**Fix:** Return explicit unavailable state and `should_trade=False` on account failure. Separate valid zero from unavailable.

### F9 — Legacy order fallback can duplicate an ambiguous Advanced Trade order

**Evidence:** `src/coinbase_api.py:1241-1332` falls from REST/SDK failure into `_place_legacy_order()` in some exception/permission paths.

**Failure scenario:** Advanced Trade accepted an order but verification failed; legacy fallback submits a second order.

**Fix:** Only use legacy fallback for a proven, pre-submission capability/configuration failure. Never fall through after ambiguous transport/order outcomes.

### F10 — Startup migrations can be skipped or partially fail

**Evidence:** `src/startup.py:37-56` uses nonblocking lock and continues after migration exceptions. Several migration helpers suppress all ALTER errors. One migration hardcodes `/app/data/trades.db`.

**Failure scenario:** The service starts against a partially migrated or wrong database and fails later in trading/reconciliation.

**Fix:** Blocking lock with timeout, migration version/checksum table, abort on required migration failure, configured DB path, and explicit duplicate-column classification.

### F11 — Health/status claims success without real trading-process liveness

**Evidence:** `/api/status` derives `trading_process` from the persisted `trading_active` flag. `/api/health` always returns healthy. Missing/unreadable `last_cycle.txt` becomes current time in `cache_manager.py`.

**Failure scenario:** The trading subprocess is dead or hung while dashboard/Docker reports healthy and fresh.

**Fix:** Publish process PID/liveness, heartbeat age, cycle-in-progress, last cycle result, and degraded/unavailable states. Missing heartbeat must not become `now`.

### F12 — Retraining is process-local and model replacement is non-atomic

**Evidence:** `src/api_worker.py` uses module-local retrain status/lock under Gunicorn. `src/ai/models.py` writes joblibs directly.

**Failure scenario:** Two workers or scheduler/manual retraining overwrite the same model set; trading loads a mixed generation or truncated file.

**Fix:** Inter-process retrain lock, versioned staging directory, validate every model/scaler, atomic generation switch, durable SQLite retrain status.

### F13 — Cache failures become valid empty/success data

**Evidence:** `cache_manager.py:read_signal_cache()` returns `{}` on read/JSON failure; write failures are swallowed. `/api/models/status` returns success with zero models on exception.

**Failure scenario:** Disk, permissions, stale cache, or corruption displays “no signals/no models” as a valid state.

**Fix:** Validate schema/timestamp/age and return unavailable/stale. Propagate write failures. Never return success with synthetic zero models.

### F14 — Resync success is not read-back verified and omits wallet-only holdings

**Evidence:** `src/api_worker.py:1938-1993` ignores `save_open_position()` results and reads only DB positions, not wallet-only assets.

**Failure scenario:** A failed write is reported as reconciled; manual wallet holdings remain untracked.

**Fix:** Reconcile wallet ∪ DB, classify wallet-only/DB-only/matched/unavailable, validate all data before mutation, check every write and exact read-back.

### F15 — Entry position persistence can fail after a confirmed fill without durable recovery

**Evidence:** `src/trading_engine.py:769-791` returns after `save_open_position()` failure, while the order already filled. No pending entry record is created.

**Failure scenario:** Wallet has a real new position but DB does not; future sells, cost basis, and reconciliation become ambiguous.

**Fix:** Persist an order/entry pending record before order submission and reconcile filled-but-unpersisted entries on startup.

---

## MEDIUM / LOW

### F16 — Database close transition is not conditional on claim/status

**Evidence:** `src/database.py:1529-1559` closes by position ID without requiring `sell_pending` and matching claim/order ID.

**Fix:** Conditional atomic transition requiring expected lifecycle state and claim identity.

### F17 — Signal-generation exception can be masked by an unbound `signals`

**Evidence:** `/api/models/generate_signals` writes `signals` in a finally/cleanup path even when initialization fails first.

**Fix:** Initialize before try; preserve original exception; write cache only for valid generated data.

### F18 — WebSocket callback errors and stale prices are not observable enough

**Evidence:** `src/websocket_client.py` invokes callbacks directly, catches broad failures, stores prices without timestamps, and exposes only connection boolean.

**Fix:** Per-product timestamps/sequence, stale rejection, callback failure counters, reconnect generation, bounded callback queue.

### F19 — Settings overrides accept unsafe values silently

**Evidence:** `config/settings.py` and API settings writes convert/persist values without unified range validation/read-back/versioning.

**Fix:** Typed bounds validation, transactional reject, read-after-write, settings generation visible to trading process.

### F20 — HOLD evaluation uses a different economic hurdle

**Evidence:** `src/database.py` uses the 1.7% hurdle for BUY/SELL but ~0.5% for HOLD evaluation.

**Fix:** One shared execution-derived evaluation policy, or explicitly documented HOLD tolerance with boundary tests.

### F21 — Per-model confidence is not the predicted-class probability

**Evidence:** `src/ai/signals.py` uses `max(p)`; `src/ai/base.py` logs fixed class index 2.

**Fix:** Map probability through model class labels and record predicted-class probability plus directional probabilities.

### F22 — Ensemble aggregation depends on dictionary insertion order

**Evidence:** `src/ai/ensemble.py` zips `probas.keys()` with positional votes.

**Fix:** Iterate canonical model names or `predictions.items()` and fetch matching probabilities by name.

### F23 — HistGradientBoosting internal early stopping is not chronological

**Evidence:** `src/ai/training.py` uses `early_stopping=True` and default validation fraction inside a time-series pipeline.

**Fix:** Disable internal random validation or provide explicit chronological validation outside the estimator.

### F24 — ATR class-presence check uses held-out data

**Evidence:** `src/ai/training.py` checks class presence on full labels before scoring training-prefix slices.

**Fix:** Validate class presence independently on exact training/validation partitions.

---

# Modular remediation plan

Each module is independently reviewable and deployable. Do not start the next module until the previous one is tested, deployed to the running container, verified, committed, and approved.

## Module 0 — Reproducible pipeline review harness

**Goal:** Make safety failures testable without exchange calls.

**Files:**

- Create `tests/test_trading_pipeline_contracts.py`
- Create `tests/fakes/coinbase.py` if needed
- Add fixtures for raw/typed Coinbase order responses, unavailable account/price data, and SQLite lifecycle state.

**Acceptance:** Test helpers can simulate filled/open/cancelled/partial/ambiguous orders and run without live credentials.

**Verification:**

```bash
docker exec crypto-trader-bot python3 -m pytest -q /app/tests/test_trading_pipeline_contracts.py
```

**Review gate:** Stop for approval.

## Module 1 — Fail-closed account/price/risk boundary

**Fixes:** F3, F4, F5, F8, F19.

**Files:**

- `src/trading_engine.py`
- `src/risk_manager.py`
- `src/balance_manager.py`
- `src/data_collector.py`
- `config/settings.py`
- Tests for live-mode risk, missing prices, missing accounts, and invalid settings.

**Acceptance:** Live mode never sizes from paper values, wallet quantity never becomes price, and account/price failures produce explicit unavailable/size-zero results.

## Module 2 — Durable order state and reconciliation

**Fixes:** F1, F7, F9, F15.

**Files:**

- `src/coinbase_api.py`
- `src/trading_engine.py`
- `src/database.py`
- `src/startup.py`
- migrations if order/entry state columns are needed.

**Acceptance:** Every submitted live order has a durable ID/state; ambiguous orders are never retried; startup reconciles nested Coinbase responses; filled entries/sells cannot remain unrepresented.

**Required tests:** restart recovery for filled/open/cancelled/partial entry and sell orders; SDK/REST dict/object response fixtures; no duplicate order on timeout.

## Module 3 — Atomic position lifecycle and all-exit serialization

**Fixes:** F2, F6, F16.

**Files:**

- `src/api_worker.py`
- `src/trading_engine.py`
- `src/database.py`
- manual-close, WebSocket, cycle, scale-in/out tests.

**Acceptance:** Manual, scheduled, and WebSocket exits share one claim/order/reconcile state machine. Scale-ins use verified fill values. Only the matching claim can close a position.

## Module 4 — Verified reconciliation and startup migrations

**Fixes:** F10, F14.

**Files:**

- `src/api_worker.py`
- `src/startup.py`
- `src/database.py`
- `migrations/`
- reconciliation tests.

**Acceptance:** Migrations block/abort correctly; resync reconciles wallet and DB in both directions, validates the full snapshot, checks writes, and reads back exact state.

## Module 5 — Process health, control acknowledgement, cache, and WebSocket freshness

**Fixes:** F11, F12, F13, F18.

**Files:**

- `src/startup.py`
- `src/trading_loop.py`
- `src/api_worker.py`
- `src/cache_manager.py`
- `src/websocket_client.py`
- model retraining modules.

**Acceptance:** Health distinguishes API health, trading-process liveness, heartbeat freshness, and degraded state. Retraining is one durable job with atomic model generation switching. Cache/WebSocket failures are explicit unavailable/stale states.

## Module 6 — Model/signal boundary correctness

**Fixes:** F17, F20–F24.

**Files:**

- `src/ai/ensemble.py`
- `src/ai/signals.py`
- `src/ai/base.py`
- `src/ai/training.py`
- `src/database.py`
- `tools/evaluate_predictions.py`
- signal/evaluation tests.

**Acceptance:** Probabilities map to predicted classes; ensemble pairing is name-based; HOLD/BUY/SELL use documented economic thresholds; all chronological training invariants are enforced.

## Module 7 — Full end-to-end pipeline drill

**Goal:** Prove the repaired state machine without live orders.

**Scenarios:**

1. Fresh BUY → verified fill → durable open position.
2. Ambiguous BUY → pending entry → restart → exactly one reconciliation outcome.
3. Trailing/WebSocket/manual concurrent SELL → one claim/order only.
4. Partial SELL → pending residual → retry/reconciliation.
5. Account outage → no sizing/order and explicit unavailable state.
6. Price outage → no sync/exit/entry using fallback price.
7. Process death → health degraded and restart reconciliation.
8. Failed migration → startup aborts visibly.

**Final verification:**

```bash
python3 -m compileall -q src tests
git diff --check
docker cp <changed-files> crypto-trader-bot:/app/
docker exec crypto-trader-bot python3 -m pytest -q /app/tests
docker restart crypto-trader-bot
curl -fsS http://localhost:8000/api/health
curl -fsS http://localhost:8000/api/status
curl -fsS http://localhost:8000/api/models/status
docker logs --since 60s crypto-trader-bot 2>&1 | grep -E 'Traceback|ERROR|Exception' || true
```

**Completion standard:** No live order is required. The suite must prove that unavailable, ambiguous, concurrent, partial, and restart states fail closed and reconcile durably.

---

## Risk and rollout rules

- Do not retrain or alter live thresholds until Modules 0–2 pass.
- Do not change exit behavior and accounting in the same commit as model changes.
- Do not use the live database for destructive tests; use an isolated SQLite fixture.
- Do not delete existing backup/model/database files.
- Deploy with `docker cp`, run the in-container suite, restart, and verify the exact affected read API after every module.
- Preserve the existing no-realized-loss guard throughout.

**Plan status:** Review complete; no production code changed. Ready to execute Module 0 after approval.