"""
Database module for the crypto trading bot.

This module handles all database operations including:
- Trade history storage and retrieval
- Market data caching
- Performance metrics tracking
- Configuration persistence

Educational Notes:
- Uses SQLAlchemy ORM for database abstraction
- SQLite for simplicity and reliability on Raspberry Pi
- Thread-safe operations for concurrent access
- Automatic schema management and migrations
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, UniqueConstraint
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
    side = Column(String(10), nullable=False)  # 'buy' or 'sell'
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.now)
    status = Column(String(20), default='completed')
    pnl = Column(Float, default=0.0)  # Profit/Loss for closed trades
    fees = Column(Float, default=0.0)

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
    setting_type = Column(String(20), default='string')  # 'string', 'integer', 'float', 'boolean'
    updated_at = Column(DateTime, default=datetime.now)
    
    __table_args__ = (UniqueConstraint('setting_key', name='unique_setting_key'),)

    def __repr__(self):
        return f"<UserSettings(key='{self.setting_key}', value='{self.setting_value}')>"


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
                connect_args={"check_same_thread": False}  # SQLite specific
            )

            # Create tables
            Base.metadata.create_all(bind=self.engine)

            # Create session factory
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
        """
        Save a completed trade to the database.

        Args:
            trade_data: Dictionary containing trade information

        Returns:
            True if saved successfully
        """
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
                fees=trade_data.get('fees', 0.0)
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

    def get_trades(self, product_id: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve trade history from the database.

        Args:
            product_id: Optional filter for specific trading pair
            limit: Maximum number of trades to return

        Returns:
            List of trade dictionaries
        """
        session = self.get_session()
        try:
            query = session.query(Trade).order_by(Trade.timestamp.desc())

            if product_id:
                query = query.filter(Trade.product_id == product_id)

            trades = query.limit(limit).all()

            result = []
            for trade in trades:
                result.append({
                    'id': trade.id,
                    'order_id': trade.order_id,
                    'product_id': trade.product_id,
                    'side': trade.side,
                    'size': trade.size,
                    'price': trade.price,
                    'timestamp': trade.timestamp.isoformat(),
                    'status': trade.status,
                    'pnl': trade.pnl,
                    'fees': trade.fees
                })

            return result

        except Exception as e:
            logger.error(f"Failed to update trade P&L: {e}")
            return False
        finally:
            session.close()

    def clear_all_trades(self) -> int:
        """
        Delete all trades from the database.

        This method removes all simulated/test trades while preserving
        user settings and market data cache.

        Returns:
            Number of trades deleted
        """
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

    def set_trading_active(self, active: bool) -> bool:
        """
        Set the trading active state.

        Args:
            active: Whether trading should be active

        Returns:
            True if updated successfully
        """
        return self.save_user_setting('trading_active', str(active).lower(), 'boolean')

    def get_trading_active(self) -> bool:
        """
        Get the current trading active state.

        Returns:
            True if trading is active, False otherwise
        """
        setting = self.get_user_setting('trading_active', 'false')
        return setting.lower() == 'true' if setting else False

    def update_trade_pnl(self, order_id: str, pnl: float, fees: float = 0.0) -> bool:
        """
        Update the profit/loss for a completed trade.

        Args:
            order_id: The order ID to update
            pnl: Profit/loss amount
            fees: Trading fees

        Returns:
            True if updated successfully
        """
        session = self.get_session()
        try:
            trade = session.query(Trade).filter(Trade.order_id == order_id).first()
            if trade:
                trade.pnl = pnl
                trade.fees = fees
                session.commit()
                logger.info(f"Updated P&L for trade {order_id}: {pnl}")
                return True
            else:
                logger.warning(f"Trade {order_id} not found for P&L update")
                return False

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update trade P&L: {e}")
            return False
        finally:
            session.close()

    def save_market_data(self, product_id: str, candles_df) -> bool:
        """
        Save market data (candles) to the database.

        Args:
            product_id: Trading pair identifier
            candles_df: Pandas DataFrame with OHLCV data

        Returns:
            True if saved successfully
        """
        session = self.get_session()
        try:
            # Convert DataFrame to database records
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
        """
        Retrieve historical market data from the database.

        Args:
            product_id: Trading pair identifier
            start_date: Start date for data retrieval
            end_date: End date for data retrieval

        Returns:
            List of market data dictionaries
        """
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
        """
        Save performance metrics to the database.

        Args:
            metrics: Dictionary containing performance statistics

        Returns:
            True if saved successfully
        """
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
        """
        Get performance summary for the specified period.

        Args:
            days: Number of days to look back

        Returns:
            Dictionary with performance statistics
        """
        session = self.get_session()
        try:
            cutoff_date = datetime.now() - timedelta(days=days)

            # Get recent performance metrics
            metrics = session.query(PerformanceMetrics).filter(
                PerformanceMetrics.date >= cutoff_date
            ).all()

            if not metrics:
                return {
                    'total_trades': 0,
                    'win_rate': 0.0,
                    'total_pnl': 0.0,
                    'max_drawdown': 0.0,
                    'period_days': days
                }

            # Aggregate metrics
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

    def save_user_setting(self, setting_key: str, setting_value: str, setting_type: str = 'string') -> bool:
        """
        Save or update a user setting in the database.

        Args:
            setting_key: Setting identifier (e.g., 'display_currency')
            setting_value: Setting value to store
            setting_type: Type of setting ('string', 'integer', 'float', 'boolean')

        Returns:
            True if saved successfully
        """
        session = self.get_session()
        try:
            # Check if setting exists
            existing_setting = session.query(UserSettings).filter(
                UserSettings.setting_key == setting_key
            ).first()

            if existing_setting:
                # Update existing setting
                existing_setting.setting_value = setting_value
                existing_setting.setting_type = setting_type
                existing_setting.updated_at = datetime.now()
            else:
                # Create new setting
                new_setting = UserSettings(
                    setting_key=setting_key,
                    setting_value=setting_value,
                    setting_type=setting_type
                )
                session.add(new_setting)

            session.commit()
            logger.info(f"Saved user setting: {setting_key} = {setting_value}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save user setting: {e}")
            return False
        finally:
            session.close()

    def get_user_setting(self, setting_key: str, default_value: str = None) -> Optional[str]:
        """
        Retrieve a user setting from the database.

        Args:
            setting_key: Setting identifier to retrieve
            default_value: Default value if setting not found

        Returns:
            Setting value or default if not found
        """
        session = self.get_session()
        try:
            setting = session.query(UserSettings).filter(
                UserSettings.setting_key == setting_key
            ).first()

            if setting:
                return setting.setting_value
            else:
                return default_value

        except Exception as e:
            logger.error(f"Failed to retrieve user setting: {e}")
            return default_value
        finally:
            session.close()

    def get_all_user_settings(self) -> Dict[str, str]:
        """
        Retrieve all user settings from the database.

        Returns:
            Dictionary of all settings key-value pairs
        """
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


# Global database instance
db_manager = DatabaseManager()