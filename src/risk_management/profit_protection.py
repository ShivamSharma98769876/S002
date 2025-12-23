"""
Cycle-wise Profit Protection System
Locks profit from completed trades separately from current trade P&L
"""

from typing import Optional, Dict, Any, List, TYPE_CHECKING
from datetime import datetime, date
from pytz import UTC
from src.utils.logger import get_logger
from src.database.repository import (
    PositionRepository, TradeRepository, DailyStatsRepository
)
from src.database.models import Position, Trade
from src.api.kite_client import KiteClient

if TYPE_CHECKING:
    from src.utils.notifications import NotificationService

logger = get_logger("risk")


class ProfitProtection:
    """Cycle-wise profit protection system"""
    
    def __init__(
        self,
        position_repo: PositionRepository,
        trade_repo: TradeRepository,
        daily_stats_repo: DailyStatsRepository,
        kite_client: KiteClient
    ):
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.daily_stats_repo = daily_stats_repo
        self.kite_client = kite_client
        
        # Track previous positions to detect closures
        self.previous_positions: Dict[str, Position] = {}
        self._load_previous_positions()
        self.notification_service: Optional['NotificationService'] = None
    
    def _load_previous_positions(self):
        """Load current active positions to track changes"""
        try:
            active_positions = self.position_repo.get_active_positions()
            for pos in active_positions:
                self.previous_positions[f"{pos.exchange}:{pos.trading_symbol}"] = pos
        except Exception as e:
            logger.error(f"Error loading previous positions: {e}")
    
    def get_protected_profit(self, trade_date: Optional[date] = None) -> float:
        """
        Get protected profit from completed trades (sum of ALL completed trades - profit + loss)
        
        Note: Protected Profit includes ALL completed trades (both profit and loss).
        This represents the cumulative P&L from all closed trades.
        Daily loss limit applies only to LIVE positions, not to this protected profit.
        
        Args:
            trade_date: Date to get protected profit for (default: today)
        
        Returns:
            Total P&L from all completed trades (can be positive or negative)
        """
        if trade_date is None:
            trade_date = datetime.now().date()
        
        try:
            return self.trade_repo.get_protected_profit(trade_date)
        except Exception as e:
            logger.error(f"Error getting protected profit: {e}")
            return 0.0
    
    def get_current_positions_pnl(self) -> float:
        """
        Get current unrealized P&L from all active positions
        
        Returns:
            Total unrealized P&L from active positions
        """
        try:
            active_positions = self.position_repo.get_active_positions()
            return sum(pos.unrealized_pnl for pos in active_positions)
        except Exception as e:
            logger.error(f"Error getting current positions P&L: {e}")
            return 0.0
    
    def get_total_daily_pnl(self) -> Dict[str, float]:
        """
        Get total daily P&L breakdown
        
        Returns:
            Dict with protected_profit, current_pnl, and total_pnl
        """
        protected_profit = self.get_protected_profit()
        current_pnl = self.get_current_positions_pnl()
        total_pnl = protected_profit + current_pnl
        
        return {
            "protected_profit": protected_profit,
            "current_pnl": current_pnl,
            "total_pnl": total_pnl
        }
    
    def detect_and_process_trade_completions(self) -> List[Dict[str, Any]]:
        """
        Detect position closures and process profit protection
        
        Returns:
            List of completed trades with their realized P&L
        """
        completed_trades = []
        
        try:
            # Check if authenticated before making API calls
            if not self.kite_client.is_authenticated():
                # Not authenticated yet - skip trade completion detection
                return completed_trades
            
            # Get current positions from Zerodha
            current_positions_data = self.kite_client.get_positions()
            
            # Create a map of current positions
            current_positions_map = {}
            for pos_data in current_positions_data:
                key = f"{pos_data.get('exchange')}:{pos_data.get('tradingsymbol')}"
                current_positions_map[key] = pos_data
            
            # Check for closed positions
            for key, prev_position in self.previous_positions.items():
                if key not in current_positions_map:
                    # Position was closed
                    completed_trade = self._process_position_closure(prev_position)
                    if completed_trade:
                        completed_trades.append(completed_trade)
                else:
                    # Position still exists, check if quantity changed
                    current_qty = abs(current_positions_map[key].get('quantity', 0))
                    if current_qty == 0 and prev_position.quantity > 0:
                        # Position fully closed
                        completed_trade = self._process_position_closure(prev_position)
                        if completed_trade:
                            completed_trades.append(completed_trade)
            
            # Update previous positions
            self._update_previous_positions()
            
        except Exception as e:
            logger.error(f"Error detecting trade completions: {e}")
        
        return completed_trades
    
    def _process_position_closure(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Process a closed position and lock profit if profitable
        
        Args:
            position: The closed position
        
        Returns:
            Dict with trade completion details or None
        """
        try:
            # Get the exit price from API if available, otherwise use current_price
            exit_price = position.current_price or position.entry_price
            
            # Try to get latest price from API
            if self.kite_client and self.kite_client.is_authenticated():
                try:
                    # Get latest quote for the instrument
                    instrument_token = int(position.instrument_token)
                    quote = self.kite_client.kite.quote([f"{position.exchange}:{position.trading_symbol}"])
                    if quote and f"{position.exchange}:{position.trading_symbol}" in quote:
                        last_price = quote[f"{position.exchange}:{position.trading_symbol}"].get('last_price')
                        if last_price:
                            exit_price = last_price
                except Exception as e:
                    logger.debug(f"Could not fetch exit price from API: {e}")
            
            # Convert to IST time
            from src.utils.date_utils import get_current_ist_time
            exit_time = get_current_ist_time()
            
            # Determine transaction type from quantity sign
            transaction_type = 'BUY' if position.quantity > 0 else 'SELL'
            
            # Calculate realized P&L correctly based on transaction type
            from src.utils.position_utils import calculate_position_pnl
            realized_pnl = calculate_position_pnl(
                position.entry_price,
                exit_price,
                position.quantity,
                position.lot_size
            )
            
            # Determine exit type (manual or auto)
            exit_type = "manual"  # Default, can be updated based on context
            
            # Convert entry_time to IST if it's not already
            from src.utils.date_utils import IST
            if position.entry_time.tzinfo is None:
                # Assume UTC if no timezone
                entry_time_ist = position.entry_time.replace(tzinfo=UTC).astimezone(IST)
            else:
                entry_time_ist = position.entry_time.astimezone(IST)
            
            # Create trade record
            trade = self.trade_repo.create_trade(
                instrument_token=position.instrument_token,
                trading_symbol=position.trading_symbol,
                exchange=position.exchange,
                entry_time=entry_time_ist,
                exit_time=exit_time,
                entry_price=position.entry_price,
                exit_price=exit_price,
                quantity=position.quantity,  # Can be negative for SELL
                exit_type=exit_type,
                position_id=position.id,
                transaction_type=transaction_type
            )
            
            # Deactivate position in database
            self.position_repo.deactivate_position(position.id)
            
            # Update protected profit for ALL completed trades (profit + loss)
            # Protected profit = sum of ALL completed trades
            self._lock_profit(realized_pnl, trade)
            
            if realized_pnl > 0:
                logger.info(
                    f"Trade closed with profit: ₹{realized_pnl:.2f} | "
                    f"Symbol: {position.trading_symbol} | Protected P&L updated"
                )
                if self.notification_service:
                    self.notification_service.notify_trade_completed(
                        realized_pnl, position.trading_symbol
                    )
            else:
                logger.info(
                    f"Trade closed with loss: ₹{realized_pnl:.2f} | "
                    f"Symbol: {position.trading_symbol} | Protected P&L updated"
                )
            
            # Update daily stats
            self._update_daily_stats()
            
            return {
                "trade_id": trade.id,
                "symbol": position.trading_symbol,
                "realized_pnl": realized_pnl,
                "is_profit": realized_pnl > 0,
                "protected": realized_pnl > 0
            }
            
        except Exception as e:
            logger.error(f"Error processing position closure: {e}")
            return None
    
    def _lock_profit(self, profit: float, trade: Trade):
        """
        Update protected profit counter after trade completion
        
        Note: Protected profit includes ALL completed trades (profit + loss).
        This method updates the daily stats after a trade is completed.
        
        Args:
            profit: Realized P&L from the completed trade (can be positive or negative)
            trade: The completed trade
        """
        try:
            # Protected profit is calculated in get_protected_profit()
            # which sums ALL completed trades (both profit and loss).
            # We just need to ensure the trade is recorded correctly,
            # which is already done in create_trade()
            
            # Update daily stats to reflect new protected profit
            today = datetime.now().date()
            protected_profit = self.get_protected_profit(today)
            
            self.daily_stats_repo.update_daily_stats(
                protected_profit=protected_profit
            )
            
            if profit > 0:
                logger.info(f"Trade completed with profit: ₹{profit:.2f} | Total protected P&L: ₹{protected_profit:.2f}")
            else:
                logger.info(f"Trade completed with loss: ₹{profit:.2f} | Total protected P&L: ₹{protected_profit:.2f}")
            
        except Exception as e:
            logger.error(f"Error updating protected profit: {e}")
            raise
    
    def _update_previous_positions(self):
        """Update the previous positions cache"""
        try:
            active_positions = self.position_repo.get_active_positions()
            self.previous_positions = {}
            for pos in active_positions:
                key = f"{pos.exchange}:{pos.trading_symbol}"
                self.previous_positions[key] = pos
        except Exception as e:
            logger.error(f"Error updating previous positions: {e}")
    
    def _update_daily_stats(self):
        """Update daily statistics with current P&L breakdown"""
        try:
            pnl_breakdown = self.get_total_daily_pnl()
            
            self.daily_stats_repo.update_daily_stats(
                protected_profit=pnl_breakdown["protected_profit"],
                total_unrealized_pnl=pnl_breakdown["current_pnl"]
            )
        except Exception as e:
            logger.error(f"Error updating daily stats: {e}")
    
    def reset_daily_protection(self):
        """Reset profit protection for new trading day"""
        self.previous_positions = {}
        self._load_previous_positions()
        logger.info("Profit protection reset for new trading day")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current profit protection status"""
        pnl_breakdown = self.get_total_daily_pnl()
        
        return {
            "protected_profit": pnl_breakdown["protected_profit"],
            "current_positions_pnl": pnl_breakdown["current_pnl"],
            "total_daily_pnl": pnl_breakdown["total_pnl"],
            "active_positions_count": len(self.previous_positions)
        }
    
    def set_notification_service(self, notification_service):
        """Set notification service"""
        self.notification_service = notification_service

