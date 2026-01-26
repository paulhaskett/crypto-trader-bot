"""
Data collector module for market data and historical prices.

This module is responsible for:
- Fetching real-time market data from Coinbase API
- Collecting historical price data for analysis
- Processing and cleaning data for AI models
- Caching data to avoid repeated API calls

Educational Notes:
- Market data comes in different formats: tickers, candles (OHLCV), order book
- Candles provide aggregated price action over time intervals
- Real-time data requires WebSocket connections for low latency
- Data preprocessing is crucial for AI model accuracy
"""

import logging
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from config.settings import settings
from src.coinbase_api import coinbase_api
from src.database import db_manager

logger = logging.getLogger(__name__)


class DataCollector:
    """
    Main data collector class for market data.

    Handles all data acquisition, processing, and storage operations.
    Provides clean interfaces for other modules to access market data.
    """

    def __init__(self):
        """Initialize the data collector."""
        self.last_update = {}
        self.market_data_cache = {}

    def get_current_prices(self) -> Dict[str, float]:
        """
        Get current market prices for all configured trading pairs AND USD equivalents.

        Returns:
            Dictionary mapping product_id to current price (includes both trading pairs and USD pairs)
        """
        prices = {}

        # 1. Get existing BTC-quoted prices for trading
        for product_id in settings.PRODUCT_IDS:
            try:
                ticker = coinbase_api.get_product_ticker(product_id)
                price = ticker.get('price')
                
                if price and price > 0:
                    prices[product_id] = price
                    logger.info(f"Current price for {product_id}: ${price:.2f}")
                else:
                    logger.warning(f"Invalid price data for {product_id}: {ticker}")
                    # Use cached price if available
                    if product_id in self.market_data_cache:
                        prices[product_id] = self.market_data_cache[product_id]
                        logger.warning(f"Using cached price for {product_id}")
            
            except Exception as e:
                logger.error(f"Failed to get price for {product_id}: {e}")
                # Use cached price if available
                if product_id in self.market_data_cache:
                    prices[product_id] = self.market_data_cache[product_id]
                    logger.warning(f"Using cached price for {product_id}")

        # 2. NEW: Get USD prices for base currencies (for risk management)
        base_currencies = set()
        for product_id in settings.PRODUCT_IDS:
            base_currency = product_id.split('-')[0]
            base_currencies.add(base_currency)
        
        # 2. Get USD prices for base currencies (for risk management)  
        for base_currency in base_currencies:
            usd_product_id = f"{base_currency}-USD"
            
            # Skip BTC-USD since we already have BTC as quote currency in GBP pairs
            if usd_product_id in prices:
                logger.debug(f"USD price for {base_currency} already available from existing pairs")
                continue
            
            # Skip GBP-USD requests - use existing exchange rate instead
            if base_currency == 'GBP':
                logger.info(f"✅ SKIPPED GBP-USD request - using exchange rate instead")
                continue
                
            try:
                ticker = coinbase_api.get_product_ticker(usd_product_id)
                price = ticker.get('price')
                
                if price and float(price) > 0:
                    prices[usd_product_id] = float(price)
                    logger.info(f"USD price for {base_currency}: ${float(price):.2f} (for risk management)")
                else:
                    logger.warning(f"Invalid USD price data for {usd_product_id}: {ticker}")
                    # Use cached price if available
                    if usd_product_id in self.market_data_cache:
                        prices[usd_product_id] = self.market_data_cache[usd_product_id]
                        logger.warning(f"Using cached USD price for {usd_product_id}")
            
            except Exception as e:
                logger.debug(f"Could not fetch USD price for {base_currency}: {e}")
                # This is not critical - some currencies might not have USD pairs
                # Risk manager will handle missing USD prices gracefully
        
        return prices

    def collect_historical_data(self, product_id: str, days: int = None) -> pd.DataFrame:
        """
        Collect historical candle data for a trading pair.

        Args:
            product_id: Trading pair (e.g., 'BTC-USD')
            days: Number of days of data to collect (defaults to settings)

        Returns:
            Pandas DataFrame with OHLCV data
        """
        days = days or settings.HISTORICAL_DATA_DAYS

        try:
            # Check if we have recent data in database
            cached_data = self._get_cached_data(product_id, days)
            if cached_data is not None and not cached_data.empty:
                logger.info(f"Using cached data for {product_id} ({len(cached_data)} records)")
                return cached_data

            # Fetch from API
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            logger.info(f"Fetching historical data for {product_id} from {start_date.date()} to {end_date.date()}")

            df = coinbase_api.get_candles(
                product_id=product_id,
                start=start_date,
                end=end_date,
                granularity=settings.CANDLE_GRANULARITY
            )

            if not df.empty:
                # Save to database for future use
                db_manager.save_market_data(product_id, df)

                # Cache in memory
                self.market_data_cache[product_id] = df
                self.last_update[product_id] = datetime.now()

            return df

        except Exception as e:
            logger.error(f"Failed to collect historical data for {product_id}: {e}")
            return pd.DataFrame()

    def _get_cached_data(self, product_id: str, days: int) -> Optional[pd.DataFrame]:
        """
        Retrieve cached market data from database if recent enough.

        Args:
            product_id: Trading pair identifier
            days: Number of days of data requested

        Returns:
            DataFrame if cache is valid, None otherwise
        """
        try:
            # Check if we have recent data
            cutoff_date = datetime.now() - timedelta(hours=1)  # Data freshness threshold

            if product_id in self.last_update and self.last_update[product_id] > cutoff_date:
                # Use in-memory cache
                if product_id in self.market_data_cache:
                    df = self.market_data_cache[product_id]
                    # Filter to requested time range
                    start_date = datetime.now() - timedelta(days=days)
                    df_filtered = df[df.index >= start_date]
                    return df_filtered

            # Check database
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            data_records = db_manager.get_market_data(product_id, start_date, end_date)

            if data_records:
                # Convert to DataFrame
                df_data = []
                for record in data_records:
                    df_data.append({
                        'timestamp': pd.to_datetime(record['timestamp']),
                        'open': record['open'],
                        'high': record['high'],
                        'low': record['low'],
                        'close': record['close'],
                        'volume': record['volume']
                    })

                df = pd.DataFrame(df_data)
                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)

                return df

        except Exception as e:
            logger.error(f"Error retrieving cached data for {product_id}: {e}")

        return None

    def update_market_data(self) -> bool:
        """
        Update market data for all configured products.

        This method should be called periodically to keep data fresh.
        """
        success = True

        for product_id in settings.PRODUCT_IDS:
            try:
                # Get latest candle data (last few hours)
                df = self.collect_historical_data(product_id, days=1)

                if not df.empty:
                    # Update cache
                    self.market_data_cache[product_id] = df
                    self.last_update[product_id] = datetime.now()
                    logger.debug(f"Updated market data for {product_id}")

                else:
                    logger.warning(f"No data received for {product_id}")
                    success = False

            except Exception as e:
                logger.error(f"Failed to update data for {product_id}: {e}")
                success = False

        return success

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators for price data.

        Since we removed TA-Lib, we'll implement basic indicators manually.
        In a production system, you'd use a proper technical analysis library.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            DataFrame with additional technical indicator columns
        """
        if df.empty:
            return df

        df = df.copy()

        try:
            # Simple Moving Averages
            df['sma_20'] = df['close'].rolling(window=20).mean()
            df['sma_50'] = df['close'].rolling(window=50).mean()

            # Exponential Moving Averages
            df['ema_12'] = df['close'].ewm(span=12).mean()
            df['ema_26'] = df['close'].ewm(span=26).mean()

            # MACD
            df['macd'] = df['ema_12'] - df['ema_26']
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_histogram'] = df['macd'] - df['macd_signal']

            # RSI (Relative Strength Index)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            # Bollinger Bands
            df['bb_middle'] = df['close'].rolling(window=20).mean()
            df['bb_std'] = df['close'].rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
            df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)

            # Volume indicators
            df['volume_sma'] = df['volume'].rolling(window=20).mean()

            # Price momentum
            df['returns'] = df['close'].pct_change()
            df['volatility'] = df['returns'].rolling(window=20).std() * np.sqrt(252)  # Annualized

            logger.debug(f"Calculated technical indicators for {len(df)} data points")

        except Exception as e:
            logger.error(f"Error calculating technical indicators: {e}")

        return df

    def get_latest_features(self, product_id: str) -> Dict[str, float]:
        """
        Get the latest feature values for AI model input.

        Args:
            product_id: Trading pair identifier

        Returns:
            Dictionary of feature values for model prediction
        """
        try:
            logger.info(f"Getting latest features for {product_id}")
            # Get recent data
            df = self.collect_historical_data(product_id, days=7)
            logger.info(f"Historical data for {product_id}: {len(df)} rows")

            if df.empty:
                logger.warning(f"No data available for {product_id}")
                return {}

            # Calculate indicators
            df_with_indicators = self.calculate_technical_indicators(df)

            # Get latest values
            latest = df_with_indicators.iloc[-1]

            features = {
                'close_price': latest['close'],
                'volume': latest['volume'],
                'sma_20': latest.get('sma_20', 0),
                'sma_50': latest.get('sma_50', 0),
                'ema_12': latest.get('ema_12', 0),
                'ema_26': latest.get('ema_26', 0),
                'macd': latest.get('macd', 0),
                'macd_signal': latest.get('macd_signal', 0),
                'macd_histogram': latest.get('macd_histogram', 0),
                'rsi': latest.get('rsi', 0),
                'bb_upper': latest.get('bb_upper', 0),
                'bb_lower': latest.get('bb_lower', 0),
                'bb_middle': latest.get('bb_middle', 0),
                'returns': latest.get('returns', 0),
                'volatility': latest.get('volatility', 0),
                'volume_sma': latest.get('volume_sma', 0)
            }

            # Fill any NaN values with 0
            features = {k: (v if not pd.isna(v) else 0.0) for k, v in features.items()}

            return features

        except Exception as e:
            logger.error(f"Failed to get features for {product_id}: {e}")
            return {}

    def get_market_sentiment_data(self) -> Dict[str, Any]:
        """
        Collect market sentiment data from various sources.

        This is a placeholder for sentiment analysis. In a real implementation,
        you'd integrate with news APIs, social media sentiment, etc.
        """
        # Placeholder implementation
        # In production, this would fetch from news APIs, social media, etc.

        sentiment_data = {
            'btc_sentiment': 0.5,  # Neutral sentiment
            'eth_sentiment': 0.5,
            'market_fear_greed': 50,  # Neutral fear/greed index
            'timestamp': datetime.now().isoformat()
        }

        return sentiment_data

    def get_data_summary(self) -> Dict[str, Any]:
        """
        Get a summary of available market data.

        Returns:
            Dictionary with data statistics
        """
        summary = {
            'products': settings.PRODUCT_IDS,
            'cached_products': list(self.market_data_cache.keys()),
            'last_updates': {k: v.isoformat() for k, v in self.last_update.items()},
            'cache_size': len(self.market_data_cache)
        }

        return summary


# Global data collector instance
data_collector = DataCollector()