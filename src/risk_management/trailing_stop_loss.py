"""
Trailing Stop Loss System
Activates when profit reaches ₹5,000 and trails every ₹10,000 increment
"""

from typing import Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime
from src.utils.logger import get_logger
from src.utils.exceptions import TrailingSLTriggeredError
from src.config.config_manager import ConfigManager
from src.api.kite_client import KiteClient
from src.database.repository import (
    PositionRepository, DailyStatsRepository, TradeRepository
)

if TYPE_CHECKING:
    from src.utils.notifications import NotificationService

logger = get_logger("risk")


class TrailingStopLoss:
    """Trailing stop loss management system"""
    
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
        self.activation_threshold = admin_config.trailing_sl_activation
        self.increment_amount = admin_config.trailing_sl_increment
        
        self.trailing_sl_active = False
        self.trailing_sl_level: Optional[float] = None
        self.highest_profit: float = 0.0
        self.activation_notification_sent = False
        self.notification_service: Optional['NotificationService'] = None
    
    def calculate_total_daily_profit(self) -> float:
        """
        Calculate total daily profit including protected profit and current positions P&L
        
        Returns:
            Total daily profit (positive value) or 0 if loss
        """
        try:
            # Get protected profit from completed trades
            today = datetime.now().date()
            protected_profit = self.trade_repo.get_protected_profit(today)
            
            # Get unrealized P&L from active positions
            active_positions = self.position_repo.get_active_positions()
            unrealized_pnl = sum(pos.unrealized_pnl for pos in active_positions)
            
            # Total profit = protected profit + unrealized P&L
            total_profit = protected_profit + unrealized_pnl
            
            # Only return positive profit
            return max(0.0, total_profit)
        except Exception as e:
            logger.error(f"Error calculating total daily profit: {e}")
            return 0.0
    
    def get_protected_profit(self) -> float:
        """Get protected profit for today"""
        today = datetime.now().date()
        return self.trade_repo.get_protected_profit(today)
    
    def check_and_update_trailing_sl(self) -> Dict[str, Any]:
        """
        Check profit and update trailing SL accordingly
        
        Returns:
            Dict with trailing SL status information
        """
        total_profit = self.calculate_total_daily_profit()
        
        status = {
            "total_profit": total_profit,
            "trailing_sl_active": self.trailing_sl_active,
            "trailing_sl_level": self.trailing_sl_level,
            "activation_threshold": self.activation_threshold,
            "increment_amount": self.increment_amount,
            "triggered": False
        }
        
        # Update highest profit seen
        if total_profit > self.highest_profit:
            self.highest_profit = total_profit
        
        # Check if activation threshold is reached
        if not self.trailing_sl_active and total_profit >= self.activation_threshold:
            self._activate_trailing_sl(total_profit)
            status["trailing_sl_active"] = True
            status["trailing_sl_level"] = self.trailing_sl_level
        
        # If trailing SL is active, update it based on profit increments
        if self.trailing_sl_active:
            self._update_trailing_sl_level(total_profit)
            status["trailing_sl_level"] = self.trailing_sl_level
            
            # Check if trailing SL is triggered
            if total_profit <= self.trailing_sl_level:
                status["triggered"] = True
                self._handle_trailing_sl_trigger()
        
        return status
    
    def _activate_trailing_sl(self, current_profit: float):
        """Activate trailing SL when profit reaches activation threshold"""
        try:
            self.trailing_sl_active = True
            # Set initial trailing SL at activation threshold
            self.trailing_sl_level = self.activation_threshold
            self.highest_profit = current_profit
            
            logger.info(
                f"Trailing SL activated! Profit: ₹{current_profit:.2f}, "
                f"Trailing SL set at: ₹{self.trailing_sl_level:.2f}"
            )
            
            # Update database
            self.daily_stats_repo.update_daily_stats(
                trailing_sl_active=True,
                trailing_sl_level=self.trailing_sl_level
            )
            
            # Send notification
            if not self.activation_notification_sent:
                logger.info(f"Profit ₹{self.activation_threshold:.2f} reached - Trailing SL activated")
                if self.notification_service:
                    self.notification_service.notify_trailing_sl_activated(current_profit)
                self.activation_notification_sent = True
            
        except Exception as e:
            logger.error(f"Error activating trailing SL: {e}")
            raise
    
    def _update_trailing_sl_level(self, current_profit: float):
        """
        Update trailing SL level based on profit increments
        
        Logic:
        - Trailing SL moves up in increments of ₹10,000
        - Pattern: ₹5k → ₹10k → ₹20k → ₹30k → ₹40k...
        - Only moves up, never down
        
        Example:
        - Profit ₹5,000 → SL = ₹5,000
        - Profit ₹15,000 → SL = ₹10,000 (profit >= ₹10k)
        - Profit ₹28,000 → SL = ₹20,000 (profit >= ₹20k)
        """
        if not self.trailing_sl_active or self.trailing_sl_level is None:
            return
        
        # Calculate how many increments above activation threshold
        profit_above_threshold = current_profit - self.activation_threshold
        
        if profit_above_threshold < 0:
            # Profit dropped below activation threshold, but keep SL at activation level
            return
        
        # Calculate number of increments above activation threshold
        # increments = 0: profit < ₹10k → SL = ₹5k
        # increments = 1: profit >= ₹10k and < ₹20k → SL = ₹10k
        # increments = 2: profit >= ₹20k and < ₹30k → SL = ₹20k
        increments = int(profit_above_threshold / self.increment_amount)
        
        # Calculate new SL level based on increments
        # Pattern: ₹5k → ₹10k → ₹20k → ₹30k → ₹40k...
        if increments == 0:
            new_sl_level = self.activation_threshold  # ₹5k
        elif increments == 1:
            new_sl_level = self.activation_threshold + self.increment_amount  # ₹10k
        else:
            # For increments >= 2: ₹20k, ₹30k, ₹40k...
            # Formula: activation_threshold + (increments - 1) * increment_amount
            new_sl_level = self.activation_threshold + (increments - 1) * self.increment_amount
        
        # Only update if new level is higher (trailing SL only moves up)
        if new_sl_level > self.trailing_sl_level:
            old_level = self.trailing_sl_level
            self.trailing_sl_level = new_sl_level
            
            logger.info(
                f"Trailing SL updated: ₹{old_level:.2f} → ₹{new_sl_level:.2f} "
                f"(Current profit: ₹{current_profit:.2f})"
            )
            
            # Update database
            self.daily_stats_repo.update_daily_stats(
                trailing_sl_level=self.trailing_sl_level
            )
            
            # Send notification
            if self.notification_service:
                self.notification_service.notify_trailing_sl_updated(self.trailing_sl_level)
            logger.info(f"Trailing SL updated to ₹{self.trailing_sl_level:.2f}")
    
    def _handle_trailing_sl_trigger(self):
        """Handle trailing SL trigger - exit all positions"""
        try:
            total_profit = self.calculate_total_daily_profit()
            
            logger.critical(
                f"Trailing SL triggered! Profit dropped to ₹{total_profit:.2f}, "
                f"Trailing SL level: ₹{self.trailing_sl_level:.2f}. Exiting all positions..."
            )
            
            # Exit all positions
            order_ids = self.kite_client.square_off_all_positions()
            logger.info(f"Exited {len(order_ids)} positions due to trailing SL. Order IDs: {order_ids}")
            
            # Deactivate trailing SL
            self.trailing_sl_active = False
            self.trailing_sl_level = None
            
            # Update database
            self.daily_stats_repo.update_daily_stats(
                trailing_sl_active=False,
                trailing_sl_level=None
            )
            
            # Send notification
            if self.notification_service:
                self.notification_service.notify_trailing_sl_triggered()
            logger.critical("Trailing SL triggered - All positions closed")
            
        except Exception as e:
            logger.error(f"Error handling trailing SL trigger: {e}")
            raise TrailingSLTriggeredError(f"Failed to handle trailing SL trigger: {str(e)}")
    
    def reset_daily_trailing_sl(self):
        """Reset trailing SL for new trading day"""
        self.trailing_sl_active = False
        self.trailing_sl_level = None
        self.highest_profit = 0.0
        self.activation_notification_sent = False
        
        logger.info("Trailing SL reset for new trading day")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current trailing SL status"""
        total_profit = self.calculate_total_daily_profit()
        
        return {
            "total_profit": total_profit,
            "trailing_sl_active": self.trailing_sl_active,
            "trailing_sl_level": self.trailing_sl_level,
            "activation_threshold": self.activation_threshold,
            "increment_amount": self.increment_amount,
            "highest_profit": self.highest_profit
        }
    
    def set_notification_service(self, notification_service):
        """Set notification service"""
        self.notification_service = notification_service

