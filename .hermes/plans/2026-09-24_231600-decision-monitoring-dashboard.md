# Decision Monitoring Dashboard Plan

**Goal:** Expose the bot's initial-entry gate, model decision metadata, and open-position risk state in the dashboard.

**Scope:** Extend `/api/market/conditions` and `/api/open_positions`, then render the fields in the existing signal cards and position detail rows. No trading behavior changes.

**Files:**
- Modify `/projects/crypto-trader-bot/src/api_worker.py`
- Modify `/projects/crypto-trader-bot/src/templates/dashboard.html`
- Add focused API/HTML smoke checks where existing test structure permits.

**Data to expose:**
- Signal timestamp/age, raw confidence where available, adjusted confidence, model agreement, regime, and threshold status.
- Entry gate enabled/confirmed state, candidate trough, ATR, rebound requirement, confirmation level, and rejection reason.
- Open-position signal action/confidence, entry reason, break-even distance, underwater duration/drawdown, peak-to-current giveback, and trailing-stop state.

**Verification:**
- Compile Python and run existing tests.
- Copy API/template changes into the running container, restart, and verify `/api/health`, `/api/market/conditions`, and `/api/open_positions` return the new fields.
- Confirm dashboard HTML contains and renders the new data fields without JavaScript errors visible in the source-level smoke checks.
