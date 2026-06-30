"""
Configuration settings for the crypto trading bot.
This file contains all configurable parameters for the bot's operation.

v1.3.0 - Updated to use unified trading_pairs.yaml configuration.
All trading pairs defined in config/trading_pairs.yaml - no code changes needed to add new pairs.
Position sizing automatically calculated from number of active pairs.
"""

import os
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'api_keys.env'))

# Import trading pairs configuration
from config.trading_pairs import (
    get_active_pairs,
    get_active_base_currencies,
    get_position_sizing_config,
    get_data_source_config,
    get_source_weights,
)

class Settings:
    """
    Configuration class that holds all bot settings.
    Uses environment variables for sensitive data and constants for others.
    """

    # Coinbase API Configuration
    # Get these from https://www.coinbase.com/settings/api
    COINBASE_API_KEY: str = os.getenv('COINBASE_API_KEY', '')
    COINBASE_API_SECRET: str = os.getenv('COINBASE_API_SECRET', '')
    # Advanced Trade API Key (with trading permissions)
    # Use the full organizations path as provided by Coinbase
    COINBASE_ADVANCED_API_KEY: str = os.getenv('TRADING_COINBASE_API_KEY', COINBASE_API_KEY)
    COINBASE_ADVANCED_API_SECRET: str = os.getenv('TRADING_COINBASE_API_KEY_SECRET', COINBASE_API_SECRET)

    # Trading Configuration - Loaded from trading_pairs.yaml
    # v1.3.0 - All pairs defined in config/trading_pairs.yaml
    BASE_CURRENCY: str = 'GBP'  # Primary base currency for portfolio valuation
    BASE_CURRENCIES: list = ['USD', 'USDC']  # Support USD valuation for risk management
    QUOTE_CURRENCIES: list = ['BTC', 'ETH']  # Cryptos available for trading (from config)
    PRODUCT_IDS: list = get_active_pairs()  # Loaded from trading_pairs.yaml
    # Train on BOTH USD and GBP pairs for maximum coverage
    # v1.3.1: Train on GBP pairs directly for trading, also USD for robustness
    TRAINING_PAIRS: list = get_active_pairs() + [p.replace('-GBP', '-USD') for p in get_active_pairs()]
    FOCUS_CURRENCIES: list = get_active_base_currencies()  # Loaded from config
    DIVERSIFY_AFTER_VALUE: float = 50.0  # Add more cryptos after portfolio reaches $50

    # Position Sizing - v1.3.0 - Auto-calculated from config
    # 45% per pair (2 pairs = 90% max deployed, 10% reserve)
    _position_config = get_position_sizing_config()
    MAX_POSITION_SIZE: float = _position_config.get('max_per_pair_percent', 0.45)
    MAX_CONCURRENT_POSITIONS: int = len(PRODUCT_IDS)  # One position per active pair
    CASH_RESERVE_PERCENT: float = _position_config.get('min_cash_reserve', 0.10)

    # Portfolio Display Settings
    MIN_PORTFOLIO_VALUE_DISPLAY: float = 0.001  # Hide balances worth less than $0.001 (temporarily lowered for small balances)
    MAX_PORTFOLIO_CURRENCIES: int = 20  # Limit display to top 20 currencies by value
    TIMEZONE: str = 'Europe/London'  # Timezone for timestamps (auto-adjusts for BST/GMT)

    # Risk Management - v1.3.0 (position sizing above)
    MAX_DAILY_TRADES: int = 1  # Maximum 1 trade per day (more selective)
    MIN_TRADE_VALUE: float = 15.0  # Minimum £15 trade value (avoid small trades due to fees)
    MIN_TRADE_AMOUNT: float = 0.000001  # Minimum absolute trade amount (fallback)
    MIN_TRADE_AMOUNT_HIGH: float = 0.0000001  # Minimum for BTC (~£10 at £50k)
    MIN_TRADE_AMOUNT_MID_HIGH: float = 0.000003  # Minimum for ETH (~£10 at £1500)
    MIN_TRADE_AMOUNT_MID: float = 0.00008  # Minimum for mid-tier (~£10 at £65)
    MIN_TRADE_AMOUNT_LOW: float = 0.5  # Minimum for low-tier (~£5 at £10)
    PRICE_TIER_HIGH: float = 10000.0  # Price threshold for HIGH tier
    PRICE_TIER_MID_HIGH: float = 1000.0  # Price threshold for MID-HIGH tier
    PRICE_TIER_MID: float = 10.0  # Price threshold for MID tier
    MAX_CRYPTO_EXPOSURE: float = 0.25  # Maximum 25% exposure to any single crypto
    PAPER_TRADING_PORTFOLIO_VALUE: float = 10000.0  # Simulated $10k for paper trading
    GBP_BUFFER: float = 2.0  # Keep £2 GBP minimum balance
    STOP_LOSS_MIN_PERCENT: float = 0.10  # Stop loss at 10% below entry (user configurable 5-20%)
    
    # Position Replacement Settings
    POSITION_REPLACEMENT_ENABLED: bool = True  # Enable position replacement when better signals appear
    REPLACEMENT_CONFIDENCE_THRESHOLD: float = 0.08  # 8% improvement required to replace position
    REPLACEMENT_MIN_PROFIT: float = 0.02  # Position must be 2%+ profit to allow replacement
    REPLACEMENT_COOLDOWN_HOURS: int = 24  # Don't replace same position within 24 hours
    REPLACEMENT_MAX_PER_CYCLE: int = 1  # Maximum 1 replacement per cycle
    ALLOW_SELL_REPLACEMENT: bool = False  # Disabled: SELL signals can't replace positions
    
    # Buy Cooldown - Prevent excessive buying
    BUY_COOLDOWN_HOURS: int = 2  # Don't buy same pair within 2 hours after sell
    BUY_COOLDOWN_AFTER_LOSS_HOURS: int = 12  # Don't buy same pair within 12h after losing trade
    BUY_MAX_ATTEMPTS_PER_DAY: int = 1  # Maximum 1 buy attempt per pair per day

    # Position Scaling (Averaging Down) - Single Scale-In (lowest fees)
    SCALE_IN_ENABLED: bool = True  # Enable scale-in (averaging down)
    SCALE_IN_LEVELS: list = [2.0]  # Single trigger level (neutral)
    SCALE_IN_SIZE_BY_LEVEL: list = [1.0]  # 100% of original position size (single trade)
    MAX_SCALE_INS_PER_POSITION: int = 1  # Max 1 scale-in per position
    SCALE_IN_COOLDOWN_HOURS: int = 4  # Minimum hours between scale-ins
    SCALE_IN_GLOBAL_BLOCK: bool = False  # Emergency stop - block all scale-ins
    SCALE_IN_MAX_GBP_PER_CYCLE: float = 15.0  # Max GBP spent on scale-ins per cycle
    SCALE_IN_MIN_SIGNAL_CONFIDENCE: float = 0.60  # Min AI signal confidence to scale-in
    
    # Position Scaling (Taking Profits) - Scale-Out
    SCALE_OUT_ENABLED: bool = False  # Disable - prevent early selling
    SCALE_OUT_PERCENTAGES: list = [25, 25, 50]  # % to sell at each TP level (reduced for lower fees)
    SCALE_OUT_MIN_PROFIT_PCT: float = 2.0  # Minimum 2% profit before any scale-out (fallback)
    MIN_PROFIT_BEAR: float = 0.03      # Strong Downtrend: 3% min profit (covers fees + margin)
    MIN_PROFIT_NEUTRAL: float = 0.05   # Neutral/Sideways: 5% min profit
    MIN_PROFIT_BULL: float = 0.10      # Strong Uptrend: 10% min profit (strong profit target)
    
    # Multi-level trend profit thresholds (v2.2)
    MIN_PROFIT_STRONG_UPTREND: float = 0.12  # Strong uptrend: 12% (ride the trend)
    MIN_PROFIT_WEAK_UPTREND: float = 0.06  # Weak uptrend (recovery): 6%
    MIN_PROFIT_SIDEWAYS: float = 0.05      # Sideways: 5%
    MIN_PROFIT_WEAK_DOWNTREND: float = 0.03  # Weak downtrend (rebound): 3%
    MIN_PROFIT_STRONG_DOWNTREND: float = 0.02  # Strong downtrend: 2% (may recover)
    
    TRAILING_STOP_PERCENT: float = 0.02  # 2% trailing stop (user request)
    TRAILING_ACTIVATION_BUFFER: float = 0.02  # 2% above break-even to activate trailing
    
    # v2.4: Per-regime trailing stop (matches MIN_PROFIT thresholds)
    # Trailing stop only activates when price is above break-even (covering fees)
    # Uses trend regime from signal: 'uptrend', 'neutral', 'downtrend'
    TRAILING_STOP_REGIME_MAP: Dict[str, float] = {
        'uptrend': 0.02,      # 2% trailing (user request)
        'neutral': 0.02,      # 2% trailing (user request)
        'downtrend': 0.02,    # 2% trailing (user request)
    }
    
    # Fee settings
    FEE_CHECK_INTERVAL_DAYS: int = 7  # Check fees weekly
    DEFAULT_MAKER_FEE: float = 0.006  # 0.6% fallback (intro tier)
    DEFAULT_TAKER_FEE: float = 0.012  # 1.2% fallback (intro tier)
    SCALE_OUT_MIN_PROFIT_BEAR: float = 0.03   # Strong Downtrend: scale out at 3%+
    SCALE_OUT_MIN_PROFIT_NEUTRAL: float = 0.06  # Neutral/Sideways: scale out at 6%+
    SCALE_OUT_MIN_PROFIT_BULL: float = 0.10    # Strong Uptrend: scale out at 10%+
    
    # Regime-based scale-in levels (single trigger - lowest fees)
    SCALE_IN_LEVELS_BEAR: list = [3.0]       # Downtrend: trigger at 3% drop
    SCALE_IN_LEVELS_NEUTRAL: list = [2.0]   # Neutral: trigger at 2% drop
    SCALE_IN_LEVELS_BULL: list = [1.0]      # Uptrend: trigger at 1% drop

    # AI/ML Configuration
    MODEL_CONFIDENCE_THRESHOLD: float = 0.65  # 65% - reduce signals
    FEATURE_WINDOW_SIZE: int = 48  # Hours of data for features (48h - more context)
    PREDICTION_HORIZON: int = 12  # Hours to predict ahead (12h aligns with patient trading)
    
    # v2.1: Dynamic Confidence Threshold
    USE_DYNAMIC_THRESHOLD: bool = True           # Enable volatility-based threshold
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.80    # 80% - high quality signals only
    HIGH_VOL_THRESHOLD: float = 0.85            # Higher threshold in high volatility
    LOW_VOL_THRESHOLD: float = 0.70             # Lower threshold in low volatility
    VOLATILITY_HIGH_RATIO: float = 1.5          # vol_ratio threshold for high volatility
    
    # v1.9.0: Dynamic Threshold (ATR-based)
    USE_ATR_THRESHOLD: bool = True           # Enable ATR threshold
    ATR_PERIOD: int = 24                    # 24 hours (1 day)
    ATR_MULTIPLIER: float = 0.05            # k × ATR threshold (lowered for more signals in low volatility)
    ATR_MIN_THRESHOLD: float = 0.0001        # Minimum 0.01% floor (lowered for more signals in low volatility)
    USE_ASYMMETRIC_ATR: bool = False        # Future: different k for BUY/SELL
    
    # v2.0: Volatility Regime Filter (ATR-based)
    USE_VOLATILITY_REGIME: bool = True       # Enable volatility-based ATR adjustment
    VOLATILITY_ATR_SHORT: int = 24           # Short ATR period (hours)
    VOLATILITY_ATR_LONG: int = 72            # Long ATR period (hours)  
    VOLATILITY_RATIO_THRESHOLD: float = 1.5 # vol_ratio > 1.5 = high volatility
    VOLATILITY_HIGH_VOL_MULTIPLIER: float = 0.25  # Multiplier when high volatility (k=0.25)
    VOLATILITY_LOW_VOL_MULTIPLIER: float = 0.10   # Multiplier when low volatility (optional)
    
    # v1.9.0: Label Format
    LABEL_TYPE: str = '3class'              # 'binary' (BUY/SELL only) or '3class' (BUY/HOLD/SELL)
    LABEL_DISTRIBUTION_MONITOR: bool = True # Log class counts
    
    # v1.9.0: Walk-Forward Validation
    USE_WALK_FORWARD: bool = True           # Walk-forward validation default ON
    WALK_FORWARD_SPLITS: int = 3
    WALK_FORWARD_TRAIN_SIZE: int = 300       # samples per window
    EVALUATE_GBP_ONLY: bool = True           # Evaluate on GBP pairs only (target market)
    
    # v1.9.1: Feature Engineering - Enable for 40 features
    ADD_PAIR_FEATURES: bool = True          # Enable to use all pair features
    ADD_CURRENCY_INDICATOR: bool = True     # Enable for is_gbp, is_usd
    USE_LOG_RETURNS: bool = True            # Enable log returns feature
    USE_ATR_NORMALIZATION: bool = True      # Enable ATR normalization
    
    # Legacy fallback (used when ATR disabled)
    TRAINING_MIN_PROFIT_THRESHOLD: float = 0.001  # 0.1% min price move
    
    CONSERVATIVE_MODE: bool = False  # Enable day trading mode

    # Regime Detection (Market Trend) - Enhanced v2.2
    REGIME_DETECTION_ENABLED: bool = True  # Enable regime detection
    REGIME_LONG_MA_PERIOD: int = 50  # Standard 50-period MA for trend detection
    REGIME_SHORT_MA_PERIOD: int = 20  # Standard 20-period MA for trend detection
    REGIME_THRESHOLD: float = 0.002  # 0.2% - match chart uptrend detection
    REGIME_DOWNTREND_BUY_THRESHOLD: float = 0.85  # Need 85% confidence in downtrend to buy
    
    # Multi-Level Trend Detection (v2.2)
    # Higher timeframe MAs for trend confirmation
    REGIME_MEDIUM_MA_PERIOD: int = 100  # 100 candles for medium-term trend
    REGIME_STRONG_MA_PERIOD: int = 200  # 200 candles for long-term trend
    
    # Trend level thresholds (% difference)
    REGIME_WEAK_TREND_THRESHOLD: float = 0.02  # 2% - weak trend threshold
    REGIME_SIDEWAYS_MAX_SPREAD: float = 0.015  # 1.5% max spread for sideways
    
    # Higher highs/lower lows detection
    REGIME_HIGHER_HIGHS_PERIOD: int = 20  # Lookback for higher highs
    REGIME_LOWER_LOWS_PERIOD: int = 20  # Lookback for lower lows
    REGIME_MIN_SWINGS: int = 3  # Minimum swings to confirm trend
    
    # RSI boundaries for trend strength
    REGIME_STRONG_RSI_UPPER: float = 65.0  # Strong uptrend RSI lower bound
    REGIME_STRONG_RSI_LOWER: float = 35.0  # Strong downtrend RSI upper bound
    REGIME_WEAK_RSI_UPPER: float = 58.0  # Weak uptrend RSI lower bound
    REGIME_WEAK_RSI_LOWER: float = 42.0  # Weak downtrend RSI upper bound
    
    # Model version - auto-retrain if this changes
    REGIME_VERSION: str = "v2.2"  # v2.2 = multi-level trend detection
    REGIME_VERSION_HASH: str = f"{REGIME_STRONG_RSI_UPPER:.0f}{REGIME_STRONG_RSI_LOWER:.0f}{REGIME_WEAK_RSI_UPPER:.0f}{REGIME_WEAK_RSI_LOWER:.0f}"
    # Hash: 6558355842 - change triggers auto-retrain
    
    # Trend change sensitivity
    REGIME_CONFIRMATION_CANDLES: int = 3  # Require 3 candles to confirm trend change
    
    # Buy-the-Dip (Disabled - regime detection blocks downtrends)
    BUY_DIP_THRESHOLD: float = 0.0  # Disabled - regime detection blocks BUY in downtrends

    # Neural Network / Ensemble Settings
    ENSEMBLE_ENABLED: bool = True  # Enable ensemble
    NN_HIDDEN_LAYERS: tuple = (64, 32)  # Medium network: 2 hidden layers
    NN_ACTIVATION: str = 'relu'  # ReLU activation
    NN_ALPHA: float = 0.001  # L2 regularization
    NN_MAX_ITER: int = 500  # Max training iterations
    
    # Model toggle controls (enable/disable individual models)
    USE_RF_MODEL: bool = True   # Random Forest
    USE_LR_MODEL: bool = False  # Disabled - poor performance
    USE_MLP_MODEL: bool = False  # Disabled - low F1 scores (0.19-0.60)
    USE_GB_MODEL: bool = True   # Gradient Boosting
    
    # Ridge Classifier (alternative linear model - better than LR for multicollinearity)
    USE_RIDGE_MODEL: bool = True  # NEW - Linear model with L2 regularization
    RIDGE_ALPHA: float = 1.0      # Regularization strength
    
    # Best ensemble feature - automatically selects best model combination
    BEST_ENSEMBLE_ENABLED: bool = True  # Enable best ensemble selection
    BEST_ENSEMBLE_MIN_TRADES: int = 5  # Minimum trades before selecting best ensemble
    
    # Ensemble weight mode: 'performance' (auto F1-based) or 'manual'
    ENSEMBLE_WEIGHT_MODE: str = 'performance'
    
    # Manual weights (used if ENSEMBLE_WEIGHT_MODE='manual')
    RF_WEIGHT: float = 0.35
    LR_WEIGHT: float = 0.25
    MLP_WEIGHT: float = 0.15
    GB_WEIGHT: float = 0.30  # Increased from 0.25 - HistGradientBoosting with balanced class weights
    MIN_MODEL_AGREEMENT: float = 0.15  # Minimum ensemble score to avoid HOLD (below this = disagreement)
    ENSEMBLE_VOTE_THRESHOLD: float = 0.75  # v2.9.1: Models must agree at this rate for BUY/SELL (75% = 3/4 models)
    
    # Gradient Boosting Settings
    GB_N_ESTIMATORS: int = 150  # More boosting stages
    GB_LEARNING_RATE: float = 0.05  # Slower learning for better accuracy
    GB_MAX_DEPTH: int = 5  # Deeper trees
    GB_MIN_SAMPLES_SPLIT: int = 2  # Min samples to split node

    # Data Collection
    CANDLE_GRANULARITY: str = "ONE_HOUR"  # 1-hour candles
    HISTORICAL_DATA_DAYS: int = 365  # Days of historical data to fetch

    # Scheduling
    MARKET_CHECK_INTERVAL: int = 14400  # Check market every 4 hours (reduced from 60min to prevent overtrading)
    DATA_UPDATE_INTERVAL: int = 1800  # Update data every 30 minutes
    TRADING_HOURS_ONLY: bool = True  # Only trade during active market hours
    TRADE_COOLDOWN_SECONDS: int = 300  # 5 min cooldown between trades for same product

    # Auto Model Retraining
    AUTO_RETRAIN_ENABLED: bool = True  # Enable automatic weekly model retraining
    AUTO_RETRAIN_DAY_OF_WEEK: str = 'sun'  # Day of week (sun, mon, tue, etc.)
    AUTO_RETRAIN_HOUR: int = 3  # Hour of day (3 AM)
    AUTO_RETRAIN_MINUTE: int = 0  # Minute

    # Safety Limits
    MAX_DAILY_LOSS: float = 0.02  # Stop trading if daily loss exceeds 2% ($0.32)
    MAX_WEEKLY_LOSS: float = 0.05  # Stop trading if weekly loss exceeds 5% ($0.79)
    CIRCUIT_BREAKER_VOLATILITY: float = 0.10  # Pause on 10% volatility spike (more sensitive)
    EMERGENCY_STOP: bool = False  # Manual emergency stop
    MAX_CONSECUTIVE_LOSSES: int = 4  # Stop after 4 consecutive losing trades
    COOLDOWN_PERIOD: int = 1800  # 30-minute cooldown after losses

    # Trading Mode Configuration
    PAPER_TRADING_MODE: bool = True  # Enable paper trading for testing (safe mode)
    TRADING_STARTUP_DELAY: int = 60  # Seconds to wait before first trade in live mode

    # Database
    DATABASE_URL: str = 'sqlite:///data/trades.db'

    # Logging
    LOG_LEVEL: str = 'DEBUG'
    LOG_FILE: str = 'logs/trading_bot.log'
    
    # Prediction Logging
    PREDICTION_LOGGING_ENABLED: bool = True  # Enable detailed prediction logging for auditability
    PREDICTION_LOG_BUFFER_SIZE: int = 100   # Number of predictions to buffer before writing to disk

    # Web Dashboard
    DASHBOARD_HOST: str = '0.0.0.0'
    DASHBOARD_PORT: int = 8000

    # Currency Configuration
    DISPLAY_CURRENCY: str = 'GBP'  # Default display currency (options: 'USD', 'GBP')
    SUPPORTED_CURRENCIES: list = ['USD', 'GBP']  # Supported display currencies
    CURRENCY_CACHE_DURATION: int = 3600  # Cache exchange rates for 1 hour
    
    # Balance Monitoring
    GBP_WARNING_THRESHOLD: float = 2.0  # Warning when < £2
    GBP_CRITICAL_THRESHOLD: float = 1.0   # Critical when < £1
    
    # Network Proxy Configuration
    USE_PROXY: bool = False  # Temporarily disable proxy for testing
    PROXY_HOST: str = 'crypto-trader-nginx'  # Nginx container hostname
    COINBASE_API_PROXY_PORT: int = 3128  # Port for Coinbase Advanced API
    EXCHANGE_API_PROXY_PORT: int = 3129  # Port for Coinbase Exchange API
    PROXY_TIMEOUT: int = 30  # Proxy connection timeout
    PROXY_VERIFY_SSL: bool = True  # SSL verification through proxy

    # Multi-Source Market Data Configuration - v1.3.0
    # Weights loaded from trading_pairs.yaml, with Binance added
    MULTI_SOURCE_ENABLED: bool = True  # Enable multi-source price aggregation
    PRICE_SOURCE_WEIGHTS: Dict[str, float] = get_source_weights()  # From config/trading_pairs.yaml
    MAX_PRICE_DEVIATION: float = 0.03  # 3% outlier detection (normal market spread)
    CONSENSUS_MIN_SOURCES: int = 2  # Minimum sources required for consensus
    CONSENSUS_MIN_CONFIDENCE: float = 0.60  # 60% confidence threshold for trading
    
    # Spread Alert Configuration - v2.2
    # Used for arbitrage opportunity detection
    SPREAD_ALERT_THRESHOLD: float = 0.01  # 1% spread = alert
    SPREAD_WARNING_THRESHOLD: float = 0.02  # 2% spread = warning
    SPREAD_LOG_ENABLED: bool = True  # Enable spread logging
    
    # WebSocket Configuration (per slippage-modeling.md: prioritize high-liquidity pairs)
    WEBSOCKET_ENABLED: bool = True  # Enable WebSocket for real-time prices
    WEBSOCKET_PAIRS: list = ['BTC-GBP', 'ETH-GBP', 'BTC-USD', 'ETH-USD']  # High-liquidity pairs
    
    # Rate Limiting (per source)
    COINGECKO_RATE_LIMIT: int = 10  # calls per minute (free tier)
    KRAKEN_RATE_LIMIT: int = 60    # calls per minute
    
    # Priority pairs - fetched first in batch requests
    PRIORITY_PAIRS: list = ['BTC-GBP', 'ETH-GBP']

    def __init__(self):
        """Initialize settings and validate configuration."""
        self._validate_configuration()

    def _validate_configuration(self):
        """Validate that all required settings are present."""
        if not self.COINBASE_API_KEY or not self.COINBASE_API_SECRET:
            raise ValueError(
                "COINBASE_API_KEY and COINBASE_API_SECRET must be set in .env file. "
                "Get them from https://www.coinbase.com/settings/api"
            )

        if self.MAX_POSITION_SIZE > 0.50:
            raise ValueError("MAX_POSITION_SIZE should not exceed 50% for safety (v1.3.0: 45% per pair)")

        if self.MAX_DAILY_LOSS > 0.05:
            raise ValueError("MAX_DAILY_LOSS should not exceed 5% for risk management")

    def get_product_id(self, quote_currency: str) -> str:
        """Get the product ID for a quote currency."""
        return f"{quote_currency}-{self.BASE_CURRENCY}"

    def is_sandbox_mode(self) -> bool:
        """Check if running in sandbox mode (for testing)."""
        return os.getenv('SANDBOX_MODE', 'false').lower() == 'true'

    def get_database_path(self) -> str:
        """Get the full path to the database file."""
        return os.path.join(os.path.dirname(__file__), '..', self.DATABASE_URL.replace('sqlite:///', ''))

# Global settings instance
settings = Settings()