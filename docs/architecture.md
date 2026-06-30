# Architecture

System architecture for the crypto trading bot.

## Overview

The crypto-trader-bot uses a **multi-process architecture** to separate computationally expensive ML operations from lightweight HTTP serving.

## Multi-Process Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Docker Container                            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │               Trading Process (src/trading_loop.py)      │   │
│  │                                                             │   │
│  │  • Runs trading_engine.run_trading_cycle() every 45 min  │   │
│  │  • Generates AI signals fresh for trading decisions       │   │
│  │  • Executes orders on Coinbase                           │   │
│  │  • Monitors positions (SL, TP, scale-in/out)            │   │
│  │  • Writes to SQLite DB                                   │   │
│  │  • Writes to data/signal_cache.json (for API workers)   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                │                                │
│                                │ Shared Files                    │
│                                ▼                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │                 data/signal_cache.json                    │   │
│  │  { "BTC-GBP": { "action": "BUY", "confidence": 0.72 }}│   │
│  └────────────────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────────────┐   │
│  │                    data/trades.db (SQLite)                │   │
│  └────────────────────────────────────────────────────────┘   │
│                                ▲                                │
│                                │                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │            API Workers (gunicorn + uvicorn)               │   │
│  │                                                             │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                   │   │
│  │  │ Worker1 │  │ Worker2 │  │ Worker3 │  (NUM_WORKERS=3)   │   │
│  │  └─────────┘  └─────────┘  └─────────┘                   │   │
│  │                                                             │   │
│  │  • Serve FastAPI endpoints for dashboard                   │   │
│  │  • Read from signal_cache.json (fast, no ML)             │   │
│  │  • Read from SQLite DB                                    │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Startup (`src/startup.py`)

Orchestrates the entire system startup by launching trading and API processes.

| Component | Description |
|-----------|-------------|
| `BotStarter` | Main orchestrator class |
| `start_trading()` | Launches `src/trading_loop.py` as subprocess |
| `start_api_workers()` | Launches gunicorn with uvicorn workers |
| `wait_for_api_ready()` | Polls `/api/health` until ready |
| `check_process_health()` | Monitors both processes for crashes |

---

### 2. Trading Loop (`src/trading_loop.py`)

Main entry point for the trading process. Runs trading cycles on a schedule.

| Component | Description |
|-----------|-------------|
| `TradingProcess` | Main class |
| `run()` | Main loop that runs indefinitely |
| `run_cycle()` | Executes one complete trading cycle |

**Flow**:
1. Initialize logging
2. Run `initial_position_sync()` to sync with Coinbase
3. Run initial trading cycle
4. Loop every `MARKET_CHECK_INTERVAL` (45 min default)
5. Log cycle completion time

---

### 3. API Worker (`src/api_worker.py`)

FastAPI application serving the web dashboard. Handles HTTP requests from browser.

| Component | Description |
|-----------|-------------|
| `FastAPI app` | Main application with route handlers |
| `Jinja2Templates` | HTML page rendering |
| `APScheduler` | Background tasks |

**Key Responsibilities**:
- Serve HTML dashboard pages
- Handle API requests (read-only data)
- Read from signal cache (no ML computation)
- Read from SQLite database

---

### 4. Trading Engine (`src/trading_engine.py`)

Core trading logic that orchestrates signal generation, risk management, and order execution.

| Component | Description |
|-----------|-------------|
| `TradingEngine` | Main class |
| `run_trading_cycle()` | Main cycle: scan, execute, monitor |
| `scan_for_signals()` | Generate BUY/SELL signals from AI |
| `execute_signal()` | Execute validated signals |
| `monitor_positions()` | Check SL, TP, trailing SL, AI SELL |

---

### 5. Database (`src/database.py`)

SQLite persistence for trades, positions, and settings.

| Class | Purpose |
|-------|---------|
| `Trade` | Completed trade records |
| `MarketData` | Historical OHLCV candles |
| `UserSettings` | User preferences |
| `OpenPosition` | Current open positions |
| `DatabaseManager` | CRUD operations |

---

### 6. AI Model (`src/ai/`)

Machine learning signal generation with **modular architecture** for maintainability.

**Recommended Usage** (new code):
```python
from src.ai import get_signal, regime_detector
signal = get_signal('BTC-GBP')
```

**Backward Compatible** (existing code):
```python
from src.ai_model import ai_model
signal = ai_model.get_signal('BTC-GBP')
```

#### Modular Structure (`src/ai/`)

| File | Purpose |
|------|---------|
| `base.py` | Core utilities, PredictionLogger, PerformanceTracker, SignalCache |
| `regime.py` | Market regime detection (uptrend/downtrend/neutral) |
| `features.py` | Feature engineering for ML |
| `ensemble.py` | Model ensemble voting with regime adjustments |
| `models.py` | Model storage/loading (supports legacy filenames) |
| `training.py` | Model training with ATR threshold tuning |
| `signals.py` | Signal generation wrapper |

| Component | Description |
|-----------|-------------|
| `AIModel` | Main class (backward compatibility) |
| `get_signal()` | Generate trading signal for product |
| `predict()` | ML prediction using ensemble |
| `detect_regime()` | Market trend detection |
| `refresh_all_signals()` | **PARALLEL** refresh of all 8 trading pair signals |
| `entry_reason` | Tracks why position was opened (e.g., "AI BUY, conf=72%, regime=uptrend") |

#### Parallel Signal Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PARALLEL SIGNAL PROCESSING                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  refresh_all_signals() called after:                                        │
│    1. Trading cycle completion                                              │
│    2. Dashboard page load (optional refresh)                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    BEFORE (Sequential - ~4 min)                    │   │
│  │                                                                      │   │
│  │  for product in pairs:        # 8 iterations                       │   │
│  │      thread.start()           # Start thread                       │   │
│  │      thread.join()           # WAIT for completion!                │   │
│  │                                                                      │   │
│  │  Result: Each signal waits for previous → total ~4 minutes          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              vs                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    AFTER (Parallel - ~30-60s)                      │   │
│  │                                                                      │   │
│  │  threads = []                                                        │   │
│  │  for product in pairs:           # Start all 8 threads             │   │
│  │      t = Thread(target=...)                                       │   │
│  │      t.start()                                                      │   │
│  │      threads.append(t)                                             │   │
│  │                                                                      │   │
│  │  for t in threads:              # Then wait for ALL                 │   │
│  │      t.join(timeout=120)                                        │   │
│  │                                                                      │   │
│  │  Result: All 8 signals process simultaneously → ~30-60 seconds    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Key Code (ai_model.py:154-190):                                           │
│  ```python                                                                  │
│  # Start all threads in parallel first                                     │
│  for product_id in self.gbp_trading_pairs:                                  │
│      t = threading.Thread(target=get_signal_with_timeout,                  │
│                           args=(product_id, result_dict, error_dict))        │
│      t.start()                                                              │
│      threads.append(t)                                                      │
│                                                                              │
│  # Wait for all to complete                                                 │
│  for t in threads:                                                          │
│      t.join(timeout=120)                                                    │
│  ```                                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Performance Comparison

| Operation | Before | After | Improvement |
|-----------|--------|-------|-------------|
| Signal refresh (8 pairs) | ~4 min | ~30-60s | **8x faster** |
| Market data update (8 products) | ~1 min | ~15-30s | **4x faster** |
| Signal scanning during cycle | ~8+ min (broken parallel) | ~60s (fixed parallel) | **8x faster** |
| Total trading cycle | ~15+ min (timeout) | ~3-5 min | **Completes** |
| Timer updates | ❌ No | ✅ Yes | **Fixed** |

#### Parallel Signal Scanning - Bug Fix

The initial parallel implementation had a critical bug where threads weren't being properly managed:

**Bug**: Only 3/8 products completed because thread objects weren't stored:
```python
# WRONG - stored product ID, not thread object!
threads.append(product_id)  # ❌ Can't call join() on this!
```

**Fix**: Proper thread handling with individual timeouts:
```python
# CORRECT - store actual thread objects
thread_objects = []
for product_id in settings.PRODUCT_IDS:
    t = threading.Thread(target=process_product_signal, ...)
    t.start()
    thread_objects.append(t)

# Wait for each with proper join
for t in thread_objects:
    t.join(timeout=120)  # Wait up to 2 min per product
```

Each thread now gets individual timeout handling, and the system logs completion status per product:
```
PARALLEL_SCAN: Completed BTC-GBP
PARALLEL_SCAN: Completed ETH-GBP
PARALLEL_SCAN: Completed 8/8 products in 45.2s
```

#### Current Trading Settings

| Setting | Value | Purpose |
|---------|-------|---------|
| Trading Interval | **4 hours** | Prevent overtrading |
| Scale-Out | **Disabled** | Don't sell at tiny profits |
| Min Profit (Neutral) | **8%** | Only sell in profit |
| Min Profit (Bear) | **2%** | Require profit in downtrend |
| Min Profit (Bull) | **10%** | Require strong profit |
| Signal Cache TTL | **5 minutes** | Fresh enough signals |
| Buy Cooldown | **2 hours** | After selling |
| Daily Buy Limit | **1 per pair** | Prevent excessive buying |

#### Parallel Signal Scanning During Trading

The trading cycle uses parallel processing for signal generation to ensure cycles complete in time:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TRADING CYCLE SIGNAL SCANNING                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  scan_for_signals() - Called during each trading cycle                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    BEFORE (Sequential - ~4-8 min)                  │   │
│  │                                                                      │   │
│  │  for product in PRODUCT_IDS:        # 8 iterations                   │   │
│  │      get_signal(product)           # Each triggers:                 │   │
│  │                                      #   - Data fetch (5-10s)        │   │
│  │                                      #   - ML prediction (10-30s)     │   │
│  │                                      #   - Trading logic             │   │
│  │                                                                      │   │
│  │  Result: Cycle timeout after 20 min, signals not executed            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              vs                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    AFTER (Parallel - ~30-60s)                       │   │
│  │                                                                      │   │
│  │  threads = []                                                        │   │
│  │  for product in PRODUCT_IDS:       # Start all 8 threads            │   │
│  │      t = Thread(target=process)                                    │   │
│  │      t.start()                                                      │   │
│  │      threads.append(t)                                             │   │
│  │                                                                      │   │
│  │  for t in threads:               # Wait for all                      │   │
│  │      t.join(timeout=180)                                         │   │
│  │                                                                      │   │
│  │  Result: All signals processed simultaneously → ~30-60 seconds     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Key Features:                                                               │
│  • Uses fresh data via use_cache=True (fetches if cache stale)             │
│  • 180s (3 min) timeout per product                                         │
│  • Cycle timeout increased to 1800s (30 min)                                │
│  • Logs: PARALLEL_SCAN: Starting/Waiting/Completed                         │
│                                                                              │
│  Files Modified:                                                             │
│  • src/trading_engine.py - scan_for_signals() parallelized                 │
│  • src/ai_model.py - refresh_all_signals() parallelized                      │
│  • src/data_collector.py - update_market_data() parallelized                │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Multi-Source Price Aggregation

The bot uses multiple price sources for robustness:

| Source | Weight | Purpose |
|--------|--------|---------|
| Coinbase | 45% | Primary (trading capability) |
| Kraken | 30% | Additional exchange |
| CryptoCompare | 25% | Backup aggregator |

See `src/multi_source_pricer.py` for implementation.

---

### 7. Risk Manager (`src/risk_manager.py`)

Position sizing and risk calculations.

| Component | Description |
|-----------|-------------|
| `RiskManager` | Main class |
| `calculate_position_size()` | Calculate trade size |
| `calculate_stop_loss()` | Calculate SL price |
| `calculate_take_profits()` | Calculate TP levels (regime-based) |
| `check_portfolio_risk()` | Overall risk status |

---

### 8. Trading Limitations - Coinbase UK

**Important**: Coinbase Advanced Trade in the UK only supports **spot trading**. This means:

- **No leverage/margin** - Cannot short or use borrowed funds
- **No futures/options** - Cannot trade derivatives
- **Long positions only** - When you "buy" you own the crypto
- **SELL closes positions** - Selling returns GBP to your wallet

#### Terminology in This Bot

| Term | Meaning in UK Spot Trading |
|------|---------------------------|
| BUY | Open a long position (own crypto) |
| SELL | Close long position (convert to GBP) |
| LONG | Same as BUY - holding crypto |
| SHORT | Not available in UK |
| Stop Loss | Auto-sell if price drops |
| Take Profit | Auto-sell when price reaches target |
| Scale-out | Sell a portion to lock in profit |
| Scale-in | Buy more to lower average entry |

---

### 9. Data Collector (`src/data_collector.py`)

Market data fetching and processing.

| Component | Description |
|-----------|-------------|
| `DataCollector` | Main class |
| `collect_historical_data()` | Fetch OHLCV from Coinbase |
| `get_current_prices()` | Get latest prices |
| `get_features()` | Calculate technical indicators |

---

### 9. Coinbase API (`src/coinbase_api.py`)

Coinbase Advanced Trade API integration.

| Component | Description |
|-----------|-------------|
| `CoinbaseAPI` | Main class |
| `get_accounts()` | Get all accounts |
| `get_product_ticker()` | Get price for pair |
| `place_market_order()` | Execute market order |

---

## Data Flow

### Signal Generation Flow

```
Trading Process
├── ai_model.get_signal(product_id)
│   ├── Map GBP pair → USD pair (for training data)
│   ├── data_collector.get_features(product_id)
│   ├── detect_regime(product_id)
│   ├── Get ML predictions (RF, NN, GB)
│   └── Return {action, confidence, regime}
├── Cache signal in memory
└── Write to data/signal_cache.json

API Workers
├── Read from data/signal_cache.json
└── Serve to dashboard (no ML computation)
```

### Trade Execution Flow

```
scan_for_signals()
├── AI signal generated
├── Position check (have position?)
├── Profit validation for SELL
└── Signal added to queue

_validate_signal()
├── Check trading paused?
├── Get current price
├── Calculate stop loss
├── Calculate position size
├── Check GBP balance
└── Store validated details

execute_signal()
├── Place order (live or paper)
├── Update holdings
├── Save to DB
└── Record trade
```

---

## Settings Persistence

```
┌─────────────────────────────────────────────────────┐
│                   config/settings.py                  │
│   (Code defaults - MAX_POSITION_SIZE, etc.)         │
└─────────────────────┬───────────────────────────────┘
                      │ On startup
                      ▼
┌─────────────────────────────────────────────────────┐
│                   DatabaseManager                    │
│   Table: user_settings (key-value pairs)            │
│   - paper_trading, trading_active                   │
│   - scale_in_enabled, scale_out_enabled             │
│   - model_confidence_threshold                      │
└─────────────────────┬───────────────────────────────┘
                      │ Runtime changes
                      ▼
┌─────────────────────────────────────────────────────┐
│              Dashboard (Settings Page)               │
│   • Read current values from /api/settings/risk    │
│   • Save via POST /api/settings/risk              │
└─────────────────────────────────────────────────────┘
```

---

## Trading Pairs

| Purpose | Pairs | Notes |
|---------|-------|-------|
| **Trading** | 8 GBP pairs | BTC, ETH, SOL, LTC, DOT, ADA, LINK, UNI |
| **AI Training** | 8 GBP pairs | Same pairs as trading (direct market dynamics) |

**Why GBP Training?**
- Direct market dynamics capture (no currency mapping needed)
- 350 candles available for all GBP pairs (Coinbase limit)
- Simpler architecture - train on what you trade

---

## File Structure

```
crypto-trader-bot/
├── config/
│   ├── settings.py          # Configuration class
│   └── api_keys.env          # API keys (not committed)
├── src/
│   ├── startup.py            # Multi-process orchestration
│   ├── trading_loop.py       # Trading process entry point
│   ├── api_worker.py         # FastAPI + gunicorn workers
│   ├── trading_engine.py     # Core trading logic
│   ├── database.py           # SQLAlchemy ORM
│   ├── ai_model.py          # ML signal generation
│   ├── risk_manager.py      # Position sizing, SL/TP
│   ├── data_collector.py    # Market data fetching
│   ├── coinbase_api.py      # Coinbase API wrapper
│   ├── currency_utils.py     # GBP/USD conversion
│   └── templates/            # HTML dashboard pages
├── data/
│   ├── trades.db             # SQLite database
│   ├── signal_cache.json    # Shared signal cache
│   └── last_cycle.txt        # Last cycle timestamp
├── docs/                     # Developer documentation
├── main.py                   # Single-process dev mode
├── requirements.txt          # Dependencies
└── dockerfile               # Container build
```

---

## Key Interactions

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  trading_loop.py│────▶│ trading_engine  │────▶│  coinbase_api   │
│                 │     │                 │     │                 │
│                 │     │  ┌───────────┐  │     │  • get_accounts │
│                 │     │  │  ai_model  │◀─┼─────│  • get_products │
│                 │     │  └───────────┘  │     │  • place_order  │
│                 │     │         │        │     └─────────────────┘
│                 │     │         ▼        │
│                 │     │  ┌───────────┐  │     ┌─────────────────┐
│                 │     │  │data_collect│◀─┼────│    database     │
│                 │     │  └───────────┘  │     │                 │
│                 │     │         │        │     │  • trades       │
│                 │     │         ▼        │     │  • positions    │
│                 │     │  ┌───────────┐  │     │  • settings      │
│                 │     │  │risk_manager│   │     └─────────────────┘
│                 │     │  └───────────┘  │
└─────────────────┘     └─────────────────┘
                              │
                              ▼
                        ┌─────────────────┐
                        │  signal_cache   │
                        │     .json       │
                        └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │   api_worker    │
                        │   (Dashboard)    │
                        └─────────────────┘
```

---

## Position Management

### Position Lifecycle

```
1. OPEN
   ├── Signal generated (AI BUY)
   ├── Validate with risk_manager
   ├── Execute buy order on Coinbase
   └── Save to open_positions table

2. MONITOR (every trading cycle)
   ├── Get current price
   ├── Check AI SELL signal
   ├── Check trailing stop
   └── Check emergency stop

3. CLOSE
   ├── Execute sell order
   ├── Calculate P&L
   ├── Save to trades table
   └── Remove from open_positions
```

### Trailing Stop Logic (`trading_engine.py:monitor_positions()`)

The trailing stop system is designed to:
1. **Never sell at a loss** - only close when above break-even
2. **Lock in profits** - stop moves up as price increases
3. **Dynamic** - adapts to market regime

**Key Calculations**:

```python
# 1. Break-even (covers fees)
break_even = entry_price × (1 + taker_fee)  # taker_fee = 0.75%

# 2. Peak tracking (always update if higher)
if current_price > peak_price:
    peak_price = current_price

# 3. Trailing activation (price has covered fees)
trailing_activated = (peak_price >= break_even)

# 4. Trailing stop (moves with price)
trailing_stop = peak_price × (1 - trailing_pct)  # trailing_pct = 2%
trailing_stop = max(trailing_stop, entry_price × 0.95)  # Floor at 95% of entry

# 5. Close conditions (checked in order)
#    a) AI SELL signal (if profitable)
#    b) Trailing stop hit (if activated)
#    c) Emergency stop (2% drop from entry)
```

### Exit Conditions

| Condition | When Triggered | Purpose |
|-----------|----------------|---------|
| AI SELL Signal | AI generates SELL + above break-even | Take profit on AI signal |
| Trailing Stop | Price drops from peak + was above break-even | Lock in profits |
| Emergency Stop | Price drops >2% from entry (anywhere) | Limit losses |

### Database Schema

**Table: `open_positions`**

| Column | Type | Description |
|--------|------|-------------|
| position_id | String | UUID |
| product_id | String | Trading pair (BTC-GBP) |
| side | String | 'buy' or 'sell' |
| size | Float | Crypto amount |
| entry_price | Float | Entry price |
| stop_loss_price | Float | Stop loss level (MUST be below entry for long) |
| peak_price | Float | Highest price since open |
| remaining_size | Float | Remaining after scale-outs |
| scale_out_count | Integer | Number of scale-outs |

### Common Bugs

1. **`trailing_activated` undefined** - Variable referenced but never set → NameError
2. **Stop loss above entry** - For long positions, SL must be BELOW entry, not above
3. **Fee parsing failure** - Use `response.fee_tier` (attribute), not `.get()` (dict)
4. **AI SELL not checked** - Must check signals for existing positions

---

## Fee System

### Fee Fetching (`coinbase_api.py`)

```python
# SDK returns GetTransactionSummaryResponse object, NOT dict
response = sdk_client.get_transaction_summary(product_type="SPOT")
fee_tier = response.fee_tier  # Access as attribute!
maker_fee = float(fee_tier.get('maker_fee_rate', 0))
taker_fee = float(fee_tier.get('taker_fee_rate', 0))
```

### Fee Rates (Intro 2 Tier)

| Fee Type | Rate | On £15 Trade |
|----------|------|--------------|
| Maker | 0.35% | £0.05 |
| Taker | 0.75% | £0.11 |
| **Total** | **1.10%** | **£0.16** |

### Fallback Rates (WRONG - don't use!)

| Fee Type | Rate | On £15 Trade |
|----------|------|--------------|
| Maker | 0.60% | £0.09 |
| Taker | 1.20% | £0.18 |
| **Total** | **1.80%** | **£0.27** |

The fallback rates are 64% higher than actual - this causes positions to never reach break-even!

---

## Key Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| MARKET_CHECK_INTERVAL | 2700s (45 min) | Trading cycle frequency |
| TRAILING_STOP_PERCENT | 2% | Trailing stop percentage |
| DEFAULT_STOP_LOSS | 5% | 5% below entry for long positions |
| MIN_PROFIT_THRESHOLD | 1% | Minimum profit to close on SELL signal |
