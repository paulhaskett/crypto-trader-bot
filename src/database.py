"""
Database module for the crypto trading bot.

This module handles all database operations including:
- Trade history storage and retrieval
- Market data caching
- Performance metrics tracking
- Configuration persistence
- Open position persistence

Educational Notes:
- Uses SQLAlchemy ORM for database abstraction
- SQLite for simplicity and reliability on Raspberry Pi
- Thread-safe operations for concurrent access
- Automatic schema management and migrations
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, UniqueConstraint, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from config.settings import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


class Trade(Base):
    """
    Database model for storing trade information.

    Each trade record contains all details about a completed transaction,
    including entry/exit prices, timestamps, and profit/loss calculations.
    """
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True)
    order_id = Column(String(50), unique=True, nullable=False)
    product_id = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.now)
    status = Column(String(20), default='completed')
    pnl = Column(Float, default=0.0)
    fees = Column(Float, default=0.0)
    trade_type = Column(String(10), default='paper')

    def __repr__(self):
        return f"<Trade(order_id='{self.order_id}', product_id='{self.product_id}', side='{self.side}', price={self.price})>"


class MarketData(Base):
    """
    Database model for caching market data.

    Stores historical price data to avoid repeated API calls and
    enable faster backtesting and analysis.
    """
    __tablename__ = 'market_data'

    id = Column(Integer, primary_key=True)
    product_id = Column(String(20), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    def __repr__(self):
        return f"<MarketData(product_id='{self.product_id}', timestamp='{self.timestamp}', close={self.close_price})>"


class PerformanceMetrics(Base):
    """
    Database model for storing performance statistics.

    Tracks daily/weekly/monthly performance, win rates, and risk metrics
    to analyze the bot's effectiveness over time.
    """
    __tablename__ = 'performance_metrics'

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)

    def __repr__(self):
        return f"<PerformanceMetrics(date='{self.date}', total_pnl={self.total_pnl}, win_rate={self.win_rate})>"


class PriceAggregationMetrics(Base):
    """
    Database model for storing multi-source price aggregation metrics.
    
    Tracks consensus prices, source data, and quality metrics
    for analyzing price data quality over time.
    """
    __tablename__ = 'price_aggregation_metrics'
    
    id = Column(Integer, primary_key=True)
    product_id = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    
    # Consensus price
    consensus_price = Column(Float, nullable=False)
    confidence = Column(Float, default=0.0)
    
    # Source prices (JSON for flexibility)
    coinbase_price = Column(Float)
    coingecko_price = Column(Float)
    kraken_price = Column(Float)
    
    # Source metadata
    sources_used = Column(String(100))  # Comma-separated list
    outlier_sources = Column(String(100))  # Comma-separated list
    max_deviation_pct = Column(Float, default=0.0)
    
    # Volume data
    volume_24h = Column(Float)
    
    # Verification (Chainlink)
    verification_passed = Column(Boolean, default=True)
    reference_price = Column(Float)
    reference_source = Column(String(20))
    
    # Latency
    latency_ms = Column(Float)
    
    __table_args__ = (
        Index('idx_price_agg_product_time', 'product_id', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<PriceAggregationMetrics(product_id='{self.product_id}', price={self.consensus_price}, confidence={self.confidence})>"


class PortfolioSnapshot(Base):
    """
    Database model for tracking portfolio value over time.
    
    Stores daily snapshots of the total portfolio value (GBP + crypto)
    to track performance against the goal of increasing portfolio value.
    """
    __tablename__ = 'portfolio_snapshots'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    
    # Portfolio components
    gbp_balance = Column(Float, nullable=False)
    crypto_value = Column(Float, nullable=False)
    
    # Calculated totals
    total_value = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)
    
    # Metrics
    daily_change = Column(Float, default=0.0)  # Change from previous snapshot
    daily_change_pct = Column(Float, default=0.0)
    
    # Trade stats at time of snapshot
    trades_today = Column(Integer, default=0)
    pnl_today = Column(Float, default=0.0)
    fees_today = Column(Float, default=0.0)
    
    __table_args__ = (
        Index('idx_portfolio_timestamp', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<PortfolioSnapshot(total_value={self.total_value}, timestamp={self.timestamp})>"


class UserSettings(Base):
    """
    Database model for storing user preferences and settings.

    Persists user choices like currency preferences, risk settings,
    and other configuration options across sessions.
    """
    __tablename__ = 'user_settings'

    id = Column(Integer, primary_key=True)
    setting_key = Column(String(50), nullable=False, unique=True)
    setting_value = Column(String(100), nullable=False)
    setting_type = Column(String(20), default='string')
    updated_at = Column(DateTime, default=datetime.now)

    __table_args__ = (UniqueConstraint('setting_key', name='unique_setting_key'),)

    def __repr__(self):
        return f"<UserSettings(key='{self.setting_key}', value='{self.setting_value}')>"


class OpenPosition(Base):
    """
    Database model for storing open positions.

    Persists open positions so they survive container rebuilds.
    Tracks entry price, size, stop loss, and current P&L.
    """
    __tablename__ = 'open_positions'

    id = Column(Integer, primary_key=True)
    position_id = Column(String(50), unique=True, nullable=False)
    product_id = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, default=0.0)
    stop_loss_price = Column(Float, default=0.0)
    signal_action = Column(String(10), default='HOLD')
    signal_confidence = Column(Float, default=0.0)
    status = Column(String(20), default='open')
    position_type = Column(String(20), default='normal')
    opened_at = Column(DateTime, default=datetime.now)
    pnl = Column(Float, default=0.0)
    exit_reason = Column(String(100), default='')
    closed_at = Column(DateTime, nullable=True)
    trade_type = Column(String(10), default='paper')
    peak_price = Column(Float, default=0.0)  # Track peak price for trailing stop
    entry_reason = Column(String(200), default='')  # NEW: Track why position was opened (e.g., "AI BUY, conf=72%, regime=uptrend")
    
    # Position Scaling (Averaging Down) fields
    scale_in_count = Column(Integer, default=0)  # Number of scale-ins performed
    last_scale_in_price = Column(Float, default=0.0)  # Price of last scale-in
    last_scale_in_time = Column(DateTime, nullable=True)  # When last scale-in occurred
    total_scale_in_size = Column(Float, default=0.0)  # Cumulative size from scale-ins
    weighted_entry_price = Column(Float, default=0.0)  # Weighted average entry price
    scale_in_levels_triggered = Column(String(50), default="")  # Comma-separated levels triggered (e.g., "1,2")
    
    # Position Scaling (Taking Profits) fields
    scale_out_count = Column(Integer, default=0)  # Number of scale-outs performed
    scale_out_levels_triggered = Column(String(50), default="")  # Comma-separated levels triggered (e.g., "1,2")
    last_scale_out_price = Column(Float, default=0.0)  # Price of last scale-out
    last_scale_out_time = Column(DateTime, nullable=True)  # When last scale-out occurred
    remaining_size = Column(Float, default=0.0)  # Remaining position size after scale-outs

    def __repr__(self):
        return f"<OpenPosition(position_id='{self.position_id}', product_id='{self.product_id}', side='{self.side}', pnl={self.pnl})>"


class Holding(Base):
    """
    Database model for tracking current holdings (what crypto we own).
    
    This is the source of truth for what the bot currently holds.
    """
    __tablename__ = 'holdings'

    id = Column(Integer, primary_key=True)
    product_id = Column(String(20), nullable=False, index=True)  # e.g., "ETH-GBP" - removed unique constraint to allow historical positions
    side = Column(String(10), nullable=False)  # "buy" (we own crypto)
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    coinbase_order_id = Column(String(50), nullable=True)  # Coinbase trade ID
    opened_at = Column(DateTime, default=datetime.now)
    trade_type = Column(String(10), default='live')  # 'paper' or 'live'

    def __repr__(self):
        return f"<Holding(product_id='{self.product_id}', side='{self.side}', size={self.size}, entry={self.entry_price})>"


class DatabaseManager:
    """
    Main database manager class.

    Handles all database operations including connections, sessions,
    and CRUD operations for all models.
    """

    def __init__(self, database_url: str = None):
        """
        Initialize the database manager.

        Args:
            database_url: Database connection string (defaults to settings)
        """
        self.database_url = database_url or settings.DATABASE_URL
        self.engine = None
        self.SessionLocal = None

        self._initialize_database()

    def _initialize_database(self):
        """Create database engine and tables."""
        try:
            self.engine = create_engine(
                self.database_url,
                connect_args={
                    "check_same_thread": False,
                    "timeout": 30  # Wait up to 30s for locks
                }
            )
            Base.metadata.create_all(bind=self.engine)
            
            # Enable WAL mode for better concurrency (allows concurrent reads with one writer)
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA busy_timeout=30000"))
                conn.commit()
            
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            logger.info(f"Database initialized at {self.database_url} with WAL mode")
            
            # Run migrations to add missing columns
            self._migrate_open_positions()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _migrate_open_positions(self):
        """Add missing columns to open_positions table for migrations."""
        session = self.get_session()
        try:
            columns_to_add = [
                ('scale_in_count', 'INTEGER DEFAULT 0'),
                ('last_scale_in_price', 'REAL DEFAULT 0.0'),
                ('last_scale_in_time', 'TIMESTAMP'),
                ('total_scale_in_size', 'REAL DEFAULT 0.0'),
                ('weighted_entry_price', 'REAL DEFAULT 0.0'),
            ]
            
            for col_name, col_type in columns_to_add:
                try:
                    session.execute(text(f"ALTER TABLE open_positions ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"Migration: Added column {col_name}")
                except Exception:
                    pass  # Column already exists
            session.commit()
        except Exception as e:
            logger.warning(f"Migration warning: {e}")
        finally:
            session.close()

    def _calculate_take_profits(self, entry_price: float, stop_price: float, regime: str = 'neutral') -> List[float]:
        """Calculate take profit levels using regime-based absolute percentages.
        
        Args:
            entry_price: Position entry price
            stop_price: Stop loss price (unused, kept for compatibility)
            regime: Market regime ('uptrend', 'neutral', 'downtrend')
            
        Returns:
            List of take profit prices
        """
        if not entry_price or entry_price <= 0:
            return []
        
        regime_multipliers = {
            'uptrend': [5.0, 7.5, 10.0],
            'neutral': [4.0, 6.0, 8.0],
            'downtrend': [2.0, 4.0, 6.0]
        }
        
        levels = regime_multipliers.get(regime, [2.0, 3.0, 4.0])
        return [entry_price * (1 + pct / 100) for pct in levels]

    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()

    def save_trade(self, trade_data: Dict[str, Any]) -> bool:
        """Save a completed trade to the database."""
        session = self.get_session()
        try:
            # Check for duplicate order_id to prevent double-saving
            existing = session.query(Trade).filter(
                Trade.order_id == trade_data['order_id']
            ).first()
            if existing:
                logger.warning(f"Trade with order_id {trade_data['order_id']} already exists, skipping duplicate")
                return True
            
            trade = Trade(
                order_id=trade_data['order_id'],
                product_id=trade_data['product_id'],
                side=trade_data['side'],
                size=trade_data['size'],
                price=trade_data['price'],
                timestamp=trade_data.get('timestamp', datetime.now()),
                status=trade_data.get('status', 'completed'),
                pnl=trade_data.get('pnl', 0.0),
                fees=trade_data.get('fees', 0.0),
                trade_type=trade_data.get('trade_type', 'paper')
            )
            session.add(trade)
            session.commit()
            logger.info(f"Saved trade: {trade.order_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save trade: {e}")
            return False
        finally:
            session.close()

    def save_holding(self, product_id: str, side: str, size: float, entry_price: float, 
                    coinbase_order_id: str = None, trade_type: str = 'live') -> bool:
        """Save or update a holding in the database."""
        session = self.get_session()
        try:
            # Check if holding exists for this product
            existing = session.query(Holding).filter(Holding.product_id == product_id).first()
            
            if existing:
                # Update existing holding
                existing.side = side
                existing.size = size
                existing.entry_price = entry_price
                existing.coinbase_order_id = coinbase_order_id
                existing.trade_type = trade_type
                existing.opened_at = datetime.now()
                logger.info(f"Updated holding: {product_id}")
            else:
                # Create new holding
                holding = Holding(
                    product_id=product_id,
                    side=side,
                    size=size,
                    entry_price=entry_price,
                    coinbase_order_id=coinbase_order_id,
                    trade_type=trade_type
                )
                session.add(holding)
                logger.info(f"Saved new holding: {product_id}")
            
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save holding: {e}")
            return False
        finally:
            session.close()

    def get_holdings(self, trade_type: str = None) -> Dict[str, Dict[str, Any]]:
        """Get all holdings from database."""
        session = self.get_session()
        try:
            query = session.query(Holding)
            if trade_type:
                query = query.filter(Holding.trade_type == trade_type)
            
            holdings = query.all()
            result = {}
            for h in holdings:
                result[h.product_id] = {
                    'product_id': h.product_id,
                    'side': h.side,
                    'size': h.size,
                    'entry_price': h.entry_price,
                    'coinbase_order_id': h.coinbase_order_id,
                    'opened_at': h.opened_at.isoformat() if h.opened_at else None,
                    'trade_type': h.trade_type,
                    'has_position': True
                }
            logger.info(f"Loaded {len(result)} holdings from database")
            return result
        except Exception as e:
            logger.error(f"Failed to get holdings: {e}")
            return {}
        finally:
            session.close()

    def close_open_position_by_product(self, product_id: str, exit_price: float, pnl: float, reason: str) -> bool:
        """Mark all open positions as closed by product_id."""
        session = self.get_session()
        try:
            positions = session.query(OpenPosition).filter(
                OpenPosition.product_id == product_id,
                OpenPosition.status == 'open'
            ).all()
            
            if positions:
                for position in positions:
                    position.status = 'closed'
                    position.current_price = exit_price
                    position.pnl = pnl
                    position.exit_reason = reason
                    position.closed_at = datetime.now()
                session.commit()
                logger.info(f"Closed {len(positions)} position(s) for {product_id}: {reason}, P&L: {pnl}")
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to close position by product: {e}")
            return False
        finally:
            session.close()

    def clear_holding(self, product_id: str) -> bool:
        """Remove a holding when sold."""
        session = self.get_session()
        try:
            holding = session.query(Holding).filter(Holding.product_id == product_id).first()
            if holding:
                session.delete(holding)
                session.commit()
                logger.info(f"Cleared holding: {product_id}")
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to clear holding: {e}")
            return False
        finally:
            session.close()

    def clear_all_holdings(self) -> int:
        """Clear all holdings."""
        session = self.get_session()
        try:
            count = session.query(Holding).delete()
            session.commit()
            logger.info(f"Cleared {count} holdings")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to clear holdings: {e}")
            return 0
        finally:
            session.close()

    def get_holdings_for_display(self) -> List[Dict[str, Any]]:
        """
        Get holdings in a format compatible with dashboard display.
        Returns list of holdings with all fields needed by the UI.
        """
        holdings = self.get_holdings()
        result = []
        for product_id, h in holdings.items():
            if h.get('has_position'):
                result.append({
                    'product_id': product_id,
                    'side': h.get('side', 'buy'),
                    'size': h.get('size', 0),
                    'entry_price': h.get('entry_price', 0),
                    'current_price': 0,  # Will be filled by API
                    'stop_loss_price': 0,
                    'signal_action': 'HOLD',
                    'signal_confidence': 0,
                    'status': 'open',
                    'opened_at': h.get('opened_at'),
                    'pnl': 0,
                    'trade_type': h.get('trade_type', 'live'),
                    'coinbase_order_id': h.get('coinbase_order_id')
                })
        return result

    def get_trades(self, product_id: str = None, trade_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve trade history from the database."""
        session = self.get_session()
        try:
            query = session.query(Trade).order_by(Trade.timestamp.desc())
            if product_id:
                query = query.filter(Trade.product_id == product_id)
            if trade_type and trade_type != 'all':
                query = query.filter(Trade.trade_type == trade_type)
            trades = query.limit(limit).all()
            return [{
                'id': trade.id,
                'order_id': trade.order_id,
                'product_id': trade.product_id,
                'side': trade.side,
                'size': trade.size,
                'price': trade.price,
                'timestamp': trade.timestamp,
                'status': trade.status,
                'pnl': trade.pnl,
                'fees': trade.fees,
                'trade_type': trade.trade_type
            } for trade in trades]
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []
        finally:
            session.close()

    def update_trade_pnl(self, order_id: str, pnl: float, fees: float = 0.0) -> bool:
        """Update the profit/loss for a completed trade."""
        session = self.get_session()
        try:
            trade = session.query(Trade).filter(Trade.order_id == order_id).first()
            if trade:
                trade.pnl = pnl
                trade.fees = fees
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update trade P&L: {e}")
            return False
        finally:
            session.close()

    def clear_all_trades(self) -> int:
        """Delete all trades from the database."""
        session = self.get_session()
        try:
            deleted_count = session.query(Trade).delete()
            session.commit()
            logger.info(f"Deleted {deleted_count} trades from database")
            return deleted_count
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to clear trades: {e}")
            return 0
        finally:
            session.close()
    
    def clear_old_trades(self, days: int = 30) -> int:
        """Delete trades older than specified days. Keeps recent trades."""
        session = self.get_session()
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            deleted_count = session.query(Trade).filter(
                Trade.timestamp < cutoff_date
            ).delete()
            session.commit()
            logger.info(f"Deleted {deleted_count} trades older than {days} days")
            return deleted_count
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to clear old trades: {e}")
            return 0
        finally:
            session.close()

    def save_market_data(self, product_id: str, candles_df) -> bool:
        """Save market data (candles) to the database."""
        session = self.get_session()
        try:
            market_data_records = []
            for timestamp, row in candles_df.iterrows():
                market_data_records.append(MarketData(
                    product_id=product_id,
                    timestamp=timestamp.to_pydatetime(),
                    open_price=row['open'],
                    high_price=row['high'],
                    low_price=row['low'],
                    close_price=row['close'],
                    volume=row['volume']
                ))
            session.add_all(market_data_records)
            session.commit()
            logger.info(f"Saved {len(market_data_records)} market data records for {product_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save market data: {e}")
            return False
        finally:
            session.close()

    def get_market_data(self, product_id: str, start_date: datetime = None,
                        end_date: datetime = None) -> List[Dict[str, Any]]:
        """Retrieve historical market data from the database."""
        session = self.get_session()
        try:
            query = session.query(MarketData).filter(
                MarketData.product_id == product_id
            ).order_by(MarketData.timestamp.desc())  # Order DESC to get newest first
            if start_date:
                query = query.filter(MarketData.timestamp >= start_date)
            if end_date:
                query = query.filter(MarketData.timestamp <= end_date)
            
            # Limit to avoid slow queries - just get last 500 records
            query = query.limit(500)
            
            records = query.all()
            result = []
            for record in records:
                result.append({
                    'timestamp': record.timestamp.isoformat(),
                    'open': record.open_price,
                    'high': record.high_price,
                    'low': record.low_price,
                    'close': record.close_price,
                    'volume': record.volume
                })
            return result
        except Exception as e:
            logger.error(f"Failed to retrieve market data: {e}")
            return []
        finally:
            session.close()

    def save_performance_metrics(self, metrics: Dict[str, Any]) -> bool:
        """Save performance metrics to the database."""
        session = self.get_session()
        try:
            perf_metrics = PerformanceMetrics(
                date=metrics.get('date', datetime.now()),
                total_trades=metrics.get('total_trades', 0),
                winning_trades=metrics.get('winning_trades', 0),
                total_pnl=metrics.get('total_pnl', 0.0),
                max_drawdown=metrics.get('max_drawdown', 0.0),
                sharpe_ratio=metrics.get('sharpe_ratio', 0.0),
                win_rate=metrics.get('win_rate', 0.0)
            )
            session.add(perf_metrics)
            session.commit()
            logger.info(f"Saved performance metrics for {perf_metrics.date}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save performance metrics: {e}")
            return False
        finally:
            session.close()

    def get_performance_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get performance summary for the specified period."""
        session = self.get_session()
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            metrics = session.query(PerformanceMetrics).filter(
                PerformanceMetrics.date >= cutoff_date
            ).all()
            if not metrics:
                return {'total_trades': 0, 'win_rate': 0.0, 'total_pnl': 0.0, 'max_drawdown': 0.0, 'period_days': days}
            total_trades = sum(m.total_trades for m in metrics)
            winning_trades = sum(m.winning_trades for m in metrics)
            total_pnl = sum(m.total_pnl for m in metrics)
            max_drawdown = max(m.max_drawdown for m in metrics)
            win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0
            return {
                'total_trades': total_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'max_drawdown': max_drawdown,
                'period_days': days
            }
        except Exception as e:
            logger.error(f"Failed to get performance summary: {e}")
            return {}
        finally:
            session.close()

    def get_all_user_settings(self) -> Dict[str, str]:
        """Retrieve all user settings from the database."""
        session = self.get_session()
        try:
            settings = session.query(UserSettings).all()
            result = {}
            for setting in settings:
                result[setting.setting_key] = setting.setting_value
            return result
        except Exception as e:
            logger.error(f"Failed to retrieve user settings: {e}")
            return {}
        finally:
            session.close()

    def save_open_position(self, position_data: Dict[str, Any]) -> bool:
        """Save or update an open position in the database.
        
        Uses product_id as the key - one position per crypto.
        Prevents duplicates by removing any extra open positions for same product_id+trade_type.
        """
        session = self.get_session()
        try:
            product_id = position_data.get('product_id')
            trade_type = position_data.get('trade_type', 'paper')
            
            # Find ALL existing positions for this product_id (to prevent duplicates)
            existing_positions = session.query(OpenPosition).filter(
                OpenPosition.product_id == product_id,
                OpenPosition.trade_type == trade_type,
                OpenPosition.status == 'open'
            ).all()
            
            if len(existing_positions) > 1:
                # Keep the most recent one, close the rest
                logger.warning(f"Found {len(existing_positions)} open positions for {product_id}, cleaning up duplicates")
                sorted_positions = sorted(existing_positions, key=lambda p: p.opened_at if p.opened_at else datetime.min, reverse=True)
                for dup in sorted_positions[1:]:  # All except the first (most recent)
                    dup.status = 'closed'
                    dup.exit_reason = 'duplicate_cleanup'
                    logger.info(f"Closed duplicate position {dup.position_id} for {product_id}")
                session.commit()
            
            existing = existing_positions[0] if existing_positions else None

            if existing:
                # Update existing position
                existing.side = position_data.get('side', existing.side)
                existing.size = position_data.get('size', existing.size)
                existing.entry_price = position_data.get('entry_price', existing.entry_price)
                existing.current_price = position_data.get('current_price', existing.current_price)
                existing.pnl = position_data.get('pnl', existing.pnl)
                # Only update opened_at if explicitly provided (don't overwrite with current time)
                if 'opened_at' in position_data:
                    opened_at_val = position_data['opened_at']
                    # Handle string datetime format
                    if isinstance(opened_at_val, str):
                        try:
                            from datetime import datetime
                            opened_at_val = datetime.fromisoformat(opened_at_val.replace('Z', '+00:00'))
                        except:
                            pass  # Keep as-is if parsing fails
                    existing.opened_at = opened_at_val
                # Scale-in fields
                if 'scale_in_count' in position_data:
                    existing.scale_in_count = position_data['scale_in_count']
                if 'last_scale_in_price' in position_data:
                    existing.last_scale_in_price = position_data['last_scale_in_price']
                if 'last_scale_in_time' in position_data:
                    existing.last_scale_in_time = position_data['last_scale_in_time']
                if 'total_scale_in_size' in position_data:
                    existing.total_scale_in_size = position_data['total_scale_in_size']
                if 'weighted_entry_price' in position_data:
                    existing.weighted_entry_price = position_data['weighted_entry_price']
                if 'scale_in_levels_triggered' in position_data:
                    existing.scale_in_levels_triggered = position_data['scale_in_levels_triggered']
                if 'stop_loss_price' in position_data:
                    existing.stop_loss_price = position_data['stop_loss_price']
                if 'peak_price' in position_data:
                    existing.peak_price = position_data['peak_price']
                if 'entry_reason' in position_data:
                    existing.entry_reason = position_data['entry_reason']
                # Scale-out fields
                if 'scale_out_count' in position_data:
                    existing.scale_out_count = position_data['scale_out_count']
                if 'scale_out_levels_triggered' in position_data:
                    existing.scale_out_levels_triggered = position_data['scale_out_levels_triggered']
                if 'last_scale_out_price' in position_data:
                    existing.last_scale_out_price = position_data['last_scale_out_price']
                if 'last_scale_out_time' in position_data:
                    existing.last_scale_out_time = position_data['last_scale_out_time']
                if 'remaining_size' in position_data:
                    new_remaining = position_data['remaining_size']
                    existing_scale_out = existing.scale_out_count or 0
                    
                    # Validate: remaining_size should never exceed size
                    if new_remaining > existing.size:
                        logger.warning(f"Invalid remaining_size {new_remaining} > size {existing.size} for {product_id}, resetting to size")
                        new_remaining = existing.size
                    
                    # Validate: remaining_size should not be less than size unless scale-out was recorded
                    elif new_remaining < existing.size and existing_scale_out == 0:
                        logger.warning(f"Invalid remaining_size {new_remaining} < size {existing.size} for {product_id} with no scale_out, resetting to size")
                        new_remaining = existing.size
                    
                    # Validate: remaining_size should equal size if no scale-outs
                    elif new_remaining == existing.size and existing_scale_out > 0:
                        logger.warning(f"Invalid remaining_size {new_remaining} == size but scale_out={existing_scale_out} for {product_id}, calculating correct value")
                        # Calculate based on scale-out percentages [33, 50, 100]
                        if existing_scale_out == 1:
                            new_remaining = existing.size * 0.67
                        elif existing_scale_out == 2:
                            new_remaining = existing.size * 0.335
                        elif existing_scale_out >= 3:
                            new_remaining = 0
                    
                    existing.remaining_size = new_remaining
                logger.info(f"Updated position for {product_id}: {position_data.get('side')} @ {position_data.get('entry_price')}")
            else:
                # Create new position - generate position_id
                import uuid
                position_id = str(uuid.uuid4())
                
                # Filter to only include fields that exist in the model
                model_fields = ['position_id', 'product_id', 'side', 'size', 'entry_price', 
                              'current_price', 'stop_loss_price', 'signal_action', 'signal_confidence',
                              'status', 'position_type', 'opened_at', 'pnl', 'trade_type',
                              'peak_price', 'entry_reason', 'scale_in_count', 'last_scale_in_price', 'last_scale_in_time',
                              'total_scale_in_size', 'weighted_entry_price',
                              'scale_out_count', 'scale_out_levels_triggered', 'last_scale_out_price',
                              'last_scale_out_time', 'remaining_size']
                filtered_data = {k: v for k, v in position_data.items() if k in model_fields}
                
                # Validate entry_price and weighted_entry_price - must not be None
                if filtered_data.get('entry_price') is None:
                    logger.error(f"Cannot save position for {product_id}: entry_price is None")
                    return False
                if filtered_data.get('weighted_entry_price') is None:
                    filtered_data['weighted_entry_price'] = filtered_data.get('entry_price', 0) or 0
                
                # Ensure numeric values are valid floats
                for field in ['entry_price', 'weighted_entry_price', 'current_price', 'stop_loss_price', 'peak_price', 'remaining_size']:
                    if field in filtered_data and (filtered_data[field] is None or not isinstance(filtered_data[field], (int, float))):
                        filtered_data[field] = 0.0
                
                filtered_data['position_id'] = position_id
                filtered_data['status'] = 'open'
                
                # Handle opened_at - it might be a datetime object or string
                if 'opened_at' in filtered_data and isinstance(filtered_data['opened_at'], str):
                    filtered_data['opened_at'] = datetime.fromisoformat(filtered_data['opened_at'].replace('Z', '+00:00'))
                
                new_position = OpenPosition(**filtered_data)
                session.add(new_position)
                logger.info(f"Saved new position for {product_id}: {position_data.get('side')} @ {position_data.get('entry_price')}")

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save open position: {e}")
            return False
        finally:
            session.close()

    def update_position_current_price(self, product_id: str, current_price: float) -> bool:
        """Update current_price for tracking price changes between API calls.
        
        Args:
            product_id: The trading pair (e.g., 'BTC-GBP')
            current_price: The current market price
            
        Returns:
            True if updated, False otherwise
        """
        session = self.get_session()
        try:
            result = session.query(OpenPosition).filter(
                OpenPosition.product_id == product_id,
                OpenPosition.status == 'open'
            ).update({'current_price': current_price})
            session.commit()
            return result > 0
        except Exception as e:
            logger.error(f"Failed to update position price: {e}")
            return False
        finally:
            session.close()

    def load_open_positions(self, trade_type: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Load all open positions from the database.
        
        Args:
            trade_type: If provided, only load positions matching this type ('paper' or 'live')
        """
        session = self.get_session()
        try:
            # First, find and expire old waiting positions
            try:
                from datetime import timedelta
                max_hours = 4
                cutoff_time = datetime.now() - timedelta(hours=max_hours)
                
                # Update old waiting positions to expired
                expired = session.query(OpenPosition).filter(
                    OpenPosition.status == 'waiting_for_drop',
                    OpenPosition.opened_at < cutoff_time
                ).update({'status': 'expired'})
                if expired > 0:
                    logger.warning(f"Auto-expired {expired} old waiting positions")
                    session.commit()
            except Exception as e:
                logger.error(f"Failed to auto-expire positions: {e}")
            
            query = session.query(OpenPosition).filter(
                OpenPosition.status == 'open'
            )
            if trade_type:
                query = query.filter(OpenPosition.trade_type == trade_type)
            positions = query.all()

            # Update peak prices using cached current_price from DB (don't fetch fresh - too slow)
            # The current_price is already updated by the trading cycle
            peak_updated = False
            for pos in positions:
                current_price = pos.current_price or 0.0
                if current_price > 0:
                    current_peak = pos.peak_price if pos.peak_price else pos.entry_price
                    if current_price > current_peak:
                        pos.peak_price = current_price
                        peak_updated = True
            if peak_updated:
                session.commit()

            # Key by product_id - one position per crypto
            # Keep only latest position per product_id (in case of duplicates)
            position_by_product = {}
            for pos in positions:
                if pos.product_id in position_by_product:
                    # Keep the one opened more recently
                    existing = position_by_product[pos.product_id]
                    if pos.opened_at and existing['opened_at_dt'] and pos.opened_at > existing['opened_at_dt']:
                        position_by_product[pos.product_id] = {
                            'position_id': str(pos.position_id),
                            'product_id': pos.product_id,
                            'side': pos.side,
                            'size': pos.size,
                            'entry_price': pos.entry_price,
                            'peak_price': pos.peak_price if pos.peak_price else pos.entry_price,
                            'current_price': pos.current_price or 0.0,
                            'stop_loss_price': pos.stop_loss_price or 0.0,
                            'status': pos.status,
                            'opened_at': pos.opened_at.isoformat() if pos.opened_at else None,
                            'opened_at_dt': pos.opened_at,
                            'pnl': pos.pnl or 0.0,
                            'trade_type': pos.trade_type,
                            'signal_action': pos.signal_action or 'HOLD',
                            'signal_confidence': pos.signal_confidence or 0.0,
                            'take_profit_prices': self._calculate_take_profits(pos.entry_price, pos.stop_loss_price or 0, regime='neutral'),
                            'scale_in_count': pos.scale_in_count or 0,
                            'last_scale_in_price': pos.last_scale_in_price or 0.0,
                            'last_scale_in_time': pos.last_scale_in_time,
                            'total_scale_in_size': pos.total_scale_in_size or 0.0,
                            'weighted_entry_price': pos.weighted_entry_price or pos.entry_price,
                            'scale_out_count': pos.scale_out_count or 0,
                            'scale_out_levels_triggered': pos.scale_out_levels_triggered or "",
                            'last_scale_out_price': pos.last_scale_out_price or 0.0,
                            'last_scale_out_time': pos.last_scale_out_time,
                            'remaining_size': pos.remaining_size if pos.remaining_size and pos.remaining_size > 0 else pos.size
                        }
                else:
                    position_by_product[pos.product_id] = {
                        'position_id': str(pos.position_id),
                        'product_id': pos.product_id,
                        'side': pos.side,
                        'size': pos.size,
                        'entry_price': pos.entry_price,
                        'peak_price': pos.peak_price if pos.peak_price else pos.entry_price,
                        'current_price': pos.current_price or 0.0,
                        'stop_loss_price': pos.stop_loss_price or 0.0,
                        'status': pos.status,
                        'opened_at': pos.opened_at.isoformat() if pos.opened_at else None,
                        'opened_at_dt': pos.opened_at,
                        'pnl': pos.pnl or 0.0,
                        'trade_type': pos.trade_type,
                        'signal_action': pos.signal_action or 'HOLD',
                        'signal_confidence': pos.signal_confidence or 0.0,
                        'take_profit_prices': self._calculate_take_profits(pos.entry_price, pos.stop_loss_price or 0, regime='neutral'),
                        'scale_in_count': pos.scale_in_count or 0,
                        'last_scale_in_price': pos.last_scale_in_price or 0.0,
                        'last_scale_in_time': pos.last_scale_in_time,
                        'total_scale_in_size': pos.total_scale_in_size or 0.0,
                        'weighted_entry_price': pos.weighted_entry_price or pos.entry_price,
                        'scale_out_count': pos.scale_out_count or 0,
                        'scale_out_levels_triggered': pos.scale_out_levels_triggered or "",
                        'last_scale_out_price': pos.last_scale_out_price or 0.0,
                        'last_scale_out_time': pos.last_scale_out_time,
                        'remaining_size': pos.remaining_size if pos.remaining_size and pos.remaining_size > 0 else pos.size
                    }
            
            # Remove the temporary datetime field before returning
            result = {}
            for product_id, pos_data in position_by_product.items():
                pos_data_copy = pos_data.copy()
                pos_data_copy.pop('opened_at_dt', None)
                result[product_id] = pos_data_copy
            
            logger.info(f"Loaded {len(result)} positions from database (keyed by product_id)")
            return result
        except Exception as e:
            logger.error(f"Failed to load open positions: {e}")
            return {}
        finally:
            session.close()

    def update_open_position_price(self, position_id: str, current_price: float, pnl: float) -> bool:
        """Update current price and P&L for an open position."""
        session = self.get_session()
        try:
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()
            if position:
                position.current_price = current_price
                position.pnl = pnl
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update position price: {e}")
            return False
        finally:
            session.close()

    def update_peak_price(self, position_id: str, peak_price: float) -> bool:
        """Update peak price for trailing stop tracking."""
        session = self.get_session()
        try:
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()
            if position:
                old_peak = position.peak_price
                position.peak_price = peak_price
                session.commit()
                logger.info(f"[DB] Updated peak_price for {position.product_id}: £{old_peak:.2f} -> £{peak_price:.2f}")
                return True
            logger.warning(f"[DB] Could not find position {position_id} to update peak_price")
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"[DB] Failed to update peak price for {position_id}: {e}")
            return False
        finally:
            session.close()

    def update_stop_loss_price(self, position_id: str, stop_loss_price: float) -> bool:
        """Update stop loss price for a position."""
        session = self.get_session()
        try:
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()
            if position:
                position.stop_loss_price = stop_loss_price
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update stop loss price: {e}")
            return False
        finally:
            session.close()

    def update_scale_out_state(self, position_id: str, triggered_levels: str, 
                               last_scale_out_price: float, remaining_size: float) -> bool:
        """Update scale-out state after partial profit-taking."""
        session = self.get_session()
        try:
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()
            if position:
                position.scale_out_levels_triggered = triggered_levels
                position.last_scale_out_price = last_scale_out_price
                position.last_scale_out_time = datetime.now()
                position.remaining_size = remaining_size
                position.scale_out_count = len(triggered_levels.split(',')) if triggered_levels else 0
                session.commit()
                logger.info(f"Updated scale-out state: levels={triggered_levels}, remaining={remaining_size}")
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update scale-out state: {e}")
            return False
        finally:
            session.close()

    def update_scale_in_state(self, position_id: str, weighted_entry_price: float,
                              last_scale_in_price: float, scale_in_count: int,
                              total_size: float) -> bool:
        """Update scale-in state after averaging down."""
        session = self.get_session()
        try:
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()
            if position:
                position.weighted_entry_price = weighted_entry_price
                position.last_scale_in_price = last_scale_in_price
                position.last_scale_in_time = datetime.now()
                position.scale_in_count = scale_in_count
                position.total_scale_in_size = total_size - position.size  # Additional size added
                position.size = total_size  # Update total position size
                position.remaining_size = total_size
                session.commit()
                logger.info(
                    f"Updated scale-in state: count={scale_in_count}, "
                    f"weighted=£{weighted_entry_price:.2f}, total_size={total_size}"
                )
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update scale-in state: {e}")
            return False
        finally:
            session.close()

    def close_open_position(self, position_id: str, exit_price: float, pnl: float, reason: str, exit_reason: str = '') -> bool:
        """Mark an open position as closed."""
        session = self.get_session()
        try:
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()
            if position:
                product_before = position.product_id
                status_before = position.status
                
                position.status = 'closed'
                position.current_price = exit_price
                position.pnl = pnl
                position.exit_reason = exit_reason or reason
                position.closed_at = datetime.now()
                session.commit()
                
                # Verify the close worked
                position_after = session.query(OpenPosition).filter(
                    OpenPosition.position_id == position_id
                ).first()
                
                if position_after and position_after.status == 'closed':
                    logger.info(f"Successfully closed position {position_id[:8]}... ({product_before}): {exit_reason or reason}, P&L: {pnl}")
                    return True
                else:
                    logger.error(f"Position {position_id[:8]}... status NOT updated to closed!")
                    return False
            logger.warning(f"Position {position_id[:8]}... not found in database")
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to close position {position_id[:8]}...: {e}")
            return False
        finally:
            session.close()

    def get_closed_positions(self, limit: int = 20) -> List[Dict]:
        """Get closed positions with P&L information."""
        session = self.get_session()
        try:
            positions = session.query(OpenPosition).filter(
                OpenPosition.status == 'closed'
            ).order_by(OpenPosition.closed_at.desc()).limit(limit).all()
            
            result = []
            for p in positions:
                result.append({
                    'position_id': p.position_id,
                    'product_id': p.product_id,
                    'side': p.side,
                    'size': p.size,
                    'entry_price': p.entry_price,
                    'exit_price': p.current_price,
                    'pnl': p.pnl,
                    'exit_reason': p.exit_reason,
                    'opened_at': p.opened_at.isoformat() if p.opened_at else None,
                    'closed_at': p.closed_at.isoformat() if p.closed_at else None,
                    'trade_type': p.trade_type,
                    'position_type': getattr(p, 'position_type', 'normal'),
                    'scale_out_count': getattr(p, 'scale_out_count', 0) or 0,
                    'scale_out_levels_triggered': getattr(p, 'scale_out_levels_triggered', '') or '',
                    'original_size': getattr(p, 'total_scale_in_size', 0) + p.size if p.size > 0 else p.size
                })
            return result
        except Exception as e:
            logger.error(f"Failed to get closed positions: {e}")
            return []
        finally:
            session.close()

    def clear_all_open_positions(self) -> int:
        """Delete all open positions from the database."""
        session = self.get_session()
        try:
            deleted_count = session.query(OpenPosition).delete()
            session.commit()
            logger.info(f"Deleted {deleted_count} open positions from database")
            return deleted_count
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to clear open positions: {e}")
            return 0
        finally:
            session.close()

    def get_all_open_positions_detailed(self) -> List[Dict[str, Any]]:
        """Get all open positions with full details for dashboard display."""
        session = self.get_session()
        try:
            # Use cached current_price from DB - don't fetch fresh (too slow)
            # The current_price is updated by the trading cycle
            
            positions = session.query(OpenPosition).filter(
                OpenPosition.status.in_(['open', 'waiting_for_drop'])
            ).all()
            result = []
            for pos in positions:
                # Use cached price from DB
                product_id = pos.product_id
                current_price = pos.current_price or 0.0
                
                # Update peak price if current price is higher
                current_peak = pos.peak_price if pos.peak_price else pos.entry_price
                if current_price > current_peak:
                    pos.peak_price = current_price
                    session.commit()
                    logger.info(f"[REAL_TIME_PEAK] {product_id}: £{current_peak:.2f} -> £{current_price:.2f}")
                
                position_data = {
                    'position_id': pos.position_id,
                    'product_id': pos.product_id,
                    'side': pos.side,
                    'size': pos.size,
                    'entry_price': pos.entry_price,
                    'current_price': current_price,
                    'stop_loss_price': pos.stop_loss_price,
                    'peak_price': pos.peak_price if pos.peak_price else pos.entry_price,
                    'signal_action': pos.signal_action,
                    'signal_confidence': pos.signal_confidence,
                    'status': pos.status,
                    'position_type': getattr(pos, 'position_type', 'normal'),
                    'opened_at': pos.opened_at.isoformat() if pos.opened_at else None,
                    'pnl': pos.pnl,
                    'trade_type': pos.trade_type or 'live',
                    'scale_in_count': pos.scale_in_count or 0,
                    'last_scale_in_price': pos.last_scale_in_price or 0.0,
                    'total_scale_in_size': pos.total_scale_in_size or 0.0,
                    'weighted_entry_price': pos.weighted_entry_price or pos.entry_price
                }
                
                result.append(position_data)
            return result
        except Exception as e:
            logger.error(f"Failed to get open positions: {e}")
            return []
        finally:
            session.close()

    def save_user_setting(self, setting_key: str, setting_value: str, setting_type: str = 'string') -> bool:
        """Save or update a user setting in the database."""
        session = self.get_session()
        try:
            existing = session.query(UserSettings).filter(
                UserSettings.setting_key == setting_key
            ).first()
            if existing:
                existing.setting_value = setting_value
                existing.setting_type = setting_type
                existing.updated_at = datetime.now()
            else:
                session.add(UserSettings(
                    setting_key=setting_key,
                    setting_value=setting_value,
                    setting_type=setting_type
                ))
            session.commit()
            logger.info(f"Saved user setting: {setting_key} = {setting_value}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save user setting: {e}")
            return False
        finally:
            session.close()

    def get_user_setting(self, setting_key: str, default_value: Optional[str] = None) -> Optional[str]:
        """Retrieve a user setting from the database."""
        session = self.get_session()
        try:
            setting = session.query(UserSettings).filter(
                UserSettings.setting_key == setting_key
            ).first()
            return setting.setting_value if setting else default_value
        except Exception as e:
            logger.error(f"Failed to retrieve user setting: {e}")
            return default_value
        finally:
            session.close()

    def get_trading_active(self) -> bool:
        """Get the current trading active state."""
        setting = self.get_user_setting('trading_active', 'false')
        return setting.lower() == 'true' if setting else False

    def set_trading_active(self, active: bool) -> bool:
        """Set the trading active state."""
        return self.save_user_setting('trading_active', str(active).lower(), 'boolean')

    def get_paper_trading(self) -> bool:
        """Get the current trading mode (paper vs live)."""
        setting = self.get_user_setting('paper_trading', 'true')
        return setting.lower() == 'true'

    def set_paper_trading(self, paper_trading: bool) -> bool:
        """Set the trading mode (paper vs live)."""
        return self.save_user_setting('paper_trading', str(paper_trading).lower(), 'boolean')

    def save_fee_rates(self, maker_fee: float, taker_fee: float) -> bool:
        """Save fee rates to database."""
        try:
            maker_success = self.save_user_setting('coinbase_maker_fee', str(maker_fee), 'float')
            taker_success = self.save_user_setting('coinbase_taker_fee', str(taker_fee), 'float')
            timestamp_success = self.save_user_setting(
                'fee_rates_updated_at', 
                datetime.now().isoformat(), 
                'datetime'
            )
            logger.info(f"Saved fee rates: maker={maker_fee:.4f}, taker={taker_fee:.4f}")
            return maker_success and taker_success and timestamp_success
        except Exception as e:
            logger.error(f"Failed to save fee rates: {e}")
            return False

    def get_fee_rates(self) -> Optional[Dict[str, Any]]:
        """Get fee rates from database."""
        try:
            maker_fee = self.get_user_setting('coinbase_maker_fee')
            taker_fee = self.get_user_setting('coinbase_taker_fee')
            updated_at = self.get_user_setting('fee_rates_updated_at')
            
            if maker_fee and taker_fee:
                return {
                    'maker_fee': float(maker_fee),
                    'taker_fee': float(taker_fee),
                    'updated_at': updated_at,
                    'is_fallback': False
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get fee rates: {e}")
            return None

    def should_update_fees(self, interval_days: int = 7) -> bool:
        """Check if fees should be updated based on interval."""
        try:
            updated_at = self.get_user_setting('fee_rates_updated_at')
            if not updated_at:
                return True
            
            last_update = datetime.fromisoformat(updated_at)
            days_since_update = (datetime.now() - last_update).days
            return days_since_update >= interval_days
        except Exception as e:
            logger.error(f"Failed to check fee update status: {e}")
            return True

    def update_fee_rates(self) -> Dict[str, Any]:
        """Update fee rates from Coinbase API."""
        from src.coinbase_api import coinbase_api
        
        try:
            summary = coinbase_api.get_transaction_summary()
            
            if summary:
                self.save_fee_rates(
                    maker_fee=summary['maker_fee_rate'],
                    taker_fee=summary['taker_fee_rate']
                )
                return {
                    'maker_fee': summary['maker_fee_rate'],
                    'taker_fee': summary['taker_fee_rate'],
                    'pricing_tier': summary.get('pricing_tier', 'Unknown'),
                    'is_fallback': False
                }
            
            # Return current cached or default
            cached = self.get_fee_rates()
            if cached:
                return cached
            
            from config.settings import settings
            return {
                'maker_fee': settings.DEFAULT_MAKER_FEE,
                'taker_fee': settings.DEFAULT_TAKER_FEE,
                'is_fallback': True
            }
        except Exception as e:
            logger.error(f"Failed to update fee rates: {e}")
            from config.settings import settings
            return {
                'maker_fee': settings.DEFAULT_MAKER_FEE,
                'taker_fee': settings.DEFAULT_TAKER_FEE,
                'is_fallback': True,
                'error': str(e)
            }

    def clean_dust_positions(self, min_size: float = 0.0001) -> int:
        """
        Close any open positions with size below minimum threshold (dust positions).
        
        Args:
            min_size: Minimum size threshold (default 0.0001)
            
        Returns:
            Number of dust positions cleaned up
        """
        session = self.get_session()
        try:
            # Find dust positions
            dust_positions = session.query(OpenPosition).filter(
                OpenPosition.status == 'open',
                OpenPosition.size < min_size
            ).all()
            
            count = 0
            for pos in dust_positions:
                logger.warning(f"Cleaning dust position: {pos.product_id} size={pos.size}")
                pos.status = 'closed'
                pos.exit_reason = 'dust_position_cleanup'
                pos.closed_at = datetime.now()
                count += 1
            
            if count > 0:
                session.commit()
                logger.info(f"Cleaned up {count} dust positions")
            
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to clean dust positions: {e}")
            return 0
        finally:
            session.close()

    def save_portfolio_snapshot(
        self,
        gbp_balance: float,
        crypto_value: float,
        unrealized_pnl: float = 0.0,
        trades_today: int = 0,
        pnl_today: float = 0.0,
        fees_today: float = 0.0
    ) -> bool:
        """
        Save a portfolio snapshot for tracking over time.
        
        Args:
            gbp_balance: Current GBP balance
            crypto_value: Current value of crypto holdings
            unrealized_pnl: Unrealized profit/loss from open positions
            trades_today: Number of trades executed today
            pnl_today: Realized P&L for today
            fees_today: Fees paid today
            
        Returns:
            True if successful
        """
        session = self.get_session()
        try:
            total_value = gbp_balance + crypto_value
            
            # Get previous snapshot for daily change calculation
            prev_snapshot = session.query(PortfolioSnapshot).order_by(
                PortfolioSnapshot.timestamp.desc()
            ).first()
            
            daily_change = 0.0
            daily_change_pct = 0.0
            if prev_snapshot:
                daily_change = total_value - prev_snapshot.total_value
                if prev_snapshot.total_value > 0:
                    daily_change_pct = (daily_change / prev_snapshot.total_value) * 100
            
            snapshot = PortfolioSnapshot(
                timestamp=datetime.now(),
                gbp_balance=gbp_balance,
                crypto_value=crypto_value,
                total_value=total_value,
                unrealized_pnl=unrealized_pnl,
                daily_change=daily_change,
                daily_change_pct=daily_change_pct,
                trades_today=trades_today,
                pnl_today=pnl_today,
                fees_today=fees_today
            )
            session.add(snapshot)
            session.commit()
            
            logger.info(f"Saved portfolio snapshot: £{total_value:.2f} (daily: £{daily_change:.2f})")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save portfolio snapshot: {e}")
            return False
        finally:
            session.close()

    def get_portfolio_snapshots(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get portfolio snapshots for the specified number of days.
        
        Args:
            days: Number of days to retrieve
            
        Returns:
            List of portfolio snapshot dictionaries
        """
        session = self.get_session()
        try:
            cutoff = datetime.now() - timedelta(days=days)
            snapshots = session.query(PortfolioSnapshot).filter(
                PortfolioSnapshot.timestamp >= cutoff
            ).order_by(PortfolioSnapshot.timestamp.asc()).all()
            
            return [
                {
                    'timestamp': s.timestamp.isoformat(),
                    'gbp_balance': s.gbp_balance,
                    'crypto_value': s.crypto_value,
                    'total_value': s.total_value,
                    'unrealized_pnl': s.unrealized_pnl,
                    'daily_change': s.daily_change,
                    'daily_change_pct': s.daily_change_pct,
                    'trades_today': s.trades_today,
                    'pnl_today': s.pnl_today,
                    'fees_today': s.fees_today
                }
                for s in snapshots
            ]
        except Exception as e:
            logger.error(f"Failed to get portfolio snapshots: {e}")
            return []
        finally:
            session.close()

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """
        Get a summary of portfolio performance including goal tracking.
        
        Returns:
            Dictionary with portfolio summary and goal status
        """
        session = self.get_session()
        try:
            # Get first and latest snapshots
            first_snapshot = session.query(PortfolioSnapshot).order_by(
                PortfolioSnapshot.timestamp.asc()
            ).first()
            
            latest_snapshot = session.query(PortfolioSnapshot).order_by(
                PortfolioSnapshot.timestamp.desc()
            ).first()
            
            if not latest_snapshot:
                return {
                    'status': 'no_data',
                    'message': 'No portfolio snapshots recorded yet'
                }
            
            # Calculate overall performance
            total_change = 0.0
            total_change_pct = 0.0
            if first_snapshot:
                total_change = latest_snapshot.total_value - first_snapshot.total_value
                if first_snapshot.total_value > 0:
                    total_change_pct = (total_change / first_snapshot.total_value) * 100
            
            # Calculate metrics
            days_tracked = (latest_snapshot.timestamp - first_snapshot.timestamp).days if first_snapshot else 0
            
            # Get daily average
            avg_daily_change = total_change / days_tracked if days_tracked > 0 else 0
            
            # Goal tracking (simple: is total value increasing?)
            goal_achieved = total_change > 0
            
            # Count snapshots
            snapshot_count = session.query(PortfolioSnapshot).count()
            
            return {
                'status': 'success',
                'tracking': {
                    'started': first_snapshot.timestamp.isoformat() if first_snapshot else None,
                    'days_tracked': days_tracked,
                    'snapshots_count': snapshot_count
                },
                'current': {
                    'timestamp': latest_snapshot.timestamp.isoformat(),
                    'gbp_balance': latest_snapshot.gbp_balance,
                    'crypto_value': latest_snapshot.crypto_value,
                    'total_value': latest_snapshot.total_value,
                    'unrealized_pnl': latest_snapshot.unrealized_pnl,
                    'daily_change': latest_snapshot.daily_change,
                    'daily_change_pct': latest_snapshot.daily_change_pct
                },
                'performance': {
                    'starting_value': first_snapshot.total_value if first_snapshot else latest_snapshot.total_value,
                    'current_value': latest_snapshot.total_value,
                    'total_change': total_change,
                    'total_change_pct': total_change_pct,
                    'avg_daily_change': avg_daily_change,
                    'goal_achieved': goal_achieved
                },
                'goal': {
                    'objective': 'Increase portfolio value',
                    'status': 'achieved' if goal_achieved else 'not_achieved',
                    'change_needed': 'positive' if total_change > 0 else f"£{-total_change:.2f} to break even"
                }
            }
        except Exception as e:
            logger.error(f"Failed to get portfolio summary: {e}")
            return {'status': 'error', 'message': str(e)}
        finally:
            session.close()




def _migrate_database():
    """Add missing columns to existing tables."""
    session = db_manager.get_session()
    try:
        # Add trade_type to trades table if not exists
        try:
            session.execute(text("ALTER TABLE trades ADD COLUMN trade_type VARCHAR(10) DEFAULT 'paper'"))
            logger.info("Added trade_type column to trades table")
        except Exception:
            pass

        # Add trade_type to open_positions table if not exists
        try:
            session.execute(text("ALTER TABLE open_positions ADD COLUMN trade_type VARCHAR(10) DEFAULT 'paper'"))
            logger.info("Added trade_type column to open_positions table")
        except Exception:
            pass

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Migration failed: {e}")
    finally:
        session.close()

# Run migration on module import
try:
    _migrate_database()
except Exception:
    pass

db_manager = DatabaseManager()
