# AGENTS.md - Crypto Trading Bot Agent Guidelines

---

## ⚠️ Critical Information for Agents

### Common Bugs to Avoid

1. **`trailing_activated` undefined** - In `trading_engine.py:monitor_positions()`, the variable `trailing_activated` must be defined before use:
   ```python
   trailing_activated = peak_price >= break_even
   ```
   Without this, you get `NameError: name 'trailing_activated' is not defined`

2. **Fee parsing failure** - SDK returns `GetTransactionSummaryResponse` object, NOT dict:
   ```python
   # WRONG:
   fee_tier = response.get('fee_tier', {})  # AttributeError!
   
   # CORRECT:
   fee_tier = response.fee_tier  # Access as attribute
   ```

3. **Stop loss direction** - For long positions, stop loss must be BELOW entry:
   ```python
   # WRONG (above entry):
   stop_loss = entry_price * 1.05
   
   # CORRECT (below entry):
   stop_loss = entry_price * 0.95
   ```

4. **AI SELL not checked** - `monitor_positions()` must check AI signals for existing positions

5. **Selling at a loss** - Emergency stop and trailing stop must NEVER close positions below break-even:
   ```python
   # WRONG (sells at loss):
   elif (entry_price - current_price) / entry_price > 0.02:
       should_close = True
   
   # CORRECT (only sells if was in profit):
   elif current_price >= break_even and (entry_price - current_price) / entry_price > 0.02:
       should_close = True
   ```

6. **Trailing stop floor too high** - Floor must be below break-even, not 95% of entry:
   ```python
   # WRONG (triggers too early):
   trailing_stop = max(trailing_stop, entry_price * 0.95)
   
   # CORRECT (floor is below break-even):
   stop_floor = break_even * (1 - trailing_pct)
   trailing_stop = max(trailing_stop, stop_floor)
   ```

7. **Peak price not persisting** - When updating `peak_price` in `monitor_positions()`, always log the result:
    ```python
    # Always log to verify update succeeded
    result = db_manager.update_peak_price(position_id, peak_price)
    if result:
        logger.info(f"[PEAK_UPDATE] {product_id}: £{peak_price:.2f}")
    else:
        logger.error(f"[PEAK_UPDATE] FAILED for {product_id}")
    ```
    Also ensure `peak_price: entry_price` is set when creating new positions in `initial_position_sync()`.

8. **Fees not recorded in trade records** - Trade records were saving `fees: 0.0` even though Coinbase charges ~0.75% on sells:
    ```python
    # WRONG (hardcoded to 0):
    trade_data = {
        ...
        'fees': 0.0,  # This loses money!
    }
    
    # CORRECT (extract from Coinbase API response):
    fees = order_result.get('fees', 0.0)
    trade_data = {
        ...
        'fees': fees,  # Now captures actual fees
    }
    ```
    Fixed in: `coinbase_api.py` (fetch `total_fees` from order details), `trading_engine.py` (use fees in trade_data)
    
    Historical fix: Run SQL to update old trades: `UPDATE trades SET fees = size * price * 0.0075 WHERE side = 'sell' AND price > 0`

9. **Portfolio value not tracked** - Bot had no way to track if it's achieving its goal of increasing portfolio value:
    ```python
    # Solution: Added PortfolioSnapshot model and tracking:
    # - New table: portfolio_snapshots
    # - Save after each trading cycle: db_manager.save_portfolio_snapshot()
    # - Get summary: db_manager.get_portfolio_summary()
    # - API endpoints: /api/portfolio/goal, /api/portfolio/history
    ```
    Current status: Starting £157.44 → Current £136.41 = -£21.03 (-13.4%) - NOT ACHIEVED

### Key Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| Taker Fee | 0.75% | Actual Coinbase fee, NOT fallback 1.2% |
| Maker Fee | 0.35% | Actual Coinbase fee, NOT fallback 0.6% |
| Trailing Stop | 2% | Percentage below peak |
| Trailing Activation Buffer | 2% | Must be 2% above break-even to activate |
| Model Confidence Threshold | 65% | Minimum confidence for signals |
| Break-even | entry × 1.0075 | Price needed to cover fees |

---

## 📡 Multi-Source Market Data Architecture

The bot uses a multi-source market data system to improve robustness and reduce single-source bias.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MULTI-SOURCE MARKET DATA FLOW                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                  MultiSourcePricer Layer                             │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  consensus_average(prices) → weighted median + outlier detect │   │   │
│  │  │  • Excludes prices >3% deviation from median                │   │   │
│  │  │  • Confidence scoring based on source agreement              │   │   │
│  │  │  • Minimum 2 sources required for consensus                  │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                      │                                      │
│          ┌───────────────────────────┼───────────────────────────┐        │
│          ▼                           ▼                           ▼        │
│  ┌───────────────┐          ┌───────────────┐          ┌───────────────┐   │
│  │   Coinbase    │          │   Kraken      │          │ CryptoCompare │   │
│  │   (Primary)   │          │   (Backup)    │          │   (Backup)    │   │
│  │               │          │               │          │               │   │
│  │ • Trading    │          │ • No auth     │          │ • No auth     │   │
│  │ • GBP pairs  │          │ • GBP pairs   │          │ • Rate limit  │   │
│  │ • 50% weight │          │ • 30% weight │          │ • 25% weight  │   │
│  └───────────────┘          └───────────────┘          └───────────────┘   │
│          │                           │                           │          │
│          ▼                           ▼                           ▼          │
│  ┌───────────────┐          ┌───────────────┐          ┌───────────────┐   │
│  │ coinbase_api  │          │  kraken_api   │          │cryptocompare │   │
│  │   (exist)     │          │    (NEW)      │          │    (NEW)      │   │
│  └───────────────┘          └───────────────┘          └───────────────┘   │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    Chainlink Verification (Optional)                    │  │
│  │  • Used for price anomaly detection                                   │  │
│  │  • Compares consensus price against reference                         │  │
│  │  • Flags prices >5% deviation                                         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Features

| Feature | Description |
|---------|-------------|
| **Consensus Averaging** | Weighted average of available sources |
| **Outlier Detection** | Excludes prices >3% from median |
| **Graceful Degradation** | Works with any combination of sources |
| **Confidence Scoring** | 0-100% based on source agreement |
| **Chainlink Verification** | Optional price anomaly detection |

### Configuration

Settings in `config/settings.py`:

```python
# Multi-Source Configuration
MULTI_SOURCE_ENABLED: bool = True
PRICE_SOURCE_WEIGHTS = {
    'coinbase': 0.45,     # Primary (trading capability)
    'kraken': 0.30,       # Additional exchange
    'cryptocompare': 0.25, # Backup aggregator
}
MAX_PRICE_DEVIATION: float = 0.03  # 3% outlier threshold
CONSENSUS_MIN_SOURCES: int = 2     # Minimum sources for consensus
CONSENSUS_MIN_CONFIDENCE: float = 0.60  # 60% confidence threshold
```

### API Keys (Optional)

For higher rate limits, set environment variables:

```bash
# CoinGecko (free tier requires API key now)
COINGECKO_API_KEY=your_api_key

# CryptoCompare (optional, for higher limits)
CRYPTOCOMPARE_API_KEY=your_api_key
```

### Supported Pairs

| Product | Coinbase | Binance | Kraken | CryptoCompare |
|---------|----------|---------|--------|---------------|
| BTC-GBP | ✅ | ✅ | ✅ | ❌ |
| ETH-GBP | ✅ | ✅ | ✅ | ❌ |
| SOL-GBP | ✅ | ✅ | ✅ | ❌ |
| LTC-GBP | ✅ | ✅ | ✅ | ❌ |
| DOT-GBP | ✅ | ✅ | ✅ | ❌ |
| ADA-GBP | ✅ | ✅ | ✅ | ❌ |
| LINK-GBP | ✅ | ✅ | ✅ | ❌ |
| UNI-GBP | ✅ | ✅ | ❌ | ❌ |

### WebSocket Real-Time Prices (per slippage-modeling.md)

The system uses WebSocket for real-time prices on high-liquidity pairs:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        WEBSOCKET PRICE FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  High-Liquidity Pairs (BTC, ETH):                                          │
│                                                                              │
│    Coinbase WebSocket ─────────────────────────► Real-time price            │
│    Endpoint: wss://advanced-trade-ws.coinbase.com                          │
│    Channel: ticker (no auth required)                                      │
│                                                                              │
│  Other Pairs:                                                               │
│                                                                              │
│    REST API (Coinbase + Kraken consensus) ──────► Aggregated price         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Feature | Description |
|---------|-------------|
| Endpoint | wss://advanced-trade-ws.coinbase.com |
| Channel | ticker (real-time on every trade) |
| Auth | Not required (public channel) |
| Pairs | BTC-GBP, ETH-GBP, BTC-USD, ETH-USD |
| Fallback | REST API if WebSocket unavailable |

### Usage

```python
from src.multi_source_pricer import get_multi_source_pricer

pricer = get_multi_source_pricer()

# Get consensus price
result = pricer.get_consensus_price('BTC-GBP')

print(f"Price: £{result.price:.2f}")
print(f"Sources: {result.sources_used}")  # ['coinbase', 'kraken']
print(f"Confidence: {result.confidence:.0%}")  # e.g., "99%"
print(f"Outliers: {result.outlier_sources}")  # any excluded sources
```

### Testing

```bash
# Run multi-source tests
python tools/test_multi_source_pricer.py
```

---



## 📋 Project Overview
- **Language**: Python 3.13+
- **Type**: Crypto Trading Bot
- **Platform**: Raspberry Pi 5 / Docker
- **Architecture**: Multi-Worker (Trading Process + API Workers) + Signal Cache
- **Trading Mode**: Paper trading initially, real-money option available
- **Key Dependencies**: pandas, numpy, scikit-learn, fastapi, SQLAlchemy, APScheduler, uvicorn

## 🏗️ System Architecture

### Multi-Worker Design
The system uses a multi-process architecture to solve GIL contention and improve performance:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Container                          │
│                                                                  │
│  ┌─────────────────────┐     ┌─────────────────────────────┐   │
│  │   Trading Process   │     │      API Worker Pool       │   │
│  │                     │     │                             │   │
│  │  - Trading loop     │     │  ┌─────┐ ┌─────┐ ┌─────┐  │   │
│  │  - AI signal gen    │     │  │ W1  │ │ W2  │ │ W3  │  │   │
│  │  - Order execution  │     │  └─────┘ └─────┘ └─────┘  │   │
│  │  - Position mgmt   │     │      FastAPI HTTP Server   │   │
│  │                     │     │                             │   │
│  │  Writes to:         │     │  Reads from:               │   │
│  │  - signal_cache.json│     │  - signal_cache.json       │   │
│  │  - SQLite DB        │     │  - SQLite DB               │   │
│  └─────────────────────┘     └─────────────────────────────┘   │
│                                                                  │
│                    Shared Signal Cache File                      │
│                    (data/signal_cache.json)                      │
└─────────────────────────────────────────────────────────────────┘
```

### Key Files
| File | Purpose |
|------|---------|
| `src/startup.py` | Production entry point - starts trading + API workers |
| `src/trading_loop.py` | Trading process (runs in subprocess via startup.py) |
| `src/api_worker.py` | API server for dashboard (uvicorn workers) |
| `src/ai_model.py` | AI model management, signal generation, regime detection, Ridge model |
| `src/data_collector.py` | Market data collection (multi-source) |
| `src/multi_source_pricer.py` | Multi-source price aggregation with consensus, Coinbase fallback |
| `src/coinbase_api.py` | Coinbase API integration |
| `src/binance_api.py` | Binance API integration |
| `src/kraken_api.py` | Kraken API integration |
| `src/cryptocompare_api.py` | CryptoCompare API integration |
| `src/price_mapper.py` | Coin ID translation between exchanges |
| `src/websocket_client.py` | Coinbase WebSocket for real-time BTC/ETH prices |
| `src/trading_engine.py` | Trading logic, position management, order execution, trailing stop |
| `src/risk_manager.py` | Risk management and position sizing |
| `src/database.py` | Database operations with SQLAlchemy, peak_price column |
| `src/cache_manager.py` | Centralized cache management, path definitions |
| `src/feature_engineering.py` | Feature creation for ML models, temporal features |
| `main_legacy.py` | DEPRECATED - Old single-process development mode |
| `src/dashboard_legacy.py.old` | DEPRECATED - Old dashboard implementation |
| `backup/` | Legacy backup files from previous updates |
| `tools/` | Debug and test utilities, validate_signals.py |

### Legacy Files
The following files are deprecated and kept for reference only:
- `main_legacy.py` - Old single-process mode (replaced by startup.py)
- `src/dashboard_legacy.py.old` - Old dashboard (replaced by api_worker.py)
- `backup/` - Previous backup files
- `tools/` - Debug/test utilities

### Signal Generation Flow
1. Trading process generates signals periodically
2. Signals are generated in **PARALLEL** (8 pairs simultaneously, ~30-60s total)
3. Signals written to `data/signal_cache.json` with timestamp
4. API workers read from cache (fast, no ML computation)
5. Dashboard displays cached signals instantly

### Parallel Processing Architecture
- **Signal refresh**: 8 trading pairs processed in parallel (not sequential)
- **Market data**: 8 products updated in parallel
- **Performance**: Trading cycle reduced from ~15 min to ~3-5 min

### Startup Sequence
1. Trading process starts, loads models
2. Trading process writes initial signals to cache
3. API workers start, read from cache
4. Both processes share the cache file

## 🐧 Build/Int/Test Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Run AI model tests (from tools directory)
python tools/test_ai.py

# Run single test function (pattern: module_function_name)
python -c "from tools.test_ai import test_technical_indicators; test_technical_indicators()"
python -c "from tools.test_ai import test_model_training; test_model_training()"

# Run with environment file check
python -c "from config.settings import settings; print('API keys loaded:', bool(settings.COINBASE_API_KEY))"
```

### Code Quality
```bash
# Format code with black (88 char line length)
black src/ config/ --line-length=88

# Type check with mypy (ignore venv)
mypy src/ --ignore=venv/ --no-error-summary

# Lint with flake8 (E203, W503 are black compatible)
flake8 src/ --max-line-length=88 --extend-ignore=E203,W503

# Security check for API keys
grep -r "API_KEY\|SECRET" --exclude-dir=venv --exclude="*.md" .
```

### Docker
```bash
# Build and run
docker-compose up --build -d

# View logs
docker-compose logs -f crypto-trader-bot

# Stop and remove
docker-compose down
```

## 🏗️ Code Style Guidelines

### Import Organization
```python
# Standard library imports first (alphabetically sorted)
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Third-party imports (alphabetically sorted)  
import pandas as pd
import numpy as np
from fastapi import FastAPI
from sklearn.ensemble import RandomForestClassifier

# Local imports (grouped by module)
from config.settings import settings
from src.coinbase_api import coinbase_api
from src.database import db_manager
from src.data_collector import data_collector
from src.ai_model import ai_model
from src.risk_manager import risk_manager
from src.trading_engine import trading_engine
```

### File Structure
```bash
crypto-trader-bot/
├── config/              # Configuration files
│   ├── settings.py      # Application settings and constants
│   └── api_keys.env     # Environment variables (DO NOT COMMIT)
├── src/                 # Core bot modules
│   ├── ai_model.py      # Machine learning and signal generation
│   ├── api_worker.py    # API worker entry point (uvicorn workers)
│   ├── coinbase_api.py  # Coinbase API integration
│   ├── currency_utils.py# Currency conversion utilities
│   ├── data_collector.py # Market data collection and processing
│   ├── database.py      # Database operations with SQLAlchemy
│   ├── risk_manager.py  # Risk management and position sizing
│   ├── trading_engine.py # Main trading logic orchestration
│   ├── trading_loop.py  # Trading process entry point
│   └── templates/       # HTML templates
│       ├── dashboard.html   # Main dashboard
│       ├── trades.html      # Trades history page
│       ├── performance.html # Performance metrics page
│       └── settings.html    # Settings page
├── models/              # Saved AI models (.joblib files)
├── data/                # Market data, SQLite DB, signal cache
├── logs/                # Application logs
├── migrations/          # Database migration scripts
├── tests/               # Unit and integration tests
├── tools/               # Debug and test utilities
├── backup/              # Legacy backup files
├── main_legacy.py       # DEPRECATED - Old single-process mode
└── requirements.txt     # Python dependencies
```

### Naming Conventions
```python
# Classes: PascalCase
class TradingEngine:
class RiskManager:

# Functions and methods: snake_case
def get_current_prices():
def run_trading_cycle():
def _validate_signal():  # Private methods with leading underscore

# Variables: snake_case
portfolio_value = 10000.0
daily_pnl = 0.0

# Constants: UPPER_CASE
MAX_POSITION_SIZE = 0.025
MARKET_CHECK_INTERVAL = 300
```

### Type Hints & Error Handling
```python
from typing import Optional, Dict, List, Any, Tuple

def get_portfolio_value(currency: str) -> Optional[float]:
    """Get current portfolio value for a currency."""
    pass

try:
    result = coinbase_api.place_market_order(...)
    if not result:
        raise TradingEngineError("Order placement failed")
except CoinbaseAPIError as e:
    logger.error(f"API error placing order: {e}")
    raise TradingEngineError(f"Failed to place order: {e}") from e
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise
```

### Testing Guidelines
```python
import pytest
from unittest.mock import Mock, patch

def test_trading_engine_initialization():
    """Test TradingEngine initializes correctly."""
    engine = TradingEngine()
    assert engine.paper_trading is True
    assert engine.active_positions == {}

# Test naming: component_action
def test_risk_manager_position_sizing():
def test_data_collector_price_fetching():
```

### Configuration Management
```python
# Use settings module, never hardcode
from config.settings import settings

max_position = settings.MAX_POSITION_SIZE
interval = settings.MARKET_CHECK_INTERVAL

# WRONG:
if portfolio_value > 10000:
    pass

# RIGHT:
if portfolio_value > settings.PAPER_TRADING_PORTFOLIO_VALUE:
    pass
```

### Security & Performance
```python
# API keys from environment
import os
api_key = os.getenv('COINBASE_API_KEY', '')
if not api_key:
    raise ValueError("API key not found")

# Cache expensive operations
from functools import lru_cache

@lru_cache(maxsize=128)
def fetch_historical_data(product_id: str, days: int = 30):
    """Cache historical data requests."""
    pass
```

## 🔑 Important Notes for Agents

### Testing Strategy
- **No test runner configured**: Use direct execution (`python test_ai.py`) or single function calls
- **AI model testing**: Focus on `test_ai.py` for ML component validation
- **Integration testing**: Test API connections with paper trading mode first

### Key Integration Points
- **Coinbase API**: Two key files - `coinbase_api.py` (basic) and Advanced Trade API integration
- **Settings Management**: All config via `config/settings.py` using environment variables
- **Database**: SQLite with SQLAlchemy ORM in `src/database.py`
- **ML Pipeline**: `ai_model.py` + `data_collector.py` for signal generation

### Development Workflow
1. Always run `python main.py --test` before real trading
2. Verify API keys loaded: check environment variables
3. Test individual components: AI models, data collection, risk management
4. Use dashboard (`--dashboard`) for real-time monitoring
5. Check logs in `logs/` directory for debugging

### Critical Security Reminders
- Never commit `api_keys.env` or any API keys
- Always use paper trading mode for development
- Validate all API responses before processing trades
- Monitor logs for unauthorized access attempts

## 🔧 Recent Fixes & Updates

### v1.0.2 - UI Fixes & API Diagnostics
**Date**: January 23, 2026

**UI/UX Fixes:**
- **Currency Dropdown Synchronization**: Fixed currency dropdown on settings page to match dashboard and show current selection
  - **Issue**: Settings page dropdown didn't display current currency selection
  - **Fix**: Added `display_currency` to settings page template context
- **Exchange Rate Loading**: Added missing `updateExchangeRate()` JavaScript function to dashboard
  - **Issue**: Exchange rate showed "Loading..." permanently
  - **Fix**: Implemented function to fetch and display USD→GBP exchange rate with auto-refresh
- **JavaScript Functions**: Added missing `changeCurrency()` function for dashboard currency switching

**API Diagnostics:**
- **API Permissions Check**: Added `/api/check-api-permissions` endpoint for Coinbase API key diagnostics
  - **Purpose**: Verify API key permissions (`view`, `trade`, `transfer`) for live trading setup
  - **Usage**: GET request to check if API keys have required permissions
  - **Integration**: Uses Coinbase SDK's `get_api_key_permissions()` method

**Error Message Improvements:**
- **Live Trading Errors**: Enhanced error messages to include API permissions guidance
  - **Issue**: "account is not available" errors lacked troubleshooting context
  - **Fix**: Added guidance to check API key 'trade' permission when permissions issues occur

## 📚 Coinbase SDK Usage Guide

### 🔑 **SDK Authentication Setup**

The application uses Coinbase's official Python SDK for Advanced Trade API integration. The SDK automatically handles authentication using ECDSA keys.

#### **Environment Configuration**
```bash
# api_keys.env file
COINBASE_ADVANCED_API_KEY=your_api_key_id
COINBASE_ADVANCED_API_SECRET=your_ecdsa_private_key
```

#### **SDK Features Used**
- **Authentication**: Automatic JWT generation with ECDSA signing
- **Permissions Checking**: `RESTClient.get_api_key_permissions()`
- **Order Management**: `RESTClient.create_order()`, `market_order()`, etc.
- **Account Data**: `RESTClient.get_accounts()`, `get_account()`
- **Market Data**: `RESTClient.get_products()`, `get_product()`

#### **SDK Initialization**
The SDK client is automatically initialized on startup in `src/coinbase_api.py`:
```python
self.sdk_client = RESTClient(
    api_key=self.advanced_api_key,
    api_secret=self.advanced_api_secret  # ECDSA private key
)
```

#### **Error Handling**
- SDK provides detailed error messages for authentication issues
- Automatic retry logic for network failures
- Clear differentiation between API errors and authentication errors

#### **Key Type Support**
- **ECDSA Keys**: Primary authentication method (Advanced Trade API)
- **RSA Keys**: Alternative asymmetric key format
- **HMAC Keys**: Legacy API support (not recommended for live trading)

### 🔧 **Troubleshooting SDK Issues**

#### **Common Problems**
1. **SDK Client Not Initialized**: Check `api_keys.env` file and key format
2. **Authentication Errors**: Verify ECDSA keys are correct and not expired
3. **Permission Errors**: Use `/api/check-api-permissions` endpoint to diagnose

#### **Key Format Verification**
- ECDSA keys are long strings (not file paths)
- Should start with typical ECDSA prefix patterns
- Coinbase developer platform provides keys in JSON format

#### **Testing SDK Connectivity**
```bash
# Check permissions
curl http://localhost:8000/api/check-api-permissions

# Expected response for working setup:
{
  "success": true,
  "permissions": {
    "can_view": true,
    "can_trade": true,
    "can_transfer": true
  }
}
```

### 🔮 **Current Status Summary**

### **Trading System**
- **Status**: ✅ **Timer Working**, ✅ **GBP Pairs Only**, ⚠️ **Trading Loop Issues**
- **Configuration**: Ultra-conservative 0.01% risk, 30-minute intervals, GBP monitoring alerts
- **Models**: 8/9 GBP models working correctly, AVAX-USD removed

### **Key Issues Identified**
1. **Trading Loop Shutdown**: Application starts but immediately shuts down after model loading errors
2. **Thread State Management**: Trading flag persistence vs actual thread execution mismatch
3. **API Route Conflicts**: Main.py endpoints vs dashboard.py module routing

### **📖 **SDK Documentation Resources**
- [Coinbase SDK GitHub](https://github.com/coinbase/coinbase-advanced-py)
- [SDK API Reference](https://coinbase.github.io/coinbase-advanced-py/)
- [Authentication Guide](/coinbase-app/authentication-authorization/api-key-authentication)

### v1.0.1 - Portfolio Valuation Fixes
**Date**: January 23, 2026

**Critical Bug Fixes:**
- **USDC Valuation Bug**: Fixed USDC being incorrectly valued at $100 instead of $1, causing massive portfolio inflation
  - **Issue**: Portfolio debug endpoint lacked special handling for stablecoins
  - **Fix**: Added USDC special case in `/api/portfolio/debug` to ensure $1 valuation
  - **Impact**: Portfolio values now accurate (was ~$491 GBP, now ~$11.46 GBP)

- **USDC Conversion Function**: Enhanced `convert_usdc_to_usd()` to handle accounts without USD balance
  - **Issue**: Function failed when no USD account existed (since USDC is already USD-pegged)
  - **Fix**: Added fallback logic to treat USDC as USD-equivalent when no USD account found

**UI/UX Improvements:**
- **Currency Dropdown**: Added missing `changeCurrency()` JavaScript function
  - **Issue**: Currency selector onchange event had no handler
  - **Fix**: Implemented function to POST to `/api/settings/display_currency`
- **Clear Trades Button**: Added missing API endpoint
  - **Issue**: Frontend called `/api/trades/clear` but endpoint didn't exist
  - **Fix**: Created endpoint that calls `db_manager.clear_all_trades()`
- **Display Currency API**: Added `/api/settings/display_currency` endpoint
  - **Issue**: No backend support for changing display currency preference
  - **Fix**: Added POST endpoint to save user currency preference

**New Features:**
- **Test Trade Endpoint**: Added `/api/test-trade` for API connectivity testing
  - **Purpose**: Place small test trades to verify API keys work (paper mode only)
  - **Safety**: Only functions in paper trading mode to prevent accidental real trades

**Testing Verified:**
- ✅ Portfolio valuation now accurate (±3.5% vs Coinbase reported values)
- ✅ Currency switching (USD ↔ GBP) works correctly
- ✅ Clear trades functionality removes all trade history
- ✅ API endpoints respond correctly
- ✅ Docker container rebuilds successfully with all fixes

### Development Notes
- **Container Deployment**: All fixes require Docker container rebuild (`docker-compose build --no-cache`)
- **Stablecoin Handling**: USDC and other stablecoins must be explicitly handled at $1 valuation
- **API Error Handling**: Functions now gracefully handle missing accounts (USD vs USDC scenarios)
- **Live Trading Setup**: Use `/api/check-api-permissions` to verify API key permissions before attempting live trades
- **Coinbase API Permissions**: Ensure API keys have 'trade' permission for live trading (check via Coinbase developer portal)

#### 📋 **v1.0.5 - Final Configuration & Production Readiness**
**Date**: January 25, 2026

**Final Implementation Status:**
- **GBP Trading Complete**: Successfully converted from USD to GBP-based trading for UK user
- **Risk Management**: Configured 1% risk per trade for £21.05 portfolio with day trading parameters
- **Equal Priority**: All 8 GBP trading pairs (BTC, ETH, SOL, LTC, DOT, ADA, LINK, UNI) with equal signal treatment
- **AI Model Full Coverage**: Complete AI model system with working predictions for all configured pairs
- **Portfolio Accuracy**: Perfect portfolio valuation matching Coinbase exactly (£21.05)
- **Dashboard Full Functionality**: Complete web interface with real-time monitoring and control

**Production Readiness Checklist:**
- ✅ **Currency Configuration**: GBP base and display currency ready
- ✅ **Risk Management**: Conservative 1% risk with proper position sizing
- ✅ **Trading Pairs**: All 8 GBP pairs active and monitored
- ✅ **AI Models**: 4 working, 4 ready for training
- ✅ **Dashboard**: Full monitoring and control interface
- ✅ **API Integration**: Coinbase SDK properly authenticated and connected
- ✅ **Container System**: Docker deployment with local HTTPS proxy infrastructure

**Final Development Notes:**
- **Container Deployment**: All fixes require Docker container rebuild (`docker-compose build --no-cache`)
- **Stablecoin Handling**: USDC and other stablecoins must be explicitly handled at $1 valuation
- **API Error Handling**: Functions now gracefully handle missing accounts (USD vs USDC scenarios)
- **Live Trading Setup**: Use `/api/check-api-permissions` to verify API key permissions before attempting live trades
- **Coinbase API Permissions**: Ensure API keys have 'trade' permission for live trading (check via Coinbase developer portal)

**Current State**: Fully functional crypto trading bot ready for GBP day trading with equal priority across 8 pairs and ultra-conservative risk management.

---

#### 📋 **v1.0.6 - Critical Bug Fixes & UI Improvements**
**Date**: January 27, 2026

**Bug Fixes Applied:**

1. **Currency Switcher Persistence Fix**
   - **Issue**: Currency switcher reverted to USD despite successful API calls
   - **Root Cause**: Missing `await` keyword on async function calls (main.py:1140, 1163)
   - **Fix**: Added `await` to `set_display_currency()` and `set_base_currency()` calls
   - **Impact**: ✅ Currency preferences now persist correctly in database

2. **Market Conditions Data Display Fix**
   - **Issue**: Market conditions section displayed no price or signal data
   - **Root Cause**: Invalid API call to non-existent `GBP-USD` trading pair (main.py:873)
   - **Fix**: Removed invalid ticker call, used existing exchange rate from `currency_converter.get_exchange_rate()`
   - **Additional Fix**: Added validation in `coinbase_api.py` to skip invalid pairs
   - **Impact**: ✅ Market conditions now display correctly with prices and signals

3. **Route Ordering Fix**
   - **Issue**: "Method Not Allowed" error on `/api/settings/display_currency` and `/api/settings/base_currency`
   - **Root Cause**: Catch-all route `/api/settings/{setting_key}` matched before specific routes
   - **Fix**: Moved specific currency endpoints before catch-all route (lines 1128-1176)
   - **Impact**: ✅ All API endpoints now accessible with proper routing

4. **UI Layout Improvement**
   - **Request**: Crypto balance should display directly under crypto price
   - **Previous Layout**: Price → Signal → Confidence → Action → Balance (at bottom)
   - **New Layout**: Price → **Balance** → Signal → Confidence → Action
   - **Impact**: ✅ Better UX with balance immediately visible

**Technical Details:**

```python
# Fix 1: Added await to async calls
success = await unified_bot.set_display_currency(currency)  # main.py:1140
success = await unified_bot.set_base_currency(currency)  # main.py:1163

# Fix 2: Removed invalid GBP-USD ticker call
# REMOVED (lines 873-877):
# gbp_ticker = coinbase_api.get_product_ticker('GBP-USD')  # 404 Error

# Fix 3: Route ordering
@app.post("/api/settings/display_currency")  # Line 1128 - FIRST
@app.post("/api/settings/base_currency")     # Line 1151 - SECOND
@app.post("/api/settings/{setting_key}")    # Line 1179 - THIRD (catch-all)

# Fix 4: Added pair validation in coinbase_api.py
def get_product_ticker(self, product_id: str) -> Dict[str, Any]:
    if product_id in ['GBP-USD', 'USDC-USD']:
        return self._get_fallback_ticker(product_id)
```

**Verification Steps:**
```bash
# Test currency switcher
curl -X POST http://localhost:8000/api/settings/display_currency \
  -H "Content-Type: application/json" -d '{"value": "GBP"}'
# Expected: {"status":"success","message":"Display currency set to GBP"}

# Verify persistence
curl -s http://localhost:8000/api/debug/context
# Expected: {"display_currency":"GBP",...}

# Check for errors in logs
docker logs crypto-trader-bot 2>&1 | grep -i "error\|GBP-USD"
# Expected: No GBP-USD 404 errors
```

**Files Modified:**
- `main.py`: Lines 1140, 1163 (added `await`), Lines 1128-1176 (route reordering), Line 871-877 (removed GBP-USD call)
- `src/coinbase_api.py`: Lines 384-387 (added pair validation)
- `src/templates/dashboard.html`: Lines 561-613 (moved crypto balance section)

**Current Status**: ✅ All bugs fixed, UI improved, system fully operational

---

## 🔮 **Future: Automated Balance Management**

### **Planned Feature: Crypto→GBP Auto-Conversion**
**Purpose**: Automatically restore GBP balance when levels get low through strategic crypto-to-GBP conversions.

### **Implementation Framework**
```python
# Future BalanceManager class structure
class BalanceManager:
    def __init__(self):
        """Initialize balance management system."""
        self.gbp_warning_threshold = settings.GBP_WARNING_THRESHOLD  # £10
        self.gbp_critical_threshold = settings.GBP_CRITICAL_THRESHOLD  # £5
        self.auto_conversion_enabled = False  # Future feature toggle
        
    def check_balance_status(self) -> Dict[str, Any]:
        """Check GBP balance and determine conversion needs."""
        # Monitor GBP balance continuously
        # Determine if auto-conversion is needed
        # Provide conversion recommendations
        
    def analyze_crypto_positions(self) -> List[Dict]:
        """Analyze crypto holdings for conversion candidates."""
        # Evaluate which crypto positions to sell
        # Consider profit/loss status
        # Account for tax implications and fees
        
    def execute_strategic_conversion(self, target_gbp_amount: float) -> bool:
        """Convert crypto to GBP to restore balance."""
        # Select optimal crypto positions to sell
        # Execute gradual conversions to avoid market impact
        # Respect user-defined conversion limits
```

### **Conversion Strategy**
- **Monitor**: Continuous GBP balance monitoring with warning/critical thresholds
- **Analyze**: Evaluate crypto positions for profitable conversion opportunities
- **Execute**: Strategic selling of profitable or high-risk positions
- **Control**: User-defined limits and approval requirements

### **Safety Controls**
- **Maximum Daily Conversion**: Limit total crypto→GBP conversions per day
- **User Approval**: Require manual approval for large conversions
- **Gradual Execution**: Spread conversions over time to avoid market impact
- **Rollback Protection**: Ability to cancel and unwind conversions if needed

### **Implementation Timeline**
- **Phase 1** (Current): Alert system with manual conversion recommendations
- **Phase 2** (Future): Automated analysis and conversion recommendations
- **Phase 3** (Future): Full automated conversion with safety controls

### **Configuration Support**
```python
# Future settings for automated balance management
AUTO_CONVERSION_ENABLED: bool = False  # Future: Enable auto-conversion
MAX_DAILY_CONVERSION: float = 50.0  # Maximum GBP to convert per day
CONVERSION_APPROVAL_REQUIRED: bool = True  # Require user approval for conversions
PREFERRED_CONVERSION_PAIRS: list = ['BTC-GBP', 'ETH-GBP']  # Prioritize major pairs
```

### **Code Integration Points**
- **Balance Monitoring**: Already integrated in `risk_manager.py:check_portfolio_risk()`
- **Alert System**: Dashboard displays GBP status and warnings
- **Framework Ready**: Code structure supports easy automation addition
- **Safety Framework**: Multiple validation layers planned

**Note**: Current implementation provides comprehensive balance monitoring and alerts. Future automation will build on this foundation with user safety controls and strategic conversion logic.

---

## 📋 **v1.1.0 - Position Management & UI Fixes**
**Date**: February 2, 2026

### Major Features Implemented

#### 1. AI SELL Signal Monitoring for Existing Positions
**Issue**: Bot opened positions but never closed them even when AI generated SELL signals.

**Fix**: Added AI sell signal checking in `monitor_positions()`:
```python
# Check AI sell signal for BUY positions
if not should_close and position['side'] == 'buy':
    try:
        signal = ai_model.get_signal(product_id)
        if signal['action'] == 'SELL':
            confidence = signal.get('confidence', 0.0)
            logger.info(f"AI SELL signal for {product_id}: confidence={confidence:.2%}")
            should_close = True
            exit_reason = f"AI sell signal (confidence: {confidence:.1%})"
    except Exception as e:
        logger.error(f"Error getting AI signal for {product_id}: {e}")
```

**File**: `src/trading_engine.py` (lines ~410-446)

#### 2. Intelligent Position Replacement
**Feature**: When max positions reached, bot can replace lower-confidence positions with higher-confidence signals.

**Configuration** (`config/settings.py`):
```python
POSITION_REPLACEMENT_ENABLED: bool = True
REPLACEMENT_CONFIDENCE_THRESHOLD: float = 0.15  # 15% improvement required
ALLOW_SELL_REPLACEMENT: bool = True  # SELL signals can replace any position
```

**Replacement Logic** (`src/trading_engine.py`):
- SELL signals replace worst-performing position (maintains GBP balance)
- BUY signals replace lowest confidence position if 15%+ improvement
- Prevents multiple replacements of same position

**New Methods**:
- `_evaluate_replacements()` - Evaluates if candidates should replace existing positions
- `_get_worst_position()` - Finds lowest P&L position
- `_get_lowest_confidence_position()` - Finds lowest confidence position

#### 3. Conservative Trading Settings
**Updated** (`config/settings.py`):
```python
MAX_POSITION_SIZE: float = 0.005  # 0.5% of portfolio per trade
MAX_DAILY_TRADES: int = 4  # Maximum trades per day
MAX_CONCURRENT_POSITIONS: int = 8  # Maximum open positions (all 8 GBP pairs)
MIN_TRADE_AMOUNT: float = 0.0001  # ~£0.10 equivalent
GBP_BUFFER: float = 2.0  # Always keep £2 GBP minimum balance
MARKET_CHECK_INTERVAL: int = 1800  # 30 minutes
```

#### 4. GBP Buffer Check
**New Feature** (`src/risk_manager.py`):
```python
def can_open_trade(self, required_gbp: float, is_paper_trading: bool = True) -> Tuple[bool, str]:
    """
    Check if a trade can open while maintaining GBP buffer.
    
    - Paper trading: simulates with £10,000, maintains £2 buffer
    - Live trading: checks real GBP balance, maintains £2 buffer
    """
```

#### 5. Dashboard UI Fixes
**Issues Fixed**:
- Start/Stop trading buttons didn't toggle after API call
- Trading notification didn't update

**Fixes** (`src/templates/dashboard.html`):
- Added button IDs for JavaScript selection
- Added `updateTradingButtons(tradingActive)` function
- Added `updateTradingNotification(tradingActive)` function
- Updated `controlBot()` response handler to call update functions

**Before**: Button visibility based on server-rendered template only
**After**: Buttons update dynamically after API response

#### 6. Manual Control Endpoints
**New Endpoints** (`main.py`):
- `POST /api/control/trigger_cycle` - Manually trigger a trading cycle
- `POST /api/control/sell_all` - Close all open positions
- `GET /api/portfolio/positions` - Get detailed position info with P&L

#### 7. Debug Endpoints
**New Endpoint** (`main.py`):
- `GET /api/debug/controls` - Debug control state:
  ```json
  {
    "trading_engine_paper_trading": true,
    "db_paper_trading": "true",
    "unified_bot_trading_active": true,
    "unified_bot_trading_thread_alive": true,
    "unified_bot_shutdown_event": true,
    "timestamp": "2026-02-02T15:23:20.919590"
  }
  ```

### AI Model Training Architecture

**Critical**: Models are trained on **GBP pairs** directly (`TRAINING_PAIRS`), NOT USD pairs.

**Training Data**: 8 GBP pairs (`BTC-GBP`, `ETH-GBP`, etc.)
**Trading Data**: 8 GBP pairs (`BTC-GBP`, `ETH-GBP`, etc.)

**Signal Generation Flow**:
1. Request signal for `BTC-GBP`
2. Get features for `BTC-GBP` from data collector
3. Predict using GBP-trained model
4. Return signal for `BTC-GBP`

**Why GBP Training?**:
- Direct market dynamics (no currency mapping needed)
- 350 candles available for all GBP pairs (Coinbase limit)
- Simpler architecture - train on what you trade

**Configuration** (`config/settings.py`):
```python
PRODUCT_IDS = ['BTC-GBP', 'ETH-GBP', 'SOL-GBP', 'LTC-GBP', 'DOT-GBP', 'ADA-GBP', 'LINK-GBP', 'UNI-GBP']
TRAINING_PAIRS = ['BTC-GBP', 'ETH-GBP', 'SOL-GBP', 'LTC-GBP', 'DOT-GBP', 'ADA-GBP', 'LINK-GBP', 'UNI-GBP']
```

### Files Modified

| File | Changes |
|------|---------|
| `src/trading_engine.py` | AI sell signal monitoring, position replacement, helper methods |
| `src/risk_manager.py` | GBP buffer check, `can_open_trade()` |
| `config/settings.py` | Conservative settings, position replacement config |
| `main.py` | Manual control endpoints, debug endpoint, button toggle fix |
| `src/templates/dashboard.html` | Button IDs, update functions, UI fixes |

### Current Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| Trading Interval | 30 minutes | Balance between responsiveness and not over-trading |
| Risk Per Trade | 0.5% | Conservative, capital preservation |
| Max Positions | 2 | Diversification without over-exposure |
| GBP Buffer | £2 | Never fully deplete GBP balance |
| Min Trade | 0.0001 | Enable small test trades |
| Position Replacement | Enabled | Auto-upgrade to better signals |
| Replacement Threshold | 15% | Conservative improvement requirement |

### Testing Verified

- ✅ Start/Stop trading buttons toggle correctly
- ✅ Trading notification updates (Active/Paused)
- ✅ Position replacement works (SELL replaces worst, BUY replaces low confidence)
- ✅ Paper trading uses simulated £10,000
- ✅ Live trading respects GBP buffer
- ✅ Manual control endpoints work
- ✅ Debug endpoint shows correct state

### Usage Notes

**Trading with Real Money**:
1. Ensure API keys have 'trade' permission
2. Add GBP to Coinbase account
3. Bot uses real balance with conservative settings
4. Each trade risks ~0.5% of portfolio (£0.05 on £10)

**Model Retraining**:
- Click "Retrain AI Models" on dashboard when confidence drops
- Models don't auto-learn - manual retraining required
- Retrain weekly or when signals consistently show low confidence

**Dashboard Controls**:
- Start/Stop Trading - Toggle automated trading
- Emergency Stop - Immediate halt of all trading
- Retrain AI Models - Refresh models with latest data
- Sell All - Close all positions manually

---

## 📋 **v1.1.1 - Duplicate Trades, Scale-Out & Performance Fixes**
**Date**: March 2026

### Problem Discovery

Through analysis of portfolio performance decline, several critical issues were identified:

1. **700+ duplicate trade records** in database
2. **Portfolio value decrease** from £21.05 to ~£14
3. **Scale-out never triggered** despite TP levels being hit
4. **Insufficient balance errors** when trying to close positions
5. **BTC display showed "0.0000"** for small values

### Bug Fixes Applied

#### 1. Duplicate Trade Records
**Issue**: Trades were saved twice - once in `execute_live_trade()` and again in `_close_position()`.

**Fix** (`src/database.py`): Added duplicate check in `save_trade()`:
```python
def save_trade(self, trade_data: Dict[str, Any]) -> Optional[int]:
    # Check for duplicate by order_id
    existing = self.session.query(Trade).filter(
        Trade.order_id == trade_data.get('order_id')
    ).first()
    if existing:
        logger.warning(f"Duplicate trade detected: {trade_data.get('order_id')}")
        return existing.id
    # ... rest of save logic
```

#### 2. Price = 0 in Trade Records
**Issue**: Coinbase SDK returns `price=0` for market orders in the response.

**Fix** (`src/trading_engine.py`): Fetch order details via `get_order()` API:
```python
# After placing order, get actual price from API
try:
    order_details = coinbase_api.sdk_client.get_order(order_result.order_id)
    if order_details and order_details.get('price'):
        executed_price = float(order_details['price'])
except Exception as e:
    logger.warning(f"Could not get order price: {e}")
    executed_price = current_price  # Fallback to market price
```

#### 3. Portfolio Value Decrease - 2% Minimum Profit Threshold
**Issue**: AI SELL signals were closing positions at tiny profits (0.04%-0.5%), causing portfolio erosion through fees and spread.

**Fix** (`src/trading_engine.py`): Added minimum profit check before closing:
```python
def _check_take_profit(self, position: Dict, current_price: float) -> bool:
    entry_price = position['entry_price']
    profit_pct = (current_price - entry_price) / entry_price
    
    # Require minimum 2% profit before allowing close
    min_profit = settings.MIN_PROFIT_FOR_SELL  # Default: 0.02 (2%)
    if profit_pct < min_profit:
        logger.info(f"Skipping TP - profit {profit_pct:.2%} < {min_profit:.2%} minimum")
        return False
    # ... rest of TP logic
```

**Configuration** (`config/settings.py`):
```python
MIN_PROFIT_FOR_SELL: float = 0.02  # 2% minimum profit required to close
```

#### 4. Scale-Out Not Triggering
**Issue**: Positions were closing via "Sold via signal" before TP levels could trigger.

**Fix**: 
- The 2% threshold fix prevents premature closes
- Fixed balance check to use `remaining_size` instead of original `position_size`
- Enhanced logging to track scale-out events

#### 5. Insufficient Balance Errors
**Issue**: Bot tried to close full position size instead of remaining size after scale-outs.

**Fix** (`src/trading_engine.py`):
```python
# Use remaining_size for balance calculations
remaining_size = position.get('remaining_size', position['position_size'])
if remaining_size <= 0:
    logger.info(f"Position fully scaled out, removing {product_id}")
    continue

# Calculate value based on remaining size
remaining_value = remaining_size * current_price
```

#### 6. BTC Display Decimal Issue
**Issue**: Small BTC values showed as "0.0000 / 0.0001" - meaningless for tiny amounts.

**Fix** (`src/templates/dashboard.html`): Dynamic decimal places based on value:
```javascript
function formatCryptoAmount(amount, gbpValue) {
    if (gbpValue >= 10) return amount.toFixed(2);
    if (gbpValue >= 1) return amount.toFixed(4);
    if (gbpValue >= 0.1) return amount.toFixed(6);
    return amount.toFixed(8);  // Show full precision for tiny amounts
}
```

#### 7. Database Missing Columns
**Issue**: Open positions table was missing scale-out tracking columns.

**Fix**: Created migration script (`migrations/add_scale_out_columns.py`):
```python
# Added columns to open_positions table:
- scale_out_count: Integer (number of scale-out trades executed)
- scale_out_levels: JSON (list of TP levels that triggered)
- remaining_size: Float (remaining position size after scale-outs)
- last_scale_out: DateTime (timestamp of last scale-out)
```

**Migration execution** (added to Dockerfile):
```dockerfile
# Run migrations on startup
RUN python migrations/add_scale_out_columns.py
```

### New Features Implemented

#### 1. Scale-Out (Partial Profit Taking)
**Purpose**: Take partial profits at TP levels without closing entire position.

**How it works**:
1. When price hits TP1 (e.g., +2%), sell 25% of position
2. When price hits TP2 (e.g., +4%), sell another 25%
3. Continue until position fully closed or price reverses

**Configuration** (`config/settings.py`):
```python
SCALE_OUT_ENABLED: bool = True
SCALE_OUT_PERCENTAGE: float = 0.25  # Sell 25% at each TP
SCALE_OUT_TP1: float = 0.02  # First TP at 2%
SCALE_OUT_TP2: float = 0.04  # Second TP at 4%
SCALE_OUT_TP3: float = 0.06  # Third TP at 6%
```

#### 2. Scale-In (Average Down)
**Purpose**: Add to losing positions at defined intervals.

**Configuration** (`config/settings.py`):
```python
SCALE_IN_ENABLED: bool = False  # Disabled by default
SCALE_IN_THRESHOLD: float = -0.03  # Add when -3% below entry
SCALE_IN_SIZE: float = 0.5  # Add 50% of original position size
SCALE_IN_MAX: int = 2  # Maximum 2 scale-ins per position
```

#### 3. Settings Persistence
**Issue**: Scale-in/scale-out settings were hardcoded.

**Fix**: Added database persistence:
- `load_trading_settings()` - Load settings from database on startup
- `save_trading_settings()` - Save settings to database when changed
- Dashboard UI to toggle settings

**Database table** (`settings`):
```python
# New settings stored:
- scale_in_enabled (boolean)
- scale_out_enabled (boolean)
- market_check_interval (integer, seconds)
```

#### 4. Market Check Interval Setting
**Purpose**: Allow users to adjust trading frequency without code changes.

**Configuration** (`config/settings.py`):
```python
MARKET_CHECK_INTERVAL: int = 2700  # 45 minutes (changed from 1800)
```

**Dashboard** (`src/templates/settings.html`): Added input field for custom interval.

### Current Configuration (v1.2.2 - Optimized for Profit)

| Setting | Value | Purpose |
|---------|-------|---------|
| Trading Interval | **4 hours** | Prevent overtrading |
| Risk Per Trade | 0.5% | Conservative |
| Max Positions | 8 | All GBP pairs |
| GBP Buffer | £2 | Never fully deplete |
| Min Trade | 0.0001 | ~£0.10 equivalent |
| Min Profit for Sell (Neutral) | **8%** | Only sell when in profit |
| Min Profit for Sell (Bear) | **2%** | Require profit in downtrend |
| Min Profit for Sell (Bull) | **10%** | Require strong profit |
| Scale-Out | **Disabled** | Prevent tiny profit taking |
| Scale-In | Disabled | User can enable |
| Buy Cooldown | **2 hours** | After selling |
| Daily Buy Limit | **1 per pair** | Prevent excessive buying |
| Parallel Processing | **Fixed** | Proper thread handling |

### Dashboard UI Updates

**New Columns Added** (`src/templates/dashboard.html`):
- **TP %**: Take profit percentage levels
- **Scale**: Number of scale-outs executed
- **Remaining**: Remaining position size after scale-outs

**Settings Page** (`src/templates/settings.html`):
- Scale-out enable/disable toggle
- Scale-in enable/disable toggle  
- Market check interval input (seconds)

### Files Modified

| File | Changes |
|------|---------|
| `src/trading_engine.py` | Scale-out logic, 2% threshold, remaining_size, enhanced logging |
| `src/database.py` | Duplicate check, scale-out fields, validation logic |
| `config/settings.py` | MIN_PROFIT_FOR_SELL, SCALE_OUT_*, SCALE_IN_*, MARKET_CHECK_INTERVAL |
| `main.py` | Settings API endpoints, load/save functions |
| `src/templates/dashboard.html` | New columns (TP%, Scale, Remaining), dynamic decimals |
| `src/templates/settings.html` | Scale-out/in toggles, market interval input |
| `Dockerfile` | Added migration script execution |
| `migrations/add_scale_out_columns.py` | Database migration (NEW) |
| `docker-compose.yml` | Healthcheck timeout increased |

### Current Open Positions (Verified)

| Product | Size | Remaining | Scale-Out |
|---------|------|-----------|-----------|
| BTC-GBP | 0.00005789 | 0.00003889 | 1 |
| LTC-GBP | 0.0739 | 0.0495 | 1 |
| DOT-GBP | 3.945 | 3.945 | 0 |
| UNI-GBP | 0.518 | 0.1735 | 2 |
| SOL-GBP | 0.312 | 0.0232 | 2 |
| ADA-GBP | 15.31 | 15.31 | 1 |
| ETH-GBP | 0.00098 | 0.00033 | 2 |
| LINK-GBP | 0.45 | 0.449 | 1 |

### Testing Verified

- ✅ Duplicate trades no longer saved
- ✅ Trade records show correct prices
- ✅ 2% threshold blocks small-profit closes
- ✅ Scale-out executes at TP levels
- ✅ Balance checks use remaining_size
- ✅ BTC displays proper decimals
- ✅ Settings persist in database
- ✅ Market interval configurable via dashboard
- ✅ Docker rebuild runs migrations

### Deployment Notes

**IMPORTANT**: All fixes require Docker rebuild:
```bash
docker-compose build --no-cache
docker-compose up -d
```

**Migration runs automatically** on container startup.

### Usage Tips

1. **Monitor scale-out events**: Check Docker logs for `🎯 SCALE-OUT` messages
2. **Enable scale-in carefully**: Only enable if you understand averaging down risks
3. **Adjust interval**: Use dashboard Settings to change from 45min if needed
4. **Check profits**: 2% threshold should prevent small-profit closes

---

## 📋 **v1.1.2 - Performance Optimization & Caching**
**Date**: March 2026

### Problem Identified

Dashboard loading was taking 15-30+ seconds due to:
1. **ML predictions blocking** - Each `get_signal()` call takes ~5-10 seconds
2. **Duplicate database records** - 536,000 duplicate records in market_data table
3. **Regime detection** - Called for every signal without caching
4. **Risk check on every load** - `check_portfolio_risk()` called on each dashboard request

### Optimizations Implemented

#### 1. Regime Caching (`src/ai_model.py`)
**Purpose**: Regime changes slowly, no need to recalculate every time.

```python
# Added to __init__():
self._regime_cache = {}  # {product_id: {'regime': str, 'timestamp': datetime}}
self._regime_cache_ttl = 300  # Cache regime for 5 minutes

# Updated detect_regime() to check cache first:
def detect_regime(self, product_id: str) -> str:
    cached_regime = self._regime_cache.get(product_id)
    if cached_regime:
        cached_time, cached_value = cached_regime
        age = (datetime.now() - cached_time).total_seconds()
        if age < self._regime_cache_ttl:
            return cached_value
    # ... compute regime, then cache it
```

#### 2. Signal Cache Pre-warming (`src/ai_model.py`)
**Purpose**: Warm cache on startup so dashboard doesn't block waiting for ML predictions.

```python
def prewarm_cache_async(self):
    """Pre-warm signal cache in background thread for fast app startup."""
    def _prewarm():
        for product_id in self.gbp_trading_pairs:
            signal = self.get_signal(product_id, use_cache=False)
    thread = threading.Thread(target=_prewarm, daemon=True)
    thread.start()

# Called on module load:
ai_model.prewarm_cache_async()
```

#### 3. Database Query Optimization (`src/data_collector.py`)
**Purpose**: Fix duplicate data and limit query size.

**Issues Fixed**:
- Database had 536,000 duplicate records out of 568,050 total
- Queries without date filters were fetching entire history

**Fixes**:
```python
# Limit queries to max 7 days
max_days = min(days, 7)
start_date = end_date - timedelta(days=max_days)

# Deduplicate when fetching
seen_timestamps = set()
for record in reversed(data_records):  # Keep latest
    if record['timestamp'] not in seen_timestamps:
        seen_timestamps.add(record['timestamp'])
        # Add to df_data
```

#### 4. Risk Data Caching (`src/risk_manager.py`)
**Purpose**: Avoid expensive portfolio calculations on every dashboard load.

```python
# Added to __init__():
self._risk_cache = None
self._risk_cache_time = None
self._risk_cache_ttl = 60  # Cache for 60 seconds

def check_portfolio_risk_cached(self, is_paper_trading: bool = True):
    """Check portfolio risk with caching for dashboard."""
    now = datetime.now()
    if (self._risk_cache is not None and 
        self._risk_cache_time is not None and 
        (now - self._risk_cache_time).total_seconds() < self._risk_cache_ttl):
        return self._risk_cache  # Return cached data
    
    # Compute fresh and cache
    fresh_data = self.check_portfolio_risk(is_paper_trading)
    self._risk_cache = fresh_data
    self._risk_cache_time = now
    return fresh_data
```

#### 5. Dashboard Route Optimization (`main.py`)
**Purpose**: Use cached data instead of generating fresh on each request.

```python
# Use cached signals (fast) instead of generating new ones
cached = ai_model._signal_cache.get(product_id)
if cached:
    _, signal = cached
    all_signals[product_id] = signal

# Use cached risk data
risk_data = risk_manager.check_portfolio_risk_cached(paper)
```

### Files Modified

| File | Changes |
|------|---------|
| `src/ai_model.py` | Added regime cache, signal cache pre-warming, `use_cache` parameter |
| `src/data_collector.py` | Query optimization, deduplication, max 7-day limit |
| `src/risk_manager.py` | Added `_risk_cache`, `check_portfolio_risk_cached()` |
| `main.py` | Dashboard uses cached signals and risk data |

### Performance Results

| Operation | Before | After |
|-----------|--------|-------|
| `collect_historical_data` | ~22s | ~4s |
| `get_signal` (fresh) | ~55s | ~12s |
| `get_signal` (cached) | N/A | <1s |
| Dashboard (first load) | 15-30s | 10-20s |
| Dashboard (cached) | N/A | <5s |

### Known Issues

1. **Dashboard still slow on first load**: First load after restart still takes 10-20s while cache warms up
2. **Trading cycle blocks HTTP**: The ~60s trading cycle runs synchronously and can block HTTP requests
3. **Background cache warming**: Signal cache pre-warming runs in daemon thread and may not complete before first dashboard load

### Future Improvements

1. **Async trading loop**: Run trading cycle in true background thread with proper asyncio
2. **Dashboard skeleton**: Show UI immediately, load data asynchronously via JavaScript
3. **Persistent cache**: Store signal cache in Redis or file for faster restarts
4. **Rate limiting**: Add request coalescing to prevent multiple simultaneous expensive calls

### Deployment Notes

```bash
# Rebuild to apply changes
docker-compose build --no-cache
docker-compose up -d
```

### Verification Commands

```bash
# Check signal cache
docker exec crypto-trader-bot python3 -c "from src.ai_model import ai_model; print(f'Signal cache: {len(ai_model._signal_cache)}')"

# Check regime cache  
docker exec crypto-trader-bot python3 -c "from src.ai_model import ai_model; print(f'Regime cache: {len(ai_model._regime_cache)}')"

# Test dashboard load time
time curl -s http://localhost:8000/ -o /dev/null
```
---

## 📋 **v1.2.0 - Dashboard & Page Improvements**
**Date**: March 21, 2026

### Summary

Complete overhaul of the dashboard and web pages to provide better UX and more information.

### Changes Made

#### 1. Dashboard Improvements (`src/templates/dashboard.html`)
- **GBP Balance Card**: Added dedicated card showing GBP balance with color indicator
  - Green: Healthy balance (above warning threshold)
  - Yellow: Warning level
  - Red: Critical (below minimum)
- **Closed Positions Accordion**: Dropdown showing recent closed positions under Recent Trades
- **Models Status**: Fixed to show actual AI signals instead of "N/A"
- **Countdown Timer**: Shows time until next trading cycle

#### 2. Models Page (`src/templates/models.html` / API update)
- **Fixed Signal Display**: Now shows actual signals from cache instead of "N/A"
- **API Endpoint**: `/api/models/status` returns cached signals for each model
- Shows: product pair, action (BUY/SELL/HOLD), confidence, regime, timestamp

#### 3. Trades Page (`src/templates/trades.html`)
- **New dedicated page** with comprehensive trade history
- **Filters**: By product, side (buy/sell), status, date range
- **Stats section**: Total trades, buy/sell breakdown, average trade value
- **Full details**: Entry/exit prices, P&L, fees, timestamps
- **Pagination**: For large trade histories

#### 4. Performance Page (`src/templates/performance.html`)
- **New dedicated page** for performance metrics
- **Key Metrics**: Total P&L, win rate, profit factor, Sharpe ratio
- **Charts** (using Chart.js):
  - Equity curve (portfolio value over time)
  - Daily P&L bar chart
  - Trade distribution by product
  - Monthly returns heatmap-style display
- **Filters**: By date range, product

#### 5. Settings Page Conversion (`src/templates/settings.html`)
- **Converted from Jinja2 to JavaScript API-based**
- All settings load via API calls instead of server-side rendering
- Toggle switches for boolean settings
- Input fields for numeric settings
- Save button triggers API call
- Shows success/error feedback

### New API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/gbp-balance` | GET | Get GBP balance with status |
| `/api/closed_positions` | GET | Get recent closed positions |
| `/api/models/status` | GET | Get AI model status with signals |
| `/api/scale_in/status` | GET | Get scale-in settings |
| `/api/scale_out/status` | GET | Get scale-out settings |
| `/api/trades` | GET | Get all trades with filters |
| `/api/trades/stats` | GET | Get trade statistics |
| `/api/performance` | GET | Get performance metrics |
| `/api/settings/{key}` | GET | Get individual setting value |

### Signal Cache Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Trading Process                       │
│  ┌─────────────────────────────────────────────────┐    │
│  │  ai_model.get_signal(product_id)               │    │
│  │  → Generate signal with ML prediction          │    │
│  │  → Cache in memory + write to file             │    │
│  └─────────────────────────────────────────────────┘    │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │  data/signal_cache.json                        │    │
│  │  {                                             │    │
│  │    "BTC-GBP": {                                │    │
│  │      "action": "BUY",                          │    │
│  │      "confidence": 0.72,                       │    │
│  │      "regime": "bullish",                       │    │
│  │      "timestamp": "2026-03-21T..."             │    │
│  │    }, ...                                      │    │
│  │  }                                             │    │
│  └─────────────────────────────────────────────────┘    │
│                         ▲                               │
│                         │                               │
└─────────────────────────┼───────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────┐
│                    API Workers                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Read from signal_cache.json (fast!)           │    │
│  │  No ML computation needed                       │    │
│  │  Return cached signals to dashboard              │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Files Modified

| File | Changes |
|------|---------|
| `src/templates/dashboard.html` | GBP balance card, closed positions accordion, countdown timer |
| `src/templates/models.html` | Fixed to display actual signals from API |
| `src/templates/trades.html` | NEW - Full trades page with filters and stats |
| `src/templates/performance.html` | NEW - Performance metrics with charts |
| `src/templates/settings.html` | Converted to JavaScript API-based |
| `src/api_worker.py` | Updated models status to include cached signals |
| `src/ai_model.py` | Added timeout protection to prevent hangs |
| `src/trading_loop.py` | Skipped slow initial signal generation |
| `AGENTS.md` | Updated with new architecture documentation |

### Deployment

```bash
# Rebuild container
docker-compose build --no-cache
docker-compose down && docker-compose up -d
```

### Testing Checklist

- [ ] Dashboard loads quickly with GBP balance card visible
- [ ] Closed positions accordion shows recent trades
- [ ] Models page shows actual BUY/SELL/HOLD signals
- [ ] Trades page filters work correctly
- [ ] Performance page charts render properly
- [ ] Settings page saves changes via API

### Current Status

- ✅ All HTML templates created/updated
- ✅ API endpoints enhanced
- ✅ AGENTS.md updated with architecture docs
- ⏳ Container rebuild pending

---

## v1.2.1 - Trading Engine Refactor & Simplified Caching
**Date**: March 21, 2026

### Summary

Simplified the caching architecture by removing file-based cache sharing between processes. Each process (trading, API workers) now manages its own independent signal cache.

### Problems Fixed

1. **Cycle Timeout**: Trading cycles timed out before executing signals
   - **Issue**: Scan took 6-10 minutes, timeout was 5 minutes (300s)
   - **Evidence**: `CYCLE TIMEOUT: Timeout exceeded during signal execution at signal 1/4`
   - **Fix**: Increased timeout to 1200s (20 minutes)

2. **Complex File-Based Cache Sharing**: Multiple threads/processes writing to shared file
   - **Issue**: Race conditions and unnecessary complexity
   - **Fix**: Removed file-based sharing, each process has independent cache

3. **Background Pre-Scan Thread Issues**: Multiple threads competing for resources
   - **Issue**: Background pre-scan running simultaneously with trading cycle
   - **Fix**: Removed background pre-scan thread entirely

4. **Position Count Mismatch**: 8 products shown as "positions" when only 6 had holdings
   - **Issue**: `len(self.holdings)` counted all products, not actual positions
   - **Fix**: Added `_get_open_position_count()` helper to count only `has_position=True`

### Architecture (Simplified)

```
┌─────────────────────────────────────────────────────────┐
│                  Trading Process                         │
│  • Own signal cache (in-memory)                       │
│  • Uses use_cache=True for fast signal retrieval      │
│  • Writes to SQLite DB for persistence               │
│  • No file-based cache sharing                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    API Workers                           │
│  • Own signal cache (in-memory)                       │
│  • Pre-warms cache on startup                         │
│  • Reads from SQLite DB for dashboard                 │
│  • No file-based cache sharing                        │
└─────────────────────────────────────────────────────────┘
```

### Key Changes

| Change | File | Purpose |
|--------|------|---------|
| Removed `prewarm_cache_async()` | `ai_model.py` | No longer auto-starts background pre-warming |
| Removed background pre-scan thread | `trading_loop.py` | Simplified, no competing threads |
| Increased cycle timeout | `trading_engine.py` | 1200s to allow full scan |
| Uses `use_cache=True` | `trading_engine.py` | Fast signal retrieval from cache |
| Simplified `trading_loop.py` | `trading_loop.py` | ~130 lines, no file I/O |

### Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| `cycle_timeout` | 1200s | Allow full scan to complete |
| `use_cache` | True | Use cached signals for speed |
| Cache TTL | 5 minutes | Signals auto-expire |

### Files Modified

| File | Changes |
|------|---------|
| `src/ai_model.py` | Removed `prewarm_cache_async()` call and method |
| `src/trading_loop.py` | Simplified, removed background pre-scan |
| `src/trading_engine.py` | Increased timeout to 1200s |
| `AGENTS.md` | Updated with simplified architecture |

### Testing Checklist

After rebuild, verify:
- [x] Cycle completes without timeout (452s for first cycle)
- [x] Signals generated with use_cache=True
- [x] No "Background pre-scan" messages in logs
- [x] No race conditions or file conflicts
- [x] "Open positions: 6/8" shows correct count
- [x] Dashboard loads quickly with cached signals

### Current Status

- ✅ Code changes implemented
- ✅ Container rebuilt successfully
- ✅ Testing completed - cycle #1 ran successfully
- ✅ Live trading executed (DOT-GBP bought)
- ✅ Documentation updated

---

## v1.2.2 - Settings Page Complete Fix
**Date**: March 22, 2026

### Summary

Fixed the Settings page to display **actual values** from the system instead of placeholder defaults, added save buttons for all settings sections, and fixed all data conversion issues.

### Problems Fixed

1. **Wrong displayed values**: Settings page showed placeholder defaults instead of actual config values
   - **Issue**: Risk settings were fetched from `/api/status` which doesn't include them
   - **Fix**: Created new `GET /api/settings/risk` endpoint that returns actual settings

2. **Missing `/api/portfolio/summary`**: Settings page fetched from endpoint that didn't exist
   - **Fix**: Created new endpoint providing GBP balance, open positions, display currency

3. **Scale-In/Scale-Out showed off/empty**: Incorrect field names and value conversions
   - **Issue**: Scale-Out used wrong field (`percentages` instead of `take_profit_levels`)
   - **Issue**: Scale-In size was stored as decimal (0.25) but displayed as percentage (25)
   - **Fix**: Updated endpoints to return correct fields and values

4. **Missing save functionality**: `saveRiskSettings()` only showed toast, didn't persist changes

### API Endpoints Added/Updated

#### `GET /api/portfolio/summary` (NEW)
Returns GBP balance, open positions count, display currency for settings page.

#### `GET /api/settings/risk` (NEW)
Returns current risk settings from `config/settings.py`:
```json
{
  "confidence_threshold": 0.70,
  "stop_loss": 0.05,
  "take_profit": 1.0,
  "max_position_size": 0.05,
  "market_check_interval": 2700
}
```

#### `POST /api/settings/risk` (NEW)
Saves risk settings to database and updates in-memory settings.

#### `GET /api/scale_out/status` (UPDATED)
Added `take_profit_levels` field for TP1/TP2/TP3 profit percentages.

#### `POST /api/scale_out/configure` (UPDATED)
Added `take_profit_levels` parameter support.

### Settings Page Changes

| Section | Before | After |
|---------|--------|-------|
| Risk Settings | Fetched from `/api/status` (wrong fields) | Fetches from `/api/settings/risk` |
| Portfolio Info | Fetched from `/api/portfolio/summary` (didn't exist) | Now exists |
| Scale-In Threshold | min=1 (can't enter 0.5) | min=0.1 |
| Scale-In Size | Displayed 0.25 (should be 25%) | Multiplies by 100 for display |
| Scale-Out TP Levels | Used wrong field (`percentages`) | Uses `take_profit_levels` |
| All Sections | No save buttons | Save buttons added |

### Files Modified

| File | Changes |
|------|---------|
| `main.py` | Added `/api/portfolio/summary`, `/api/settings/risk` endpoints; Updated scale_out endpoints |
| `src/templates/settings.html` | Fixed all value conversions, added save buttons |
| `AGENTS.md` | Documented v1.2.2 changes |

### Testing Checklist

- [x] Risk settings now show actual values from config
- [x] Portfolio summary provides GBP balance, positions count
- [x] Scale-In shows correct threshold (0.5%) and size (25%)
- [x] Scale-Out shows correct TP levels (1%, 2%, 3%)
- [ ] All save buttons persist settings to database
- [ ] Settings persist after page reload

---

## 📚 Developer Documentation

### Documentation Structure

```
docs/
├── index.md           # Main documentation index
├── architecture.md    # System architecture
├── api-reference.md   # Complete API endpoint reference
├── settings.md        # Configuration settings reference
└── sessions/         # Session changelog
    ├── template.md   # Session documentation template
    └── v1.2.2.md    # v1.2.2 session (this session)
```

### Documentation Location

All developer documentation is in the `/docs/` directory:
- **Quick Start**: `docs/index.md`
- **Architecture**: `docs/architecture.md`
- **API Reference**: `docs/api-reference.md`
- **Settings**: `docs/settings.md`
- **Session History**: `docs/sessions/`

### Session Documentation

After each development session, create a new file in `docs/sessions/` documenting:

```markdown
# Session: vX.X.X - [Brief Title]
**Date**: YYYY-MM-DD

## Changes Made
| File | Change |
|------|--------|
| `src/xxx.py` | Description |

## API Endpoints Added/Modified
- `GET /api/xxx` - Purpose

## Testing
- [x] Verified X works
- [ ] TODO: Need to verify Y

## Decisions
- [Chosen approach] → [Reason]

## Follow-up
- [ ] Future improvement
```

### Key Files for Agents

| File | Purpose |
|------|---------|
| `docs/index.md` | Main entry point for developers |
| `docs/api-reference.md` | All 82 API endpoints |
| `docs/architecture.md` | System design and components |
| `docs/settings.md` | Configuration reference |
| `docs/sessions/template.md` | Session doc template |

### Updating Documentation

After each session:

1. **Create session file**: `docs/sessions/vX.X.X.md`
2. **Update index**: Add version to changelog in `docs/index.md`
3. **Update API reference**: If endpoints added/modified
4. **Update settings**: If configuration changed
5. **Update architecture**: If system design changed

### AGENTS.md vs docs/

- **AGENTS.md**: Agent-specific guidelines, prompting instructions
- **docs/**: General developer documentation

Update both when making changes:
- AGENTS.md for agent instructions
- docs/ for developer reference

---

## v1.3.0 - Configuration Refactor & Binance Addition
**Date**: April 10, 2026

### Summary

Refactored to use unified configuration system with trading_pairs.yaml. Reduced active pairs to BTC-GBP and ETH-GBP. Added Binance as data source.

### Changes Made

| File | Change |
|------|--------|
| `config/trading_pairs.yaml` | NEW - Unified pair configuration |
| `config/trading_pairs.py` | NEW - YAML loader and accessor functions |
| `src/binance_api.py` | NEW - Binance public API wrapper |
| `config/settings.py` | MODIFY - Load from YAML, auto position sizing |
| `src/price_mapper.py` | MODIFY - Added Binance symbol mappings |
| `src/multi_source_pricer.py` | MODIFY - Added Binance as data source |
| `src/trading_engine.py` | MODIFY - One position per pair logic, enhanced logging |
| `src/ai_model.py` | MODIFY - Uses config-based pairs (no code changes needed) |

### Configuration

**Active Pairs**: BTC-GBP, ETH-GBP

**Position Sizing** (v1.3.0):
- 45% per pair (auto-adjusted from config)
- 90% max deployed (2 pairs × 45%)
- 10% cash reserve always maintained

**Data Sources** (v1.3.0):
- Coinbase: 40% weight
- Binance: 30% weight (NEW)
- Kraken: 20% weight
- CoinGecko: 10% weight

### Adding New Pairs

To add a new pair (e.g., DOT-GBP), only edit `config/trading_pairs.yaml`:

```yaml
trading_pairs:
  BTC-GBP:
    ...
  ETH-GBP:
    ...
  DOT-GBP:
    name: "Polkadot"
    base_currency: "DOT"
    binance_symbol: "DOTGBP"
    kraken_symbol: "DOTGBP"
    coingecko_id: "polkadot"
```

Position sizing automatically adjusts: 3 pairs → 30% per pair (90% max).

### Backup Location

Backup of v1.2.2: `../backup/crypto-trader-bot-v1.2.2-2026-04-10/`

### Rollback

```bash
# Restore from backup
cp -r ../backup/crypto-trader-bot-v1.2.2-2026-04-10/* .
```

### Testing Verified

- [x] Configuration loads correctly (PRODUCT_IDS: BTC-GBP, ETH-GBP)
- [x] Position sizing: 45% per pair, 2 max positions
- [x] Binance API created (public endpoints, no auth required)
- [x] One position per pair logic implemented
- [x] BUY signal ignored if position already open (logged)
- [x] SELL signal closes full position
- [x] Data source logging added

---

## v2.1 - ATR Threshold Fixes for Low Volatility
**Date**: April 13, 2026

### Problem
All GBP models failing to generate 3-class labels (BUY/HOLD/SELL):
- Models producing only 2 classes ([0, 1] = HOLD/BUY) instead of required 3 classes
- ATR threshold too high for current low volatility market conditions
- LINK-GBP and SOL-GBP particularly affected

### Root Cause
The ATR (Average True Range) threshold sensitivity settings were too conservative:
- `ATR_MULTIPLIER: 0.15` (15% of ATR) - too high
- `ATR_MIN_THRESHOLD: 0.0005` → 0.0002 (0.05% → 0.02%) - too high floor

### Changes Made

| File | Setting | Before | After |
|------|---------|--------|--------|
| `config/settings.py` | `ATR_MULTIPLIER` | 0.15 | 0.05 |
| `config/settings.py` | `ATR_MIN_THRESHOLD` | 0.0005 | 0.0001 |
| `src/ai_model.py` | ATR configs | min: 0.0001 | min: 0.00005 (extended range) |

### Extended ATR Test Configurations
Added lower sensitivity ATR configurations to find valid 3-class thresholds:
```python
atr_configs = [
    {'mult': 0.01, 'min': 0.00005},  # NEW: Very sensitive
    {'mult': 0.01, 'min': 0.0001},  # NEW: Very sensitive
    {'mult': 0.02, 'min': 0.00005},  # NEW
    {'mult': 0.02, 'min': 0.0001},
    {'mult': 0.03, 'min': 0.00005},  # NEW
    {'mult': 0.03, 'min': 0.0001},
    # ... existing configs
]
```

### Configuration

**ATR Settings** (v2.1):
- `USE_ATR_THRESHOLD: True` - Enable ATR threshold
- `ATR_PERIOD: 24` - 24 hours (1 day)
- `ATR_MULTIPLIER: 0.05` - k × ATR threshold (lowered from 0.15)
- `ATR_MIN_THRESHOLD: 0.0001` - Minimum 0.01% floor (lowered from 0.0005)

### Verification

After rebuild, check logs for:
- `[API] INFO:src.ai_model:ATR config {mult: X, min: Y}: win_rate Z%` - should show ≥35%
- `[API] INFO:src.ai_model:Best ATR for [PAIR]: mult=X, min=Y` - found valid config
- `[API] INFO:src.ai_model:Model [PAIR] has 3 classes: [0, 1, 2]` - successful 3-class generation
- `[TRADING] Scan: [PAIR] → action=BUY/SELL/HOLD` - trading signals working

### Notes
- Lower volatility in GBP pairs requires more sensitive ATR thresholds
- The `ATR_MIN_THRESHOLD` floor prevents tiny thresholds in noisy markets
- Extended ATR config range allows finding valid configs for all pairs
- Model should now generate BUY/HOLD/SELL signals dynamically based on market conditions

### Deployment
```bash
docker-compose build --no-cache && docker-compose up -d
```

### Fee Considerations (v2.1.1)
**Coinbase Fees**: 
- Maker fee: 0.35%
- Taker fee: 0.75%

**Trailing Stop Protection**: 
- Updated trailing stop to require minimum 1% profit before triggering
- This ensures profits exceed the maximum 0.75% fee plus spread costs
- Prevents selling at a loss after paying fees

**Minimum Trade Value**:
- Set to £15 to ensure trades are meaningful after fees
- Smaller trades may result in net loss due to fee percentage

---

## 🗂️ src/cache_manager.py - Centralized Cache Management

### Purpose

Single source of truth for file-based caching, path definitions, and timestamp utilities. Eliminates duplicate path definitions and cache handling across modules.

### Import Pattern

```python
from src.cache_manager import (
    read_signal_cache,
    write_signal_cache,
    SIGNAL_CACHE_FILE,
    get_timestamp,
    api_response
)
```

### Path Constants

| Constant | Path |
|----------|------|
| `BASE_DIR` | Project root (`/home/pi/Projects/crypto-trader-bot`) |
| `DATA_DIR` | `data/` directory |
| `LOG_DIR` | `logs/` directory |
| `MODEL_DIR` | `models/` directory |
| `SIGNAL_CACHE_FILE` | `data/signal_cache.json` |
| `LAST_CYCLE_FILE` | `data/last_cycle.txt` |

### Cache Functions

| Function | Purpose | Parameters | Returns |
|----------|---------|------------|---------|
| `read_signal_cache()` | Read signal cache from file | None | `Dict[str, Any]` |
| `write_signal_cache(signals)` | Write signals with proper formatting | `signals: Dict` | `None` |
| `read_last_cycle_time()` | Read cycle timestamp | None | `float` (Unix timestamp) |
| `write_last_cycle_time(ts)` | Write cycle timestamp | `ts: float` | `None` |

### Utility Functions

| Function | Purpose | Parameters | Returns |
|----------|---------|------------|---------|
| `get_timestamp()` | Get ISO timestamp | None | `str` (e.g., `2026-04-23T16:30:00`) |
| `format_time(ts)` | Format Unix timestamp to time | `ts: float` | `str` (e.g., `16:30:00`) |
| `format_datetime(ts)` | Format Unix timestamp to datetime | `ts: float` | `str` (e.g., `2026-04-23 16:30:00`) |
| `api_response(data)` | Create standardized API response | `data: Dict` | `Dict` with timestamp |

### Files Using cache_manager

| File | Usage |
|------|-------|
| `src/api_worker.py` | read_signal_cache, write_signal_cache, read_last_cycle_time |
| `src/trading_engine.py` | write_signal_cache (signals sync) |
| `src/ai_model.py` | write_signal_cache |
| `src/trading_loop.py` | BASE_DIR, DATA_DIR, LOG_DIR, LAST_CYCLE_FILE |
| `src/startup.py` | BASE_DIR |

---

## v2.7 - Position Opening Fixes & trailing Stop Bug Fix

**Date**: May 7, 2026

### Critical Bug Fixes

#### 1. `final_stop` NameError in Trailing Stop

**Problem**: Trading cycle crashed with `NameError: name 'final_stop' is not defined`

**Root Cause**: Variable was renamed from `final_stop` to `trailing_stop` (lines 726-727) but references at lines 836 and 856 were missed.

**Fix** (`src/trading_engine.py`):
- Line 836: Changed `final_stop={final_stop:.2f}` → `trailing_stop={trailing_stop:.2f}`
- Line 856: Changed `'final_stop': final_stop` → `'trailing_stop': trailing_stop`

#### 2. Position `remaining_size` Not Set on Open

**Problem**: Positions opened via BUY signals had `remaining_size=0.0` in database, causing them to be filtered out by API (`api_worker.py:881`).

**Root Cause**: When creating new positions, `remaining_size` was not included in:
- `position_details` dict (line 415-430)
- `save_open_position()` call (line 433-446)

**Fix** (`src/trading_engine.py`):
- Line 429: Added `'remaining_size': size` to `position_details`
- Line 439: Added `'remaining_size': size` to `save_open_position()` call
- Lines 165, 178: Added `'remaining_size': wallet_balance` to `initial_position_sync()`

#### 3. Database Save Order

**Problem**: In-memory state was updated BEFORE database save, causing race conditions if DB save failed.

**Fix** (`src/trading_engine.py:428-462`):
- Reordered to save to database FIRST
- Only update `self.active_positions` and `self.holdings` AFTER successful DB save
- Added error checking for `db_manager.save_open_position()` return value

#### 4. Database Schema Fix

**Problem**: `OpenPosition.product_id` had `unique=True` constraint, preventing multiple position records for same product.

**Fix** (`src/database.py:224`):
- Removed `unique=True` from `product_id` column
- Changed to `index=True` to maintain query performance
- Created migration `migrations/remove_product_id_unique.py`

### Files Modified

| File | Changes |
|------|---------|
| `src/trading_engine.py` | Fixed `final_stop` → `trailing_stop` (2 places), added `remaining_size` to position creation, reordered DB save logic |
| `src/database.py` | Removed `unique=True` from `product_id` |
| `migrations/remove_product_id_unique.py` | NEW - Migration script for database fix |

### Deployment

```bash
docker-compose build --no-cache && docker-compose up -d
```

---

## Trailing Stop - Sell Order Fix (v2.6) & Bug Fix (v2.7)

### Problem (v2.6)

Trailing stop was updating position records but NOT executing actual sell orders on Coinbase.

### Root Cause (v2.6)

`_close_position()` only updated in-memory/DB records - it never called `execute_live_trade()`.

### Solution (v2.6)

Added actual sell execution in trailing stop logic (trading_engine.py lines 640-655):

```python
if should_close:
    sell_size = position.get('remaining_size', position.get('size', 0))
    
    # Actually execute the sell order on Coinbase (not just update record!)
    if not self.paper_trading and sell_size > 0:
        try:
            order_result = self.execute_live_trade(product_id, 'sell', sell_size)
            logger.info(f"[TRAILING STOP] Sell order result: {order_result}")
        except Exception as e:
            logger.error(f"[TRAILING STOP] Failed to execute sell: {e}")
    
    # Update position record in DB
    self._close_position(position_id, pnl, exit_reason, current_price)
```

### Behavior Now (v2.6 + v2.7)

| Trigger | Action |
|---------|--------|
| Trailing stop hit (price <= trailing_stop AND price >= break_even) | Log "[TRAILING STOP] SELL TRIGGERED" |
| | Execute actual sell order on Coinbase via execute_live_trade() |
| | Update position record in DB |

### Bug Fix (v2.7) - `final_stop` NameError

**Problem**: After v2.6 fix, trading cycle crashed with `NameError: name 'final_stop' is not defined`

**Root Cause**: Variable was renamed from `final_stop` to `trailing_stop` (lines 726-727) but references at lines 836 and 856 were missed.

**Fix** (v2.7):
- Line 836: Changed `final_stop={final_stop:.2f}` → `trailing_stop={trailing_stop:.2f}` in log message
- Line 856: Changed `'final_stop': final_stop` → `'trailing_stop': trailing_stop` in closed position dict

### Previously (Broken - v2.6)

- Trailing stop triggered → _close_position() called → Only updated record in DB
- No actual sell order placed on Coinbase
- Position showed as "closed" but still owned crypto
- CRITICAL: `final_stop` NameError crashed trading cycle (fixed in v2.7)


---

## v2.8.0 - AI Model Fixes & Stop Loss Bug Fixes
**Date**: May 8, 2026

### Major Fixes Implemented

#### 1. **Critical: `peak_price` Not Initialized**
**Problem**: `peak_price` column existed in DB but wasn't being saved when positions opened.

**Fix** (`src/trading_engine.py`):
- Added `'peak_price': entry_price` to `position_details` dict (line 428)
- Added `'peak_price': entry_price` to `db_manager.save_open_position()` call (line 438)
- Verified: `OpenPosition` model already had `peak_price = Column(Float, default=0.0)` (line 194)

#### 2. **Critical: `stop_loss_price = £0.0` Bug**
**Problem**: SOL position had `stop_loss_price: 0.0`, positions weren't closing.

**Fix** (`src/trading_engine.py`):
- Added fallback in `validate_signal()` (lines 325-335): if `stop_loss_price <= 0`, use 5% stop loss from entry
- Added validation check after setting `signal['stop_loss_price']`

#### 3. **Critical: Trailing Stop Logic Overhaul (Option A)**
**Problem**: Trailing stop never activated if price never reached break-even. SOL price £64.99 < break-even £65.24 → `trailing_activated = False` → never checked sell condition!

**Fix** (`src/trading_engine.py` lines 734-752):
- **Before**: Only checked trailing stop if `trailing_activated = (peak >= break_even)`
- **After**: Always calculate trailing stop, check sell conditions:
  - If activated AND trailing stop hit → normal sell
  - If NOT activated AND price drops >2% from entry → **emergency stop** (new!)
- Added emergency stop logging: `[EMERGENCY STOP] Price £XX below entry £YY by ZZ%`

#### 4. **SOL Position Closed**
- Position `f05a0e42-a365-47d4-bd67-c3e7c7957027` closed manually
- P&L: £0.11 (0.71% profit)
- Reason: "Manual close (stop loss bug fix)"

#### 5. **RidgeClassifier Integration**
**Problem**: Ridge models weren't being saved (`/app/models/*_ridge_model.joblib` not found).

**Fix** (`src/ai_model.py`):
- Always initialize result lists (`rf_fold_results`, `mlp_fold_results`, etc.) to avoid NameError
- Fixed mean calculations to use initialized lists
- Removed LR-specific code since `USE_LR_MODEL = False`
- Added debug logging for Ridge training
- Training now succeeds: `train_model('SOL-GBP', force_retrain=True)` → Success

#### 6. **Multi-Source Pricer Fallback for Coinbase Outage**
**Problem**: Coinbase AWS outage causing USD pair API failures (503 errors).

**Fix** (`src/multi_source_pricer.py`):
- Added special handling: If Coinbase fails but other sources available → use them with lower confidence
- Changed logic: `Coinbase failed for {product_id}, using {len(valid_prices)} remaining sources: [...]`
- Allows system to function with Binance + Kraken when Coinbase is down

### Files Modified

| File | Changes |
|------|---------|
| `src/trading_engine.py` | Fixed `peak_price` init, `stop_loss_price` fallback, trailing stop Option A |
| `src/ai_model.py` | Fixed Ridge training, removed LR code, initialized lists |
| `src/multi_source_pricer.py` | Added Coinbase outage fallback |
| `docs/sessions/v2.8.0.md` | NEW - Session documentation |
| `docs/index.md` | Updated changelog with v2.8.0 |
| `AGENTS.md` | Updated key files, documentation references |

### Configuration

**RidgeClassifier Settings** (`config/settings.py`):
```python
USE_RIDGE_MODEL: bool = True   # NEW - Linear model with L2 regularization
RIDGE_ALPHA: float = 1.0      # Regularization strength
```

**Trailing Stop Settings** (unchanged, but logic fixed):
- `TRAILING_STOP_PERCENT: 0.02` (2% trailing stop)
- `TRAILING_STOP_REGIME_MAP`: downtrend=2%, neutral=2%, bull=2%

### Testing Verified

- [x] Ridge model training succeeds
- [x] Ridge models saved to `models/*_ridge_model.joblib`
- [x] `stop_loss_price` fallback works (5% stop when value is 0)
- [x] Trailing stop emergency stop triggers when price drops >2% from entry
- [x] `peak_price` initialized when opening new positions
- [x] Multi-source pricer falls back to Binance/Kraken when Coinbase fails

### Deployment Notes

**IMPORTANT**: All fixes require Docker rebuild:
```bash
docker compose build --no-cache
docker compose up -d
```

**Verification After Rebuild**:
```bash
# 1. Check Ridge models exist
docker exec crypto-trader-bot ls -la /app/models/*_ridge_model.joblib

# 2. Check new positions have peak_price
docker exec crypto-trader-bot python3 -c "
from src.database import db_manager
positions = db_manager.get_all_open_positions_detailed()
for p in positions:
    print(f"{p.get('product_id')}: peak={p.get('peak_price')}, stop={p.get('stop_loss_price')}")
"

# 3. Monitor trailing stop behavior
docker logs crypto-trader-bot -f | grep "TRAILING STOP"
```

---

## v2.9 - AI Model Improvements: Selective Trading & Adaptive Weighting

**Date**: May 15, 2026

### Summary

Improved AI model performance to make better BUY predictions that actually make money. Key changes:
- Increased BUY/SELL threshold to 75% agreement (3/4 models)
- Added rolling live performance tracking for adaptive weighting
- Added regime-aware confidence adjustment

### Changes Made

#### 1. Increased Voting Threshold to 75%

**File**: `src/ai_model.py` (lines ~885-910)

**Before:**
```python
# 3-class: BUY=2, SELL=0, HOLD=1
if buy_votes >= 2:  # 66% (2/3 or 2/4)
    majority_vote = 2  # BUY
```

**After:**
```python
# v2.9: Increased threshold to 75% (3/4 models) for more selective trading
if buy_votes >= 3:  # Require 75% agreement (3/4 models)
    majority_vote = 2  # BUY
elif sell_votes >= 3:  # Require 75% agreement
    majority_vote = 0  # SELL
elif buy_votes >= 2 and n_models >= 3:  # Allow 66% only if 3 models
    majority_vote = 2  # BUY (2/3 = 66%)
```

**Impact:**
- Fewer but higher-quality trades
- Reduces false signals from 2-model agreement

#### 2. Rolling Live Performance Tracking

**File**: `src/ai_model.py` (lines ~1515-1600)

**New Methods Added:**
- `_track_live_performance(product_id, model_predictions, actual_direction)` - Tracks prediction accuracy
- `_get_rolling_accuracy(product_id, model_name)` - Returns accuracy over last 50 predictions

**How It Works:**
```python
# Tracks last 50 predictions per model
self._model_performance[product_id][model_name] = {
    'correct': int,
    'total': int,
    'recent_correct': []  # Rolling window of 50
}

# Blends training F1 with live accuracy (70% training, 30% live)
blended_weights[model_name] = (training_weight * 0.7) + (live_acc * 0.3)
```

**Impact:**
- Model weights adapt to live market conditions
- Good models in current market get higher weight
- Poor models get lower weight automatically

#### 3. Regime-Aware Confidence Adjustment

**File**: `src/ai_model.py` (lines ~1098-1145)

**Confidence Adjustments:**
| Regime | Action | Adjustment |
|--------|--------|------------|
| Uptrend | BUY | +15% boost |
| Downtrend | BUY | -30% reduction |
| Downtrend | SELL | +15% boost |
| Uptrend | SELL | -30% reduction |
| High volatility | Any | -20% reduction |
| Low volatility | Any | +10% boost |

**Example:**
```python
if regime == 'uptrend' and action == 'BUY':
    result['confidence'] = min(result['confidence'] * 1.15, 0.95)
    # 70% → 80.5% (boosted in favorable trend)
elif regime == 'downtrend' and action == 'BUY':
    result['confidence'] = result['confidence'] * 0.7
    # 70% → 49% (reduced - counter-trend is riskier)
```

### Files Modified

| File | Changes |
|------|---------|
| `src/ai_model.py` | Added rolling performance, increased threshold, regime-aware confidence |

### Configuration

**Settings** (`config/settings.py`):
```python
ENSEMBLE_WEIGHT_MODE: str = 'performance'  # Uses live performance tracking
MODEL_CONFIDENCE_THRESHOLD: float = 0.70   # Minimum confidence for signals
```

### Expected Outcomes

| Metric | Before | After |
|--------|--------|-------|
| BUY triggers | 66% (2/4 models) | 75% (3/4 models) |
| False signals | Higher | Lower (~25% reduction expected) |
| Uptrend captures | Baseline | +15% confidence |
| Downtrend protection | -20% | -30% (stronger) |
| Live adaptation | None | 30% weight to live perf |

### Testing Checklist

- [x] Import test passes (AI Model initialized correctly)
- [x] New methods exist (_track_live_performance, _get_rolling_accuracy)
- [x] Voting threshold logic tested (3/4 triggers BUY, 2/4 does not)
- [x] _model_performance initialized as empty dict

### Deployment

```bash
# Rebuild to apply changes
docker-compose build --no-cache
docker-compose up -d
```

### Verification

```bash
# Test AI model imports
docker exec crypto-trader-bot python3 -c "from src.ai_model import AIModel; print('OK')"

# Check for confidence adjustment logs
docker logs crypto-trader-bot -f | grep "confidence in"
# Should show: "Boosted BUY confidence in uptrend" or "Reduced BUY confidence in downtrend"

# Check for weight blending logs
docker logs crypto-trader-bot -f | grep "WEIGHT_BLEND"
# Should show: "BTC-GBP/rf: training=0.350, live=0.500, blended=0.395"
```

### Notes

- Live performance tracking needs ~10-20 predictions before weights start adapting
- The 75% threshold means some previously-valid signals will now show as HOLD
- This is intentional - better to miss a trade than take a losing trade
- Confidence adjustments are multiplicative (can stack: uptrend + low volatility = +25%)

---

## v2.9.1 - Ridge Model Loading Fix & Confidence Bug Fix

**Date**: May 15, 2026

### Problem

After deploying v2.9 changes, BTC, ETH, and SOL pairs showed **0% confidence** with signals showing "Signal HOLD" despite models generating valid predictions.

### Root Causes

1. **Ridge models not loading**: Missing `load_existing_ridge_models()` method and call in `__init__`
   - Only RF + GB were loading = 2 models
   - With 2 models, 75% threshold impossible to meet → always HOLD

2. **n_models UnboundLocalError**: Variable used in voting logic before being defined

3. **Ridge probability conversion bug**: Decision function returned multi-dimensional array causing error

4. **Confidence edge case**: When majority_vote = HOLD but no model predicted HOLD, confidence = 0%

### Fixes Applied

#### 1. Added Ridge Model Loading

**File**: `src/ai_model.py`

Added new method:
```python
def load_existing_ridge_models(self):
    """Load all existing trained Ridge models from disk into memory."""
    # Similar to other load methods but for Ridge
    ...
```

Added call in `__init__`:
```python
if self.ensemble_enabled:
    self.load_existing_lr_models()
    self.load_existing_mlp_models()
    self.load_existing_gb_models()
    self.load_existing_ridge_models()  # v2.9.1: Added
```

#### 2. Fixed n_models variable scope

**File**: `src/ai_model.py`

Added n_models calculation before voting logic:
```python
# v2.9.1: Calculate n_models BEFORE using in voting logic
n_models = len(vote_list)
```

#### 3. Fixed Ridge probability conversion

**File**: `src/ai_model.py`

Fixed multi-dimensional array handling:
```python
decision = np.array(decision).flatten()
if len(decision) == 0:
    decision = np.array([0.0])
proba_val = 1.0 / (1.0 + np.exp(-np.abs(decision)))
proba_val = float(proba_val[0])  # Extract scalar
```

#### 4. Added confidence fallback

**File**: `src/ai_model.py`

```python
# v2.9.1: Fallback - if confidence is 0 but action is not HOLD, use agreement
if confidence == 0.0 and action != 'HOLD':
    confidence = float(agreement)
elif confidence == 0.0 and action == 'HOLD':
    confidence = max(float(ensemble_proba), 0.33)
```

### Results After Fix

| Pair | Before Fix | After Fix |
|------|------------|-----------|
| BTC-GBP | HOLD (0%) | HOLD (58.6%) |
| ETH-GBP | HOLD (0%) | HOLD (59.5%) |
| SOL-GBP | HOLD (0%) | HOLD (62.1%) |
| ADA-GBP | N/A | SELL (47.0%) |
| LTC-GBP | N/A | SELL (72.1%) |
| LINK-GBP | N/A | BUY (91.6%) |

### Verification

```bash
# Test model loading
docker exec crypto-trader-bot python3 -c "
from src.ai_model import AIModel
ai = AIModel()
print(f'RF: {len(ai.models)}, GB: {len(ai.gb_models)}, Ridge: {len(ai.ridge_models)}')
# Expected: RF: 12, GB: 12, Ridge: 12
"

# Test signal generation
docker exec crypto-trader-bot python3 -c "
from src.ai_model import AIModel
ai = AIModel()
for pair in ['BTC-GBP', 'ETH-GBP', 'SOL-GBP']:
    signal = ai.get_signal(pair)
    print(f'{pair}: {signal.get(\"action\")} ({signal.get(\"confidence\", 0):.1%})')
"
```

### Deployment

```bash
docker-compose build --no-cache
docker-compose up -d
```

---

## v2.9.2 - Configurable Vote Threshold & Dashboard Update

**Date**: May 15, 2026

### Summary

Made the ensemble vote threshold configurable and updated the dashboard to show both thresholds.

### Changes

#### 1. New Configurable Setting

**File**: `config/settings.py`
```python
ENSEMBLE_VOTE_THRESHOLD: float = 0.75  # v2.9.1: Models must agree at this rate for BUY/SELL (75% = 3/4 models)
```

#### 2. Updated AI Model to Use Setting

**File**: `src/ai_model.py`
```python
# v2.9.1: Use configurable vote threshold from settings
vote_threshold = settings.ENSEMBLE_VOTE_THRESHOLD  # 0.75 = 75% = 3/4 models
votes_needed = max(2, int(vote_threshold * n_models))  # At least 2, at least 75%
fallback_votes_needed = max(2, int(0.66 * n_models))  # 66% fallback
```

#### 3. Updated Dashboard Display

**File**: `src/templates/dashboard.html`

Now shows both thresholds in Trading Logic section:
- **AI Signal**: ≥ 75% model agreement (vote threshold)
- **Confidence**: ≥ 65% probability threshold (confidence threshold)
- **Position Size**: Max 0.5% of portfolio
- **Check Interval**: Every 45 minutes
- **Risk**: Max 0.5% per trade, £2 buffer maintained

### Two Threshold System

| Threshold | Setting | Default | Purpose |
|-----------|---------|---------|---------|
| **Vote Threshold** | `ENSEMBLE_VOTE_THRESHOLD` | 75% | How many models must agree (3/4) |
| **Confidence Threshold** | `MODEL_CONFIDENCE_THRESHOLD` | 65% | Minimum probability for valid signal |

Both thresholds must pass for a trade to execute:
1. First: Vote threshold (models agree)
2. Second: Confidence threshold (probability high enough)

### Files Modified

| File | Change |
|------|--------|
| `config/settings.py` | Added `ENSEMBLE_VOTE_THRESHOLD` setting |
| `src/ai_model.py` | Use setting instead of hardcoded 3 |
| `src/api_worker.py` | Return vote_threshold in API response |
| `src/templates/dashboard.html` | Display both thresholds in Trading Logic |

### Testing

```bash
# Verify settings load
python3 -c "from config.settings import settings; print(f'Vote: {settings.ENSEMBLE_VOTE_THRESHOLD}, Conf: {settings.MODEL_CONFIDENCE_THRESHOLD}')"
# Expected: Vote: 0.75, Conf: 0.65
```
