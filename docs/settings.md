# Settings Reference

Complete reference for all configuration settings in the crypto trading bot.

## Overview

Settings are managed in two ways:
1. **Static Settings** (`config/settings.py`) - Hardcoded defaults loaded at startup
2. **Dynamic Settings** (`user_settings` database table) - User-configurable, persisted

---

## 1. Trading Configuration

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `BASE_CURRENCY` | `'GBP'` | string | Primary base currency for portfolio valuation |
| `BASE_CURRENCIES` | `['USD', 'USDC']` | list | Support USD valuation for risk management |
| `PRODUCT_IDS` | `['BTC-GBP', 'ETH-GBP', 'SOL-GBP', 'LTC-GBP', 'DOT-GBP', 'ADA-GBP', 'LINK-GBP', 'UNI-GBP']` | list | 8 GBP pairs for trading |
| `TRAINING_PAIRS` | `['BTC-GBP', 'ETH-GBP', 'SOL-GBP', 'LTC-GBP', 'ADA-GBP', 'LINK-GBP', 'BTC-USD', 'ETH-USD', 'SOL-USD', 'LTC-USD', 'ADA-USD', 'LINK-USD']` | list | 12 pairs (6 GBP + 6 USD) for dual training - GBP models preferred for GBP trading, USD fallback |

---

## 2. Risk Management

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `MAX_POSITION_SIZE` | `0.10` (10%) | float | 10% of portfolio per trade |
| `MAX_DAILY_TRADES` | `2` | int | Maximum trades per day |
| `MAX_CONCURRENT_POSITIONS` | `4` | int | Maximum open positions at once |
| `MIN_TRADE_VALUE` | `5.0` | float | Minimum £5 trade value |
| `GBP_BUFFER` | `5.0` | float | Keep £5 GBP minimum balance |
| `STOP_LOSS_MIN_PERCENT` | `0.10` (10%) | float | Fixed stop loss (5-20% configurable) |
| `PAPER_TRADING_PORTFOLIO_VALUE` | `10000.0` | float | Simulated $10k for paper trading |

### Dynamic Settings

| Setting Key | Default | Type | API Endpoint |
|-------------|---------|------|--------------|
| `max_position_size` | `5` | int (%) | `POST /api/settings/risk` |
| `max_concurrent_positions` | `8` | int | `POST /api/settings/risk` |
| `stop_loss_min_percent` | `5` | int (%) | `POST /api/settings/risk` |
| `take_profit_level` | `1.0` | float (%) | `POST /api/settings/take_profit_level` |

---

## 3. Scale-In (Averaging Down)

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `SCALE_IN_ENABLED` | `True` | bool | Enable multi-level scale-in |
| `SCALE_IN_LEVELS_NEUTRAL` | `[2.0, 4.0, 6.0]` | list | Drop percentages in neutral market |
| `SCALE_IN_LEVELS_BEAR` | `[1.0, 2.0, 3.0]` | list | Drop percentages in downtrend (tighter - average down faster) |
| `SCALE_IN_LEVELS_BULL` | `[3.0, 5.0, 7.0]` | list | Drop percentages in uptrend (wider - less aggressive) |
| `SCALE_IN_SIZE_BY_LEVEL` | `[0.5, 0.75, 1.0]` | list | Size multipliers per level (50%, 75%, 100% of original) |
| `MAX_SCALE_INS_PER_POSITION` | `3` | int | Max scale-ins per position |
| `SCALE_IN_COOLDOWN_HOURS` | `4` | int | Minimum hours between scale-ins |
| `SCALE_IN_GLOBAL_BLOCK` | `False` | bool | Emergency stop - block all scale-ins |

> **Note**: Scale-in levels are regime-aware - tighter levels (1%, 2%, 3%) in downtrend to average down faster, wider levels (3%, 5%, 7%) in uptrend to avoid adding during rallies.

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/scale_in/status` | GET | Get current scale-in configuration |
| `/api/scale_in/configure` | POST | Update scale-in settings |
| `/api/scale_in/toggle_block` | POST | Toggle emergency scale-in block |

---

## 4. Scale-Out (Taking Profits)

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `SCALE_OUT_ENABLED` | `True` | bool | Enable partial profit-taking |
| `SCALE_OUT_PERCENTAGES` | `[25, 25, 50]` | list | % to sell at each TP level (25%, 25%, 50%) |
| `SCALE_OUT_MIN_PROFIT_NEUTRAL` | `5.0` (5%) | float | Minimum profit in neutral market |
| `SCALE_OUT_MIN_PROFIT_BEAR` | `0.5` (0.5%) | float | Minimum profit in downtrend |
| `SCALE_OUT_MIN_PROFIT_BULL` | `8.0` (8%) | float | Minimum profit in uptrend |
| `MAX_SCALE_OUT_PER_POSITION` | `3` | int | Max scale-outs per position |

### Regime-Aware Profit Thresholds

| Regime | SELL Threshold | Scale-Out Threshold | Scale-In Levels |
|--------|---------------|---------------------|-----------------|
| **Downtrend (Bear)** | 0.5% | 0.5% | 1%, 2%, 3% drops |
| **Neutral** | 5.0% | 5.0% | 2%, 4%, 6% drops |
| **Uptrend (Bull)** | 8.0% | 8.0% | 3%, 5%, 7% drops |

> **Note**: Profit thresholds increased in v1.5.0 to reduce trade frequency and fees.

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/scale_out/status` | GET | Get current scale-out configuration |
| `/api/scale_out/configure` | POST | Update scale-out settings |

---

## 4b. Position Replacement

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `POSITION_REPLACEMENT_ENABLED` | `True` | bool | Enable position replacement |
| `REPLACEMENT_CONFIDENCE_THRESHOLD` | `0.08` (8%) | float | 8% confidence improvement to replace |
| `REPLACEMENT_MIN_PROFIT` | `0.02` (2%) | float | Position must be 2%+ profit to allow replacement |
| `REPLACEMENT_COOLDOWN_HOURS` | `24` | int | Don't replace same position within 24 hours |
| `REPLACEMENT_MAX_PER_CYCLE` | `1` | int | Maximum 1 replacement per cycle |

### Replacement Rules

1. **Confidence improvement**: New signal must be at least 8% higher confidence than existing position
2. **Profit requirement**: Position must be at least 2% in profit to be replaced
3. **Cooldown**: Same position can't be replaced within 24 hours
4. **Max per cycle**: Maximum 1 replacement per trading cycle

> **Note**: Replacement allows the bot to upgrade from weak to strong signals without closing positions. Prevents selling at a loss.

---

## 5. Stop Loss & Take Profit

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `STOP_LOSS_MIN_PERCENT` | `0.10` (10%) | float | Fixed stop loss (5-20% configurable) |
| `TAKE_PROFIT_LEVELS` | `[1.0, 2.0, 3.0]` | list | Profit taking levels (1%, 2%, 3% gains) |
| `TRAILING_STOP_PERCENT` | `2.0` (2%) | float | Trailing stop percentage |

---

## 6. AI/ML Settings

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `MODEL_CONFIDENCE_THRESHOLD` | `0.80` (80%) | float | Required confidence to execute trade |
| `PREDICTION_HORIZON` | `12` (hours) | int | Hours to predict ahead |
| `FEATURE_WINDOW_SIZE` | `48` (hours) | int | Hours of data for features |
| `ENSEMBLE_ENABLED` | `True` | bool | Enable RF + NN + GB ensemble |

### Training Feature Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `USE_ATR_THRESHOLD` | `True` | bool | Use ATR-based dynamic thresholds for labels |
| `ATR_MULTIPLIER` | `0.15` | float | k × ATR for label threshold (base value) |
| `ATR_MIN_THRESHOLD` | `0.0005` | float | Minimum 0.05% floor for labels |
| `TRAINING_MIN_PROFIT_THRESHOLD` | `0.001` | float | 0.1% min price move for training labels |
| `USE_WALK_FORWARD` | `True` | bool | Walk-forward validation |
| `WALK_FORWARD_SPLITS` | `3` | int | Number of walk-forward splits |
| `WALK_FORWARD_TRAIN_SIZE` | `300` | int | Training window size per split |
| `LABEL_TYPE` | `binary` | str | 'binary' (BUY/SELL) or '3class' |
| `ADD_PAIR_FEATURES` | `False` | bool | One-hot encode pair identity |
| `ADD_CURRENCY_INDICATOR` | `False` | bool | Binary GBP/USD indicator |

### Volatility Regime Filter (v2.0)

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `USE_VOLATILITY_REGIME` | `True` | bool | Enable volatility-based ATR adjustment |
| `VOLATILITY_ATR_SHORT` | `24` | int | Short ATR period (hours) |
| `VOLATILITY_ATR_LONG` | `72` | int | Long ATR period (hours) |
| `VOLATILITY_RATIO_THRESHOLD` | `1.5` | float | vol_ratio > 1.5 = high volatility |
| `VOLATILITY_HIGH_VOL_MULTIPLIER` | `0.25` | float | k when high volatility |
| `VOLATILITY_LOW_VOL_MULTIPLIER` | `0.10` | float | k when low volatility |

### Volatility Regime Logic

| vol_ratio | Regime | Multiplier (k) |
|-----------|--------|---------------|
| > 1.5 | high | 0.25 |
| 0.7 - 1.5 | normal | ATR_MULTIPLIER (0.15) |
| < 0.7 | low | 0.10 |

### Ensemble Weights

| Setting | Default | Purpose |
|---------|---------|---------|
| `RF_WEIGHT` | `0.5` (50%) | Random Forest weight |
| `NN_WEIGHT` | `0.25` (25%) | Neural Network weight |
| `GB_WEIGHT` | `0.25` (25%) | Gradient Boosting weight |

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/models/status` | GET | Get AI model status |
| `/api/models/retrain` | POST | Retrain all AI models |
| `/api/settings/auto_retrain` | POST | Toggle auto-retrain |

---

## 7. Scheduling

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `MARKET_CHECK_INTERVAL` | `3600` (60 min) | int | Check market every 60 minutes |
| `DATA_UPDATE_INTERVAL` | `1800` (30 min) | int | Update data every 30 minutes |
| `TRADE_COOLDOWN_SECONDS` | `300` (5 min) | int | Cooldown between trades for same product |
| `CANDLE_GRANULARITY` | `"ONE_HOUR"` | string | 1-hour candles |
| `HISTORICAL_DATA_DAYS` | `365` | int | Days of historical data to fetch |

### Dynamic Settings

| Setting Key | Default | API Endpoint |
|-------------|---------|--------------|
| `market_check_interval` | `3600` | `POST /api/settings/market_check_interval` |

### Auto Retraining

| Setting | Default | Purpose |
|---------|---------|---------|
| `AUTO_RETRAIN_ENABLED` | `True` | Enable automatic weekly model retraining |
| `AUTO_RETRAIN_DAY_OF_WEEK` | `'sun'` | Day of week |
| `AUTO_RETRAIN_HOUR` | `3` | Hour of day (3 AM) |

---

## 8. Safety Limits

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `MAX_DAILY_LOSS` | `0.02` (2%) | float | Stop if daily loss exceeds 2% |
| `MAX_WEEKLY_LOSS` | `0.05` (5%) | float | Stop if weekly loss exceeds 5% |
| `CIRCUIT_BREAKER_VOLATILITY` | `0.10` (10%) | float | Pause on 10% volatility spike |
| `EMERGENCY_STOP` | `False` | bool | Manual emergency stop |
| `MAX_CONSECUTIVE_LOSSES` | `4` | int | Stop after 4 consecutive losses |
| `COOLDOWN_PERIOD` | `1800` (30 min) | int | Cooldown after losses |

---

## 9. Display & Currency

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `DISPLAY_CURRENCY` | `'GBP'` | string | Default display currency |
| `SUPPORTED_CURRENCIES` | `['USD', 'GBP']` | list | Supported display currencies |
| `GBP_WARNING_THRESHOLD` | `10.0` | float | Warning when < £10 |
| `GBP_CRITICAL_THRESHOLD` | `5.0` | float | Critical when < £5 |

### Dynamic Settings

| Setting Key | Default | API Endpoint |
|-------------|---------|--------------|
| `display_currency` | `'GBP'` | `POST /api/settings/display_currency` |
| `base_currency` | `'GBP'` | `POST /api/settings/base_currency` |

---

## 10. Trading Mode

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `PAPER_TRADING_MODE` | `True` | bool | Enable paper trading for testing |
| `TRADING_STARTUP_DELAY` | `60` (seconds) | int | Seconds to wait before first trade |

### Dynamic Settings

| Setting Key | Default | API Endpoint |
|-------------|---------|--------------|
| `paper_trading` | `true` | `POST /api/control/switch_paper` |

### Control Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/control/start` | POST | Start trading |
| `/api/control/stop` | POST | Stop trading |
| `/api/control/emergency_stop` | POST | Emergency stop all trading |

---

## Quick Reference: Key Tunables

| Parameter | Recommended Range | Current Default | Effect |
|-----------|-------------------|-----------------|--------|
| `MAX_POSITION_SIZE` | 0.5% - 5% | 5% | Risk per trade |
| `MARKET_CHECK_INTERVAL` | 30-90 min | 60 min | Trading frequency |
| `MODEL_CONFIDENCE_THRESHOLD` | 70% - 90% | 80% | Signal selectivity |
| `MIN_PROFIT_NEUTRAL` | 3% - 8% | 5% | Min profit in neutral |
| `MIN_PROFIT_BULL` | 5% - 10% | 8% | Min profit in uptrend |
| `MAX_CONCURRENT_POSITIONS` | 2 - 8 | 4 | Focus quality over quantity |
| `GBP_BUFFER` | £2 - £10 | £5 | Capital preservation |
| `REPLACEMENT_CONFIDENCE_THRESHOLD` | 5% - 15% | 8% | Position replacement ease |
| `TRADE_COOLDOWN_SECONDS` | 60 - 600 | 300 | Prevent duplicate trades |
| `ATR_MULTIPLIER` | 0.10 - 0.30 | 0.15 | Dynamic label threshold |
| `TRAINING_MIN_PROFIT_THRESHOLD` | 0.001 - 0.005 | 0.001 | Min price move for labels |

---

## Settings Summary

| Category | Settings Count | Persistence |
|----------|---------------|--------------|
| Trading Configuration | 4 | Static |
| Risk Management | 7 | Static + Database |
| Scale-In | 6 | Static + Database |
| Scale-Out | 5 | Static + Database |
| Stop Loss / Take Profit | 4 | Static |
| AI/ML | 4 | Static + Database |
| Scheduling | 4 | Static + Database |
| Safety Limits | 6 | Static |
| Display / Currency | 4 | Static + Database |
| Trading Mode | 2 | Static + Database |
| Multi-Source Pricing | 4 | Static |

**Total: ~50 configurable settings across 11 categories**

---

## Multi-Source Price Settings

### Static Settings

| Setting | Default | Type | Purpose |
|---------|---------|------|---------|
| `MULTI_SOURCE_ENABLED` | `True` | bool | Enable multi-source price aggregation |
| `PRICE_SOURCE_WEIGHTS` | `{'coinbase': 0.4, 'binance': 0.3, 'kraken': 0.2, 'coingecko': 0.1}` | dict | Source weights for consensus calculation |
| `MAX_PRICE_DEVIATION` | `0.03` (3%) | float | Outlier detection threshold |
| `CONSENSUS_MIN_SOURCES` | `2` | int | Minimum sources required for consensus |

### Source Details

| Source | Weight | Description |
|--------|--------|-------------|
| Coinbase | 40% | Primary - has GBP pairs directly |
| Binance | 30% | Uses USDT pairs + implied GBP conversion |
| Kraken | 20% | Has BTC-GBP, ETH-GBP pairs |
| CoinGecko | 10% | Backup aggregator |

### Binance Integration

Binance doesn't have GBP trading pairs. The system uses USDT pairs and converts using an implied exchange rate:

1. Fetch `BTCUSDT` price from Binance
2. Fetch `BTC-GBP` price from Coinbase (reference)
3. Calculate implied rate = USDT price / GBP price
4. Apply smoothed rate (95% implied + 5% fiat) for stability

### Outlier Detection

Prices beyond `MAX_PRICE_DEVIATION` from median are excluded:
- 3% accommodates normal market spread and minor conversion variance
- Sources flagged as outliers don't contribute to consensus
- Minimum 2 sources required for valid consensus
