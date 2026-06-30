# API Reference

Complete list of all API endpoints in the crypto trading bot.

## Architecture

### Two Entry Points

| Mode | File | Usage | Endpoint Count |
|------|------|-------|----------------|
| Production | `src/startup.py` | Docker default (trading + API workers) | 39 |
| Legacy | `main_legacy.py` | Old single-process mode (deprecated) | 47 |

### Startup Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Container                          │
│                                                                  │
│  ┌─────────────────────┐     ┌─────────────────────────────┐   │
│  │   Trading Process   │     │      API Worker Pool        │   │
│  │                     │     │                             │   │
│  │  - Trading loop     │     │  ┌─────┐ ┌─────┐ ┌─────┐    │   │
│  │  - AI signal gen    │     │  │ W1  │ │ W2  │ │ W3  │    │   │
│  │  - Order execution │     │  └─────┘ └─────┘ └─────┘    │   │
│  │  - Position mgmt   │     │      FastAPI HTTP Server    │   │
│  │                     │     │                             │   │
│  │  Entry:            │     │  Entry:                      │   │
│  │  src/trading_loop.py│     │  src/api_worker.py           │   │
│  └─────────────────────┘     └─────────────────────────────┘   │
│                                                                  │
│  Started by: src/startup.py                                     │
└─────────────────────────────────────────────────────────────────┘
```

### Endpoint Location

- **Active (used by frontend)**: `src/api_worker.py` - 35 endpoints
- **Legacy (deprecated)**: `main_legacy.py` - 47 endpoints (not used in production)

### Endpoint Status

| Status | Count | Description |
|--------|-------|-------------|
| ACTIVE | ~39 | Used by dashboard, settings, models, trades, performance pages |
| UTILITY | ~15 | Debug, testing, control utilities |
| DUPLICATE | ~40 | Shared between api_worker and main_legacy (main_legacy not used) |

## Summary

| File | Endpoints |
|------|-----------|
| `src/api_worker.py` | 39 endpoints (ACTIVE) |
| `main_legacy.py` | 47 endpoints (DEPRECATED, not used) |
| **Total** | **86 endpoints** (39 active, 47 legacy) |

---

## 1. Page Routes

### src/api_worker.py

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve the main dashboard page |
| GET | `/models` | Serve the AI models page |
| GET | `/trades` | Serve the trades history page |
| GET | `/performance` | Serve the performance metrics page |
| GET | `/settings` | Serve the settings configuration page |
| GET | `/favicon.ico` | Return empty favicon to prevent 404s |
| HEAD | `/favicon.ico` | Handle HEAD requests for favicon |

### main.py

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Main dashboard with overview of bot status |
| GET | `/settings` | Settings page for currency management and bot configuration |
| GET | `/trades` | Trades history page |
| GET | `/performance` | Performance metrics page |
| GET | `/models` | AI Models status page |
| WS | `/ws/status` | WebSocket endpoint for real-time status updates |

---

## 2. Status & Health

### src/api_worker.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/status` | Get overall bot status | `{"status", "trading_active", "paper_trading", "timestamp"}` |
| GET | `/api/health` | Health check endpoint | `{"status": "healthy", "timestamp"}` |
| GET | `/api/countdown` | Get countdown timing for next trading cycle | `{"remaining_seconds", "elapsed_seconds", "progress_percent", "trading_active"}` |
| GET | `/api/debug/context` | Debug endpoint to check template variables | `{"display_currency", "raw_value", "length"}` |

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/status` | Get current bot status as JSON | `{"trading_active", "paper_trading", "portfolio_value", ...}` |
| GET | `/api/countdown` | Get countdown timing for next trading cycle | `{"remaining_seconds", "elapsed_seconds", "progress_percent", "trading_active"}` |
| GET | `/api/debug/comprehensive` | Comprehensive debugging for trading engine issues | Full debug state object |
| GET | `/api/debug/trading-cycle` | Debug endpoint to show trading cycle state | `{"engine_memory", "database", "settings", ...}` |

---

## 3. Portfolio

### src/api_worker.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/portfolio/summary` | Get portfolio summary for overview cards | `{"total_value", "gbp_balance", "daily_pnl", "holdings", ...}` |
| GET | `/api/open_positions` | Get open positions formatted for table display | `{"status", "positions": [...], "count"}` |
| GET | `/api/closed_positions` | Get closed positions formatted for table display | `{"status", "positions": [...], "count"}` |
| GET | `/api/recent_trades` | Get recent trades formatted for table display | `{"status", "trades": [...], "count"}` |

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/portfolio` | Get portfolio composition with currency conversion | `{"portfolio", "total_value", "formatted_total", ...}` |
| GET | `/api/portfolio/summary` | Get portfolio summary for settings page | `{"display_currency", "gbp_balance", "open_positions", ...}` |
| GET | `/api/portfolio/open_positions` | Get all currently held positions | `{"positions": [...], "count", "total_pnl"}` |
| GET | `/api/portfolio/closed_positions` | Get closed positions with P&L information | `{"positions": [...], "count"}` |

---

## 4. Market & Trading

### src/api_worker.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/market/conditions` | Get market conditions with prices and signals | `{"status", "conditions": {...}}` |
| GET | `/api/exchange_rate` | Get USD to GBP exchange rate | `{"status", "exchange_rate", "usd_to_gbp"}` |
| GET | `/api/gbp-balance` | Get GBP balance info | `{"status", "gbp_balance", "formatted_balance", "status"}` |
| GET | `/api/risk/status` | Get risk status details | `{"status", "risk_status", "message", "gbp_balance"}` |
| POST | `/api/control/{action}` | Control bot actions (start, stop, emergency_stop, retrain) | `{"status", "message", "trading_active"}` |

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/market/conditions` | Get market conditions (signals and regime) for all trading pairs | `{"status", "conditions": {...}}` |
| GET | `/api/exchange_rate` | Get current USD to GBP exchange rate | `{"rate", "source"}` |
| GET | `/api/exchange-rate` | Alias for exchange-rate endpoint | `{"rate", "source"}` |
| GET | `/api/gbp-balance` | Get GBP balance status with alert levels | `{"gbp_balance", "status", "warning_threshold", ...}` |
| POST | `/api/control/{action}` | Control bot operations | Returns control action result |

**Control Actions**:
- `start_trading` - Start trading engine
- `stop_trading` - Stop trading engine
- `enable_live_trading` - Enable live trading
- `switch_to_paper_trading` - Switch to paper trading
- `emergency_stop` - Activate emergency stop
- `reset_emergency_stop` - Reset emergency stop
- `retrain_models` - Retrain AI models
- `cleanup_dust` - Clean up dust positions

---

## 5. Trading Control (main.py)

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| POST | `/api/control/switch_live` | Switch to live trading mode | `{"status", "message", "positions_cleared"}` |
| POST | `/api/control/switch_paper` | Switch to paper trading mode | `{"status", "message"}` |
| POST | `/api/position/{position_id}/close` | Close a specific open position | `{"status", "message", "exit_price", "pnl"}` |
| POST | `/api/trading/reset` | Reset inconsistent trading state | `{"success", "message"}` |

---

## 6. AI Models

### src/api_worker.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/models/status` | Get AI model status with current signals | `{"status", "models_trained", "working_models", "models": [...]}` |
| POST | `/api/models/retrain` | Retrain all AI models (runs in background) | `{"status", "message", "completed", "total"}` |
| GET | `/api/models/retrain_progress` | Get current retrain progress + last retrain info (consolidated) | `{"in_progress", "last_retrain_date", "days_since_retrain", "auto_retrain_enabled", ...}` |
| POST | `/api/models/generate_signals` | Generate fresh signals for all GBP trading pairs | `{"status", "signals": {...}, "timestamp"}` |
| GET | `/api/ai/retrain_status` | DEPRECATED — use `/api/models/retrain_progress` instead | `{"status", ...}` |

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/models/status` | Get AI model status for all trading pairs | `{"success", "total_products", "working_models", "models": {...}}` |
| GET | `/api/ai/retrain_status` | Get automatic retraining status and last retrain date | `{"status", "data": {...}}` |
| POST | `/api/settings/auto_retrain` | Enable or disable automatic weekly model retraining | `{"status", "message"}` |

---

## 7. Scale-In

### src/api_worker.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/scale_in/status` | Get current scale-in configuration | `{"enabled", "levels", "size_by_level", ...}` |
| POST | `/api/scale_in/configure` | Update scale-in settings | `{"status", "message"}` |

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/scale_in/status` | Get current scale-in configuration | `{"enabled", "levels", "size_by_level", ...}` |
| POST | `/api/scale_in/configure` | Update scale-in settings | `{"status", "message", "settings": {...}}` |
| POST | `/api/scale_in/toggle_block` | Toggle global block on scale-ins | `{"status", "message", "blocked"}` |

---

## 8. Scale-Out

### src/api_worker.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/scale_out/status` | Get current scale-out settings | `{"enabled", "min_profit_pct", "take_profit_levels", ...}` |
| POST | `/api/scale_out/configure` | Update scale-out settings | `{"status", "message"}` |

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/scale_out/status` | Get current scale-out settings | `{"enabled", "min_profit_pct", "take_profit_levels", ...}` |
| POST | `/api/scale_out/configure` | Update scale-out settings | `{"status", "message", "settings": {...}}` |

---

## 9. Risk Settings

### src/api_worker.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/settings/risk` | Get current risk management settings | `{"confidence_threshold", "stop_loss", "take_profit", ...}` |
| POST | `/api/settings/risk` | Save risk management settings | `{"status", "message"}` |
| POST | `/api/settings/display_currency` | Save display currency preference | `{"status", "message"}` |
| POST | `/api/settings/market_check_interval` | Save market check interval in seconds | `{"status", "message", "interval_seconds", "interval_minutes"}` |
| GET | `/api/settings/{key}` | Get individual setting value | `{"key", "value"}` |

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| POST | `/api/settings/{setting_key}` | Update user setting | `{"status", "message"}` |
| POST | `/api/settings/market_check_interval` | Set market check interval in seconds | `{"status", "interval_seconds", "interval_minutes"}` |
| POST | `/api/settings/display_currency` | Set user's preferred display currency | `{"status", "message", "saved_currency"}` |
| GET | `/api/settings/display_currency` | Get current display currency | `{"display_currency"}` |
| POST | `/api/settings/base_currency` | Set user's preferred base currency for trading | `{"status", "message", "base_currency", "trading_pairs"}` |
| POST | `/api/settings/take_profit_level` | Set user's take profit level percentage | `{"status", "message", "take_profit_level"}` |
| POST | `/api/settings/auto_retrain` | Enable or disable automatic weekly model retraining | `{"status", "message"}` |

---

## 11. Currency

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| GET | `/api/currency/info` | Get current currency configuration and exchange rates | `{"base_currency", "display_currency", "exchange_rates", ...}` |

---

## 12. Trades

### src/api_worker.py

| Method | Path | Purpose | Query Params |
|--------|------|---------|--------------|
| GET | `/api/recent_trades` | Get recent trades with FIFO P&L matching | `limit` |
| GET | `/api/trades/stats` | Get trade statistics | `trade_type`, `min_trades` |
| POST | `/api/trades/clear` | Clear all trade records from database | None |
| POST | `/api/trades/cleanup` | Delete trades older than `days` (default 30) | `days` |

---

## 13. Performance

### src/api_worker.py

| Method | Path | Purpose | Query Params |
|--------|------|---------|--------------|
| GET | `/api/performance` | Get performance metrics and chart data | `start_date`, `end_date`, `product` |

---

## 14. Diagnostics

### main.py

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| POST | `/api/test-trade` | Place a very small test trade to verify API keys work | `{"success", "message", "order_id", "product_id"}` |
| GET | `/api/check-api-permissions` | Check Coinbase API key permissions using SDK | `{"success", "permissions": {"can_view", "can_trade", "can_transfer", ...}}` |

---

## Endpoint Summary by HTTP Method

### GET Endpoints (47 total)

```
src/api_worker.py:
- /
- /models
- /trades
- /performance
- /settings
- /favicon.ico
- /api/status
- /api/countdown
- /api/portfolio/summary
- /api/portfolio/coinbase_pnl
- /api/market/conditions
- /api/open_positions
- /api/closed_positions
- /api/recent_trades
- /api/models/status
- /api/models/retrain_progress
- /api/ai/retrain_status (deprecated)
- /api/exchange_rate
- /api/gbp-balance
- /api/risk/status
- /api/trades/stats
- /api/performance
- /api/scale_in/status
- /api/scale_out/status
- /api/settings/risk
- /api/settings/{key}
- /api/fees/status
- /api/health

main.py:
- /
- /settings
- /trades
- /performance
- /models
- /api/status
- /api/countdown
- /api/debug/context
- /api/debug/comprehensive
- /api/debug/trading-cycle
- /api/market/conditions
- /api/exchange_rate
- /api/exchange-rate
- /api/gbp-balance
- /api/models/status
- /api/ai/retrain_status
- /api/settings/display_currency
- /api/currency/info
- /api/trades
- /api/portfolio
- /api/portfolio/summary
- /api/portfolio/open_positions
- /api/portfolio/closed_positions
```

### POST Endpoints (25 total)

```
src/api_worker.py:
- /api/models/retrain
- /api/models/generate_signals
- /api/control/{action}
- /api/scale_in/configure
- /api/scale_out/configure
- /api/settings/risk
- /api/settings/display_currency
- /api/settings/market_check_interval
- /api/trades/clear
- /api/trades/cleanup

main.py (deprecated):
- /api/control/{action}
- /api/control/switch_live
- /api/control/switch_paper
- /api/position/{position_id}/close
- /api/trading/reset
- /api/scale_in/configure
- /api/scale_in/toggle_block
- /api/scale_out/configure
- /api/settings/risk
- /api/settings/{setting_key}
- /api/settings/market_check_interval
- /api/settings/display_currency
- /api/settings/base_currency
- /api/settings/take_profit_level
- /api/settings/auto_retrain
- /api/trades/clear
- /api/test-trade
```

### WebSocket Endpoint (1)
- WS `/ws/status`

### HEAD Endpoint (1)
- HEAD `/favicon.ico`

---

## Notes

### Legacy Files (Renamed March 2026)

- **main.py** → `main_legacy.py` - DEPRECATED (not used in production)
- **src/dashboard.py.old** → `src/dashboard_legacy.py.old` - DEPRECATED

### Production Architecture

- **`src/startup.py`** - Production entry point, starts trading process + API workers
- **`src/trading_loop.py`** - Trading process (subprocess)
- **`src/api_worker.py`** - API server for dashboard (gunicorn workers)
- **`main_legacy.py`** - Legacy single-process mode (not used, kept for reference)

### Endpoint Usage

- Frontend templates (dashboard.html, settings.html, etc.) use `src/api_worker.py` endpoints
- `main_legacy.py` has duplicate endpoints but is not used
- When adding new endpoints, add to `src/api_worker.py` only
