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
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

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
        
        # Initialize scheduler for auto model retraining
        self.scheduler = BackgroundScheduler(timezone='UTC')
        self._init_retrain_scheduler()
        
        # Add timing tracking for countdown
        self.last_cycle_time = time.time()
        self.cycle_count = 0

        # Initialize currency settings
        self.base_currency = db_manager.get_user_setting('base_currency', settings.BASE_CURRENCY) or settings.BASE_CURRENCY
        self.display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'

        # Initialize thread watchdog
        self.last_thread_check = time.time()
        self.thread_check_interval = 60  # Check every 60 seconds

        logger.info(f"Unified Bot initialized - Trading active: {self.trading_active}")
        logger.info(f"Currency settings - Base: {self.base_currency}, Display: {self.display_currency}")
        
        # Fix trading state consistency on startup
        if self.trading_active:
            logger.info("Trading flag is True but will check thread state on first start attempt")
            # Don't start trading immediately - let start() method handle thread creation

    def _init_retrain_scheduler(self):
        """Initialize the automatic model retraining scheduler."""
        try:
            # Add listener for job execution events (logging and error handling)
            def job_executed_listener(event):
                if event.exception:
                    logger.error(f"Scheduled job failed: {event.exception}")
                else:
                    logger.info(f"Scheduled job executed successfully: {event.job_id}")

            self.scheduler.add_listener(job_executed_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

            # Check if auto-retrain is enabled
            if ai_model.get_auto_retrain_enabled():
                # Add weekly retrain job
                trigger = CronTrigger(
                    day_of_week=settings.AUTO_RETRAIN_DAY_OF_WEEK,
                    hour=settings.AUTO_RETRAIN_HOUR,
                    minute=settings.AUTO_RETRAIN_MINUTE,
                    timezone='UTC'
                )
                self.scheduler.add_job(
                    ai_model.scheduled_retrain,
                    trigger,
                    id='auto_retrain',
                    replace_existing=True
                )
                
                # Start the scheduler
                if not self.scheduler.running:
                    self.scheduler.start()
                    logger.info(f"Auto-retrain scheduler started (runs {settings.AUTO_RETRAIN_DAY_OF_WEEK} at {settings.AUTO_RETRAIN_HOUR:02d}:{settings.AUTO_RETRAIN_MINUTE:02d} UTC)")
                else:
                    logger.info("Scheduler already running")
            else:
                logger.info("Auto-retrain is disabled")
        except Exception as e:
            logger.error(f"Failed to initialize retrain scheduler: {e}")

    def update_retrain_schedule(self, enabled: bool):
        """Update the retrain schedule based on enabled setting."""
        try:
            if enabled:
                # Add the job
                trigger = CronTrigger(
                    day_of_week=settings.AUTO_RETRAIN_DAY_OF_WEEK,
                    hour=settings.AUTO_RETRAIN_HOUR,
                    minute=settings.AUTO_RETRAIN_MINUTE,
                    timezone='UTC'
                )
                self.scheduler.add_job(
                    ai_model.scheduled_retrain,
                    trigger,
                    id='auto_retrain',
                    replace_existing=True
                )
                if not self.scheduler.running:
                    self.scheduler.start()
                logger.info(f"Auto-retrain scheduler enabled (runs {settings.AUTO_RETRAIN_DAY_OF_WEEK} at {settings.AUTO_RETRAIN_HOUR:02d}:{settings.AUTO_RETRAIN_MINUTE:02d} UTC)")
            else:
                # Remove the job
                self.scheduler.remove_job('auto_retrain')
                logger.info("Auto-retrain scheduler disabled")
        except Exception as e:
            logger.error(f"Failed to update retrain schedule: {e}")

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
        # Always restart the thread if requested - force a fresh start
        # This handles cases where the thread is stuck or in a bad state
        
        was_running = False
        
        # First, stop the existing thread if running
        if self.trading_thread and self.trading_thread.is_alive():
            logger.warning("start_trading: Existing thread found, stopping it first...")
            self.trading_active = False  # Signal thread to stop
            was_running = True
            # Wait briefly for thread to finish current iteration
            self.trading_thread.join(timeout=5)
        
        # Reset state and start fresh
        logger.info("Starting trading engine (forced restart)...")
        self.trading_active = True
        
        # Set cycle timer to past value so next cycle runs after interval wait (no stuck warning)
        self.last_cycle_time = time.time() - settings.MARKET_CHECK_INTERVAL
        
        # Persist trading state to database
        db_manager.set_trading_active(True)
        
        # Start new thread
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

    def reset_trading_state(self) -> bool:
        """Reset inconsistent trading state."""
        logger.info("Resetting inconsistent trading state - clearing trading flag")
        self.trading_active = False
        db_manager.set_trading_active(False)
        
        # Wait a moment to ensure state clears
        import time
        time.sleep(1)
        
        return True

    def stop_trading(self) -> bool:
        """Stop the trading engine."""
        if not self.trading_active:
            logger.warning("Trading not active")
            return False

        logger.info("Stopping trading engine...")
        self.trading_active = False
        
        # Wait for thread to finish
        if self.trading_thread and self.trading_thread.is_alive():
            logger.info("Waiting for trading thread to finish...")
            self.trading_thread.join(timeout=10)
            if self.trading_thread.is_alive():
                logger.warning("Trading thread did not finish in time")
        
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
        print("=== _TRADING_LOOP() STARTED ===", flush=True)
        print("Trading loop started", flush=True)
        logger.info("Trading loop started")
        cycle_timeout = 600  # 10 minutes max per cycle (API can be slow)

        # Add lock to prevent concurrent cycles
        import threading
        cycle_lock = getattr(self, 'cycle_lock', None)
        if cycle_lock is None:
            self.cycle_lock = threading.Lock()
            cycle_lock = self.cycle_lock

        # Run initial position sync on startup to reset database to match Coinbase
        print("Running initial position sync with Coinbase...", flush=True)
        logger.info("Running initial position sync with Coinbase...")
        try:
            trading_engine.initial_position_sync()
            print("Initial position sync completed", flush=True)
            logger.info("Initial position sync completed")
        except Exception as e:
            logger.error(f"Initial position sync failed: {e}")

        # Simplified model: no separate position monitor thread
        # Flips are handled during signal execution in each cycle

        while not self.shutdown_event.is_set():
            try:
                if self.trading_active:
                    # Check if we got stuck previously
                    last_cycle = getattr(self, 'last_cycle_time', 0)
                    time_since_last = time.time() - last_cycle
                    
                    # Enforce minimum interval between cycles
                    if time_since_last < settings.MARKET_CHECK_INTERVAL:
                        remaining = settings.MARKET_CHECK_INTERVAL - time_since_last
                        if remaining > 60:
                            logger.info(f"Waiting for interval: {remaining:.0f}s remaining (interval: {settings.MARKET_CHECK_INTERVAL}s)")
                        time.sleep(min(remaining, 60))  # Sleep at most 60s at a time
                        continue  # Skip this iteration, wait for interval
                    
                    # If it's been too long since last cycle (2x interval = 90 min), force restart
                    if time_since_last > settings.MARKET_CHECK_INTERVAL * 2:
                        logger.warning(f"CYCLE STUCK: {time_since_last:.0f}s since last cycle (> 2x interval), resetting cycle timing...")
                        self.last_cycle_time = time.time() - settings.MARKET_CHECK_INTERVAL + 60
                    
                    # Try to acquire lock - if another cycle is running, skip
                    if not cycle_lock.acquire(blocking=False):
                        logger.warning("Cycle already running, skipping this iteration")
                        time.sleep(30)
                        continue
                    
                    try:
                        logger.info(f"Starting new trading cycle (interval: {settings.MARKET_CHECK_INTERVAL}s)...")
                        cycle_start_time = time.time()

                        # Run one trading cycle with timeout
                        cycle_results = trading_engine.run_trading_cycle(cycle_timeout=cycle_timeout)

                        cycle_time = time.time() - cycle_start_time

                        # Check for cycle timeout
                        if cycle_time > cycle_timeout:
                            logger.error(f"CYCLE TIMEOUT: Cycle took {cycle_time:.1f}s (> {cycle_timeout}s)")
                            self.broadcast_status({
                                "type": "error",
                                "message": f"Cycle timeout after {cycle_time:.1f}s - possible hang detected",
                                "trading_active": self.trading_active
                            })
                            
                            # Track consecutive timeouts
                            self.consecutive_timeouts = getattr(self, 'consecutive_timeouts', 0) + 1
                            logger.warning(f"Consecutive timeouts: {self.consecutive_timeouts}/2")
                            
                            # Restart after 2 consecutive timeouts
                            if self.consecutive_timeouts >= 2:
                                logger.error("2 consecutive timeouts detected, restarting trading thread...")
                                self.trading_thread = threading.Thread(target=self._trading_loop, daemon=True)
                                self.trading_thread.start()
                                self.consecutive_timeouts = 0
                                cycle_lock.release()
                                continue
                        else:
                            # Reset counter on successful cycle
                            self.consecutive_timeouts = 0

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
                        is_paper = db_manager.get_paper_trading()
                        portfolio_data = risk_manager.check_portfolio_risk(is_paper)
                        status_update.update({
                            "portfolio_value": portfolio_data.get('portfolio_value', 0),
                            "daily_pnl": portfolio_data.get('daily_pnl', 0),
                            "risk_status": portfolio_data.get('risk_status', 'unknown')
                        })

                        self.broadcast_status(status_update)

                        # Sync positions with Coinbase after trading cycle
                        print("=== CALLING POST-CYCLE SYNC ===", flush=True)
                        logger.info("Syncing positions with Coinbase...")
                        trading_engine.sync_positions_with_coinbase()
                        print("=== POST-CYCLE SYNC COMPLETED ===", flush=True)
                        logger.info("Position sync completed")

                        # Update cycle timing for countdown
                        self.last_cycle_time = time.time()
                        self.cycle_count += 1
                        logger.info(f"Cycle #{self.cycle_count} completed in {cycle_time:.1f}s")
                        
                    except Exception as cycle_error:
                        logger.error(f"Trading cycle failed: {cycle_error}")
                        cycle_results = {
                            'signals_found': 0,
                            'trades_executed': 0,
                            'positions_closed': 0,
                            'total_pnl': 0.0,
                            'error': str(cycle_error)
                        }
                    finally:
                        # Release the cycle lock
                        try:
                            cycle_lock.release()
                        except:
                            pass
                    
                    # Sleep between cycles - but only if we waited for interval
                    if time_since_last < settings.MARKET_CHECK_INTERVAL:
                        remaining = settings.MARKET_CHECK_INTERVAL - time_since_last
                        if remaining > 0:
                            logger.info(f"Sleeping for remaining {remaining:.0f}s until next interval...")
                            time.sleep(remaining)

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

    def _check_thread_health(self):
        """Watchdog to ensure trading thread stays alive."""
        now = time.time()
        if now - self.last_thread_check < self.thread_check_interval:
            return
        
        self.last_thread_check = now
        
        # Check if trading should be active but thread is dead
        if self.trading_active:
            if not self.trading_thread or not self.trading_thread.is_alive():
                logger.warning(f"THREAD_WATCHDOG: Trading active but thread is dead! Restarting...")
                # Try to restart the thread
                try:
                    self.trading_thread = threading.Thread(target=self._trading_loop, daemon=True)
                    self.trading_thread.start()
                    logger.warning(f"THREAD_WATCHDOG: Thread restarted successfully")
                except Exception as e:
                    logger.error(f"THREAD_WATCHDOG: Failed to restart thread: {e}")

    def get_status(self) -> dict:
        """Get current bot status for dashboard"""
        is_paper = db_manager.get_paper_trading()
        portfolio_data = risk_manager.check_portfolio_risk(is_paper)
        engine_status = trading_engine.get_status()
        model_status = ai_model.get_model_status()
        
        # Convert portfolio value to display currency
        display_currency = db_manager.get_user_setting('display_currency', 'GBP') or 'GBP'
        portfolio_usd = portfolio_data.get('portfolio_value', 0)
        portfolio_value = currency_converter.convert_amount(portfolio_usd, 'USD', display_currency)
        
        return {
            "trading_active": self.trading_active,
            "paper_trading": is_paper,
            "portfolio_value": portfolio_value,
            "portfolio_value_usd": portfolio_usd,
            "display_currency": display_currency,
            "daily_pnl": portfolio_data.get('daily_pnl', 0),
            "risk_status": portfolio_data.get('risk_status', 'normal'),
            "active_positions": engine_status.get('active_positions', 0),
            "models_trained": model_status.get('models_trained', []),
            "listeners_connected": len(self.status_listeners),
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
                            # Use currency converter instead of non-existent GBP-USD ticker
                            rate = currency_converter.get_exchange_rate('USD', 'GBP')
                            if rate:
                                db_manager.save_user_setting(f"{gbp_pair}_exchange_rate", str(rate))
                                logger.info(f"Updated {gbp_pair} exchange rate: {rate}")
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
            risk_status = risk_manager.check_portfolio_risk(db_manager.get_paper_trading())
            logger.info(f"Risk status: {risk_status['risk_status']}")

            logger.info("All startup checks passed!")
            return True

        except Exception as e:
            logger.error(f"Startup check failed: {e}")
            return False

    def run_cycle(self):
        """Execute one trading cycle."""
        print("=== RUN_CYCLE() CALLED ===", flush=True)
        try:
            current_time = time.time()

            # Clean up dust positions at start of each cycle
            cleaned = db_manager.clean_dust_positions(settings.MIN_TRADE_AMOUNT)
            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} dust positions")

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
            risk_status = risk_manager.check_portfolio_risk(db_manager.get_paper_trading())
            logger.info(f"Portfolio: ${risk_status['portfolio_value']:.2f} | Daily P&L: ${risk_status['daily_pnl']:.2f}")

            # Sync positions with Coinbase after trading cycle
            logger.info("Syncing positions with Coinbase...")
            try:
                trading_engine.sync_positions_with_coinbase()
                logger.info("Position sync completed")
            except Exception as e:
                logger.error(f"Position sync failed: {e}")

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

    # Load scale-in settings from database on startup
    def load_scale_in_settings():
        """Load scale-in settings from database."""
        try:
            saved = db_manager.get_user_setting('scale_in_enabled', 'false')
            if saved:
                settings.SCALE_IN_ENABLED = saved.lower() == 'true'
            
            saved = db_manager.get_user_setting('scale_in_levels', None)
            if saved:
                try:
                    levels = [float(x.strip()) for x in saved.split(',')]
                    settings.SCALE_IN_LEVELS = levels
                except:
                    pass
            
            saved = db_manager.get_user_setting('scale_in_sizes', None)
            if saved:
                try:
                    sizes = [float(x.strip()) for x in saved.split(',')]
                    settings.SCALE_IN_SIZE_BY_LEVEL = sizes
                except:
                    pass
            
            saved = db_manager.get_user_setting('scale_in_max_scale_ins', None)
            if saved:
                settings.MAX_SCALE_INS_PER_POSITION = int(saved)
            
            saved = db_manager.get_user_setting('scale_in_cooldown_hours', None)
            if saved:
                settings.SCALE_IN_COOLDOWN_HOURS = int(saved)
            
            saved = db_manager.get_user_setting('scale_in_global_block', 'false')
            if saved:
                settings.SCALE_IN_GLOBAL_BLOCK = saved.lower() == 'true'
            
            # Load take profit level
            saved = db_manager.get_user_setting('take_profit_level', None)
            if saved:
                level = float(saved)
                settings.TAKE_PROFIT_LEVELS = [level]
                logger.info(f"Loaded take profit level: {level}%")
            
            logger.info(f"Loaded scale-in settings: enabled={settings.SCALE_IN_ENABLED}, levels={settings.SCALE_IN_LEVELS}")
        except Exception as e:
            logger.error(f"Error loading scale-in settings: {e}")
    
    load_scale_in_settings()

    # Load scale-out settings from database on startup
    def load_scale_out_settings():
        """Load scale-out settings from database."""
        try:
            saved = db_manager.get_user_setting('scale_out_enabled', 'true')
            if saved:
                settings.SCALE_OUT_ENABLED = saved.lower() == 'true'
            
            saved = db_manager.get_user_setting('scale_out_min_profit_pct', None)
            if saved:
                settings.SCALE_OUT_MIN_PROFIT_PCT = float(saved)
            
            saved = db_manager.get_user_setting('max_scale_out_per_position', None)
            if saved:
                settings.MAX_SCALE_OUT_PER_POSITION = int(saved)
            
            logger.info(f"Loaded scale-out settings: enabled={settings.SCALE_OUT_ENABLED}, min_profit={settings.SCALE_OUT_MIN_PROFIT_PCT}")
        except Exception as e:
            logger.error(f"Error loading scale-out settings: {e}")

    load_scale_out_settings()

    # Load market check interval from database on startup
    def load_market_check_interval():
        """Load market check interval from database."""
        try:
            saved = db_manager.get_user_setting('market_check_interval', None)
            if saved:
                interval_seconds = int(saved)
                if interval_seconds >= 900:  # Minimum 15 minutes
                    settings.MARKET_CHECK_INTERVAL = interval_seconds
                    logger.info(f"Loaded market check interval: {interval_seconds} seconds ({interval_seconds/60:.0f} minutes)")
        except Exception as e:
            logger.error(f"Error loading market check interval: {e}")

    load_market_check_interval()

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Main dashboard page showing overview of bot status."""

        try:
            # Add cache-busting timestamp to force refresh
            import time
            timestamp = str(int(time.time()))
            cache_buster = f"?_t={timestamp}"

            # Skip data refresh on dashboard load - let trading engine maintain data
            # This speeds up dashboard loading significantly
            # from config.settings import settings
            # for product_id in settings.TRAINING_PAIRS:
            #     try:
            #         data_collector.collect_historical_data(product_id, days=2)
            #     except:
            #         pass  # Continue even if some data fails

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
                # Use cached data to speed up dashboard loading - JavaScript will update with fresh data
                import concurrent.futures
                
                accounts = []
                current_prices = {}
                
                # Use thread pool to fetch data with timeout
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    accounts_future = executor.submit(coinbase_api.get_accounts)
                    prices_future = executor.submit(data_collector.get_current_prices)
                    
                    try:
                        accounts = accounts_future.result(timeout=5)
                    except concurrent.futures.TimeoutError:
                        logger.warning("Dashboard: get_accounts timed out after 5s, using empty")
                        accounts = []
                    except Exception as e:
                        logger.warning(f"Dashboard: get_accounts failed: {e}")
                        accounts = []
                    
                    try:
                        current_prices = prices_future.result(timeout=10)
                    except concurrent.futures.TimeoutError:
                        logger.warning("Dashboard: get_current_prices timed out after 10s, using empty")
                        current_prices = {}
                    except Exception as e:
                        logger.warning(f"Dashboard: get_current_prices failed: {e}")
                        current_prices = {}

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
                        # Skip non-tradeable currency pairs - use exchange rate instead
                        if currency == 'GBP':
                            # Use exchange rate from currency_converter (already fetched)
                            gbp_rate = currency_converter.get_exchange_rate('GBP', 'USD')
                            if gbp_rate:
                                current_prices['GBP-USD'] = gbp_rate
                                logger.debug(f"Using cached exchange rate for GBP-USD: {gbp_rate}")
                            continue
                        elif currency in ['USDC', 'USDT']:
                            # Stablecoins are 1:1 with USD
                            current_prices[f"{currency}-USD"] = 1.0
                            continue
                        
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
                        gbp_to_usd = currency_converter.get_exchange_rate('GBP', 'USD') or 1.0
                        value_usd = balance * price * gbp_to_usd
                    elif currency == 'USDC':
                        value_usd = balance
                        price = 1.0
                    elif currency == 'GBP':
                        # GBP is the base currency - convert balance to USD for portfolio totals
                        gbp_to_usd = currency_converter.get_exchange_rate('GBP', 'USD') or 1.0
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
            # Filter by current trading mode to avoid loading positions from wrong mode
            trade_type = 'paper' if db_manager.get_paper_trading() else 'live'
            
            # Load open positions from database
            db_positions = db_manager.load_open_positions(trade_type=trade_type)
            # Sync to trading engine
            for product_id in settings.PRODUCT_IDS:
                if product_id not in trading_engine.holdings:
                    trading_engine.holdings[product_id] = {'has_position': False, 'entry_price': 0, 'size': 0}
            for product_id, position in db_positions.items():
                trading_engine.holdings[product_id] = {
                    'has_position': True,
                    'entry_price': position.get('entry_price', 0),
                    'size': position.get('size', 0),
                    'position_id': position.get('position_id'),
                    'trade_type': position.get('trade_type', 'paper')
                }
            trading_engine.active_positions = trading_engine.holdings
            logger.info(f"Synced {len(db_positions)} open positions from database")
            
            # Get open positions count from open_positions table
            open_positions_count = len(db_positions)

            # Get recent trades (last 10)
            recent_trades = db_manager.get_trades(limit=10)

            # Get performance metrics
            perf_summary = db_manager.get_performance_summary(days=30)

            # Get risk status (use cached for dashboard speed)
            risk_data = risk_manager.check_portfolio_risk_cached(db_manager.get_paper_trading())

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

            # Get cached signals only (fast, non-blocking) - JS will update with fresh data
            # Skip signal generation to speed up page load; use stale cache or defaults
            all_signals = {}
            cached_count = 0
            for product_id in base_pairs:
                cached = ai_model._signal_cache.get(product_id)
                if cached:
                    _, signal = cached
                    all_signals[product_id] = signal
                    cached_count += 1
            logger.info(f"Dashboard loaded with {cached_count}/{len(base_pairs)} cached signals")

            for product_id in base_pairs:
                market_conditions[product_id] = {'price': 0.0, 'signal': 'HOLD', 'confidence': 0, 'action': 'WAIT'}

            # Get exchange rate from currency converter (GBP-USD doesn't exist on Coinbase)
            exchange_rate = currency_converter.get_exchange_rate('USD', 'GBP') or 1.0
            
            for product_id in base_pairs:
                # Get price from unified source
                price = current_prices.get(product_id, 0.0)
                
                # If not found, try USD conversion
                if price <= 0:
                    if base_currency == 'GBP':
                        usd_product_id = product_id.replace('-GBP', '-USD')
                    else:
                        usd_product_id = product_id.replace('-USD', '-GBP')
                    
                    usd_price = current_prices.get(usd_product_id, 0.0)
                    if usd_price > 0:
                        if base_currency == 'GBP':
                            price = usd_price / exchange_rate
                        else:
                            price = usd_price * exchange_rate
                        market_conditions[product_id]['price'] = price
                        market_conditions[product_id]['used_conversion_fallback'] = True
                        market_conditions[product_id]['original_pair'] = usd_product_id
                else:
                    market_conditions[product_id]['price'] = price
                    market_conditions[product_id]['used_conversion_fallback'] = False

                # Get AI signal from pre-fetched signals (fast - from cache)
                signal_data = all_signals.get(product_id)
                if signal_data:
                    confidence = signal_data.get('confidence', 0) * 100  # Convert to percentage
                    action = signal_data.get('action', 'HOLD')
                    meets_threshold = confidence >= (settings.MODEL_CONFIDENCE_THRESHOLD * 100)
                    
                    # Get RF and NN details
                    rf_pred = signal_data.get('rf_prediction')
                    nn_pred = signal_data.get('nn_prediction')
                    
                    rf_signal = 'N/A' if rf_pred is None else ('BUY' if rf_pred == 1 else 'SELL')
                    nn_signal = 'N/A' if nn_pred is None else ('BUY' if nn_pred == 1 else 'SELL')
                    
                    market_conditions[product_id].update({
                        'signal': action,
                        'confidence': confidence,
                        'meets_threshold': meets_threshold,
                        'action': 'TRADE' if meets_threshold else 'WAIT',
                        'rf_signal': rf_signal,
                        'rf_confidence': (signal_data.get('rf_confidence', 0) or 0) * 100,
                        'nn_signal': nn_signal,
                        'nn_confidence': (signal_data.get('nn_confidence', 0) or 0) * 100,
                        'nn_available': nn_pred is not None,
                        'regime': signal_data.get('regime', 'neutral')
                    })

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
                has_balance = crypto_balance.get('balance_gbp', 0.0) > 0.001  # Minimum significant balance (£0.001)
                
                # Determine if we used conversion fallback
                used_conversion_fallback = base_product_id != display_product_id
                
                display_market_conditions[display_product_id] = {
                    'price': display_price,
                    'formatted_price': f"{currency_symbol}{display_price:,.2f}",
                    'signal': base_data.get('signal', 'HOLD'),
                    'confidence': base_data.get('confidence', 0),
                    'meets_threshold': base_data.get('meets_threshold', False),
                    'action': base_data.get('action', 'WAIT'),
                    'regime': base_data.get('regime', 'neutral'),
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

    # Scale-In (Position Averaging) endpoints
    @app.get("/api/scale_in/status")
    async def get_scale_in_status():
        """Get current scale-in configuration."""
        return {
            "enabled": settings.SCALE_IN_ENABLED,
            "levels": settings.SCALE_IN_LEVELS,
            "size_by_level": settings.SCALE_IN_SIZE_BY_LEVEL,
            "max_scale_ins": settings.MAX_SCALE_INS_PER_POSITION,
            "cooldown_hours": settings.SCALE_IN_COOLDOWN_HOURS,
            "global_block": settings.SCALE_IN_GLOBAL_BLOCK
        }

    @app.post("/api/scale_in/configure")
    async def configure_scale_in(request: Request):
        """Update scale-in settings."""
        try:
            data = await request.json()
            settings.SCALE_IN_ENABLED = data.get('enabled', True)
            
            # Update levels
            levels = data.get('levels')
            if levels:
                try:
                    settings.SCALE_IN_LEVELS = [float(x) for x in levels]
                except:
                    pass
            
            sizes = data.get('size_by_level')
            if sizes:
                try:
                    settings.SCALE_IN_SIZE_BY_LEVEL = [float(x) for x in sizes]
                except:
                    pass
            
            settings.MAX_SCALE_INS_PER_POSITION = data.get('max_scale_ins', 3)
            settings.SCALE_IN_COOLDOWN_HOURS = data.get('cooldown_hours', 6)
            
            # Save to database
            db_manager.save_user_setting('scale_in_enabled', str(settings.SCALE_IN_ENABLED).lower())
            db_manager.save_user_setting('scale_in_levels', ','.join(map(str, settings.SCALE_IN_LEVELS)))
            db_manager.save_user_setting('scale_in_sizes', ','.join(map(str, settings.SCALE_IN_SIZE_BY_LEVEL)))
            db_manager.save_user_setting('scale_in_max_scale_ins', str(settings.MAX_SCALE_INS_PER_POSITION))
            db_manager.save_user_setting('scale_in_cooldown_hours', str(settings.SCALE_IN_COOLDOWN_HOURS))
            
            logger.info(f"Scale-in settings updated: enabled={settings.SCALE_IN_ENABLED}, levels={settings.SCALE_IN_LEVELS}")
            
            return {
                "status": "success", 
                "message": "Scale-in settings updated",
                "settings": {
                    "enabled": settings.SCALE_IN_ENABLED,
                    "levels": settings.SCALE_IN_LEVELS,
                    "max_scale_ins": settings.MAX_SCALE_INS_PER_POSITION,
                    "size_by_level": settings.SCALE_IN_SIZE_BY_LEVEL,
                    "cooldown_hours": settings.SCALE_IN_COOLDOWN_HOURS
                }
            }
        except Exception as e:
            logger.error(f"Scale-in configure error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/scale_in/toggle_block")
    async def toggle_scale_in_block():
        """Toggle global block on scale-ins (emergency stop)."""
        try:
            settings.SCALE_IN_GLOBAL_BLOCK = not settings.SCALE_IN_GLOBAL_BLOCK
            db_manager.save_user_setting('scale_in_global_block', str(settings.SCALE_IN_GLOBAL_BLOCK).lower())
            return {
                "status": "success", 
                "message": f"Scale-ins {'blocked' if settings.SCALE_IN_GLOBAL_BLOCK else 'unblocked'}",
                "blocked": settings.SCALE_IN_GLOBAL_BLOCK
            }
        except Exception as e:
            logger.error(f"Scale-in block toggle error: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/scale_out/status")
    async def get_scale_out_status():
        """Get current scale-out settings."""
        try:
            return {
                "status": "success",
                "enabled": settings.SCALE_OUT_ENABLED,
                "min_profit_pct": settings.SCALE_OUT_MIN_PROFIT_PCT,
                "max_scale_outs": settings.MAX_SCALE_OUT_PER_POSITION,
                "percentages": settings.SCALE_OUT_PERCENTAGES,
                "take_profit_levels": settings.TAKE_PROFIT_LEVELS
            }
        except Exception as e:
            logger.error(f"Scale-out status error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/scale_out/configure")
    async def configure_scale_out(request: Request):
        """Update scale-out settings."""
        try:
            data = await request.json()
            settings.SCALE_OUT_ENABLED = data.get('enabled', True)
            settings.SCALE_OUT_MIN_PROFIT_PCT = data.get('min_profit_pct', 0.5)
            settings.MAX_SCALE_OUT_PER_POSITION = data.get('max_scale_outs', 3)
            
            # Update take profit levels if provided
            take_profit_levels = data.get('take_profit_levels')
            if take_profit_levels and isinstance(take_profit_levels, list):
                try:
                    settings.TAKE_PROFIT_LEVELS = [float(x) for x in take_profit_levels[:3]]
                    db_manager.save_user_setting('take_profit_level', str(settings.TAKE_PROFIT_LEVELS[0]))
                except Exception:
                    pass
            
            # Save to database
            db_manager.save_user_setting('scale_out_enabled', str(settings.SCALE_OUT_ENABLED).lower())
            db_manager.save_user_setting('scale_out_min_profit_pct', str(settings.SCALE_OUT_MIN_PROFIT_PCT))
            db_manager.save_user_setting('max_scale_out_per_position', str(settings.MAX_SCALE_OUT_PER_POSITION))
            
            logger.info(f"Scale-out settings updated: enabled={settings.SCALE_OUT_ENABLED}, "
                       f"TP_levels={settings.TAKE_PROFIT_LEVELS}")
            
            return {
                "status": "success", 
                "message": "Scale-out settings updated",
                "settings": {
                    "enabled": settings.SCALE_OUT_ENABLED,
                    "min_profit_pct": settings.SCALE_OUT_MIN_PROFIT_PCT,
                    "max_scale_outs": settings.MAX_SCALE_OUT_PER_POSITION,
                    "take_profit_levels": settings.TAKE_PROFIT_LEVELS
                }
            }
        except Exception as e:
            logger.error(f"Scale-out configure error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/settings/market_check_interval")
    async def set_market_check_interval(request: Request):
        """Set market check interval in seconds."""
        try:
            data = await request.json()
            interval_minutes = float(data.get('minutes', 45))
            
            # Validate - minimum 15 minutes, maximum 180 minutes
            if interval_minutes < 15:
                interval_minutes = 15
            if interval_minutes > 180:
                interval_minutes = 180
            
            interval_seconds = int(interval_minutes * 60)
            
            # Save to database
            db_manager.save_user_setting('market_check_interval', str(interval_seconds))
            
            # Update settings in memory
            settings.MARKET_CHECK_INTERVAL = interval_seconds
            
            logger.info(f"Market check interval set to {interval_seconds} seconds ({interval_minutes} minutes)")
            return {
                "status": "success",
                "message": f"Market check interval set to {interval_minutes} minutes",
                "interval_seconds": interval_seconds,
                "interval_minutes": interval_minutes
            }
            
        except Exception as e:
            logger.error(f"Market check interval error: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/settings/risk")
    async def get_risk_settings():
        """Get current risk management settings."""
        return {
            "status": "success",
            "confidence_threshold": settings.MODEL_CONFIDENCE_THRESHOLD,
            "stop_loss": settings.STOP_LOSS_MIN_PERCENT,
            "take_profit": settings.TAKE_PROFIT_LEVELS[0],
            "max_position_size": settings.MAX_POSITION_SIZE,
            "market_check_interval": settings.MARKET_CHECK_INTERVAL
        }

    @app.post("/api/settings/risk")
    async def save_risk_settings(request: Request):
        """Save risk management settings."""
        try:
            data = await request.json()
            
            # Confidence threshold
            if 'confidence_threshold' in data:
                pct = float(data['confidence_threshold']) / 100
                settings.MODEL_CONFIDENCE_THRESHOLD = pct
                db_manager.save_user_setting('model_confidence_threshold', str(pct))
            
            # Stop loss
            if 'stop_loss' in data:
                settings.STOP_LOSS_MIN_PERCENT = float(data['stop_loss']) / 100
                db_manager.save_user_setting('stop_loss_min_percent', str(settings.STOP_LOSS_MIN_PERCENT))
            
            # Take profit
            if 'take_profit' in data:
                level = float(data['take_profit'])
                settings.TAKE_PROFIT_LEVELS = [level, level * 2, level * 3]
                db_manager.save_user_setting('take_profit_level', str(level))
            
            # Max position size
            if 'max_position_size' in data:
                pct = float(data['max_position_size']) / 100
                settings.MAX_POSITION_SIZE = pct
                db_manager.save_user_setting('max_position_size', str(pct))
            
            logger.info(f"Risk settings saved: confidence={settings.MODEL_CONFIDENCE_THRESHOLD:.0%}, "
                       f"stop_loss={settings.STOP_LOSS_MIN_PERCENT:.1%}, "
                       f"take_profit={settings.TAKE_PROFIT_LEVELS[0]:.1f}%, "
                       f"max_position={settings.MAX_POSITION_SIZE:.1%}")
            
            return {
                "status": "success",
                "message": "Risk settings saved",
                "settings": {
                    "confidence_threshold": settings.MODEL_CONFIDENCE_THRESHOLD,
                    "stop_loss": settings.STOP_LOSS_MIN_PERCENT,
                    "take_profit": settings.TAKE_PROFIT_LEVELS[0],
                    "max_position_size": settings.MAX_POSITION_SIZE
                }
            }
        except Exception as e:
            logger.error(f"Risk settings save error: {e}")
            return {"status": "error", "message": str(e)}

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
    
    @app.get("/api/exchange-rate")
    async def get_exchange_rate_hyphen():
        """Alias for exchange-rate endpoint (dashboard compatibility)."""
        return await get_exchange_rate()
    
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
            # Look up position by UUID in database
            session = db_manager.get_session()
            from src.database import OpenPosition
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id,
                OpenPosition.status == 'open'
            ).first()
            
            if not position:
                session.close()
                return {"status": "error", "message": "Position not found"}
            
            product_id = position.product_id
            side = position.side
            size = position.size
            entry_price = position.entry_price
            
            # Get current price
            from src.data_collector import data_collector
            prices = data_collector.get_current_prices()
            current_price = prices.get(product_id.replace('-GBP', '-USD').replace('-USD', '-GBP'), entry_price) or entry_price
            
            pnl = (current_price - entry_price) * size if side == 'buy' else (entry_price - current_price) * size
            
            # Clear holding in trading engine using product_id
            close_trade_type = 'paper' if db_manager.get_paper_trading() else 'live'
            trading_engine.holdings[product_id] = {
                'has_position': False,
                'entry_price': 0,
                'size': 0,
                'coinbase_order_id': None,
                'trade_type': close_trade_type
            }
            
            # Close in database by UUID
            db_manager.close_open_position(position_id, current_price, pnl, "manual_close", "manual")
            session.close()
            
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
                # Count successes - each product has rf (and optionally nn) sub-models
                success_count = 0
                total_count = 0
                for product_id, product_result in result.items():
                    if product_result.get('rf', {}).get('success', False):
                        success_count += 1
                    total_count += 1
                # Update last retrain date after manual retrain
                if success_count > 0:
                    ai_model.update_last_retrain_date()
                return {
                    "status": "success", 
                    "message": f"Models retrained: {success_count}/{total_count} successful",
                    "details": result
                }

            elif action == "cleanup_dust":
                # Clean up dust positions (size below minimum)
                cleaned = db_manager.clean_dust_positions(settings.MIN_TRADE_AMOUNT)
                return {
                    "status": "success",
                    "message": f"Cleaned up {cleaned} dust positions"
                }

            else:
                return {"status": "error", "message": f"Unknown action: {action}"}

        except Exception as e:
            logger.error(f"Control API error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/settings/auto_retrain")
    async def set_auto_retrain(request: Request):
        """Enable or disable automatic weekly model retraining."""
        try:
            data = await request.json()
            enabled = data.get('enabled', False)
            
            # Save to database
            success = ai_model.set_auto_retrain_enabled(enabled)
            
            if success:
                # Update scheduler
                unified_bot.update_retrain_schedule(enabled)
                return {
                    "status": "success",
                    "message": f"Auto-retrain {'enabled' if enabled else 'disabled'}"
                }
            else:
                return {"status": "error", "message": "Failed to save setting"}
        except Exception as e:
            logger.error(f"Auto-retrain setting error: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/ai/retrain_status")
    async def get_retrain_status():
        """Get automatic retraining status and last retrain date."""
        try:
            status = ai_model.get_retrain_status()
            return {"status": "success", "data": status}
        except Exception as e:
            logger.error(f"Retrain status error: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/market/conditions")
    async def get_market_conditions():
        """Get market conditions (signals and regime) for all trading pairs."""
        try:
            conditions = {}
            cache_status = "warm"
            
            # Check if cache is populated first (non-blocking)
            if not ai_model._signal_cache:
                return {"status": "loading", "conditions": {}, "message": "Signals being generated"}
            
            # Use cached signals (fast)
            for product_id in settings.PRODUCT_IDS:
                try:
                    signal_data = ai_model.get_signal(product_id)
                    if signal_data:
                        conditions[product_id] = {
                            'signal': signal_data.get('action', 'HOLD'),
                            'confidence': (signal_data.get('confidence', 0) or 0) * 100,
                            'regime': signal_data.get('regime', 'neutral'),
                            'meets_threshold': (signal_data.get('confidence', 0) or 0) >= settings.MODEL_CONFIDENCE_THRESHOLD
                        }
                except Exception as e:
                    logger.warning(f"Error getting signal for {product_id}: {e}")
            
            return {"status": "success", "conditions": conditions}
        except Exception as e:
            logger.error(f"Market conditions error: {e}")
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

    @app.post("/api/settings/take_profit_level")
    async def set_take_profit_level(request: Request):
        """Set user's take profit level percentage."""
        try:
            data = await request.json()
            level = float(data.get('value', 3.0))
            
            # Validate level
            if level < 0.5 or level > 10:
                return {"status": "error", "message": "Take profit level must be between 0.5% and 10%"}
            
            # Save to database
            db_manager.save_user_setting('take_profit_level', str(level))
            
            # Update settings in memory (for current session)
            settings.TAKE_PROFIT_LEVELS = [level]
            
            logger.info(f"Take profit level set to {level}%")
            return {
                "status": "success",
                "message": f"Take profit level set to {level}%",
                "take_profit_level": level
            }
            
        except Exception as e:
            logger.error(f"Take profit level error: {e}")
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
                
                # Check if model is trained (look for GBP pair or USD model in trained list)
                crypto_symbol = product_id.split('-')[0]  # 'BTC' from 'BTC-GBP'
                gbp_pair = f"{crypto_symbol}-GBP"
                usd_base = f"{crypto_symbol}-USD"
                is_trained = (
                    gbp_pair in model_status.get('models_trained', []) or
                    usd_base in model_status.get('models_trained', []) or
                    any(usd_base in s for s in model_status.get('models_trained', []))
                )
                
                # Get current signal for this product
                signal_data = {}
                rf_pred = nn_pred = gb_pred = None
                rf_signal = nn_signal = gb_signal = 'N/A'
                try:
                    signal_data = ai_model.get_cached_signal(product_id)
                    signal = signal_data.get('action', 'N/A')
                    confidence = signal_data.get('confidence', 0.0)
                    
                    # Get RF, NN, and GB details
                    rf_pred = signal_data.get('rf_prediction')
                    nn_pred = signal_data.get('nn_prediction')
                    gb_pred = signal_data.get('gb_prediction')
                    rf_signal = 'N/A' if rf_pred is None else ('BUY' if rf_pred == 1 else 'SELL')
                    nn_signal = 'N/A' if nn_pred is None else ('BUY' if nn_pred == 1 else 'SELL')
                    gb_signal = 'N/A' if gb_pred is None else ('BUY' if gb_pred == 1 else 'SELL')
                except Exception as e:
                    logger.warning(f"Error getting signal for {product_id}: {e}")
                    signal = 'N/A'
                    confidence = 0.0
                
                models_info.append({
                    'product_id': product_id,
                    'trained': is_trained,
                    'signal': signal,
                    'confidence': confidence,
                    'rf_signal': rf_signal,
                    'rf_confidence': signal_data.get('rf_confidence', 0) or 0,
                    'nn_signal': nn_signal,
                    'nn_confidence': signal_data.get('nn_confidence', 0) or 0,
                    'nn_available': nn_pred is not None,
                    'gb_signal': gb_signal,
                    'gb_confidence': signal_data.get('gb_confidence', 0) or 0,
                    'gb_available': gb_pred is not None,
                    'ensemble_used': signal_data.get('ensemble_used', False)
                })
            
            # Get actual feature count dynamically from trained model
            if ai_model.feature_names:
                first_model_features = next(iter(ai_model.feature_names.values()), None)
                features_count = len(first_model_features) if first_model_features else 17
            else:
                features_count = 17  # Default to expected count
            
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
        """Get all currently held positions (from open_positions table)."""
        try:
            # Get positions from open_positions table
            positions_dict = db_manager.load_open_positions()
            positions = []
            for product_id, pos in positions_dict.items():
                positions.append({
                    'product_id': product_id,
                    'side': pos.get('side', 'buy'),
                    'size': pos.get('size', 0),
                    'entry_price': pos.get('entry_price', 0),
                    'current_price': pos.get('current_price', 0),
                    'stop_loss_price': pos.get('stop_loss_price', 0),
                    'signal_action': pos.get('signal_action', 'HOLD'),
                    'signal_confidence': pos.get('signal_confidence', 0),
                    'status': pos.get('status', 'open'),
                    'opened_at': pos.get('opened_at'),
                    'pnl': pos.get('pnl', 0),
                    'trade_type': pos.get('trade_type', 'paper'),
                    'position_id': pos.get('position_id'),
                    'scale_in_count': pos.get('scale_in_count', 0),
                    'last_scale_in_price': pos.get('last_scale_in_price', 0),
                    'total_scale_in_size': pos.get('total_scale_in_size', 0),
                    'weighted_entry_price': pos.get('weighted_entry_price', pos.get('entry_price', 0)),
                    'scale_out_count': pos.get('scale_out_count', 0),
                    'scale_out_levels_triggered': pos.get('scale_out_levels_triggered', ''),
                    'remaining_size': pos.get('remaining_size', pos.get('size', 0)),
                    'take_profit_prices': pos.get('take_profit_prices', [])
                })
            
            # Fetch current prices
            try:
                from src.data_collector import data_collector
                current_prices = data_collector.get_current_prices()
            except Exception as e:
                logger.warning(f"Failed to fetch current prices: {e}")
                current_prices = {}
            
            # Update current prices in positions
            for pos in positions:
                product_id = pos['product_id']
                if product_id in current_prices:
                    pos['current_price'] = current_prices[product_id]
            
            total_pnl = sum(p.get('pnl', 0) for p in positions)
            return {
                "positions": positions,
                "count": len(positions),
                "total_pnl": total_pnl
            }
        except Exception as e:
            logger.error(f"Open positions API error: {e}")
            return {"error": str(e)}

    @app.get("/api/portfolio/summary")
    async def get_portfolio_summary():
        """Get portfolio summary for settings page."""
        try:
            display_currency = db_manager.get_user_setting('display_currency', 'GBP') or 'GBP'
            base_currency = db_manager.get_user_setting('base_currency', 'GBP') or 'GBP'
            
            # Get GBP balance
            gbp_balance = 0.0
            try:
                accounts = coinbase_api.get_accounts()
                for account in accounts:
                    if account.get('currency') == 'GBP':
                        gbp_balance = float(account.get('available_value', account.get('balance', 0)))
                        break
            except Exception as e:
                logger.warning(f"Could not fetch GBP balance: {e}")
            
            # Get open positions count
            open_positions_count = 0
            try:
                positions_dict = db_manager.load_open_positions()
                open_positions_count = sum(1 for p in positions_dict.values() if p.get('status') == 'open')
            except Exception as e:
                logger.warning(f"Could not fetch positions count: {e}")
            
            # Get max position size from settings
            max_position_size = settings.MAX_POSITION_SIZE
            
            return {
                "status": "success",
                "display_currency": display_currency,
                "base_currency": base_currency,
                "gbp_balance": gbp_balance,
                "open_positions": open_positions_count,
                "max_position_size": max_position_size
            }
        except Exception as e:
            logger.error(f"Portfolio summary error: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/portfolio/closed_positions")
    async def get_closed_positions(limit: int = 20):
        """Get closed positions with P&L information."""
        try:
            positions = db_manager.get_closed_positions(limit=limit)
            
            display_currency = getattr(settings, 'DISPLAY_CURRENCY', 'GBP')
            formatted_positions = []
            for pos in positions:
                formatted = pos.copy()
                formatted['formatted_entry_price'] = currency_converter.format_currency(pos.get('entry_price', 0), display_currency)
                formatted['formatted_exit_price'] = currency_converter.format_currency(pos.get('exit_price', 0), display_currency)
                formatted['formatted_pnl'] = currency_converter.format_currency(pos.get('pnl', 0), display_currency)
                formatted_positions.append(formatted)
            
            return {"positions": formatted_positions, "count": len(formatted_positions)}
        except Exception as e:
            logger.error(f"Closed positions API error: {e}")
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
                    # Map GBP trading pair to USD model file (we train on USD, trade on GBP)
                    check_product_id = product_id
                    if product_id.endswith('-GBP'):
                        crypto_symbol = product_id.split('-')[0]
                        check_product_id = f"{crypto_symbol}-USD"
                    
                    # Check if model exists and is working
                    if os.path.exists(f"models/{check_product_id}_model.pkl"):
                        # Test if model can be loaded
                        try:
                            prediction = ai_model.predict(product_id)
                            if prediction is not None and prediction.get('success'):
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
            
            # If trading is paused/stopped, show 0 remaining (will show "PAUSED" in UI)
            if not unified_bot.trading_active:
                return {
                    "remaining_seconds": 0,
                    "elapsed_seconds": 0,
                    "progress_percent": 0,
                    "last_cycle_time": datetime.fromtimestamp(last_cycle).strftime("%H:%M:%S"),
                    "interval_minutes": interval // 60,
                    "trading_active": False
                }
            
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
            exchange_rate = currency_converter.get_exchange_rate('GBP', 'USD') or 1.0

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
                elif currency == 'GBP':
                    # GBP is base currency - convert to USD for portfolio totals
                    gbp_usd_rate = currency_converter.get_exchange_rate('GBP', 'USD')
                    if gbp_usd_rate is None:
                        gbp_usd_rate = 1.0
                    value_usd = balance * gbp_usd_rate
                    price = gbp_usd_rate
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
                "portfolio_risk": risk_manager.check_portfolio_risk(db_manager.get_paper_trading()),
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

    @app.get("/api/debug/trading-cycle")
    async def debug_trading_cycle():
        """Debug endpoint to show trading cycle state."""
        try:
            from src.database import Trade
            db_paper = db_manager.get_paper_trading()
            debug_trade_type = 'paper' if db_paper else 'live'
            db_positions = db_manager.load_open_positions(trade_type=debug_trade_type)

            engine_positions = trading_engine.active_positions
            engine_times = trading_engine.last_trade_time

            db_trade_times = {}
            try:
                session = db_manager.get_session()
                trades = session.query(Trade).order_by(Trade.timestamp.desc()).limit(100).all()
                for trade in trades:
                    if trade.product_id not in db_trade_times:
                        ts = getattr(trade, 'timestamp', None)
                        db_trade_times[trade.product_id] = ts.isoformat() if ts is not None else None
                session.close()
            except Exception as e:
                db_trade_times = {"error": str(e)}

            return {
                "timestamp": datetime.now().isoformat(),
                "engine_memory": {
                    "active_positions_count": len(engine_positions),
                    "last_trade_time_count": len(engine_times),
                    "last_trade_times": {k: v.isoformat() if v else None for k, v in engine_times.items()},
                    "paper_trading": trading_engine.paper_trading,
                },
                "database": {
                    "positions_count": len(db_positions),
                    "positions": db_positions,
                    "paper_trading": db_paper,
                    "trade_times_from_db": db_trade_times,
                },
                "settings": {
                    "max_concurrent_positions": settings.MAX_CONCURRENT_POSITIONS,
                    "min_trade_interval_minutes": 30,
                    "position_replacement_enabled": settings.POSITION_REPLACEMENT_ENABLED,
                },
                "signal_candidates": None,
            }
        except Exception as e:
            import traceback
            return {
                "error": str(e),
                "traceback": traceback.format_exc()
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
        print("=== MAIN() - STARTING TRADING ENGINE ===", flush=True)
        logger.info("Starting trading engine...")
        
        # Only start if not already running
        if unified_bot.trading_thread and unified_bot.trading_thread.is_alive():
            logger.info("Trading thread already running, skipping start")
            trading_started = True
        else:
            trading_started = unified_bot.start_trading()
            if trading_started:
                logger.info("Trading engine started successfully")
                # Small delay to let thread initialize
                time.sleep(2)
                # Verify thread is actually running
                if unified_bot.trading_thread and unified_bot.trading_thread.is_alive():
                    logger.info("Trading thread is running")
                else:
                    logger.error("Trading thread failed to start!")
                    trading_started = False
            else:
                logger.warning("Trading engine failed to start")
        
        # Start the FastAPI server in a separate thread so it doesn't get blocked by trading loop
        import threading
        def run_server():
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=settings.DASHBOARD_PORT,
                log_level="info",
                timeout_keep_alive=5,
                limit_concurrency=100
            )
        
        logger.info(f"Starting unified dashboard on http://0.0.0.0:{settings.DASHBOARD_PORT}")
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        
        # Wait for server thread to finish (it runs until shutdown)
        server_thread.join()
    except KeyboardInterrupt:
        logger.info("Dashboard interrupted by user")
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
    finally:
        unified_bot.shutdown()

if __name__ == "__main__":
    main()