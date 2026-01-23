"""
Risk Management module for crypto trading bot.

This module implements comprehensive risk management including:
- Position sizing based on confidence and volatility
- Stop-loss and take-profit calculations
- Daily loss limits and drawdown protection
- Portfolio risk monitoring

Educational Notes:
- Risk management is more important than trading strategy
- Position sizing determines survival during losing streaks
- Stop losses protect capital, take profits lock in gains
- Risk limits prevent emotional decision-making
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np

from config.settings import settings
from src.database import db_manager
from src.coinbase_api import coinbase_api
from src.data_collector import data_collector

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Risk Management class for position sizing and capital protection.

    This class ensures the bot trades safely by:
    - Calculating appropriate position sizes
    - Setting stop losses and take profits
    - Monitoring daily/weekly loss limits
    - Preventing over-leveraging
    """

    def __init__(self):
        """Initialize the risk manager."""
        self.portfolio_value = 0.0
        self.daily_pnl = 0.0
        self.open_positions = {}  # Track open positions
        self.daily_start_time = datetime.now().date()  # Initialize daily start time
        self.daily_start_time_set = True  # Track initialization
        # Portfolio value will be updated when needed with trading mode parameter

    def _update_portfolio_value(self, is_paper_trading: bool = True):
        """
        Update the current portfolio value.

        Args:
            is_paper_trading: Whether bot is in paper trading mode
        """
        try:
            if is_paper_trading:
                # Paper trading: use simulated portfolio value
                self.portfolio_value = settings.PAPER_TRADING_PORTFOLIO_VALUE
                logger.info(f"Paper trading mode - using simulated portfolio: ${self.portfolio_value:.2f}")
            else:
                # Live trading: use real Coinbase balances
                accounts = coinbase_api.get_accounts()

                total_value = 0.0
                prices = data_collector.get_current_prices()

                for account in accounts:
                    currency = account['currency']
                    balance = account['available']

                    if currency == 'USD':
                        total_value += balance
                    elif currency in ['BTC', 'ETH', 'SOL', 'LTC', 'XRP']:
                        symbol = f"{currency}-USD"
                        if symbol in prices:
                            total_value += balance * prices[symbol]

                self.portfolio_value = total_value
                logger.info(f"Live trading mode - using real portfolio: ${self.portfolio_value:.2f}")

        except Exception as e:
            logger.error(f"Failed to update portfolio value: {e}")
            # Fallback to paper trading value if update fails
            if self.portfolio_value == 0.0:
                self.portfolio_value = settings.PAPER_TRADING_PORTFOLIO_VALUE
                logger.info(f"Using fallback portfolio value: ${self.portfolio_value:.2f}")

    def calculate_position_size(self, product_id: str, confidence: float,
                              entry_price: float, stop_loss_price: float) -> Dict[str, Any]:
        """
        Calculate the appropriate position size for a trade.

        Uses Kelly Criterion and risk management principles to determine
        how much capital to allocate to this trade.

        Args:
            product_id: Trading pair (e.g., 'BTC-USD')
            confidence: AI model confidence (0-1)
            entry_price: Expected entry price
            stop_loss_price: Stop loss price

        Returns:
            Dictionary with position sizing details
        """
        try:
            # Update portfolio value
            self._update_portfolio_value()

            if self.portfolio_value <= 0:
                return {
                    'size': 0.0,
                    'reason': 'No portfolio value available',
                    'risk_amount': 0.0
                }

            # Calculate risk per trade (percentage of portfolio)
            base_risk_pct = settings.MAX_POSITION_SIZE  # 2.5%

            # Adjust risk based on confidence
            # Higher confidence = higher risk allocation
            confidence_multiplier = min(confidence * 2.0, 1.5)  # Max 1.5x multiplier
            adjusted_risk_pct = base_risk_pct * confidence_multiplier

            # Calculate dollar risk amount
            risk_amount = self.portfolio_value * adjusted_risk_pct

            # Calculate position size based on stop loss distance
            # For long positions: stop loss should be below entry price
            # For short positions: stop loss should be above entry price
            price_risk = abs(entry_price - stop_loss_price)

            if price_risk == 0:
                return {
                    'size': 0.0,
                    'reason': 'Stop loss too close to entry price',
                    'risk_amount': 0.0
                }

            # Risk = Position Size * |Entry - Stop Loss|
            # Position Size = Risk / |Entry - Stop Loss|
            position_size_usd = risk_amount / price_risk

            # Convert USD size to crypto amount
            base_currency, quote_currency = product_id.split('-')
            if quote_currency == 'USD':
                # Standard USD pair (e.g., BTC-USD)
                crypto_amount = position_size_usd / entry_price
            else:
                # Crypto pair (e.g., BTC-ETH): get USD price of base currency
                usd_product_id = f"{base_currency}-USD"
                usd_prices = data_collector.get_current_prices()
                usd_price = usd_prices.get(usd_product_id)
                if usd_price and usd_price > 0:
                    crypto_amount = position_size_usd / usd_price
                else:
                    return {
                        'size': 0.0,
                        'reason': f'No USD price available for {base_currency}',
                        'risk_amount': 0.0
                    }

            # Apply maximum limits
            max_size = self._get_max_position_size(product_id, entry_price)
            final_size = min(crypto_amount, max_size)

            # Check daily loss limits
            if not self._check_daily_limits(risk_amount):
                return {
                    'size': 0.0,
                    'reason': 'Daily loss limit would be exceeded',
                    'risk_amount': risk_amount
                }

            return {
                'size': final_size,
                'risk_amount': risk_amount,
                'risk_percentage': adjusted_risk_pct,
                'confidence_multiplier': confidence_multiplier,
                'max_allowed_size': max_size,
                'reason': 'Position size calculated successfully'
            }

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return {
                'size': 0.0,
                'reason': f'Calculation error: {str(e)}',
                'risk_amount': 0.0
            }

    def _get_max_position_size(self, product_id: str, entry_price: float) -> float:
        """
        Get the maximum allowed position size for safety limits.

        Args:
            product_id: Trading pair
            entry_price: Current price

        Returns:
            Maximum position size in crypto units
        """
        # Set maximum position sizes based on asset
        max_sizes = {
            'BTC-USD': 0.01,  # Max 0.01 BTC (~$500 at $50k)
            'ETH-USD': 0.1,   # Max 0.1 ETH (~$300 at $3k)
        }

        base_max = max_sizes.get(product_id, 0.001)  # Default small size

        # Reduce max size if portfolio is small
        if self.portfolio_value < 1000:
            base_max *= 0.5  # 50% reduction for small portfolios
        elif self.portfolio_value < 5000:
            base_max *= 0.75  # 25% reduction

        return base_max

    def _check_daily_limits(self, risk_amount: float) -> bool:
        """
        Check if we can take this trade based on daily P&L.

        Args:
            risk_amount: Dollar amount being risked

        Returns:
            True if trade is allowed
        """
        # Reset daily P&L if it's a new day
        current_date = datetime.now().date()
        if current_date != self.daily_start_time:
            self.daily_start_time = current_date
            self.daily_pnl = 0.0
            logger.info("Daily P&L reset for new trading day")

        # Check if we've already exceeded daily loss limit from realized trades
        max_daily_loss = self.portfolio_value * settings.MAX_DAILY_LOSS if self.portfolio_value > 0 else 0

        # Ensure daily_start_time is set with fallback
        if not hasattr(self, 'daily_start_time') or self.daily_start_time is None:
            self.daily_start_time = datetime.now().date()

        if self.daily_pnl < -max_daily_loss:
            logger.warning(f"Daily loss limit exceeded: ${abs(self.daily_pnl):.2f} < -${max_daily_loss:.2f}")
            return False

        # Position sizing already limits risk per trade
        # Daily limit only checks realized P&L from closed trades
        return True

    def calculate_stop_loss(self, entry_price: float, direction: str,
                           volatility: float = None) -> float:
        """
        Calculate appropriate stop loss price.

        Args:
            entry_price: Entry price
            direction: 'long' or 'short'
            volatility: Price volatility (optional)

        Returns:
            Stop loss price
        """
        # Use ATR-based stop loss or fixed percentage
        atr_multiplier = settings.STOP_LOSS_ATR_MULTIPLIER

        if volatility and volatility > 0:
            # ATR-based stop loss
            stop_distance = volatility * atr_multiplier
        else:
            # Fixed percentage stop loss (fallback)
            stop_distance = entry_price * 0.02  # 2% stop loss

        if direction.lower() == 'long':
            stop_price = entry_price - stop_distance
        else:  # short
            stop_price = entry_price + stop_distance

        # Ensure minimum stop distance
        min_stop_pct = 0.005  # 0.5% minimum
        min_stop_distance = entry_price * min_stop_pct

        if abs(entry_price - stop_price) < min_stop_distance:
            if direction.lower() == 'long':
                stop_price = entry_price - min_stop_distance
            else:
                stop_price = entry_price + min_stop_distance

        return stop_price

    def calculate_take_profits(self, entry_price: float, stop_price: float,
                              direction: str) -> List[float]:
        """
        Calculate take profit levels.

        Args:
            entry_price: Entry price
            stop_price: Stop loss price
            direction: 'long' or 'short'

        Returns:
            List of take profit prices
        """
        risk_amount = abs(entry_price - stop_price)

        take_profit_levels = []
        for ratio in settings.TAKE_PROFIT_LEVELS:
            profit_distance = risk_amount * ratio

            if direction.lower() == 'long':
                tp_price = entry_price + profit_distance
            else:  # short
                tp_price = entry_price - profit_distance

            take_profit_levels.append(tp_price)

        return take_profit_levels

    def update_daily_pnl(self, pnl_change: float):
        """
        Update the daily P&L tracking.

        Args:
            pnl_change: Profit/loss change in dollars
        """
        self.daily_pnl += pnl_change
        logger.debug(f"Daily P&L updated: ${self.daily_pnl:.2f}")

    def check_portfolio_risk(self, is_paper_trading: bool = True) -> Dict[str, Any]:
        """
        Check overall portfolio risk metrics.

        Args:
            is_paper_trading: Whether bot is in paper trading mode

        Returns:
            Dictionary with risk assessment
        """
        # Update portfolio value
        self._update_portfolio_value(is_paper_trading)

        # Get performance summary
        perf_summary = db_manager.get_performance_summary(days=30)

        risk_assessment = {
            'portfolio_value': self.portfolio_value,
            'daily_pnl': self.daily_pnl,
            'daily_pnl_pct': (self.daily_pnl / self.portfolio_value) if self.portfolio_value > 0 else 0,
            'open_positions': len(self.open_positions),
            'monthly_performance': perf_summary,
            'risk_status': 'normal'
        }

        # Assess risk status
        # Only set high_risk if we have trades and win rate is low
        total_trades = perf_summary.get('total_trades', 0)
        if total_trades > 0 and perf_summary.get('win_rate', 0) < 0.3:
            risk_assessment['risk_status'] = 'high_risk'
        elif self.daily_pnl < -self.portfolio_value * 0.05:  # 5% daily loss
            risk_assessment['risk_status'] = 'daily_loss_limit'
        elif len(self.open_positions) >= settings.MAX_CONCURRENT_POSITIONS:
            risk_assessment['risk_status'] = 'max_positions'

        return risk_assessment

    def should_pause_trading(self) -> Tuple[bool, str]:
        """
        Check if trading should be paused due to risk limits.

        Returns:
            Tuple of (should_pause, reason)
        """
        risk_check = self.check_portfolio_risk()

        if risk_check['risk_status'] == 'daily_loss_limit':
            return True, "Daily loss limit exceeded"

        if risk_check['risk_status'] == 'max_positions':
            return True, "Maximum concurrent positions reached"

        if settings.EMERGENCY_STOP:
            return True, "Emergency stop activated"

        # Check for high volatility (placeholder)
        # In production, this would check current market volatility

        return False, "Trading allowed"

    def add_open_position(self, position_id: str, details: Dict[str, Any]):
        """
        Track a new open position.

        Args:
            position_id: Unique position identifier
            details: Position details (size, entry price, etc.)
        """
        self.open_positions[position_id] = {
            'details': details,
            'opened_at': datetime.now(),
            'status': 'open'
        }
        logger.info(f"Added open position: {position_id}")

    def close_position(self, position_id: str, pnl: float):
        """
        Close a position and update P&L.

        Args:
            position_id: Position identifier
            pnl: Profit/loss from the position
        """
        if position_id in self.open_positions:
            self.open_positions[position_id]['status'] = 'closed'
            self.open_positions[position_id]['closed_at'] = datetime.now()
            self.open_positions[position_id]['pnl'] = pnl

            # Update daily P&L
            self.update_daily_pnl(pnl)

            logger.info(f"Closed position {position_id}: P&L ${pnl:.2f}")
        else:
            logger.warning(f"Position {position_id} not found for closing")


# Global risk manager instance
risk_manager = RiskManager()