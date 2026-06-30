# Crypto Trading Bot

A sophisticated automated cryptocurrency trading bot built with Python, FastAPI, and machine learning capabilities. Features real-time market analysis, risk management, and web-based monitoring with multi-currency support (USD/GBP).

**Current Version**: v1.0.6 (January 27, 2026)

## 🤖 Development Credits

This project was developed with assistance from **opencode**, an AI-powered coding assistant that helped implement the core trading logic, API integrations, dashboard development, risk management systems, and deployment configurations.

## 🚀 Features

### Core Trading Features
- **AI/ML Trading**: Random Forest models with 65%+ accuracy for price prediction
- **Real-time Market Data**: Live price feeds from Coinbase Advanced Trade API
- **Risk Management**: Position sizing, stop-loss, daily loss limits, and circuit breakers
- **Multi-currency Support**: USD and GBP display options with real-time conversion
- **Paper Trading Mode**: Safe testing without real money (default)

### Technical Features
- **Web Dashboard**: Real-time monitoring and control at `http://localhost:8000`
- **REST API**: Comprehensive API for integration and automation
- **Docker Deployment**: Containerized for easy deployment on any platform
- **Emergency Stop**: Instant cancellation of all open orders
- **WebSocket Updates**: Real-time status updates without page refresh

### Safety & Monitoring
- **Position Limits**: Configurable maximum position sizes (default 2.5%)
- **Daily Loss Limits**: Automatic trading suspension at 2% daily loss
- **Real-time Alerts**: Trading status notifications and error handling
- **Comprehensive Logging**: Detailed trade history and performance tracking
- **Sandbox Testing**: Coinbase sandbox environment for safe testing

## 📋 Prerequisites

- **Docker & Docker Compose** (recommended for easy deployment)
- **Python 3.13+** (for local development)
- **Coinbase Advanced Trade API** credentials (get from https://www.coinbase.com/settings/api)
- **4GB+ RAM** recommended
- **Linux/Windows/MacOS** compatible

## 🛠️ Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd crypto-trader-bot

# Start with Docker Compose
docker compose up -d

# Access dashboard at http://localhost:8000
```

### Option 2: Local Development

```bash
# Clone and setup
git clone <repository-url>
cd crypto-trader-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure API keys (see Configuration section)
# Start the bot
python main.py
```

## ⚙️ Configuration

### Current Configuration (v1.0.6)

- **Base Currency**: GBP (portfolio valuation and trading pairs)
- **Trading Pairs**: 8 GBP pairs (BTC-GBP, ETH-GBP, SOL-GBP, LTC-GBP, DOT-GBP, ADA-GBP, LINK-GBP, UNI-GBP)
- **Market Data**: High-liquidity USD markets with real-time GBP conversion
- **Display Currency**: Toggle between USD and GBP (user preference, persistent)
- **Risk Management**: Conservative 1-2% per trade with day trading parameters
- **AI Models**: 8 Random Forest models (65%+ accuracy)
- **Deployment**: Docker containerized on Raspberry Pi 5

### API Credentials

Create `config/api_keys.env` with your Coinbase credentials:

```bash
# Coinbase Advanced Trade API Credentials
# Get these from: https://www.coinbase.com/settings/api
COINBASE_API_KEY=your_api_key_here
COINBASE_API_SECRET=your_api_secret_here

# Trading Mode (true for paper trading, false for live)
SANDBOX_MODE=true
```

### Trading Settings

Edit `config/settings.py` to customize:

```python
# Risk Management
MAX_POSITION_SIZE = 0.025  # Maximum 2.5% of portfolio per trade
MAX_DAILY_TRADES = 2       # Maximum trades per day
MAX_DAILY_LOSS = 0.02      # Stop trading at 2% daily loss
STOP_LOSS_ATR_MULTIPLIER = 1.5  # ATR-based stop loss

# AI/ML Configuration
MODEL_CONFIDENCE_THRESHOLD = 0.75  # Minimum confidence for trades
FEATURE_WINDOW_SIZE = 24           # Hours of data for features
PREDICTION_HORIZON = 4             # Hours to predict ahead

# Currency Display
DISPLAY_CURRENCY = 'USD'           # 'USD' or 'GBP'
SUPPORTED_CURRENCIES = ['USD', 'GBP']
CURRENCY_CACHE_DURATION = 3600     # Cache rates for 1 hour
```

## 🎯 Usage

### Web Dashboard

Access the comprehensive web interface at `http://localhost:8000`:

- **Portfolio Overview**: Real-time balances in USD/GBP with individual account breakdowns
- **Trading Controls**: Start/stop automated trading, emergency stop, model retraining
- **Currency Selector**: Switch between USD and GBP display (persists in settings)
- **Performance Metrics**: Win rate, P&L, trade statistics
- **Risk Monitoring**: Daily limits, position tracking, safety status
- **Trade History**: Complete transaction log with detailed analysis

### Dashboard Controls

- **Start Trading**: Begin automated trading with AI signals
- **Stop Trading**: Pause all trading activities
- **Emergency Stop**: Instantly cancel all open orders and stop trading
- **Retrain Models**: Update AI models with latest market data
- **Refresh Dashboard**: Update all displayed data
- **Currency Selector**: Switch between USD and GBP display

### Trading Modes

- **Paper Trading** (default): Test strategies without real money
- **Live Trading**: Execute real trades with actual funds

## 📊 API Documentation

### Core Endpoints

#### Portfolio Management
```http
GET /api/portfolio
```
Returns portfolio composition with individual balances and currency conversion.

**Response:**
```json
{
  "portfolio": [
    {
      "currency": "BTC",
      "balance": "0.023456 BTC",
      "value_usd": 1056.78,
      "value": 1056.78,
      "formatted_value": "$1,056.78",
      "percentage": 65.5
    }
  ],
  "total_value": 1615.23,
  "formatted_total": "$1,615.23",
  "display_currency": "USD"
}
```

#### Bot Status
```http
GET /api/status
```
Returns comprehensive bot status and trading information.

#### Trading Controls
```http
POST /api/control/{action}
```
Available actions: `start_trading`, `stop_trading`, `emergency_stop`, `retrain_models`

#### Currency Settings
```http
POST /api/settings/display_currency
```
Body: `{"value": "USD"}` or `{"value": "GBP"}`

#### Exchange Rates
```http
GET /api/exchange_rate
```
Returns current USD to GBP exchange rate from Coinbase.

## 🔧 Advanced Configuration

### Risk Management Parameters

```python
# Position Sizing
MAX_POSITION_SIZE = 0.025      # Maximum 2.5% per trade
MAX_CONCURRENT_POSITIONS = 1   # Maximum open positions

# Stop Loss Configuration
STOP_LOSS_ATR_MULTIPLIER = 1.5 # ATR-based stop loss
TAKE_PROFIT_LEVELS = [1.5, 2.0, 3.0]  # Profit taking levels

# Daily Safety Limits
MAX_DAILY_TRADES = 2           # Maximum trades per day
MAX_DAILY_LOSS = 0.02          # Stop at 2% daily loss
CIRCUIT_BREAKER_VOLATILITY = 0.15  # Pause on 15% volatility
```

### AI Model Configuration

```python
# Model Parameters
MODEL_CONFIDENCE_THRESHOLD = 0.75  # Minimum confidence for trades
FEATURE_WINDOW_SIZE = 24           # Hours of historical data
PREDICTION_HORIZON = 4             # Hours to predict ahead

# Technical Indicators (14 total)
# RSI, MACD, Bollinger Bands, ATR, Volume analysis, etc.
```

### Market Data Settings

```python
# Data Collection
CANDLE_GRANULARITY = "ONE_HOUR"  # 1-hour candles
HISTORICAL_DATA_DAYS = 365       # Days of historical data
MARKET_CHECK_INTERVAL = 300       # Check market every 5 minutes
DATA_UPDATE_INTERVAL = 3600       # Update data every hour
```

## 🐳 Docker Deployment

### Production Setup

```bash
# Build and run in production
docker compose -f docker-compose.yml up -d

# View logs
docker compose logs -f crypto-trader-bot

# Restart services
docker compose restart crypto-trader-bot
```

### Environment Configuration

```yaml
# docker-compose.yml
environment:
  - COINBASE_API_KEY=your_key
  - COINBASE_API_SECRET=your_secret
  - SANDBOX_MODE=false
```

### Docker Commands

```bash
# Build custom image
docker build -t crypto-trader-bot .

# Run with volume mounting
docker run -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/models:/app/models \
  crypto-trader-bot

# View container logs
docker logs crypto-trader-bot

# Access container shell
docker exec -it crypto-trader-bot bash
```

## 📈 Performance Monitoring

### Dashboard Metrics

- **Portfolio Value**: Real-time account balance with currency conversion
- **Active Positions**: Current open trades and position sizes
- **Daily P&L**: Profit/loss tracking with percentage changes
- **Win Rate**: Trading success percentage and statistics
- **Risk Status**: Safety limit monitoring and alerts
- **AI Confidence**: Model prediction confidence levels

### Logging System

Comprehensive logging to `logs/trading_bot.log`:

```python
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = 'logs/trading_bot.log'
LOG_MAX_SIZE = 10*1024*1024  # 10MB rotation
LOG_BACKUP_COUNT = 5         # Keep 5 backup files
```

## 🚨 Safety Features

### Emergency Controls

- **Emergency Stop Button**: Instantly cancels all open orders
- **Daily Loss Limits**: Automatic suspension when loss thresholds reached
- **Position Size Limits**: Prevents oversized trades based on portfolio %
- **Circuit Breakers**: Pauses trading during extreme volatility
- **Manual Override**: Complete control over trading operations

### Risk Management

- **Conservative Position Sizing**: Maximum 2.5% per trade by default
- **Stop Loss Protection**: ATR-based automatic loss prevention
- **Diversification**: Multi-asset portfolio management (BTC, ETH)
- **Drawdown Protection**: Multiple safety layers against losses
- **Sandbox Testing**: Risk-free strategy testing

## 📅 Recent Updates (v1.0.6)

### January 27, 2026 - Critical Bug Fixes

**1. Currency Switcher Fixed**
- ✅ Fixed currency switcher persisting issue by adding `await` to async function calls
- ✅ Currency preferences now save correctly to database
- ✅ Display currency switching (USD ↔ GBP) works as expected

**2. Market Conditions Data Fixed**
- ✅ Removed invalid API call to non-existent `GBP-USD` trading pair
- ✅ Added validation to skip invalid pairs in coinbase_api.py
- ✅ Market conditions now display prices and AI signals correctly
- ✅ No more 404 errors in logs

**3. API Route Ordering Fixed**
- ✅ Moved specific currency endpoints before catch-all route
- ✅ Fixed "Method Not Allowed" errors on currency endpoints
- ✅ All API endpoints now accessible with proper routing

**4. UI Layout Improved**
- ✅ Moved crypto balance display to appear directly under crypto price
- ✅ Better UX with holdings immediately visible
- ✅ Improved information hierarchy

### Previous Versions

**v1.0.5** (January 25, 2026): GBP trading system complete with 8 trading pairs and AI model coverage

**v1.0.2** (January 23, 2026): Portfolio valuation fixes and API diagnostics

**v1.0.1** (January 23, 2026): USDC valuation bug fixes, currency switching, test trade endpoint

---

## 🐛 Troubleshooting

### Common Issues

#### "Function is not defined" JavaScript errors
```bash
# Hard refresh browser (Ctrl + Shift + R)
# Clear browser cache completely
# Check browser developer tools for specific errors
```

#### "API credentials not found"
```bash
# Verify config/api_keys.env exists and has correct format
cat config/api_keys.env

# Ensure proper permissions
chmod 600 config/api_keys.env
```

#### "WebSocket connection failed"
```bash
# Check container networking
docker compose ps

# View detailed logs
docker compose logs crypto-trader-bot

# Test API connectivity
curl http://localhost:8000/api/status
```

#### "Trading engine not starting"
```bash
# Check sandbox mode setting
grep SANDBOX_MODE config/api_keys.env

# Verify API credentials are valid
python -c "from src.coinbase_api import coinbase_api; print('API:', coinbase_api.is_sandbox_mode())"

# Check logs for specific errors
tail -f logs/trading_bot.log
```

#### "Database connection failed"
```bash
# Check file permissions
ls -la data/trades.db

# Reset database if corrupted
rm data/trades.db
python -c "from src.database import db_manager; print('DB reset')"
```

### API Rate Limits

Coinbase enforces rate limits:
- **Public endpoints**: 10 requests/second
- **Private endpoints**: 5 requests/second
- **Order placement**: 5 requests/second

The bot automatically handles rate limiting with exponential backoff.

### Performance Issues

- **High CPU usage**: Reduce `MARKET_CHECK_INTERVAL` in settings
- **Memory issues**: Lower `HISTORICAL_DATA_DAYS` or increase RAM
- **Slow dashboard**: Check WebSocket connection and browser cache

## 🔍 Development

### Project Structure

```
crypto-trader-bot/
├── config/              # Configuration files
│   ├── settings.py      # Trading parameters and constants
│   └── api_keys.env     # Secure API credential storage
├── src/                 # Core application modules
│   ├── coinbase_api.py  # Coinbase Advanced Trade API wrapper
│   ├── data_collector.py # Market data collection and processing
│   ├── ai_model.py      # Machine learning trading signals
│   ├── risk_manager.py  # Position sizing and risk controls
│   ├── trading_engine.py # Trade execution and signal processing
│   ├── dashboard.py     # Web interface and API endpoints
│   ├── database.py      # SQLite database operations
│   └── currency_utils.py # Multi-currency conversion utilities
├── templates/           # Jinja2 HTML templates
│   ├── dashboard.html   # Main trading dashboard
│   └── settings.html    # Configuration interface
├── static/              # Static assets (CSS, JS, images)
├── data/                # Persistent data storage
├── logs/                # Application logs and debugging
├── models/              # Trained machine learning models
├── tests/               # Unit and integration tests
├── main.py              # Application entry point
├── docker-compose.yml   # Docker orchestration
├── Dockerfile           # Container build configuration
├── requirements.txt     # Python dependencies
└── README.md            # This documentation
```

### Adding New Features

1. **Plan the Feature**
```python
# Define requirements and integration points
# Consider risk management implications
```

2. **Implement the Code**
```python
# Add new module in src/
# Follow existing patterns and error handling
# Add comprehensive logging
```

3. **Add Configuration**
```python
# Update config/settings.py with new parameters
# Ensure backward compatibility
```

4. **Write Tests**
```python
# Add unit tests in tests/
# Test edge cases and error conditions
```

5. **Update Documentation**
```markdown
# Update README.md and docstrings
# Add API documentation if applicable
```

### Testing Framework

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src/ --cov-report=html

# Run specific test module
pytest tests/test_api.py

# Run integration tests
pytest tests/integration/
```

### Code Quality

- **Linting**: `flake8 src/`
- **Type checking**: `mypy src/`
- **Security**: `bandit src/`
- **Documentation**: `pydoc src/`

## 🤝 Contributing

### Development Setup

1. **Fork the repository**
2. **Create feature branch**
   ```bash
   git checkout -b feature/new-trading-strategy
   ```
3. **Set up development environment**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Make changes with tests**
5. **Run quality checks**
   ```bash
   pytest tests/
   flake8 src/
   mypy src/
   ```
6. **Commit and push**
   ```bash
   git commit -m 'feat: add new trading strategy'
   git push origin feature/new-trading-strategy
   ```
7. **Open Pull Request**

### Commit Conventions

- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation
- `style:` Code style changes
- `refactor:` Code refactoring
- `test:` Testing
- `chore:` Maintenance

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

**This software is for educational and research purposes only.**

Cryptocurrency trading involves significant risk of loss. Never trade with money you cannot afford to lose. Always test strategies in paper trading mode first. The authors are not responsible for any financial losses incurred through the use of this software.

**Key Risks:**
- Market volatility can result in rapid losses
- Technical issues can prevent order execution
- API downtime can affect trading
- Past performance does not guarantee future results

**Safety Recommendations:**
- Start with small amounts ($10-20 per trade)
- Use paper trading mode extensively before live trading
- Monitor positions regularly
- Set conservative risk limits
- Have emergency stop procedures ready

## 🙏 Acknowledgments

- **Coinbase Advanced Trade API** - Trading infrastructure
- **FastAPI** - Web framework
- **Scikit-learn** - Machine learning
- **SQLAlchemy** - Database ORM
- **Bootstrap 5** - UI framework
- **Raspberry Pi Community** - Hardware platform

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/crypto-trader-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/crypto-trader-bot/discussions)
- **Documentation**: [Wiki](https://github.com/yourusername/crypto-trader-bot/wiki)

---

**Happy Trading!** 🚀📈

*Built with ❤️ for the crypto trading community*
