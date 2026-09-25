# SOL Fill Reconciliation Fix Implementation Plan

> **For Hermes:** Execute task-by-task with tests before production deployment.

**Goal:** Ensure Coinbase market fills are parsed from the actual response schema, failed verification never creates fake filled trades, and wallet/database state cannot leave a successfully sold position open.

**Architecture:** Add a small Coinbase order-fill normaliser used by the SDK verification path, make trade persistence conditional on verified success, repair the known SOL record from the authoritative Coinbase order, and add regression tests for both current and legacy response shapes. Keep the no-duplicate-order and never-sell-below-break-even safeguards intact.

**Tech Stack:** Python, SQLite/SQLAlchemy, Coinbase Advanced Trade REST/SDK, pytest, Docker.

---

## Context and verified incident

- Coinbase order `1d964fed-dd1c-4ad7-b4bc-9ef3df046ddb` is `FILLED`, size `0.17`, average price `91.05`, fees `0.0773925`, settled at `2026-09-25T16:06:09.744582Z`.
- The code expects `filled_base_volume` and nested `total_value`, but Coinbase returned `filled_size`, `filled_value`, and `average_filled_price`.
- `execute_live_trade()` persisted the unsuccessful verification result as a `filled` trade with size/price zero.
- Position `69ed86f8-55eb-4692-bef1-36fb75029a52` remains open while the Coinbase SOL balance is zero.

## Files likely to change

- Modify: `/projects/crypto-trader-bot/src/coinbase_api.py`
- Modify: `/projects/crypto-trader-bot/src/trading_engine.py`
- Modify: `/projects/crypto-trader-bot/src/database.py` only if the repair needs a narrowly scoped helper
- Test: `/projects/crypto-trader-bot/tests/test_coinbase_order_fills.py`
- Add: `/projects/crypto-trader-bot/scripts/reconcile_known_sol_fill.py` only if a repeatable repair script is preferable to a one-time SQL transaction
- Update: `/projects/crypto-trader-bot/AGENTS.md` after verification

## Task 1: Protect the working tree

1. Do not include generated `data/` files or `models.backup-*` in the source backup.
2. Create a source-only rollback commit or patch before edits.
3. Confirm the working tree baseline and current container image/source state.

Expected: source files are recoverable without committing generated model artifacts.

## Task 2: Add failing fill-normalisation tests

Create tests for:

1. Current Coinbase shape: `FILLED`, `filled_size`, `average_filled_price`, `total_fees`.
2. Current shape without average price: derive price from `filled_value / filled_size`.
3. Legacy shape: `filled_base_volume` and nested `total_value.value`.
4. Cancelled order: unsuccessful result.
5. Open order with no fill: unsuccessful result and no retry order placement.
6. Malformed filled order: unsuccessful result.

Run:

```bash
pytest -q tests/test_coinbase_order_fills.py
```

Expected initially: failures because the normaliser does not exist.

## Task 3: Implement the normaliser

In `src/coinbase_api.py`, add a documented helper that:

- accepts the inner Coinbase order dictionary;
- normalises status, filled size, average fill price, fees, and order ID;
- accepts both current and legacy field names;
- treats `FILLED`/positive filled quantities as verified only when size and price are positive;
- preserves `OPEN` and `CANCELLED` as non-success states;
- never substitutes the market price for a missing fill price.

Use this helper in both the initial order lookup and the `OPEN` recheck path.

Run the targeted tests and expect all to pass.

## Task 4: Prevent false filled trade persistence

In `src/trading_engine.py`:

- require `order_result.get('success') is True` before calculating P&L or saving a trade;
- return the failed result unchanged when verification fails;
- only call `save_trade()` with positive verified size/price;
- retain the existing check before `_close_position()`.

Add a regression test proving an unsuccessful result with an order ID does not create a filled trade.

## Task 5: Repair the known SOL records safely

Before changing the live database:

1. Back up `/app/data/trades.db` to a timestamped file.
2. Re-read Coinbase order `1d964fed-dd1c-4ad7-b4bc-9ef3df046ddb`.
3. Confirm SOL wallet balance remains zero.
4. In one transaction, repair position `69ed86f8-55eb-4692-bef1-36fb75029a52` using the verified fill time/price/size.
5. Replace trade `id=212` values with verified size, price, fees, and verified status.
6. Recalculate FIFO P&L only through the existing fill-accounting method; do not invent unavailable buy fees.

Do not run a broad “close all zero wallet positions” update.

## Task 6: Deploy without a slow rebuild

1. Run the complete local test suite.
2. Copy changed Python files into the running container with `docker cp`.
3. Restart the container.
4. Verify `/api/health` and `/api/status`.
5. Re-query `/api/open_positions` and `/api/recent_trades`.
6. Confirm SOL is absent from open positions and the repaired trade has nonzero verified size/price.

## Task 7: Reconciliation hardening review

Inspect whether startup-only wallet sync is sufficient. If a small safe periodic reconciliation hook already exists, extend it to detect a zero wallet balance and verify recent Coinbase sells before closing stale DB rows. Do not add an unverified automatic close path.

## Acceptance criteria

- The actual Coinbase response shape parses as a verified fill.
- A filled sell closes the position only after authoritative verification.
- Failed/ambiguous results never create `status='filled'` trades.
- The known SOL position is closed in the database using the real fill.
- The dashboard no longer shows SOL as open.
- No duplicate order is submitted during verification or recovery.
- Break-even/no-loss protections remain unchanged.
- Targeted and full tests pass; `/api/health` is healthy after deployment.
