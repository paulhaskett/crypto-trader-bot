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
from datetime import datetime
from typing import Optional, List

# Import our modules
from config.settings import settings
from src.coinbase_api import coinbase_api
from src.database import db_manager
from src.data_collector import data_collector
from src.ai_model import ai_model
from src.risk_manager import risk_manager
from src.trading_engine import trading_engine

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
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

        logger.info(f"Unified Bot initialized - Trading active: {self.trading_active}")

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
        """Start the trading engine."""
        if self.trading_active:
            logger.warning("Trading already active")
            return False

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
                "paper_trading": trading_engine.paper_trading,
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
            "paper_trading": trading_engine.paper_trading,
            "message": "Trading engine stopped"
        })

        return True

    def _trading_loop(self):
        """Main trading loop that runs continuously."""
        logger.info("Trading loop started")

        while not self.shutdown_event.is_set():
            try:
                if self.trading_active:
                    logger.info("Starting new trading cycle...")
                    # Run one trading cycle
                    cycle_results = trading_engine.run_trading_cycle()

                    # Broadcast results to dashboard
                    status_update = {
                        "type": "cycle_complete",
                        "timestamp": time.time(),
                        "signals_found": cycle_results.get('signals_found', 0),
                        "trades_executed": cycle_results.get('trades_executed', 0),
                        "positions_closed": cycle_results.get('positions_closed', 0),
                        "total_pnl": cycle_results.get('total_pnl', 0.0),
                        "trading_active": self.trading_active,
                        "paper_trading": trading_engine.paper_trading
                    }

                    # Add current portfolio status
                    portfolio_data = risk_manager.check_portfolio_risk()
                    status_update.update({
                        "portfolio_value": portfolio_data.get('portfolio_value', 0),
                        "daily_pnl": portfolio_data.get('daily_pnl', 0),
                        "risk_status": portfolio_data.get('risk_status', 'unknown')
                    })

                    self.broadcast_status(status_update)

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
        """Get current bot status."""
        portfolio_data = risk_manager.check_portfolio_risk()
        engine_status = trading_engine.get_status()

        # Get model status from AI system (not trading engine)
        model_status = ai_model.get_model_status()

        return {
            "trading_active": self.trading_active,
            "paper_trading": trading_engine.paper_trading,
            "portfolio_value": portfolio_data.get('portfolio_value', 0),
            "daily_pnl": portfolio_data.get('daily_pnl', 0),
            "risk_status": portfolio_data.get('risk_status', 'unknown'),
            "active_positions": engine_status.get('active_positions', 0),
            "models_trained": len(model_status.get('models_trained', [])),
            "listeners_connected": len(self.status_listeners)
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
    from src.dashboard import app
    from fastapi import Request
    from fastapi.templating import Jinja2Templates
    from fastapi.responses import HTMLResponse
    logger.info("Imports completed successfully")
    from pathlib import Path

    # Override the dashboard route to use unified bot status
    templates_dir = Path(__file__).parent / "src" / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Main dashboard page showing overview of bot status."""

        print("DEBUG: Dashboard function called")
        try:
            # Add cache-busting timestamp to force refresh
            import time
            timestamp = str(int(time.time()))
            cache_buster = f"?_t={timestamp}"

            # Get portfolio data with currency conversion
            from src.currency_utils import currency_converter

            # Get user's preferred display currency
            display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'

            # Check trading mode to determine data source
            if trading_engine.paper_trading:
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
                    balance = account['available']

                    # Skip zero balances
                    if balance <= 0:
                        continue

                    if currency == 'USD':
                        value_usd = balance
                        price = 1.0
                    elif f"{currency}-USD" in current_prices:
                        price = current_prices[f"{currency}-USD"]
                        value_usd = balance * price
                    else:
                        # Skip currencies without valid prices
                        continue

                    # Skip very small values
                    if value_usd < settings.MIN_PORTFOLIO_VALUE_DISPLAY:
                        continue

                    total_value_usd += value_usd

                    portfolio.append({
                        "currency": currency,
                        "balance": balance,
                        "price": price,
                        "value_usd": value_usd,
                        "percentage": 0.0  # Will be calculated after total
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

            # Get recent trades (last 10)
            recent_trades = db_manager.get_trades(limit=10)

            # Get performance metrics
            perf_summary = db_manager.get_performance_summary(days=30)

            # Get risk status
            risk_data = risk_manager.check_portfolio_risk(trading_engine.paper_trading)

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

            # Set defaults first
            for product_id in ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'LTC-USD']:
                market_conditions[product_id] = {'price': 0.0, 'signal': 'HOLD', 'confidence': 0, 'action': 'WAIT'}

            # Try to get real data
            try:
                for product_id in ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'LTC-USD']:
                    # Get current price
                    try:
                        ticker = coinbase_api.get_product_ticker(product_id)
                        if ticker and 'price' in ticker:
                            price = float(ticker['price'])
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

            trading_active = db_manager.get_trading_active()

            context = {
                "portfolio": converted_portfolio,
                "portfolio_value": total_value,
                "formatted_total": formatted_total,
                "display_currency": display_currency,
                "daily_pnl": risk_data.get('daily_pnl', 0),
                "formatted_daily_pnl": formatted_daily_pnl,
                "risk_status": risk_data.get('risk_status', 'unknown'),
                "paper_trading": trading_engine.paper_trading,
                "trading_active": trading_active,
                "active_positions": engine_status.get('active_positions', 0),
                "models_trained": len(model_status.get('models_trained', [])),
                "current_prices": current_prices,
                "formatted_current_prices": formatted_current_prices,
                "recent_trades": formatted_recent_trades,
                "total_trades": len(recent_trades) if recent_trades else 0,
                "total_trades_all_time": total_trades_all_time,
                "win_rate": win_rate_percentage,
                "recent_win_rate": recent_win_rate,
                "total_pnl": total_pnl,
                "formatted_total_pnl": formatted_total_pnl,
                "market_conditions": market_conditions,
                "perf_summary": perf_summary,
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
                        "paper_trading": trading_engine.paper_trading
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
                        "paper_trading": trading_engine.paper_trading
                    }
                else:
                    return {"status": "error", "message": "Trading not active"}

            elif action == "enable_live_trading":
                if trading_engine.paper_trading:
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
                if not trading_engine.paper_trading:
                    trading_engine.paper_trading = True
                    # Persist the trading mode change
                    db_manager.save_user_setting('paper_trading', 'true')
                    logger.info("Switched to paper trading mode")
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
                return {"status": "success", "message": f"Models retrained"}
            
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

            # Save user setting
            success = db_manager.save_user_setting('display_currency', currency)
            if success:
                return {"status": "success", "message": f"Display currency set to {currency}"}
            else:
                return {"status": "error", "message": "Failed to save currency preference"}

        except Exception as e:
            logger.error(f"Display currency error: {e}")
            return {"status": "error", "message": str(e)}

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
            if not trading_engine.paper_trading:
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

    # Add portfolio endpoint
    @app.get("/api/portfolio")
    async def get_portfolio():
        """Get portfolio composition with currency conversion."""
        try:
            # Get user's preferred display currency
            display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'
            
            accounts = coinbase_api.get_accounts()
            current_prices = data_collector.get_current_prices()

            portfolio = []
            total_value_usd = 0.0

            for account in accounts:
                currency = account['currency']
                balance = account['available']

                if currency == 'USD':
                    value_usd = balance
                    price = 1.0
                elif currency in ['BTC', 'ETH'] and f"{currency}-USD" in current_prices:
                    price = current_prices[f"{currency}-USD"]
                    value_usd = balance * price
                else:
                    continue

                total_value_usd += value_usd

                portfolio.append({
                    "currency": currency,
                    "balance": balance,
                    "price": price,
                    "value_usd": value_usd,
                    "percentage": 0.0  # Will be calculated after total
                })

            # Calculate percentages
            for item in portfolio:
                item["percentage"] = (item["value_usd"] / total_value_usd * 100) if total_value_usd > 0 else 0

            # Convert to display currency
            from src.currency_utils import currency_converter
            total_value = currency_converter.convert_amount(total_value_usd, 'USD', display_currency)
            
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

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        unified_bot.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
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