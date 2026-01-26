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

        # Check if we already have a position in this product
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
                    'status': 'open'
                }

                self.active_positions[position_id] = position_details
                self.last_trade_time[product_id] = datetime.now()

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
                    'order_id': order_result['order_id'],
                    'product_id': product_id,
                    'side': side,
                    'size': order_result['size'],
                    'price': order_result['price'],
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

            for position_id, position in list(self.active_positions.items()):
                try:
                    if position['status'] != 'open':
                        continue

                    product_id = position['product_id']
                    current_prices = data_collector.get_current_prices()

                    if product_id not in current_prices:
                        continue

                    current_price = current_prices[product_id]
                    entry_price = position['entry_price']
                    stop_loss = position['stop_loss_price']
                    take_profits = position['take_profit_prices']

                    should_close = False
                    pnl = 0.0
                    exit_reason = ""

                    # Check stop loss
                    if position['side'] == 'buy':
                        if current_price <= stop_loss:
                            should_close = True
                            pnl = (current_price - entry_price) * position['size']
                            exit_reason = "Stop loss hit"
                    else:  # sell/short
                        if current_price >= stop_loss:
                            should_close = True
                            pnl = (entry_price - current_price) * position['size']
                            exit_reason = "Stop loss hit"

                    # Check take profit levels
                    if not should_close:
                        for i, tp_price in enumerate(take_profits):
                            if position['side'] == 'buy':
                                if current_price >= tp_price:
                                    should_close = True
                                    pnl = (current_price - entry_price) * position['size']
                                    exit_reason = f"Take profit {i+1} hit"
                                    break
                            else:  # sell/short
                                if current_price <= tp_price:
                                    should_close = True
                                    pnl = (entry_price - current_price) * position['size']
                                    exit_reason = f"Take profit {i+1} hit"
                                    break

                    # Close position if conditions met
                    if should_close:
                        self._close_position(position_id, pnl, exit_reason, current_price)
                        closed_positions.append({
                            'position_id': position_id,
                            'pnl': pnl,
                            'exit_reason': exit_reason,
                            'exit_price': current_price
                        })

                except Exception as e:
                    logger.error(f"Error monitoring position {position_id}: {e}")
                    continue

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

                # Update position record
                position['status'] = 'closed'
                position['closed_at'] = datetime.now()
                position['pnl'] = pnl
                position['exit_reason'] = reason
                position['exit_price'] = exit_price

                # Update risk manager
                risk_manager.close_position(position_id, pnl)

                logger.info(f"Position closed: {position_id} | P&L: ${pnl:.2f} | Reason: {reason}")

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

            logger.info(f"Trading cycle completed: {cycle_results}")

        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")

        return cycle_results


# Global trading engine instance
trading_engine = TradingEngine()