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
from src.multi_source_pricer import get_multi_source_pricer, PriceAggregationError

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
        
        # Initialize multi-source pricer
        self._multi_source_enabled = getattr(settings, 'MULTI_SOURCE_ENABLED', True)
        self._multi_source_pricer = None
        if self._multi_source_enabled:
            try:
                self._multi_source_pricer = get_multi_source_pricer()
                logger.info("Multi-source pricing enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize multi-source pricer: {e}")

    def get_current_prices(self) -> Dict[str, float]:
        """
        Get current market prices for all configured trading pairs AND USD equivalents.
        
        Uses multi-source pricing when enabled (Coinbase + CoinGecko + Kraken consensus).

        Returns:
            Dictionary mapping product_id to current price (includes both trading pairs and USD pairs)
        """
        prices = {}

        # Try multi-source pricing first
        if self._multi_source_enabled and self._multi_source_pricer:
            try:
                prices = self._get_prices_multi_source()
            except Exception as e:
                logger.warning(f"Multi-source pricing failed, falling back to Coinbase: {e}")
                prices = self._get_prices_coinbase()
        else:
            prices = self._get_prices_coinbase()

        # Get USD prices for risk management (can use multi-source too)
        usd_prices = self._get_usd_prices()
        prices.update(usd_prices)
        
        return prices
    
    def _get_prices_multi_source(self) -> Dict[str, float]:
        """
        Get prices using multi-source consensus (Coinbase + CoinGecko + Kraken).
        
        Returns:
            Dict of product_id to consensus price
        """
        prices = {}
        
        try:
            # Use batch prices for efficiency
            results = self._multi_source_pricer.get_batch_prices(settings.PRODUCT_IDS)
            
            for product_id, consensus in results.items():
                if consensus.price > 0:
                    prices[product_id] = consensus.price
                    
                    # Log detailed info
                    source_str = '+'.join(consensus.sources_used)
                    logger.info(
                        f"Multi-source {product_id}: £{consensus.price:.2f} "
                        f"[{source_str}] conf:{consensus.confidence:.0%}"
                    )
                else:
                    logger.warning(f"Invalid consensus price for {product_id}")
                    
        except Exception as e:
            logger.warning(f"Multi-source batch failed: {e}")
            raise
        
        return prices
    
    def _get_prices_coinbase(self) -> Dict[str, float]:
        """
        Get prices from Coinbase only (fallback mode).
        
        Returns:
            Dict of product_id to price
        """
        prices = {}
        
        for product_id in settings.PRODUCT_IDS:
            try:
                ticker = coinbase_api.get_product_ticker(product_id)
                price = ticker.get('price')
                
                if price and price > 0:
                    prices[product_id] = price
                    logger.info(f"Coinbase price for {product_id}: £{price:.2f}")
                else:
                    logger.warning(f"Invalid price data for {product_id}: {ticker}")
                    if product_id in self.market_data_cache:
                        prices[product_id] = self.market_data_cache[product_id]
                        logger.warning(f"Using cached price for {product_id}")
            
            except Exception as e:
                logger.error(f"Failed to get price for {product_id}: {e}")
                if product_id in self.market_data_cache:
                    prices[product_id] = self.market_data_cache[product_id]
                    logger.warning(f"Using cached price for {product_id}")
        
        return prices
    
    def _get_usd_prices(self) -> Dict[str, float]:
        """
        Get USD prices for base currencies for risk management.
        Uses multi-source consensus for accurate pricing.
        
        Returns:
            Dict of USD product_id to price
        """
        prices = {}
        
        # Build USD pair list from active trading pairs
        usd_pairs = []
        for product_id in settings.PRODUCT_IDS:
            base = product_id.split('-')[0]
            usd_pairs.append(f"{base}-USD")
        
        # Remove duplicates
        usd_pairs = list(set(usd_pairs))
        
        # Use multi-source pricer if available
        if self._multi_source_enabled and self._multi_source_pricer:
            try:
                results = self._multi_source_pricer.get_batch_prices(usd_pairs)
                for product_id, consensus in results.items():
                    if consensus.price > 0:
                        prices[product_id] = consensus.price
                        source_str = '+'.join(consensus.sources_used)
                        logger.debug(f"Multi-source USD {product_id}: ${consensus.price:.2f} [{source_str}]")
            except Exception as e:
                logger.warning(f"Multi-source USD fetch failed, falling back to Coinbase: {e}")
                prices = self._get_usd_prices_coinbase(usd_pairs)
        else:
            prices = self._get_usd_prices_coinbase(usd_pairs)
        
        return prices
    
    def _get_usd_prices_coinbase(self, usd_pairs: List[str]) -> Dict[str, float]:
        """
        Fallback: Get USD prices from Coinbase only.
        
        Args:
            usd_pairs: List of USD product IDs (e.g., ['BTC-USD', 'ETH-USD'])
            
        Returns:
            Dict of USD product_id to price
        """
        prices = {}
        
        for usd_product_id in usd_pairs:
            if usd_product_id in prices:
                continue
            
            try:
                ticker = coinbase_api.get_product_ticker(usd_product_id)
                price = ticker.get('price')
                
                if price and float(price) > 0:
                    prices[usd_product_id] = float(price)
                    logger.debug(f"Coinbase USD {usd_product_id}: ${float(price):.2f}")
            
            except Exception as e:
                logger.debug(f"Could not fetch USD price for {usd_product_id}: {e}")
        
        return prices
        
        return prices

    def collect_historical_data(self, product_id: str, days: Optional[int] = None) -> pd.DataFrame:
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
            # Check if we have RECENT data in database (within 10 minutes)
            cached_data = self._get_cached_data(product_id, days, max_age_minutes=10)
            
            # If no recent cache, fetch fresh from API
            if cached_data is None or cached_data.empty:
                logger.info(f"No recent cache for {product_id}, fetching fresh data from API...")
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)

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
                    logger.info(f"Fetched fresh data for {product_id}: {len(df)} records")

                return df
            
            logger.info(f"Using cached data for {product_id} ({len(cached_data)} records)")
            return cached_data

        except Exception as e:
            logger.error(f"Failed to collect historical data for {product_id}: {e}")
            return pd.DataFrame()

    def collect_multi_source_data(self, product_id: str, days: int = 180) -> pd.DataFrame:
        """
        Collect historical data from multiple sources (Coinbase + CoinGecko + Kraken) and merge.
        
        This provides more robust training data by combining sources, reducing single-source bias.
        Priority:
        - Coinbase: Primary (used for live trading)
        - CoinGecko: Supplementary
        - Kraken: Additional historical data

        Args:
            product_id: Trading pair (e.g., 'BTC-GBP')
            days: Number of days of data to collect

        Returns:
            DataFrame with OHLCV data (merged from multiple sources)
        """
        from src.coingecko_api import get_coingecko_api
        from src.kraken_api import get_kraken_api
        from src.price_mapper import price_mapper
        
        try:
            all_dataframes = []
            
            # 1. Get Coinbase data (primary source)
            coinbase_df = self.collect_historical_data(product_id, days)
            if not coinbase_df.empty:
                all_dataframes.append(('coinbase', coinbase_df))
                logger.info(f"Coinbase: {len(coinbase_df)} rows for {product_id}")
            
            # 2. Get CoinGecko data (supplementary)
            # Map product_id like 'UNI-GBP' to CoinGecko coin ID
            cg_coin_id = price_mapper.get_coingecko_id(product_id)
            if cg_coin_id:
                cg_days = min(days, 365)
                vs_currency = 'usd' if '-USD' in product_id else 'gbp'
                cg_api = get_coingecko_api()
                cg_data = cg_api.get_ohlc(cg_coin_id, vs_currency=vs_currency, days=cg_days)
                
                if cg_data:
                    cg_df = pd.DataFrame(cg_data, columns=['timestamp', 'open', 'high', 'low', 'close'])
                    cg_df['timestamp'] = pd.to_datetime(cg_df['timestamp'], unit='ms')
                    cg_df.set_index('timestamp', inplace=True)
                    cg_df = cg_df.sort_index()
                    cg_df = cg_df.resample('1h').last().dropna()
                    if not cg_df.empty:
                        all_dataframes.append(('coingecko', cg_df))
                        logger.info(f"CoinGecko: {len(cg_df)} rows for {product_id}")
            
            # 3. Get Kraken data (additional)
            kraken_pair = price_mapper.get_kraken_pair(product_id)
            if kraken_pair:
                kraken_api = get_kraken_api()
                kraken_df = kraken_api.get_ohlc(kraken_pair, interval=60)
                
                if kraken_df is not None and not kraken_df.empty:
                    start_date = datetime.now() - timedelta(days=days)
                    kraken_df = kraken_df[kraken_df['timestamp'] >= start_date]
                    if not kraken_df.empty:
                        kraken_df = kraken_df.set_index('timestamp').sort_index()
                        all_dataframes.append(('kraken', kraken_df))
                        logger.info(f"Kraken: {len(kraken_df)} rows for {product_id}")
            
            # 4. Get Binance klines (additional source)
            binance_symbol = price_mapper.get_binance_symbol(product_id)
            if binance_symbol:
                from src.binance_api import get_binance_api
                binance_api = get_binance_api()
                # Request up to 1000 candles for more training data
                binance_klines = binance_api.get_klines(binance_symbol, '1h', limit=1000)
                
                if binance_klines and len(binance_klines) > 0:
                    binance_df = pd.DataFrame(
                        binance_klines,
                        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
                               'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'unused']
                    )
                    binance_df['timestamp'] = pd.to_datetime(binance_df['timestamp'], unit='ms')
                    binance_df.set_index('timestamp', inplace=True)
                    binance_df = binance_df[['open', 'high', 'low', 'close', 'volume']].astype(float)
                    binance_df = binance_df.sort_index()
                    
                    # Filter to requested date range
                    start_date = datetime.now() - timedelta(days=days)
                    binance_df = binance_df[binance_df.index >= start_date]
                    
                    if not binance_df.empty:
                        all_dataframes.append(('binance', binance_df))
                        logger.info(f"Binance: {len(binance_df)} rows for {product_id}")
            
            # Merge all dataframes
            if not all_dataframes:
                return pd.DataFrame()
            
            if len(all_dataframes) == 1:
                return all_dataframes[0][1]
            
            # For pairs with limited Coinbase data (like UNI), prioritize other sources
            if product_id == 'UNI-GBP' or (len(coinbase_df) < 100 and len(all_dataframes) > 1):
                priority_order = ['kraken', 'coingecko', 'coinbase']
                all_dataframes.sort(key=lambda x: priority_order.index(x[0]) if x[0] in priority_order else 99)
            
            # Combine dataframes, prioritizing earlier sources
            combined = pd.DataFrame()
            for source, df in all_dataframes:
                if combined.empty:
                    combined = df.copy()
                else:
                    combined_dates = set(combined.index)
                    new_data = df[~df.index.isin(combined_dates)]
                    if not new_data.empty:
                        combined = pd.concat([combined, new_data])
                        combined = combined.sort_index()
                        combined = combined[~combined.index.duplicated(keep='first')]
            
            logger.info(f"Combined {len(all_dataframes)} sources: {len(combined)} total rows for {product_id}")
            return combined
            
        except Exception as e:
            logger.warning(f"Multi-source collection failed for {product_id}, using Coinbase only: {e}")
            return self.collect_historical_data(product_id, days)

    def _get_cached_data(self, product_id: str, days: int, max_age_minutes: int = 10) -> Optional[pd.DataFrame]:
        """
        Retrieve cached market data from database if recent enough.

        Args:
            product_id: Trading pair identifier
            days: Number of days of data requested
            max_age_minutes: Maximum age of cache in minutes (default 10)

        Returns:
            DataFrame if cache is valid and recent, None otherwise
        """
        try:
            # First check in-memory cache
            if product_id in self.last_update:
                cache_age = (datetime.now() - self.last_update[product_id]).total_seconds() / 60
                if cache_age < max_age_minutes:
                    if product_id in self.market_data_cache:
                        df = self.market_data_cache[product_id]
                        start_date = datetime.now() - timedelta(days=days)
                        df_filtered = df[df.index >= start_date]
                        return df_filtered
                else:
                    logger.info(f"In-memory cache too old ({cache_age:.0f} min), will refresh")

            # Check database for freshness - limit to only 7 days max to avoid slow queries
            end_date = datetime.now()
            max_days = min(days, 7)
            start_date = end_date - timedelta(days=max_days)

            data_records = db_manager.get_market_data(product_id, start_date, end_date)

            if data_records:
                # Check how recent the data is
                latest_record_time = max(pd.to_datetime(r['timestamp']) for r in data_records if r.get('timestamp'))
                data_age_minutes = (datetime.now() - latest_record_time.to_pydatetime()).total_seconds() / 60
                
                logger.info(f"DB cache age for {product_id}: {data_age_minutes:.0f} minutes")
                
                if data_age_minutes > max_age_minutes:
                    logger.info(f"DB cache too old ({data_age_minutes:.0f} min > {max_age_minutes} min), will fetch fresh")
                    return None

            if data_records:
                # Remove duplicates by keeping only the last record per timestamp
                df_data = []
                seen_timestamps = set()
                for record in reversed(data_records):  # Reverse to keep latest
                    ts = record['timestamp']
                    if ts not in seen_timestamps:
                        seen_timestamps.add(ts)
                        df_data.append({
                            'timestamp': pd.to_datetime(ts),
                            'open': record['open'],
                            'high': record['high'],
                            'low': record['low'],
                            'close': record['close'],
                            'volume': record['volume']
                        })
                
                if not df_data:
                    return None
                    
                df = pd.DataFrame(df_data)
                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)
                
                # Cache it - but only keep last 7 days to avoid memory bloat
                cache_days = 7
                cache_start = datetime.now() - timedelta(days=cache_days)
                df_cached = df[df.index >= cache_start]
                self.market_data_cache[product_id] = df_cached
                self.last_update[product_id] = datetime.now()
                
                # Filter to requested time range
                requested_start = datetime.now() - timedelta(days=days)
                df_filtered = df[df.index >= requested_start]
                return df_filtered

        except Exception as e:
            logger.error(f"Error retrieving cached data for {product_id}: {e}")
            return None

    def update_market_data(self) -> bool:
        """
        Update market data for all configured products IN PARALLEL.
        """
        import threading
        success = True
        results = {}
        errors = {}
        
        def fetch_data_for_product(product_id, results_dict, errors_dict):
            try:
                df = self.collect_historical_data(product_id, days=1)
                if not df.empty:
                    results_dict[product_id] = df
                    logger.debug(f"Updated market data for {product_id}")
                else:
                    logger.warning(f"No data received for {product_id}")
                    errors_dict[product_id] = "No data"
            except Exception as e:
                logger.error(f"Failed to update data for {product_id}: {e}")
                errors_dict[product_id] = str(e)
        
        # Start all threads in parallel
        threads = []
        thread_product_ids = []
        
        for product_id in settings.PRODUCT_IDS:
            t = threading.Thread(target=fetch_data_for_product, args=(product_id, results, errors))
            t.daemon = True
            t.start()
            threads.append(t)
            thread_product_ids.append(product_id)
        
        # Wait for all to complete (max 2 minutes total)
        for t in threads:
            t.join(timeout=120)
        
        # Apply results to cache
        for product_id, df in results.items():
            self.market_data_cache[product_id] = df
            self.last_update[product_id] = datetime.now()
        
        if errors:
            logger.warning(f"update_market_data: {len(errors)} products failed: {errors}")
            success = False
        
        logger.info(f"update_market_data: {len(results)}/{len(settings.PRODUCT_IDS)} products updated")
        return success

    def get_24h_high(self, product_id: str) -> float:
        """
        Get the 24-hour high price for a trading pair.
        
        Args:
            product_id: Trading pair identifier (e.g., 'BTC-GBP')
            
        Returns:
            24-hour high price, or 0 if unavailable
        """
        try:
            df = self.collect_historical_data(product_id, days=2)
            if df.empty:
                return 0.0
            
            if 'high' in df.columns:
                high_24h = df['high'].tail(24).max()
                if pd.notna(high_24h):
                    return float(high_24h)
            return 0.0
        except Exception as e:
            logger.error(f"Error getting 24h high for {product_id}: {e}")
            return 0.0

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

            # ============================================================
            # NEW: Regime-invariant features (Phase 1)
            # These features work across different price levels/currencies
            # ============================================================

            # Price-relative features (replace absolute MAs)
            df['sma_20_ratio'] = df['close'] / df['sma_20']
            df['sma_50_ratio'] = df['close'] / df['sma_50']
            df['ema_12_ratio'] = df['close'] / df['ema_12']
            df['ema_26_ratio'] = df['close'] / df['ema_26']

            # Price deviation from moving averages
            df['price_deviation_sma20'] = (df['close'] - df['sma_20']) / df['sma_20']
            df['price_deviation_sma50'] = (df['close'] - df['sma_50']) / df['sma_50']

            # Bollinger Band position (0-1 scale, regime-invariant)
            df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

            # MACD normalized by price
            df['macd_normalized'] = df['macd'] / df['close']

            # RSI regime indicator (-1 oversold, 0 neutral, 1 overbought)
            df['rsi_regime'] = np.where(df['rsi'] > 70, 1,
                               np.where(df['rsi'] < 30, -1, 0))

            # Volume ratio
            df['volume_ratio'] = df['volume'] / df['volume_sma']

            # Volatility percentile (relative to recent period)
            df['volatility_percentile'] = df['volatility'].rank(pct=True)

            # ============================================================
            # v1.9.0: ATR (Average True Range) for dynamic threshold
            # ============================================================
            from src.feature_engineering import calculate_atr
            from config.settings import Settings
            settings = Settings()
            df['atr'] = calculate_atr(df, period=settings.ATR_PERIOD)
            
            # ============================================================
            # v1.9.1: Additional features
            # ============================================================
            
            # Log returns (preferred over simple pct_change)
            df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
            
            # ATR-normalized features (scale by ATR for volatility adaptation)
            atr = df['atr'].replace(0, np.nan)
            df['returns_per_atr'] = df['returns'] / (atr / df['close'])
            df['volatility_per_atr'] = df['volatility'] / (atr / df['close'])
            
            logger.debug(f"Calculated technical indicators for {len(df)} data points")

        except Exception as e:
            logger.error(f"Error calculating technical indicators: {e}")

        return df

    def _calculate_regime_feature(self, df: pd.DataFrame, target_regime: str) -> float:
        """
        Calculate regime one-hot encoded feature for the latest row.
        
        Args:
            df: DataFrame with technical indicators
            target_regime: 'uptrend', 'downtrend', or 'neutral'
            
        Returns:
            1.0 if current regime matches target, 0.0 otherwise
        """
        try:
            if df.empty or len(df) < 50:
                return 1.0 if target_regime == 'neutral' else 0.0
            
            # Use settings for regime detection - consistent with ai_model
            short_period = settings.REGIME_SHORT_MA_PERIOD  # 12 hours
            long_period = settings.REGIME_LONG_MA_PERIOD   # 48 hours
            threshold = settings.REGIME_THRESHOLD     # 3%
            
            # Get latest values
            close = df['close']
            short_ma = close.rolling(short_period).mean().iloc[-1]
            long_ma = close.rolling(long_period).mean().iloc[-1]
            
            # Calculate RSI (consistent settings)
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=14, min_periods=14).mean().iloc[-1]
            avg_loss = loss.rolling(window=14, min_periods=14).mean().iloc[-1]
            
            if pd.isna(short_ma) or pd.isna(long_ma) or pd.isna(avg_gain) or pd.isna(avg_loss):
                return 1.0 if target_regime == 'neutral' else 0.0
            
            rs = avg_gain / (avg_loss if avg_loss > 0 else 0.0001)
            rsi = 100 - (100 / (1 + rs))
            
            # Determine regime - use consistent settings thresholds
            ma_uptrend = short_ma > long_ma * (1 + threshold)
            ma_downtrend = short_ma < long_ma * (1 - threshold)
            rsi_strong_up = rsi > settings.REGIME_STRONG_RSI_UPPER  # 65
            rsi_strong_down = rsi < settings.REGIME_STRONG_RSI_LOWER  # 35
            
            if ma_uptrend or rsi_strong_up:
                current_regime = 'uptrend'
            elif ma_downtrend or rsi_strong_down:
                current_regime = 'downtrend'
            else:
                current_regime = 'neutral'
            
            return 1.0 if current_regime == target_regime else 0.0
            
        except Exception as e:
            logger.warning(f"Error calculating regime feature: {e}")
            return 1.0 if target_regime == 'neutral' else 0.0

    def get_latest_features(self, product_id: str, force_refresh: bool = False) -> Dict[str, float]:
        """
        Get the latest feature values for AI model input.

        Args:
            product_id: Trading pair identifier
            force_refresh: If True, skip cache and fetch fresh data

        Returns:
            Dictionary of feature values for model prediction
        """
        try:
            logger.info(f"Getting latest features for {product_id}, force_refresh={force_refresh}")
            # Get recent data (reduced from 7 to 2 days for more responsive features)
            df = self.collect_historical_data(product_id, days=2)
            logger.info(f"Historical data for {product_id}: {len(df)} rows, latest: {df.index[-1] if not df.empty else 'N/A'}")

            if df.empty:
                logger.warning(f"No data available for {product_id}")
                return {}

            # Calculate indicators (including new regime-invariant features)
            df_with_indicators = self.calculate_technical_indicators(df)

            # Get latest values
            latest = df_with_indicators.iloc[-1]

            features = {
                # Original features (kept for backward compatibility)
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
                'volume_sma': latest.get('volume_sma', 0),
                
                # NEW: Regime-invariant features (Phase 1)
                'sma_20_ratio': latest.get('sma_20_ratio', 1.0),
                'sma_50_ratio': latest.get('sma_50_ratio', 1.0),
                'ema_12_ratio': latest.get('ema_12_ratio', 1.0),
                'ema_26_ratio': latest.get('ema_26_ratio', 1.0),
                'price_deviation_sma20': latest.get('price_deviation_sma20', 0.0),
                'price_deviation_sma50': latest.get('price_deviation_sma50', 0.0),
                'bb_position': latest.get('bb_position', 0.5),
                'macd_normalized': latest.get('macd_normalized', 0.0),
                'rsi_regime': latest.get('rsi_regime', 0.0),
                'volume_ratio': latest.get('volume_ratio', 1.0),
                'volatility_percentile': latest.get('volatility_percentile', 0.5),
                
                # v1.9.1: Log returns (must match training)
                'log_returns': latest.get('log_returns', 0.0),
                
                # v1.9.1: ATR normalization features (must match training)
                'atr': latest.get('atr', 0.0),
                'returns_per_atr': latest.get('returns_per_atr', 0.0),
                'volatility_per_atr': latest.get('volatility_per_atr', 0.0),
                
                # Regime one-hot encoded features (calculated from current data)
                'regime_is_uptrend': self._calculate_regime_feature(df_with_indicators, 'uptrend'),
                'regime_is_downtrend': self._calculate_regime_feature(df_with_indicators, 'downtrend'),
                'regime_is_neutral': self._calculate_regime_feature(df_with_indicators, 'neutral'),
            }
            
            # Add pair one-hot encoding features (must match training!)
            from src.feature_engineering import PAIR_IDENTIFIERS
            base_currency = product_id.split('-')[0]  # e.g., 'BTC' from 'BTC-GBP'
            for currency in PAIR_IDENTIFIERS:
                features[f'is_{currency}'] = 1.0 if currency == base_currency else 0.0
            
            # Add currency indicator (GBP vs USD)
            quote_currency = product_id.split('-')[1]  # e.g., 'GBP' from 'BTC-GBP'
            features['is_gbp'] = 1.0 if quote_currency == 'GBP' else 0.0
            features['is_usd'] = 1.0 if quote_currency == 'USD' else 0.0
            
            # Fill any NaN values with sensible defaults
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