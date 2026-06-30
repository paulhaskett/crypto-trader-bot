"""
Multi-Source Price Aggregator with Consensus Averaging.

This module aggregates prices from multiple sources (Coinbase, Binance, Kraken, CoinGecko)
and calculates a consensus price using weighted averaging and outlier detection.

v1.3.0 - Added Binance as a data source.

Features:
- Weighted consensus based on source reliability
- Outlier detection (>3% deviation from median)
- Source health tracking
- Chainlink verification for anomalies
- Rate limit management across sources
"""

import logging
import statistics
import time
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import pandas as pd

from config.settings import settings
from src.coinbase_api import coinbase_api
from src.coingecko_api import get_coingecko_api
from src.kraken_api import get_kraken_api
from src.cryptocompare_api import get_cryptocompare_api
from src.binance_api import get_binance_api
from src.price_mapper import get_price_mapper
from src.chainlink_oracle import get_chainlink_oracle
from src.websocket_client import get_websocket_client

logger = logging.getLogger(__name__)


class PriceAggregationError(Exception):
    """Exception for price aggregation failures."""
    pass


@dataclass
class PriceSource:
    """Represents a single price source."""
    name: str
    price: float
    volume_24h: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    latency_ms: float = 0.0
    is_fallback: bool = False


@dataclass 
class ConsensusResult:
    """Result of price consensus calculation."""
    product_id: str
    price: float
    confidence: float
    sources_used: List[str]
    source_prices: Dict[str, PriceSource]
    outlier_sources: List[str] = field(default_factory=list)
    max_deviation_pct: float = 0.0
    spread_pct: float = 0.0  # Max spread between sources (for arbitrage detection)
    source_spreads: Dict[str, float] = field(default_factory=dict)  # Per-source spreads
    verification_result: Optional[Dict] = None
    timestamp: datetime = field(default_factory=datetime.now)


class MultiSourcePricer:
    """
    Aggregates prices from multiple sources with consensus averaging.
    
    v1.3.0 - Added Binance as data source.
    
    Features:
    - Fetches prices from Coinbase, Binance, Kraken, and CoinGecko
    - Weighted consensus based on source priority
    - Outlier detection and exclusion
    - Chainlink verification (optional)
    - Rate limiting per source
    """
    
    # Default source weights (can be overridden in settings)
    DEFAULT_WEIGHTS = {
        'coinbase': 0.40,   # Primary - has trading capability
        'binance': 0.30,    # Major exchange - good liquidity
        'kraken': 0.20,     # Additional exchange
        'coingecko': 0.10,  # Backup aggregator
    }
    
    # Max deviation threshold for outlier detection (per slippage-modeling.md)
    DEFAULT_MAX_DEVIATION = 0.02  # 2%
    
    # Min sources required for consensus
    MIN_SOURCES = 2
    
    # Confidence threshold for trading
    CONFIDENCE_THRESHOLD = 0.60  # 60%
    
    def __init__(self):
        """Initialize multi-source pricer with all sources."""
        # Initialize source clients
        self.coinbase = coinbase_api
        self.coingecko = get_coingecko_api()
        self.kraken = get_kraken_api()
        self.cryptocompare = get_cryptocompare_api()
        self.binance = get_binance_api()  # v1.3.0 - Added Binance
        self.price_mapper = get_price_mapper()
        self.chainlink = get_chainlink_oracle()
        
        # WebSocket client for real-time prices (BTC/ETH)
        self.websocket = get_websocket_client()
        self._websocket_started = False
        
        # Configuration
        self.source_weights = getattr(
            settings, 'PRICE_SOURCE_WEIGHTS', self.DEFAULT_WEIGHTS
        )
        self.max_deviation = getattr(
            settings, 'MAX_PRICE_DEVIATION', self.DEFAULT_MAX_DEVIATION
        )
        self.min_sources = getattr(
            settings, 'CONSENSUS_MIN_SOURCES', self.MIN_SOURCES
        )
        self.confidence_threshold = getattr(
            settings, 'CONSENSUS_MIN_CONFIDENCE', self.CONFIDENCE_THRESHOLD
        )
        
        # Priority pairs - fetched first (both GBP and USD for complete price coverage)
        self.priority_pairs = ['BTC-GBP', 'ETH-GBP', 'BTC-USD', 'ETH-USD']
        
        # Cache for consensus prices
        self._price_cache: Dict[str, Tuple[ConsensusResult, datetime]] = {}
        self._cache_ttl = 30  # 30 seconds
        
        # Rate limiting
        self._last_batch_time = 0
        self._batch_interval = 2.0  # Min time between batch requests
        
        # Source health tracking
        self._source_health: Dict[str, Dict] = {
            'coinbase': {'success': 0, 'fail': 0, 'last_success': None},
            'binance': {'success': 0, 'fail': 0, 'last_success': None},  # v1.3.0
            'coingecko': {'success': 0, 'fail': 0, 'last_success': None},
            'kraken': {'success': 0, 'fail': 0, 'last_success': None},
        }
        
        logger.info(
            f"MultiSourcePricer initialized with weights: {self.source_weights}"
        )
    
    def get_consensus_price(self, product_id: str, use_cache: bool = True) -> ConsensusResult:
        """
        Get consensus price from all available sources.
        
        Args:
            product_id: Coinbase product ID (e.g., 'BTC-GBP')
            use_cache: Whether to use cached prices
            
        Returns:
            ConsensusResult with aggregated price data
            
        Raises:
            PriceAggregationError: If no valid prices available
        """
        # Check cache
        if use_cache and product_id in self._price_cache:
            cached_result, cached_time = self._price_cache[product_id]
            age = (datetime.now() - cached_time).total_seconds()
            if age < self._cache_ttl:
                return cached_result
        
        # Fetch prices from all sources
        source_prices = self._fetch_all_prices(product_id)
        
        if not source_prices:
            raise PriceAggregationError(
                f"No price data available for {product_id} from any source"
            )
        
        # Calculate consensus
        consensus = self._calculate_consensus(product_id, source_prices)
        
        # Optionally verify with Chainlink
        if settings.MULTI_SOURCE_ENABLED and consensus.confidence > 0.5:
            try:
                verification = self.chainlink.verify_price(
                    product_id, consensus.price, 'consensus', 
                    tolerance=0.05  # 5% for consensus
                )
                consensus.verification_result = verification
            except Exception as e:
                logger.debug(f"Chainlink verification failed: {e}")
        
        # Cache result
        self._price_cache[product_id] = (consensus, datetime.now())
        
        # Log result
        self._log_consensus(consensus)
        
        return consensus
    
    def get_batch_prices(self, product_ids: List[str]) -> Dict[str, ConsensusResult]:
        """
        Get consensus prices for multiple products efficiently.
        
        Args:
            product_ids: List of Coinbase product IDs
            
        Returns:
            Dict mapping product_id to ConsensusResult
        """
        results = {}
        
        # Separate priority and regular pairs
        priority = [p for p in self.priority_pairs if p in product_ids]
        regular = [p for p in product_ids if p not in priority]
        
        # Fetch priority first (rate limit management)
        for product_id in priority:
            try:
                results[product_id] = self.get_consensus_price(product_id)
            except PriceAggregationError as e:
                logger.warning(f"Failed to get consensus for {product_id}: {e}")
        
        # Small delay to respect rate limits
        time.sleep(0.5)
        
        # Fetch regular pairs
        for product_id in regular:
            try:
                results[product_id] = self.get_consensus_price(product_id)
            except PriceAggregationError as e:
                logger.warning(f"Failed to get consensus for {product_id}: {e}")
        
        return results
    
    def _fetch_all_prices(self, product_id: str) -> Dict[str, PriceSource]:
        """
        Fetch prices from all available sources.
        
        Args:
            product_id: Coinbase product ID
            
        Returns:
            Dict mapping source name to PriceSource
        """
        prices = {}
        
        # 0. Try WebSocket first for any WS-subscribed pair (live GBP + USD training)
        ws_pairs = getattr(self.websocket, 'ws_subscriptions', []) if self.websocket else []
        if product_id in ws_pairs:
            try:
                ws_price = self._get_websocket_price(product_id)
                if ws_price:
                    prices['websocket'] = ws_price
                    logger.debug(f"WebSocket price for {product_id}: £{ws_price.price}")
            except Exception as e:
                logger.debug(f"WebSocket fetch failed for {product_id}: {e}")
        
        # 1. Fetch from Coinbase (baseline) - always try this
        try:
            price_data = self._fetch_coinbase_price(product_id)
            if price_data:
                prices['coinbase'] = price_data
                self._update_health('coinbase', success=True)
        except Exception as e:
            logger.debug(f"Coinbase fetch failed for {product_id}: {e}")
            self._update_health('coinbase', success=False)
        
        # 2. Fetch from Binance (major exchange - good liquidity)
        try:
            price_data = self._fetch_binance_price(product_id)
            if price_data:
                prices['binance'] = price_data
                self._update_health('binance', success=True)
        except Exception as e:
            logger.debug(f"Binance fetch failed for {product_id}: {e}")
            self._update_health('binance', success=False)
        
        # 3. Fetch from Kraken (fast, no auth needed)
        try:
            price_data = self._fetch_kraken_price(product_id)
            if price_data:
                prices['kraken'] = price_data
                self._update_health('kraken', success=True)
        except Exception as e:
            logger.debug(f"Kraken fetch failed for {product_id}: {e}")
            self._update_health('kraken', success=False)
        
        # Skip CoinGecko and CryptoCompare if we already have 2 sources
        # (they have rate limits and are slower)
        if len(prices) >= 2:
            return prices
        
        # 3. Fetch from CoinGecko (skip if no API key - they require it now)
        if self.coingecko.api_key:
            try:
                price_data = self._fetch_coingecko_price(product_id)
                if price_data:
                    prices['coingecko'] = price_data
                    self._update_health('coingecko', success=True)
            except Exception as e:
                logger.debug(f"CoinGecko fetch failed for {product_id}: {e}")
                self._update_health('coingecko', success=False)
        
        # 4. Fetch from CryptoCompare (as backup)
        try:
            price_data = self._fetch_cryptocompare_price(product_id)
            if price_data:
                prices['cryptocompare'] = price_data
                self._update_health('cryptocompare', success=True)
        except Exception as e:
            logger.debug(f"CryptoCompare fetch failed for {product_id}: {e}")
            self._update_health('cryptocompare', success=False)
        
        return prices
    
    def _get_websocket_price(self, product_id: str) -> Optional[PriceSource]:
        """
        Get price from WebSocket for high-liquidity pairs (BTC, ETH).
        
        Per slippage-modeling.md: prioritize high-liquidity pairs with WebSocket.
        """
        # Active + training pairs that benefit from WebSocket (dynamically loaded)
        ws_pairs = getattr(self.websocket, 'ws_subscriptions', []) if self.websocket else []
        
        if product_id not in ws_pairs:
            return None
        
        # Start WebSocket if not started
        if not self._websocket_started:
            try:
                self.websocket.start()
                self._websocket_started = True
            except Exception as e:
                logger.debug(f"Failed to start WebSocket: {e}")
                return None
        
        # Try to get price from WebSocket
        price = self.websocket.get_price(product_id)
        
        if price:
            return PriceSource(
                name='websocket',
                price=float(price),
                timestamp=datetime.now(),
                latency_ms=0.0,  # Real-time, no latency
                is_fallback=False
            )
        
        return None
    
    def _fetch_coinbase_price(self, product_id: str) -> Optional[PriceSource]:
        """Fetch price from Coinbase."""
        start_time = time.time()
        
        ticker = self.coinbase.get_product_ticker(product_id)
        
        if not ticker or not ticker.get('price'):
            return None
        
        latency = (time.time() - start_time) * 1000
        
        return PriceSource(
            name='coinbase',
            price=float(ticker['price']),
            volume_24h=ticker.get('volume_24h'),
            timestamp=datetime.now(),
            latency_ms=latency,
            is_fallback=ticker.get('is_fallback', False)
        )
    
    def _fetch_binance_price(self, product_id: str) -> Optional[PriceSource]:
        """Fetch price from Binance."""
        start_time = time.time()
        
        # Use get_price_product which handles GBP conversion via USDT fallback
        price = self.binance.get_price_product(product_id)
        
        if not price:
            return None
        
        latency = (time.time() - start_time) * 1000
        
        return PriceSource(
            name='binance',
            price=float(price),
            timestamp=datetime.now(),
            latency_ms=latency
        )
    
    def _fetch_coingecko_price(self, product_id: str) -> Optional[PriceSource]:
        """Fetch price from CoinGecko."""
        # Get coin ID from mapper
        coin_id = self.price_mapper.get_coingecko_id(product_id)
        
        if not coin_id:
            return None
        
        start_time = time.time()
        
        # Get quote currency from product
        quote = self.price_mapper.get_quote_currency(product_id)
        vs_currency = quote.lower() if quote else 'gbp'
        
        # Fetch price
        price_data = self.coingecko.get_price(coin_id, vs_currency)
        
        if not price_data or not price_data.get('price'):
            return None
        
        latency = (time.time() - start_time) * 1000
        
        return PriceSource(
            name='coingecko',
            price=float(price_data['price']),
            volume_24h=price_data.get('volume_24h'),
            timestamp=datetime.now(),
            latency_ms=latency
        )
    
    def _fetch_kraken_price(self, product_id: str) -> Optional[PriceSource]:
        """Fetch price from Kraken."""
        # Get Kraken pair from mapper
        kraken_pair = self.price_mapper.get_kraken_pair(product_id)
        
        if not kraken_pair:
            return None
        
        start_time = time.time()
        
        # Fetch ticker - use get_ticker which takes Kraken pair name directly
        ticker = self.kraken.get_ticker(kraken_pair)
        
        if not ticker or not ticker.get('c') or not ticker['c'][0]:
            return None
        
        latency = (time.time() - start_time) * 1000
        
        return PriceSource(
            name='kraken',
            price=float(ticker['c'][0]),  # Last trade price is in 'c'[0]
            volume_24h=float(ticker['v'][1]) if ticker.get('v') else None,
            timestamp=datetime.now(),
            latency_ms=latency
        )
    
    def _fetch_cryptocompare_price(self, product_id: str) -> Optional[PriceSource]:
        """Fetch price from CryptoCompare."""
        # Get symbol from mapper
        symbol = self.price_mapper.get_coingecko_id(product_id)
        
        if not symbol:
            return None
        
        start_time = time.time()
        
        # Fetch price
        price = self.cryptocompare.get_price(symbol, 'GBP')
        
        if not price:
            return None
        
        latency = (time.time() - start_time) * 1000
        
        return PriceSource(
            name='cryptocompare',
            price=float(price),
            timestamp=datetime.now(),
            latency_ms=latency
        )
    
    def _calculate_consensus(
        self, 
        product_id: str, 
        source_prices: Dict[str, PriceSource]
    ) -> ConsensusResult:
        """
        Calculate consensus price from multiple sources.
        
        Args:
            product_id: Product ID
            source_prices: Dict of source prices
            
        Returns:
            ConsensusResult
        """
        if not source_prices:
            raise PriceAggregationError("No source prices to aggregate")
        
        # Get all price values
        price_values = {name: src.price for name, src in source_prices.items()}
        
        if not price_values:
            raise PriceAggregationError("No valid prices")
        
        # Calculate median for outlier detection
        median_price = statistics.median(price_values.values())
        
        # Detect and exclude outliers
        valid_prices = {}
        outlier_sources = []
        
        for source_name, price in price_values.items():
            deviation = abs(price - median_price) / median_price
            
            if deviation > self.max_deviation:
                outlier_sources.append(source_name)
                logger.warning(
                    f"Outlier detected: {source_name} for {product_id}: "
                    f"£{price:.2f} vs median £{median_price:.2f} "
                    f"(deviation: {deviation:.2%})"
                )
            else:
                valid_prices[source_name] = source_prices[source_name]
        
        # Check minimum sources
        if len(valid_prices) < self.min_sources:
            # Special handling: If Coinbase is the one that failed, try with remaining sources
            coinbase_failed = 'coinbase' not in valid_prices and 'coinbase' in source_prices
            
            if coinbase_failed and len(valid_prices) >= 1:
                # Coinbase failed but we have other sources - use them with lower confidence
                logger.warning(
                    f"Coinbase failed for {product_id}, using {len(valid_prices)} remaining sources: "
                    f"{list(valid_prices.keys())}"
                )
                # Continue with available sources (don't reset to include outliers)
            else:
                # Try with outliers if not enough valid sources
                logger.warning(
                    f"Not enough valid sources ({len(valid_prices)}), "
                    f"including outliers for {product_id}"
                )
                valid_prices = source_prices
                outlier_sources = []
        
        # Calculate weighted average
        total_weight = sum(
            self.source_weights.get(source, 0.1) 
            for source in valid_prices.keys()
        )
        
        weighted_sum = sum(
            valid_prices[source].price * self.source_weights.get(source, 0.1)
            for source in valid_prices.keys()
        )
        
        consensus_price = weighted_sum / total_weight if total_weight > 0 else median_price
        
        # Calculate confidence based on source agreement
        confidence = self._calculate_confidence(valid_prices, consensus_price)
        
        # Calculate spread for arbitrage detection
        max_deviation = self._calculate_max_deviation(valid_prices, consensus_price)
        source_spreads = self._calculate_source_spreads(valid_prices, consensus_price)
        
        # Log spread alert if above threshold
        spread_threshold = getattr(settings, 'SPREAD_ALERT_THRESHOLD', 0.01)
        warning_threshold = getattr(settings, 'SPREAD_WARNING_THRESHOLD', 0.02)
        if getattr(settings, 'SPREAD_LOG_ENABLED', True) and max_deviation > spread_threshold:
            alert_level = "WARNING" if max_deviation > warning_threshold else "ALERT"
            logger.info(
                f"SPREAD {alert_level} {product_id}: {max_deviation:.2%} spread "
                f"(sources: {', '.join(valid_prices.keys())})"
            )
        
        return ConsensusResult(
            product_id=product_id,
            price=consensus_price,
            confidence=confidence,
            sources_used=list(valid_prices.keys()),
            source_prices=valid_prices,
            outlier_sources=outlier_sources,
            max_deviation_pct=max_deviation,
            spread_pct=max_deviation,
            source_spreads=source_spreads
        )
    
    def _calculate_confidence(
        self, 
        source_prices: Dict[str, PriceSource], 
        consensus_price: float
    ) -> float:
        """
        Calculate confidence score based on source agreement.
        
        Args:
            source_prices: Valid source prices
            consensus_price: Calculated consensus price
            
        Returns:
            Confidence score (0-1)
        """
        if not source_prices:
            return 0.0
        
        if len(source_prices) == 1:
            return 0.5  # Single source = lower confidence
        
        # Calculate average deviation from consensus
        deviations = [
            abs(src.price - consensus_price) / consensus_price
            for src in source_prices.values()
        ]
        
        avg_deviation = sum(deviations) / len(deviations)
        
        # Convert to confidence (0 deviation = 1.0, max_deviation = 0.0)
        confidence = max(0, 1 - (avg_deviation / self.max_deviation))
        
        return confidence
    
    def _calculate_max_deviation(
        self, 
        source_prices: Dict[str, PriceSource], 
        consensus_price: float
    ) -> float:
        """Calculate max deviation from consensus."""
        if not source_prices:
            return 0.0
        
        deviations = [
            abs(src.price - consensus_price) / consensus_price
            for src in source_prices.values()
        ]
        
        return max(deviations) if deviations else 0.0
    
    def _calculate_source_spreads(
        self,
        source_prices: Dict[str, PriceSource],
        consensus_price: float
    ) -> Dict[str, float]:
        """
        Calculate per-source spread from consensus.
        
        Returns:
            Dict mapping source name to spread percentage
        """
        if not source_prices or consensus_price <= 0:
            return {}
        
        spreads = {}
        for source, src_data in source_prices.items():
            spread = abs(src_data.price - consensus_price) / consensus_price
            spreads[source] = spread
        
        return spreads
    
    def _update_health(self, source: str, success: bool):
        """Update source health statistics."""
        health = self._source_health.get(source, {'success': 0, 'fail': 0})
        
        if success:
            health['success'] = health.get('success', 0) + 1
            health['last_success'] = datetime.now()
        else:
            health['fail'] = health.get('fail', 0) + 1
        
        self._source_health[source] = health
    
    def _log_consensus(self, result: ConsensusResult):
        """Log consensus result."""
        source_str = ', '.join(result.sources_used)
        
        if result.outlier_sources:
            outlier_str = f" (outliers: {', '.join(result.outlier_sources)})"
        else:
            outlier_str = ""
        
        logger.info(
            f"Consensus {result.product_id}: £{result.price:.2f} "
            f"[{source_str}]{outlier_str} "
            f"conf:{result.confidence:.0%} dev:{result.max_deviation_pct:.2%}"
        )
    
    def get_source_health(self) -> Dict[str, Dict]:
        """Get health statistics for all sources."""
        return self._source_health.copy()
    
    def clear_cache(self):
        """Clear the price cache."""
        self._price_cache.clear()
        logger.info("Multi-source price cache cleared")


# Singleton instance
multi_source_pricer: Optional[MultiSourcePricer] = None


def get_multi_source_pricer() -> MultiSourcePricer:
    """Get or create multi-source pricer singleton."""
    global multi_source_pricer
    if multi_source_pricer is None:
        multi_source_pricer = MultiSourcePricer()
    return multi_source_pricer
