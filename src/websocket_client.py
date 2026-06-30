"""
Coinbase WebSocket client for real-time price updates.

This module provides real-time price feeds using Coinbase Advanced Trade WebSocket API.
Per slippage-modeling.md: prioritize high-liquidity pairs (BTC, ETH) with WebSocket.

WebSocket Endpoint: wss://advanced-trade-ws.coinbase.com
Channels: ticker (real-time price updates)
"""

import logging
import threading
import time
from typing import Dict, Optional
from datetime import datetime

from coinbase.websocket import WSClient

from config.settings import settings

logger = logging.getLogger(__name__)


class WebSocketError(Exception):
    """Exception for WebSocket errors."""
    pass


class CoinbaseWebSocketClient:
    """
    Real-time price feed via Coinbase WebSocket.
    
    Provides real-time price updates for high-liquidity pairs (BTC, ETH)
    to minimize latency and stay within REST API rate limits.
    """
    
    WS_URL = "wss://advanced-trade-ws.coinbase.com"
    
    # High-liquidity pairs for WebSocket (per slippage-modeling.md)
    WEBSOCKET_PAIRS = ['BTC-GBP', 'ETH-GBP']
    
    # Fallback pairs in USD
    WEBSOCKET_PAIRS_USD = ['BTC-USD', 'ETH-USD']
    
    def __init__(self):
        """Initialize WebSocket client."""
        self._prices: Dict[str, float] = {}
        self._prices_lock = threading.Lock()
        self._ws_client = None
        self._connected = False
        self._running = False
        self._thread = None
        
        # Message callback for price updates
        self._on_price_update = None
        
    def start(self, on_price_update=None):
        """
        Start WebSocket connection in background thread.
        
        Args:
            on_price_update: Optional callback function(product_id, price)
        """
        if self._running:
            logger.warning("WebSocket already running")
            return
        
        self._on_price_update = on_price_update
        self._running = True
        
        # Start in background thread
        self._thread = threading.Thread(target=self._run_websocket, daemon=True)
        self._thread.start()
        
        logger.info("WebSocket client started in background thread")
    
    def _run_websocket(self):
        """Run WebSocket connection (called in background thread)."""
        while self._running:
            try:
                self._connect_and_listen()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    time.sleep(5)
    
    def _connect_and_listen(self):
        """Connect to WebSocket and listen for messages."""
        # Use None for API key - ticker channel is public
        self._ws_client = WSClient(on_message=self._on_message)
        
        try:
            self._ws_client.open()
            self._connected = True
            logger.info("WebSocket connected")
            
            # Subscribe to ticker channel for high-liquidity pairs
            # Use USD pairs as fallback since GBP might not have ticker
            product_ids = self.WEBSOCKET_PAIRS_USD + ['ETH-USD']
            
            self._ws_client.subscribe(
                product_ids=product_ids,
                channels=["ticker", "heartbeats"]
            )
            logger.info(f"Subscribed to ticker for {product_ids}")
            
            # Keep connection alive
            while self._running:
                self._ws_client.sleep_with_exception_check(1)
                
        except Exception as e:
            self._connected = False
            raise WebSocketError(f"Connection failed: {e}") from e
        finally:
            if self._ws_client:
                try:
                    self._ws_client.close()
                except:
                    pass
            self._connected = False
    
    def _on_message(self, msg):
        """Handle incoming WebSocket messages."""
        try:
            import json
            
            if isinstance(msg, str):
                data = json.loads(msg)
            else:
                data = msg
            
            # Handle ticker messages
            if data.get('channel') == 'ticker':
                product_id = data.get('product_id')
                if not product_id:
                    return
                
                # Extract price from ticker
                # Ticker format: { price: "53000.00", ... }
                price_str = data.get('price')
                if price_str:
                    try:
                        price = float(price_str)
                        
                        # Store price
                        with self._prices_lock:
                            self._prices[product_id] = price
                        
                        # Call callback if set
                        if self._on_price_update:
                            self._on_price_update(product_id, price)
                            
                        logger.debug(f"WebSocket price update: {product_id} = £{price}")
                        
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid price in ticker: {price_str}: {e}")
            
            # Handle heartbeat to keep connection alive
            elif data.get('channel') == 'heartbeats':
                logger.debug("Heartbeat received")
                
        except Exception as e:
            logger.warning(f"Error processing WebSocket message: {e}")
    
    def stop(self):
        """Stop WebSocket connection."""
        self._running = False
        if self._ws_client:
            try:
                self._ws_client.close()
            except:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("WebSocket client stopped")
    
    def get_price(self, product_id: str) -> Optional[float]:
        """
        Get latest price for a product.
        
        Args:
            product_id: e.g., 'BTC-GBP', 'BTC-USD'
            
        Returns:
            Latest price or None if not available
        """
        with self._prices_lock:
            # Try direct match first
            if product_id in self._prices:
                return self._prices[product_id]
            
            # Try USD equivalent for GBP pairs
            if product_id == 'BTC-GBP' and 'BTC-USD' in self._prices:
                return self._prices.get('BTC-USD')
            if product_id == 'ETH-GBP' and 'ETH-USD' in self._prices:
                return self._prices.get('ETH-USD')
            
            return None
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._connected
    
    def get_all_prices(self) -> Dict[str, float]:
        """Get all available prices."""
        with self._prices_lock:
            return self._prices.copy()


# Singleton instance
_websocket_client: Optional[CoinbaseWebSocketClient] = None


def get_websocket_client() -> CoinbaseWebSocketClient:
    """Get or create WebSocket client singleton."""
    global _websocket_client
    if _websocket_client is None:
        _websocket_client = CoinbaseWebSocketClient()
    return _websocket_client


def start_websocket_prices(on_price_update=None):
    """Start WebSocket price feed in background."""
    client = get_websocket_client()
    client.start(on_price_update=on_price_update)
    return client


def stop_websocket_prices():
    """Stop WebSocket price feed."""
    global _websocket_client
    if _websocket_client:
        _websocket_client.stop()
        _websocket_client = None
