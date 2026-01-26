"""
Balance Manager Module for Crypto Trading Bot

This module handles GBP balance monitoring and alerts for low balance warnings.
Provides foundation for future automated crypto-to-GBP conversion features.

Educational Notes:
- Balance monitoring helps prevent portfolio depletion
- Threshold-based alerts provide early warnings
- Future automation will handle balance restoration automatically
- All balance checks are non-blocking to maintain trading functionality
"""

import logging
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

from config.settings import settings
from src.coinbase_api import coinbase_api
from src.database import db_manager

logger = logging.getLogger(__name__)


class BalanceManager:
    """
    Balance Manager for GBP monitoring and low balance alerts.
    
    This class monitors GBP balance and provides warnings when levels
    get low. Future enhancements will include automated crypto-to-GBP conversion.
    """
    
    def __init__(self):
        """Initialize balance manager."""
        self.last_check_time = 0
        self.cache_duration = 60  # Cache balance checks for 60 seconds
        
        logger.info("Balance Manager initialized")
        logger.info(f"GBP thresholds: Warning £{settings.GBP_WARNING_THRESHOLD}, Critical £{settings.GBP_CRITICAL_THRESHOLD}")
    
    def check_gbp_balance(self) -> Dict[str, Any]:
        """
        Check current GBP balance and determine alert status.
        
        Returns:
            Dictionary with balance status, alert level, and recommendations
        """
        try:
            # Get GBP balance directly from Coinbase API (same as risk manager and debug endpoint)
            gbp_balance = 0.0
            try:
                accounts = coinbase_api.get_accounts()
                logger.info(f"Total accounts found: {len(accounts)}")
                for i, account in enumerate(accounts):
                    currency = account.get('currency', 'Unknown')
                    available = account.get('available', 'Not found')
                    logger.info(f"Account {i}: {currency} - available: {available}")
                    if currency == 'GBP':
                        balance_field = account.get('available')
                        logger.info(f"GBP account found! available: {balance_field}")
                        if balance_field is not None and float(balance_field) > 0:
                            gbp_balance = float(balance_field)
                            logger.info(f"SUCCESS: Using GBP available balance: £{gbp_balance}")
                        else:
                            gbp_balance = float(account.get('balance', 0))
                            logger.info(f"Fallback: Using GBP balance field: £{gbp_balance}")
                        break
            except Exception as e:
                logger.error(f"Error getting GBP balance from Coinbase API: {e}")
            
            # Determine alert level
            alert_level = self._get_alert_level(gbp_balance)
            status_color = self._get_status_color(alert_level)
            alert_message = self._get_alert_message(alert_level, gbp_balance)
            recommendation = self._get_recommendation(alert_level, gbp_balance)
            
            balance_status = {
                'gbp_balance': gbp_balance,
                'alert_level': alert_level,  # 'normal', 'warning', 'critical'
                'status_color': status_color,  # 'success', 'warning', 'danger'
                'alert_message': alert_message,
                'recommendation': recommendation,
                'warning_threshold': settings.GBP_WARNING_THRESHOLD,
                'critical_threshold': settings.GBP_CRITICAL_THRESHOLD,
                'last_check': datetime.now().strftime("%H:%M:%S"),
                'trading_allowed': True,  # Never block trading, just warn
            }
            
            logger.debug(f"GBP balance check: £{gbp_balance:.2f} - {alert_level}")
            return balance_status
            
        except Exception as e:
            logger.error(f"Error checking GBP balance: {e}")
            return {
                'gbp_balance': 0.0,
                'alert_level': 'error',
                'status_color': 'secondary',
                'alert_message': 'Unable to check balance',
                'recommendation': 'Check API connection',
                'last_check': datetime.now().strftime("%H:%M:%S"),
                'trading_allowed': True
            }
    
    def should_trade(self, trade_size_gbp: float) -> Tuple[bool, str]:
        """
        Determine if a trade should proceed based on GBP balance.
        
        Args:
            trade_size_gbp: Size of trade in GBP
            
        Returns:
            Tuple of (should_trade, reason)
        """
        try:
            balance_status = self.check_gbp_balance()
            gbp_balance = balance_status['gbp_balance']
            alert_level = balance_status['alert_level']
            
            # Always allow trades (non-blocking), but provide guidance
            should_trade = True
            reason = "Trade allowed (monitoring active)"
            
            # Add recommendations based on balance level
            if alert_level == 'critical':
                reason = f"Trade allowed but GBP critical (£{gbp_balance:.2f}). Consider top-up."
            elif alert_level == 'warning':
                reason = f"Trade allowed but GBP low (£{gbp_balance:.2f}). Monitor balance."
            
            return should_trade, reason
            
        except Exception as e:
            logger.error(f"Error evaluating trade: {e}")
            return True, "Unable to check balance - proceeding with trade"
    
    def _get_alert_level(self, gbp_balance: float) -> str:
        """Determine alert level based on GBP balance."""
        if gbp_balance <= settings.GBP_CRITICAL_THRESHOLD:
            return 'critical'
        elif gbp_balance <= settings.GBP_WARNING_THRESHOLD:
            return 'warning'
        else:
            return 'normal'
    
    def _get_status_color(self, alert_level: str) -> str:
        """Map alert level to UI color."""
        color_map = {
            'normal': 'success',
            'warning': 'warning', 
            'critical': 'danger',
            'error': 'secondary'
        }
        return color_map.get(alert_level, 'secondary')
    
    def _get_alert_message(self, alert_level: str, balance: float) -> str:
        """Generate alert message based on level and balance."""
        if alert_level == 'critical':
            return f"⚠️ CRITICAL: GBP balance very low (£{balance:.2f})"
        elif alert_level == 'warning':
            return f"⚠️ WARNING: GBP balance low (£{balance:.2f})"
        elif alert_level == 'normal':
            return f"✅ GBP balance healthy (£{balance:.2f})"
        else:
            return "❓ Unable to check balance"
    
    def _get_recommendation(self, alert_level: str, balance: float) -> str:
        """Get recommendation based on balance level."""
        if alert_level == 'critical':
            return "Top up GBP immediately. Consider selling crypto holdings."
        elif alert_level == 'warning':
            return "Top up GBP soon. Monitor trading activity."
        else:
            return "Balance adequate. Continue normal trading."
    
    # TODO: Future automation methods - framework for automated crypto-to-GBP conversion
    def check_auto_topup_needed(self) -> Tuple[bool, Optional[str]]:
        """
        Future: Check if automatic GBP top-up is needed.
        
        Returns:
            Tuple of (needed, crypto_to_sell)
        """
        # Future implementation:
        # - Check if below critical threshold
        # - Analyze crypto holdings for profitable positions
        # - Recommend specific crypto to sell
        # - Respect user-defined limits and approvals
        logger.info("TODO: Implement automatic top-up assessment")
        return False, None
    
    def execute_crypto_to_gbp_conversion(self, crypto_symbol: str, amount: float) -> bool:
        """
        Future: Execute crypto-to-GBP conversion to restore balance.
        
        Args:
            crypto_symbol: Crypto to sell (e.g., 'BTC', 'ETH')
            amount: Amount of crypto to sell
            
        Returns:
            True if conversion successful, False otherwise
        """
        # Future implementation:
        # - Validate crypto holdings
        # - Calculate optimal sell amount
        # - Execute market sell order
        # - Convert proceeds to GBP
        # - Log conversion for tax purposes
        # - Update balance status
        logger.info("TODO: Implement crypto-to-GBP auto-conversion")
        return False
    
    def get_topup_recommendations(self) -> Dict[str, Any]:
        """
        Future: Get recommendations for crypto-to-GBP conversion.
        
        Returns:
            Dictionary with conversion recommendations
        """
        # Future implementation:
        # - Analyze all crypto holdings
        # - Identify profitable positions
        # - Calculate tax implications
        # - Recommend gradual conversion strategy
        # - Consider market conditions
        logger.info("TODO: Implement top-up recommendations")
        return {}


# Global balance manager instance
balance_manager = BalanceManager()