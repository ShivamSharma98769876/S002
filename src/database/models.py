"""
Database Models for Positions, Trades, and Daily Statistics
"""

from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
from typing import Optional
from src.utils.logger import get_logger

Base = declarative_base()


class Position(Base):
    """Position data model"""
    __tablename__ = 'positions'
    
    id = Column(Integer, primary_key=True)
    broker_id = Column(String, nullable=False, index=True)  # User ID from Kite API
    instrument_token = Column(String, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    entry_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float)
    quantity = Column(Integer, nullable=False)
    lot_size = Column(Integer, default=1)
    unrealized_pnl = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    trades = relationship("Trade", back_populates="position")
    
    __table_args__ = (
        Index('idx_broker_instrument_active', 'broker_id', 'instrument_token', 'is_active'),
        Index('idx_broker_active', 'broker_id', 'is_active'),
    )


class Trade(Base):
    """Completed trade data model"""
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    broker_id = Column(String, nullable=False, index=True)  # User ID from Kite API
    position_id = Column(Integer, ForeignKey('positions.id'), nullable=True)
    instrument_token = Column(String, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    exit_time = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)  # Positive for BUY, Negative for SELL
    transaction_type = Column(String, nullable=False, default='BUY')  # 'BUY' or 'SELL'
    realized_pnl = Column(Float, nullable=False)
    is_profit = Column(Boolean, nullable=False)
    exit_type = Column(String, nullable=False)  # 'manual', 'auto_loss_limit', 'auto_trailing_sl'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    position = relationship("Position", back_populates="trades")
    
    __table_args__ = (
        Index('idx_broker_trade_date', 'broker_id', 'exit_time'),
        Index('idx_broker_trade_symbol', 'broker_id', 'trading_symbol'),
    )


class DailyStats(Base):
    """Daily statistics model"""
    __tablename__ = 'daily_stats'
    
    id = Column(Integer, primary_key=True)
    broker_id = Column(String, nullable=False, index=True)  # User ID from Kite API
    date = Column(DateTime, nullable=False, index=True)
    total_realized_pnl = Column(Float, default=0.0)
    total_unrealized_pnl = Column(Float, default=0.0)
    protected_profit = Column(Float, default=0.0)
    number_of_trades = Column(Integer, default=0)
    daily_loss_used = Column(Float, default=0.0)
    daily_loss_limit = Column(Float, default=5000.0)
    loss_limit_hit = Column(Boolean, default=False)
    trading_blocked = Column(Boolean, default=False)
    trailing_sl_active = Column(Boolean, default=False)
    trailing_sl_level = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_broker_date', 'broker_id', 'date', unique=True),
    )


class AuditLog(Base):
    """Audit log for critical operations"""
    __tablename__ = 'audit_logs'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    action = Column(String, nullable=False)
    user = Column(String, nullable=True)
    details = Column(String, nullable=True)  # JSON string
    ip_address = Column(String, nullable=True)
    
    __table_args__ = (
        Index('idx_audit_timestamp', 'timestamp'),
        Index('idx_audit_action', 'action'),
    )


class DailyPurgeFlag(Base):
    """Track daily purge status to avoid purging multiple times per day"""
    __tablename__ = 'daily_purge_flags'
    
    id = Column(Integer, primary_key=True)
    broker_id = Column(String, nullable=False, index=True)  # User ID from Kite API
    purge_date = Column(DateTime, nullable=False, index=True)  # Date when purge was done
    purge_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)  # Exact time of purge
    trades_deleted = Column(Integer, default=0)  # Number of trades deleted
    
    __table_args__ = (
        Index('idx_broker_purge_date', 'broker_id', 'purge_date', unique=True),
    )


class Candle(Base):
    """Candle/OHLCV data model for storing historical and live candle data"""
    __tablename__ = 'candles'
    
    id = Column(Integer, primary_key=True)
    segment = Column(String, nullable=False, index=True)  # 'NIFTY', 'BANKNIFTY', 'SENSEX'
    timestamp = Column(DateTime, nullable=False, index=True)
    interval = Column(String, nullable=False)  # '3minute', '5minute', '15minute', etc.
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0)
    is_synthetic = Column(Boolean, default=False)  # True if created from LTP, False if from historical data
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_candle_segment_timestamp', 'segment', 'timestamp', 'interval'),
        Index('idx_candle_timestamp', 'timestamp'),
    )


class DatabaseManager:
    """Database connection and session management"""
    
    def __init__(self, db_path: str = "data/risk_management.db"):
        self.db_path = db_path
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._create_tables()
    
    def _create_tables(self):
        """Create all database tables"""
        Base.metadata.create_all(self.engine)
        # Run migrations to add new columns if they don't exist
        self._migrate_transaction_type()
        self._migrate_broker_id()
    
    def _migrate_transaction_type(self):
        """Migrate trades table to add transaction_type column if needed"""
        from sqlalchemy import text
        session = self.get_session()
        try:
            # Check if column already exists
            result = session.execute(text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('trades') 
                WHERE name='transaction_type'
            """))
            
            column_exists = result.fetchone()[0] > 0
            
            if not column_exists:
                # Add transaction_type column
                session.execute(text("""
                    ALTER TABLE trades 
                    ADD COLUMN transaction_type VARCHAR(10) DEFAULT 'BUY'
                """))
                
                # Update existing records based on quantity sign
                session.execute(text("""
                    UPDATE trades 
                    SET transaction_type = CASE 
                        WHEN quantity > 0 THEN 'BUY' 
                        ELSE 'SELL' 
                    END
                """))
                
                session.commit()
                logger = get_logger("database")
                logger.info("Migration: Added transaction_type column to trades table")
        except Exception as e:
            session.rollback()
            logger.error(f"Migration error: {e}")
        finally:
            session.close()
    
    def _migrate_broker_id(self):
        """Migrate tables to add broker_id column if needed"""
        from sqlalchemy import text
        logger = get_logger("database")
        session = self.get_session()
        try:
            tables_to_migrate = ['positions', 'trades', 'daily_stats', 'daily_purge_flags']
            
            for table_name in tables_to_migrate:
                # Check if column already exists
                result = session.execute(text(f"""
                    SELECT COUNT(*) as count 
                    FROM pragma_table_info('{table_name}') 
                    WHERE name='broker_id'
                """))
                
                column_exists = result.fetchone()[0] > 0
                
                if not column_exists:
                    # Add broker_id column with default value 'DEFAULT' for existing records
                    session.execute(text(f"""
                        ALTER TABLE {table_name} 
                        ADD COLUMN broker_id VARCHAR(50) DEFAULT 'DEFAULT'
                    """))
                    
                    # Create index
                    try:
                        if table_name == 'daily_stats':
                            # For daily_stats, create unique index on broker_id + date
                            session.execute(text(f"""
                                CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_date 
                                ON {table_name}(broker_id, date)
                            """))
                        elif table_name == 'daily_purge_flags':
                            session.execute(text(f"""
                                CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_purge_date 
                                ON {table_name}(broker_id, purge_date)
                            """))
                        else:
                            session.execute(text(f"""
                                CREATE INDEX IF NOT EXISTS idx_{table_name}_broker_id 
                                ON {table_name}(broker_id)
                            """))
                    except Exception as idx_error:
                        logger.warning(f"Index creation warning for {table_name}: {idx_error}")
                    
                    session.commit()
                    logger.info(f"Migration: Added broker_id column to {table_name} table")
        except Exception as e:
            session.rollback()
            logger.error(f"Migration error: {e}")
        finally:
            session.close()
    
    def get_session(self):
        """Get database session"""
        return self.SessionLocal()
    
    def close(self):
        """Close database connection"""
        self.engine.dispose()

