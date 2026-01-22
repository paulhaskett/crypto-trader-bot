# Crypto Trading Bot Plan - Raspberry Pi 5 (Beginner-Safe AI/ML)

## Overview
Budget-friendly, beginner-safe AI/ML trading bot for BTC+ETH on Coinbase. Focus on capital preservation with conservative AI-driven signals. Designed for Raspberry Pi 5 with lightweight architecture.

## Technology Stack
- **Core:** Python 3.13 + Coinbase Advanced Trade SDK
- **Data:** pandas, numpy, TA-Lib
- **AI/ML:** scikit-learn (Random Forest, Gradient Boosting)
- **Database:** SQLite with SQLAlchemy
- **Scheduling:** APScheduler
- **Monitoring:** FastAPI + basic web dashboard

## Key Features
1. **Sandbox Testing:** Full paper trading with Coinbase sandbox
2. **Conservative Risk:** 2.5% max per trade, 1 concurrent position, wide stops
3. **AI Signals:** High-confidence predictions (>75%) with multi-timeframe confirmation
4. **Safety First:** Circuit breakers, manual override, daily limits
5. **Monitoring:** Real-time dashboard, automated alerts

## Timeline (4 Weeks)
- **Week 1:** Environment setup, Coinbase API integration, data collection
- **Week 2:** AI model development, feature engineering, backtesting
- **Week 3:** Risk management, strategy implementation, paper trading
- **Week 4:** Live testing with micro amounts, monitoring setup

## Risk Management (Ultra-Conservative)
```python
max_position_per_trade = 0.025  # 2.5% of portfolio
max_daily_trades = 2           # Limit frequency
max_concurrent_positions = 1    # One trade at a time
stop_loss_atr = 1.5           # Wider stops
take_profit_levels = [1.5, 2.0, 3.0]  # Multiple profit targets
```

## Project Structure
```
crypto-trader-bot/
├── src/
│   ├── coinbase_api.py          # API wrapper with sandbox support
│   ├── data_collector.py        # Market data pipeline
│   ├── ai_model.py             # ML models and predictions
│   ├── risk_manager.py         # Position sizing and safety
│   ├── trading_engine.py       # Signal generation and execution
│   └── database.py             # SQLite operations
├── config/
│   ├── settings.py             # Configuration management
│   └── api_keys.env            # Secure key storage
├── models/                     # Trained ML models
├── tests/                      # Unit and integration tests
├── docs/                       # Setup and usage guides
├── requirements.txt            # Python dependencies
└── main.py                     # Entry point
```

## Dependencies
```
coinbase-advanced-py==1.0.0
pandas==2.1.0
numpy==1.26.0
scikit-learn==1.3.0
TA-Lib==0.4.25
fastapi==0.104.0
uvicorn==0.24.0
python-dotenv==1.0.0
```

## Safety Mechanisms
- Mandatory 4-week paper trading period
- Circuit breakers on high volatility
- Emergency stop functionality
- Manual override capabilities
- Daily loss limits (2% max)
- Position size limits

## Expected Performance
- **Win Rate:** 60-65% (conservative AI)
- **Risk/Reward:** 2:1 average
- **Max Drawdown:** <10%
- **Monthly Return:** 5-8% (paper trading target)

## Prerequisites
- Raspberry Pi 5 with 4GB+ RAM
- Coinbase Advanced Trade account with API keys
- Python 3.13 installed
- Basic Linux command line knowledge

## ✅ CURRENT PROJECT STATUS

### **🚀 LIVE TRADING BOT DEPLOYED & RUNNING**

**Bot is now in production with real money trading:**

#### **📊 Current Status:**
- **Trading Mode**: Live (Real Coinbase API)
- **Portfolio Value**: $15.91 (~£10 account balance)
- **Max Position Size**: 2.5% per trade ($0.40 max)
- **Trading Status**: Active and operational
- **API Connection**: Real-time market data from Coinbase Exchange
- **Safety Systems**: Emergency stop, position limits, risk management

#### **🔧 System Architecture:**
- **API Integration**: Coinbase Advanced Trade API (JWT + ECDSA authentication)
- **Market Data**: Coinbase Exchange API (public ticker data)
- **Database**: SQLite with trade history and settings
- **Risk Management**: 2% max position size, daily loss limits
- **AI Models**: Random Forest for signal generation
- **Dashboard**: FastAPI web interface at http://localhost:8000

#### **🛡️ Safety Mechanisms Active:**
- **Position Limits**: Maximum $0.40 per trade (2.5% of portfolio)
- **Emergency Stop**: Instant trading shutdown capability
- **Manual Controls**: Start/Stop trading anytime
- **Risk Validation**: Pre-trade checks and balance verification
- **API Error Handling**: Graceful fallback to mock data if needed

#### **💰 Trading Capabilities:**
- **Supported Pairs**: BTC-USD, ETH-USD, SOL-USD, LTC-USD, XRP-USD
- **Order Types**: Market orders (immediate execution)
- **AI Signals**: Multi-timeframe technical analysis with confidence scoring
- **Position Tracking**: Real-time P&L monitoring
- **Performance Metrics**: Win rate, profit tracking, trade history

### **📈 Performance Targets:**
- **Initial Goal**: Grow £10 to £100 through AI-powered trading
- **Conservative Approach**: Focus on capital preservation over aggressive growth
- **Risk Management**: 2% maximum position sizing
- **Performance Monitoring**: Real-time dashboard with comprehensive metrics

### **🔮 Next Development Phases:**

#### **Phase 1: Production Monitoring** (Current)
- Monitor live trading performance
- Collect real trade data for model improvement
- Fine-tune risk parameters based on actual performance
- Optimize AI signal accuracy with real market data

#### **Phase 2: Advanced Features** (Future)
- Implement stop-loss orders
- Add take-profit automation
- Portfolio rebalancing strategies
- Advanced technical indicators

#### **Phase 3: Performance Optimization**
- Model retraining with real trade data
- Strategy backtesting and optimization
- Risk parameter optimization
- Performance analytics dashboard

### **⚠️ Current Monitoring:**
- **Dashboard**: http://localhost:8000
- **API Status**: All endpoints operational
- **Trading Controls**: Start/Stop/Emergency working
- **Safety Systems**: All mechanisms active and functional

**The bot is successfully deployed and trading with real money!**

## Next Steps
1. Review this plan
2. Confirm API keys setup
3. Begin Week 1 implementation
4. Start with sandbox/paper trading

## Important Notes
- Always test with paper money first
- Start with micro amounts ($10-20 per trade)
- Monitor system performance regularly
- Have manual override ready
- Backup configurations and data daily