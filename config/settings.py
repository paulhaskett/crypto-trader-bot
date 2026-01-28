"""
Configuration settings for the crypto trading bot.
This file contains all configurable parameters for the bot's operation.
"""

import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'api_keys.env'))

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

    # Trading Configuration
    BASE_CURRENCY: str = 'GBP'  # Primary base currency for portfolio valuation
    BASE_CURRENCIES: list = ['USD', 'USDC']  # Support USD valuation for risk management
    QUOTE_CURRENCIES: list = ['BTC', 'ETH', 'SOL', 'XRP', 'LTC']  # Cryptos available for trading
    PRODUCT_IDS: list = ['BTC-GBP', 'ETH-GBP', 'SOL-GBP', 'LTC-GBP', 'DOT-GBP', 'ADA-GBP', 'LINK-GBP', 'UNI-GBP']  # 8 GBP pairs only - removed AVAX-USD to fix model training conflicts
    FOCUS_CURRENCIES: list = ['BTC', 'ETH', 'SOL', 'XRP', 'LTC']  # Complete multi-currency focus
    DIVERSIFY_AFTER_VALUE: float = 50.0  # Add more cryptos after portfolio reaches $50

    # Portfolio Display Settings
    MIN_PORTFOLIO_VALUE_DISPLAY: float = 0.001  # Hide balances worth less than $0.001 (temporarily lowered for small balances)
    MAX_PORTFOLIO_CURRENCIES: int = 20  # Limit display to top 20 currencies by value

    # Risk Management
    MAX_POSITION_SIZE: float = 0.02  # 2% of portfolio per trade (enables more trading activity)
    MAX_DAILY_TRADES: int = 8  # Maximum trades per day (day trading frequency)
    MAX_CONCURRENT_POSITIONS: int = 4  # Maximum open positions at once (balanced approach)
    MIN_TRADE_AMOUNT: float = 0.01  # Minimum absolute trade amount in USD (reduced for small crypto amounts)
    MAX_CRYPTO_EXPOSURE: float = 0.5  # Maximum 50% exposure to any single crypto
    PAPER_TRADING_PORTFOLIO_VALUE: float = 10000.0  # Default $10k for paper trading

    # Stop Loss Configuration
    STOP_LOSS_ATR_MULTIPLIER: float = 1.5  # ATR-based stop loss multiplier
    TAKE_PROFIT_LEVELS: list = [2.0, 3.0]  # Profit taking levels for day trading (2-3% gains)

    # AI/ML Configuration
    MODEL_CONFIDENCE_THRESHOLD: float = 0.50  # Set to 50% to enable more trading opportunities
    FEATURE_WINDOW_SIZE: int = 48  # Hours of data for features (48h - more context)
    PREDICTION_HORIZON: int = 2  # Hours to predict ahead (shorter for small trades)
    CONSERVATIVE_MODE: bool = False  # Enable day trading mode

    # Data Collection
    CANDLE_GRANULARITY: str = "ONE_HOUR"  # 1-hour candles
    HISTORICAL_DATA_DAYS: int = 365  # Days of historical data to fetch

    # Scheduling
    MARKET_CHECK_INTERVAL: int = 1800  # Check market every 30 minutes (balanced approach)
    DATA_UPDATE_INTERVAL: int = 1800  # Update data every 30 minutes (more frequent)
    TRADING_HOURS_ONLY: bool = True  # Only trade during active market hours

    # Safety Limits
    MAX_DAILY_LOSS: float = 0.01  # Stop trading if daily loss exceeds 1% ($0.16)
    MAX_WEEKLY_LOSS: float = 0.03  # Stop trading if weekly loss exceeds 3% ($0.47)
    CIRCUIT_BREAKER_VOLATILITY: float = 0.10  # Pause on 10% volatility spike (more sensitive)
    EMERGENCY_STOP: bool = False  # Manual emergency stop
    MAX_CONSECUTIVE_LOSSES: int = 3  # Stop after 3 consecutive losing trades
    COOLDOWN_PERIOD: int = 3600  # 1-hour cooldown after losses

    # Database
    DATABASE_URL: str = 'sqlite:///data/trades.db'

    # Logging
    LOG_LEVEL: str = 'DEBUG'
    LOG_FILE: str = 'logs/trading_bot.log'

    # Web Dashboard
    DASHBOARD_HOST: str = '0.0.0.0'
    DASHBOARD_PORT: int = 8000

    # Currency Configuration
    DISPLAY_CURRENCY: str = 'GBP'  # Default display currency (options: 'USD', 'GBP')
    SUPPORTED_CURRENCIES: list = ['USD', 'GBP']  # Supported display currencies
    CURRENCY_CACHE_DURATION: int = 3600  # Cache exchange rates for 1 hour
    
    # Balance Monitoring
    GBP_WARNING_THRESHOLD: float = 10.0  # Warning when < £10
    GBP_CRITICAL_THRESHOLD: float = 5.0   # Critical when < £5
    
    # Network Proxy Configuration
    USE_PROXY: bool = False  # Temporarily disable proxy for testing
    PROXY_HOST: str = 'crypto-trader-nginx'  # Nginx container hostname
    COINBASE_API_PROXY_PORT: int = 3128  # Port for Coinbase Advanced API
    EXCHANGE_API_PROXY_PORT: int = 3129  # Port for Coinbase Exchange API
    PROXY_TIMEOUT: int = 30  # Proxy connection timeout
    PROXY_VERIFY_SSL: bool = True  # SSL verification through proxy

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

        if self.MAX_POSITION_SIZE > 0.1:
            raise ValueError("MAX_POSITION_SIZE should not exceed 10% for safety")

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