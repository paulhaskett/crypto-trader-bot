# Wallet Value and ATR Position Display Implementation Plan

> **For Hermes:** Use the project-development workflow and implement task-by-task with tests before deployment.

**Goal:** Make dashboard portfolio value reconcile with the GBP wallet when no crypto is held, and expose the same live ATR/trailing-stop inputs used by the trading engine in every open-position row.

**Architecture:** Keep Coinbase account balances as the source of truth, but convert every non-GBP fiat/stablecoin balance into GBP before summing `total_value`. Extract one shared ATR/trailing-stop calculation so the API and both trading-engine paths use the same values; return the calculation details from `/api/open_positions` and render them in the existing detail row rather than making a second browser request per position.

**Tech Stack:** FastAPI, Python, SQLAlchemy/SQLite, pandas, existing `calculate_atr()`, vanilla JavaScript/Bootstrap dashboard, pytest.

---

## Confirmed findings

- Live `/api/open_positions` currently returns zero positions.
- Live `/api/portfolio/summary` currently returns `total_value=£140.06`, `gbp_balance=£139.97`, and a `USDC` holding of `0.09098557` valued as `£0.09`.
- `src/api_worker.py:395-398` treats USD/USDC as `value = balance`, which is a USD value being labelled as GBP. It should use the USD→GBP rate in GBP display mode. This explains the current £0.09 difference; even after conversion, a tiny residual USDC balance may leave a sub-penny difference until rounded.
- The summary also uses `available` balances, while `get_account_balance('GBP')` is used for the separate GBP card. The implementation must document and consistently use the intended Coinbase balance field, and return an explicit breakdown/reconciliation value for diagnosis.
- `src/trading_engine.py:950-979` calculates live ATR over seven days with `calculate_atr(hist_df, period=settings.ATR_PERIOD)`, then derives `atr_pct`, `atr_based_stop = atr_pct * 2.5`, and capped `trailing_pct`.
- `src/api_worker.py:950-979` currently calculates the displayed stop using only the fixed/regime percentage and does not calculate ATR. Therefore the stop shown by the dashboard can differ from the stop used by the cycle engine. The WebSocket path at `src/trading_engine.py:1453-1468` also currently uses only the fixed/regime percentage, so the shared calculation must be applied carefully to avoid changing the no-loss guard or stop floors unintentionally.
- The open-positions table already has a trailing-stop detail row, making it suitable for ATR, ATR%, ATR-derived stop%, effective trailing%, and stop-distance display without adding a separate table column for every value.

## Acceptance criteria

1. With no non-GBP balances, `/api/portfolio/summary.total_value` equals the GBP balance to the API's documented precision.
2. USD, USDC, and EUR balances are converted to GBP using the same cached/current exchange-rate policy used by the summary; no balance is silently treated as GBP.
3. The API exposes enough reconciliation data to identify GBP, converted fiat/stablecoin value, crypto value, total, and rounding delta.
4. For each open position, the API returns `atr`, `atr_pct`, `atr_based_stop_pct`, `trailing_pct`, `trailing_stop`, `break_even`, `stop_distance`, and whether the stop is currently active/pending. Values use the same formula and fallback behavior as the execution path.
5. The dashboard shows the ATR and stop data in each position's detail row, with `N/A`/`-` when historical data is unavailable, and makes clear that a pending stop will not sell until the break-even guard is satisfied.
6. Existing hard invariants remain unchanged: never sell below break-even, retain minimum locked profit, retain the 5% trailing cap, and do not create duplicate data-fetch calls per position in the browser.
7. Tests cover fiat conversion, no-position reconciliation, ATR success/fallback, and frontend/API field compatibility. Live read-only API checks pass after deployment.

## Files likely to change

- Modify: `/projects/crypto-trader-bot/src/api_worker.py`
  - Fix GBP conversion for USD/USDC/EUR in `/api/portfolio/summary`.
  - Add reconciliation fields.
  - Add shared/helper-backed ATR fields to `/api/open_positions`.
- Modify: `/projects/crypto-trader-bot/src/trading_engine.py`
  - Reuse the shared ATR/trailing calculation in cycle monitoring and WebSocket monitoring, or explicitly document and test any intentional difference caused by WebSocket latency/data availability.
- Modify: `/projects/crypto-trader-bot/src/templates/dashboard.html`
  - Render ATR and stop-distance details in the existing trailing-stop row.
  - Correct the colspan/empty-row count while touching the table markup.
- Modify or create: `/projects/crypto-trader-bot/src/trailing_stop.py` (preferred new single-responsibility helper)
  - Pure calculation function accepting ATR inputs, settings, regime, entry, peak, and fees; no network or DB calls.
  - Return a typed/dict result containing `atr`, `atr_pct`, `atr_based_stop_pct`, effective trailing percentage, break-even, stop floor, minimum locked-profit floor, final stop, and activation threshold.
- Create/modify: `/projects/crypto-trader-bot/tests/test_portfolio_summary.py`
  - Unit tests for conversion and reconciliation using mocked account/rate data.
- Create/modify: `/projects/crypto-trader-bot/tests/test_trailing_stop_display.py`
  - Unit tests for the pure helper, fallback behavior, cap/floor rules, and no-loss invariants.
- Optional: `/projects/crypto-trader-bot/tests/test_dashboard_contract.py`
  - Static contract test asserting the template references every API field and preserves the empty-state markup.
- Modify: `/projects/crypto-trader-bot/AGENTS.md`
  - Record the wallet conversion root cause and the shared ATR/display invariant after implementation.

## Implementation tasks

### Task 1: Add failing tests for wallet-value reconciliation

Write tests that pass mocked accounts containing only GBP, GBP+USDC, GBP+USD, and GBP+EUR. Assert that the total is calculated in GBP, not by adding raw USD/USDC/EUR numbers. Include a test that verifies the zero-crypto/no-open-position case.

Run:

```bash
pytest -q tests/test_portfolio_summary.py
```

Expected initially: FAIL because USD/USDC are currently added 1:1 and the summary is coupled to live loaders.

### Task 2: Isolate and fix fiat/stablecoin conversion

Refactor the summary calculation into a small testable helper or inject account/rate dependencies. In GBP display mode:

```python
if currency == 'GBP':
    value_gbp = balance
elif currency in {'USD', 'USDC'}:
    value_gbp = balance * usd_gbp_rate
elif currency == 'EUR':
    value_gbp = balance * eur_gbp_rate
```

Keep display-currency behavior explicit; do not label raw USD as GBP. Return fields such as `gbp_balance`, `crypto_value`, `other_fiat_value`, `total_value`, and `reconciliation_delta` so a future discrepancy is observable.

Run the focused tests and a syntax check. Expected: all new conversion tests pass.

### Task 3: Add failing tests for a pure ATR/trailing-stop calculation

Cover:

- ATR available: `atr_pct = atr / current_price`, ATR stop percentage = `atr_pct * 2.5`.
- Effective percentage is `max(fixed, ATR-derived, regime)` and is capped at `0.05`.
- Final stop respects break-even floor and `MIN_LOCKED_PROFIT_FOR_SELL`.
- Missing/failed ATR falls back to fixed/regime settings and marks ATR unavailable rather than inventing a value.
- The break-even/no-realized-loss invariant is represented in the returned state and remains enforced by execution code.

Run:

```bash
pytest -q tests/test_trailing_stop_display.py
```

Expected initially: FAIL because the calculation is duplicated inline and the API has no ATR output.

### Task 4: Implement the shared calculation and wire execution paths

Create the pure helper in `/projects/crypto-trader-bot/src/trailing_stop.py`, with a file header and docstrings explaining why the helper is shared. Replace duplicated calculation logic in the cycle monitor and API with the helper. Update the WebSocket path to use the helper only where historical ATR data is safely available; otherwise retain its fixed/regime fallback and report `atr_available=false`. Do not move network fetching into the pure helper.

Use the existing seven-day `collect_historical_data()` and `settings.ATR_PERIOD` policy. Avoid fetching historical data more often than the current monitor/API behavior permits; if necessary, add a short per-product cache with an explicit TTL rather than multiplying Coinbase/API load.

Run:

```bash
pytest -q tests/test_trailing_stop_display.py tests/test_currency_utils.py tests/test_price_mapper.py
python3 -m compileall -q src
```

Expected: focused tests pass and no syntax errors are reported.

### Task 5: Extend `/api/open_positions`

Return, per position:

```json
{
  "atr": 0.0,
  "atr_pct": 0.0,
  "atr_based_stop_pct": 0.0,
  "trailing_pct": 0.0,
  "trailing_stop": 0.0,
  "break_even": 0.0,
  "stop_floor": 0.0,
  "stop_distance": 0.0,
  "stop_distance_pct": 0.0,
  "atr_available": false,
  "trailing_activated": false
}
```

Use `null` for unavailable ATR values rather than `0.0` where that distinction matters; keep the existing stop fields numeric for compatibility. Add a `stop_status`/`stop_note` field so the UI can explain pending break-even protection without duplicating trading logic in JavaScript.

### Task 6: Update the open positions table

In `/projects/crypto-trader-bot/src/templates/dashboard.html`, extend the existing trailing-stop detail row to show:

- `ATR: £x.xx (y.yy%)`
- `ATR stop: z.zz%`
- `Trail: z.zz%`
- `Stop: £x.xx`
- `Distance: £x.xx / y.yy%`
- `Active` or `Pending — waits for break-even`

Use safe formatting helpers for null values. Keep the main row readable and avoid widening it with another permanent column unless testing shows the detail row is insufficient.

### Task 7: Add contract and regression verification

Add a static/API contract test for the new fields and empty state. Run:

```bash
pytest -q
python3 -m compileall -q src
```

Before any deployment, create the required git backup commit according to the project workflow. Then use `docker cp` for changed Python/template files and restart the running container; do not perform a slow rebuild unless dependencies or the Dockerfile changed.

### Task 8: Verify live behavior

Run read-only checks:

```bash
curl -fsS http://localhost:8000/api/portfolio/summary
curl -fsS http://localhost:8000/api/open_positions
curl -fsS http://localhost:8000/api/status
```

Verify:

- The portfolio summary's GBP-only total equals the GBP balance.
- Any USDC/USD/EUR holding is shown with a GBP-converted value.
- The open-positions endpoint returns `positions=[]` and remains healthy when there are no positions.
- When a safe test position is present later, ATR fields match the execution calculation and the displayed stop is not above/below the intended floor incorrectly.
- Container logs contain no new ATR/API errors and the trading process remains running.

## Risks and decisions

- Coinbase account `available` versus total/hold balance must be confirmed before changing the field globally. The current discrepancy is already explained by USDC conversion, but a reserved balance could create a second discrepancy.
- Historical ATR fetching from `/api/open_positions` can add exchange/API load. Prefer a shared cache or reuse the trading engine's recent ATR result; never make the dashboard poll trigger an unbounded seven-day fetch per refresh.
- The current cycle and WebSocket stop formulas differ. The plan should converge them where possible, but must not weaken the hard break-even guard or introduce a sell below break-even.
- A zero ATR is not the same as an ATR of zero volatility. The API should distinguish unavailable data from a measured value.
- No database migration is needed unless the decision is made to persist ATR snapshots. The first implementation should calculate current display values rather than store rapidly changing market data.

## Final verification checklist

- [ ] Wallet totals reconcile in GBP with no open positions.
- [ ] Stablecoin/fiat conversion is covered by tests.
- [ ] ATR data is returned and displayed for open positions.
- [ ] Displayed stop uses the same formula/floors/cap as execution, or an intentional fallback is clearly marked.
- [ ] No-loss guard and minimum locked profit remain intact.
- [ ] Existing tests and compile checks pass.
- [ ] Live APIs and container health verified after deployment.
