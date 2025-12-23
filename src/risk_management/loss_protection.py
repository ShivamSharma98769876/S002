"""
Daily Loss Protection System
Monitors daily loss and automatically exits all positions when limit is reached
"""

from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime, time as dt_time
from src.utils.logger import get_logger
from src.utils.exceptions import LossLimitExceededError, TradingBlockedError
from src.config.config_manager import ConfigManager
from src.api.kite_client import KiteClient
from src.database.repository import (
    PositionRepository, DailyStatsRepository, TradeRepository
)
from src.database.models import Position

if TYPE_CHECKING:
    from src.utils.notifications import NotificationService

logger = get_logger("risk")


class DailyLossProtection:
    """Daily loss protection system"""
    
    def __init__(
        self,
        config_manager: ConfigManager,
        kite_client: KiteClient,
        position_repo: PositionRepository,
        daily_stats_repo: DailyStatsRepository,
        trade_repo: TradeRepository
    ):
        self.config_manager = config_manager
        self.kite_client = kite_client
        self.position_repo = position_repo
        self.daily_stats_repo = daily_stats_repo
        self.trade_repo = trade_repo
        
        admin_config = config_manager.get_admin_config()
        self.daily_loss_limit = admin_config.daily_loss_limit
        self.loss_warning_threshold = admin_config.loss_warning_threshold
        self.warning_sent = False
        self.loss_limit_hit = False
        self.trading_blocked = False
        self.notification_service: Optional['NotificationService'] = None
    
    def calculate_daily_loss(self, protected_profit: float = 0.0) -> float:
        """
        Calculate cumulative daily loss from all live positions only
        Protected profit is NOT included in loss calculation
        
        Args:
            protected_profit: Protected profit from completed trades (for reference only)
        
        Returns:
            Total daily loss from live positions only (positive value) or 0 if profit
        """
        try:
            active_positions = self.position_repo.get_active_positions()
            total_unrealized_pnl = sum(pos.unrealized_pnl for pos in active_positions)
            
            # Daily loss = negative of unrealized P&L (only from live positions)
            # Protected profit is NOT subtracted - loss limit applies only to live trades
            # If unrealized P&L is negative (loss), daily_loss will be positive
            daily_loss = -total_unrealized_pnl if total_unrealized_pnl < 0 else 0.0
            
            # Only return loss if it's positive (negative P&L)
            return max(0.0, daily_loss)
        except Exception as e:
            logger.error(f"Error calculating daily loss: {e}")
            return 0.0
    
    def check_loss_limit(self, protected_profit: float = 0.0) -> Dict[str, Any]:
        """
        Check if daily loss limit is reached
        
        Returns:
            Dict with status information
        """
        daily_loss = self.calculate_daily_loss(protected_profit)
        warning_threshold = self.daily_loss_limit * self.loss_warning_threshold
        
        status = {
            "daily_loss": daily_loss,
            "daily_loss_limit": self.daily_loss_limit,
            "warning_threshold": warning_threshold,
            "loss_limit_hit": False,
            "warning_triggered": False,
            "trading_blocked": self.trading_blocked
        }
        
        # Check if loss limit is hit
        if daily_loss >= self.daily_loss_limit:
            status["loss_limit_hit"] = True
            if not self.loss_limit_hit:
                logger.critical(f"Daily loss limit reached: ₹{daily_loss:.2f} / ₹{self.daily_loss_limit:.2f}")
                self.loss_limit_hit = True
                self._handle_loss_limit_breach()
        # Check warning threshold
        elif daily_loss >= warning_threshold and not self.warning_sent:
            status["warning_triggered"] = True
            self.warning_sent = True
            logger.warning(
                f"Daily loss approaching limit: ₹{daily_loss:.2f} / ₹{self.daily_loss_limit:.2f} "
                f"({self.loss_warning_threshold * 100}%)"
            )
            if self.notification_service:
                self.notification_service.notify_loss_warning(daily_loss, self.daily_loss_limit)
        
        return status
    
    def _handle_loss_limit_breach(self):
        """Handle loss limit breach - exit all positions and block trading"""
        try:
            logger.critical("Loss limit breached! Exiting all positions...")
            
            # Check market closure scenario
            from src.risk_management.edge_cases import EdgeCaseHandler
            from src.database.repository import TradeRepository
            edge_handler = EdgeCaseHandler(
                self.kite_client,
                self.position_repo,
                self.trade_repo
            )
            
            # Handle market closure if applicable
            edge_handler.handle_market_closure_scenario()
            
            # Exit all positions
            active_positions = self.position_repo.get_active_positions()
            if active_positions:
                # Use edge case handler for multiple positions
                order_ids = edge_handler.handle_multiple_positions_exit(active_positions)
            else:
                order_ids = self.kite_client.square_off_all_positions()
            
            logger.info(f"Exited {len(order_ids)} positions. Order IDs: {order_ids}")
            
            # Block trading
            self.trading_blocked = True
            self._block_trading_until_next_day()
            
            # Update daily stats
            protected_profit = self._get_protected_profit()
            self.daily_stats_repo.update_daily_stats(
                total_unrealized_pnl=0.0,  # All positions closed
                protected_profit=protected_profit,
                daily_loss_used=self.daily_loss_limit,
                loss_limit_hit=True,
                trading_blocked=True
            )
            
            # Send notification
            from src.utils.date_utils import get_next_trading_day
            next_day = get_next_trading_day().strftime('%Y-%m-%d')
            if self.notification_service:
                self.notification_service.notify_loss_limit_reached(next_day)
            logger.critical("Trading blocked until next trading day (9:30 AM)")
            
        except Exception as e:
            logger.error(f"Error handling loss limit breach: {e}")
            raise LossLimitExceededError(f"Failed to handle loss limit breach: {str(e)}")
    
    def _block_trading_until_next_day(self):
        """Block trading until next trading day at 9:30 AM"""
        self.trading_blocked = True
        # The block will be reset by the trading block manager at 9:30 AM
        logger.info("Trading blocked until next trading day")
    
    def is_trading_blocked(self) -> bool:
        """Check if trading is currently blocked"""
        return self.trading_blocked
    
    def reset_daily_limits(self):
        """Reset daily limits at start of new trading day"""
        self.warning_sent = False
        self.loss_limit_hit = False
        self.trading_blocked = False
        logger.info("Daily loss limits reset for new trading day")
    
    def _get_protected_profit(self) -> float:
        """Get protected profit from completed trades today"""
        today = datetime.now().date()
        return self.trade_repo.get_protected_profit(today)
    
    def get_protected_profit(self) -> float:
        """Get protected profit from completed trades today (public method)"""
        return self._get_protected_profit()
    
    def can_place_order(self) -> bool:
        """Check if new orders can be placed"""
        if self.trading_blocked:
            raise TradingBlockedError(
                "Trading is blocked. Daily loss limit reached. "
                "Trading will resume at 9:30 AM next trading day."
            )
        return True
    
    def set_notification_service(self, notification_service):
        """Set notification service"""
        self.notification_service = notification_service

