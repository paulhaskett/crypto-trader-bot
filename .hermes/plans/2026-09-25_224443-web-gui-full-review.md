# Crypto Trader Web GUI and Page Review Plan

> **For Hermes:** Planning only. Do not implement until this plan is approved. Preserve the hard invariant: the UI must never imply that an order filled, a position closed, or an account balance is known when the backend has not verified it.

**Goal:** Audit and repair the dashboard, trades, performance, AI models, settings, and API control surfaces so they show authoritative state, cannot issue misleading/destructive actions, remain usable on mobile, and expose the operational information needed to diagnose trading decisions.

**Architecture:** Keep the existing FastAPI + server-rendered HTML/Bootstrap architecture for the first pass. Centralize browser helpers for escaping, fetch/error handling, request state, and destructive-action confirmation instead of duplicating inline JavaScript. Make the API the single source of truth for controls and status; do not let the browser optimistically claim that a command succeeded.

**Tech stack:** FastAPI, Jinja-served HTML, vanilla JavaScript, Bootstrap 5, Chart.js, SQLite/SQLAlchemy, Docker on Raspberry Pi.

---

## Review scope inspected

Pages:

- `/` → `src/templates/dashboard.html`
- `/trades` → `src/templates/trades.html`
- `/performance` → `src/templates/performance.html`
- `/models` → `src/templates/models.html`
- `/settings` → `src/templates/settings.html`
- `src/templates/error.html`
- `src/static/style.css`

Backend/UI contract:

- `src/api_worker.py` page routes and API routes from `/api/status` through `/api/resources`.
- Live container behavior at `http://localhost:8000`.
- Existing test suite under `tests/`.

The current runtime was reachable and healthy during review. This is a source review; no GUI code or live trading state was changed.

---

# Confirmed findings

## P0 — Controls can claim success without changing bot state

**Evidence:** `src/api_worker.py:1818-1865` returns success for `start`, `stop`, and `emergency_stop` without persisting `trading_active`, signalling the trading subprocess, or verifying a changed state. The handler itself comments that API-worker actions may not work because the trading engine is a separate process. `dashboard.html:408-420` trusts the returned `status` and updates the UI optimistically.

**Impact:** A user can click Emergency Stop and receive “Emergency stop executed” while trading may continue. Start/stop badges can revert on the next poll or, worse, display an unsafe state temporarily.

**Plan:** Build one control-command path backed by persisted state plus an inter-process stop/command mechanism. Return `202 pending` while the trading process has not acknowledged the command; return success only after reading back the authoritative state. Emergency stop must be fail-closed and idempotent. The GUI should show `Requested`, `Acknowledged`, `Failed`, and `Unknown` states rather than treating an HTTP response as execution proof.

## P0 — Settings “Paper/Live” buttons do not switch trading mode

**Evidence:** `settings.html:396-404` maps paper to `stop` and live to `start`; `api_worker.py:1818-1865` only returns a response and does not change `paper_trading`. This can stop/start activity but cannot switch mode.

**Impact:** The UI labels can say the wrong mode and a user may believe they enabled paper mode when they only stopped trading, or believe live mode is enabled when it is not.

**Plan:** Add an explicit authenticated mode endpoint with a confirmation requirement for live mode. Persist the mode, require trading to be stopped before switching, read back the mode, and display the effective mode from `/api/status`. Never use generic start/stop actions as mode switching.

## P0 — Manual close endpoint has a live-path `settings` NameError

**Evidence:** `api_worker.py:1869-1900` imports `db_manager`, `coinbase_api`, and `risk_manager`, then references `settings.MAKER_FEE_RATE` and `settings.TAKER_FEE_RATE` without importing `settings` in that function. The exception handler returns an error after the price and position have been read.

**Impact:** Live manual closes can fail before the break-even check. The page gives only a generic failure and does not explain whether Coinbase was touched.

**Plan:** Import settings explicitly, add a backend unit test for the live manual-close path, and return a typed result distinguishing `blocked_below_break_even`, `order_unverified`, `partial_fill`, `fill_below_break_even`, `database_close_failed`, and `closed`.

## P0 — GUI has no authentication, authorization, CSRF protection, or network-safety boundary

**Evidence:** All page and API routes are unauthenticated. Destructive POST routes include control, retrain, trade clearing/cleanup, settings mutation, resync, and manual close. Browser code submits POST requests without CSRF tokens or an authenticated session.

**Impact:** Anyone able to reach port 8000 can potentially stop/start the bot, retrain models, mutate risk settings, clear records, resync positions, or close positions. The emergency-stop surface is especially dangerous.

**Plan:** Add an operator-auth boundary before exposing mutation routes. At minimum: local-network binding/firewall verification, a configured bearer/session credential, role checks for read versus mutation routes, CSRF protection for browser sessions, and audit logs containing actor, action, target, request ID, result, and state read-back. Keep `/api/health` deliberately minimal and unauthenticated. Do not put credentials in page source or localStorage.

## P1 — Dashboard displays success and error states as if they were valid zero/empty data

**Evidence:** `fetchJSON()` returns `null` on HTTP failure; many callers render “Loading”, “No positions”, £0.00, or empty tables. `api_worker.py:327-329` obtains accounts, and the summary path can continue with an empty account list. `/api/status` returns `{status: "running"}` even though it does not verify the trading subprocess.

**Impact:** A Coinbase outage can look like a zero wallet, zero P&L, no positions, or a healthy bot. This is exactly the class of stale/false state that caused the SOL dashboard incident.

**Plan:** Define an API envelope with `data_status: fresh|stale|unavailable`, `as_of`, `source`, `error_code`, and `request_id`. Distinguish empty from unavailable in every card/table. Display prominent stale/unavailable banners and preserve the last known value with its timestamp instead of replacing it with zero. Make `/api/status` report trading-process liveness, last heartbeat, last successful reconciliation, and command state.

## P1 — Broad innerHTML use creates a stored/reflected XSS surface

**Evidence:** Dashboard, models, trades, and settings pages interpolate API/database values directly into `innerHTML`: product IDs, reasons, status strings, signal text, error messages, model names, and timestamps. Examples include `dashboard.html:369,615,651,668`, `models.html:251,304,359,455,487`, `trades.html:384`, and `settings.html:327,353,364`.

**Impact:** A compromised or malformed API/database value can execute script in the operator's browser. The issue is made worse by unauthenticated mutation endpoints.

**Plan:** Add a shared `escapeHtml()`/`text()` rendering helper and use DOM node creation or escaped interpolation for all data values. Keep only fixed, audited class names and icon names in HTML templates. Add a restrictive Content-Security-Policy, remove inline event handlers where practical, and add a browser test that injects `<img onerror=...>` into a mocked API response and verifies no execution/HTML interpretation.

## P1 — Dashboard retrain button calls a fake control action

**Evidence:** `dashboard.html:419-420` calls `retrainModels()`, which calls `controlBot('retrain')`; `api_worker.py:1842-1844` returns “Retrain initiated” without invoking retraining. The models page correctly calls `/api/models/retrain`.

**Impact:** The dashboard can tell the operator retraining started when nothing happened.

**Plan:** Route every retrain button to `/api/models/retrain`, use one progress polling component, disable duplicate requests, and show the actual job ID/status/result. Add a backend contract test proving a retrain request creates or reports a real job.

## P1 — Resync action can corrupt positions on account/API failure

**Evidence:** `api_worker.py:1839-1859` calls `get_account_balance()` and treats unavailable/zero results as zero, then saves an open position with wallet size and current price. It does not check `last_accounts_fetch_ok`, does not preserve the authoritative cost basis, and does not verify the resulting read-back.

**Impact:** A dashboard resync during a Coinbase outage can rewrite valid positions to zero or replace cost basis with current price.

**Plan:** Make resync a backend reconciliation job that fails closed on account or price unavailability, preserves FIFO cost basis and verified fills, records a reconciliation report, and only commits after all products pass validation. Show a preview/diff and require confirmation before applying changes.

## P1 — Model page presents derived/fallback metrics as authoritative

**Evidence:** `models.html:414-455` calculates ensemble weights in the browser from maximum win rates and falls back to equal weights. It also shows model cards based on fields that may be absent or stale. Startup logs show known incompatible USD GB models (`No module named '_loss'`).

**Impact:** Operators can read browser-derived weights that do not match execution weights, and may interpret stale or unavailable model metrics as live model health.

**Plan:** Have `/api/models/status` return authoritative model load state, model file timestamp/version, feature schema hash, training data range, calibration state, raw versus adjusted confidence, per-model availability/error, and actual ensemble weights. Display unavailable/incompatible models explicitly; never invent equal weights in the UI.

## P1 — Settings validation and units are too implicit

**Evidence:** `settings.html` sends percentages for confidence, stop loss, and max position size; the API divides by 100. Other values use decimal or seconds semantics. The API performs little range validation. Live/trading-critical settings can be posted directly without confirmation or an audit record.

**Impact:** A malformed or out-of-range request can change risk behavior. The UI does not clearly show whether a value is percent, decimal, GBP, or seconds.

**Plan:** Define typed request/response schemas with explicit units and bounds. Return normalized values and display units beside every field. Reject NaN, infinity, negative intervals, impossible thresholds, and unsafe live-risk combinations. Add a settings change preview, confirmation for safety-critical changes, audit history, and read-after-write verification.

## P1 — Manual close and emergency controls lack complete lifecycle feedback

**Evidence:** The dashboard only shows a generic toast; it does not display order ID, verified fill size/price/fees, partial-fill residual, or reconciliation-required state. `closePosition()` does not prevent duplicate clicks while the request is in flight.

**Plan:** Add an operation modal with target position, requested size, current price, break-even, expected minimum exit, and explicit confirmation. Poll the operation/order state, show authoritative fill data, keep residual positions visible, and prevent duplicate submissions with idempotency keys.

## P1 — Trade page merges incompatible data and double-counts performance

**Evidence:** `trades.html:230-384` merges `/api/recent_trades` and `/api/closed_positions` into one array. A closed position can represent the lifecycle of trades already present in the trade endpoint, causing duplicated rows, totals, win rate, and P&L. The closed-position timestamp construction assumes `date` and `time` fields, while other pages use `timestamp`.

**Plan:** Separate `fills`, `position lifecycles`, and `orders` into distinct tabs or use one backend-normalized ledger endpoint with stable IDs and explicit row types. Calculate stats server-side from authoritative verified fills/position closures; include pagination and `has_more`. Add contract fixtures for one buy + one sell + one closed position and assert no double counting.

## P1 — Performance page and dashboard P&L sources need an explicit contract

**Evidence:** Dashboard uses Coinbase `realized_pnl` when available, while trades/performance pages calculate client-side from mixed rows and raw fields. The UI labels do not consistently distinguish realized, unrealized, FIFO, fees-included, and estimated P&L.

**Plan:** Add a canonical P&L response with `realized`, `unrealized`, `fees`, `cost_basis_method`, `currency`, `as_of`, and `source`. Display those labels on every page. Remove browser-side financial aggregation except presentation formatting.

## P2 — Accessibility and mobile usability gaps

**Evidence:** Icon-only close/refresh buttons lack reliable accessible names; tables are wide and not consistently wrapped; state is communicated through color and arrows; controls rely on inline `onclick`; external font/icon assets can fail without a fallback strategy. The settings and models pages have dense tables without a mobile-specific presentation.

**Plan:** Add accessible names, keyboard focus states, `aria-live` status regions, visible text alongside color/icon state, responsive table cards or horizontal scroll labels, 44px touch targets, reduced-motion handling, and automated axe/Playwright checks at desktop and mobile widths.

## P2 — Polling and request-race behavior can overwrite newer UI state

**Evidence:** Dashboard starts several independent intervals; `updateSignals`, summary, positions, and resource requests have no AbortController or sequence guard. Slow older responses can overwrite newer data. Models retrain polling can continue after navigation or duplicate timers.

**Plan:** Centralize a request manager with per-resource abort/sequence handling, backoff, visibility-aware polling, and one global error state. Stop polling on hidden pages and ensure retrain timers are cleaned up.

## P2 — External assets and security headers are weak

**Evidence:** Pages load Bootstrap, Font Awesome, and Chart.js from CDNs without SRI hashes. Page routes return raw HTML with no visible CSP/security headers.

**Plan:** Pin and self-host required assets where practical; otherwise add SRI and explicit CSP source allowlists. Add `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors`, and appropriate cache headers. Test headers on every page and API response.

---

# Useful information to add to the GUI

## Global status strip

Show on every page:

- `PAPER` or `LIVE` mode, read from the backend;
- trading process: `running`, `stopped`, `degraded`, `reconciliation blocked`;
- last cycle and last successful Coinbase account reconciliation;
- data freshness age and source;
- pending order/reconciliation count;
- current display currency and timestamp timezone (`Europe/London` display, UTC source data where applicable).

## Dashboard cards

Add:

- realized P&L versus unrealized P&L;
- fees paid and cost-basis method;
- wallet/API status with stale/unavailable distinction;
- open positions versus pending exits;
- last verified fill and latest order status;
- model availability count, with incompatible/stale model details;
- risk-limit headroom and daily loss used/remaining;
- data-source agreement and age for the current snapshot.

## Position detail

Add:

- position ID and ownership/source;
- requested versus filled size;
- residual size after partial fills;
- entry fill price, weighted/FIFO cost basis, buy fees;
- break-even including fees;
- current stop inputs: snapshot timestamp, ATR, RSI, MA20, MA50, regime, momentum protection;
- last exit attempt, order ID, status, fill price, fees, and reconciliation state;
- explicit reason when a sell is blocked.

## Trades/order view

Add separate order and fill records, Coinbase order IDs, verified status, requested size, filled size, average fill price, fees, timestamp, and whether the record is estimated or authoritative. Preserve failed/cancelled/open orders for diagnosis without counting them as trades.

## AI models page

Add raw versus adjusted confidence, model load errors, model file age/version, training horizon, label hurdle, feature schema, data range, calibration status, per-model vote, actual ensemble weights, and a warning when an unavailable model is excluded.

## Settings page

Add units, valid ranges, last changed time, changed-by/audit entry, pending restart/reload requirement, and a clear warning that live mode and risk settings affect real orders. Add a read-only “effective settings” panel showing what the trading subprocess currently loaded.

---

# Implementation sequence

### Phase 1 — Safety and truthful state

1. Add API authentication/authorization/CSRF boundary and audit logging.
2. Replace fake control actions with persisted commands, acknowledgement, idempotency, and read-back.
3. Fix manual-close settings import and typed result states.
4. Make resync fail closed and preserve cost basis.
5. Add stale/unavailable API envelopes and status heartbeat.
6. Route dashboard retrain to the real retrain endpoint.

### Phase 2 — Data contracts and financial correctness

1. Define Pydantic response/request models for status, positions, orders, fills, P&L, models, and settings.
2. Create a canonical ledger endpoint; stop merging lifecycle rows and fills in the browser.
3. Move P&L/statistics aggregation server-side and label fees/cost basis/source/as-of.
4. Add order/fill lifecycle read-back and partial-fill UI.
5. Add model-health and actual-weight fields from the backend.

### Phase 3 — Browser correctness and security

1. Add shared escaped rendering helpers and remove unsafe API interpolation.
2. Add request cancellation/sequence guards and polling cleanup.
3. Add CSP, security headers, SRI or self-hosted assets.
4. Replace inline handlers with delegated listeners and typed payloads.
5. Add accessible labels, live regions, focus styles, and mobile layouts.

### Phase 4 — Operational information and polish

1. Add global status/freshness strip and reconciliation banner.
2. Add position/order/fill diagnostics and explainable exit decisions.
3. Add model compatibility/age/calibration details.
4. Add settings audit/effective-settings view.
5. Remove obsolete diagnostic template/code and consolidate duplicated page JavaScript.

---

# Files likely to change

- `src/api_worker.py`
- `src/templates/dashboard.html`
- `src/templates/trades.html`
- `src/templates/performance.html`
- `src/templates/models.html`
- `src/templates/settings.html`
- `src/templates/error.html`
- `src/static/style.css`
- `src/database.py` and any required migration under `migrations/`
- New shared browser asset, preferably `src/static/js/app.js`, `src/static/js/api.js`, `src/static/js/render.js`
- New API/schema modules under `src/` if Pydantic contracts are introduced
- `tests/test_api_gui_contracts.py`
- `tests/test_control_actions.py`
- `tests/test_manual_close_endpoint.py`
- `tests/test_reconciliation_endpoint.py`
- `tests/test_ledger_presentation.py`
- `tests/test_security_headers.py`
- Browser tests under `tests/browser/` using Playwright or an equivalent installed test runner

---

# Verification plan

## Backend/API tests

- GET every page route returns 200 and expected title/navigation.
- Control actions persist state, are idempotent, require authorization, and return acknowledgement only after read-back.
- Live-mode switch requires confirmation and cannot silently change mode.
- Manual close imports settings, blocks below break-even, verifies fills, handles partial fills, and never closes the DB row on an unverified order.
- Resync rejects unavailable Coinbase accounts/prices and leaves DB state unchanged.
- Account failure is represented as unavailable, never zero.
- Canonical ledger does not double-count one buy/sell lifecycle.
- Model status distinguishes loaded, unavailable, incompatible, stale, and excluded.
- Security headers and CSP are present.

## Browser tests

- Inject hostile strings into every API value and verify they render as text.
- Verify stale/unavailable badges do not show £0.00 or “No positions”.
- Verify control buttons cannot be double-submitted and display pending/failed/success states.
- Verify manual close confirmation and partial-fill residual display.
- Verify settings units, bounds, read-after-write, and live-mode warning.
- Verify dashboard, trades, performance, models, and settings at 1280px, 768px, and 375px widths.
- Keyboard-only navigation and axe checks for labels, contrast, focus, tables, and live regions.
- Simulate slow/out-of-order responses and ensure older data cannot overwrite newer data.

## Runtime verification

```bash
cd /projects/crypto-trader-bot
python3 -m compileall -q src tests
git diff --check
docker cp <changed-runtime-files> crypto-trader-bot:/app/src/
docker exec crypto-trader-bot python3 -m pytest -q /app/tests
docker restart crypto-trader-bot
curl -fsS http://localhost:8000/api/health
for page in / /trades /performance /models /settings; do curl -fsS -o /dev/null -w "$page %{http_code}\n" "http://localhost:8000$page"; done
docker logs --since 60s crypto-trader-bot 2>&1 | grep -E 'Traceback|ERROR|Exception' || true
```

Acceptance requires that the GUI never claims a mutation, fill, balance, position close, model retrain, or healthy trading process without backend evidence and read-back.

---

# Risks and open questions

- Authentication changes can lock out the operator; deploy with a local recovery path and verify from the actual LAN client.
- Browser CSP may require moving inline scripts/styles to static files or using nonces; do not weaken CSP to preserve inline code.
- Self-hosting assets increases image size, while CDN assets create supply-chain and availability risk; choose deliberately.
- The current dashboard is server-rendered and duplicated across pages; centralizing JavaScript is worthwhile but should be incremental to avoid breaking the live Pi UI.
- The API-worker/trading-process boundary needs an explicit command protocol before controls can be made truthful. Do not implement another in-memory flag.
- Live mode and emergency stop require an explicit policy for what happens to already-open positions; stopping new entries is different from cancelling orders or closing positions.
