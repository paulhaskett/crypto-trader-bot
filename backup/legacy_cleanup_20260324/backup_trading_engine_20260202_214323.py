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
import sys
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

        logger.info(f"Trading Engine initialized (paper trading: {self.paper_trading})")

    def scan_for_signals(self) -> List[Dict[str, Any]]:
        """
        Scan all configured products for trading signals.

        Handles max positions with intelligent replacement:
        - When positions < max: take up to (max - current_count) valid signals
        - When positions >= max: evaluate replacements based on confidence

        Returns:
            List of valid trading signals
        """
        print(f"SCAN_FOR_SIGNALS: Starting scan, active_positions={len(self.active_positions)}, max={settings.MAX_CONCURRENT_POSITIONS})", flush=True)
        
        signals = []
        candidates = []

        for product_id in settings.PRODUCT_IDS:
            try:
                # Get AI signal (skip frequency check for replacement evaluation)
                signal = ai_model.get_signal(product_id)

                if signal['action'] != 'HOLD':
                    candidates.append({
                        'product_id': product_id,
                        'signal': signal,
                        'timestamp': datetime.now()
                    })
                    print(f"  Candidate: {product_id} {signal['action']} ({signal['confidence']:.1%})", flush=True)

            except Exception as e:
                logger.error(f"Error scanning {product_id}: {e}")
                continue

        current_count = len(self.active_positions)
        max_positions = settings.MAX_CONCURRENT_POSITIONS
        room_remaining = max_positions - current_count

        print(f"SCAN_FOR_SIGNALS: {len(candidates)} candidates, current_count={current_count}, max={max_positions}, room={room_remaining}", flush=True)

        if current_count < max_positions:
            print(f"SCAN_FOR_SIGNALS: Room for {room_remaining} new positions", flush=True)
            signals_added = 0
            for candidate in candidates:
                if signals_added >= room_remaining:
                    print(f"SCAN_FOR_SIGNALS: Max positions reached ({signals_added}/{room_remaining}), stopping", flush=True)
                    break
                    
                product_id = candidate['product_id']
                # Check frequency and existing position (but NOT max count - already calculated above)
                if self._should_trade_product(product_id, check_max_positions=False):
                    if self._validate_signal(candidate['signal'], product_id):
                        signals.append(candidate)
                        signals_added += 1
                        logger.info(f"Valid signal found: {product_id} {candidate['signal']['action']} ({candidate['signal']['confidence']:.1%})")
        elif current_count >= max_positions and settings.POSITION_REPLACEMENT_ENABLED:
            print(f"SCAN_FOR_SIGNALS: Max positions reached, evaluating replacements", flush=True)
            replacements = self._evaluate_replacements(candidates)
            signals.extend(replacements)
            print(f"SCAN_FOR_SIGNALS: {len(replacements)} replacements found", flush=True)
        else:
            print(f"SCAN_FOR_SIGNALS: Max positions reached, replacements disabled", flush=True)

        print(f"SCAN_FOR_SIGNALS: Returning {len(signals)} signals", flush=True)
        return signals

    def _evaluate_replacements(self, candidates: List[Dict]) -> List[Dict[str, Any]]:
        """
        Evaluate if any candidates should replace existing positions.

        Rules:
        1. SELL signals can replace any position (maintains GBP balance)
        2. BUY signals replace lowest confidence BUY position
        3. Requires 15% confidence improvement (conservative threshold)

        Args:
            candidates: List of signal candidates

        Returns:
            List of signals that should replace existing positions
        """
        replacements = []
        replaced_positions = set()  # Track which positions are already marked for replacement
        max_replacements = len(self.active_positions)  # Can replace up to all current positions

        for candidate in candidates:
            if len(replacements) >= max_replacements:
                print(f"REPLACE_LIMIT: Max replacements reached ({max_replacements}), stopping", flush=True)
                break
                
            product_id = candidate['product_id']
            action = candidate['signal']['action']
            confidence = candidate['signal']['confidence']

            existing = next((p for p in self.active_positions.values()
                            if p['product_id'] == product_id), None)
            if existing:
                continue

            if action == 'SELL' and settings.ALLOW_SELL_REPLACEMENT:
                worst = self._get_worst_position()
                if worst and worst['position_id'] not in replaced_positions:
                    print(f"REPLACE: SELL {product_id} ({confidence:.1%}) replaces {worst['product_id']}", flush=True)
                    candidate['replaces'] = worst['product_id']
                    candidate['replacement_reason'] = 'SELL signal replaces worst position'
                    replacements.append(candidate)
                    replaced_positions.add(worst['position_id'])

            elif action == 'BUY':
                lowest = self._get_lowest_confidence_position()
                if lowest and lowest['position_id'] not in replaced_positions:
                    lowest_confidence = lowest.get('signal', {}).get('confidence', 0)
                    improvement = confidence - lowest_confidence

                    if improvement >= settings.REPLACEMENT_CONFIDENCE_THRESHOLD:
                        print(f"REPLACE: BUY {product_id} ({confidence:.1%}) replaces {lowest['product_id']} (conf: {lowest_confidence:.1%}, imp: {improvement:.1%})", flush=True)
                        candidate['replaces'] = lowest['product_id']
                        candidate['replacement_reason'] = f'BUY signal replaces lower confidence ({improvement:.1%} improvement)'
                        replacements.append(candidate)
                        replaced_positions.add(lowest['position_id'])

        if replacements:
            print(f"REPLACE_RESULT: {len(replacements)} positions will be replaced", flush=True)
        else:
            print(f"REPLACE_RESULT: No replacements made", flush=True)

        return replacements

    def _get_worst_position(self) -> Optional[Dict[str, Any]]:
        """
        Get the worst performing position (lowest P&L or oldest).

        Returns:
            Worst position dict or None
        """
        if not self.active_positions:
            return None

        worst = None
        worst_pnl = float('inf')

        for pos in self.active_positions.values():
            current_pnl = pos.get('pnl', 0)
            if current_pnl < worst_pnl:
                worst_pnl = current_pnl
                worst = pos

        return worst

    def _get_lowest_confidence_position(self) -> Optional[Dict[str, Any]]:
        """
        Get the position with lowest AI confidence.

        Returns:
            Lowest confidence position dict or None
        """
        if not self.active_positions:
            return None

        lowest = None
        lowest_conf = float('inf')

        for pos in self.active_positions.values():
            pos_confidence = pos.get('signal', {}).get('confidence', 0)
            if pos_confidence < lowest_conf:
                lowest_conf = pos_confidence
                lowest = pos

        return lowest

    def _should_trade_product(self, product_id: str, check_max_positions: bool = True) -> bool:
        """
        Check if we should trade a specific product.

        Args:
            product_id: Trading pair identifier
            check_max_positions: Whether to check max concurrent positions

        Returns:
            True if trading is allowed
        """
        # Check trading frequency limits
        now = datetime.now()
        if product_id in self.last_trade_time:
            time_since_last_trade = now - self.last_trade_time[product_id]
            if time_since_last_trade < timedelta(minutes=30):  # Minimum 30 minutes between trades
                return False

        # Check if we already have a position in this product (always check)
        for position in self.active_positions.values():
            if position['product_id'] == product_id:
                return False

        # Check max concurrent positions (optional)
        if check_max_positions and len(self.active_positions) >= settings.MAX_CONCURRENT_POSITIONS:
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
            # Check if trading is paused
            should_pause, reason = risk_manager.should_pause_trading()
            if should_pause:
                logger.info(f"Trading paused: {reason}")
                return False

            # Get current price
            prices = data_collector.get_current_prices()
            if product_id not in prices:
                print(f"VALIDATE: No price for {product_id}", flush=True)
                return False

            entry_price = prices[product_id]
            print(f"VALIDATE: {product_id} entry_price={entry_price}", flush=True)

            # Get volatility for stop loss calculation
            features = data_collector.get_latest_features(product_id)
            volatility = features.get('volatility', entry_price * 0.02) if features else entry_price * 0.02

            # Ensure volatility is not None for stop loss calculation
            if volatility is None or volatility <= 0:
                volatility = entry_price * 0.02
                print(f"VALIDATE: Using fallback volatility {volatility} for {product_id}", flush=True)

            # Calculate stop loss
            direction = 'long' if signal['prediction'] == 1 else 'short'
            stop_loss_price = risk_manager.calculate_stop_loss(entry_price, direction, volatility)

            print(f"VALIDATE: {product_id} direction={direction} stop_loss={stop_loss_price}", flush=True)

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
                # Check GBP buffer for GBP purchases
                if required_currency == 'GBP':
                    can_trade, reason = risk_manager.can_open_trade(required_amount, self.paper_trading)
                    if not can_trade:
                        logger.info(f"Signal rejected: {reason}")
                        return False
                else:
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
            replacement_info = signal_data.get('replaces', None)
            replacement_reason = signal_data.get('replacement_reason', '')
            
            # Get current prices for close price calculation
            current_prices = data_collector.get_current_prices()

            # Handle position replacement: close old position first
            if replacement_info:
                old_position_id = None
                old_pos = None
                for pos_id, pos in self.active_positions.items():
                    if pos.get('product_id') == replacement_info:
                        old_position_id = pos_id
                        old_pos = pos
                        break
                
                if old_position_id and old_pos:
                    logger.info(f"Closing position {old_position_id} to make room for {product_id}")
                    raw_close_price = current_prices.get(product_id)
                    close_price = float(raw_close_price) if raw_close_price else float(signal['entry_price']) if 'entry_price' in signal else None
                    if close_price is None:
                        # Fallback: use signal entry_price or current price from signal
                        features = data_collector.get_latest_features(product_id)
                        close_price = features.get('close_price', 0) if features else 0
                    old_pnl = old_pos.get('pnl', 0) if old_pos else 0
                    self._close_position(
                        old_position_id, 
                        old_pnl, 
                        f"Position replaced: {replacement_reason}",
                        close_price
                    )

            logger.info(f"Executing {signal['action']} signal for {product_id}")

            # Ensure signal has required fields (for replacements that skipped validation)
            if 'position_size' not in signal or 'entry_price' not in signal:
                print(f"VALIDATE_REPLACE: Validating replacement signal for {product_id}", flush=True)
                if not self._validate_signal(signal, product_id):
                    logger.error(f"Replacement signal validation failed for {product_id}")
                    print(f"VALIDATE_REPLACE: Validation failed for {product_id}", flush=True)
                    return None
                print(f"VALIDATE_REPLACE: Validation complete for {product_id}", flush=True)

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
                position_details = {
                    'position_id': position_id,
                    'product_id': product_id,
                    'side': side,
                    'size': size,
                    'entry_price': entry_price,
                    'stop_loss_price': signal['stop_loss_price'],
                    'take_profit_prices': signal['take_profit_prices'],
                    'signal': signal,
                    'opened_at': datetime.now(),
                    'status': 'open',
                    'replaces': replacement_info,
                    'replacement_reason': replacement_reason
                }

                self.active_positions[position_id] = position_details
                self.last_trade_time[product_id] = datetime.now()

                # Add to risk manager
                risk_manager.add_open_position(position_id, position_details)

                if replacement_info:
                    logger.info(f"Position opened (replaced {replacement_info}): {position_id} ({side} {size:.6f} {product_id})")
                else:
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
            'fees': 0.0
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
                    'fees': 0.0
                }

                db_manager.save_trade(trade_data)

                logger.info(f"Live order executed: {order_result}")
                return order_result

        except Exception as e:
            logger.error(f"Live order execution failed: {e}")
            return {'success': False, 'error': str(e)}

    def simple_test_method(self):
        """Simple test method."""
        return "test"

    def monitor_positions(self) -> List[Dict[str, Any]]:
            """
            Monitor open positions and check for exit conditions.

            Returns:
                List of positions that were closed
            """
            closed_positions = []
            
            # Explicit logging for debugging
            logger.info("=" * 60)
            logger.info("MONITOR_POSITIONS - Starting position check")
            logger.info(f"Active positions count: {len(self.active_positions)}")
            
            if not self.active_positions:
                logger.info("No active positions to monitor")
                logger.info("=" * 60)
                return closed_positions

            for position_id, position in list(self.active_positions.items()):
                try:
                    if position['status'] != 'open':
                        logger.info(f"Position {position_id} status is {position['status']}, skipping")
                        continue

                    product_id = position['product_id']
                    current_prices = data_collector.get_current_prices()

                    if product_id not in current_prices:
                        logger.warning(f"Price not found for {product_id}, skipping")
                        continue

                    current_price = current_prices[product_id]
                    entry_price = position['entry_price']
                    stop_loss = position['stop_loss_price']
                    take_profits = position['take_profit_prices']
                    position_side = position['side']
                    position_size = position['size']

                    # Log detailed position info
                    logger.info(f"Checking position {position_id}:")
                    logger.info(f"  Product: {product_id}")
                    logger.info(f"  Side: {position_side}")
                    logger.info(f"  Size: {position_size}")
                    logger.info(f"  Entry Price: {entry_price}")
                    logger.info(f"  Current Price: {current_price}")
                    logger.info(f"  Stop Loss: {stop_loss}")
                    logger.info(f"  Take Profits: {take_profits}")
                    
                    # Calculate current P&L
                    if position_side == 'buy':
                        current_pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    else:
                        current_pnl_pct = ((entry_price - current_price) / entry_price) * 100
                    logger.info(f"  Current P&L: {current_pnl_pct:.2f}%")

                    should_close = False
                    pnl = 0.0
                    exit_reason = ""

                    # Check stop loss
                    if position_side == 'buy':
                        if current_price <= stop_loss:
                            should_close = True
                            pnl = (current_price - entry_price) * position_size
                            exit_reason = "Stop loss hit"
                            logger.info(f"  STOP LOSS TRIGGERED: {current_price} <= {stop_loss}")
                    else:  # sell/short
                        if current_price >= stop_loss:
                            should_close = True
                            pnl = (entry_price - current_price) * position_size
                            exit_reason = "Stop loss hit"
                            logger.info(f"  STOP LOSS TRIGGERED: {current_price} >= {stop_loss}")

                    # Check take profit levels
                    if not should_close:
                        for i, tp_price in enumerate(take_profits):
                            if position_side == 'buy':
                                if current_price >= tp_price:
                                    should_close = True
                                    pnl = (current_price - entry_price) * position_size
                                    exit_reason = f"Take profit {i+1} hit"
                                    logger.info(f"  TAKE PROFIT {i+1} TRIGGERED: {current_price} >= {tp_price}")
                                    break
                            else:  # sell/short
                                if current_price <= tp_price:
                                    should_close = True
                                    pnl = (entry_price - current_price) * position_size
                                    exit_reason = f"Take profit {i+1} hit"
                                    logger.info(f"  TAKE PROFIT {i+1} TRIGGERED: {current_price} <= {tp_price}")
                                    break

                    # Check AI sell signal for BUY positions
                    if not should_close and position_side == 'buy':
                        try:
                            signal = ai_model.get_signal(product_id)
                            signal_action = signal.get('action', 'HOLD')
                            signal_confidence = signal.get('confidence', 0.0)
                            logger.info(f"  AI Signal: action={signal_action}, confidence={signal_confidence:.2%}")
                            
                            if signal_action == 'SELL':
                                logger.info(f"  AI SELL SIGNAL DETECTED - Closing position")
                                confidence = signal_confidence
                                should_close = True
                                pnl = (current_price - entry_price) * position_size
                                exit_reason = f"AI sell signal (confidence: {confidence:.1%})"
                            elif signal_action == 'BUY':
                                logger.info(f"  AI BUY signal - Holding position (already in buy)")
                            else:
                                logger.info(f"  AI HOLD signal - Holding position")
                        except Exception as e:
                            logger.error(f"  Error getting AI signal for {product_id}: {e}")

                    # Log decision
                    if should_close:
                        logger.info(f"  DECISION: CLOSE position (reason: {exit_reason})")
                    else:
                        logger.info(f"  DECISION: HOLD position")

                    # Close position if conditions met
                    if should_close:
                        # Verify balance before closing position
                        base_currency, quote_currency = product_id.split('-')
                        required_amount = position_size
                        
                        try:
                            balance = coinbase_api.get_account_balance(base_currency)
                            logger.info(f"  Balance check: required={required_amount:.6f} {base_currency}, available={balance:.6f}")
                            
                            if balance < required_amount:
                                logger.warning(f"  Insufficient balance to close {product_id}: need {required_amount:.6f} {base_currency}, have {balance:.6f}")
                                continue
                        except Exception as e:
                            logger.error(f"  Failed to check balance for {base_currency} before closing position: {e}")
                            continue
                        
                        logger.info(f"  EXECUTING CLOSE for {position_id}")
                        self._close_position(position_id, pnl, exit_reason, current_price)
                        closed_positions.append({
                            'position_id': position_id,
                            'pnl': pnl,
                            'exit_reason': exit_reason,
                            'exit_price': current_price
                        })

                except Exception as e:
                    logger.error(f"Error monitoring position {position_id}: {e}", exc_info=True)
                    continue
            
            logger.info(f"MONITOR_POSITIONS - Completed. Positions closed: {len(closed_positions)}")
            logger.info("=" * 60)
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
                product_id = position.get('product_id', position_id)

                # Update position record
                position['status'] = 'closed'
                position['closed_at'] = datetime.now()
                position['pnl'] = pnl
                position['exit_reason'] = reason
                position['exit_price'] = exit_price

                # Update risk manager
                risk_manager.close_position(position_id, pnl)

                # Log with replacement info
                if 'replacement' in reason.lower() or 'replaces' in reason.lower():
                    logger.info(f"Position REPLACED: {product_id} | P&L: ${pnl:.4f} | {reason}")
                else:
                    logger.info(f"Position closed: {product_id} | P&L: ${pnl:.4f} | Reason: {reason}")

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
        print("=" * 60, flush=True)
        print("TRADING_ENGINE.run_trading_cycle() - STARTING", flush=True)
        print(f"Active positions count: {len(self.active_positions)}", flush=True)
        
        cycle_results = {
            'signals_found': 0,
            'trades_executed': 0,
            'positions_closed': 0,
            'total_pnl': 0.0
        }

        try:
            # 1. Scan for signals
            print("Scanning for signals...", flush=True)
            signals = self.scan_for_signals()
            cycle_results['signals_found'] = len(signals)
            print(f"Signals found: {len(signals)}", flush=True)

            # 2. Execute valid signals
            print("Executing signals...", flush=True)
            for signal_data in signals:
                result = self.execute_signal(signal_data)
                if result:
                    cycle_results['trades_executed'] += 1
            print(f"Trades executed: {cycle_results['trades_executed']}", flush=True)

            # 3. Monitor existing positions
            print("Calling monitor_positions()...", flush=True)
            closed_positions = self.monitor_positions()
            cycle_results['positions_closed'] = len(closed_positions)
            print(f"Positions closed: {cycle_results['positions_closed']}", flush=True)

            # Calculate total P&L from closed positions
            for closed in closed_positions:
                cycle_results['total_pnl'] += closed['pnl']

            print(f"Trading cycle completed: {cycle_results}", flush=True)
            print("=" * 60, flush=True)

        except Exception as e:
            print(f"ERROR in trading cycle: {e}", flush=True)
            import traceback
            traceback.print_exc()
            logger.error(f"Error in trading cycle: {e}")

        return cycle_results


# Global trading engine instance
trading_engine = TradingEngine()