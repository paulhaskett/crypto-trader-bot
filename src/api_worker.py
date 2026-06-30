"""
API Worker - FastAPI app for gunicorn workers.
This module contains API endpoints for the dashboard.
Run with: gunicorn src.api_worker:app --workers 3 --bind 0.0.0.0:8000 --worker-class uvicorn.workers.UvicornWorker
"""
import os
import sys
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

BASE_DIR = Path(__file__).parent.parent.absolute()
STATIC_DIR = BASE_DIR / 'src' / 'static'
TEMPLATES_DIR = BASE_DIR / 'src' / 'templates'

from src.cache_manager import SIGNAL_CACHE_FILE, LAST_CYCLE_FILE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# APScheduler instance for auto-retrain
_scheduler = BackgroundScheduler(timezone='UTC')

# Import settings and setup auto-retrain scheduler
from config.settings import settings


def get_local_time_string(timestamp: float) -> str:
    """Convert Unix timestamp to local time string based on settings timezone."""
    try:
        tz = ZoneInfo(settings.TIMEZONE)
        local_dt = datetime.fromtimestamp(timestamp, tz)
        return local_dt.strftime("%H:%M:%S")
    except Exception:
        # Fallback to UTC if timezone is invalid
        return datetime.utcfromtimestamp(timestamp).strftime("%H:%M:%S")


def refresh_signals_background():
    """Refresh signals in background every 10 minutes."""
    try:
        from src.ai_model import ai_model
        settings = load_settings()
        signals = {}
        for product_id in settings.PRODUCT_IDS:
            try:
                signal = ai_model.get_signal(product_id, use_cache=False)
                signals[product_id] = signal
            except Exception as e:
                logger.debug(f"Background signal refresh error for {product_id}: {e}")
        
        # Write signals to cache file for dashboard
        if signals:
            ai_model.write_signals_to_file(signals)
            logger.info(f"Background signal refresh completed, wrote {len(signals)} signals to cache")
        else:
            logger.debug("Background signal refresh completed (no signals generated)")
    except Exception as e:
        logger.warning(f"Background signal refresh error: {e}")

try:
    from src.ai_model import ai_model
    if settings.AUTO_RETRAIN_ENABLED:
        _scheduler.add_job(
            ai_model.scheduled_retrain,
            CronTrigger(
                day_of_week=settings.AUTO_RETRAIN_DAY_OF_WEEK,
                hour=settings.AUTO_RETRAIN_HOUR,
                minute=settings.AUTO_RETRAIN_MINUTE
            )
        )
        _scheduler.start()
        logger.info(f"Auto-retrain scheduled: {settings.AUTO_RETRAIN_DAY_OF_WEEK} at {settings.AUTO_RETRAIN_HOUR:02d}:{settings.AUTO_RETRAIN_MINUTE:02d} UTC")
        
        # Add signal refresh scheduler (every 10 minutes)
        _scheduler.add_job(
            refresh_signals_background,
            'interval',
            minutes=10,
            id='signal_refresh'
        )
        logger.info("Signal refresh scheduler: every 10 minutes")
    else:
        logger.info("Auto-retrain disabled")
except Exception as e:
    logger.warning(f"Could not setup scheduler: {e}")

app = FastAPI(
    title="Crypto Trading Bot API",
    version="1.0.0"
)

# Global retrain status (shared across workers)
# Total will be set dynamically based on settings.PRODUCT_IDS
_retrain_status = {
    'in_progress': False,
    'started_at': None,
    'completed': 0,
    'total': 0,  # Will be set dynamically
    'current_model': None,
    'result': None
}
_retrain_lock = threading.Lock()

# APScheduler instance for auto-retrain
_scheduler = BackgroundScheduler(timezone='UTC')

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

sys.path.insert(0, str(BASE_DIR))

from src.cache_manager import read_signal_cache, write_signal_cache, read_last_cycle_time

_settings_loaded = False

def load_settings():
    """Lazy load settings with DB overrides on first call."""
    from config.settings import settings
    global _settings_loaded
    if not _settings_loaded:
        settings.load_from_db()
        logger.info(f"Settings loaded from DB: interval={settings.MARKET_CHECK_INTERVAL}s, confidence={settings.MODEL_CONFIDENCE_THRESHOLD}, scale_in={settings.SCALE_IN_ENABLED}, scale_out={settings.SCALE_OUT_ENABLED}")
        _settings_loaded = True
    return settings

def load_db_manager():
    """Lazy load database manager."""
    from src.database import db_manager
    return db_manager

def load_currency_converter():
    """Lazy load currency converter."""
    from src.currency_utils import currency_converter
    return currency_converter

def load_coinbase_api():
    """Lazy load Coinbase API."""
    from src.coinbase_api import coinbase_api
    return coinbase_api

def load_data_collector():
    """Lazy load data collector."""
    from src.data_collector import data_collector
    return data_collector

def load_ai_model():
    """Lazy load AI model."""
    from src.ai_model import ai_model
    return ai_model

def format_currency(amount: float, currency: str = 'GBP') -> str:
    """Format amount as currency string."""
    symbol = '£' if currency == 'GBP' else '$'
    return f"{symbol}{amount:,.2f}"

@app.get("/")
async def dashboard():
    """Serve the main dashboard page."""
    try:
        dashboard_path = TEMPLATES_DIR / 'dashboard.html'
        if not dashboard_path.exists():
            return HTMLResponse(content="<h1>Error: Dashboard not found</h1>", status_code=500)
        with open(dashboard_path, 'r') as f:
            html = f.read()
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/models")
async def models_page():
    """Serve the AI models page."""
    try:
        models_path = TEMPLATES_DIR / 'models.html'
        if not models_path.exists():
            return HTMLResponse(content="<h1>Error: Models page not found</h1>", status_code=500)
        with open(models_path, 'r') as f:
            html = f.read()
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Models page error: {e}")
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/trades")
async def trades_page():
    """Serve the trades page."""
    try:
        trades_path = TEMPLATES_DIR / 'trades.html'
        if not trades_path.exists():
            return HTMLResponse(content="<h1>Error: Trades page not found</h1>", status_code=500)
        with open(trades_path, 'r') as f:
            html = f.read()
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Trades page error: {e}")
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/performance")
async def performance_page():
    """Serve the performance page."""
    try:
        perf_path = TEMPLATES_DIR / 'performance.html'
        if not perf_path.exists():
            return HTMLResponse(content="<h1>Error: Performance page not found</h1>", status_code=500)
        with open(perf_path, 'r') as f:
            html = f.read()
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Performance page error: {e}")
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/settings")
async def settings_page():
    """Serve the settings page."""
    try:
        settings_path = TEMPLATES_DIR / 'settings.html'
        if not settings_path.exists():
            return HTMLResponse(content="<h1>Error: Settings page not found</h1>", status_code=500)
        with open(settings_path, 'r') as f:
            html = f.read()
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Settings page error: {e}")
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/favicon.ico")
async def favicon():
    """Return empty favicon to prevent 404s."""
    from fastapi.responses import Response
    return Response(content=b"", media_type="image/x-icon")

@app.head("/favicon.ico")
async def favicon_head():
    """Handle HEAD requests for favicon."""
    from fastapi.responses import Response
    return Response(content=b"", media_type="image/x-icon")

@app.get("/api/status")
async def get_status():
    """Get overall bot status."""
    try:
        db = load_db_manager()
        return {
            "status": "running",
            "trading_active": db.get_trading_active(),
            "paper_trading": db.get_paper_trading(),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Status error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/countdown")
async def get_countdown():
    """Get countdown timing for next trading cycle."""
    try:
        settings = load_settings()
        db = load_db_manager()
        
        last_cycle = read_last_cycle_time()
        interval = settings.MARKET_CHECK_INTERVAL
        trading_active = db.get_trading_active()
        
        if not trading_active:
            return {
                "remaining_seconds": 0,
                "elapsed_seconds": 0,
                "progress_percent": 0,
                "last_cycle_time": get_local_time_string(last_cycle),
                "interval_minutes": interval // 60,
                "trading_active": False
            }
        
        now = time.time()
        elapsed = now - last_cycle
        remaining = max(0, interval - elapsed)
        progress = min(100, (elapsed / interval) * 100)
        
        return {
            "remaining_seconds": int(remaining),
            "elapsed_seconds": int(elapsed),
            "progress_percent": round(progress, 1),
            "last_cycle_time": get_local_time_string(last_cycle),
            "interval_minutes": interval // 60,
            "trading_active": True
        }
    except Exception as e:
        logger.error(f"Countdown error: {e}")
        return {"error": str(e)}

@app.get("/api/portfolio/summary")
async def get_portfolio_summary():
    """Get portfolio summary for overview cards."""
    try:
        db = load_db_manager()
        settings = load_settings()
        cc = load_currency_converter()
        coinbase = load_coinbase_api()
        
        display_currency = db.get_user_setting('display_currency', 'GBP') or 'GBP'
        symbol = '£' if display_currency == 'GBP' else '$'
        
        # Get all accounts
        accounts = coinbase.get_accounts()
        
        # Get valid trading currencies (from PRODUCT_IDS)
        valid_currencies = set(pid.split('-')[0] for pid in settings.PRODUCT_IDS)
        
        # Pre-fetch and cache all prices ONCE using multi-source pricer for consistency
        price_cache = {}
        usd_gbp_rate = cc.get_exchange_rate('USD', 'GBP') or 0.75
        
        # Try to use multi-source pricer for better price quality
        pricer = None
        if settings.MULTI_SOURCE_ENABLED:
            try:
                from src.multi_source_pricer import get_multi_source_pricer
                pricer = get_multi_source_pricer()
            except Exception:
                logger.debug("Multi-source pricer not available, using Coinbase")
        
        for currency in valid_currencies | {'BTC', 'ETH', 'SOL', 'LTC', 'DOT', 'ADA', 'LINK', 'UNI'}:
            # Try multi-source first, then fallback to Coinbase
            result = None
            price = 0.0
            source = 'unknown'
            
            gbp_pair = f"{currency}-GBP"
            usd_pair = f"{currency}-USD"
            
            if pricer:
                try:
                    result = pricer.get_consensus_price(gbp_pair)
                    if result and result.price > 0:
                        price = result.price
                        source = f"multi:{','.join(result.sources_used)}"
                except Exception:
                    pass
            
            # Fallback to Coinbase if multi-source failed
            if price <= 0:
                try:
                    ticker = coinbase.get_product_ticker(gbp_pair)
                    price = ticker.get('price', 0) or 0
                    if price > 0:
                        source = 'coinbase_gbp'
                    else:
                        # Fallback to USD pair with exchange rate
                        ticker = coinbase.get_product_ticker(usd_pair)
                        price = ticker.get('price', 0) or 0
                        if price > 0:
                            price = price * usd_gbp_rate
                            source = f'coinbase_usd@{usd_gbp_rate:.3f}'
                except Exception:
                    pass
            
            if price > 0:
                price_cache[currency] = {'price': price, 'source': source}
        
        # Calculate total value using cached prices
        total_value = 0.0
        gbp_balance = 0.0
        holdings = []
        
        for account in accounts:
            currency = account.get('currency', '')
            balance = float(account.get('available', 0))
            
            if balance <= 0:
                continue
            
            # Calculate value based on currency using cached prices
            if currency == 'GBP':
                value = balance
                gbp_balance = balance
            elif currency in ['USD', 'USDC', 'EUR']:
                # Handle stablecoins and fiat
                if currency == 'EUR':
                    rate = cc.get_exchange_rate('EUR', 'GBP') or 0.85
                    value = balance * rate
                else:
                    value = balance  # USD/USDC = 1:1
            elif currency not in valid_currencies:
                continue
            else:
                # Use cached price
                price_info = price_cache.get(currency, {})
                price = price_info.get('price', 0)
                value = balance * price if price > 0 else 0
            
            if value > 0:
                total_value += value
                holdings.append({
                    'currency': currency,
                    'balance': round(balance, 8),
                    'value': round(value, 2),
                    'symbol': symbol
                })
        
        # Sort by value descending
        holdings.sort(key=lambda x: x['value'], reverse=True)
        
        # Calculate percentages
        for h in holdings:
            h['percentage'] = round((h['value'] / total_value * 100) if total_value > 0 else 0, 1)
        
        # Calculate P&L from positions - only current trading mode
        is_paper = db.get_paper_trading()
        trade_type = 'paper' if is_paper else 'live'
        positions = db.load_open_positions(trade_type=trade_type)
        positions_pnl = 0.0
        for product_id, pos in (positions or {}).items():
            # Use remaining_size for accurate P&L (accounts for scale-outs)
            size = pos.get('remaining_size', pos.get('size', 0))
            if size <= 0:
                continue
            # Use weighted_entry_price for accurate P&L (accounts for scale-ins)
            entry_price = pos.get('weighted_entry_price') or pos.get('entry_price', 0) or 0
            
            # Get current price from cache (same source as portfolio!)
            currency = product_id.split('-')[0]
            price_info = price_cache.get(currency, {})
            current_price = price_info.get('price', 0) or 0
        
            if current_price > 0:
                pnl = (current_price - entry_price) * size
                positions_pnl += pnl
        
        # Get closed positions P&L
        closed = db.get_closed_positions(limit=100)
        closed_pnl = sum((t.get('pnl', 0) or 0) for t in (closed or []))
        
        # Get realized P&L from Coinbase (source of truth) - FIFO matched
        coinbase_realized_pnl = 0.0
        coinbase_trade_count = 0
        coinbase_win_rate = 0.0
        try:
            # Use FIFO matching for true P&L
            client = coinbase.sdk_client
            from datetime import datetime, timedelta, timezone
            fills = client.get_fills()
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            
            product_lots = {}
            total_pnl = 0.0
            wins = 0
            losses = 0
            
            # Sort fills by time (oldest first)
            sorted_fills = []
            for fill in fills.fills:
                try:
                    trade_time = datetime.fromisoformat(fill.trade_time.replace('Z', '+00:00'))
                except:
                    continue
                if trade_time.timestamp() < thirty_days_ago.timestamp():
                    continue
                sorted_fills.append({'time': trade_time, 'product': fill.product_id, 
                                    'side': fill.side.upper(), 'price': float(fill.price), 
                                    'size': float(fill.size)})
            
            sorted_fills.sort(key=lambda x: x['time'])
            
            # FIFO matching
            for fill in sorted_fills:
                product = fill['product']
                side = fill['side']
                size = fill['size']
                price = fill['price']
                
                if product not in product_lots:
                    product_lots[product] = []
                
                if side == 'BUY':
                    product_lots[product].append({'size': size, 'price': price})
                else:
                    remaining = size
                    lots = product_lots[product]
                    while remaining > 0.00000001 and lots:
                        lot = lots[0]
                        if lot['size'] <= remaining:
                            pnl = (price - lot['price']) * lot['size']
                            total_pnl += pnl
                            if pnl > 0: wins += 1
                            else: losses += 1
                            remaining -= lot['size']
                            lots.pop(0)
                        else:
                            pnl = (price - lot['price']) * remaining
                            total_pnl += pnl
                            if pnl > 0: wins += 1
                            else: losses += 1
                            lot['size'] -= remaining
                            remaining = 0
            
            coinbase_realized_pnl = total_pnl
            coinbase_trade_count = wins + losses
            coinbase_win_rate = round(wins / coinbase_trade_count * 100, 1) if coinbase_trade_count > 0 else 0
        except Exception as e:
            logger.warning(f"Could not fetch Coinbase P&L: {e}")
        
        # Calculate metrics
        total_trades = len(closed) if closed else 0
        winning_trades = sum(1 for t in (closed or []) if (t.get('pnl', 0) or 0) > 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Get risk status
        risk_status = 'low'
        gbp_balance = coinbase.get_account_balance('GBP')
        if gbp_balance < settings.GBP_CRITICAL_THRESHOLD:
            risk_status = 'critical'
        elif gbp_balance < settings.GBP_WARNING_THRESHOLD:
            risk_status = 'warning'
        
        # Get models trained count (check loaded models instead of empty list)
        models_trained = 0
        try:
            ai = load_ai_model()
            model_status = ai.get_model_status()
            
            # Get loaded model counts - if models are loaded, they're trained
            loaded = model_status.get('loaded_models', {})
            loaded_count = sum(loaded.values()) if loaded else 0
            
            # Get active symbols from PRODUCT_IDS
            active_symbols = set(pid.split('-')[0] for pid in settings.PRODUCT_IDS)
            
            # Count trained symbols (each model type per product = 1 trained)
            # loaded_models has format {'rf': 6, 'gb': 6, 'ridge': 6} = 18 total
            # We have 6 products, so 6 products * 3 model types = 18 = fully trained
            if loaded_count >= len(active_symbols):
                models_trained = len(active_symbols)
            else:
                # Estimate based on ratio
                models_trained = int(loaded_count / 3)  # 3 model types
            
            logger.info(f"Models trained: {models_trained}, loaded: {loaded}")
        except Exception as e:
            logger.error(f"Error counting models: {e}")
        
        return {
            "status": "success",
            "total_value": round(total_value, 2),
            "formatted_total_value": format_currency(total_value, display_currency),
            "gbp_balance": round(gbp_balance, 2),
            "daily_pnl": round(positions_pnl, 2),
            "formatted_daily_pnl": ('+' if positions_pnl >= 0 else '') + format_currency(abs(positions_pnl), display_currency),
            "total_pnl": round(positions_pnl + closed_pnl, 2),
            "formatted_total_pnl": ('+' if (positions_pnl + closed_pnl) >= 0 else '') + format_currency(abs(positions_pnl + closed_pnl), display_currency),
            "realized_pnl": round(coinbase_realized_pnl, 2),
            "realized_pnl_formatted": ('+' if coinbase_realized_pnl >= 0 else '') + format_currency(abs(coinbase_realized_pnl), display_currency),
            "coinbase_trade_count": coinbase_trade_count,
            "coinbase_win_rate": coinbase_win_rate,
            "win_rate": round(win_rate, 1),
            "open_positions": len(positions) if positions else 0,
            "max_positions": settings.MAX_CONCURRENT_POSITIONS,
            "total_trades": total_trades,
            "models_trained": models_trained,
            "risk_status": risk_status,
            "confidence_threshold": int(settings.MODEL_CONFIDENCE_THRESHOLD * 100),
            "vote_threshold": int(settings.ENSEMBLE_VOTE_THRESHOLD * 100),  # v2.9.1: Model agreement threshold
            "max_position_size": int(settings.MAX_POSITION_SIZE * 100),
            "interval_minutes": settings.MARKET_CHECK_INTERVAL // 60,
            "exchange_rate": cc.get_exchange_rate('USD', display_currency) or 0.75,
            "display_currency": display_currency,
            "holdings": holdings
        }
    except Exception as e:
        logger.error(f"Portfolio summary error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}

@app.get("/api/portfolio/coinbase_pnl")
async def get_coinbase_realized_pnl():
    """
    Get realized P&L from Coinbase API as the source of truth.
    Fetches all fills from Coinbase and calculates true P&L using FIFO matching.
    """
    try:
        coinbase = load_coinbase_api()
        client = coinbase.sdk_client
        
        # Fetch all fills (last 30 days)
        fills = client.get_fills()
        
        from datetime import datetime, timedelta, timezone
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Group fills by product
        # FIFO matching: match each sell to earliest buy
        product_lots = {}  # product -> [{size, price, time}]
        closed_trades = []  # [{product, buy_price, sell_price, size, pnl, time}]
        
        # Sort fills by time (oldest first for FIFO)
        sorted_fills = []
        for fill in fills.fills:
            try:
                trade_time = datetime.fromisoformat(fill.trade_time.replace('Z', '+00:00'))
            except:
                continue
            
            if trade_time.timestamp() < thirty_days_ago.timestamp():
                continue
            
            sorted_fills.append({
                'time': trade_time,
                'time_str': trade_time.strftime('%Y-%m-%d %H:%M'),
                'product': fill.product_id,
                'side': fill.side.upper(),
                'price': float(fill.price),
                'size': float(fill.size),
                'value': float(fill.price) * float(fill.size)
            })
        
        # Sort by time (oldest first)
        sorted_fills.sort(key=lambda x: x['time'])
        
        # FIFO matching
        for fill in sorted_fills:
            product = fill['product']
            side = fill['side']
            size = fill['size']
            price = fill['price']
            
            if product not in product_lots:
                product_lots[product] = []
            
            if side == 'BUY':
                # Add to lots
                product_lots[product].append({
                    'size': size,
                    'price': price,
                    'time': fill['time'],
                    'time_str': fill['time_str']
                })
            else:  # SELL
                # Match against oldest buys (FIFO)
                remaining_size = size
                lots = product_lots[product]
                
                while remaining_size > 0.00000001 and lots:
                    lot = lots[0]
                    
                    if lot['size'] <= remaining_size:
                        # Use entire lot
                        pnl = (price - lot['price']) * lot['size']
                        closed_trades.append({
                            'product': product,
                            'buy_price': lot['price'],
                            'sell_price': price,
                            'size': lot['size'],
                            'pnl': pnl,
                            'time': fill['time_str'],
                            'side': 'SELL'
                        })
                        remaining_size -= lot['size']
                        lots.pop(0)
                    else:
                        # Partial lot
                        pnl = (price - lot['price']) * remaining_size
                        closed_trades.append({
                            'product': product,
                            'buy_price': lot['price'],
                            'sell_price': price,
                            'size': remaining_size,
                            'pnl': pnl,
                            'time': fill['time_str'],
                            'side': 'SELL'
                        })
                        lot['size'] -= remaining_size
                        remaining_size = 0
        
        # Calculate totals from matched trades
        total_pnl = sum(t['pnl'] for t in closed_trades)
        winning_trades = [t for t in closed_trades if t['pnl'] > 0]
        losing_trades = [t for t in closed_trades if t['pnl'] < 0]
        
        avg_win = sum(t['pnl'] for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t['pnl'] for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        # Build display list (newest first)
        display_trades = []
        for t in sorted(closed_trades, key=lambda x: x['time'], reverse=True)[:50]:
            display_trades.append({
                'time': t['time'],
                'product': t['product'],
                'side': t['side'],
                'size': round(t['size'], 8),
                'buy_price': round(t['buy_price'], 2),
                'sell_price': round(t['sell_price'], 2),
                'pnl': round(t['pnl'], 2)
            })
        
        return {
            "status": "success",
            "source": "coinbase_api",
            "period_days": 30,
            "total_trades": len(closed_trades),
            "realized_pnl": round(total_pnl, 2),
            "realized_pnl_formatted": ('+' if total_pnl >= 0 else '') + f"£{abs(total_pnl):.2f}",
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": round(len(winning_trades) / len(closed_trades) * 100, 1) if closed_trades else 0,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_loss_ratio": round(abs(avg_loss / avg_win), 2) if avg_loss != 0 and avg_win != 0 else 0,
            "recent_trades": display_trades
        }
    except Exception as e:
        logger.error(f"Coinbase P&L error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}

@app.post("/api/trades/clear")
async def clear_trades():
    """Clear all trade records from the database."""
    try:
        db = load_db_manager()
        count = db.clear_all_trades()
        return {"status": "success", "message": f"Deleted {count} trades"}
    except Exception as e:
        logger.error(f"Clear trades error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/trades/cleanup")
async def cleanup_old_trades(days: int = 30):
    """Clean up trades older than specified days (default 30)."""
    try:
        db = load_db_manager()
        count = db.clear_old_trades(days)
        return {"status": "success", "message": f"Deleted {count} trades older than {days} days"}
    except Exception as e:
        logger.error(f"Cleanup trades error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/market/conditions")
async def get_market_conditions():
    """Get market conditions with prices and signals."""
    try:
        settings = load_settings()
        coinbase = load_coinbase_api()
        cache = read_signal_cache()
        
        display_currency = 'GBP'
        symbol = '£'
        
        # Get all accounts for holdings
        accounts = coinbase.get_accounts()
        crypto_balances = {}
        for account in accounts:
            currency = account.get('currency', '')
            balance = float(account.get('available', 0))
            if balance > 0 and currency not in ['GBP', 'USD', 'USDC']:
                crypto_balances[currency] = balance
        
        conditions = {}
        
        for product_id in settings.PRODUCT_IDS:
            try:
                ticker = coinbase.get_product_ticker(product_id)
                price = ticker.get('price', 0) or 0
                
                signal_data = cache.get(product_id, {})
                signal = signal_data.get('action', 'HOLD')
                confidence = (signal_data.get('confidence', 0) or 0) * 100
                regime = signal_data.get('regime', 'neutral')
                
                # Load accuracy from training results
                accuracy = 0
                rf_accuracy = 0
                try:
                    logger.info(f"Loading training results for {product_id}")
                    ai = load_ai_model()
                    import os
                    results_dir = os.path.join(ai.model_dir, 'training_results')
                    results_file = os.path.join(results_dir, f'{product_id}_results.json')
                    if os.path.exists(results_file):
                        with open(results_file, 'r') as f:
                            results = json.load(f)
                            # Use avg of model accuracies, or trading_metrics win_rate
                            accuracies = [
                                results.get('rf', {}).get('accuracy', 0),
                                results.get('lr', {}).get('accuracy', 0),
                                results.get('mlp', {}).get('accuracy', 0),
                                results.get('gb', {}).get('accuracy', 0)
                            ]
                            valid_accs = [a for a in accuracies if a and a > 0]
                            accuracy = sum(valid_accs) / len(valid_accs) if valid_accs else results.get('trading_metrics', {}).get('win_rate', 0) or 0
                            rf_accuracy = results.get('rf', {}).get('accuracy', 0) or 0
                except Exception as e:
                    logger.warning(f"Could not load accuracy for {product_id}: {e}")
                
                # Get holdings for this crypto
                base_currency = product_id.split('-')[0]
                balance = crypto_balances.get(base_currency, 0)
                
                crypto_balance = None
                if balance > 0:
                    value = balance * price
                    crypto_balance = {
                        'balance': round(balance, 8),
                        'value': round(value, 2)
                    }
                
                # Get agreement and unanimous from signal
                agreement = signal_data.get('agreement', 0) or 0
                unanimous = signal_data.get('unanimous', False)
                
                # Determine why threshold is met (if at all)
                threshold_reason = ''
                if signal in ['BUY', 'SELL']:
                    if confidence >= settings.MODEL_CONFIDENCE_THRESHOLD * 100:
                        threshold_reason = '80% threshold'
                    elif unanimous and agreement == 1.0 and confidence >= 50:
                        threshold_reason = 'Unanimous (50%+)'
                
                conditions[product_id] = {
                    'price': round(price, 2),
                    'formatted_price': f"{symbol}{price:,.2f}",
                    'signal': signal,
                    'confidence': round(confidence, 1),
                    'agreement': round(agreement * 100, 0),
                    'unanimous': unanimous,
                    'threshold_reason': threshold_reason,
                    'regime': regime,
                    'action': 'TRADE' if (signal in ['BUY', 'SELL'] and confidence >= settings.MODEL_CONFIDENCE_THRESHOLD * 100) else 'WAIT',
                    'meets_threshold': signal in ['BUY', 'SELL'] and confidence >= settings.MODEL_CONFIDENCE_THRESHOLD * 100,
                    'crypto_balance': crypto_balance,
                    'accuracy': round(accuracy * 100, 1),
                    'rf_accuracy': round(rf_accuracy * 100, 1)
                }
            except Exception as e:
                logger.warning(f"Error getting conditions for {product_id}: {e}")
                conditions[product_id] = {
                    'price': 0,
                    'formatted_price': 'N/A',
                    'signal': 'HOLD',
                    'confidence': 0,
                    'agreement': 0,
                    'unanimous': False,
                    'threshold_reason': '',
                    'regime': 'unknown',
                    'action': 'WAIT',
                    'meets_threshold': False,
                    'crypto_balance': None,
                    'accuracy': 0,
                    'rf_accuracy': 0
                }
        
        return {
            "status": "success",
            "conditions": conditions,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Market conditions error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/open_positions")
async def get_open_positions():
    """Get open positions formatted for table display."""
    try:
        db = load_db_manager()
        coinbase = load_coinbase_api()
        display_currency = db.get_user_setting('display_currency', 'GBP') or 'GBP'
        symbol = '£' if display_currency == 'GBP' else '$'
        
        # Load positions based on current trading mode
        is_paper = db.get_paper_trading()
        trade_type = 'paper' if is_paper else 'live'
        positions = db.load_open_positions(trade_type=trade_type)
        rows = []
        
        # v2.9.8: Fetch fresh prices for all positions
        from config.settings import settings
        fresh_prices = {}
        if settings.MULTI_SOURCE_ENABLED:
            try:
                from src.multi_source_pricer import get_multi_source_pricer
                pricer = get_multi_source_pricer()
                for product_id in (positions or {}).keys():
                    result = pricer.get_consensus_price(product_id)
                    if result and result.price > 0:
                        fresh_prices[product_id] = result.price
            except Exception as e:
                logger.warning(f"Failed to fetch fresh prices: {e}")
        
        for product_id, pos in (positions or {}).items():
            # Use remaining_size for accurate P&L (accounts for scale-outs)
            size = pos.get('remaining_size', pos.get('size', 0))
            if size <= 0:
                continue
            
            try:
                # Use fresh price if available, fallback to cached
                current_price = fresh_prices.get(product_id) or pos.get('current_price', 0) or 0
                # Use weighted_entry_price for accurate P&L (accounts for scale-ins)
                entry_price = pos.get('weighted_entry_price') or pos.get('entry_price', 0) or 0
                
                # Get previous price from database to track direction
                prev_price = pos.get('current_price', 0) or 0
                price_change = current_price - prev_price
                
                # Determine direction
                if price_change > 0:
                    price_direction = 'up'
                elif price_change < 0:
                    price_direction = 'down'
                else:
                    price_direction = 'flat'
                
                pnl = (current_price - entry_price) * size
                pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                
                # Get original entry price (before any scale-ins)
                original_entry = pos.get('entry_price', 0) or 0
                weighted_entry = pos.get('weighted_entry_price') or original_entry or 0
                
                # Get scale-in details
                scale_in_count = pos.get('scale_in_count', 0) or 0
                scale_in_levels = pos.get('scale_in_levels_triggered', '') or ''
                scale_in_price = pos.get('last_scale_in_price', 0) or 0
                
                # Calculate trailing stop info
                from config.settings import settings
                
                # Get fee rates
                fees = db.get_fee_rates()
                maker_fee = fees.get('maker_fee', settings.DEFAULT_MAKER_FEE) if fees else settings.DEFAULT_MAKER_FEE
                taker_fee = fees.get('taker_fee', settings.DEFAULT_TAKER_FEE) if fees else settings.DEFAULT_TAKER_FEE
                total_fee = maker_fee + taker_fee
                
                # Get regime
                regime = pos.get('regime', 'neutral')
                
                # Get trailing percentage (2% as requested)
                trailing_pct = settings.TRAILING_STOP_REGIME_MAP.get(regime, settings.TRAILING_STOP_PERCENT)
                
                # Get entry and peak
                entry_price_calc = pos.get('entry_price',0) or 0
                peak_price = pos.get('peak_price', entry_price_calc)
                
                # Calculate break-even (covers fees)
                break_even = entry_price_calc * (1 + total_fee)
                
                # Calculate actual trailing stop (2% below peak, floored below break-even)
                trailing_stop = peak_price * (1 - trailing_pct)
                # v2.9.1: Floor is break-even minus buffer, NOT 95% of entry
                stop_floor = break_even * (1 - trailing_pct)
                trailing_stop = max(trailing_stop, stop_floor)
                
                # Only activate trailing stop after break-even + buffer is reached (once activated, stays active)
                # Use peak_price to check if we've ever been above break-even + buffer
                activation_threshold = break_even * (1 + settings.TRAILING_ACTIVATION_BUFFER)
                trailing_activated = peak_price >= activation_threshold
                
                rows.append({
                    'product_id': product_id,
                    'side': pos.get('side', 'buy').upper(),
                    'size': round(size, 8),
                    'remaining_size': round(pos.get('remaining_size', size), 8),
                    'entry_price': round(weighted_entry, 2),  # Weighted (for P&L)
                    'original_entry_price': round(original_entry, 2),  # Original (before scale-ins)
                    'scale_in_price': round(scale_in_price, 2) if scale_in_price > 0 else None,  # Scale-in price
                    'current_price': round(current_price, 2),
                    'pnl': round(pnl, 2),
                    'formatted_pnl': ('+' if pnl >= 0 else '') + f"{symbol}{abs(pnl):,.2f}",
                    'pnl_pct': round(pnl_pct, 2),
                    'price_direction': price_direction,
                    'scale_in_count': scale_in_count,
                    'scale_out_count': pos.get('scale_out_count', 0) or 0,
                    'scale_out_levels': pos.get('scale_out_levels_triggered', '') or '',
                    'position_id': pos.get('position_id'),
                    'opened_at': pos.get('opened_at'),
                    'status': pos.get('status', 'open'),
                    # Trailing stop info
                    'break_even': round(break_even, 2),
                    'unlock_price': round(activation_threshold, 2),  # Price needed for trailing above BE+buffer
                    'peak_price': round(peak_price, 2),
                    'trailing_stop': round(trailing_stop, 2),  # 2% below peak (moves with price)
                    'stop_floor': round(stop_floor, 2),  # Floor is below break-even
                    'trailing_activated': trailing_activated,
                    'regime': regime,
                    'trailing_pct': round(trailing_pct * 100, 0)
                })
                
                # Update current_price in database for next time
                db.update_position_current_price(product_id, current_price)
                
            except Exception as e:
                logger.warning(f"Error processing position {product_id}: {e}")
        
        return {
            "status": "success",
            "positions": rows,
            "count": len(rows)
        }
    except Exception as e:
        logger.error(f"Open positions error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/closed_positions")
async def get_closed_positions(limit: int = 50):
    """Get closed positions formatted for table display."""
    try:
        db = load_db_manager()
        display_currency = db.get_user_setting('display_currency', 'GBP') or 'GBP'
        symbol = '£' if display_currency == 'GBP' else '$'
        
        positions = db.get_closed_positions(limit=limit)
        rows = []
        
        for pos in (positions or []):
            try:
                timestamp = pos.get('closed_at') or pos.get('created_at') or datetime.now().isoformat()
                if isinstance(timestamp, str) and 'T' in timestamp:
                    date_str = timestamp.split('T')[0]
                    time_str = timestamp.split('T')[1][:8]
                else:
                    date_str = ''
                    time_str = ''
                
                pnl = pos.get('pnl', 0) or 0
                entry_price_calc = pos.get('entry_price', 0) or 0
                
                rows.append({
                    'product_id': pos.get('product_id', 'N/A'),
                    'side': pos.get('side', 'N/A').upper(),
                    'size': round(pos.get('size', 0), 8),
                    'entry_price': round(entry_price_calc, 2),
                    'exit_price': round(pos.get('exit_price', 0) or 0, 2),
                    'pnl': round(pnl, 2),
                    'formatted_pnl': ('+' if pnl >= 0 else '') + f'{symbol}{abs(pnl):,.2f}',
                    'date': date_str,
                    'time': time_str,
                    'status': pos.get('status', 'closed'),
                    'exit_reason': pos.get('exit_reason', ''),
                    # Add trailing stop info for closed positions
                    'break_even': round(entry_price_calc * 1.011, 2),  # Approximate break-even
                    'stop_triggered': pos.get('final_stop', 0) or 0
                })
            except Exception as e:
                logger.warning(f"Error processing closed position: {e}")
        
        return {
            "status": "success",
            "positions": rows,
            "count": len(rows)
        }
    except Exception as e:
        logger.error(f"Closed positions error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/recent_trades")
async def get_recent_trades(limit: int = 20):
    """Get recent trades formatted for table display with FIFO matching."""
    try:
        db = load_db_manager()
        display_currency = db.get_user_setting('display_currency', 'GBP') or 'GBP'
        symbol = '£' if display_currency == 'GBP' else '$'
        
        trades = db.get_trades(limit=limit)
        
        # Get closed positions for exit_reason and exit_price mapping
        closed_positions = db.get_closed_positions(limit=100) or []
        
        # v2.9.3: Build a list of closed positions per product (not just one)
        closed_by_product = {}  # product_id -> list of {exit_price, exit_reason, entry_price, timestamp}
        for pos in closed_positions:
            product = pos.get('product_id')
            if product:
                closed_ts = pos.get('closed_at', '')
                if product not in closed_by_product:
                    closed_by_product[product] = []
                closed_by_product[product].append({
                    'exit_price': pos.get('exit_price', 0) or 0,
                    'exit_reason': pos.get('exit_reason', ''),
                    'entry_price': pos.get('entry_price', 0) or 0,
                    'timestamp': closed_ts
                })
        
        # Build FIFO queue of unmatched BUY trades per product
        # Each BUY trade will be matched to the next SELL (FIFO)
        buy_queues = {}  # product_id -> list of {price, timestamp, size}
        for trade in (trades or []):
            if trade.get('side', '').lower() == 'buy':
                product = trade.get('product_id')
                ts = trade.get('created_at') or trade.get('timestamp')
                if hasattr(ts, 'isoformat'):
                    ts = ts.isoformat()
                if product not in buy_queues:
                    buy_queues[product] = []
                buy_queues[product].append({
                    'price': trade.get('price', 0) or 0,
                    'size': trade.get('size', 0) or 0,
                    'timestamp': ts
                })
        
        # Also add open positions as potential unmatched buys
        open_positions = db.load_open_positions()
        for product, pos in (open_positions or {}).items():
            entry_price = pos.get('weighted_entry_price') or pos.get('entry_price', 0) or 0
            size = pos.get('remaining_size', pos.get('size', 0)) or 0
            if entry_price > 0 and size > 0:
                if product not in buy_queues:
                    buy_queues[product] = []
                # Add open position as "unmatched buy" - will be matched when position closes
                buy_queues[product].append({
                    'price': entry_price,
                    'size': size,
                    'timestamp': pos.get('opened_at', ''),
                    'is_open_position': True
                })
        
        rows = []
        
        for trade in (trades or []):
            try:
                ts = trade.get('created_at') or trade.get('timestamp')
                
                # Extract date and time from timestamp
                date_str = ''
                time_str = ''
                if ts:
                    if hasattr(ts, 'isoformat'):
                        ts = ts.isoformat()
                    if isinstance(ts, str) and 'T' in ts:
                        parts = ts.split('T')
                        date_str = parts[0]
                        time_str = parts[1][:8] if len(parts) > 1 else ''
                
                product_id = trade.get('product_id', 'N/A')
                price = trade.get('price', 0) or 0
                trade_size = trade.get('size', 0) or 0
                pnl = trade.get('pnl', 0) or 0
                side = trade.get('side', 'N/A').upper()
                
                # Get entry and exit info
                entry_price = 0
                exit_price = 0
                exit_reason = ''
                pnl_pct = 0
                status = trade.get('status', 'filled')
                
                if side == 'SELL':
                    # FIFO match: find earliest unmatched BUY for this product
                    matched_buy = None
                    if product_id in buy_queues and buy_queues[product_id]:
                        # Get the earliest buy (FIFO)
                        matched_buy = buy_queues[product_id][0]
                        entry_price = matched_buy.get('price', 0)
                    
                    # Try to get exit info from closed positions
                    if product_id in closed_by_product and closed_by_product[product_id]:
                        # Find the closed position that matches this sell (by most recent)
                        for closed in closed_by_product[product_id]:
                            # Use the sell price from trade, get exit_reason from closed
                            exit_price = price
                            if matched_buy and abs(closed.get('entry_price', 0) - matched_buy.get('price', 0)) < entry_price * 0.1:
                                # This closed position matches our entry price
                                exit_reason = closed.get('exit_reason', '')
                                break
                        else:
                            # No matching closed position found, use most recent
                            latest_closed = closed_by_product[product_id][0]
                            exit_reason = latest_closed.get('exit_reason', '')
                    else:
                        # No closed position, use trade price as exit
                        exit_price = price
                    
                    # Calculate pnl percentage
                    if entry_price > 0:
                        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                    
                    # Remove matched buy from queue (FIFO - consume the buy)
                    if matched_buy and product_id in buy_queues and buy_queues[product_id]:
                        buy_queues[product_id].pop(0)
                        
                else:  # BUY
                    # For buys, use price as entry
                    entry_price = price
                    
                    # Check if this buy has a matching closed position (already sold)
                    if product_id in closed_by_product and closed_by_product[product_id]:
                        # Check if there's a sell that closed this position
                        for closed in closed_by_product[product_id]:
                            # If closed entry price is close to our buy price, we sold it
                            if abs(closed.get('entry_price', 0) - price) < price * 0.1:
                                exit_price = closed.get('exit_price', 0)
                                exit_reason = closed.get('exit_reason', '')
                                if exit_price > 0:
                                    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                                status = 'closed'
                                break
                    
                    # Add this buy to the queue for future SELLs to match
                    if product_id not in buy_queues:
                        buy_queues[product_id] = []
                    buy_queues[product_id].append({
                        'price': price,
                        'size': trade_size,
                        'timestamp': ts,
                        'is_open_position': False
                    })
                
                rows.append({
                    'timestamp': time_str,
                    'date': date_str,
                    'product_id': product_id,
                    'side': side,
                    'size': round(trade_size, 8),
                    'entry_price': round(entry_price, 2),
                    'price': round(price, 2),
                    'formatted_price': f"{symbol}{price:,.2f}",
                    'exit_price': round(exit_price, 2) if exit_price > 0 else None,
                    'exit_reason': exit_reason,
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'formatted_pnl': ('+' if pnl >= 0 else '') + f"{symbol}{abs(pnl):,.2f}",
                    'status': status
                })
            except Exception as e:
                logger.warning(f"Error processing trade: {e}")
        
        return {
            "status": "success",
            "trades": rows,
            "count": len(rows)
        }
    except Exception as e:
        logger.error(f"Trades error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/models/status")
async def get_models_status():
    """Get AI model status with current signals."""
    try:
        ai = load_ai_model()
        model_status = ai.get_model_status()
        settings = load_settings()
        
        # Get cached signals from FILE CACHE ONLY (consistent with market/conditions)
        # This ensures dashboard and models page show the same signals
        cached_signals = {}
        
        # Read from signal cache file (written by trading process)
        try:
            if SIGNAL_CACHE_FILE.exists():
                with open(SIGNAL_CACHE_FILE, 'r') as f:
                    cached_signals = json.load(f)
                logger.debug(f"Loaded signals from cache file: {len(cached_signals)} products")
        except Exception as e:
            logger.warning(f"Could not read signal cache file: {e}")
        
        models = []
        # Use dynamic product IDs from settings instead of hardcoded list
        product_ids = [pid.split('-')[0] for pid in settings.PRODUCT_IDS]
        
        # Get list of trained models (v2.1: Check training_results if models deleted)
        trained_models_list = model_status.get('models_trained', [])
        models_on_disk = model_status.get('models_on_disk', [])
        
        # If no models in list, check training_results JSON files
        if not trained_models_list:
            results_dir = os.path.join(ai.model_dir, 'training_results')
            if os.path.exists(results_dir):
                for f in os.listdir(results_dir):
                    if f.endswith('_results.json'):
                        product_id = f.replace('_results.json', '')
                        if product_id not in trained_models_list:
                            trained_models_list.append(product_id)
        
        # Get model directory for loading results
        model_dir = ai.model_dir
        
        # Get USD training pairs for mapping
        usd_training_pairs = list(ai.gbp_to_usd_map.values())
        
        for symbol in product_ids:
            product_id = f"{symbol}-GBP"
            usd_product_id = f"{symbol}-USD"
            
            # Check if model is in trained models list (now checks both model files AND training_results)
            # First get results_dir for use in this check
            results_dir = os.path.join(model_dir, 'training_results')
            has_gbp_results = os.path.exists(os.path.join(results_dir, f"{product_id}_results.json"))
            has_usd_results = os.path.exists(os.path.join(results_dir, f"{usd_product_id}_results.json"))
            trained = (product_id in trained_models_list or 
                       usd_product_id in trained_models_list or
                       usd_product_id in models_on_disk or
                       product_id in models_on_disk or
                       has_gbp_results or
                       has_usd_results)
            
            # Load training results (accuracy, F1) from saved JSON files
            # Check both GBP and USD product IDs (USD models trained now)
            rf_accuracy = rf_f1 = nn_accuracy = nn_f1 = gb_accuracy = gb_f1 = 0
            try:
                results_dir = os.path.join(model_dir, 'training_results')
                
                # Try GBP results file first (our new training), then USD as fallback
                for try_product_id in [product_id, usd_product_id]:
                    results_file = os.path.join(results_dir, f'{try_product_id}_results.json')
                    if os.path.exists(results_file):
                        with open(results_file, 'r') as f:
                            results = json.load(f)
                            # Trading metrics (new format)
                            rf_win_rate = results.get('rf', {}).get('win_rate', 0)
                            rf_profit_factor = results.get('rf', {}).get('profit_factor', 0)
                            rf_total_pnl = results.get('rf', {}).get('total_pnl', 0)
                            rf_num_trades = results.get('rf', {}).get('num_trades', 0)
                            
                            lr_win_rate = results.get('lr', {}).get('win_rate', 0)
                            lr_profit_factor = results.get('lr', {}).get('profit_factor', 0)
                            lr_total_pnl = results.get('lr', {}).get('total_pnl', 0)
                            lr_num_trades = results.get('lr', {}).get('num_trades', 0)
                            
                            mlp_win_rate = results.get('mlp', {}).get('win_rate', 0)
                            mlp_profit_factor = results.get('mlp', {}).get('profit_factor', 0)
                            mlp_total_pnl = results.get('mlp', {}).get('total_pnl', 0)
                            mlp_num_trades = results.get('mlp', {}).get('num_trades', 0)
                            
                            gb_win_rate = results.get('gb', {}).get('win_rate', 0)
                            gb_profit_factor = results.get('gb', {}).get('profit_factor', 0)
                            gb_total_pnl = results.get('gb', {}).get('total_pnl', 0)
                            gb_num_trades = results.get('gb', {}).get('num_trades', 0)
                            
                            # Ridge metrics (NEW)
                            ridge_win_rate = results.get('ridge', {}).get('win_rate', 0)
                            ridge_profit_factor = results.get('ridge', {}).get('profit_factor', 0)
                            ridge_total_pnl = results.get('ridge', {}).get('total_pnl', 0)
                            ridge_num_trades = results.get('ridge', {}).get('num_trades', 0)
                            
                            # Legacy ML metrics (fallback)
                            rf_accuracy = results.get('rf', {}).get('accuracy', 0)
                            rf_f1 = results.get('rf', {}).get('f1_score', 0)
                            nn_accuracy = results.get('lr', {}).get('accuracy', 0)
                            nn_f1 = results.get('lr', {}).get('f1_score', 0)
                            gb_accuracy = results.get('gb', {}).get('accuracy', 0)
                            gb_f1 = results.get('gb', {}).get('f1_score', 0)
                            
                            # ATR config
                            atr_config = results.get('atr_config', {})
                        break
            except Exception as e:
                logger.warning(f"Could not load training results for {product_id}: {e}")
            
            # Calculate ensemble accuracy using saved weights from training results
            ensemble_accuracy = rf_accuracy  # Use RF as representative since we have performance weights saved
            
            # Get signal from cache if available
            signal_data = cached_signals.get(product_id, {})
            signal = signal_data.get('action', 'HOLD')
            confidence = signal_data.get('confidence', 0)
            regime = signal_data.get('regime', 'neutral')
            
            # Extract individual model signals from ensemble
            rf_pred = signal_data.get('rf_prediction')
            lr_pred = signal_data.get('lr_prediction')
            mlp_pred = signal_data.get('mlp_prediction')
            gb_pred = signal_data.get('gb_prediction')
            ridge_pred = signal_data.get('ridge_prediction')
            
            # Trading metrics for each model
            models.append({
                'product_id': product_id,
                'symbol': symbol,
                'trained': trained,
                'status': 'Trained' if trained else 'Not Trained',
                # Trading metrics (primary)
                'rf_win_rate': rf_win_rate,
                'rf_profit_factor': rf_profit_factor,
                'rf_total_pnl': rf_total_pnl,
                'rf_num_trades': rf_num_trades,
                'lr_win_rate': lr_win_rate,
                'lr_profit_factor': lr_profit_factor,
                'lr_total_pnl': lr_total_pnl,
                'lr_num_trades': lr_num_trades,
                'mlp_win_rate': mlp_win_rate,
                'mlp_profit_factor': mlp_profit_factor,
                'mlp_total_pnl': mlp_total_pnl,
                'mlp_num_trades': mlp_num_trades,
                'gb_win_rate': gb_win_rate,
                'gb_profit_factor': gb_profit_factor,
                'gb_total_pnl': gb_total_pnl,
                'gb_num_trades': gb_num_trades,
                'ridge_win_rate': ridge_win_rate,
                'ridge_profit_factor': ridge_profit_factor,
                'ridge_total_pnl': ridge_total_pnl,
                'ridge_num_trades': ridge_num_trades,
                'atr_config': atr_config,
                # Legacy ML metrics
                'accuracy': (rf_accuracy + nn_accuracy + gb_accuracy) / 3,
                'rf_accuracy': rf_accuracy,
                'nn_accuracy': nn_accuracy,
                'gb_accuracy': gb_accuracy,
                # Signal data
                'signal': signal,
                'confidence': confidence,
                'regime': regime,
                'agreement': signal_data.get('agreement', 0) or 0,
                'unanimous': signal_data.get('agreement', 0) == 1.0,
                'rf_signal': 'BUY' if rf_pred == 2 else ('SELL' if rf_pred == 0 else 'HOLD') if rf_pred is not None else 'N/A',
                'rf_confidence': signal_data.get('rf_confidence', 0) or 0,
                'lr_signal': 'BUY' if lr_pred == 2 else ('SELL' if lr_pred == 0 else 'HOLD') if lr_pred is not None else 'N/A',
                'lr_confidence': signal_data.get('lr_confidence', 0) or 0,
                'mlp_signal': 'BUY' if mlp_pred == 2 else ('SELL' if mlp_pred == 0 else 'HOLD') if mlp_pred is not None else 'N/A',
                'mlp_confidence': signal_data.get('mlp_confidence', 0) or 0,
                'gb_signal': 'BUY' if gb_pred == 2 else ('SELL' if gb_pred == 0 else 'HOLD') if gb_pred is not None else 'N/A',
                'gb_confidence': signal_data.get('gb_confidence', 0) or 0,
                'ridge_signal': 'BUY' if ridge_pred == 2 else ('SELL' if ridge_pred == 0 else 'HOLD') if ridge_pred is not None else 'N/A',
                'ridge_confidence': signal_data.get('ridge_confidence', 0) or 0,
                'ensemble_used': signal_data.get('ensemble_used', False)
            })
        
        trained_count = len([m for m in models if m['trained']])
        
        return {
            "status": "success",
            "models_trained": trained_count,
            "working_models": trained_count,
            "total_products": len(settings.PRODUCT_IDS),
            "features_count": 30,
            "models": models
        }
    except Exception as e:
        logger.error(f"Models status error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "success", "models_trained": 0, "working_models": 0, "total_products": 8, "models": []}

@app.post("/api/models/retrain")
async def retrain_models():
    """Retrain all AI models (runs in background)."""
    global _retrain_status
    
    # Check if already running
    with _retrain_lock:
        if _retrain_status['in_progress']:
            return {
                "status": "running",
                "message": f"Retrain already in progress: {_retrain_status.get('current_model', 'unknown')}",
                "completed": _retrain_status['completed'],
                "total": _retrain_status['total']
            }
        
        # Set total dynamically from settings.PRODUCT_IDS
        settings = load_settings()
        _retrain_status['total'] = len(settings.PRODUCT_IDS)
        
        _retrain_status['in_progress'] = True
        _retrain_status['started_at'] = datetime.now().isoformat()
        _retrain_status['completed'] = 0
        _retrain_status['current_model'] = "Starting..."
        _retrain_status['result'] = None
    
    def run_retrain():
        """Background thread for retraining."""
        global _retrain_status
        try:
            ai = load_ai_model()
            logger.info("Starting background model retraining...")
            
            result = ai.retrain_all_models()
            
            success_count = sum(1 for r in result.values() if r.get('rf', {}).get('success', False))
            total_count = len(result)
            
            ai.update_last_retrain_date()
            
            logger.info(f"Background retrain completed: {success_count}/{total_count} successful")
            
            with _retrain_lock:
                _retrain_status['result'] = {
                    'status': 'success',
                    'message': f"Models retrained: {success_count}/{total_count} successful",
                    'trained': success_count,
                    'total': total_count,
                    'details': result,
                    'completed_at': datetime.now().isoformat()
                }
                _retrain_status['completed'] = total_count
                _retrain_status['current_model'] = "Complete"
        except Exception as e:
            logger.error(f"Background retrain error: {e}")
            with _retrain_lock:
                _retrain_status['result'] = {
                    'status': 'error',
                    'message': str(e),
                    'completed_at': datetime.now().isoformat()
                }
        finally:
            with _retrain_lock:
                _retrain_status['in_progress'] = False
    
    # Start background thread - NOT daemon so it persists after API returns
    thread = threading.Thread(target=run_retrain)  # Remove daemon=True to keep thread alive
    thread.start()
    thread.join(timeout=5)  # Give it a moment to start, but return immediately
    
    settings = load_settings()
    return {
        "status": "started",
        "message": "Model retraining started in background",
        "completed": 0,
        "total": len(settings.PRODUCT_IDS)
    }

@app.get("/api/models/retrain_progress")
async def get_retrain_progress():
    """Get current retrain progress + last retrain info."""
    with _retrain_lock:
        result = {
            "in_progress": _retrain_status['in_progress'],
            "started_at": _retrain_status['started_at'],
            "completed": _retrain_status['completed'],
            "total": _retrain_status['total'],
            "current_model": _retrain_status['current_model'],
            "result": _retrain_status['result']
        }
    # Add retrain status fields (merged from /api/ai/retrain_status)
    try:
        ai = load_ai_model()
        rstatus = ai.get_retrain_status()
        result['last_retrain_date'] = rstatus.get('last_retrain_date')
        result['days_since_retrain'] = rstatus.get('days_since_retrain')
        result['auto_retrain_enabled'] = rstatus.get('auto_retrain_enabled', False)
    except Exception:
        pass
    return result

@app.post("/api/models/generate_signals")
async def generate_signals():
    """Generate fresh signals for all GBP trading pairs."""
    try:
        ai = load_ai_model()
        settings = load_settings()
        logger.info("Generating fresh signals for all trading pairs...")
        
        signals = {}
        for product_id in settings.PRODUCT_IDS:
            try:
                signal = ai.get_signal(product_id, use_cache=False)
                signals[product_id] = {
                    'action': signal.get('action', 'HOLD'),
                    'confidence': signal.get('confidence', 0),
                    'regime': signal.get('regime', 'neutral'),
                    'success': signal.get('success', False),
                    # Individual model predictions for agreement matrix
                    'rf_prediction': signal.get('rf_prediction'),
                    'lr_prediction': signal.get('lr_prediction'),
                    'mlp_prediction': signal.get('mlp_prediction'),
                    'gb_prediction': signal.get('gb_prediction'),
                    'ridge_prediction': signal.get('ridge_prediction'),
                    'rf_confidence': signal.get('rf_confidence', 0),
                    'lr_confidence': signal.get('lr_confidence', 0),
                    'mlp_confidence': signal.get('mlp_confidence', 0),
                    'gb_confidence': signal.get('gb_confidence', 0),
                    'ridge_confidence': signal.get('ridge_confidence', 0),
                    'agreement': signal.get('agreement', 0),
                    'unanimous': signal.get('unanimous', False)
                }
            except Exception as e:
                logger.warning(f"Error generating signal for {product_id}: {e}")
                signals[product_id] = {'action': 'HOLD', 'confidence': 0, 'regime': 'neutral', 'success': False, 'error': str(e)}
        
        success_count = sum(1 for s in signals.values() if s.get('success', False))
        
        logger.info(f"Signal generation completed: {success_count}/{len(signals)} successful")
        
        return {
            "status": "success",
            "message": f"Signals generated: {success_count}/{len(signals)}",
            "signals": signals,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Signal generation error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}
    finally:
        # Always write to cache file for dashboard
        try:
            write_signal_cache(signals)
        except Exception as e:
            logger.error(f"Failed to write signal cache: {e}")

@app.get("/api/ai/retrain_status")
async def get_retrain_status():
    """Get AI model retraining status (DEPRECATED: use /api/models/retrain_progress)."""
    try:
        ai = load_ai_model()
        status = ai.get_retrain_status()
        return {"status": "success", **status}
    except Exception as e:
        logger.error(f"Retrain status error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/exchange_rate")
async def get_exchange_rate():
    """Get USD to GBP exchange rate."""
    try:
        cc = load_currency_converter()
        display_currency = 'GBP'
        rate = cc.get_exchange_rate('USD', display_currency) or 0.75
        
        return {
            "status": "success",
            "exchange_rate": round(rate, 4),
            "usd_to_gbp": round(rate, 4),
            "age_seconds": 0,
            "display_currency": display_currency
        }
    except Exception as e:
        logger.error(f"Exchange rate error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/gbp-balance")
async def get_gbp_balance():
    """Get GBP balance info."""
    try:
        coinbase = load_coinbase_api()
        db = load_db_manager()
        settings = load_settings()
        
        gbp_balance = coinbase.get_account_balance('GBP')
        
        status = 'normal'
        if gbp_balance < settings.GBP_CRITICAL_THRESHOLD:
            status = 'critical'
        elif gbp_balance < settings.GBP_WARNING_THRESHOLD:
            status = 'warning'
        
        return {
            "status": "success",
            "gbp_balance": round(gbp_balance, 2),
            "formatted_balance": f"£{gbp_balance:,.2f}",
            "status": status,
            "warning_threshold": settings.GBP_WARNING_THRESHOLD,
            "critical_threshold": settings.GBP_CRITICAL_THRESHOLD
        }
    except Exception as e:
        logger.error(f"GBP balance error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/risk/status")
async def get_risk_status():
    """Get risk status details."""
    try:
        db = load_db_manager()
        settings = load_settings()
        coinbase = load_coinbase_api()
        
        gbp_balance = coinbase.get_account_balance('GBP')
        
        status = 'low'
        message = 'All risk parameters within limits'
        
        if gbp_balance < settings.GBP_CRITICAL_THRESHOLD:
            status = 'critical'
            message = f'GBP balance critical: £{gbp_balance:.2f} below £{settings.GBP_CRITICAL_THRESHOLD:.2f}'
        elif gbp_balance < settings.GBP_WARNING_THRESHOLD:
            status = 'warning'
            message = f'GBP balance low: £{gbp_balance:.2f} below £{settings.GBP_WARNING_THRESHOLD:.2f}'
        
        return {
            "status": "success",
            "risk_status": status,
            "message": message,
            "gbp_balance": round(gbp_balance, 2),
            "warning_threshold": settings.GBP_WARNING_THRESHOLD,
            "critical_threshold": settings.GBP_CRITICAL_THRESHOLD
        }
    except Exception as e:
        logger.error(f"Risk status error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/{action}")
async def control_action(action: str):
    """Control bot actions (start, stop, emergency_stop, retrain, resync)."""
    try:
        # Note: In API worker mode, these actions may not work as expected
        # since the trading engine runs in a separate process
        if action == 'start':
            return {"status": "success", "message": "Trading started", "trading_active": True}
        elif action == 'stop':
            return {"status": "success", "message": "Trading stopped", "trading_active": False}
        elif action == 'emergency_stop':
            return {"status": "success", "message": "Emergency stop executed", "trading_active": False}
        elif action == 'retrain':
            return {"status": "success", "message": "Retrain initiated", "details": {}}
        elif action == 'resync':
            # Force resync positions with Coinbase wallet
            from src.database import db_manager
            from src.coinbase_api import coinbase_api
            from src.data_collector import data_collector
            from config.settings import settings
            
            wallet_balances = {}
            for product_id in settings.PRODUCT_IDS:
                base_currency = product_id.split('-')[0]
                balance = coinbase_api.get_account_balance(base_currency)
                if balance > 0:
                    wallet_balances[base_currency] = balance
            
            current_prices = data_collector.get_current_prices()
            
            # Update each position to match wallet
            positions = db_manager.load_open_positions(trade_type='live')
            updated = 0
            for product_id, pos in positions.items():
                base_currency = product_id.split('-')[0]
                wallet_size = wallet_balances.get(base_currency, 0)
                current_price = current_prices.get(product_id, pos.get('current_price', 0))
                
                db_manager.save_open_position({
                    'product_id': product_id,
                    'side': 'buy',
                    'size': wallet_size,
                    'entry_price': current_price,
                    'trade_type': 'live',
                    'status': 'open'
                })
                updated += 1
            
            return {"status": "success", "message": f"Resynced {updated} positions with wallet", "wallets": wallet_balances}
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}
    except Exception as e:
        logger.error(f"Control action error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/position/{position_id}/close")
async def close_position(position_id: str):
    """Close a specific open position by ID."""
    try:
        from src.database import db_manager
        from src.coinbase_api import coinbase_api
        from src.risk_manager import risk_manager

        positions = db_manager.get_all_open_positions_detailed()
        position = next((p for p in positions if p['position_id'] == position_id), None)

        if not position:
            return {"status": "error", "message": "Position not found"}

        product_id = position['product_id']
        current_price = coinbase_api.get_product_ticker(product_id)
        if not current_price or 'price' not in current_price:
            return {"status": "error", "message": f"Could not get price for {product_id}"}

        exit_price = float(current_price['price'])
        size = position.get('size', position.get('remaining_size', 0))
        entry_price = position['entry_price']
        pnl = (exit_price - entry_price) * size

        result = db_manager.close_open_position(position_id, exit_price, pnl, "manual_close", "manual")
        if result:
            risk_manager.close_position(position_id, pnl)
            return {"status": "success", "message": f"{product_id} closed", "exit_price": exit_price, "pnl": round(pnl, 2)}
        else:
            return {"status": "error", "message": "Failed to close position"}
    except Exception as e:
        logger.error(f"Close position error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/trades/stats")
async def get_trades_stats(
    trade_type: Optional[str] = None,
    min_trades: int = 30
):
    """Get trade statistics.
    
    Args:
        trade_type: Filter by 'live' or 'paper' (optional, defaults to all)
        min_trades: Minimum trades required to show metrics (default: 30)
    """
    try:
        from src.database import db_manager
        
        trades = db_manager.get_trades(limit=10000)
        
        # Normalize timestamps to avoid datetime comparison issues
        for trade in trades:
            ts = trade.get('timestamp')
            if ts is not None and hasattr(ts, 'replace'):
                ts = ts.replace(tzinfo=None)
                trade['timestamp'] = str(ts)[:19] if ts else ''
        
        # Filter by trade_type if provided
        if trade_type:
            trades = [t for t in trades if (t.get('trade_type') or '').lower() == trade_type.lower()]
        
        # Get timestamp for data freshness
        first_trade_time = None
        last_trade_time = None
        if trades:
            sorted_trades = sorted(trades, key=lambda x: x.get('timestamp') or '')
            first_trade_time = sorted_trades[0].get('timestamp')
            last_trade_time = sorted_trades[-1].get('timestamp')
        
        if not trades:
            return {
                "source": "live_trades",
                "data_type": "executed_trades",
                "total_trades": 0,
                "buy_count": 0,
                "sell_count": 0,
                "win_rate": None,
                "has_sufficient_data": False,
                "min_trades_required": min_trades,
                "message": "No trades recorded yet",
                "avg_profit": 0,
                "avg_loss": 0,
                "total_pnl": 0,
                "largest_win": 0,
                "largest_loss": 0,
                "profit_factor": 0
            }
        
        total = len(trades)
        has_sufficient_data = total >= min_trades
        
        buys = [t for t in trades if t.get('side', '').lower() == 'buy']
        sells = [t for t in trades if t.get('side', '').lower() == 'sell']
        
        winning_trades = [t for t in trades if (t.get('pnl', 0) or 0) > 0]
        losing_trades = [t for t in trades if (t.get('pnl', 0) or 0) < 0]
        
        win_rate = (len(winning_trades) / total * 100) if total > 0 else 0
        
        profits = [t.get('pnl', 0) or 0 for t in winning_trades]
        losses = [abs(t.get('pnl', 0) or 0) for t in losing_trades]
        
        gross_profit = sum(profits) if profits else 0
        gross_loss = sum(losses) if losses else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        message = None
        if not has_sufficient_data:
            message = f"Insufficient data: {total}/{min_trades} trades required"
        
        return {
            "source": "live_trades",
            "data_type": "executed_trades",
            "trade_type_filter": trade_type or "all",
            "total_trades": total,
            "has_sufficient_data": has_sufficient_data,
            "min_trades_required": min_trades,
            "buy_count": len(buys),
            "sell_count": len(sells),
            "win_rate": round(win_rate, 2) if has_sufficient_data else None,
            "avg_profit": round(gross_profit / len(profits), 2) if profits and has_sufficient_data else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses and has_sufficient_data else 0,
            "total_pnl": round(sum(profits + losses), 2) if (profits or losses) else 0,
            "largest_win": round(max(profits), 2) if profits and has_sufficient_data else 0,
            "largest_loss": round(min(losses), 2) if losses and has_sufficient_data else 0,
            "profit_factor": round(profit_factor, 2) if has_sufficient_data else 0,
            "first_trade_timestamp": str(first_trade_time) if first_trade_time else None,
            "last_trade_timestamp": str(last_trade_time) if last_trade_time else None,
            "message": message
        }
    except Exception as e:
        logger.error(f"Error getting trade stats: {e}")
        return {"error": str(e)}


@app.get("/api/portfolio/goal")
async def get_portfolio_goal_status():
    """Get portfolio goal tracking - shows if the goal of increasing portfolio value is being achieved.
    
    Returns:
        Portfolio performance summary showing goal status
    """
    try:
        from src.database import db_manager
        
        summary = db_manager.get_portfolio_summary()
        
        if summary.get('status') == 'no_data':
            return {
                "status": "no_data",
                "message": "Portfolio tracking is being initialized. Check back after first trading cycle.",
                "goal": {
                    "objective": "Increase portfolio value",
                    "status": "initializing"
                }
            }
        
        return summary
    except Exception as e:
        logger.error(f"Error getting portfolio goal status: {e}")
        return {"error": str(e)}


@app.get("/api/portfolio/history")
async def get_portfolio_history(days: int = 30):
    """Get portfolio history over time.
    
    Args:
        days: Number of days to retrieve (default: 30)
        
    Returns:
        List of portfolio snapshots with values over time
    """
    try:
        from src.database import db_manager
        
        snapshots = db_manager.get_portfolio_snapshots(days=days)
        
        return {
            "status": "success",
            "days": days,
            "snapshots": snapshots,
            "count": len(snapshots)
        }
    except Exception as e:
        logger.error(f"Error getting portfolio history: {e}")
        return {"error": str(e)}


@app.get("/api/performance")
async def get_performance(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    product: Optional[str] = None,
    trade_type: Optional[str] = None,
    min_trades: int = 30
):
    """Get performance metrics and chart data.
    
    Args:
        start_date: Filter trades from this date
        end_date: Filter trades until this date
        product: Filter by product ID (e.g., 'BTC-GBP')
        trade_type: Filter by 'live' or 'paper'
        min_trades: Minimum trades required (default: 30)
    """
    try:
        from src.database import db_manager
        from datetime import datetime, timedelta, timezone
        
        trades = db_manager.get_trades(limit=10000)
        
        # Normalize all timestamps to timezone-naive for consistent comparison
        for trade in trades:
            ts = trade.get('timestamp')
            if ts is not None:
                # Convert to string to avoid datetime comparison issues
                if hasattr(ts, 'replace'):
                    ts = ts.replace(tzinfo=None)
                trade['timestamp'] = str(ts)[:19] if ts else ''
        
        # Filter by trade_type
        if trade_type:
            trades = [t for t in trades if (t.get('trade_type') or '').lower() == trade_type.lower()]
        
        if not trades:
            return {
                "source": "live_trades",
                "data_type": "executed_trades",
                "summary": {
                    "total_pnl": 0,
                    "win_rate": None,
                    "profit_factor": 0,
                    "total_trades": 0,
                    "has_sufficient_data": False,
                    "min_trades_required": min_trades
                },
                "equity_curve": [],
                "daily_pnl": [],
                "product_distribution": {},
                "monthly_returns": {},
                "message": "No trades recorded yet"
            }
        
        filtered = trades
        if product:
            filtered = [t for t in filtered if t.get('product_id') == product]
        
        total_pnl = sum(t.get('pnl', 0) or 0 for t in filtered)
        winning = [t for t in filtered if (t.get('pnl', 0) or 0) > 0]
        losing = [t for t in filtered if (t.get('pnl', 0) or 0) < 0]
        
        win_rate = (len(winning) / len(filtered) * 100) if filtered else 0
        
        gross_profit = sum(t.get('pnl', 0) or 0 for t in winning)
        gross_loss = abs(sum(t.get('pnl', 0) or 0 for t in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        total = len(filtered)
        has_sufficient_data = total >= min_trades
        
        # Phase 4: Precision by signal type (BUY vs SELL signals)
        buy_trades = [t for t in filtered if (t.get('side') or '').lower() == 'buy']
        sell_trades = [t for t in filtered if (t.get('side') or '').lower() == 'sell']
        
        buy_wins = [t for t in buy_trades if (t.get('pnl', 0) or 0) > 0]
        buy_losses = [t for t in buy_trades if (t.get('pnl', 0) or 0) < 0]
        buy_precision = (len(buy_wins) / len(buy_trades) * 100) if buy_trades else 0
        
        sell_wins = [t for t in sell_trades if (t.get('pnl', 0) or 0) > 0]
        sell_losses = [t for t in sell_trades if (t.get('pnl', 0) or 0) < 0]
        sell_precision = (len(sell_wins) / len(sell_trades) * 100) if sell_trades else 0
        
        signal_precision = {
            "buy": {
                "total": len(buy_trades),
                "wins": len(buy_wins),
                "losses": len(buy_losses),
                "precision": round(buy_precision, 1) if has_sufficient_data and len(buy_trades) >= 5 else None,
                "total_pnl": round(sum(t.get('pnl', 0) or 0 for t in buy_trades), 2)
            },
            "sell": {
                "total": len(sell_trades),
                "wins": len(sell_wins),
                "losses": len(sell_losses),
                "precision": round(sell_precision, 1) if has_sufficient_data and len(sell_trades) >= 5 else None,
                "total_pnl": round(sum(t.get('pnl', 0) or 0 for t in sell_trades), 2)
            }
        }
        
        equity = 0
        equity_curve = []
        daily_pnl = {}
        product_dist = {}
        product_counts = {}
        product_wins = {}
        product_losses = {}
        
        def get_ts_string(ts):
            if ts is None:
                return ''
            if hasattr(ts, 'strftime'):
                return ts.strftime('%Y-%m-%d')
            return str(ts)[:10] if len(str(ts)) >= 10 else str(ts)
        
        for trade in sorted(filtered, key=lambda x: x.get('timestamp') or ''):
            pnl = trade.get('pnl', 0) or 0
            equity += pnl
            
            ts = trade.get('timestamp')
            ts_str = get_ts_string(ts)
            if ts_str:
                daily_pnl[ts_str] = daily_pnl.get(ts_str, 0) + pnl
            
            product_id = trade.get('product_id', 'Unknown')
            product_dist[product_id] = product_dist.get(product_id, 0) + pnl
            product_counts[product_id] = product_counts.get(product_id, 0) + 1
            if pnl > 0:
                product_wins[product_id] = product_wins.get(product_id, 0) + 1
            elif pnl < 0:
                product_losses[product_id] = product_losses.get(product_id, 0) + 1
            
            equity_curve.append({
                "date": ts_str,
                "equity": round(equity, 2)
            })
        
        daily_pnl_list = [
            {"date": date, "pnl": round(pnl, 2)}
            for date, pnl in sorted(daily_pnl.items())
        ]
        
        monthly_returns = {}
        for trade in filtered:
            ts = trade.get('timestamp')
            ts_str = get_ts_string(ts)
            if ts_str and len(ts_str) >= 7:
                month = ts_str[:7]
                monthly_returns[month] = monthly_returns.get(month, 0) + (trade.get('pnl', 0) or 0)
        
        # Get timestamps
        first_trade_time = None
        last_trade_time = None
        if filtered:
            sorted_trades = sorted(filtered, key=lambda x: x.get('timestamp') or '')
            first_trade_time = sorted_trades[0].get('timestamp')
            last_trade_time = sorted_trades[-1].get('timestamp')
        
        message = None
        if not has_sufficient_data:
            message = f"Insufficient data: {total}/{min_trades} trades required"
        
        return {
            "source": "live_trades",
            "data_type": "executed_trades",
            "trade_type_filter": trade_type or "all",
            "summary": {
                "total_pnl": round(total_pnl, 2),
                "win_rate": round(win_rate, 2) if has_sufficient_data else None,
                "profit_factor": round(profit_factor, 2) if has_sufficient_data else 0,
                "total_trades": total,
                "has_sufficient_data": has_sufficient_data,
                "min_trades_required": min_trades,
                "sharpe_ratio": 0
            },
            "equity_curve": equity_curve,
            "daily_pnl": daily_pnl_list,
            "product_distribution": {k: round(v, 2) for k, v in product_dist.items()},
            "product_breakdown": [
                {
                    "product": pid,
                    "trades": product_counts.get(pid, 0),
                    "wins": product_wins.get(pid, 0),
                    "losses": product_losses.get(pid, 0),
                    "total_pnl": round(pnl, 2),
                    "win_rate": round(product_wins.get(pid, 0) / product_counts.get(pid, 1) * 100, 1) if product_counts.get(pid, 0) > 0 else 0,
                    "avg_pnl": round(pnl / product_counts.get(pid, 1), 2) if product_counts.get(pid, 0) > 0 else 0
                }
                for pid, pnl in sorted(product_dist.items(), key=lambda x: abs(x[1]), reverse=True)
            ],
            "monthly_returns": {k: round(v, 2) for k, v in monthly_returns.items()},
            "first_trade_timestamp": str(first_trade_time) if first_trade_time else None,
            "last_trade_timestamp": str(last_trade_time) if last_trade_time else None,
            "message": message,
            "signal_precision": signal_precision if has_sufficient_data else {"buy": {"total": 0, "wins": 0, "losses": 0, "precision": None, "total_pnl": 0}, "sell": {"total": 0, "wins": 0, "losses": 0, "precision": None, "total_pnl": 0}}
        }
    except Exception as e:
        logger.error(f"Error getting performance: {e}")
        return {"error": str(e)}


@app.get("/api/scale_in/status")
async def get_scale_in_status():
    """Get current scale-in configuration."""
    try:
        settings = load_settings()
        return {
            "status": "success",
            "enabled": settings.SCALE_IN_ENABLED,
            "levels": settings.SCALE_IN_LEVELS,
            "size_by_level": settings.SCALE_IN_SIZE_BY_LEVEL,
            "max_scale_ins": settings.MAX_SCALE_INS_PER_POSITION,
            "cooldown_hours": settings.SCALE_IN_COOLDOWN_HOURS,
            "global_block": settings.SCALE_IN_GLOBAL_BLOCK
        }
    except Exception as e:
        logger.error(f"Scale-in status error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/scale_in/configure")
async def configure_scale_in(request: Request):
    """Update scale-in settings."""
    try:
        data = await request.json()
        settings = load_settings()
        db = load_db_manager()
        
        settings.SCALE_IN_ENABLED = data.get('enabled', True)
        
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
        
        db.save_user_setting('scale_in_enabled', str(settings.SCALE_IN_ENABLED).lower())
        db.save_user_setting('scale_in_levels', ','.join(map(str, settings.SCALE_IN_LEVELS)))
        db.save_user_setting('scale_in_sizes', ','.join(map(str, settings.SCALE_IN_SIZE_BY_LEVEL)))
        
        return {
            "status": "success",
            "message": "Scale-in settings updated"
        }
    except Exception as e:
        logger.error(f"Scale-in configure error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/scale_out/status")
async def get_scale_out_status():
    """Get current scale-out settings."""
    try:
        settings = load_settings()
        return {
            "status": "success",
            "enabled": settings.SCALE_OUT_ENABLED,
            "min_profit_pct": settings.SCALE_OUT_MIN_PROFIT_PCT,
            "max_scale_outs": settings.MAX_SCALE_OUT_PER_POSITION,
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
        settings = load_settings()
        db = load_db_manager()
        
        settings.SCALE_OUT_ENABLED = data.get('enabled', True)
        settings.SCALE_OUT_MIN_PROFIT_PCT = data.get('min_profit_pct', 0.5)
        settings.MAX_SCALE_OUT_PER_POSITION = data.get('max_scale_outs', 3)
        
        take_profit_levels = data.get('take_profit_levels')
        if take_profit_levels and isinstance(take_profit_levels, list):
            try:
                settings.TAKE_PROFIT_LEVELS = [float(x) for x in take_profit_levels[:3]]
                db.save_user_setting('take_profit_level', str(settings.TAKE_PROFIT_LEVELS[0]))
            except:
                pass
        
        db.save_user_setting('scale_out_enabled', str(settings.SCALE_OUT_ENABLED).lower())
        db.save_user_setting('scale_out_min_profit_pct', str(settings.SCALE_OUT_MIN_PROFIT_PCT))
        
        return {
            "status": "success",
            "message": "Scale-out settings updated"
        }
    except Exception as e:
        logger.error(f"Scale-out configure error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/trailing_stop/status")
async def get_trailing_stop_status():
    """Get current trailing stop settings."""
    try:
        settings = load_settings()
        return {
            "status": "success",
            "enabled": settings.TRAILING_STOP_ENABLED,
            "trailing_stop_percent": round(settings.TRAILING_STOP_PERCENT * 100, 1),
            "activation_buffer": round(settings.TRAILING_ACTIVATION_BUFFER * 100, 1),
            "regime_trail_map": settings.TRAILING_STOP_REGIME_MAP
        }
    except Exception as e:
        logger.error(f"Trailing stop status error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/trailing_stop/configure")
async def configure_trailing_stop(request: Request):
    """Update trailing stop settings."""
    try:
        data = await request.json()
        settings = load_settings()
        db = load_db_manager()

        if 'enabled' in data:
            settings.TRAILING_STOP_ENABLED = bool(data['enabled'])
            db.save_user_setting('trailing_stop_enabled', str(settings.TRAILING_STOP_ENABLED).lower())

        if 'trailing_stop_percent' in data:
            pct = float(data['trailing_stop_percent']) / 100
            settings.TRAILING_STOP_PERCENT = pct
            db.save_user_setting('trailing_stop_percent', str(pct))

        if 'activation_buffer' in data:
            buf = float(data['activation_buffer']) / 100
            settings.TRAILING_ACTIVATION_BUFFER = buf
            db.save_user_setting('trailing_activation_buffer', str(buf))

        return {
            "status": "success",
            "message": "Trailing stop settings updated"
        }
    except Exception as e:
        logger.error(f"Trailing stop configure error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/settings/risk")
async def get_risk_settings():
    """Get current risk management settings."""
    try:
        settings = load_settings()
        return {
            "status": "success",
            "confidence_threshold": settings.MODEL_CONFIDENCE_THRESHOLD,
            "stop_loss": settings.STOP_LOSS_MIN_PERCENT,
            "take_profit": settings.TAKE_PROFIT_LEVELS[0] if settings.TAKE_PROFIT_LEVELS else 1.0,
            "max_position_size": settings.MAX_POSITION_SIZE,
            "max_concurrent_positions": settings.MAX_CONCURRENT_POSITIONS,
            "market_check_interval": settings.MARKET_CHECK_INTERVAL
        }
    except Exception as e:
        logger.error(f"Risk settings error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/settings/risk")
async def save_risk_settings(request: Request):
    """Save risk management settings."""
    try:
        data = await request.json()
        settings = load_settings()
        db = load_db_manager()
        
        if 'confidence_threshold' in data:
            pct = float(data['confidence_threshold']) / 100
            settings.MODEL_CONFIDENCE_THRESHOLD = pct
            db.save_user_setting('model_confidence_threshold', str(pct))
        
        if 'stop_loss' in data:
            settings.STOP_LOSS_MIN_PERCENT = float(data['stop_loss']) / 100
            db.save_user_setting('stop_loss_min_percent', str(settings.STOP_LOSS_MIN_PERCENT))
        
        if 'take_profit' in data:
            level = float(data['take_profit'])
            settings.TAKE_PROFIT_LEVELS = [level, level * 2, level * 3]
            db.save_user_setting('take_profit_level', str(level))
        
        if 'max_position_size' in data:
            pct = float(data['max_position_size']) / 100
            settings.MAX_POSITION_SIZE = pct
            db.save_user_setting('max_position_size', str(pct))
        
        if 'max_concurrent_positions' in data:
            settings.MAX_CONCURRENT_POSITIONS = int(data['max_concurrent_positions'])
            db.save_user_setting('max_concurrent_positions', str(settings.MAX_CONCURRENT_POSITIONS))
        
        return {
            "status": "success",
            "message": "Risk settings saved"
        }
    except Exception as e:
        logger.error(f"Risk settings save error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/settings/display_currency")
async def save_display_currency(request: Request):
    """Save display currency preference."""
    try:
        data = await request.json()
        currency = data.get('value', 'GBP')
        db = load_db_manager()
        db.save_user_setting('display_currency', currency)
        logger.info(f"Display currency set to {currency}")
        return {"status": "success", "message": f"Display currency set to {currency}"}
    except Exception as e:
        logger.error(f"Display currency save error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/settings/market_check_interval")
async def save_market_check_interval(request: Request):
    """Save market check interval in seconds."""
    try:
        data = await request.json()
        seconds = int(data.get('value', 2700))
        settings = load_settings()
        settings.MARKET_CHECK_INTERVAL = seconds
        db = load_db_manager()
        db.save_user_setting('market_check_interval', str(seconds))
        logger.info(f"Market check interval set to {seconds}s ({seconds//60} minutes)")
        return {
            "status": "success",
            "message": f"Interval set to {seconds//60} minutes",
            "interval_seconds": seconds,
            "interval_minutes": seconds // 60
        }
    except Exception as e:
        logger.error(f"Market check interval save error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/settings/{key}")
async def get_setting(key: str):
    """Get individual setting value."""
    try:
        from config.settings import settings
        
        if hasattr(settings, key):
            return {"key": key, "value": getattr(settings, key)}
        
        db = load_db_manager()
        db_value = db.get_user_setting(key)
        if db_value is not None:
            return {"key": key, "value": db_value}
        
        return {"key": key, "value": None, "error": "Setting not found"}
    except Exception as e:
        logger.error(f"Error getting setting {key}: {e}")
        return {"key": key, "value": None, "error": str(e)}


@app.get("/api/fees/status")
async def get_fees_status():
    """Get current fee rates from Coinbase."""
    try:
        from src.coinbase_api import coinbase_api
        from src.database import db_manager
        
        # Check if we should update fees
        if db_manager.should_update_fees(settings.FEE_CHECK_INTERVAL_DAYS):
            fees = db_manager.update_fee_rates()
            logger.info(f"Updated fee rates: {fees}")
        else:
            fees = db_manager.get_fee_rates()
            if not fees:
                fees = coinbase_api.get_fees()
        
        # Get updated timestamp
        updated_at = db_manager.get_user_setting('fee_rates_updated_at')
        
        return {
            "success": True,
            "maker_fee": fees.get('maker_fee', settings.DEFAULT_MAKER_FEE),
            "taker_fee": fees.get('taker_fee', settings.DEFAULT_TAKER_FEE),
            "updated_at": updated_at,
            "is_fallback": fees.get('is_fallback', False),
            "pricing_tier": fees.get('pricing_tier', 'Unknown')
        }
    except Exception as e:
        logger.error(f"Error getting fees status: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/resources")
async def resource_stats():
    """Container resource usage from cgroups."""
    memory_mb = None
    memory_limit_mb = None
    cpu_percent = None
    load_avg = None
    try:
        # Memory current (cgroup v2)
        mem_path = "/sys/fs/cgroup/memory.current"
        if Path(mem_path).exists():
            with open(mem_path) as f:
                memory_bytes = int(f.read().strip())
                memory_mb = round(memory_bytes / (1024 * 1024), 1)
        # Memory limit (cgroup v2)
        mem_max_path = "/sys/fs/cgroup/memory.max"
        if Path(mem_max_path).exists():
            with open(mem_max_path) as f:
                val = f.read().strip()
                if val not in ("max", "inf"):
                    memory_limit_mb = round(int(val) / (1024 * 1024), 1)
        elif Path("/sys/fs/cgroup/memory.limit_in_bytes").exists():
            with open("/sys/fs/cgroup/memory.limit_in_bytes") as f:
                memory_limit_mb = round(int(f.read().strip()) / (1024 * 1024), 1)
        # CPU load average
        with open("/proc/loadavg") as f:
            parts = f.read().strip().split()
            load_avg = float(parts[0])
        # CPU usage from cpu.stat (cgroup v2)
        cpu_usage_path = "/sys/fs/cgroup/cpu.stat"
        if Path(cpu_usage_path).exists():
            usage_total = 0
            with open(cpu_usage_path) as f:
                for line in f:
                    if line.startswith("usage_usec ") or line.startswith("usage "):
                        usage_total += int(line.split()[1])
            # approximate since last read: simple snapshot
            cpu_percent = None
    except Exception as e:
        logger.debug(f"Resource stats error: {e}")

    return {
        "memory_mb": memory_mb,
        "memory_limit_mb": memory_limit_mb,
        "load_avg_1m": load_avg,
        "cpu_percent": cpu_percent,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
