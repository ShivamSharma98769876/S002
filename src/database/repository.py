"""
Data Repository for CRUD operations
"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from src.database.models import (
    Position, Trade, DailyStats, AuditLog, DatabaseManager, DailyPurgeFlag, Candle
)
from src.utils.logger import get_logger

logger = get_logger("app")


class PositionRepository:
    """Repository for position operations"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def create_or_update_position(
        self,
        instrument_token: str,
        trading_symbol: str,
        exchange: str,
        entry_price: float,
        quantity: int,
        lot_size: int = 1,
        current_price: Optional[float] = None
    ) -> Position:
        """Create new position or update existing"""
        session = self.db_manager.get_session()
        try:
            # Check if active position exists
            position = session.query(Position).filter(
                and_(
                    Position.instrument_token == instrument_token,
                    Position.is_active == True
                )
            ).first()
            
            if position:
                # Update existing position
                position.quantity = quantity
                position.current_price = current_price or position.current_price
                position.updated_at = datetime.utcnow()
                if current_price:
                    # Use correct P&L calculation based on transaction type
                    from src.utils.position_utils import calculate_position_pnl
                    position.unrealized_pnl = calculate_position_pnl(
                        position.entry_price,
                        current_price,
                        quantity,
                        lot_size
                    )
            else:
                # Create new position
                position = Position(
                    instrument_token=instrument_token,
                    trading_symbol=trading_symbol,
                    exchange=exchange,
                    entry_price=entry_price,
                    current_price=current_price or entry_price,
                    quantity=quantity,
                    lot_size=lot_size,
                    unrealized_pnl=0.0
                )
                session.add(position)
            
            session.commit()
            session.refresh(position)
            return position
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating/updating position: {e}")
            raise
        finally:
            session.close()
    
    def get_active_positions(self) -> List[Position]:
        """Get all active positions"""
        session = self.db_manager.get_session()
        try:
            return session.query(Position).filter(Position.is_active == True).all()
        finally:
            session.close()
    
    def get_inactive_positions(self) -> List[Position]:
        """Get all inactive positions (quantity=0 or is_active=False)"""
        session = self.db_manager.get_session()
        try:
            return session.query(Position).filter(
                and_(
                    Position.quantity == 0,
                    Position.is_active == True
                )
            ).order_by(Position.updated_at.desc()).all()
        finally:
            session.close()
    
    def get_all_inactive_positions(self) -> List[Position]:
        """Get all inactive positions (is_active=False or quantity=0)"""
        session = self.db_manager.get_session()
        try:
            from sqlalchemy import or_
            positions = session.query(Position).filter(
                or_(
                    Position.is_active == False,
                    Position.quantity == 0
                )
            ).order_by(Position.updated_at.desc()).all()
            logger.debug(f"Found {len(positions)} inactive positions")
            return positions
        finally:
            session.close()
    
    def get_position_by_id(self, position_id: int) -> Optional[Position]:
        """Get position by ID"""
        session = self.db_manager.get_session()
        try:
            return session.query(Position).filter(Position.id == position_id).first()
        finally:
            session.close()
    
    def update_position_pnl(self, position_id: int, current_price: float) -> Position:
        """Update position P&L"""
        session = self.db_manager.get_session()
        try:
            position = session.query(Position).filter(Position.id == position_id).first()
            if position:
                position.current_price = current_price
                # Calculate P&L correctly based on transaction type (quantity sign)
                from src.utils.position_utils import calculate_position_pnl
                position.unrealized_pnl = calculate_position_pnl(
                    position.entry_price,
                    current_price,
                    position.quantity,
                    position.lot_size
                )
                position.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(position)
            return position
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating position P&L: {e}")
            raise
        finally:
            session.close()
    
    def deactivate_position(self, position_id: int):
        """Mark position as inactive"""
        session = self.db_manager.get_session()
        try:
            position = session.query(Position).filter(Position.id == position_id).first()
            if position:
                position.is_active = False
                position.updated_at = datetime.utcnow()
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error deactivating position: {e}")
            raise
        finally:
            session.close()
    
    def clear_all_positions(self):
        """Clear all active positions from cache (deactivate them)"""
        session = self.db_manager.get_session()
        try:
            count = session.query(Position).filter(Position.is_active == True).update(
                {Position.is_active: False, Position.updated_at: datetime.utcnow()},
                synchronize_session=False
            )
            session.commit()
            logger.info(f"Cleared {count} positions from cache")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Error clearing positions: {e}")
            raise
        finally:
            session.close()


class TradeRepository:
    """Repository for trade operations"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def create_trade(
        self,
        instrument_token: str,
        trading_symbol: str,
        exchange: str,
        entry_time: datetime,
        exit_time: datetime,
        entry_price: float,
        exit_price: float,
        quantity: int,
        exit_type: str,
        position_id: Optional[int] = None,
        transaction_type: Optional[str] = None
    ) -> Trade:
        """Create a completed trade record"""
        session = self.db_manager.get_session()
        try:
            # Determine transaction type from quantity sign if not provided
            if transaction_type is None:
                transaction_type = 'BUY' if quantity > 0 else 'SELL'
            
            # Calculate realized P&L correctly based on transaction type
            # For BUY: P&L = (exit_price - entry_price) * quantity
            # For SELL: P&L = (entry_price - exit_price) * abs(quantity)
            if transaction_type == 'SELL':
                # For SELL trades, profit when entry > exit
                realized_pnl = (entry_price - exit_price) * abs(quantity)
            else:
                # For BUY trades, profit when exit > entry
                realized_pnl = (exit_price - entry_price) * quantity
            
            is_profit = realized_pnl > 0
            
            trade = Trade(
                position_id=position_id,
                instrument_token=instrument_token,
                trading_symbol=trading_symbol,
                exchange=exchange,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,  # Can be negative for SELL
                transaction_type=transaction_type,
                realized_pnl=realized_pnl,
                is_profit=is_profit,
                exit_type=exit_type
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating trade: {e}")
            raise
        finally:
            session.close()
    
    def get_trades_by_date(self, trade_date: date) -> List[Trade]:
        """Get all trades for a specific date (in IST timezone)"""
        from src.utils.date_utils import IST
        from pytz import UTC
        session = self.db_manager.get_session()
        try:
            # Create date range in IST timezone
            # Start of day in IST (00:00:00 IST)
            start_datetime_ist = IST.localize(
                datetime.combine(trade_date, datetime.min.time())
            )
            # End of day in IST (23:59:59.999999 IST)
            end_datetime_ist = IST.localize(
                datetime.combine(trade_date, datetime.max.time())
            )
            
            # Convert IST range to UTC for database comparison
            # (assuming exit_time is stored in UTC or naive UTC)
            start_datetime_utc = start_datetime_ist.astimezone(UTC).replace(tzinfo=None)
            end_datetime_utc = end_datetime_ist.astimezone(UTC).replace(tzinfo=None)
            
            # Query with UTC range (covers the full IST day)
            trades = session.query(Trade).filter(
                and_(
                    Trade.exit_time >= start_datetime_utc,
                    Trade.exit_time <= end_datetime_utc
                )
            ).order_by(Trade.exit_time.desc()).all()
            
            # Additional filter: verify the date in IST (handles edge cases)
            # This ensures trades before 10 AM IST are included
            filtered_trades = []
            for trade in trades:
                # Convert exit_time to IST for date comparison
                exit_time_ist = trade.exit_time
                if exit_time_ist.tzinfo is None:
                    # Assume UTC if naive
                    exit_time_ist = exit_time_ist.replace(tzinfo=UTC).astimezone(IST)
                else:
                    exit_time_ist = exit_time_ist.astimezone(IST)
                
                # Compare dates in IST
                exit_date_ist = exit_time_ist.date()
                if exit_date_ist == trade_date:
                    filtered_trades.append(trade)
            
            logger.debug(f"Found {len(filtered_trades)} trades for date {trade_date} (IST)")
            return filtered_trades
        finally:
            session.close()
    
    def get_all_trades(self, limit: Optional[int] = None) -> List[Trade]:
        """Get all trades (inactive/completed trades)"""
        session = self.db_manager.get_session()
        try:
            query = session.query(Trade).order_by(Trade.exit_time.desc())
            if limit:
                query = query.limit(limit)
            trades = query.all()
            logger.debug(f"Found {len(trades)} completed trades")
            return trades
        finally:
            session.close()
    
    def get_trades_by_position_id(self, position_id: int) -> List[Trade]:
        """Get trades for a specific position"""
        session = self.db_manager.get_session()
        try:
            return session.query(Trade).filter(
                Trade.position_id == position_id
            ).order_by(Trade.exit_time.desc()).all()
        finally:
            session.close()
    
    def get_trades_summary(self) -> Dict[str, Any]:
        """Get summary of all trades (total profit, loss, count)"""
        session = self.db_manager.get_session()
        try:
            all_trades = session.query(Trade).all()
            
            total_profit = sum(t.realized_pnl for t in all_trades if t.realized_pnl > 0)
            total_loss = sum(t.realized_pnl for t in all_trades if t.realized_pnl < 0)
            total_pnl = sum(t.realized_pnl for t in all_trades)
            total_trades = len(all_trades)
            profitable_trades = sum(1 for t in all_trades if t.realized_pnl > 0)
            loss_trades = sum(1 for t in all_trades if t.realized_pnl < 0)
            
            return {
                "total_profit": total_profit,
                "total_loss": total_loss,
                "total_pnl": total_pnl,
                "total_trades": total_trades,
                "profitable_trades": profitable_trades,
                "loss_trades": loss_trades
            }
        finally:
            session.close()
    
    def get_protected_profit(self, trade_date: date) -> float:
        """
        Calculate protected profit for a date (sum of ALL completed trades - profit + loss)
        
        Note: Protected Profit = Sum of all completed trades (both profit and loss).
        This represents the cumulative P&L from all closed trades.
        Daily loss limit applies only to LIVE positions, not to this protected profit.
        """
        session = self.db_manager.get_session()
        try:
            start_datetime = datetime.combine(trade_date, datetime.min.time())
            end_datetime = datetime.combine(trade_date, datetime.max.time())
            # Sum ALL trades (both profit and loss) - not just profitable ones
            result = session.query(func.sum(Trade.realized_pnl)).filter(
                and_(
                    Trade.exit_time >= start_datetime,
                    Trade.exit_time <= end_datetime
                )
            ).scalar()
            return result or 0.0
        finally:
            session.close()
    
    def delete_trades_by_date(self, trade_date: date) -> int:
        """
        Delete all trades for a specific date (clears protected profit for that date)
        
        WARNING: This is a destructive operation that permanently deletes trade records.
        Use with caution. Consider backing up data before deletion.
        
        Args:
            trade_date: Date for which to delete trades
        
        Returns:
            Number of trades deleted
        """
        session = self.db_manager.get_session()
        try:
            from src.utils.date_utils import IST
            from pytz import UTC
            
            # Create date range in IST timezone
            start_datetime_ist = IST.localize(
                datetime.combine(trade_date, datetime.min.time())
            )
            end_datetime_ist = IST.localize(
                datetime.combine(trade_date, datetime.max.time())
            )
            
            # Convert IST range to UTC for database comparison
            start_datetime_utc = start_datetime_ist.astimezone(UTC).replace(tzinfo=None)
            end_datetime_utc = end_datetime_ist.astimezone(UTC).replace(tzinfo=None)
            
            # Count trades before deletion
            count = session.query(Trade).filter(
                and_(
                    Trade.exit_time >= start_datetime_utc,
                    Trade.exit_time <= end_datetime_utc
                )
            ).count()
            
            # Delete trades
            deleted = session.query(Trade).filter(
                and_(
                    Trade.exit_time >= start_datetime_utc,
                    Trade.exit_time <= end_datetime_utc
                )
            ).delete(synchronize_session=False)
            
            session.commit()
            logger.warning(f"Deleted {deleted} trades for date {trade_date} (Protected Profit cleared)")
            return deleted
        except Exception as e:
            session.rollback()
            logger.error(f"Error deleting trades for date {trade_date}: {e}")
            raise
        finally:
            session.close()
    
    def is_purge_done_for_today(self) -> bool:
        """Check if Day-1 trades have been purged today"""
        session = self.db_manager.get_session()
        try:
            from src.utils.date_utils import get_current_ist_time
            today_ist = get_current_ist_time().date()
            
            # Check if purge flag exists for today
            purge_flag = session.query(DailyPurgeFlag).filter(
                func.date(DailyPurgeFlag.purge_date) == today_ist
            ).first()
            
            return purge_flag is not None
        finally:
            session.close()
    
    def purge_day_minus_one_trades(self) -> int:
        """
        Purge all Day-1 (previous day) trades from the system.
        This should be called once per day on system startup.
        
        Returns:
            Number of trades deleted
        """
        session = self.db_manager.get_session()
        try:
            from src.utils.date_utils import get_current_ist_time, IST
            from pytz import UTC
            
            today_ist = get_current_ist_time().date()
            
            # Check if purge already done for today
            if self.is_purge_done_for_today():
                logger.info(f"Day-1 trades already purged for {today_ist}")
                return 0
            
            # Get all trades
            all_trades = session.query(Trade).all()
            
            # Filter trades from Day-1 (previous day)
            from datetime import timedelta
            day_minus_one = today_ist - timedelta(days=1)
            
            trades_to_delete = []
            for trade in all_trades:
                # Convert exit_time to IST for date comparison
                exit_time_ist = trade.exit_time
                if exit_time_ist.tzinfo is None:
                    exit_time_ist = exit_time_ist.replace(tzinfo=UTC).astimezone(IST)
                else:
                    exit_time_ist = exit_time_ist.astimezone(IST)
                
                exit_date_ist = exit_time_ist.date()
                
                # Delete trades from Day-1 (previous day)
                if exit_date_ist == day_minus_one:
                    trades_to_delete.append(trade)
            
            # Delete the trades
            deleted_count = 0
            for trade in trades_to_delete:
                session.delete(trade)
                deleted_count += 1
            
            if deleted_count > 0:
                session.commit()
                logger.info(f"Purged {deleted_count} Day-1 trades (from {day_minus_one})")
            else:
                logger.info(f"No Day-1 trades found to purge (from {day_minus_one})")
            
            # Record purge flag for today
            purge_flag = DailyPurgeFlag(
                purge_date=datetime.combine(today_ist, datetime.min.time()),
                purge_timestamp=datetime.utcnow(),
                trades_deleted=deleted_count
            )
            session.add(purge_flag)
            session.commit()
            
            logger.info(f"Daily purge flag set for {today_ist}")
            return deleted_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error purging Day-1 trades: {e}", exc_info=True)
            raise
        finally:
            session.close()


class DailyStatsRepository:
    """Repository for daily statistics"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def get_or_create_today_stats(self) -> DailyStats:
        """Get today's stats or create if not exists"""
        session = self.db_manager.get_session()
        try:
            today = datetime.now().date()
            stats = session.query(DailyStats).filter(
                func.date(DailyStats.date) == today
            ).first()
            
            if not stats:
                stats = DailyStats(date=datetime.now())
                session.add(stats)
                session.commit()
                session.refresh(stats)
            
            return stats
        except Exception as e:
            session.rollback()
            logger.error(f"Error getting/creating daily stats: {e}")
            raise
        finally:
            session.close()
    
    def update_daily_stats(
        self,
        total_unrealized_pnl: Optional[float] = None,
        protected_profit: Optional[float] = None,
        daily_loss_used: Optional[float] = None,
        loss_limit_hit: Optional[bool] = None,
        trading_blocked: Optional[bool] = None,
        trailing_sl_active: Optional[bool] = None,
        trailing_sl_level: Optional[float] = None
    ):
        """Update daily statistics"""
        session = self.db_manager.get_session()
        try:
            stats = self.get_or_create_today_stats()
            if total_unrealized_pnl is not None:
                stats.total_unrealized_pnl = total_unrealized_pnl
            if protected_profit is not None:
                stats.protected_profit = protected_profit
            if daily_loss_used is not None:
                stats.daily_loss_used = daily_loss_used
            if loss_limit_hit is not None:
                stats.loss_limit_hit = loss_limit_hit
            if trading_blocked is not None:
                stats.trading_blocked = trading_blocked
            if trailing_sl_active is not None:
                stats.trailing_sl_active = trailing_sl_active
            if trailing_sl_level is not None:
                stats.trailing_sl_level = trailing_sl_level
            stats.updated_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating daily stats: {e}")
            raise
        finally:
            session.close()


class CandleRepository:
    """Repository for candle/OHLCV data operations"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def get_candle(
        self,
        segment: str,
        timestamp: datetime,
        interval: str
    ) -> Optional[Candle]:
        """Get a specific candle by segment, timestamp, and interval"""
        session = self.db_manager.get_session()
        try:
            candle = session.query(Candle).filter(
                and_(
                    Candle.segment == segment.upper(),
                    Candle.timestamp == timestamp,
                    Candle.interval == interval
                )
            ).first()
            return candle
        except Exception as e:
            logger.error(f"Error getting candle: {e}")
            return None
        finally:
            session.close()
    
    def get_candles(
        self,
        segment: str,
        start_time: datetime,
        end_time: datetime,
        interval: str
    ) -> List[Candle]:
        """Get candles for a time range"""
        session = self.db_manager.get_session()
        try:
            candles = session.query(Candle).filter(
                and_(
                    Candle.segment == segment.upper(),
                    Candle.timestamp >= start_time,
                    Candle.timestamp <= end_time,
                    Candle.interval == interval
                )
            ).order_by(Candle.timestamp).all()
            return candles
        except Exception as e:
            logger.error(f"Error getting candles: {e}")
            return []
        finally:
            session.close()
    
    def save_candle(
        self,
        segment: str,
        timestamp: datetime,
        interval: str,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        is_synthetic: bool = False
    ) -> Candle:
        """Save or update a candle"""
        session = self.db_manager.get_session()
        try:
            # Check if candle already exists
            existing = session.query(Candle).filter(
                and_(
                    Candle.segment == segment.upper(),
                    Candle.timestamp == timestamp,
                    Candle.interval == interval
                )
            ).first()
            
            if existing:
                # Update existing candle (prefer non-synthetic data)
                if not existing.is_synthetic or not is_synthetic:
                    existing.open = open
                    existing.high = high
                    existing.low = low
                    existing.close = close
                    existing.volume = volume
                    existing.is_synthetic = is_synthetic
                    existing.updated_at = datetime.utcnow()
                candle = existing
            else:
                # Create new candle
                candle = Candle(
                    segment=segment.upper(),
                    timestamp=timestamp,
                    interval=interval,
                    open=open,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    is_synthetic=is_synthetic
                )
                session.add(candle)
            
            session.commit()
            return candle
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving candle: {e}")
            raise
        finally:
            session.close()
    
    def save_candles_batch(
        self,
        candles_data: List[Dict[str, Any]]
    ) -> int:
        """Save multiple candles in a batch"""
        session = self.db_manager.get_session()
        saved_count = 0
        try:
            for candle_data in candles_data:
                # Check if candle already exists
                existing = session.query(Candle).filter(
                    and_(
                        Candle.segment == candle_data['segment'].upper(),
                        Candle.timestamp == candle_data['timestamp'],
                        Candle.interval == candle_data['interval']
                    )
                ).first()
                
                if existing:
                    # Update if new data is non-synthetic
                    if not existing.is_synthetic or not candle_data.get('is_synthetic', False):
                        existing.open = candle_data['open']
                        existing.high = candle_data['high']
                        existing.low = candle_data['low']
                        existing.close = candle_data['close']
                        existing.volume = candle_data.get('volume', 0.0)
                        existing.is_synthetic = candle_data.get('is_synthetic', False)
                        existing.updated_at = datetime.utcnow()
                    saved_count += 1
                else:
                    candle = Candle(
                        segment=candle_data['segment'].upper(),
                        timestamp=candle_data['timestamp'],
                        interval=candle_data['interval'],
                        open=candle_data['open'],
                        high=candle_data['high'],
                        low=candle_data['low'],
                        close=candle_data['close'],
                        volume=candle_data.get('volume', 0.0),
                        is_synthetic=candle_data.get('is_synthetic', False)
                    )
                    session.add(candle)
                    saved_count += 1
            
            session.commit()
            return saved_count
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving candles batch: {e}")
            raise
        finally:
            session.close()
    
    def get_latest_candles(
        self,
        segment: str,
        interval: str,
        limit: int = 100
    ) -> List[Candle]:
        """Get latest N candles for a segment"""
        session = self.db_manager.get_session()
        try:
            candles = session.query(Candle).filter(
                and_(
                    Candle.segment == segment.upper(),
                    Candle.interval == interval
                )
            ).order_by(Candle.timestamp.desc()).limit(limit).all()
            return list(reversed(candles))  # Return in chronological order
        except Exception as e:
            logger.error(f"Error getting latest candles: {e}")
            return []
        finally:
            session.close()

