"""
Trading Engine module for crypto trading bot.

This module orchestrates the complete trading workflow:
- Signal generation from AI model
- Risk assessment and position sizing
- Order execution and management
- Position monitoring and closing

Educational Notes:
- Trading engines separate signal generation from execution
- Orders should be validated before execution
- Position management includes entry, monitoring, and exit
- Paper trading allows testing without real money
"""

import logging
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import uuid

from config.settings import settings
from src.ai_model import ai_model
from src.risk_manager import risk_manager
from src.data_collector import data_collector
from src.coinbase_api import coinbase_api
from src.database import db_manager
from src.cache_manager import write_signal_cache
from typing import Tuple

logger = logging.getLogger(__name__)

def get_fifo_cost_basis(product_id: str) -> Tuple[float, float]:
    """Get FIFO cost basis from Coinbase fills."""
    try:
        client = coinbase_api.sdk_client
        fills = client.get_fills(product_id=product_id)
        
        # Sort fills by time (oldest first) for proper FIFO processing
        fill_list = sorted(fills.fills, key=lambda f: f.trade_time)
        
        lots = []
        for fill in fill_list:
            side = fill.side.upper()
            price = float(fill.price)
            size = float(fill.size)
            
            if side == 'BUY':
                lots.append({'size': size, 'price': price})
            else:
                # SELL - use FIFO
                remaining = size
                while remaining > 0.00000001 and lots:
                    if lots[0]['size'] <= remaining:
                        remaining -= lots[0]['size']
                        lots.pop(0)
                    else:
                        lots[0]['size'] -= remaining
                        remaining = 0
        
        remaining_size = sum(lot['size'] for lot in lots)
        
        # Get actual wallet balance to validate
        currency = product_id.split('-')[0]
        wallet_balance = coinbase_api.get_account_balance(currency)
        
        # Cap at wallet balance (fills may have stale/duplicate data)
        if wallet_balance > 0 and remaining_size > wallet_balance:
            remaining_size = wallet_balance
        
        if remaining_size > 0.00000001:
            # Recalculate total cost based on capped size
            original_total = sum(lot['size'] * lot['price'] for lot in lots)
            original_size = sum(lot['size'] for lot in lots)
            if remaining_size < original_size:
                total_cost = original_total * (remaining_size / original_size)
            else:
                total_cost = original_total
            return remaining_size, total_cost / remaining_size
        return 0.0, 0.0
    except Exception as e:
        logger.warning(f"Could not get cost basis for {product_id}: {e}")
        return 0.0, 0.0

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    Trading Engine class that coordinates all trading activities.

    This class brings together AI signals, risk management, and order execution
    to create a complete automated trading system.
    """

    def __init__(self):
        """Initialize the trading engine."""
        # Load persisted trading mode, default to paper trading
        from src.database import db_manager
        persisted_mode = db_manager.get_user_setting('paper_trading', 'true')
        self.paper_trading = persisted_mode.lower() == 'true' if persisted_mode else True

        self.active_positions = {}
        self.last_trade_time = {}  # Initialize last trade time tracking
        
        # Load holdings from database
        self.holdings = {}
        for product_id in settings.PRODUCT_IDS:
            self.holdings[product_id] = {'has_position': False, 'entry_price': 0, 'size': 0}
        
        db_positions = db_manager.load_open_positions(trade_type='paper' if self.paper_trading else 'live')
        for product_id, pos in db_positions.items():
            self.holdings[product_id] = {
                'has_position': True,
                'entry_price': pos.get('entry_price', 0),
                'weighted_entry_price': pos.get('weighted_entry_price', pos.get('entry_price', 0)),
                'size': pos.get('size', 0)
            }
            # Also load into active_positions for monitoring
            # Ensure regime is set (default to 'neutral' for existing positions)
            if 'regime' not in pos:
                pos['regime'] = 'neutral'
            self.active_positions[pos['position_id']] = pos
        
        logger.info(f"Trading Engine initialized (paper trading: {self.paper_trading}, active_positions={len(self.active_positions)})")

    def initial_position_sync(self):
        """Sync positions from Coinbase wallet on startup."""
        if self.paper_trading:
            logger.info("Skipping position sync - paper trading mode")
            return
            
        logger.info("=== SYNC: Loading positions from Coinbase wallet ===")
        
        # Clear existing active positions (will reload from DB after sync)
        self.active_positions = {}
        
        # Sync each product from Coinbase wallet
        for product_id in settings.PRODUCT_IDS:
            currency = product_id.split('-')[0]
            wallet_balance = coinbase_api.get_account_balance(currency)
            
            if wallet_balance > 0.00000001:
                # Get cost basis
                size, avg_cost = get_fifo_cost_basis(product_id)
                
                if avg_cost > 0:
                    entry_price = avg_cost
                else:
                    entry_price = data_collector.get_current_prices().get(product_id, 0)
                
                # Check if position already exists in DB (avoid duplicates)
                existing_positions = db_manager.load_open_positions(trade_type='live')
                existing = existing_positions.get(product_id) if existing_positions else None
                
                if not existing:
                    # Create new position from wallet (always use live for real trading)
                    logger.info(f"SYNC: Creating {product_id} position from wallet: {wallet_balance} @ £{entry_price:.2f}")
                    db_manager.save_open_position({
                        'product_id': product_id,
                        'side': 'buy',
                        'size': wallet_balance,
                        'remaining_size': wallet_balance,  # Set remaining size
                        'entry_price': entry_price,
                        'weighted_entry_price': entry_price,
                        'peak_price': entry_price,  # Initialize peak to entry price
                        'trade_type': 'live',  # Always live for real trading
                        'status': 'open'
                    })
                else:
                    # Update existing - preserve side, trade_type, position_id, AND opened_at
                    logger.info(f"SYNC: Updating {product_id} from wallet: was {existing.get('size', 0)}, now {wallet_balance}")
                    db_manager.save_open_position({
                        'product_id': product_id,
                        'position_id': existing.get('position_id'),  # PRESERVE UUID
                        'side': existing.get('side', 'buy'),
                        'size': wallet_balance,
                        'remaining_size': wallet_balance,  # Update remaining size
                        'entry_price': entry_price,
                        'weighted_entry_price': entry_price,
                        'peak_price': existing.get('peak_price', entry_price),  # Preserve existing peak or init to entry
                        'opened_at': existing.get('opened_at'),  # PRESERVE original open date
                        'trade_type': 'live'  # Ensure live for real trading
                    })
                
                # Update holdings
                self.holdings[product_id] = {
                    'has_position': True,
                    'entry_price': entry_price,
                    'size': wallet_balance
                }
            else:
                # No balance in wallet - clear position
                self.holdings[product_id] = {'has_position': False, 'entry_price': 0, 'size': 0}
        
        # NOW load all open positions from DB into active_positions
        logger.info("=== SYNC: Loading open positions into active_positions ===")
        db_positions = db_manager.load_open_positions(trade_type='live') or {}
        for product_id, pos in db_positions.items():
            # Ensure regime is set (default to 'neutral' for existing positions)
            if 'regime' not in pos:
                pos['regime'] = 'neutral'
            self.active_positions[pos['position_id']] = pos
            
        logger.info(f"=== SYNC: Position sync complete - {len(self.active_positions)} active positions ===")

    def _sync_signals_to_cache(self):
        """
        Write all current signals to cache file for dashboard synchronization.

        This ensures the dashboard shows the same signals the trading engine is using.
        Called after each trading cycle completes.
        """
        try:
            signals_for_cache = {}
            for product_id in settings.PRODUCT_IDS:
                signal = ai_model.get_signal(product_id)
                signals_for_cache[product_id] = signal

            write_signal_cache(signals_for_cache)
            logger.info(f"Synced {len(signals_for_cache)} signals to cache for dashboard")
        except Exception as e:
            logger.error(f"Error syncing signals to cache: {e}")

    def _save_portfolio_snapshot(self, cycle_results: Dict[str, Any]):
        """
        Save a portfolio snapshot for tracking performance over time.
        
        Args:
            cycle_results: Results from the trading cycle
        """
        try:
            # Get current portfolio values
            gbp_balance = risk_manager.get_gbp_balance()
            
            # Calculate crypto value and unrealized PnL
            crypto_value = 0.0
            unrealized_pnl = 0.0
            
            for position_id, position in self.active_positions.items():
                if position.get('status') == 'open':
                    product_id = position.get('product_id', '')
                    size = position.get('remaining_size', position.get('size', 0))
                    entry = position.get('entry_price', 0)
                    
                    # Get current price
                    ticker = coinbase_api.get_product_ticker(product_id)
                    if ticker and 'price' in ticker:
                        current = float(ticker['price'])
                        crypto_value += size * current
                        unrealized_pnl += size * (current - entry)
            
            # Get today's trades stats
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Save snapshot
            db_manager.save_portfolio_snapshot(
                gbp_balance=gbp_balance,
                crypto_value=crypto_value,
                unrealized_pnl=unrealized_pnl,
                trades_today=cycle_results.get('trades_executed', 0),
                pnl_today=cycle_results.get('total_pnl', 0.0),
                fees_today=0.0  # Fees tracked in trade records
            )
            
            logger.info(f"Portfolio snapshot saved: £{gbp_balance + crypto_value:.2f} (crypto: £{crypto_value:.2f}, unrealized: £{unrealized_pnl:.2f})")
        except Exception as e:
            logger.error(f"Error saving portfolio snapshot: {e}")

    def scan_for_signals(self) -> List[Dict[str, Any]]:
        """
        Scan all configured products for trading signals.

        Returns:
            List of valid trading signals
        """
        signals = []

        for product_id in settings.PRODUCT_IDS:
            try:
                # Check if we should trade this product
                if not self._should_trade_product(product_id):
                    continue

                # Get AI signal
                signal = ai_model.get_signal(product_id)

                if signal['action'] != 'HOLD':
                    # Validate signal with risk management
                    if self._validate_signal(signal, product_id):
                        signals.append({
                            'product_id': product_id,
                            'signal': signal,
                            'timestamp': datetime.now()
                        })
                        logger.info(f"Valid signal found: {product_id} {signal['action']} ({signal['confidence']:.1%})")

            except Exception as e:
                logger.error(f"Error scanning {product_id}: {e}")
                continue

        return signals

    def _should_trade_product(self, product_id: str) -> bool:
        """
        Check if we should trade a specific product.

        Args:
            product_id: Trading pair identifier

        Returns:
            True if trading is allowed
        """
        # Check trading frequency limits
        now = datetime.now()
        if product_id in self.last_trade_time:
            time_since_last_trade = now - self.last_trade_time[product_id]
            if time_since_last_trade < timedelta(minutes=30):  # Minimum 30 minutes between trades
                return False

        # Check if product already has an open position (in holdings)
        if product_id in self.holdings and self.holdings[product_id].get('has_position', False):
            logger.info(f"SKIP: {product_id} - position already open")
            return False
        
        # Check active positions
        if len(self.active_positions) >= settings.MAX_CONCURRENT_POSITIONS:
            return False

        # Check if product already has an open position
        for position in self.active_positions.values():
            if position['product_id'] == product_id:
                return False

        return True

    def _validate_signal(self, signal: Dict[str, Any], product_id: str) -> bool:
        """
        Validate a trading signal with risk management.

        Args:
            signal: AI-generated trading signal
            product_id: Trading pair

        Returns:
            True if signal is valid for execution
        """
        try:
            # Block BUY signals in downtrend - price is decreasing, don't buy
            regime = signal.get('regime', 'neutral').lower()
            action = signal.get('action', 'HOLD').upper()
            
            if action == 'BUY' and regime == 'downtrend':
                logger.info(f"SIGNAL REJECTED: {product_id} - BUY not allowed in downtrend (price decreasing)")
                return False
            
            # Check if trading is paused
            should_pause, reason = risk_manager.should_pause_trading()
            if should_pause:
                logger.info(f"Trading paused: {reason}")
                return False

            # Get current price
            prices = data_collector.get_current_prices()
            if product_id not in prices:
                return False

            entry_price = prices[product_id]

            # Get volatility for stop loss calculation
            features = data_collector.get_latest_features(product_id)
            volatility = features.get('volatility', entry_price * 0.02)  # Fallback

            # Ensure volatility is not None for stop loss calculation
            if volatility is None or volatility <= 0:
                volatility = entry_price * 0.02  # Use fallback if None
                logger.debug(f"Using fallback volatility for {product_id}: {volatility}")

            # Calculate stop loss
            direction = 'long' if signal['prediction'] == 1 else 'short'
            stop_loss_price = risk_manager.calculate_stop_loss(entry_price, direction, volatility)
            
            logger.debug(f"Signal validation: {product_id} | Entry: {entry_price:.6f} | Volatility: {volatility:.4f} | Direction: {direction} | Stop Loss: {stop_loss_price:.6f}")
            
            # Fix 2: Fallback if stop_loss_price is 0 or negative
            if stop_loss_price <= 0:
                # Fallback: 5% stop loss from entry
                if direction == 'long':
                    stop_loss_price = entry_price * 0.95
                else:
                    stop_loss_price = entry_price * 1.05
                logger.warning(f"CRITICAL: stop_loss_price was {stop_loss_price} for {product_id}! Using fallback: £{stop_loss_price:.2f}")

            # Calculate position size
            confidence = signal['confidence']
            position_sizing = risk_manager.calculate_position_size(
                product_id, confidence, entry_price, stop_loss_price
            )

            if position_sizing['size'] <= 0:
                logger.info(f"Signal rejected: {position_sizing['reason']}")
                return False

            # Check account balance for required currency
            base_currency, quote_currency = product_id.split('-')
            side = 'buy' if signal['action'] == 'BUY' else 'sell'
            if side == 'buy':
                required_currency = quote_currency
                required_amount = position_sizing['size'] * entry_price
            else:
                required_currency = base_currency
                required_amount = position_sizing['size']

            try:
                balance = coinbase_api.get_account_balance(required_currency)
                if balance < required_amount:
                    logger.info(f"Insufficient balance for {product_id} {side}: need {required_amount:.6f} {required_currency}, have {balance:.6f}")
                    return False
            except Exception as e:
                logger.error(f"Failed to check balance for {required_currency}: {e}")
                return False

            # Store validated signal details
            signal['entry_price'] = entry_price
            signal['stop_loss_price'] = stop_loss_price
            
            # Validate stop_loss_price is set correctly
            if signal['stop_loss_price'] <= 0:
                logger.error(f"CRITICAL: stop_loss_price still 0 after setting for {product_id}!")
            signal['take_profit_prices'] = risk_manager.calculate_take_profits(
                entry_price, stop_loss_price, direction
            )
            signal['position_size'] = position_sizing

            return True

        except Exception as e:
            logger.error(f"Error validating signal: {e}")
            return False

    def execute_signal(self, signal_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Execute a validated trading signal.

        Args:
            signal_data: Validated signal with position details

        Returns:
            Trade execution result or None if failed
        """
        try:
            signal = signal_data['signal']
            product_id = signal_data['product_id']

            logger.info(f"Executing {signal['action']} signal for {product_id}")

            # Prepare order details
            side = 'buy' if signal['action'] == 'BUY' else 'sell'
            size = signal['position_size']['size']
            entry_price = signal['entry_price']

            logger.info(f"Order details: {side} {size:.8f} {product_id} at ~${entry_price:.2f}")

            # Execute order (paper trading or live)
            if self.paper_trading:
                order_result = self._execute_paper_order(
                    product_id, side, size, entry_price, signal
                )
            else:
                order_result = self.execute_live_trade(
                    product_id, side, size
                )

            logger.info(f"Order result: {order_result}")

            if order_result and order_result.get('success', False):
                # Record the position
                position_id = str(uuid.uuid4())
                
                # Get regime from signal for trailing stop
                regime = signal.get('regime', 'neutral')
                confidence = signal.get('confidence', 0)
                action = signal.get('action', 'HOLD')
                
                # Create entry_reason for tracking why position was opened
                entry_reason = f"AI {action}, conf={confidence:.0%}, regime={regime}"
                
                position_details = {
                    'position_id': position_id,
                    'product_id': product_id,
                    'side': side,
                    'size': size,
                    'entry_price': entry_price,
                    'weighted_entry_price': entry_price,  # Initialize with entry price
                    'stop_loss_price': signal['stop_loss_price'],
                    'take_profit_prices': signal['take_profit_prices'],
                    'regime': regime,
                    'signal': signal,
                    'opened_at': datetime.now(),
                    'status': 'open',
                    'scale_in_count': 0,  # Initialize scale-in tracking
                    'remaining_size': size,  # Initialize remaining size to full size
                    'peak_price': entry_price,  # NEW: Initialize peak price to entry price
                    'entry_reason': entry_reason  # NEW: Track why position was opened
                }
                
                # Persist to database FIRST
                db_result = db_manager.save_open_position({
                    'position_id': position_id,
                    'product_id': product_id,
                    'side': side,
                    'size': size,
                    'entry_price': entry_price,
                    'remaining_size': size,  # Set remaining size when opening position
                    'stop_loss_price': signal['stop_loss_price'],
                    'take_profit_prices': signal['take_profit_prices'],
                    'regime': regime,
                    'opened_at': datetime.now(),
                    'status': 'open',
                    'trade_type': 'paper' if self.paper_trading else 'live',
                    'current_price': entry_price,  # NEW: Save current price when opening
                    'peak_price': entry_price,  # NEW: Save peak price to database
                    'entry_reason': entry_reason  # NEW: Track why position was opened
                })
                
                if not db_result:
                    logger.error(f"CRITICAL: Failed to save {product_id} position to database! Position may not appear in dashboard.")
                    return None
                
                # Only update in-memory state AFTER successful DB save
                self.active_positions[position_id] = position_details
                self.last_trade_time[product_id] = datetime.now()
                
                # Update holdings to track open position
                self.holdings[product_id] = {
                    'has_position': True,
                    'entry_price': entry_price,
                    'size': size
                }
                
                # Add to risk manager
                risk_manager.add_open_position(position_id, position_details)
                
                logger.info(f"Position opened: {position_id} ({side} {size:.6f} {product_id})")
                return order_result

            else:
                logger.warning(f"Order execution failed: {order_result}")
                return None

        except Exception as e:
            logger.error(f"Error executing signal: {e}")
            return None

    def _execute_paper_order(self, product_id: str, side: str, size: float,
                           price: float, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a paper trading order (simulated).

        Args:
            product_id: Trading pair
            side: 'buy' or 'sell'
            size: Position size
            price: Entry price
            signal: Signal details

        Returns:
            Simulated order result
        """
        # Simulate order execution with UUID to avoid collisions
        import uuid
        order_id = f"paper_{str(uuid.uuid4())[:8]}"

        # Record in database
        trade_data = {
            'order_id': order_id,
            'product_id': product_id,
            'side': side,
            'size': size,
            'price': price,
            'timestamp': datetime.now(),  # Use datetime object, not string
            'status': 'filled',
            'pnl': 0.0,  # Will be updated when closed
            'fees': 0.0,
            'trade_type': 'paper'  # Explicitly set to paper
        }

        db_manager.save_trade(trade_data)

        logger.info(f"Paper order executed: {side} {size:.6f} {product_id} at ${price:.2f}")

        return {
            'success': True,
            'order_id': order_id,
            'product_id': product_id,
            'side': side,
            'size': size,
            'price': price,
            'mode': 'paper'
        }

    def execute_live_trade(self, product_id: str, side: str, size: float):
        """Execute a live trading order."""
        try:
            logger.info(f"Placing live order: {side} {size:.8f} {product_id}")
            # For live trading, use market orders
            order_result = coinbase_api.place_market_order(
                product_id=product_id,
                side=side,
                size=size
            )

            logger.info(f"Live order API result: {order_result}")

            if order_result:
                # Extract actual fees from order result (fetched from Coinbase API)
                fees = order_result.get('fees', 0.0)
                
                # Save to database
                trade_data = {
                    'order_id': order_result.get('order_id', 'N/A'),
                    'product_id': product_id,
                    'side': side,
                    'size': order_result.get('size', 0.0),
                    'price': order_result.get('price', 0.0),
                    'timestamp': datetime.now(),
                    'status': 'filled',
                    'pnl': 0.0,
                    'fees': fees,
                    'trade_type': 'live'  # Explicitly set to live
                }

                db_manager.save_trade(trade_data)

                logger.info(f"Live order executed: {order_result}")
                return order_result

        except Exception as e:
            logger.error(f"Live order execution failed: {e}")
            return {'success': False, 'error': str(e)}

    def execute_scale_in(self, position_id: str) -> Optional[Dict[str, Any]]:
        """
        Execute a scale-in (averaging down) for an existing position.
        
        Args:
            position_id: The position ID to scale in
            
        Returns:
            Scale-in result or None if failed
        """
        from config.settings import settings
        
        if position_id not in self.active_positions:
            logger.error(f"Position {position_id} not found for scale-in")
            return None
            
        position = self.active_positions[position_id]
        
        # Check if scale-in already done
        scale_in_count = position.get('scale_in_count', 0)
        if scale_in_count >= settings.MAX_SCALE_INS_PER_POSITION:
            logger.info(f"Scale-in max reached for {position_id}")
            return None
            
        product_id = position['product_id']
        current_prices = data_collector.get_current_prices()
        
        if product_id not in current_prices:
            logger.error(f"No current price for {product_id}")
            return None
            
        current_price = current_prices[product_id]
        original_size = position['size']
        original_entry = position['entry_price']
        weighted_entry = position.get('weighted_entry_price', original_entry)
        
        # Calculate scale-in size (100% of original position)
        scale_in_size = original_size * settings.SCALE_IN_SIZE_BY_LEVEL[0]
        
        # Check GBP balance for scale-in
        required_gbp = scale_in_size * current_price
        from src.risk_manager import risk_manager
        can_trade, reason = risk_manager.can_open_trade(required_gbp, self.paper_trading)
        if not can_trade:
            logger.info(f"Scale-in blocked: {reason}")
            return None
            
        try:
            logger.info(f"[SCALE-IN] Executing: {product_id} adding {scale_in_size}")
            
            # Execute buy order
            if self.paper_trading:
                order_result = self._execute_paper_order(
                    product_id, 'buy', scale_in_size, current_price, {}
                )
            else:
                order_result = self.execute_live_trade(
                    product_id, 'buy', scale_in_size
                )
            
            if order_result and order_result.get('success', False):
                # Calculate new weighted entry price
                total_size = original_size + scale_in_size
                new_weighted_entry = (
                    (original_size * weighted_entry) + 
                    (scale_in_size * current_price)
                ) / total_size
                
                # Update position in memory
                position['weighted_entry_price'] = new_weighted_entry
                position['scale_in_count'] = scale_in_count + 1
                position['last_scale_in_price'] = current_price
                position['last_scale_in_time'] = datetime.now()
                position['remaining_size'] = total_size
                
                # Update in active_positions with new size
                position['size'] = total_size
                
                # Save to database
                db_manager.update_scale_in_state(
                    position_id,
                    new_weighted_entry,
                    current_price,
                    scale_in_count + 1,
                    total_size
                )
                
                logger.info(
                    f"[SCALE-IN] Complete: {product_id} "
                    f"original={original_size}, added={scale_in_size}, "
                    f"new_weighted=£{new_weighted_entry:.2f}"
                )
                
                return {'success': True, 'new_weighted_entry': new_weighted_entry}
            else:
                logger.warning(f"Scale-in order failed: {order_result}")
                return None
                
        except Exception as e:
            logger.error(f"Scale-in execution failed: {e}")
            return None

    def simple_test_method(self):
        """Simple test method."""
        return "test"

    def monitor_positions(self) -> List[Dict[str, Any]]:
            """
            Monitor open positions and check for exit conditions.
            
            Uses dynamic trailing stop based on regime:
            - Trailing stop only activates when price covers fees (break-even)
            - Stop moves up as price increases (locks in profit)
            - Never sells below break-even floor
            """
            from config.settings import settings
            
            closed_positions = []
            scale_in_candidates = []  # Collect candidates, execute only best
            scale_in_spent = 0.0  # Track GBP spent this cycle

            for position_id, position in list(self.active_positions.items()):
                try:
                    if position['status'] != 'open':
                        continue

                    product_id = position['product_id']
                    current_prices = data_collector.get_current_prices()

                    if product_id not in current_prices:
                        continue

                    current_price = current_prices[product_id]
                    stored_entry_price = position['entry_price']
                    position_size = position.get('remaining_size', position['size'])

                    # Get TRUE cost basis from Coinbase fills (FIFO)
                    if not self.paper_trading:
                        cost_basis_size, fifo_entry_price = get_fifo_cost_basis(product_id)
                        if fifo_entry_price > 0 and cost_basis_size > 0:
                            entry_price = fifo_entry_price
                            logger.info(f"Using FIFO cost basis for {product_id}: £{fifo_entry_price:.2f}")
                        else:
                            entry_price = stored_entry_price
                    else:
                        entry_price = stored_entry_price
                    
                    # Initialize should_close
                    should_close = False
                    exit_reason = ""
                    
                    # Get fee rates from database
                    fees = db_manager.get_fee_rates()
                    if not fees:
                        fees = coinbase_api.get_fees()
                    
                    maker_fee = fees.get('maker_fee', settings.DEFAULT_MAKER_FEE)
                    taker_fee = fees.get('taker_fee', settings.DEFAULT_TAKER_FEE)
                    total_fee = maker_fee + taker_fee

                    # Calculate break-even (covers fees)
                    break_even = entry_price * (1 + total_fee)

                    # Get regime and trailing stop percentage (2% as requested)
                    regime = position.get('regime', 'neutral')
                    trailing_pct = settings.TRAILING_STOP_REGIME_MAP.get(regime, settings.TRAILING_STOP_PERCENT)

                    # Track peak unconditionally (always update if higher)
                    peak_price = position.get('peak_price', entry_price)
                    if current_price > peak_price:
                        peak_price = current_price
                        position['peak_price'] = peak_price
                        update_result = db_manager.update_peak_price(position_id, peak_price)
                        if update_result:
                            logger.info(f"[PEAK_UPDATE] {product_id}: £{peak_price:.2f} (position_id: {position_id[:8]}...)")
                        else:
                            logger.error(f"[PEAK_UPDATE] FAILED for {product_id}: position_id={position_id}")

                    # Check if trailing stop is "activated" (price has been above break-even + buffer)
                    # This means we've covered fees + buffer and can start locking in profits
                    activation_threshold = break_even * (1 + settings.TRAILING_ACTIVATION_BUFFER)
                    trailing_activated = peak_price >= activation_threshold
                    position['trailing_activated'] = trailing_activated

                    # Calculate trailing stop (always calculate)
                    trailing_stop = peak_price * (1 - trailing_pct)
                    # v2.9.1: Floor is break-even minus buffer, NOT 95% of entry
                    # This prevents triggering when price is between entry and break-even
                    stop_floor = break_even * (1 - trailing_pct)
                    trailing_stop = max(trailing_stop, stop_floor)
                    
                    # =====================================================
                    # CHECK AI SELL SIGNALS FOR EXISTING POSITIONS
                    # =====================================================
                    if not should_close and position['side'] == 'buy':
                        try:
                            signal = ai_model.get_signal(product_id)
                            signal_action = signal.get('action', 'HOLD')
                            signal_confidence = signal.get('confidence', 0.0)
                            
                            if signal_action == 'SELL':
                                profit_pct = (current_price - entry_price) / entry_price
                                # Only close if in profit (above break-even) or minimum profit threshold
                                min_profit_pct = 0.01  # 1% minimum profit
                                if current_price >= break_even or profit_pct >= min_profit_pct:
                                    should_close = True
                                    exit_reason = f"AI SELL signal (confidence: {signal_confidence:.1%})"
                                    logger.info(f"[AI SELL] {product_id}: Signal={signal_action} confidence={signal_confidence:.1%}, profit={profit_pct:.2%}, closing position")
                                else:
                                    logger.info(f"[AI SELL] {product_id}: Signal={signal_action} confidence={signal_confidence:.1%}, profit={profit_pct:.2%}, NOT closing (below break-even)")
                        except Exception as e:
                            logger.warning(f"[AI SELL] Could not get signal for {product_id}: {e}")

                    # Check if trailing stop is hit
                    if not should_close and position['side'] == 'buy':
                        if current_price <= trailing_stop:
                            if trailing_activated:
                                should_close = True
                                exit_reason = "Trailing stop hit"
                            # v2.9.1: Emergency stop ONLY if already in profit (above break-even)
                            # Don't sell at a loss - let it ride until it recovers or hits break-even
                            elif current_price >= break_even and (entry_price - current_price) / entry_price > 0.02:
                                should_close = True
                                exit_reason = "Emergency stop (2% drop from entry, was above break-even)"
                                logger.warning(f"[EMERGENCY STOP] {product_id}: Price £{current_price:.2f} below entry £{entry_price:.2f} but was above break-even £{break_even:.2f}")
                    elif position['side'] == 'sell':
                        if current_price >= trailing_stop and current_price <= entry_price:
                            should_close = True
                            exit_reason = "Trailing stop hit"
                    
                    if not should_close:
                        logger.info(f"[TRAILING STOP] {product_id}: Not triggered. trailing_stop=£{trailing_stop:.2f} current=£{current_price:.2f} activated={trailing_activated}")

                    # Log for debugging
                    logger.info(
                        f"[TRAILING STOP] {product_id}: "
                        f"entry={entry_price:.2f} peak={peak_price:.2f} current={current_price:.2f} "
                        f"break_even={break_even:.2f} trailing_stop={trailing_stop:.2f} "
                        f"trailing_pct={trailing_pct:.0%} activated={trailing_activated}"
                    )

                    # =====================================================
                    # SCALE-IN CANDIDATE COLLECTION (collect, don't execute)
                    # =====================================================
                    if position['side'] == 'buy' and not should_close:
                        logger.info(f"[SCALE-IN EVAL] {product_id}: entry={entry_price:.2f}, current={current_price:.2f}, peak={peak_price:.2f}")
                        
                        if settings.SCALE_IN_ENABLED and not settings.SCALE_IN_GLOBAL_BLOCK:
                            if current_price < entry_price:
                                price_drop_pct = (entry_price - current_price) / entry_price
                                
                                # Get regime-based scale-in threshold
                                if regime == 'bear' or regime == 'downtrend':
                                    threshold = settings.SCALE_IN_LEVELS_BEAR[0] / 100
                                elif regime == 'bull' or regime == 'uptrend':
                                    threshold = settings.SCALE_IN_LEVELS_BULL[0] / 100
                                else:
                                    threshold = settings.SCALE_IN_LEVELS_NEUTRAL[0] / 100
                                
                                scale_in_count = position.get('scale_in_count', 0)
                                last_scale_in = position.get('last_scale_in_time')
                                
                                # Check cooldown
                                cooldown_ok = True
                                cooldown_msg = "no previous scale-in"
                                if last_scale_in:
                                    hours_since = (datetime.now() - last_scale_in).total_seconds() / 3600
                                    if hours_since < settings.SCALE_IN_COOLDOWN_HOURS:
                                        cooldown_ok = False
                                        cooldown_msg = f"cooldown active ({hours_since:.1f}h < {settings.SCALE_IN_COOLDOWN_HOURS}h)"
                                
                                logger.info(f"[SCALE-IN EVAL] {product_id}: price_drop={price_drop_pct:.2%}, threshold={threshold:.2%}, scale_in_count={scale_in_count}, {cooldown_msg}")
                                
                                if scale_in_count < settings.MAX_SCALE_INS_PER_POSITION and cooldown_ok:
                                        # Get AI signal FIRST - MUST have BUY signal for scale-in (indicates bottom)
                                        try:
                                            signal = ai_model.get_signal(product_id)
                                            signal_action = signal.get('action', 'HOLD')
                                            signal_confidence = signal.get('confidence', 0.0)
                                            logger.info(f"[SCALE-IN EVAL] {product_id}: signal={signal_action}, confidence={signal_confidence:.1%}, price_drop={price_drop_pct:.2%}")
                                        except Exception as e:
                                            logger.warning(f"Could not get signal for {product_id}: {e}")
                                            continue
                                        
                                        # MUST have BUY signal for scale-in (indicates price bottom reached)
                                        if signal_action != 'BUY':
                                            logger.info(
                                                f"[SCALE-IN] {product_id} rejected: "
                                                f"signal is {signal_action}, need BUY (bottom indicator)"
                                            )
                                            continue
                                        
                                        # Check minimum confidence
                                        if signal_confidence < settings.SCALE_IN_MIN_SIGNAL_CONFIDENCE:
                                            logger.info(
                                                f"[SCALE-IN] {product_id} rejected: "
                                                f"confidence {signal_confidence:.1%} < {settings.SCALE_IN_MIN_SIGNAL_CONFIDENCE:.1%}"
                                            )
                                            continue
                                        
                                        # Verify price has dropped (sanity check - ensures we're scaling in at a discount)
                                        if price_drop_pct < threshold:
                                            logger.info(
                                                f"[SCALE-IN] {product_id} rejected: "
                                                f"price_drop {price_drop_pct:.2%} < threshold {threshold:.2%} (not enough discount)"
                                            )
                                            continue
                                        
                                        logger.info(f"[SCALE-IN] {product_id} APPROVED: signal=BUY (bottom), price_drop={price_drop_pct:.2%}, confidence={signal_confidence:.1%}")
                                        
                                        # Calculate recovery score (higher = more likely to recover)
                                        # Score = confidence / max(drop_from_peak, 0.01)
                                        drop_from_peak = (peak_price - current_price) / peak_price if peak_price > 0 else 0.01
                                        score = signal_confidence / max(drop_from_peak, 0.01)
                                        
                                        # Regime bonus: bull market = more likely to recover
                                        if regime in ['bull', 'uptrend']:
                                            score *= 1.5
                                        
                                        # Calculate scale-in cost
                                        scale_in_size = position['size'] * settings.SCALE_IN_SIZE_BY_LEVEL[0]
                                        scale_in_cost = scale_in_size * current_price
                                        
                                        scale_in_candidates.append({
                                            'position_id': position_id,
                                            'product_id': product_id,
                                            'score': score,
                                            'signal_confidence': signal_confidence,
                                            'price_drop_pct': price_drop_pct,
                                            'scale_in_cost': scale_in_cost,
                                            'scale_in_size': scale_in_size
                                        })
                                    
                                    # Close position if conditions met
                    if should_close:
                        sell_size = position.get('remaining_size', position.get('size', 0))
                        
                        # Calculate pnl for logging
                        pnl = (current_price - entry_price) * sell_size
                        
                        logger.info(
                            f"[TRAILING STOP] SELL TRIGGERED: {product_id} "
                            f"current={current_price:.2f} <= trailing_stop={trailing_stop:.2f} "
                            f"pnl=£{pnl:.2f}, size={sell_size}"
                        )
                        
                        # Actually execute the sell order on Coinbase (not just update record!)
                        if not self.paper_trading and sell_size > 0:
                            try:
                                order_result = self.execute_live_trade(product_id, 'sell', sell_size)
                                logger.info(f"[TRAILING STOP] Sell order result: {order_result}")
                            except Exception as e:
                                logger.error(f"[TRAILING STOP] Failed to execute sell: {e}")
                        
                        # Update position record in DB
                        self._close_position(position_id, pnl, exit_reason, current_price)
                        closed_positions.append({
                            'position_id': position_id,
                            'pnl': pnl,
                            'exit_reason': exit_reason,
                            'exit_price': current_price,
                            'entry_price': entry_price,
                            'trailing_stop': trailing_stop
                        })

                except Exception as e:
                    logger.error(f"Error monitoring position {position_id}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue

            # =====================================================
            # EXECUTE BEST SCALE-IN CANDIDATE (only one per cycle)
            # =====================================================
            if scale_in_candidates:
                # Sort by score (highest first = most likely to recover)
                scale_in_candidates.sort(key=lambda x: x['score'], reverse=True)
                
                best = scale_in_candidates[0]
                
                # Check budget
                if scale_in_spent + best['scale_in_cost'] > settings.SCALE_IN_MAX_GBP_PER_CYCLE:
                    logger.info(
                        f"[SCALE-IN] Budget exhausted: £{scale_in_spent:.2f} + £{best['scale_in_cost']:.2f} > £{settings.SCALE_IN_MAX_GBP_PER_CYCLE:.2f}"
                    )
                else:
                    logger.info(
                        f"[SCALE-IN] Best candidate: {best['product_id']} "
                        f"score={best['score']:.1f} conf={best['signal_confidence']:.1%} "
                        f"cost=£{best['scale_in_cost']:.2f}"
                    )
                    scale_in_result = self.execute_scale_in(best['position_id'])
                    if scale_in_result:
                        scale_in_spent += best['scale_in_cost']
                        logger.info(
                            f"[SCALE-IN] Success: {best['product_id']} "
                            f"new_weighted=£{scale_in_result.get('new_weighted_entry')}"
                        )
                    else:
                        logger.info(f"[SCALE-IN] Failed: {best['product_id']}")

            # Update current_price in database for all open positions (for dashboard display)
            for position_id, position in self.active_positions.items():
                if position.get('status') == 'open':
                    product_id = position.get('product_id')
                    current_price = current_prices.get(product_id, 0)
                    if current_price > 0:
                        db_manager.update_position_current_price(product_id, current_price)

            return closed_positions

    def _close_position(self, position_id: str, pnl: float, reason: str, exit_price: float):
            """
            Close a position and update records.

            Args:
                position_id: Position identifier
                pnl: Profit/loss amount
                reason: Reason for closing
                exit_price: Price at which position was closed
            """
            if position_id in self.active_positions:
                position = self.active_positions[position_id]
                product_id = position.get('product_id', '')

                # Update position record in memory
                position['status'] = 'closed'
                position['closed_at'] = datetime.now()
                position['pnl'] = pnl
                position['exit_reason'] = reason
                position['exit_price'] = exit_price

                # Update database - actually close the position record
                db_manager.close_open_position(position_id, exit_price, pnl, reason, reason)

                # Update risk manager
                risk_manager.close_position(position_id, pnl)

                # Update holdings to allow new positions
                if product_id in self.holdings:
                    self.holdings[product_id] = {
                        'has_position': False,
                        'entry_price': 0,
                        'size': 0
                    }
                    logger.info(f"Holdings cleared for {product_id}")

                logger.info(f"Position closed: {product_id} | P&L: £{pnl:.2f} | Reason: {reason}")

    def get_status(self) -> Dict[str, Any]:
            """
            Get current trading engine status.

            Returns:
                Dictionary with status information
            """
            return {
                'paper_trading': self.paper_trading,
                'active_positions': len(self.active_positions),
                'positions': list(self.active_positions.keys()),
                'last_signals': [],  # Could track recent signals
                'risk_status': risk_manager.check_portfolio_risk(self.paper_trading)
            }

    def enable_live_trading(self):
            """Enable live trading (use with caution!)."""
            if not self.paper_trading:
                logger.warning("Live trading already enabled")
                return

            logger.warning("ENABLING LIVE TRADING - REAL MONEY WILL BE TRADED!")
            logger.warning("Make sure you understand the risks and have tested thoroughly")

            # Additional safety checks
            risk_status = risk_manager.check_portfolio_risk(False)  # Check with live trading mode
            if risk_status['risk_status'] != 'normal':
                logger.error(f"Cannot enable live trading: Risk status is {risk_status['risk_status']}")
                return

            self.paper_trading = False

            # Persist the trading mode change
            from src.database import db_manager
            db_manager.save_user_setting('paper_trading', 'false')

            logger.info("Live trading enabled - bot will now trade with real money")


    def run_trading_cycle(self) -> Dict[str, Any]:
        """
        Run a complete trading cycle.

        Returns:
            Results of the trading cycle
        """
        cycle_results = {
            'signals_found': 0,
            'trades_executed': 0,
            'positions_closed': 0,
            'total_pnl': 0.0
        }

        try:
            # 1. Scan for signals
            signals = self.scan_for_signals()
            cycle_results['signals_found'] = len(signals)

            # 2. Execute valid signals
            for signal_data in signals:
                result = self.execute_signal(signal_data)
                if result:
                    cycle_results['trades_executed'] += 1

            # 3. Monitor existing positions
            closed_positions = self.monitor_positions()
            cycle_results['positions_closed'] = len(closed_positions)

            # Calculate total P&L from closed positions
            for closed in closed_positions:
                cycle_results['total_pnl'] += closed['pnl']

            # Save portfolio snapshot for tracking
            self._save_portfolio_snapshot(cycle_results)

            logger.info(f"Trading cycle completed: {cycle_results}")

            # Sync signals to cache for dashboard synchronization
            self._sync_signals_to_cache()

        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")

        return cycle_results


# Global trading engine instance
trading_engine = TradingEngine()