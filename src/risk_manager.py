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
from src.currency_utils import currency_converter

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
        self.daily_start_time = datetime.now().date()
        self.daily_start_time_set = True

        loaded_positions = db_manager.load_open_positions()
        self.open_positions = loaded_positions
        logger.info(f"Risk Manager initialized - loaded {len(self.open_positions)} open positions from database")

        # Cache for dashboard optimization
        self._risk_cache = None
        self._risk_cache_time = None
        self._risk_cache_ttl = 60  # Cache risk data for 60 seconds

        # Wallet snapshot tracking
        self._wallet_snapshot_logged = False
        self._last_gbp_balance = 0.0
        self._wallet_check_interval = 21600  # 6 hours
        self._last_wallet_check = None

        # Log initial wallet snapshot
        self._log_wallet_snapshot()

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
                    elif currency == 'GBP':
                        # Convert GBP to USD using actual exchange rate
                        gbp_usd_rate = currency_converter.get_exchange_rate('GBP', 'USD')
                        if gbp_usd_rate is None:
                            gbp_usd_rate = 1.0  # Fallback
                        total_value += balance * gbp_usd_rate
                    elif currency in ['BTC', 'ETH', 'SOL', 'LTC', 'XRP', 'DOT', 'ADA', 'LINK', 'UNI']:
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

    def get_min_trade_amount(self, product_id: str, entry_price: float) -> float:
        """
        Get the minimum trade amount based on the crypto's price tier.
        
        High-value crypto (BTC) can trade smaller amounts than low-value crypto.
        
        Args:
            product_id: Trading pair (e.g., 'BTC-GBP')
            entry_price: Current price
            
        Returns:
            Minimum trade amount for this crypto
        """
        if entry_price <= 0:
            return settings.MIN_TRADE_AMOUNT
        
        # Determine tier based on price
        if entry_price >= settings.PRICE_TIER_HIGH:
            # BTC and similar high-value
            return settings.MIN_TRADE_AMOUNT_HIGH
        elif entry_price >= settings.PRICE_TIER_MID_HIGH:
            # ETH and similar
            return settings.MIN_TRADE_AMOUNT_MID_HIGH
        elif entry_price >= settings.PRICE_TIER_MID:
            # LINK, SOL, etc
            return settings.MIN_TRADE_AMOUNT_MID
        else:
            # DOT, ADA, LTC, etc
            return settings.MIN_TRADE_AMOUNT_LOW

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
            # Get current trading mode from database
            from src.database import db_manager
            is_paper = db_manager.get_paper_trading()
            
            # Update portfolio value with correct mode
            self._update_portfolio_value(is_paper_trading=is_paper)

            if self.portfolio_value <= 0:
                return {
                    'size': 0.0,
                    'reason': 'No portfolio value available',
                    'risk_amount': 0.0
                }

            # Check GBP availability for BUY signals
            base_currency, quote_currency = product_id.split('-')
            if not is_paper and quote_currency == 'GBP':
                gbp_balance = self.get_gbp_balance()
                available_gbp = gbp_balance - settings.GBP_BUFFER
                if available_gbp <= 0:
                    logger.warning(f"GBP balance too low for trade: £{gbp_balance:.2f} available after £{settings.GBP_BUFFER} buffer")
                    return {
                        'size': 0.0,
                        'reason': f'GBP balance too low (£{gbp_balance:.2f})',
                        'risk_amount': 0.0
                    }
                # Cap risk amount based on available GBP
                max_risk = available_gbp * 0.5  # Max 50% of available GBP

            # Calculate risk per trade (percentage of portfolio)
            base_risk_pct = settings.MAX_POSITION_SIZE  # 2.5%

            # Adjust risk based on confidence
            # Higher confidence = higher risk allocation
            confidence_multiplier = min(confidence * 2.0, 1.5)  # Max 1.5x multiplier
            adjusted_risk_pct = base_risk_pct * confidence_multiplier

            # Calculate dollar risk amount
            risk_amount = self.portfolio_value * adjusted_risk_pct
            
            # Cap risk amount to available GBP for live trading
            if not is_paper and quote_currency == 'GBP' and risk_amount > max_risk:
                logger.info(f"Capping risk amount from £{risk_amount:.2f} to £{max_risk:.2f} based on available GBP")
                risk_amount = max_risk
            
            # DEBUG: Log the calculation
            print(f"POSITION_SIZING: portfolio={self.portfolio_value:.2f}, base_risk={base_risk_pct:.4f}, conf_mult={confidence_multiplier:.2f}, adj_risk={adjusted_risk_pct:.4f}, risk_amount={risk_amount:.2f}", flush=True)
            logger.info(f"Position sizing: portfolio={self.portfolio_value:.2f}, base_risk={base_risk_pct:.4f}, conf_mult={confidence_multiplier:.2f}, adj_risk={adjusted_risk_pct:.4f}, risk_amount={risk_amount:.2f}")

            # v2.1: Use fixed TARGET_VALUE for consistent position sizing
            # All trades target the same GBP value regardless of crypto price
            TARGET_TRADE_VALUE = 15.0  # Target £15 per trade
            
            # Determine quote currency and calculate in correct currency
            base_currency, quote_currency = product_id.split('-')
            
            if quote_currency == 'GBP':
                # GBP pair: use fixed target value
                # Position Size = Target Value / Entry Price
                crypto_amount = TARGET_TRADE_VALUE / entry_price
                actual_gbp_value = crypto_amount * entry_price
                logger.info(f"GBP pair {product_id}: target=£{TARGET_TRADE_VALUE}, price={entry_price:.2f}, crypto={crypto_amount:.8f}")
                return {
                    'size': crypto_amount,
                    'reason': f'Target £{TARGET_TRADE_VALUE} position',
                    'risk_amount': TARGET_TRADE_VALUE,
                    'gbp_value': actual_gbp_value
                }
            elif quote_currency == 'USD':
                # Standard USD pair (e.g., BTC-USD)
                position_size_usd = risk_amount / price_risk
                crypto_amount = position_size_usd / entry_price
            else:
                # Crypto pair (e.g., BTC-ETH): get USD price of base currency
                usd_product_id = f"{base_currency}-USD"
                usd_prices = data_collector.get_current_prices()
                usd_price = usd_prices.get(usd_product_id)
                
                if usd_price and usd_price > 0:
                    position_size_usd = risk_amount / price_risk
                    crypto_amount = position_size_usd / usd_price
                    logger.info(f"Position sizing {base_currency}: position_size_usd={position_size_usd:.2f}, usd_price={usd_price:.2f}, crypto_amount={crypto_amount:.8f}")
                    logger.debug(f"Using USD price for {base_currency}: ${usd_price:.6f} → {crypto_amount:.8f} {base_currency}")
                else:
                    # ENHANCED: Try fallback using existing trading pair prices
                    logger.warning(f"USD price not available for {base_currency}, attempting fallback calculation")
                    
                    # Fallback 1: If we have BTC-quoted pair, derive USD price
                    btc_usd_price = usd_prices.get('BTC-USD')
                    current_pair_price = usd_prices.get(product_id)
                    
                    if btc_usd_price and current_pair_price:
                        if f"{base_currency}-BTC" in usd_prices:
                            # Calculate implied USD price from BTC pair
                            implied_usd_price = current_pair_price * btc_usd_price
                            position_size_usd = risk_amount / price_risk
                            crypto_amount = position_size_usd / implied_usd_price
                            logger.info(f"Fallback: Using implied USD price for {base_currency}: ${implied_usd_price:.6f}")
                        else:
                            # Fallback 2: Use portfolio value percentage estimate
                            logger.warning(f"Using fallback position sizing for {base_currency}")
                            # Use minimum position size as conservative fallback
                            crypto_amount = settings.MIN_TRADE_AMOUNT / entry_price if entry_price > 0 else 0.001
                            return {
                                'size': crypto_amount,
                                'reason': f'Using fallback sizing for {base_currency} (no USD price)',
                                'risk_amount': risk_amount,
                                'fallback_used': True
                            }
                    else:
                        return {
                            'size': 0.0,
                            'reason': f'No USD price available for {base_currency} and no fallback possible',
                            'risk_amount': 0.0
                        }

            # Apply maximum limits
            max_size = self._get_max_position_size(product_id, entry_price)
            final_size = min(crypto_amount, max_size)

            # Universal minimum: ensure at least £5 position value
            # If risk-based size is too small, increase risk percentage
            min_gbp_value = 5.0  # £5 minimum
            gbp_value = final_size * entry_price
            if gbp_value < min_gbp_value and gbp_value > 0:
                min_size = min_gbp_value / entry_price
                if min_size <= max_size:
                    # Can meet £5 minimum within risk limits
                    logger.info(f"{product_id}: increasing size from {final_size:.8f} (£{gbp_value:.2f}) to minimum £{min_gbp_value} ({min_size:.8f})")
                    final_size = min_size
                else:
                    # Position below £5 minimum but max_size is too small
                    # Use max_size directly - do NOT recalculate with stop_loss_pct
                    logger.info(f"{product_id}: cannot meet £5 min - using max_size {max_size:.8f} (£{max_size * entry_price:.2f})")
                    final_size = max_size

            # NEW: Cap position size based on available GBP balance
            try:
                gbp_balance = coinbase_api.get_account_balance('GBP')
                gbp_buffer = settings.GBP_BUFFER  # Keep £2 buffer
                available_gbp = max(0, gbp_balance - gbp_buffer)
                
                # Calculate position value in GBP
                position_gbp_value = final_size * entry_price
                
                if position_gbp_value > available_gbp:
                    # Cap the position size to available GBP
                    max_gbp_value = available_gbp * 0.95  # Use 95% of available to leave margin
                    if max_gbp_value >= 1.0:  # Only cap if at least £1 available
                        capped_size = max_gbp_value / entry_price
                        logger.info(f"{product_id}: capping position size from {final_size:.8f} (£{position_gbp_value:.2f}) to {capped_size:.8f} (£{max_gbp_value:.2f}) - available GBP: {available_gbp:.2f}")
                        final_size = capped_size
                    else:
                        logger.warning(f"{product_id}: insufficient GBP balance ({available_gbp:.2f}) for minimum position")
                        return {
                            'size': 0.0,
                            'reason': f'Insufficient GBP balance ({available_gbp:.2f})',
                            'risk_amount': risk_amount
                        }
            except Exception as e:
                logger.warning(f"Could not check GBP balance for position sizing: {e}")

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
        Get the maximum allowed position size based on portfolio percentage.

        Args:
            product_id: Trading pair
            entry_price: Current price

        Returns:
            Maximum position size in crypto units
        """
        if entry_price <= 0:
            return settings.MIN_TRADE_AMOUNT
        
        # Use portfolio_value consistently for both paper and live trading
        # portfolio_value is already set correctly based on mode in _update_portfolio_value()
        if self.portfolio_value > 0:
            portfolio_value = self.portfolio_value
        else:
            portfolio_value = settings.PAPER_TRADING_PORTFOLIO_VALUE
        
        # Calculate max based on portfolio percentage (MAX_POSITION_SIZE)
        max_value = portfolio_value * settings.MAX_POSITION_SIZE
        max_size = max_value / entry_price
        
        # Ensure it's at least the minimum trade amount based on price tier
        tiered_min = self.get_min_trade_amount(product_id, entry_price)
        max_size = max(max_size, tiered_min)
        
        return max_size

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
                           volatility: Optional[float] = None) -> float:
        """
        Calculate appropriate stop loss price.

        Args:
            entry_price: Entry price
            direction: 'long' or 'short'
            volatility: Price volatility (optional)

        Returns:
            Stop loss price
        """
        # Use fixed 10% stop loss (no ATR complexity)
        STOP_LOSS_PERCENT = 0.10  # 10% stop loss

        stop_distance = entry_price * STOP_LOSS_PERCENT

        if direction.lower() == 'long':
            stop_price = entry_price - stop_distance
        else:  # short
            stop_price = entry_price + stop_distance

        return stop_price

    def calculate_take_profits(self, entry_price: float, stop_price: float,
                              direction: str, regime: str = 'neutral') -> List[float]:
        """
        Calculate take profit levels, adjusted by market regime.

        Args:
            entry_price: Entry price
            stop_price: Stop loss price
            direction: 'long' or 'short'
            regime: 'uptrend', 'downtrend', or 'neutral'

        Returns:
            List of take profit prices
        """
        regime_multipliers = {
            'uptrend': [8.0, 12.0, 16.0],
            'neutral': [5.0, 7.5, 10.0],
            'downtrend': [2.0, 4.0, 6.0]
        }
        
        levels = regime_multipliers.get(regime, [2.0, 3.0, 4.0])
        
        take_profit_levels = []
        for pct in levels:
            profit_amount = entry_price * (pct / 100)

            if direction.lower() == 'long':
                tp_price = entry_price + profit_amount
            else:  # short
                tp_price = entry_price - profit_amount

            take_profit_levels.append(tp_price)

        logger.debug(f"Take profits for {regime} regime: {take_profit_levels}")
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
        # Refresh positions from database to get accurate count
        self.open_positions = db_manager.load_open_positions()

        # Update portfolio value
        self._update_portfolio_value(is_paper_trading)

        # Get performance summary
        perf_summary = db_manager.get_performance_summary(days=30)

        # Check GBP balance for alerts
        gbp_balance = 0.0
        try:
            # Get GBP balance from coinbase (use available balance like debug endpoint)
            accounts = coinbase_api.get_accounts()
            for account in accounts:
                if account.get('currency') == 'GBP':
                    gbp_balance = float(account.get('available', account.get('balance', 0)))
                    logger.debug(f"Found GBP balance: {gbp_balance} from available_balance")
                    break
        except Exception as e:
            logger.warning(f"Failed to get GBP balance for monitoring: {e}")
        
        # Determine GBP status
        gbp_status = 'normal'
        if gbp_balance < settings.GBP_CRITICAL_THRESHOLD:
            gbp_status = 'critical'
        elif gbp_balance < settings.GBP_WARNING_THRESHOLD:
            gbp_status = 'warning'
            
        risk_assessment = {
            'portfolio_value': self.portfolio_value,
            'daily_pnl': self.daily_pnl,
            'daily_pnl_pct': (self.daily_pnl / self.portfolio_value) if self.portfolio_value > 0 else 0,
            'open_positions': len(self.open_positions),
            'monthly_performance': perf_summary,
            'risk_status': 'normal',
            'gbp_balance': gbp_balance,
            'gbp_status': gbp_status,
            'gbp_warning_threshold': settings.GBP_WARNING_THRESHOLD,
            'gbp_critical_threshold': settings.GBP_CRITICAL_THRESHOLD
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

    def check_portfolio_risk_cached(self, is_paper_trading: bool = True) -> Dict[str, Any]:
        """
        Check portfolio risk with caching for dashboard optimization.
        Returns cached data if within TTL, otherwise computes fresh data.
        
        Args:
            is_paper_trading: Whether bot is in paper trading mode
            
        Returns:
            Dictionary with risk assessment
        """
        now = datetime.now()
        if (self._risk_cache is not None and 
            self._risk_cache_time is not None and 
            (now - self._risk_cache_time).total_seconds() < self._risk_cache_ttl):
            logger.debug(f"Using cached risk data (age: {(now - self._risk_cache_time).total_seconds():.1f}s)")
            return self._risk_cache
        
        # Cache miss or expired - compute fresh data
        fresh_data = self.check_portfolio_risk(is_paper_trading)
        self._risk_cache = fresh_data
        self._risk_cache_time = now
        return fresh_data

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

    def get_gbp_balance(self) -> float:
        """
        Get current GBP balance from Coinbase.
        
        Returns:
            GBP balance available for trading
        """
        try:
            accounts = coinbase_api.get_accounts()
            logger.debug(f"Checking {len(accounts)} accounts for GBP balance")
            for i, account in enumerate(accounts):
                currency = account.get('currency')
                if currency == 'GBP':
                    # Fix: Use 'available' field instead of 'available_balance' (which doesn't exist)
                    available = account.get('available')
                    balance = account.get('balance')
                    
                    logger.debug(f"GBP account found: available={available}, balance={balance}")
                    
                    # Use available balance if exists, otherwise fallback to total balance
                    if available is not None and float(available) > 0:
                        gbp_balance = float(available)
                        logger.info(f"Using GBP available balance: £{gbp_balance}")
                        return gbp_balance
                    elif balance is not None:
                        gbp_balance = float(balance)
                        logger.info(f"Using GBP total balance: £{gbp_balance}")
                        return gbp_balance
                    else:
                        logger.warning("GBP account found but both available and balance are None")
                        return 0.0
            
            logger.warning("No GBP account found in Coinbase accounts")
            return 0.0
        except Exception as e:
            logger.error(f"Failed to get GBP balance: {e}")
            return 0.0

    def can_open_trade(self, required_gbp: float, is_paper_trading: bool = True) -> Tuple[bool, str]:
        """
        Check if a trade can be opened while maintaining GBP buffer.
        
        Args:
            required_gbp: GBP amount required for the trade
            is_paper_trading: Whether bot is in paper trading mode
            
        Returns:
            Tuple of (can_trade, reason)
        """
        if is_paper_trading:
            # Paper trading: simulate with buffer
            available = settings.PAPER_TRADING_PORTFOLIO_VALUE - settings.GBP_BUFFER
            if available >= required_gbp:
                return True, "Paper trading: sufficient simulated balance"
            return False, f"Paper trading: insufficient balance (need £{required_gbp:.2f})"
        
        # Live trading: check real GBP balance
        current_gbp = self.get_gbp_balance()
        available = current_gbp - settings.GBP_BUFFER
        
        if available < 0:
            logger.warning(f"GBP balance below buffer ({settings.GBP_BUFFER}): {current_gbp}")
            return False, f"GBP balance critical ({current_gbp:.2f}), below buffer of £{settings.GBP_BUFFER}"
        
        if available < required_gbp:
            logger.warning(f"Insufficient GBP: have {current_gbp:.2f}, need {required_gbp:.2f}, buffer £{settings.GBP_BUFFER}")
            return False, f"Insufficient GBP: have {current_gbp:.2f}, need {required_gbp:.2f}"
        
        logger.info(f"Trade allowed: £{required_gbp:.2f} from £{current_gbp:.2f} (buffer: £{settings.GBP_BUFFER})")
        return True, f"Sufficient GBP: {current_gbp:.2f} available after £{settings.GBP_BUFFER} buffer"

    def add_open_position(self, product_id: str, details: Dict[str, Any]):
        """
        Track a new open position.

        Args:
            product_id: Product identifier (e.g., BTC-GBP)
            details: Position details (size, entry price, etc.)
        """
        self.open_positions[product_id] = {
            'details': details,
            'opened_at': datetime.now(),
            'status': 'open'
        }
        logger.info(f"Added open position: {product_id}")

    def close_position(self, product_id: str, pnl: float):
        """
        Close a position and update P&L.

        Args:
            product_id: Product identifier
            pnl: Profit/loss from the position
        """
        if product_id in self.open_positions:
            self.open_positions[product_id]['status'] = 'closed'
            self.open_positions[product_id]['closed_at'] = datetime.now()
            self.open_positions[product_id]['pnl'] = pnl

            # Update daily P&L
            self.update_daily_pnl(pnl)

            logger.info(f"Closed position {product_id}: P&L £{pnl:.2f}")
        else:
            logger.warning(f"Position {product_id} not found for closing")

    def check_position_drift(self) -> Dict[str, Any]:
        """
        Check for position drift between bot records and Coinbase.
        
        Returns:
            Dict with drift analysis including any discrepancies found.
        """
        drift_report = {
            'checked_at': datetime.now(),
            'positions': [],
            'has_drift': False,
            'total_drift_value': 0.0,
            'recommendations': []
        }
        
        try:
            current_prices = data_collector.get_current_prices()
            positions = db_manager.load_open_positions()
            
            for product_id in settings.PRODUCT_IDS:
                currency = product_id.split('-')[0]
                actual_balance = coinbase_api.get_account_balance(currency)
                
                pos = positions.get(product_id, {})
                db_remaining = pos.get('remaining_size', pos.get('size', 0))
                current_price = current_prices.get(product_id, 0)
                
                drift_amount = actual_balance - db_remaining
                drift_value = abs(drift_amount) * current_price if current_price > 0 else 0
                drift_pct = (abs(drift_amount) / db_remaining * 100) if db_remaining > 0 else 0
                
                position_drift = {
                    'product_id': product_id,
                    'actual_balance': actual_balance,
                    'db_remaining': db_remaining,
                    'drift_amount': drift_amount,
                    'drift_value': drift_value,
                    'drift_pct': drift_pct,
                    'has_issue': abs(drift_amount) > 0.00000001  # More than dust
                }
                
                if position_drift['has_issue']:
                    drift_report['has_drift'] = True
                    drift_report['total_drift_value'] += drift_value
                    drift_report['recommendations'].append(
                        f"Fix {product_id}: set remaining_size to {actual_balance:.8f}"
                    )
                    logger.warning(
                        f"DRIFT DETECTED: {product_id} - Coinbase: {actual_balance:.8f}, "
                        f"DB: {db_remaining:.8f}, Diff: {drift_amount:+.8f} (£{drift_value:.2f})"
                    )
                
                drift_report['positions'].append(position_drift)
            
            if drift_report['has_drift']:
                logger.warning(
                    f"Position drift detected! Total drift value: £{drift_report['total_drift_value']:.2f}"
                )
            else:
                logger.info("Position drift check: All positions in sync with Coinbase")
                
        except Exception as e:
            logger.error(f"Error checking position drift: {e}")
            drift_report['error'] = str(e)
        
        return drift_report
    
    def auto_sync_drift(self) -> Dict[str, Any]:
        """
        Automatically sync positions with Coinbase if drift detected.
        
        Only syncs if drift is significant (> £0.50 value).
        """
        sync_report = {
            'synced': False,
            'positions_fixed': 0,
            'errors': []
        }
        
        drift_report = self.check_position_drift()
        
        if not drift_report.get('has_drift', True):
            logger.info("No drift detected - no sync needed")
            return sync_report
        
        for pos_drift in drift_report.get('positions', []):
            if not pos_drift.get('has_issue', False):
                continue
            
            product_id = pos_drift['product_id']
            actual_balance = pos_drift['actual_balance']
            drift_value = pos_drift.get('drift_value', 0)
            
            if drift_value < 0.50:
                logger.info(f"Skipping {product_id} - drift £{drift_value:.2f} below threshold")
                continue
            
            try:
                # Load existing position to get current side
                existing_positions = db_manager.load_open_positions(trade_type='live')
                existing_pos = existing_positions.get(product_id)
                existing_side = existing_pos.get('side', 'buy') if existing_pos else 'buy'
                
                update_data = {
                    'product_id': product_id,
                    'side': existing_side,
                    'remaining_size': actual_balance,
                    'scale_in_count': 0,
                    'scale_in_levels_triggered': '',
                    'scale_out_count': 0,
                    'scale_out_levels_triggered': ''
                }
                db_manager.save_open_position(update_data)
                
                sync_report['positions_fixed'] += 1
                logger.info(f"SYNCED: {product_id} remaining_size = {actual_balance:.8f}")
                
            except Exception as e:
                sync_report['errors'].append(f"{product_id}: {str(e)}")
                logger.error(f"Failed to sync {product_id}: {e}")
        
        sync_report['synced'] = sync_report['positions_fixed'] > 0
        
        if sync_report['synced']:
            logger.info(f"Auto-sync complete: {sync_report['positions_fixed']} positions fixed")
        
        return sync_report

    def _log_wallet_snapshot(self):
        """Log wallet balances to file for tracking."""
        import os
        try:
            accounts = coinbase_api.get_accounts()
            gbp_balance = 0.0
            snapshot_lines = []

            for acc in accounts:
                curr = acc['currency']
                bal = float(acc.get('balance', 0))
                if curr == 'GBP':
                    gbp_balance = bal
                if bal > 0:
                    snapshot_lines.append(f"  {curr}: {bal}")

            log_dir = 'logs'
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, 'wallet_snapshots.log')

            with open(log_file, 'a') as f:
                f.write(f"\n=== Wallet Snapshot {datetime.now().isoformat()} ===\n")
                f.write(f"GBP Balance: {gbp_balance:.2f}\n")
                for line in snapshot_lines:
                    f.write(line + "\n")

            self._last_gbp_balance = gbp_balance
            self._wallet_snapshot_logged = True
            logger.info(f"Wallet snapshot logged: GBP £{gbp_balance:.2f}")

        except Exception as e:
            logger.error(f"Failed to log wallet snapshot: {e}")

    def check_wallet_balance(self):
        """Check wallet balance and warn if GBP dropped unexpectedly."""
        try:
            if not self._wallet_snapshot_logged:
                self._log_wallet_snapshot()
                return

            now = datetime.now()
            if self._last_wallet_check and (now - self._last_wallet_check).total_seconds() < self._wallet_check_interval:
                return

            accounts = coinbase_api.get_accounts()
            current_gbp = 0.0
            for acc in accounts:
                if acc['currency'] == 'GBP':
                    current_gbp = float(acc.get('balance', 0))
                    break

            if self._last_gbp_balance > 0:
                pct_change = (self._last_gbp_balance - current_gbp) / self._last_gbp_balance
                if pct_change > 0.05:
                    logger.warning(f"WALLET ALERT: GBP dropped {pct_change:.1%} from {self._last_gbp_balance:.2f} to {current_gbp:.2f}")

            self._last_gbp_balance = current_gbp
            self._last_wallet_check = now

        except Exception as e:
            logger.error(f"Failed to check wallet balance: {e}")


# Global risk manager instance
risk_manager = RiskManager()