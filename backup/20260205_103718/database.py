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
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, UniqueConstraint, text
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
    opened_at = Column(DateTime, default=datetime.now)
    pnl = Column(Float, default=0.0)
    trade_type = Column(String(10), default='paper')

    def __repr__(self):
        return f"<OpenPosition(position_id='{self.position_id}', product_id='{self.product_id}', side='{self.side}', pnl={self.pnl})>"


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
                connect_args={"check_same_thread": False}
            )
            Base.metadata.create_all(bind=self.engine)
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            logger.info(f"Database initialized at {self.database_url}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()

    def save_trade(self, trade_data: Dict[str, Any]) -> bool:
        """Save a completed trade to the database."""
        session = self.get_session()
        try:
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
            ).order_by(MarketData.timestamp)
            if start_date:
                query = query.filter(MarketData.timestamp >= start_date)
            if end_date:
                query = query.filter(MarketData.timestamp <= end_date)
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
        """Save or update an open position in the database."""
        session = self.get_session()
        try:
            position_id = position_data.get('position_id')
            existing = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()

            if existing:
                existing.product_id = position_data.get('product_id', existing.product_id)
                existing.side = position_data.get('side', existing.side)
                existing.size = position_data.get('size', existing.size)
                existing.entry_price = position_data.get('entry_price', existing.entry_price)
                existing.current_price = position_data.get('current_price', existing.current_price)
                existing.stop_loss_price = position_data.get('stop_loss_price', existing.stop_loss_price)
                existing.signal_action = position_data.get('signal_action', existing.signal_action)
                existing.signal_confidence = position_data.get('signal_confidence', existing.signal_confidence)
                existing.status = position_data.get('status', existing.status)
                existing.pnl = position_data.get('pnl', existing.pnl)
                existing.trade_type = position_data.get('trade_type', existing.trade_type)
                logger.info(f"Updated open position: {position_id}")
            else:
                new_position = OpenPosition(
                    position_id=position_data['position_id'],
                    product_id=position_data['product_id'],
                    side=position_data['side'],
                    size=position_data['size'],
                    entry_price=position_data['entry_price'],
                    current_price=position_data.get('current_price', 0.0),
                    stop_loss_price=position_data.get('stop_loss_price', 0.0),
                    signal_action=position_data.get('signal_action', 'HOLD'),
                    signal_confidence=position_data.get('signal_confidence', 0.0),
                    status=position_data.get('status', 'open'),
                    opened_at=position_data.get('opened_at', datetime.now()),
                    pnl=position_data.get('pnl', 0.0),
                    trade_type=position_data.get('trade_type', 'paper')
                )
                session.add(new_position)
                logger.info(f"Saved new open position: {position_id}")

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save open position: {e}")
            return False
        finally:
            session.close()

    def load_open_positions(self) -> Dict[str, Dict[str, Any]]:
        """Load all open positions from the database."""
        session = self.get_session()
        try:
            positions = session.query(OpenPosition).filter(
                OpenPosition.status == 'open'
            ).all()

            result = {}
            for pos in positions:
                result[pos.position_id] = {
                    'position_id': pos.position_id,
                    'product_id': pos.product_id,
                    'side': pos.side,
                    'size': pos.size,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'stop_loss_price': pos.stop_loss_price,
                    'signal_action': pos.signal_action,
                    'signal_confidence': pos.signal_confidence,
                    'status': pos.status,
                    'opened_at': pos.opened_at.isoformat() if pos.opened_at else None,
                    'pnl': pos.pnl,
                    'trade_type': pos.trade_type
                }
            logger.info(f"Loaded {len(result)} open positions from database")
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

    def close_open_position(self, position_id: str, exit_price: float, pnl: float, reason: str) -> bool:
        """Mark an open position as closed."""
        session = self.get_session()
        try:
            position = session.query(OpenPosition).filter(
                OpenPosition.position_id == position_id
            ).first()
            if position:
                position.status = 'closed'
                position.current_price = exit_price
                position.pnl = pnl
                session.commit()
                logger.info(f"Closed position {position_id}: {reason}, P&L: {pnl}")
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to close position: {e}")
            return False
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
            positions = session.query(OpenPosition).filter(
                OpenPosition.status == 'open'
            ).all()
            result = []
            for pos in positions:
                result.append({
                    'position_id': pos.position_id,
                    'product_id': pos.product_id,
                    'side': pos.side,
                    'size': pos.size,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'stop_loss_price': pos.stop_loss_price,
                    'signal_action': pos.signal_action,
                    'signal_confidence': pos.signal_confidence,
                    'status': pos.status,
                    'opened_at': pos.opened_at.isoformat() if pos.opened_at else None,
                    'pnl': pos.pnl,
                    'trade_type': pos.trade_type or 'live'  # Default to live for safety
                })
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
