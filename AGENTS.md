# AGENTS.md - Crypto Trading Bot Agent Guidelines

## 📋 Project Overview
- **Language**: Python 3.13+
- **Type**: Crypto Trading Bot
- **Platform**: Raspberry Pi 5 / Docker
- **Architecture**: Modular FastAPI + AI/ML + SQLite
- **Trading Mode**: Paper trading initially, real-money option available

## 🐧 Build/Int/Test Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Run in development mode
python main.py --dashboard --verbose

# Run in paper trading mode (no real trades)
python main.py --test

# Run specific test file
python test_ai.py

# Run single test function
python -c "from test_ai import test_technical_indicators; test_technical_indicators()"
```

### Code Quality
```bash
# Format code with black (88 char line length)
black src/ config/ main.py --line-length=88

# Type check with mypy (ignore venv)
mypy src/ main.py --ignore=venv/

# Lint with flake8 (if configured)
flake8 src/ --max-line-length=88 --extend-ignore=E203,W503
```

### Docker
```bash
# Build and run
docker-compose up --build -d

# View logs
docker-compose logs -f crypto-trader-bot
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
│   └── settings.py      # Application settings and constants
├── src/                 # Core bot modules
│   ├── ai_model.py      # Machine learning and signal generation
│   ├── coinbase_api.py  # Coinbase API integration
│   ├── dashboard.py     # Web dashboard with FastAPI
│   ├── data_collector.py # Market data collection and processing
│   ├── database.py      # Database operations with SQLAlchemy
│   ├── risk_manager.py  # Risk management and position sizing
│   └── trading_engine.py # Main trading logic orchestration
├── models/              # Saved AI models
├── data/                # Market data and SQLite database
├── logs/                # Application logs
├── tests/               # Unit and integration tests
└── main.py              # Application entry point
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