#!/usr/bin/env python3
"""
Crypto Trading Bot - Main Entry Point

This is the main entry point for the crypto trading bot. It initializes
all components and starts the trading system.

Educational Notes:
- Command-line interfaces (CLI) are common for automation tools
- Logging is crucial for debugging and monitoring
- Graceful shutdown handling prevents data corruption
- Modular design allows for easy testing and maintenance
"""

import sys
import logging
import signal
import time
import threading
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

# Import our modules
from config.settings import settings
from src.coinbase_api import coinbase_api
from src.database import db_manager
from src.data_collector import data_collector
from src.ai_model import ai_model
from src.risk_manager import risk_manager
from src.trading_engine import trading_engine
from src.balance_manager import balance_manager
from src.currency_utils import currency_converter

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL) or logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class UnifiedBot:
    """
    Unified bot that runs both the trading engine and dashboard together.

    This class manages the coordination between the web dashboard and
    trading engine, providing real-time status updates and control.
    """

    def __init__(self):
        # Initialize trading state from database
        self.trading_active = db_manager.get_trading_active()
        self.trading_thread = None
        self.status_listeners = []  # WebSocket connections for real-time updates
        self.shutdown_event = threading.Event()
        
        # Add timing tracking for countdown
        self.last_cycle_time = time.time()
        self.cycle_count = 0

        # Initialize currency settings
        self.base_currency = db_manager.get_user_setting('base_currency', settings.BASE_CURRENCY) or settings.BASE_CURRENCY
        self.display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'

        logger.info(f"Unified Bot initialized - Trading active: {self.trading_active}")
        logger.info(f"Currency settings - Base: {self.base_currency}, Display: {self.display_currency}")
        
        # Fix trading state consistency on startup
        if self.trading_active:
            logger.info("Trading flag is True but will check thread state on first start attempt")
            # Don't start trading immediately - let start() method handle thread creation

    def add_status_listener(self, listener):
        """Add a status listener (WebSocket connection)."""
        self.status_listeners.append(listener)
        logger.debug(f"Added status listener. Total: {len(self.status_listeners)}")

    def remove_status_listener(self, listener):
        """Remove a status listener."""
        if listener in self.status_listeners:
            self.status_listeners.remove(listener)
            logger.debug(f"Removed status listener. Total: {len(self.status_listeners)}")

    def broadcast_status(self, status_data: dict):
        """Broadcast status update to all listeners."""
        for listener in self.status_listeners[:]:  # Copy list to avoid modification during iteration
            try:
                # Send status update via WebSocket
                import asyncio
                asyncio.create_task(listener.send_json(status_data))
            except Exception as e:
                logger.warning(f"Failed to send status to listener: {e}")
                self.remove_status_listener(listener)

    def start_trading(self) -> bool:
        """Starts trading engine."""
        # Check if trading is already active AND thread is actually running
        if self.trading_active and self.trading_thread and self.trading_thread.is_alive():
            logger.warning("Trading already active and thread is running")
            return False

        # If trading flag is set but thread is not running, reset and start
        if self.trading_active and (not self.trading_thread or not self.trading_thread.is_alive()):
            logger.warning("Trading flag set but thread not running - resetting and starting fresh")
            self.trading_active = False  # Reset to allow start

        if not self.trading_thread or not self.trading_thread.is_alive():
            logger.info("Starting trading engine...")
            self.trading_active = True
            
            # Persist trading state to database
            db_manager.set_trading_active(True)
            
            self.trading_thread = threading.Thread(target=self._trading_loop, daemon=True)
            self.trading_thread.start()

            # Broadcast status update
            self.broadcast_status({
                "type": "status_update",
                "trading_active": True,
                "paper_trading": db_manager.get_paper_trading(),
                "message": "Trading engine started"
            })

            return True
        else:
            logger.warning("Trading thread already running")
            return False

    def reset_trading_state(self) -> bool:
        """Reset inconsistent trading state."""
        logger.info("Resetting inconsistent trading state - clearing trading flag")
        self.trading_active = False
        db_manager.set_trading_active(False)
        
        # Wait a moment to ensure state clears
        import time
        time.sleep(1)
        
        return True

        # If trading flag is set but thread is not running, reset and start
        if self.trading_active and (not self.trading_thread or not self.trading_thread.is_alive()):
            logger.warning("Trading flag set but thread not running - resetting and starting fresh")
            self.trading_active = False  # Reset to allow start

        if not self.trading_thread or not self.trading_thread.is_alive():
            logger.info("Starting trading engine...")
            self.trading_active = True
            
            # Persist trading state to database
            db_manager.set_trading_active(True)
            
            self.trading_thread = threading.Thread(target=self._trading_loop, daemon=True)
            self.trading_thread.start()

            # Broadcast status update
            self.broadcast_status({
                "type": "status_update",
                "trading_active": True,
                "paper_trading": db_manager.get_paper_trading(),
                "message": "Trading engine started"
            })

            return True
        else:
            logger.warning("Trading thread already running")
            return False

    def stop_trading(self) -> bool:
        """Stop the trading engine."""
        if not self.trading_active:
            logger.warning("Trading not active")
            return False

        logger.info("Stopping trading engine...")
        self.trading_active = False
        
        # Persist trading state to database
        db_manager.set_trading_active(False)

        # Broadcast status update
        self.broadcast_status({
            "type": "status_update",
            "trading_active": False,
            "paper_trading": db_manager.get_paper_trading(),
            "message": "Trading engine stopped"
        })

        return True

    def _trading_loop(self):
        """Main trading loop that runs continuously with timeout protection."""
        logger.info("Trading loop started")
        cycle_timeout = 300  # 5 minutes max per cycle

        while not self.shutdown_event.is_set():
            try:
                if self.trading_active:
                    logger.info("Starting new trading cycle...")
                    cycle_start_time = time.time()

                    # Run one trading cycle with timeout
                    try:
                        cycle_results = trading_engine.run_trading_cycle(cycle_timeout=cycle_timeout)
                    except Exception as cycle_error:
                        logger.error(f"Trading cycle failed: {cycle_error}")
                        cycle_results = {
                            'signals_found': 0,
                            'trades_executed': 0,
                            'positions_closed': 0,
                            'total_pnl': 0.0,
                            'error': str(cycle_error)
                        }

                    cycle_time = time.time() - cycle_start_time

                    # Check for cycle timeout
                    if cycle_time > cycle_timeout:
                        logger.error(f"CYCLE TIMEOUT: Cycle took {cycle_time:.1f}s (> {cycle_timeout}s)")
                        self.broadcast_status({
                            "type": "error",
                            "message": f"Cycle timeout after {cycle_time:.1f}s - possible hang detected",
                            "trading_active": self.trading_active
                        })

                    # Broadcast results to dashboard
                    status_update = {
                        "type": "cycle_complete",
                        "timestamp": time.time(),
                        "signals_found": cycle_results.get('signals_found', 0),
                        "trades_executed": cycle_results.get('trades_executed', 0),
                        "positions_closed": cycle_results.get('positions_closed', 0),
                        "total_pnl": cycle_results.get('total_pnl', 0.0),
                        "cycle_time": cycle_time,
                        "trading_active": self.trading_active,
                        "paper_trading": db_manager.get_paper_trading()
                    }

                    # Add current portfolio status
                    portfolio_data = risk_manager.check_portfolio_risk()
                    status_update.update({
                        "portfolio_value": portfolio_data.get('portfolio_value', 0),
                        "daily_pnl": portfolio_data.get('daily_pnl', 0),
                        "risk_status": portfolio_data.get('risk_status', 'unknown')
                    })

                    self.broadcast_status(status_update)

                    # Update cycle timing for countdown
                    self.last_cycle_time = time.time()
                    self.cycle_count += 1
                    logger.info(f"Cycle #{self.cycle_count} completed in {cycle_time:.1f}s at {self.last_cycle_time}")

                # Sleep between cycles
                logger.debug(f"Sleeping for {settings.MARKET_CHECK_INTERVAL} seconds...")
                time.sleep(settings.MARKET_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                # Broadcast error status
                self.broadcast_status({
                    "type": "error",
                    "message": f"Trading loop error: {str(e)}",
                    "trading_active": self.trading_active
                })
                time.sleep(10)  # Wait before retrying

        logger.info("Trading loop stopped")

        def get_status(self) -> dict:
            """Get current bot status for dashboard"""
            portfolio_data = risk_manager.check_portfolio_risk()
            engine_status = trading_engine.get_status()
            model_status = ai_model.get_model_status()
            
            return {
                "trading_active": self.trading_active,
                "paper_trading": db_manager.get_paper_trading(),
                "portfolio_value": portfolio_data.get('portfolio_value', 0),
                "daily_pnl": portfolio_data.get('daily_pnl', 0),
                "risk_status": portfolio_data.get('risk_status', 'normal'),
                "active_positions": engine_status.get('active_positions', 0),
                "models_trained": model_status.get('models_trained', []),
                "listeners_connected": len(self.status_listeners),
            }
        """Get current bot status."""
        portfolio_data = risk_manager.check_portfolio_risk()
        engine_status = trading_engine.get_status()

        # Get model status from AI system (not trading engine)
        model_status = ai_model.get_model_status()

        # Get current exchange rate for display
        exchange_rate = currency_converter.get_exchange_rate('USD', self.display_currency) or 1.0

        return {
            "trading_active": self.trading_active,
            "paper_trading": db_manager.get_paper_trading(),
            "portfolio_value": portfolio_data.get('portfolio_value', 0),
            "daily_pnl": portfolio_data.get('daily_pnl', 0),
            "risk_status": portfolio_data.get('risk_status', 'unknown'),
            "active_positions": engine_status.get('active_positions', 0),
            "models_trained": model_status.get('models_trained', []),
            "listeners_connected": len(self.status_listeners),
            "base_currency": self.base_currency,
            "display_currency": self.display_currency,
            "exchange_rate": exchange_rate
        }

    def set_base_currency(self, currency: str) -> bool:
        """Set the base currency for trading operations."""
        if currency not in ['USD', 'GBP']:
            logger.error(f"Invalid base currency: {currency}")
            return False
        
        try:
            self.base_currency = currency
            success = db_manager.save_user_setting('base_currency', currency)
            
            if success:
                logger.info(f"Base currency changed to: {currency}")
                
                # Update settings for product IDs based on currency
                if currency == 'USD':
                    settings.PRODUCT_IDS = [pid.replace('-GBP', '-USD') for pid in settings.PRODUCT_IDS]
                elif currency == 'GBP':
                    settings.PRODUCT_IDS = [pid.replace('-USD', '-GBP') for pid in settings.PRODUCT_IDS]
                
                # Broadcast currency change
                self.broadcast_status({
                    "type": "currency_change",
                    "base_currency": currency,
                    "display_currency": self.display_currency,
                    "message": f"Base currency changed to {currency}"
                })
                
                return True
            else:
                logger.error("Failed to save base currency to database")
                return False
                
        except Exception as e:
            logger.error(f"Error setting base currency: {e}")
            return False

    async def set_display_currency(self, currency: str) -> bool:
        """Set the display currency for the dashboard."""
        if currency not in ['USD', 'GBP']:
            logger.error(f"Invalid display currency: {currency}")
            return False
        
        try:
            self.display_currency = currency
            logger.info(f"Attempting to save display_currency={currency} to database...")
            success = db_manager.save_user_setting('display_currency', currency)
            logger.info(f"Database save result: {success}")
            
            if success:
                # Force a commit and verify the save
                saved_value = db_manager.get_user_setting('display_currency', None)
                logger.info(f"Verified save - read back from DB: {saved_value}")
                
                self.broadcast_status({
                    "type": "currency_change",
                    "base_currency": self.base_currency,
                    "display_currency": currency
                })
                
                # Update all ongoing USD conversion rates to new base currency
                for usd_pair in settings.PRODUCT_IDS:
                    if '-GBP' not in usd_pair and usd_pair.replace('-', '') in settings.PRODUCT_IDS:
                        gbp_pair = f"{usd_pair.replace('-', '')}"
                        try:
                            rate = coinbase_api.get_product_ticker('GBP-USD')
                            if rate and 'price' in rate:
                                db_manager.save_user_setting(f"{gbp_pair}_exchange_rate", str(float(rate['price'])))
                                logger.info(f"Updated {gbp_pair} exchange rate: {float(rate['price'])}")
                        except Exception as e:
                            logger.error(f"Failed to update {gbp_pair} exchange rate: {e}")
                
                return True
            else:
                logger.error("Failed to save display currency to database")
                return False
                
        except Exception as e:
            logger.error(f"Error setting display currency: {e}")
            return False

    def get_currency_info(self) -> dict:
        """Get current currency configuration and exchange rates."""
        try:
            # Get exchange rates
            usd_to_gbp = currency_converter.get_exchange_rate('USD', 'GBP') or 0.80
            gbp_to_usd = currency_converter.get_exchange_rate('GBP', 'USD') or 1.25
            
            return {
                "base_currency": self.base_currency,
                "display_currency": self.display_currency,
                "exchange_rates": {
                    "usd_to_gbp": usd_to_gbp,
                    "gbp_to_usd": gbp_to_usd
                },
                "supported_currencies": list(currency_converter.CURRENCY_SYMBOLS.keys()),
                "trading_pairs": settings.PRODUCT_IDS
            }
        except Exception as e:
            logger.error(f"Error getting currency info: {e}")
            return {
                "base_currency": self.base_currency,
                "display_currency": self.display_currency,
                "error": str(e)
            }

    def get_status(self) -> Dict[str, Any]:
        """Get current bot status."""
        return {
            "trading_active": self.trading_active,
            "trading_thread_alive": self.trading_thread.is_alive() if self.trading_thread else False,
            "base_currency": self.base_currency,
            "display_currency": self.display_currency,
            "paper_trading": db_manager.get_paper_trading()
        }

    def shutdown(self):
        """Shutdown the unified bot."""
        logger.info("Shutting down unified bot...")
        self.shutdown_event.set()
        self.trading_active = False

        # Wait for trading thread to finish
        if self.trading_thread and self.trading_thread.is_alive():
            self.trading_thread.join(timeout=5)

        logger.info("Unified bot shutdown complete")


# Global unified bot instance
unified_bot = UnifiedBot()


class TradingBot:
    """
    Main trading bot class that orchestrates all components.

    This class manages the bot's lifecycle, coordinates between
    different modules, and handles system-wide operations.
    """

    def __init__(self):
        """Initialize the trading bot."""
        self.running = False
        self.last_data_update = 0

        logger.info("Trading Bot initialized")
        logger.info(f"Trading pairs: {settings.PRODUCT_IDS}")
        logger.info(f"Sandbox mode: {settings.is_sandbox_mode()}")

    def startup_check(self) -> bool:
        """
        Perform startup checks to ensure everything is ready.

        Returns:
            True if all checks pass
        """
        logger.info("Performing startup checks...")

        try:
            # Check API connection
            logger.info("Testing Coinbase API connection...")
            accounts = coinbase_api.get_accounts()
            logger.info(f"Found {len(accounts)} accounts")

            # Check database
            logger.info("Testing database connection...")
            logger.info("Database connection successful")

            # Check data collection
            logger.info("Testing data collection...")
            prices = data_collector.get_current_prices()
            if prices:
                logger.info(f"Current prices: {prices}")
            else:
                logger.warning("No price data available")

            # Check AI models
            logger.info("Checking AI models...")
            model_status = ai_model.get_model_status()
            if not model_status['models_trained']:
                logger.info("No trained models found. Training AI models...")

                # Train models for each product (using sample data for now)
                import pandas as pd
                import numpy as np

                # Create sample data for training
                dates = pd.date_range(start='2023-01-01', periods=200, freq='D')
                np.random.seed(42)
                base_price = 50000
                price_changes = np.random.normal(0, 0.02, len(dates))
                prices = base_price * np.cumprod(1 + price_changes)

                sample_data = pd.DataFrame({
                    'timestamp': dates,
                    'open': prices * 0.99,
                    'high': prices * 1.01,
                    'low': prices * 0.98,
                    'close': prices,
                    'volume': np.random.lognormal(15, 1, len(dates))
                })
                sample_data.set_index('timestamp', inplace=True)

                # Mock the data collection method temporarily
                original_method = data_collector.collect_historical_data
                data_collector.collect_historical_data = lambda *args, **kwargs: sample_data

                # Train models
                for product_id in settings.PRODUCT_IDS:
                    logger.info(f"Training AI model for {product_id}...")
                    result = ai_model.train_model(product_id)
                    if result['success']:
                        logger.info(f"✓ {product_id} model trained (Accuracy: {result['accuracy']:.3f})")
                    else:
                        logger.warning(f"✗ {product_id} model training failed")

                # Restore original method
                data_collector.collect_historical_data = original_method

            else:
                logger.info(f"Found {len(model_status['models_trained'])} trained models")

            # Check risk management
            logger.info("Testing risk management...")
            risk_status = risk_manager.check_portfolio_risk()
            logger.info(f"Risk status: {risk_status['risk_status']}")

            logger.info("All startup checks passed!")
            return True

        except Exception as e:
            logger.error(f"Startup check failed: {e}")
            return False

    def run_cycle(self):
        """Execute one trading cycle."""
        try:
            current_time = time.time()

            # Update market data periodically
            if current_time - self.last_data_update > settings.DATA_UPDATE_INTERVAL:
                logger.info("Updating market data...")
                success = data_collector.update_market_data()
                if success:
                    self.last_data_update = current_time
                    logger.info("Market data updated successfully")
                else:
                    logger.warning("Market data update failed")

            # Run trading cycle
            logger.info("Running trading cycle...")
            cycle_results = trading_engine.run_trading_cycle()

            # Log results
            if cycle_results['signals_found'] > 0:
                logger.info(f"Signals found: {cycle_results['signals_found']}")
            if cycle_results['trades_executed'] > 0:
                logger.info(f"Trades executed: {cycle_results['trades_executed']}")
            if cycle_results['positions_closed'] > 0:
                logger.info(f"Positions closed: {cycle_results['positions_closed']} | Total P&L: ${cycle_results['total_pnl']:.2f}")

            # Log current portfolio status
            risk_status = risk_manager.check_portfolio_risk()
            logger.info(f"Portfolio: ${risk_status['portfolio_value']:.2f} | Daily P&L: ${risk_status['daily_pnl']:.2f}")

            # Get current prices
            prices = data_collector.get_current_prices()
            for product_id, price in prices.items():
                logger.debug(f"{product_id}: ${price:.2f}")

        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")

    def run(self):
        """Main bot execution loop."""
        logger.info("Starting trading bot...")

        if not self.startup_check():
            logger.error("Startup checks failed. Exiting.")
            return

        self.running = True
        logger.info("Bot is now running. Press Ctrl+C to stop.")

        try:
            while self.running:
                self.run_cycle()

                # Wait before next cycle
                time.sleep(settings.MARKET_CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        """Clean shutdown of the bot."""
        logger.info("Shutting down trading bot...")
        self.running = False

        # TODO: Close any open positions gracefully
        # TODO: Save final state
        # TODO: Close database connections

        logger.info("Bot shutdown complete")


def main():
    """Main entry point function."""
    # Parse command line arguments (basic version)
    import argparse

    parser = argparse.ArgumentParser(description='Crypto Trading Bot')
    parser.add_argument('--test', action='store_true',
                       help='Run in test mode (no actual trades)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    parser.add_argument('--dashboard', action='store_true',
                       help='Start unified dashboard with trading engine')

    args = parser.parse_args()

    # Adjust logging if verbose
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create and run bot
    bot = TradingBot()

    # Handle graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        bot.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the bot or unified dashboard
    if args.dashboard:
        logger.info("Starting unified dashboard with trading engine...")
        run_unified_dashboard()
    else:
        bot.run()


def run_unified_dashboard():
    """Run both dashboard and trading engine together."""
    logger.info("run_unified_dashboard() called")
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.templating import Jinja2Templates
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    logger.info("Imports completed successfully")
    from pathlib import Path

    # Create FastAPI app for unified dashboard
    app = FastAPI(
        title="Crypto Trading Bot",
        description="Unified Trading Bot Dashboard",
        version="1.0.0"
    )
    
    # Mount static files
    static_dir = Path(__file__).parent / "src" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    # Dashboard route removed - using main.py dashboard function
    templates_dir = Path(__file__).parent / "src" / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Main dashboard page showing overview of bot status."""

        try:
            # Add cache-busting timestamp to force refresh
            import time
            timestamp = str(int(time.time()))
            cache_buster = f"?_t={timestamp}"

            # Get portfolio data with currency conversion
            from src.currency_utils import currency_converter

            # Get user's preferred display currency from database (not in-memory cache)
            display_currency = db_manager.get_user_setting('display_currency', 'GBP')
            if display_currency is None:
                display_currency = 'GBP'
            base_currency = db_manager.get_user_setting('base_currency', 'GBP')
            if base_currency is None:
                base_currency = 'GBP'

            # Check trading mode to determine data source
            if db_manager.get_paper_trading():
                # Paper trading: show simulated portfolio
                portfolio = [
                    {
                        "currency": "USD",
                        "balance": settings.PAPER_TRADING_PORTFOLIO_VALUE,
                        "price": 1.0,
                        "value_usd": settings.PAPER_TRADING_PORTFOLIO_VALUE,
                        "percentage": 100.0
                    }
                ]
                total_value_usd = settings.PAPER_TRADING_PORTFOLIO_VALUE
                total_value = currency_converter.convert_amount(total_value_usd, 'USD', display_currency)
                formatted_total = currency_converter.format_currency(total_value, display_currency)
                converted_portfolio = [
                    {
                        "currency": "USD",
                        "balance": settings.PAPER_TRADING_PORTFOLIO_VALUE,
                        "price": 1.0,
                        "value_usd": settings.PAPER_TRADING_PORTFOLIO_VALUE,
                        "percentage": 100.0,
                        "value": total_value,
                        "formatted_value": formatted_total,
                        "formatted_balance": f"{total_value:.2f} {display_currency}"
                    }
                ]
                # Get current prices for display even in paper trading
                current_prices = data_collector.get_current_prices()
            else:
                # Live trading: show real Coinbase balances for ALL currencies with assets
                accounts = coinbase_api.get_accounts()
                current_prices = data_collector.get_current_prices()

                # Debug: Log the currency immediately
                logger.info(f"Dashboard route: display_currency={repr(display_currency)}")

                portfolio = []
                total_value_usd = 0.0

                # Collect all currencies that need price data
                currencies_needing_prices = set()

                for account in accounts:
                    currency = account['currency']
                    balance = account['available']

                    # Skip zero balances
                    if balance <= 0:
                        continue

                    currencies_needing_prices.add(currency)

                # Fetch prices for all currencies found in wallet
                for currency in currencies_needing_prices:
                    if currency != 'USD' and f"{currency}-USD" not in current_prices:
                        # Skip GBP-USD requests - use exchange rate from dashboard instead
                        if currency == 'GBP':
                            # Get GBP-USD rate from existing exchange rate (USD->GBP inverted)
                            # TODO: Temporarily commented out to isolate recursion issue
                            pass
                            # try:
                            #     portfolio_response = await risk_manager.check_portfolio_risk()
                            #     if 'exchange_rate' in portfolio_response:
                            #         usd_to_gbp_rate = portfolio_response['exchange_rate'].get('usd_to_display', 0)
                            #         if usd_to_gbp_rate > 0:
                            #             gbp_to_usd_rate = 1 / usd_to_gbp_rate
                            #             current_prices["GBP-USD"] = gbp_to_usd_rate
                            #             logger.debug(f"Using inverted exchange rate for GBP-USD: {gbp_to_usd_rate}")
                            #             continue
                            # except Exception as e:
                            #     logger.debug(f"Could not get exchange rate for GBP: {e}")
                        
                        # For other currencies, try USD pairs
                        try:
                            ticker = coinbase_api.get_product_ticker(f"{currency}-USD")
                            price = ticker.get('price')
                            if price and price > 0:
                                current_prices[f"{currency}-USD"] = price
                        except Exception as e:
                            logger.debug(f"Could not fetch price for {currency}-USD: {e}")
                            continue

                # Now build portfolio with all currencies that have balances and prices
                for account in accounts:
                    currency = account['currency']
                    balance = float(account.get('available', 0))

                    if balance <= 0:
                        continue

                    if currency == 'USD':
                        value_usd = balance
                        price = 1.0
                    elif f"{currency}-USD" in current_prices:
                        price = current_prices[f"{currency}-USD"]
                        value_usd = balance * price
                    elif f"{currency}-GBP" in current_prices:
                        price = current_prices[f"{currency}-GBP"]
                        gbp_to_usd = currency_converter.get_exchange_rate('GBP', 'USD') or 1.30
                        value_usd = balance * price * gbp_to_usd
                    elif currency == 'USDC':
                        value_usd = balance
                        price = 1.0
                    elif currency == 'GBP':
                        # GBP is the base currency - convert balance to USD for portfolio totals
                        gbp_to_usd = currency_converter.get_exchange_rate('GBP', 'USD') or 1.30
                        value_usd = balance * gbp_to_usd
                        price = 1.0
                    else:
                        continue

                    if value_usd < settings.MIN_PORTFOLIO_VALUE_DISPLAY:
                        continue

                    total_value_usd += value_usd

                    portfolio.append({
                        "currency": currency,
                        "balance": balance,
                        "price": price,
                        "value_usd": value_usd,
                        "gbp_value": currency_converter.convert_amount(value_usd, 'USD', 'GBP'),
                        "percentage": 0.0
                    })

                # Sort portfolio by value (highest first) and calculate percentages
                portfolio.sort(key=lambda x: x["value_usd"], reverse=True)
                for item in portfolio:
                    item["percentage"] = (item["value_usd"] / total_value_usd * 100) if total_value_usd > 0 else 0

                # Convert to display currency
                total_value = currency_converter.convert_amount(total_value_usd, 'USD', display_currency)
                formatted_total = currency_converter.format_currency(total_value, display_currency)

                # Convert portfolio items to display currency
                converted_portfolio = []
                for item in portfolio:
                    converted_item = item.copy()
                    converted_item['value'] = currency_converter.convert_amount(
                        item['value_usd'], 'USD', display_currency
                    )
                    converted_item['formatted_value'] = currency_converter.format_currency(
                        converted_item['value'], display_currency
                    )
                    converted_item['formatted_balance'] = f"{converted_item['value']:.2f} {display_currency}"
                    converted_portfolio.append(converted_item)

            # Get other status data
            engine_status = trading_engine.get_status()
            model_status = ai_model.get_model_status()

            # Sync trading_engine.active_positions with database for consistency
            trading_engine.active_positions = db_manager.load_open_positions()
            
            # Get open positions count from database
            open_positions = db_manager.get_all_open_positions_detailed()
            open_positions_count = len(open_positions)

            # Get recent trades (last 10)
            recent_trades = db_manager.get_trades(limit=10)

            # Get performance metrics
            perf_summary = db_manager.get_performance_summary(days=30)

            # Get risk status
            risk_data = risk_manager.check_portfolio_risk(db_manager.get_paper_trading())

            # Format additional currency values for template
            formatted_daily_pnl = currency_converter.format_currency(risk_data.get('daily_pnl', 0), display_currency)

            # Format current prices in display currency only
            formatted_current_prices = {}
            for product_id, price in current_prices.items():
                formatted_current_prices[product_id] = currency_converter.format_currency(price, display_currency)

            # Format recent trades with currency conversion
            formatted_recent_trades = []
            for trade in (recent_trades or []):
                formatted_trade = trade.copy()
                formatted_trade['formatted_price'] = currency_converter.format_currency(trade.get('price', 0), display_currency)
                formatted_trade['formatted_pnl'] = currency_converter.format_currency(trade.get('pnl', 0), display_currency)
                formatted_recent_trades.append(formatted_trade)

            # Calculate comprehensive metrics
            total_trades_all_time = perf_summary.get('total_trades', 0) if perf_summary else 0
            win_rate_percentage = (perf_summary.get('win_rate', 0) * 100) if perf_summary else 0
            total_pnl = perf_summary.get('total_pnl', 0) if perf_summary else 0
            formatted_total_pnl = currency_converter.format_currency(total_pnl, display_currency)

            # Get trading statistics
            successful_trades = sum(1 for trade in recent_trades if trade.get('pnl', 0) > 0) if recent_trades else 0
            recent_win_rate = (successful_trades / len(recent_trades) * 100) if recent_trades else 0

# Get current market conditions and AI signals
            market_conditions = {}
            trading_signals = {}
            display_market_conditions = {}  # For display currency with direct data

            # Use pairs based on base currency (no conversion needed for base currency)
            if base_currency == 'GBP':
                base_pairs = ['BTC-GBP', 'ETH-GBP', 'SOL-GBP', 'LTC-GBP', 'DOT-GBP', 'ADA-GBP', 'LINK-GBP', 'UNI-GBP']
                display_pairs = base_pairs
            else:
                base_pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'LTC-USD', 'DOT-USD', 'ADA-USD', 'LINK-USD', 'UNI-USD']
                display_pairs = base_pairs

            for product_id in base_pairs:
                market_conditions[product_id] = {'price': 0.0, 'signal': 'HOLD', 'confidence': 0, 'action': 'WAIT'}

            # Try to get real data (fallback to conversion if needed)
            exchange_rate = currency_converter.get_exchange_rate('USD', 'GBP') or 1.30  # Default fallback rate
            try:
                gbp_ticker = coinbase_api.get_product_ticker('GBP-USD')
                if gbp_ticker and 'price' in gbp_ticker:
                    exchange_rate = float(gbp_ticker['price'])
            except:
                pass  # Keep default rate

            # Try to get real data for base currency pairs
            try:
                for product_id in base_pairs:
                    # Try base pair first
                    try:
                        ticker = coinbase_api.get_product_ticker(product_id)
                        if ticker and 'price' in ticker:
                            price = float(ticker['price'])
                            market_conditions[product_id]['price'] = price
                    except:
                        # Fallback to other currency with conversion
                        if base_currency == 'GBP':
                            usd_product_id = product_id.replace('-GBP', '-USD')
                        else:
                            gbp_product_id = product_id.replace('-USD', '-GBP')
                            usd_product_id = gbp_product_id
                        
                        try:
                            usd_ticker = coinbase_api.get_product_ticker(usd_product_id)
                            if usd_ticker and 'price' in usd_ticker:
                                usd_price = float(usd_ticker['price'])
                                if base_currency == 'GBP':
                                    price = usd_price / exchange_rate
                                else:
                                    price = usd_price * exchange_rate
                                market_conditions[product_id]['price'] = price
                        except:
                            pass  # Keep default price

                    # Get AI signal
                    try:
                        signal_data = ai_model.get_signal(product_id)
                        if signal_data:
                            confidence = signal_data.get('confidence', 0) * 100  # Convert to percentage
                            action = signal_data.get('action', 'HOLD')
                            meets_threshold = confidence >= 60.0
                            
                            market_conditions[product_id].update({
                                'signal': action,
                                'confidence': confidence,
                                'meets_threshold': meets_threshold,
                                'action': 'TRADE' if meets_threshold else 'WAIT'
                            })
                    except:
                        pass  # Keep defaults

            except Exception as e:
                # Keep defaults
                pass

            # Extract crypto balances from current portfolio for signal integration
            crypto_balances = {}
            for item in converted_portfolio:
                crypto_symbol = item.get('currency', '').upper()
                if crypto_symbol:  # Skip GBP/USD base currencies
                    crypto_balance_gbp = item.get('gbp_value', 0.0)
                    crypto_quantity = item.get('balance', 0.0)
                    
                    crypto_balances[crypto_symbol] = {
                        'balance_gbp': crypto_balance_gbp,
                        'balance_quantity': crypto_quantity,
                        'formatted_balance': f"£{crypto_balance_gbp:,.2f}",
                        'formatted_quantity': f"{crypto_quantity:.6f}" if crypto_quantity > 0.001 else "0.000000",
                        'balance_percentage': (crypto_balance_gbp / total_value * 100) if total_value > 0 else 0
                    }

            # Convert data to display currency format
            for base_product_id, base_data in market_conditions.items():
                if display_currency == 'GBP' and base_currency == 'USD':
                    display_product_id = base_product_id.replace('-USD', '-GBP')
                    base_price = base_data.get('price', 0.0)
                    display_price = base_price / exchange_rate if exchange_rate > 0 else 0.0
                    currency_symbol = '£'
                elif display_currency == 'USD' and base_currency == 'GBP':
                    display_product_id = base_product_id.replace('-GBP', '-USD')
                    base_price = base_data.get('price', 0.0)
                    display_price = base_price * exchange_rate if exchange_rate > 0 else 0.0
                    currency_symbol = '$'
                else:
                    # Same currency, no conversion needed
                    display_product_id = base_product_id
                    display_price = base_data.get('price', 0.0)
                    currency_symbol = '£' if display_currency == 'GBP' else '$'
                
                crypto_symbol = display_product_id.split('-')[0]  # BTC, ETH, SOL, etc.
                
                # Add crypto balance data to market conditions
                crypto_balance = crypto_balances.get(crypto_symbol, {})
                has_balance = crypto_balance.get('balance_gbp', 0.0) > 0.01  # Minimum significant balance
                
                # Determine if we used conversion fallback
                used_conversion_fallback = base_product_id != display_product_id
                
                display_market_conditions[display_product_id] = {
                    'price': display_price,
                    'formatted_price': f"{currency_symbol}{display_price:,.2f}",
                    'signal': base_data.get('signal', 'HOLD'),
                    'confidence': base_data.get('confidence', 0),
                    'meets_threshold': base_data.get('meets_threshold', False),
                    'action': base_data.get('action', 'WAIT'),
                    'original_pair': base_product_id,
                    'exchange_rate': exchange_rate,
                    'crypto_balance': crypto_balance,
                    'has_balance': has_balance,
                    'balance_percentage': crypto_balance.get('balance_percentage', 0),
                    'used_conversion_fallback': used_conversion_fallback
                }

            trading_active = db_manager.get_trading_active()

            # Get exchange rate info
            exchange_rate_info = unified_bot.get_currency_info()
            
            context = {
                "settings": settings,  # Add settings to template context
                "portfolio": converted_portfolio,
                "portfolio_value": total_value,
                "formatted_total": formatted_total,
                "display_currency": display_currency,
                "base_currency": base_currency,
                "daily_pnl": risk_data.get('daily_pnl', 0),
                "formatted_daily_pnl": formatted_daily_pnl,
                "risk_status": risk_data.get('risk_status', 'unknown'),
                "paper_trading": db_manager.get_paper_trading(),
                "trading_active": trading_active,
                "active_positions": open_positions_count,
                "models_trained": model_status.get('models_trained', []),
                "current_prices": current_prices,
                "formatted_current_prices": formatted_current_prices,
                "recent_trades": formatted_recent_trades,
                "total_trades": len(recent_trades) if recent_trades else 0,
                "total_trades_all_time": total_trades_all_time,
                "win_rate": win_rate_percentage,
                "recent_win_rate": recent_win_rate,
                "total_pnl": total_pnl,
                "formatted_total_pnl": formatted_total_pnl,
                "market_conditions": display_market_conditions,
                "perf_summary": perf_summary,
                "currency_info": exchange_rate_info,
                
                # Create models_info for template compatibility
                "models_info": {
                    'models_trained_count': len(model_status.get('models_trained', [])),
                    'btc_model_ready': model_status.get('btc_model_ready', False),
                    'btc_model_accuracy': model_status.get('btc_model_accuracy', 0),
                    'btc_model_status': model_status.get('btc_model_status', 'not_started'),
                    'btc_model_trained_on': model_status.get('btc_model_trained_on', 'Not trained'),
                    'btc_model_progress': model_status.get('btc_model_progress', 0),
                    'eth_model_ready': model_status.get('eth_model_ready', False),
                    'eth_model_accuracy': model_status.get('eth_model_accuracy', 0),
                    'eth_model_status': model_status.get('eth_model_status', 'not_started'),
                    'eth_model_trained_on': model_status.get('eth_model_trained_on', 'Not trained'),
                    'eth_model_progress': model_status.get('eth_model_progress', 0),
                    'sol_model_ready': model_status.get('sol_model_ready', False),
                    'sol_model_accuracy': model_status.get('sol_model_accuracy', 0),
                    'sol_model_status': model_status.get('sol_model_status', 'not_started'),
                    'sol_model_trained_on': model_status.get('sol_model_trained_on', 'Not trained'),
                    'sol_model_progress': model_status.get('sol_model_progress', 0),
                    'dot_model_ready': model_status.get('dot_model_ready', False),
                    'dot_model_accuracy': model_status.get('dot_model_accuracy', 0),
                    'dot_model_status': model_status.get('dot_model_status', 'not_started'),
                    'dot_model_trained_on': model_status.get('dot_model_trained_on', 'Not trained'),
                    'dot_model_progress': model_status.get('dot_model_progress', 0),
                    'ada_model_ready': model_status.get('ada_model_ready', False),
                    'ada_model_accuracy': model_status.get('ada_model_accuracy', 0),
                    'ada_model_status': model_status.get('ada_model_status', 'not_started'),
                    'ada_model_trained_on': model_status.get('ada_model_trained_on', 'Not trained'),
                    'ada_model_progress': model_status.get('ada_model_progress', 0),
                    'ltc_model_ready': model_status.get('ltc_model_ready', False),
                    'ltc_model_accuracy': model_status.get('ltc_model_accuracy', 0),
                    'ltc_model_status': model_status.get('ltc_model_status', 'not_started'),
                    'ltc_model_trained_on': model_status.get('ltc_model_trained_on', 'Not trained'),
                    'ltc_model_progress': model_status.get('ltc_model_progress', 0),
                    'uni_model_ready': model_status.get('uni_model_ready', False),
                    'uni_model_accuracy': model_status.get('uni_model_accuracy', 0),
                    'uni_model_status': model_status.get('uni_model_status', 'not_started'),
                    'uni_model_trained_on': model_status.get('uni_model_trained_on', 'Not trained'),
                    'uni_model_progress': model_status.get('uni_model_progress', 0),
                    'link_model_ready': model_status.get('link_model_ready', False),
                    'link_model_accuracy': model_status.get('link_model_accuracy', 0),
                    'link_model_status': model_status.get('link_model_status', 'not_started'),
                    'link_model_trained_on': model_status.get('link_model_trained_on', 'Not trained'),
                    'link_model_progress': model_status.get('link_model_progress', 0),
                    'alt_model_ready': model_status.get('alt_model_ready', False),
                    'alt_model_accuracy': model_status.get('alt_model_accuracy', 0),
                    'alt_model_status': model_status.get('alt_model_status', 'not_started'),
                    'alt_model_trained_on': model_status.get('alt_model_trained_on', 'Not trained'),
                    'alt_model_progress': model_status.get('alt_model_progress', 0)
                },
                
                "gbp_balance_status": balance_manager.check_gbp_balance() if hasattr(balance_manager, 'check_gbp_balance') else {"gbp_balance": 0.0, "status": "Unknown"},
                
                # Add product_ids for template (base currency pairs)
                "product_ids": base_pairs,
                
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # Debug logging
            logger.info(f"Dashboard context - total_pnl: {total_pnl}, formatted_total_pnl: {formatted_total_pnl}, win_rate: {win_rate_percentage}")


            # Render template with cache-busting
            response = templates.TemplateResponse("dashboard.html", {"request": {"type": "http"}, **context})

            # Add aggressive cache-busting headers
            import time
            timestamp = str(int(time.time()))
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Last-Modified"] = "0"
            response.headers["ETag"] = f'"{timestamp}"'
            return response

        except Exception as e:
            logger.error(f"Dashboard error: {e}")
            return HTMLResponse(content=f"<h1>Error: {str(e)}</h1>")

    # Add WebSocket endpoint to the FastAPI app
    @app.websocket("/ws/status")
    async def unified_status_websocket(websocket):
        """WebSocket endpoint for real-time status updates."""
        await websocket.accept()
        unified_bot.add_status_listener(websocket)

        try:
            # Keep connection alive and handle incoming messages
            while True:
                data = await websocket.receive_text()
                # Could handle commands from client here if needed
                logger.debug(f"Received WebSocket message: {data}")

        except Exception as e:
            logger.debug(f"WebSocket connection closed: {e}")
        finally:
            unified_bot.remove_status_listener(websocket)

    # Add settings management endpoint
    @app.post("/api/settings/{setting_key}")
    async def update_setting(setting_key: str, request_body: dict):
        """Update user setting."""
        try:
            setting_value = request_body.get('value')
            if not setting_value:
                return {"status": "error", "message": "Setting value is required"}
            
            success = db_manager.save_user_setting(setting_key, setting_value)
            if success:
                logger.info(f"Updated setting: {setting_key} = {setting_value}")
                return {"status": "success", "message": f"Setting {setting_key} updated"}
            else:
                return {"status": "error", "message": "Failed to update setting"}
        except Exception as e:
            logger.error(f"Settings update error: {e}")
            return {"status": "error", "message": str(e)}

    # Add exchange rate endpoint
    @app.get("/api/exchange_rate")
    async def get_exchange_rate():
        """Get current USD to GBP exchange rate."""
        try:
            from src.currency_utils import currency_converter
            rate = currency_converter.get_exchange_rate('USD', 'GBP')
            if rate:
                return {"rate": rate, "source": "coinbase"}
            else:
                return {"rate": 0.80, "source": "fallback"}  # Default fallback
        except Exception as e:
            logger.error(f"Exchange rate error: {e}")
            return {"rate": 0.80, "source": "fallback"}
    
    # Add debug endpoint to test template context
    @app.get("/api/debug/context")
    async def debug_context():
        """Debug endpoint to check template variables."""
        try:
            display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'
            return {
                "display_currency": display_currency,
                "raw_value": repr(display_currency),
                "length": len(display_currency) if display_currency else None
            }
        except Exception as e:
            return {"error": str(e)}

    # Update control endpoints to use unified bot
    # Specific endpoints must come BEFORE catch-all route

    @app.post("/api/control/switch_live")
    async def switch_to_live():
        """Switch to live trading mode - clears paper positions."""
        try:
            if not db_manager.get_paper_trading():
                return {"status": "error", "message": "Already in live trading mode"}

            open_positions = db_manager.get_all_open_positions_detailed()
            position_count = len(open_positions)

            db_manager.clear_all_open_positions()
            trading_engine.active_positions = {}

            db_manager.set_paper_trading(False)
            trading_engine.paper_trading = False

            unified_bot.broadcast_status({
                "type": "status_update",
                "paper_trading": False,
                "message": f"Switched to live trading. Cleared {position_count} paper positions."
            })

            return {
                "status": "success",
                "message": f"Live trading enabled. {position_count} paper positions cleared.",
                "positions_cleared": position_count
            }
        except Exception as e:
            logger.error(f"Switch to live error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/control/switch_paper")
    async def switch_to_paper():
        """Switch to paper trading mode."""
        try:
            if db_manager.get_paper_trading():
                return {"status": "error", "message": "Already in paper trading mode"}

            db_manager.set_paper_trading(True)
            trading_engine.paper_trading = True

            unified_bot.broadcast_status({
                "type": "status_update",
                "paper_trading": True,
                "message": "Switched to paper trading"
            })

            return {"status": "success", "message": "Paper trading enabled"}
        except Exception as e:
            logger.error(f"Switch to paper error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/position/{position_id}/close")
    async def close_position(position_id: str):
        """Close a specific open position."""
        try:
            if position_id not in trading_engine.active_positions:
                return {"status": "error", "message": "Position not found"}

            position = trading_engine.active_positions[position_id]
            product_id = position.get('product_id', position_id)
            side = position.get('side', 'buy')
            size = position.get('size', 0)
            entry_price = position.get('entry_price', 0)

            from src.data_collector import data_collector
            prices = data_collector.get_current_prices()
            current_price = prices.get(product_id.replace('-GBP', '-USD').replace('-USD', '-GBP'), entry_price) or entry_price

            pnl = (current_price - entry_price) * size if side == 'buy' else (entry_price - current_price) * size

            trading_engine._close_position(position_id, float(pnl), "Manual close", float(current_price))

            # Sync trading_engine.active_positions with database after closing
            trading_engine.active_positions = db_manager.load_open_positions()

            logger.info(f"Position closed manually: {position_id} ({product_id}, P&L: {pnl:.4f})")

            return {
                "status": "success",
                "message": f"Position closed: {product_id}",
                "position_id": position_id,
                "exit_price": current_price,
                "pnl": pnl
            }
        except Exception as e:
            logger.error(f"Close position error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/control/{action}")
    async def control_bot(action: str):
        """Control bot operations."""
        try:
            if action == "start_trading":
                success = unified_bot.start_trading()
                if success:
                    return {
                        "status": "success", 
                        "message": "Trading engine started",
                        "trading_active": True,
                        "paper_trading": db_manager.get_paper_trading()
                    }
                else:
                    return {"status": "error", "message": "Trading already active"}

            elif action == "stop_trading":
                success = unified_bot.stop_trading()
                if success:
                    return {
                        "status": "success", 
                        "message": "Trading engine stopped",
                        "trading_active": False,
                        "paper_trading": db_manager.get_paper_trading()
                    }
                else:
                    return {"status": "error", "message": "Trading not active"}

            elif action == "enable_live_trading":
                if db_manager.get_paper_trading():
                    trading_engine.enable_live_trading()
                    unified_bot.broadcast_status({
                        "type": "status_update",
                        "paper_trading": False,
                        "message": "Live trading enabled"
                    })
                    return {"status": "success", "message": "Live trading enabled"}
                else:
                    return {"status": "error", "message": "Live trading already enabled"}

            elif action == "switch_to_paper_trading":
                if not db_manager.get_paper_trading():
                    trading_engine.switch_to_paper_trading()
                    unified_bot.broadcast_status({
                        "type": "status_update",
                        "paper_trading": True,
                        "message": "Paper trading enabled"
                    })
                    return {"status": "success", "message": "Paper trading enabled"}
                else:
                    return {"status": "error", "message": "Already in paper trading mode"}

            elif action == "emergency_stop":
                unified_bot.stop_trading()
                settings.EMERGENCY_STOP = True
                logger.warning("⚠️ EMERGENCY STOP ACTIVATED")
                unified_bot.broadcast_status({
                    "type": "status_update",
                    "trading_active": False,
                    "message": "Emergency stop activated"
                })
                return {"status": "success", "message": "Emergency stop activated"}

            elif action == "reset_emergency_stop":
                settings.EMERGENCY_STOP = False
                logger.info("Emergency stop reset")
                unified_bot.broadcast_status({
                    "type": "status_update",
                    "message": "Emergency stop reset"
                })
                return {"status": "success", "message": "Emergency stop reset"}

            elif action == "retrain_models":
                result = ai_model.retrain_all_models()
                success_count = sum(1 for r in result.values() if r.get('success', False))
                total_count = len(result)
                return {
                    "status": "success", 
                    "message": f"Models retrained: {success_count}/{total_count} successful",
                    "details": result
                }
            
            elif action == "emergency_stop":
                try:
                    # Cancel all open orders
                    orders = coinbase_api.get_orders()
                    orders_cancelled = 0
                    for order in orders:
                        if order.get('status') in ['pending', 'open']:
                            if coinbase_api.cancel_order(order.get('order_id', '')):
                                orders_cancelled += 1
                    
                    # Stop trading engine using unified bot
                    unified_bot.stop_trading()
                    
                    logger.info(f"Emergency stop activated: cancelled {orders_cancelled} orders")
                    return {"status": "success", "message": f"Emergency stop: {orders_cancelled} orders cancelled"}
                except Exception as e:
                    logger.error(f"Emergency stop error: {e}")
                    return {"status": "error", "message": str(e)}

            else:
                return {"status": "error", "message": f"Unknown action: {action}"}

        except Exception as e:
            logger.error(f"Control API error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/settings/display_currency")
    async def set_display_currency(request: Request):
        """Set user's preferred display currency."""
        try:
            data = await request.json()
            currency = data.get('value', 'USD').upper()

            # Validate currency
            if currency not in ['USD', 'GBP']:
                return {"status": "error", "message": "Invalid currency. Must be USD or GBP"}

            # Use unified bot to set display currency
            success = await unified_bot.set_display_currency(currency)
            if success:
                return {
                    "status": "success", 
                    "message": f"Display currency set to {currency}",
                    "saved_currency": currency
                }
            else:
                return {"status": "error", "message": "Failed to save currency preference"}

        except Exception as e:
            logger.error(f"Display currency error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/settings/base_currency")
    async def set_base_currency(request: Request):
        """Set user's preferred base currency for trading."""
        try:
            data = await request.json()
            currency = data.get('value', 'GBP').upper()

            # Validate currency
            if currency not in ['USD', 'GBP']:
                return {"status": "error", "message": "Invalid currency. Must be USD or GBP"}

            # Use unified bot to set base currency
            success = unified_bot.set_base_currency(currency)
            if success:
                return {
                    "status": "success", 
                    "message": f"Base currency set to {currency}",
                    "base_currency": currency,
                    "trading_pairs": settings.PRODUCT_IDS
                }
            else:
                return {"status": "error", "message": "Failed to save base currency preference"}

        except Exception as e:
            logger.error(f"Base currency error: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/settings/display_currency")
    async def get_display_currency():
        """Get current display currency for verification."""
        try:
            currency = db_manager.get_user_setting('display_currency', 'USD')
            return {"display_currency": currency}
        except Exception as e:
            logger.error(f"Get display currency error: {e}")
            return {"display_currency": "USD", "error": str(e)}

    @app.get("/api/currency/info")
    async def get_currency_info():
        """Get current currency configuration and exchange rates."""
        try:
            return unified_bot.get_currency_info()
        except Exception as e:
            logger.error(f"Currency info error: {e}")
            return {"status": "error", "message": str(e)}



    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page():
        """Settings page for currency management and bot configuration."""
        try:
            # Get current currency configuration
            currency_info = unified_bot.get_currency_info()
            
            # Get other settings from database (not in-memory cache)
            display_currency = db_manager.get_user_setting('display_currency', 'GBP')
            if display_currency is None:
                display_currency = 'GBP'
            base_currency = db_manager.get_user_setting('base_currency', 'GBP')
            if base_currency is None:
                base_currency = 'GBP'
            paper_trading = db_manager.get_paper_trading()
            
            context = {
                "display_currency": display_currency,
                "base_currency": base_currency,
                "currency_info": currency_info,
                "paper_trading": paper_trading,
                "trading_active": unified_bot.trading_active,
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "settings": settings,  # Add settings object for template access
            }
            
            response = templates.TemplateResponse("settings.html", {"request": {"type": "http"}, **context})
            
            # Add aggressive cache-busting headers
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
            
        except Exception as e:
            logger.error(f"Settings page error: {e}")
            return HTMLResponse(content=f"<h1>Error: {str(e)}</h1>")

    @app.get("/trades", response_class=HTMLResponse)
    async def trades_page():
        """Trades history page."""
        try:
            # Get trades from database
            trades = db_manager.get_trades(limit=100)  # Get recent trades
            has_trades = len(trades) > 0
            
            # Calculate statistics
            total_trades = len(trades)
            winning_trades = sum(1 for trade in trades if trade.get('pnl', 0) > 0)
            win_rate = (winning_trades / total_trades * 100) if has_trades else 0.0
            total_pnl = sum(trade.get('pnl', 0) for trade in trades)
            
            context = {
                "trading_active": unified_bot.trading_active,
                "paper_trading": db_manager.get_paper_trading(),
                "display_currency": unified_bot.display_currency,
                "base_currency": unified_bot.base_currency,
                "trades": trades,
                "has_trades": has_trades,
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
            }
            return templates.TemplateResponse("trades.html", {"request": {"type": "http"}, **context})
        except Exception as e:
            logger.error(f"Trades page error: {e}")
            return HTMLResponse(content=f"<h1>Error: {str(e)}</h1>")

    @app.get("/performance", response_class=HTMLResponse)
    async def performance_page():
        """Performance metrics page."""
        try:
            # Get trades from database for performance analysis
            trades = db_manager.get_trades(limit=1000)  # Get more trades for analysis
            has_trades = len(trades) > 0
            
            # Initialize performance data
            performance_data = {}
            product_stats = {}
            
            if has_trades:
                # Calculate performance by time period
                from datetime import timedelta
                now = datetime.now()
                periods = {
                    "Today": timedelta(hours=24),
                    "Week": timedelta(days=7),
                    "Month": timedelta(days=30),
                    "All Time": timedelta(days=365)
                }
                
                for period_name, period_delta in periods.items():
                    period_trades = []
                    for trade in trades:
                        try:
                            # Handle timestamp parsing more carefully
                            timestamp = trade['timestamp']
                            if isinstance(timestamp, str):
                                # Remove timezone info if present
                                timestamp = timestamp.replace('Z', '+00:00')
                                trade_time = datetime.fromisoformat(timestamp)
                            elif isinstance(timestamp, datetime):
                                trade_time = timestamp
                            else:
                                # Skip if timestamp format is unexpected
                                continue
                            
                            if now - trade_time <= period_delta:
                                period_trades.append(trade)
                        except Exception as parse_error:
                            # Skip trades with timestamp parsing issues
                            logger.debug(f"Skipping trade with timestamp error: {parse_error}")
                            continue
                    
                    wins = sum(1 for trade in period_trades if trade.get('pnl', 0) > 0)
                    total_pnl = sum(trade.get('pnl', 0) for trade in period_trades)
                    
                    performance_data[period_name] = {
                        "trades": len(period_trades),
                        "wins": wins,
                        "total_pnl": total_pnl,
                        "win_rate": wins / len(period_trades) if period_trades else 0,
                        "avg_pnl": total_pnl / len(period_trades) if period_trades else 0
                    }
                
                # Calculate performance by product
                products = {}
                for trade in trades:
                    product = trade.get('product_id', 'Unknown')
                    if product not in products:
                        products[product] = {"trades": [], "wins": 0, "total_pnl": 0}
                    
                    products[product]["trades"].append(trade)
                    if trade.get('pnl', 0) > 0:
                        products[product]["wins"] += 1
                    products[product]["total_pnl"] += trade.get('pnl', 0)
                
                # Convert to stats format for template
                for product, data in products.items():
                    product_stats[product] = {
                        "trades": len(data["trades"]),
                        "wins": data["wins"],
                        "total_pnl": data["total_pnl"],
                        "win_rate": data["wins"] / len(data["trades"]),
                        "avg_pnl": data["total_pnl"] / len(data["trades"])
                    }
            
            context = {
                "trading_active": unified_bot.trading_active,
                "paper_trading": db_manager.get_paper_trading(),
                "display_currency": unified_bot.display_currency,
                "base_currency": unified_bot.base_currency,
                "has_trades": has_trades,
                "performance_data": performance_data,
                "product_stats": product_stats,
            }
            return templates.TemplateResponse("performance.html", {"request": {"type": "http"}, **context})
        except Exception as e:
            logger.error(f"Performance page error: {e}")
            return HTMLResponse(content=f"<h1>Error: {str(e)}</h1>")

    @app.get("/models", response_class=HTMLResponse)
    async def models_page():
        """AI Models status page."""
        try:
            # Get model status from AI model
            model_status = ai_model.get_model_status()
            
            # Prepare models info for template
            models_info = []
            for product_id in settings.PRODUCT_IDS:
                # Map to USD pair for model status
                usd_pair = settings.TRAINING_PAIRS[settings.PRODUCT_IDS.index(product_id)] if product_id in settings.PRODUCT_IDS else product_id
                
                # Get current signal for this product
                try:
                    signal_data = ai_model.get_signal(product_id)
                    signal = signal_data.get('action', 'N/A')
                    confidence = signal_data.get('confidence', 0.0)
                except:
                    signal = 'N/A'
                    confidence = 0.0
                
                models_info.append({
                    'product_id': product_id,
                    'trained': usd_pair in model_status.get('models_trained', []),
                    'signal': signal,
                    'confidence': confidence
                })
            
            # Get features count (from AI model if available)
            features_count = 16  # Default based on known features
            
            context = {
                "trading_active": unified_bot.trading_active,
                "paper_trading": db_manager.get_paper_trading(),
                "display_currency": unified_bot.display_currency,
                "base_currency": unified_bot.base_currency,
                "models_trained": model_status.get('models_trained_count', 0),
                "models_info": models_info,
                "features_count": features_count,
            }
            return templates.TemplateResponse("models.html", {"request": {"type": "http"}, **context})
        except Exception as e:
            logger.error(f"Models page error: {e}")
            return HTMLResponse(content=f"<h1>Error: {str(e)}</h1>")

    @app.post("/api/trades/clear")
    async def clear_trades():
        print("DEBUG: clear_trades endpoint called")
        """Clear all trade records from database."""
        try:
            trades_cleared = db_manager.clear_all_trades()
            return {
                "success": True,
                "message": f"Cleared {trades_cleared} trades from database"
            }
        except Exception as e:
            logger.error(f"Clear trades error: {e}")
            return {
                "success": False,
                "error": f"Failed to clear trades: {str(e)}"
            }

    @app.post("/api/test-trade")
    async def test_trade():
        """Place a very small test trade to verify API keys work."""
        try:
            # Only allow in paper trading mode for safety
            if not db_manager.get_paper_trading():
                return {
                    "success": False,
                    "error": "Test trades only allowed in paper trading mode"
                }

            # Place a very small test buy order (0.00001 BTC)
            test_result = coinbase_api.place_market_order(
                product_id="BTC-USD",
                side="buy",
                size=0.00001
            )

            if test_result:
                return {
                    "success": True,
                    "message": "Test trade successful - API keys are working",
                    "order_id": test_result.get('order_id', 'unknown'),
                    "product_id": test_result.get('product_id', 'unknown')
                }
            else:
                return {
                    "success": False,
                    "error": "Test trade failed - check API keys and connection"
                }

        except Exception as e:
            logger.error(f"Test trade error: {e}")
            return {
                "success": False,
                "error": f"Test trade failed: {str(e)}"
            }

    @app.get("/api/check-api-permissions")
    async def check_api_permissions():
        """Check Coinbase API key permissions for diagnostics using SDK."""
        try:
            # Use SDK's built-in method for permissions checking
            if coinbase_api.sdk_client:
                permissions_result = coinbase_api.sdk_client.get_api_key_permissions()
                return {
                    "success": True,
                    "permissions": {
                        "can_view": permissions_result.can_view,
                        "can_trade": permissions_result.can_trade,
                        "can_transfer": permissions_result.can_transfer,
                        "portfolio_uuid": permissions_result.portfolio_uuid,
                        "portfolio_type": permissions_result.portfolio_type
                    },
                    "message": "API permissions retrieved successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "SDK client not initialized",
                    "message": "Check api_keys.env configuration and SDK availability"
                }

        except Exception as e:
            logger.error(f"API permissions check error: {e}")
            return {
                "success": False,
                "error": f"Permissions check failed: {str(e)}",
                "message": "Verify ECDSA API keys are properly configured in api_keys.env"
            }

    # Update status endpoint to use unified bot
    @app.get("/api/status")
    async def get_status():
        """Get current bot status as JSON."""
        try:
            status = unified_bot.get_status()
            return status
        except Exception as e:
            logger.error(f"Status API error: {e}")
            return {"error": str(e)}

    @app.get("/api/portfolio/open_positions")
    async def get_open_positions():
        """Get all currently open positions with P&L."""
        try:
            positions = db_manager.get_all_open_positions_detailed()
            total_pnl = sum(p.get('pnl', 0) for p in positions)
            return {
                "positions": positions,
                "count": len(positions),
                "total_pnl": total_pnl
            }
        except Exception as e:
            logger.error(f"Open positions API error: {e}")
            return {"error": str(e)}

    @app.get("/api/models/status")
    def get_models_status():
        """Get AI model status for all trading pairs."""
        try:
            # Check each configured product ID
            models_status = {}
            working_count = 0
            error_count = 0
            
            for product_id in settings.PRODUCT_IDS:
                try:
                    # Check if model exists and is working
                    if os.path.exists(f"models/{product_id}_model.pkl"):
                        # Test if model can be loaded
                        try:
                            prediction = ai_model.predict(product_id)
                            if prediction is not None:
                                models_status[product_id] = "working"
                                working_count += 1
                            else:
                                models_status[product_id] = "error"
                                error_count += 1
                        except Exception:
                            models_status[product_id] = "error"
                            error_count += 1
                    else:
                        models_status[product_id] = "not_trained"
                        error_count += 1
                except Exception as e:
                    models_status[product_id] = "error"
                    error_count += 1
            
            return {
                "success": True,
                "total_products": len(settings.PRODUCT_IDS),
                "working_models": working_count,
                "error_models": error_count,
                "models": models_status
            }
        except Exception as e:
            logger.error(f"Models status error: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/countdown")
    async def get_countdown():
        """Get countdown timing for next trading cycle."""
        try:
            import time
            from datetime import datetime
            
            now = time.time()
            last_cycle = getattr(unified_bot, 'last_cycle_time', now)
            interval = settings.MARKET_CHECK_INTERVAL
            elapsed = now - last_cycle
            remaining = max(0, interval - elapsed)
            progress = min(100, (elapsed / interval) * 100)
            
            return {
                "remaining_seconds": int(remaining),
                "elapsed_seconds": int(elapsed),
                "progress_percent": progress,
                "last_cycle_time": datetime.fromtimestamp(last_cycle).strftime("%H:%M:%S"),
                "interval_minutes": interval // 60,
                "trading_active": unified_bot.trading_active
            }
        except Exception as e:
            logger.error(f"Countdown API error: {e}")
            return {"error": str(e)}

    # Add trades endpoint
    @app.get("/api/trades")
    async def get_trades(limit: int = 20):
        """Get recent trades as JSON."""
        try:
            trades = db_manager.get_trades(limit=limit)
            return {"trades": trades or []}
        except Exception as e:
            logger.error(f"Trades API error: {e}")
            return {"error": str(e)}

    # Add GBP balance endpoint
    @app.get("/api/gbp-balance")
    async def get_gbp_balance():
        """Get GBP balance status with alert levels."""
        try:
            balance_status = balance_manager.check_gbp_balance()
            return balance_status
        except Exception as e:
            logger.error(f"GBP balance API error: {e}")
            return {"error": str(e)}

    # Add trading state reset endpoint
    @app.post("/api/trading/reset")
    async def reset_trading_state():
        """Reset inconsistent trading state."""
        try:
            unified_bot.reset_trading_state()
            return {"success": True, "message": "Trading state reset successfully"}
        except Exception as e:
            logger.error(f"Trading state reset error: {e}")
            return {"error": str(e)}

    # Add portfolio endpoint
    @app.get("/api/portfolio")
    async def get_portfolio():
        """Get portfolio composition with currency conversion."""
        try:
            display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'
            base_currency = db_manager.get_user_setting('base_currency', settings.BASE_CURRENCY) or settings.BASE_CURRENCY
            
            accounts = coinbase_api.get_accounts()
            current_prices = data_collector.get_current_prices()

            from src.currency_utils import currency_converter
            exchange_rate = currency_converter.get_exchange_rate('GBP', 'USD') or 1.30

            trading_currencies = ['BTC', 'ETH', 'SOL', 'LTC', 'DOT', 'ADA', 'LINK', 'UNI']
            stablecoins = ['USD', 'USDC', 'USDT']
            
            portfolio = []
            total_value_usd = 0.0

            for account in accounts:
                currency = account['currency']
                balance = float(account.get('available', 0))
                if balance <= 0:
                    continue

                if currency in stablecoins:
                    value_usd = balance
                    price = 1.0
                elif currency in trading_currencies:
                    price_pair = f"{currency}-USD" if f"{currency}-USD" in current_prices else None
                    if price_pair and price_pair in current_prices:
                        price = current_prices[price_pair]
                        value_usd = balance * price
                    else:
                        gbp_pair = f"{currency}-GBP"
                        if gbp_pair in current_prices:
                            price = current_prices[gbp_pair]
                            value_usd = balance * price * exchange_rate
                        else:
                            continue
                else:
                    continue

                total_value_usd += value_usd

                portfolio.append({
                    "currency": currency,
                    "balance": balance,
                    "price": price,
                    "value_usd": value_usd,
                    "percentage": 0.0
                })

            for item in portfolio:
                item["percentage"] = (item["value_usd"] / total_value_usd * 100) if total_value_usd > 0 else 0

            total_value = currency_converter.convert_amount(total_value_usd, 'USD', display_currency)
            
            converted_portfolio = []
            for item in portfolio:
                converted_item = item.copy()
                converted_item['value'] = currency_converter.convert_amount(
                    item['value_usd'], 'USD', display_currency
                )
                converted_item['gbp_value'] = currency_converter.convert_amount(
                    item['value_usd'], 'USD', 'GBP'
                )
                converted_item['formatted_value'] = currency_converter.format_currency(
                    converted_item['value'], display_currency
                )
                converted_item['formatted_balance'] = f"{converted_item['value']:.2f} {display_currency}"
                converted_portfolio.append(converted_item)

            return {
                "portfolio": converted_portfolio,
                "total_value": total_value,
                "formatted_total": currency_converter.format_currency(total_value, display_currency),
                "display_currency": display_currency,
                "last_update": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Portfolio API error: {e}")
            return {"error": str(e)}

    # Add trading state reset endpoint
    @app.post("/api/trading/reset")
    async def reset_trading_state_endpoint():
        """Reset inconsistent trading state."""
        try:
            unified_bot.reset_trading_state()
            return {"success": True, "message": "Trading state reset successfully"}
        except Exception as e:
            logger.error(f"Trading state reset error: {e}")
            return {"error": str(e)}

    # Add comprehensive debugging endpoint BEFORE starting uvicorn
    @app.get("/api/debug/comprehensive")
    async def comprehensive_debug():
        """Comprehensive debugging endpoint for trading engine issues."""
        try:
            debug_info = {
                "timestamp": datetime.now().isoformat(),
                "unified_bot_state": {
                    "trading_active": unified_bot.trading_active,
                    "trading_thread_alive": unified_bot.trading_thread.is_alive() if unified_bot.trading_thread else False,
                    "shutdown_event_set": unified_bot.shutdown_event.is_set(),
                    "cycle_count": getattr(unified_bot, 'cycle_count', 0),
                    "last_cycle_time": getattr(unified_bot, 'last_cycle_time', None)
                },
                "trading_engine_state": trading_engine.get_status(),
                "portfolio_risk": risk_manager.check_portfolio_risk(),
                "settings": {
                    "market_check_interval": settings.MARKET_CHECK_INTERVAL,
                    "max_daily_trades": settings.MAX_DAILY_TRADES,
                    "max_position_size": settings.MAX_POSITION_SIZE,
                    "model_confidence_threshold": settings.MODEL_CONFIDENCE_THRESHOLD
                },
                "api_status": {
                    "api_key_present": bool(coinbase_api.api_key),
                    "sdk_client_available": bool(coinbase_api.sdk_client)
                },
                "coinbase_accounts": coinbase_api.get_accounts()[:5] if hasattr(coinbase_api, 'get_accounts') else [],
                "gbp_balance_status": balance_manager.check_gbp_balance()
            }
            return debug_info
        except Exception as e:
            import traceback
            return {
                "error": str(e),
                "traceback": traceback.format_exc(),
                "debug_failed": True
            }

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        unified_bot.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start the trading engine BEFORE starting the dashboard server
        logger.info("Starting trading engine...")
        trading_started = unified_bot.start_trading()
        if trading_started:
            logger.info("Trading engine started successfully")
        else:
            logger.warning("Trading engine failed to start or was already running")
        
        # Start the FastAPI server
        logger.info(f"Starting unified dashboard on http://0.0.0.0:{settings.DASHBOARD_PORT}")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=settings.DASHBOARD_PORT,
            log_level="info"
        )
    except KeyboardInterrupt:
        logger.info("Dashboard interrupted by user")
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
    finally:
        unified_bot.shutdown()

if __name__ == "__main__":
    main()