"""
Web Dashboard for Crypto Trading Bot

Provides a web interface to monitor bot performance, view trades,
manage settings, and control bot operations.

Educational Notes:
- FastAPI provides automatic API documentation and high performance
- Jinja2 templates allow dynamic HTML generation
- RESTful API design separates frontend from backend
- Web dashboards enable remote monitoring and control
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from config.settings import settings
from src.database import db_manager
from src.coinbase_api import coinbase_api
from src.ai_model import ai_model
from src.risk_manager import risk_manager
from src.trading_engine import trading_engine
from src.data_collector import data_collector
from src.balance_manager import balance_manager

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Crypto Trading Bot Dashboard",
    description="Monitor and control your AI-powered crypto trading bot",
    version="1.0.0"
)

# Setup templates and static files
templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(templates_dir))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Create directories if they don't exist
templates_dir.mkdir(exist_ok=True)
static_dir.mkdir(exist_ok=True)


# Temporarily disabled to use main.py route
# @app.get("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page showing overview of bot status."""
    try:
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
            current_prices = {}  # Not needed for paper trading
        else:
            # Live trading: show real Coinbase balances for ALL currencies with assets
            accounts = coinbase_api.get_accounts()
            current_prices = data_collector.get_current_prices()

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

                # Only add currencies that need price lookups (not USD or USDC)
                if currency not in ['USD', 'USDC']:
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
                elif currency == 'USDC':
                    # USDC is a stablecoin pegged to $1 USD
                    value_usd = balance * 1.0
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

        # Enhanced logging for portfolio debugging
        logger.info(f"Portfolio Debug - USD Total: ${total_value_usd:.2f}")
        gbp_rate = currency_converter.get_exchange_rate('USD', 'GBP')
        logger.info(f"Portfolio Debug - Exchange Rate: 1 USD = {gbp_rate:.4f} GBP")
        logger.info(f"Portfolio Debug - GBP Total: £{total_value:.2f}")
        asset_summary = [(item['currency'], f"${item.get('value_usd', 0):.2f}") for item in portfolio[:5]]
        logger.info(f"Portfolio Debug - Individual Assets: {asset_summary}")

        # Format current prices appropriately
        formatted_current_prices = {}
        for product_id, price in current_prices.items():
            base, quote = product_id.split('-')
            if quote in ['USD', 'GBP', 'EUR']:
                formatted_current_prices[product_id] = currency_converter.format_currency(price, quote)
            else:
                formatted_current_prices[product_id] = f"{price:.6f} {product_id}"

        # Get other status data (use same total_value_usd as individual breakdown)
        portfolio_data = {
            'portfolio_value': total_value,
            'daily_pnl': 0.0,  # Could calculate actual P&L later
            'risk_status': 'normal'
        }
        engine_status = trading_engine.get_status()
        model_status = ai_model.get_model_status()

        # Create standardized models_info for template
        def get_models_info_for_template(model_status):
            """Convert model status to template-friendly format."""
            models_trained_count = len(model_status.get('models_trained', []))
            
            # Helper to get model-specific info with defaults
            def get_model_info(model_prefix):
                return {
                    'ready': model_status.get(f'{model_prefix}_model_ready', False),
                    'status': model_status.get(f'{model_prefix}_model_status', 'not_started'),
                    'accuracy': model_status.get(f'{model_prefix}_model_accuracy', 0),
                    'trained_on': model_status.get(f'{model_prefix}_model_trained_on', 'Not trained'),
                    'progress': model_status.get(f'{model_prefix}_model_progress', 0)
                }
            
            return {
                'models_trained': models_trained_count,
                'btc_model_ready': model_status.get('btc_model_ready', False),
                'btc_model_status': model_status.get('btc_model_status', 'not_started'),
                'btc_model_accuracy': model_status.get('btc_model_accuracy', 0),
                'btc_model_trained_on': model_status.get('btc_model_trained_on', 'Not trained'),
                'btc_model_progress': model_status.get('btc_model_progress', 0),
                'eth_model_ready': model_status.get('eth_model_ready', False),
                'eth_model_status': model_status.get('eth_model_status', 'not_started'),
                'eth_model_accuracy': model_status.get('eth_model_accuracy', 0),
                'eth_model_trained_on': model_status.get('eth_model_trained_on', 'Not trained'),
                'eth_model_progress': model_status.get('eth_model_progress', 0),
                'alt_model_ready': model_status.get('alt_model_ready', False),
                'alt_model_status': model_status.get('alt_model_status', 'not_started'),
                'alt_model_accuracy': model_status.get('alt_model_accuracy', 0),
                'alt_model_trained_on': model_status.get('alt_model_trained_on', 'Not trained'),
                'alt_model_progress': model_status.get('alt_model_progress', 0)
            }

        # Get recent trades (last 10)
        recent_trades = db_manager.get_trades(limit=10)

        # Calculate summary stats
        total_trades = len(recent_trades) if recent_trades else 0
        winning_trades = sum(1 for trade in recent_trades if trade.get('pnl', 0) > 0) if recent_trades else 0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # Get performance metrics
        perf_summary = db_manager.get_performance_summary(days=30)

        # Build market conditions for AI signals
        market_conditions = {}
        for product_id in settings.PRODUCT_IDS:  # All pairs for complete monitoring
            try:
                signal = ai_model.get_signal(product_id)
                price = current_prices.get(product_id, 0)
                base, quote = product_id.split('-')
                if quote in ['USD', 'GBP', 'EUR']:
                    formatted_price = currency_converter.format_currency(price, quote)
                else:
                    formatted_price = f"{price:.6f} {product_id}"
                market_conditions[product_id] = {
                    'product_id': product_id,
                    'signal': signal.get('action', 'HOLD'),
                    'confidence': signal.get('confidence', 0),
                    'reason': signal.get('reason', 'No signal available'),
                    'price': price,
                    'formatted_price': formatted_price,
                    'meets_threshold': signal.get('confidence', 0) >= settings.MODEL_CONFIDENCE_THRESHOLD,
                    'action': 'TRADE' if signal.get('confidence', 0) >= settings.MODEL_CONFIDENCE_THRESHOLD else 'WAIT'
                }
            except Exception as e:
                logger.error(f"Error getting signal for {product_id}: {e}")
                price = current_prices.get(product_id, 0)
                base, quote = product_id.split('-')
                if quote in ['USD', 'GBP', 'EUR']:
                    formatted_price = currency_converter.format_currency(price, quote)
                else:
                    formatted_price = f"{price:.6f} {product_id}"
                market_conditions[product_id] = {
                    'product_id': product_id,
                    'signal': 'ERROR',
                    'confidence': 0,
                    'reason': str(e),
                    'price': price,
                    'formatted_price': formatted_price,
                    'meets_threshold': False,
                    'action': 'ERROR'
                }

        # Format portfolio data with currency conversion

        # Format portfolio data with currency conversion
        converted_portfolio = []
        for item in portfolio:
            converted_item = item.copy()
            # Use value_usd if available (paper trading), otherwise value (live trading)
            item_value = item.get('value_usd', item.get('value', 0))
            converted_item['value'] = currency_converter.convert_amount(item_value, 'USD', display_currency)
            converted_item['formatted_value'] = currency_converter.format_currency(converted_item['value'], display_currency)
            # Balance should show actual amount, not converted value
            balance = item.get('balance', 0)
            converted_item['formatted_balance'] = f"{balance:.6f} {item['currency']}"
            converted_portfolio.append(converted_item)

        # Format other currency values
        formatted_total = currency_converter.format_currency(portfolio_data.get('portfolio_value', 0), display_currency)
        formatted_daily_pnl = currency_converter.format_currency(portfolio_data.get('daily_pnl', 0), display_currency)

        context = {
            "request": request,
            "portfolio": converted_portfolio,
            "portfolio_value": portfolio_data.get('portfolio_value', 0),
            "formatted_total": formatted_total,
            "display_currency": display_currency,
            "daily_pnl": portfolio_data.get('daily_pnl', 0),
            "formatted_daily_pnl": formatted_daily_pnl,
            "risk_status": portfolio_data.get('risk_status', 'unknown'),
            "paper_trading": engine_status.get('paper_trading', True),
            "active_positions": engine_status.get('active_positions', 0),
            "models_trained": len(model_status.get('models_trained', [])),
            "models_info": get_models_info_for_template(model_status),
            "current_prices": current_prices,
            "formatted_current_prices": formatted_current_prices,
            "recent_trades": recent_trades or [],
            "total_trades": total_trades,
            "win_rate": win_rate,
            "perf_summary": perf_summary,
            "trading_active": db_manager.get_trading_active(),
            "product_ids": settings.PRODUCT_IDS,
            "market_conditions": market_conditions,
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "gbp_balance_status": balance_manager.check_gbp_balance(),
        }



        return templates.TemplateResponse("dashboard.html", context)

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request, limit: int = 50):
    """Trades history page."""
    try:
        trades = db_manager.get_trades(limit=limit)

        # Calculate statistics
        total_pnl = sum(trade.get('pnl', 0) for trade in trades) if trades else 0
        winning_trades = sum(1 for trade in trades if trade.get('pnl', 0) > 0) if trades else 0
        win_rate = (winning_trades / len(trades) * 100) if trades else 0

        context = {
            "request": request,
            "trades": trades or [],
            "total_trades": len(trades) if trades else 0,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "winning_trades": winning_trades
        }

        return templates.TemplateResponse("trades.html", context)

    except Exception as e:
        logger.error(f"Trades page error: {e}")
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/performance", response_class=HTMLResponse)
async def performance_page(request: Request):
    """Performance analytics page."""
    try:
        # Get performance data for different time periods
        periods = [7, 30, 90, 365]
        performance_data = {}

        for days in periods:
            perf = db_manager.get_performance_summary(days=days)
            performance_data[f"{days}d"] = perf

        # Get trading statistics
        all_trades = db_manager.get_trades(limit=1000)
        product_stats = {}
        if all_trades:
            # Group by product
            for trade in all_trades:
                product = trade.get('product_id', 'Unknown')
                if product not in product_stats:
                    product_stats[product] = {
                        'trades': 0,
                        'wins': 0,
                        'total_pnl': 0.0,
                        'avg_pnl': 0.0
                    }

                product_stats[product]['trades'] += 1
                pnl = trade.get('pnl', 0)
                product_stats[product]['total_pnl'] += pnl
                if pnl > 0:
                    product_stats[product]['wins'] += 1

            # Calculate averages
            for product, stats in product_stats.items():
                if stats['trades'] > 0:
                    stats['avg_pnl'] = stats['total_pnl'] / stats['trades']
                    stats['win_rate'] = (stats['wins'] / stats['trades']) * 100

        context = {
            "request": request,
            "performance_data": performance_data,
            "product_stats": product_stats,
            "total_trades": len(all_trades) if all_trades else 0
        }

        return templates.TemplateResponse("performance.html", context)

    except Exception as e:
        logger.error(f"Performance page error: {e}")
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/models", response_class=HTMLResponse)
async def models_page(request: Request):
    """AI Models status page."""
    try:
        model_status = ai_model.get_model_status()

        # Get detailed model info
        models_info = []
        for product_id in settings.PRODUCT_IDS:
            try:
                # Try to get prediction for current conditions
                signal = ai_model.get_signal(product_id)
                models_info.append({
                    'product_id': product_id,
                    'trained': product_id in model_status.get('models_trained', []),
                    'signal': signal.get('action', 'N/A'),
                    'confidence': signal.get('confidence', 0)
                })
            except:
                models_info.append({
                    'product_id': product_id,
                    'trained': product_id in model_status.get('models_trained', []),
                    'signal': 'Error',
                    'confidence': 0
                })

        context = {
            "request": request,
            "model_status": model_status,
            "models_info": models_info,
            "features_count": 14  # Number of technical indicators
        }

        return templates.TemplateResponse("models.html", context)

    except Exception as e:
        logger.error(f"Models page error: {e}")
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings and configuration page."""
    try:
        # Get user's preferred display currency
        display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'

        context = {
            "request": request,
            "display_currency": display_currency,
            "settings": {
                "max_position_size": settings.MAX_POSITION_SIZE,
                "max_daily_trades": settings.MAX_DAILY_TRADES,
                "max_concurrent_positions": settings.MAX_CONCURRENT_POSITIONS,
                "model_confidence_threshold": settings.MODEL_CONFIDENCE_THRESHOLD,
                "stop_loss_atr_multiplier": settings.STOP_LOSS_ATR_MULTIPLIER,
                "take_profit_levels": settings.TAKE_PROFIT_LEVELS,
                "max_daily_loss": settings.MAX_DAILY_LOSS,
                "market_check_interval": settings.MARKET_CHECK_INTERVAL,
                "products": settings.PRODUCT_IDS
    },
            "paper_trading": trading_engine.paper_trading,
            "trading_mode": "Paper Trading" if trading_engine.paper_trading else "Live Trading",
            "emergency_stop": settings.EMERGENCY_STOP
        }

        return templates.TemplateResponse("settings.html", context)

    except Exception as e:
        logger.error(f"Settings page error: {e}")
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


# Note: API endpoints are now handled by the unified bot in main.py


@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio composition."""
    try:
        if trading_engine.paper_trading:
            # Paper trading: return simulated portfolio
            portfolio = [
                {
                    "currency": "USD",
                    "balance": settings.PAPER_TRADING_PORTFOLIO_VALUE,
                    "price": 1.0,
                    "value": settings.PAPER_TRADING_PORTFOLIO_VALUE,
                    "percentage": 100.0
                }
            ]
            total_value = settings.PAPER_TRADING_PORTFOLIO_VALUE
        else:
            # Live trading: use real Coinbase balances for ALL currencies with assets
            accounts = coinbase_api.get_accounts()
            current_prices = data_collector.get_current_prices()

            portfolio = []
            total_value = 0.0

            # Collect all currencies that need price data
            currencies_needing_prices = set()

            for account in accounts:
                currency = account['currency']
                balance = account['available']

                # Skip zero balances
                if balance <= 0:
                    continue

                # Only add currencies that need price lookups (not USD or USDC)
                if currency not in ['USD', 'USDC']:
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
                    value = balance
                    price = 1.0
                elif f"{currency}-USD" in current_prices:
                    price = current_prices[f"{currency}-USD"]
                    value = balance * price
                else:
                    # Skip currencies without valid prices
                    continue

                # Skip very small values
                if value < settings.MIN_PORTFOLIO_VALUE_DISPLAY:
                    continue

                total_value += value

                portfolio.append({
                    "currency": currency,
                    "balance": balance,
                    "price": price,
                    "value": value,
                    "percentage": 0.0  # Will be calculated after total
                })

            # Sort portfolio by value (highest first) and calculate percentages
            portfolio.sort(key=lambda x: x["value"], reverse=True)
            for item in portfolio:
                item["percentage"] = (item["value"] / total_value * 100) if total_value > 0 else 0

        return {
            "portfolio": portfolio,
            "total_value": total_value,
            "last_update": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Portfolio API error: {e}")
        return {"error": str(e)}


@app.post("/api/exchange-rates/refresh")
async def refresh_exchange_rates():
    """Force refresh of exchange rates."""
    try:
        from src.currency_utils import currency_converter
        # Force refresh by clearing cache and fetching new rates
        old_timestamp = currency_converter.get_last_update()
        # Trigger a rate fetch by requesting a rate
        rate = currency_converter.get_exchange_rate('USD', 'GBP')
        new_timestamp = currency_converter.get_last_update()

        return {
            "status": "success",
            "message": "Exchange rates refreshed",
            "old_timestamp": str(old_timestamp) if old_timestamp else None,
            "new_timestamp": str(new_timestamp) if new_timestamp else None,
            "current_rate": rate
        }
    except Exception as e:
        logger.error(f"Exchange rate refresh error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/portfolio/debug")
async def portfolio_debug():
    """Debug endpoint showing detailed portfolio calculations."""
    try:
        from src.currency_utils import currency_converter

        # Get current display currency
        display_currency = db_manager.get_user_setting('display_currency', 'USD') or 'USD'

        # Get exchange rate details
        exchange_rate = currency_converter.get_exchange_rate('USD', display_currency)
        rate_timestamp = currency_converter.get_last_update()

        # Calculate rate age in minutes
        if isinstance(rate_timestamp, (int, float)) and rate_timestamp > 0:
            current_time = datetime.now().timestamp()
            rate_age_minutes = (current_time - rate_timestamp) / 60
        else:
            rate_age_minutes = None

        # Recalculate portfolio with detailed breakdown
        accounts = coinbase_api.get_accounts()
        current_prices = data_collector.get_current_prices()

        asset_breakdown = []
        total_usd = 0.0

        # Collect all currencies that need price data
        currencies_needing_prices = set()

        for account in accounts:
            currency = account['currency']
            balance = account['available']
            if balance > 0:
                # Only add currencies that need price lookups (not USD or USDC)
                if currency not in ['USD', 'USDC']:
                    currencies_needing_prices.add(currency)

        # Fetch prices for all currencies
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

        # Calculate individual asset values
        for account in accounts:
            currency = account['currency']
            balance = account['available']

            if balance <= 0:
                continue

            if currency == 'USD':
                value_usd = balance
                price = 1.0
            elif currency == 'USDC':
                # USDC is a stablecoin pegged to $1 USD
                value_usd = balance * 1.0
                price = 1.0
            elif f"{currency}-USD" in current_prices and currency != 'GBP':
                price = current_prices[f"{currency}-USD"]
                value_usd = balance * price
            elif currency == 'GBP':
                # GBP is base currency - no conversion needed
                price = 1.0
                value_usd = balance
            else:
                continue

            if value_usd < settings.MIN_PORTFOLIO_VALUE_DISPLAY:
                continue

            total_usd += value_usd
            asset_breakdown.append({
                "currency": currency,
                "balance": balance,
                "price_usd": price,
                "value_usd": value_usd,
                "value_display": currency_converter.convert_amount(value_usd, 'USD', display_currency)
            })

        total_display = currency_converter.convert_amount(total_usd, 'USD', display_currency)

        # Also calculate using per-asset conversion method for comparison
        if exchange_rate and exchange_rate > 0:
            total_per_asset = 0.0
            asset_breakdown_per_asset = []
            for account in accounts:
                currency = account['currency']
                balance = account['available']

                if balance <= 0:
                    continue

                if currency == 'USD':
                    value_display = currency_converter.convert_amount(balance, 'USD', display_currency)
                    price = 1.0
                elif f"{currency}-USD" in current_prices:
                    price = current_prices[f"{currency}-USD"]
                    value_usd = balance * price
                    value_display = currency_converter.convert_amount(value_usd, 'USD', display_currency)
                elif currency == 'GBP':
                    # Handle GBP currency specifically - use internal conversion system
                    gbp_to_usd_rate = currency_converter.get_exchange_rate('GBP', 'USD')
                    if gbp_to_usd_rate and gbp_to_usd_rate > 0:
                        # Convert GBP to USD for portfolio total (internal system)
                        value_usd = balance / gbp_to_usd_rate  # GBP → USD conversion
                        value_gbp = balance  # Keep GBP value for GBP display
                        # Display converted USD value and GBP value
                        value_display = currency_converter.format_currency(value_gbp, 'GBP', display_currency)
                    else:
                        # Fallback if conversion fails
                        value_usd = balance * 1.3  # Approximate 1 GBP = $1.30 USD
                        value_gbp = balance
                        value_display = currency_converter.format_currency(value_gbp, 'GBP', display_currency)
                else:
                    continue

                if value_display < settings.MIN_PORTFOLIO_VALUE_DISPLAY:
                    continue

                total_per_asset += value_display
                asset_breakdown_per_asset.append({
                    "currency": currency,
                    "balance": balance,
                    "price_usd": price,
                    "value_usd": balance * price if currency != 'USD' else balance,
                    "value_display": value_display
                })
        else:
            total_per_asset = total_display
            asset_breakdown_per_asset = asset_breakdown

        return {
            "timestamp": datetime.now().isoformat(),
            "display_currency": display_currency,
            "trading_mode": "paper" if trading_engine.paper_trading else "live",
            "exchange_rate": {
                "usd_to_display": exchange_rate,
                "last_updated": str(rate_timestamp) if rate_timestamp else None,
                "age_minutes": rate_age_minutes,
    },
            "calculation_methods": {
                "sum_usd_then_convert": {
                    "total_usd": total_usd,
                    "total_display": total_display,
                    "assets": asset_breakdown,
            },
                "convert_each_asset": {
                    "total_display": total_per_asset,
                    "assets": asset_breakdown_per_asset
                }
    },
            "coinbase_comparison": {
                "coinbase_reported_gbp": 11.88,  # User's reported Coinbase value
                "bot_calculated_gbp": total_display,
                "difference_gbp": total_display - 11.88,
                "difference_percent": ((total_display - 11.88) / 11.88) * 100 if 11.88 > 0 else 0,
                "possible_reasons": [
                            "Coinbase includes trading fees/commission adjustments",
                            "Different exchange rate timing/sources",
                            "Pending transactions or unsettled orders",
                            "Account-specific valuation differences"
                        ]
            }
        }

    except Exception as e:
        logger.error(f"Portfolio debug error: {e}")
        return {"status": "error", "message": f"Portfolio debug failed: {str(e)}"}


@app.get("/api/status")
async def get_status():
    """Get comprehensive trading bot status."""
    try:
        # Get trading state
        trading_active = db_manager.get_trading_active()
        paper_trading = trading_engine.paper_trading
        
        # Import currency converter for GBP handling
        from src.currency_utils import currency_converter

        # Get account info
        accounts = coinbase_api.get_accounts()
        total_balance = 0.0
        account_summary = []

        if accounts:
            for account in accounts:
                currency = account['currency']
                balance = account['available']
                # Skip phantom USD balance - only process real holdings
                if balance > 0 and not (currency == 'USD' and balance < 0.01):
                    value_usd = 0.0
                    if currency == 'USD':
                        value_usd = balance
                        total_balance += balance
                    elif currency == 'USDC':
                        # USDC is a stablecoin pegged to $1 USD
                        value_usd = balance * 1.0
                        total_balance += value_usd
                    elif currency == 'GBP':
                        # GBP is base currency - don't convert to USD again
                        value_usd = balance
                        total_balance += balance
                    else:
                        # Try to get current price for conversion
                        try:
                            product_id = f"{currency}-USD"
                            ticker = coinbase_api.get_product_ticker(product_id)
                            price = float(ticker.get('price', 0))
                            value_usd = balance * price
                            total_balance += value_usd
                        except:
                            # If price lookup fails, treat as zero value
                            value_usd = 0.0

                    account_summary.append({
                        "currency": currency,
                        "balance": balance,
                        "value_usd": value_usd
                    })

        # Get model status
        model_status = ai_model.get_model_status()
        models_info = {
            'BTC Model': {
                'ready': model_status.get('btc_model_ready', False),
                'accuracy': model_status.get('btc_model_accuracy', 0),
                'status': model_status.get('btc_model_status', 'not_started')
            },
            'ETH Model': {
                'ready': model_status.get('eth_model_ready', False),
                'accuracy': model_status.get('eth_model_accuracy', 0),
                'status': model_status.get('eth_model_status', 'not_started')
            },
            'Altcoins Model': {
                'ready': model_status.get('alt_model_ready', False),
                'accuracy': model_status.get('alt_model_accuracy', 0),
                'status': model_status.get('alt_model_status', 'not_started')
            }
        }

        # Get trade statistics
        trades = db_manager.get_trades(limit=100)
        total_trades = len(trades)
        win_rate = 0
        if total_trades > 0:
            winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
            win_rate = len(winning_trades) / total_trades * 100

        return {
            "timestamp": datetime.now().isoformat(),
                "trading": {
                    "active": trading_active,
                    "mode": "paper" if trading_engine.paper_trading else "live",
                    "max_position_size": f"{settings.MAX_POSITION_SIZE * 100}%"
                },
                "account": {
                    "total_balance_usd": round(total_balance, 2),
                    "currencies": account_summary,
                    "api_connected": len(accounts) > 0
                },
                "performance": {
                    "total_trades": total_trades,
                    "win_rate": round(win_rate, 1),
                    "models_trained": len(model_status.get('models_trained', [])),
                    "models": models_info
                },
                "system": {
                    "last_update": datetime.now().isoformat(),
                    "version": "1.0.0"
                }
            }

    except Exception as e:
        logger.error(f"Status API error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }


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

        # Place a very small test sell order (0.001 ETH) for BTC
        test_result = coinbase_api.place_market_order(
            product_id="ETH-BTC",
            side="sell",
            size=0.001
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


def run_dashboard(host: str = "0.0.0.0", port: int = 8001):
    """Run the dashboard server."""
    logger.info(f"Starting dashboard on http://{host}:{port}")
    uvicorn.run(
        "src.dashboard:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    run_dashboard()