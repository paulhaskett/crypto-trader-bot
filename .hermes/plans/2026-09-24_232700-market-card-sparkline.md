# Market Card Live Price Chart Plan

**Goal:** Add a compact live-updating price sparkline to the upper-right of each Market Conditions card.

**Approach:** Include the latest completed close history from the existing SQLite market-data cache in `/api/market/conditions`; render a lightweight inline SVG sparkline in each signal card. Refreshes with the existing market-conditions polling interval and shows direction/current value without adding a charting dependency.

**Files:**
- Modify `/projects/crypto-trader-bot/src/api_worker.py`
- Modify `/projects/crypto-trader-bot/src/templates/dashboard.html`

**Verification:** Compile API code, deploy with `docker cp`, restart, verify each condition includes `price_history`, confirm dashboard HTML contains sparkline rendering, and check API health.
