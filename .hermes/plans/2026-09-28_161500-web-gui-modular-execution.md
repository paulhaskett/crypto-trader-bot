# Crypto Trader Web GUI Modular Implementation Plan

> **For Hermes:** Execute one module at a time. Stop after each module and request Paul's review/confirmation before starting the next module. Do not combine modules in one deployment.

**Goal:** Implement the 2026-09-25 web-GUI review as independently reviewable, low-risk modules, beginning with the AI models page confidence/data contract problem.

**Architecture:** Preserve the FastAPI + server-rendered HTML/Bootstrap architecture. Each module has a narrow backend/UI contract, focused tests, a runtime verification pass, and its own commit. No module may change live trading behavior unless explicitly stated and separately approved.

**Safety invariant:** The GUI must never imply that a model traded, an order filled, a position closed, a balance is current, or a control command succeeded unless the backend has verified that state.

---

## Execution protocol

For every module:

1. Inspect the current implementation and write focused failing tests.
2. Implement only that module's scope.
3. Run focused tests, then the relevant existing suite.
4. Copy changed runtime files into the running container only after host tests pass.
5. Restart only if required by the changed files.
6. Verify the exact affected API and browser page.
7. Inspect logs for tracebacks/errors.
8. Commit the module separately.
9. Stop and ask for review/confirmation before proceeding.

Never alter `.env`, credentials, live trading settings, database records, or exchange orders as part of GUI work without a separate explicit approval.

---

# Module 1 — AI models page: truthful confidence and model health

**Priority:** P1

**Objective:** Make the models page distinguish actionable ensemble confidence, HOLD consensus, individual model confidence, and unavailable/incompatible models.

**This directly addresses the current bug:** all six products currently generate predictions, but the ensemble intentionally returns `confidence=0` for HOLD. The page renders that as `0%` and hides the individual RF/GB/Ridge confidence values.

**Files likely to change:**

- Modify: `/projects/crypto-trader-bot/src/api_worker.py` (`/api/models/status`)
- Modify: `/projects/crypto-trader-bot/src/templates/models.html`
- Modify: `/projects/crypto-trader-bot/src/ai/ensemble.py` only if the API contract needs a non-breaking field; do not change trading gates
- Modify: `/projects/crypto-trader-bot/src/ai/signals.py` only if required to expose existing raw/adjusted values
- Create/modify: `/projects/crypto-trader-bot/tests/test_models_api_contract.py`
- Create/modify: `/projects/crypto-trader-bot/tests/test_models_page_rendering.py` or equivalent browser/DOM test

**Backend contract:** Add explicit fields without removing existing fields:

```json
{
  "signal": "HOLD",
  "confidence": 0.0,
  "confidence_kind": "not_actionable_hold",
  "display_label": "HOLD consensus",
  "raw_confidence": 0.0,
  "adjusted_confidence": 0.0,
  "agreement": 1.0,
  "models": {
    "rf": {"available": true, "signal": "HOLD", "confidence": 0.685},
    "gb": {"available": true, "signal": "HOLD", "confidence": 0.819},
    "ridge": {"available": true, "signal": "HOLD", "confidence": 0.340}
  }
}
```

The exact schema may use the existing flat fields for compatibility, but the meaning must be explicit. Missing, stale, incompatible, or excluded models must be represented as unavailable with a reason, never as zero confidence or invented equal weights.

**UI acceptance criteria:**

- HOLD cards show `HOLD consensus`, not a red `0%` confidence bar.
- BUY/SELL cards show actionable adjusted confidence and raw confidence separately.
- Individual model signal and confidence are visible for every available model.
- Missing/incompatible models show `Unavailable` plus a reason.
- The page does not calculate or invent ensemble weights in JavaScript.
- “4-Model Ensemble” is replaced by the actual loaded model count/types.
- The existing agreement matrix remains functional and includes Ridge.

**Verification:**

```bash
cd /projects/crypto-trader-bot
python3 -m pytest -q tests/test_hold_confidence.py tests/test_models_api_contract.py
python3 -m compileall -q src tests
git diff --check
docker cp src/api_worker.py crypto-trader-bot:/app/src/api_worker.py
docker cp src/templates/models.html crypto-trader-bot:/app/src/templates/models.html
docker restart crypto-trader-bot
curl -fsS http://localhost:8000/api/health
curl -fsS http://localhost:8000/api/models/status
```

Then inspect `/models` in a browser at desktop and narrow width. Confirm the six current products show model-level confidence even when the ensemble state is HOLD.

**Review gate:** Stop after Module 1 and ask for confirmation.

---

# Module 2 — Shared API freshness and unavailable-state contract

**Priority:** P1

**Objective:** Prevent Coinbase/API failures from rendering as £0, empty positions, healthy status, or “no data”.

**Files likely to change:**

- Modify: `/projects/crypto-trader-bot/src/api_worker.py`
- Modify: `/projects/crypto-trader-bot/src/templates/dashboard.html`
- Modify: `/projects/crypto-trader-bot/src/templates/trades.html`
- Modify: `/projects/crypto-trader-bot/src/templates/performance.html`
- Modify: `/projects/crypto-trader-bot/src/templates/models.html`
- Create/modify: `/projects/crypto-trader-bot/tests/test_api_freshness_contract.py`

**Contract:** Add `data_status`, `as_of`, `source`, `error_code`, and `request_id` to affected API responses. Preserve last-known values with stale labels rather than substituting zero/empty data.

**Acceptance:** Account unavailable, stale, empty, and fresh states render distinctly on all affected pages. `/api/status` reports trading-process heartbeat and last successful reconciliation rather than only `status: running`.

**Review gate:** Stop after verification and request confirmation.

---

# Module 3 — Dashboard control actions and retraining truthfulness

**Priority:** P0/P1

**Objective:** Ensure start/stop/emergency/retrain controls report requested, acknowledged, failed, or unknown state based on read-back.

**Files likely to change:**

- Modify: `/projects/crypto-trader-bot/src/api_worker.py`
- Modify: `/projects/crypto-trader-bot/src/templates/dashboard.html`
- Modify: `/projects/crypto-trader-bot/src/templates/settings.html`
- Modify: `/projects/crypto-trader-bot/src/templates/models.html`
- Create/modify: `/projects/crypto-trader-bot/tests/test_control_actions.py`
- Create/modify: `/projects/crypto-trader-bot/tests/test_retrain_endpoint.py`

**Acceptance:**

- Dashboard retrain uses `/api/models/retrain`, not the fake generic control action.
- Start/stop/emergency commands persist and are acknowledged by the trading process before success is displayed.
- Duplicate clicks are blocked while an operation is pending.
- Live/paper mode is not changed by generic start/stop buttons.
- No live order or position is mutated by this module.

**Review gate:** Stop after verification and request confirmation.

---

# Module 4 — Manual close and reconciliation UI correctness

**Priority:** P0/P1

**Objective:** Make manual close and resync fail closed and expose verified order/fill/reconciliation state.

**Files likely to change:**

- Modify: `/projects/crypto-trader-bot/src/api_worker.py`
- Modify: `/projects/crypto-trader-bot/src/templates/dashboard.html`
- Modify: `/projects/crypto-trader-bot/src/database.py` only if a read model is required
- Create/modify: `/projects/crypto-trader-bot/tests/test_manual_close_endpoint.py`
- Create/modify: `/projects/crypto-trader-bot/tests/test_reconciliation_endpoint.py`

**Acceptance:**

- Break-even guard remains unchanged and is tested.
- Responses distinguish blocked, unverified, partial, reconciled, and closed states.
- The database is not closed on an unverified order.
- Resync rejects unavailable accounts/prices and preserves cost basis.
- Browser displays order ID, verified fill size/price/fees, residual size, and reconciliation status.

**Review gate:** Stop after verification and request confirmation.

---

# Module 5 — Canonical fills, positions, and P&L presentation

**Priority:** P1

**Objective:** Remove browser-side double counting and clearly separate fills, orders, position lifecycles, realized P&L, and unrealized P&L.

**Files likely to change:**

- Modify: `/projects/crypto-trader-bot/src/api_worker.py`
- Modify: `/projects/crypto-trader-bot/src/templates/trades.html`
- Modify: `/projects/crypto-trader-bot/src/templates/performance.html`
- Modify: `/projects/crypto-trader-bot/src/templates/dashboard.html`
- Create/modify: `/projects/crypto-trader-bot/tests/test_ledger_presentation.py`

**Acceptance:** One buy + one sell + one closed position appears once in totals. All financial figures identify source, timestamp, currency, fee treatment, and FIFO/verified/estimated status.

**Review gate:** Stop after verification and request confirmation.

---

# Module 6 — Browser safety and rendering correctness

**Priority:** P1/P2

**Objective:** Remove unsafe API interpolation and stale-response races without changing financial logic.

**Files likely to change:**

- Create: `/projects/crypto-trader-bot/src/static/js/app.js`
- Create: `/projects/crypto-trader-bot/src/static/js/api.js`
- Create: `/projects/crypto-trader-bot/src/static/js/render.js`
- Modify: all page templates using dynamic `innerHTML`
- Create/modify: `/projects/crypto-trader-bot/tests/browser/`

**Acceptance:**

- Hostile API strings render as text, not HTML.
- Request cancellation/sequence guards prevent older responses overwriting newer state.
- Polling stops or backs off when pages are hidden.
- Mobile layouts remain usable at 375px, 768px, and 1280px.
- Existing page functionality remains intact.

**Review gate:** Stop after verification and request confirmation.

---

# Module 7 — Authentication, CSRF, security headers, and audit trail

**Priority:** P0

**Objective:** Protect mutation routes and make operator actions attributable and auditable.

**Files likely to change:**

- Create: `/projects/crypto-trader-bot/src/auth.py`
- Create: `/projects/crypto-trader-bot/src/audit.py`
- Modify: `/projects/crypto-trader-bot/src/api_worker.py`
- Modify: all page templates and static assets
- Modify: `/projects/crypto-trader-bot/docker-compose.yml` only after separate approval for configuration changes
- Create: `/projects/crypto-trader-bot/tests/test_authentication.py`
- Create: `/projects/crypto-trader-bot/tests/test_security_headers.py`

**Acceptance:**

- Read and mutation permissions are separated.
- Browser mutation requests require CSRF protection.
- `/api/health` remains minimally accessible for health checks.
- Security headers/CSP are present and tested.
- Audit entries include actor, action, target, request ID, result, and read-back state.
- No credentials are placed in page source or localStorage.

**Review gate:** Stop after verification and request confirmation.

---

## Cross-module completion criteria

The full review is complete only when:

- Every module has a separate commit and verification record.
- `python3 -m pytest -q` passes in the container.
- Every page route returns HTTP 200.
- `/api/health` is healthy after restart.
- No new `Traceback`, `ERROR`, or unhandled exception appears during smoke testing.
- The GUI never claims a mutation, fill, balance, close, retrain, or healthy process without backend evidence.
- The operator has reviewed and confirmed each module before the next module begins.
