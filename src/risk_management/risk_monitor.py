"""
Risk Monitor
Main monitoring loop that checks both loss protection and trailing SL
"""

import time
import threading
from datetime import datetime
from typing import Optional
from src.utils.logger import get_logger
from src.utils.date_utils import is_market_open, get_current_ist_time
from src.risk_management.loss_protection import DailyLossProtection
from src.risk_management.trailing_stop_loss import TrailingStopLoss
from src.risk_management.profit_protection import ProfitProtection
from src.risk_management.trading_block_manager import TradingBlockManager
from src.database.repository import PositionRepository, DailyStatsRepository, TradeRepository
from src.api.websocket_client import WebSocketClient
from src.api.position_sync import PositionSync
from src.utils.backup_manager import BackupManager
from src.risk_management.quantity_manager import QuantityManager

logger = get_logger("risk")


class RiskMonitor:
    """Main risk monitoring system that coordinates loss protection and trailing SL"""
    
    def __init__(
        self,
        loss_protection: DailyLossProtection,
        trailing_sl: TrailingStopLoss,
        profit_protection: ProfitProtection,
        trading_block_manager: TradingBlockManager,
        position_repo: PositionRepository,
        daily_stats_repo: DailyStatsRepository,
        websocket_client: Optional[WebSocketClient] = None,
        position_sync: Optional[PositionSync] = None,
        monitoring_interval: float = 1.0  # Check every 1 second
    ):
        self.loss_protection = loss_protection
        self.trailing_sl = trailing_sl
        self.profit_protection = profit_protection
        self.trading_block_manager = trading_block_manager
        self.position_repo = position_repo
        self.daily_stats_repo = daily_stats_repo
        self.websocket_client = websocket_client
        self.position_sync = position_sync
        
        self.monitoring_interval = monitoring_interval
        self.monitoring_active = False
        self.monitoring_thread: Optional[threading.Thread] = None
        # Initialize sync times using IST (timezone-naive for compatibility)
        ist_now = get_current_ist_time().replace(tzinfo=None)
        self.last_sync_time = ist_now
        self.sync_interval = 2  # Sync positions every 2 seconds
        self.last_backup_time = ist_now
        self.backup_interval = 30  # Backup every 30 seconds
        
        # Initialize backup manager
        self.backup_manager = BackupManager(position_repo)
        
        # Initialize quantity manager
        from src.database.repository import TradeRepository
        trade_repo = TradeRepository(position_repo.db_manager)
        self.quantity_manager = QuantityManager(position_repo, trade_repo)
    
    def start_monitoring(self):
        """Start the risk monitoring loop in a separate thread"""
        if self.monitoring_active:
            logger.warning("Monitoring is already active")
            return
        
        # Start WebSocket if available
        if self.websocket_client:
            self._setup_websocket()
        
        self.monitoring_active = True
        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="RiskMonitor"
        )
        self.monitoring_thread.start()
        logger.info("Risk monitoring started")
    
    def _setup_websocket(self):
        """Setup WebSocket connection and callbacks"""
        if not self.websocket_client:
            return
        
        def on_ticks(ticks):
            """Handle price ticks"""
            try:
                price_updates = {}
                for tick in ticks:
                    instrument_token = tick.get('instrument_token')
                    last_price = tick.get('last_price')
                    if instrument_token and last_price:
                        price_updates[instrument_token] = last_price
                
                if price_updates and self.position_sync:
                    self.position_sync.update_position_prices(price_updates)
            except Exception as e:
                logger.error(f"Error processing ticks: {e}")
        
        def on_connect():
            """Handle WebSocket connection"""
            logger.info("WebSocket connected, subscribing to positions")
            if self.websocket_client:
                self.websocket_client.subscribe_to_positions()
        
        def on_close(code, reason):
            """Handle WebSocket disconnection"""
            logger.warning(f"WebSocket disconnected: {code} - {reason}")
        
        def on_error(code, reason):
            """Handle WebSocket errors"""
            logger.error(f"WebSocket error: {code} - {reason}")
        
        self.websocket_client.set_callbacks(
            on_ticks=on_ticks,
            on_connect=on_connect,
            on_close=on_close,
            on_error=on_error
        )
        
        # Connect
        self.websocket_client.connect()
    
    def stop_monitoring(self):
        """Stop the risk monitoring loop"""
        self.monitoring_active = False
        
        # Disconnect WebSocket
        if self.websocket_client:
            self.websocket_client.disconnect()
        
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5.0)
        logger.info("Risk monitoring stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop that runs continuously"""
        logger.info("Risk monitoring loop started")
        
        # Track last hourly P&L update (using IST)
        ist_now = get_current_ist_time()
        last_hourly_update = ist_now.replace(minute=0, second=0, microsecond=0)
        # Track last pre-close update (at 15:00, 15:10, 15:15 IST)
        last_preclose_update = None
        
        while self.monitoring_active:
            try:
                # Check if market is open
                if not is_market_open():
                    time.sleep(60)  # Check every minute when market is closed
                    continue
                
                # Check trading block status
                self.trading_block_manager.check_and_reset_block()
                
                # Skip monitoring if trading is blocked
                if self.trading_block_manager.is_blocked():
                    time.sleep(self.monitoring_interval)
                    continue
                
                # Sync positions from API periodically
                ist_now = get_current_ist_time()
                if (ist_now.replace(tzinfo=None) - self.last_sync_time).total_seconds() >= self.sync_interval:
                    if self.position_sync:
                        self.position_sync.sync_positions_from_api()
                    
                    # Detect and handle quantity changes
                    quantity_changes = self.quantity_manager.detect_quantity_changes()
                    if quantity_changes:
                        logger.info(f"Detected {len(quantity_changes)} quantity changes")
                        for change in quantity_changes:
                            position = self.position_repo.get_position_by_id(change["position_id"])
                            if position:
                                self.quantity_manager.recalculate_risk_metrics(position)
                    
                    self.last_sync_time = ist_now.replace(tzinfo=None)
                
                # Create position snapshot backup periodically
                if (ist_now.replace(tzinfo=None) - self.last_backup_time).total_seconds() >= self.backup_interval:
                    snapshot = self.backup_manager.create_position_snapshot()
                    if snapshot:
                        self.backup_manager.save_snapshot(snapshot)
                        self.backup_manager.cleanup_old_snapshots(keep_last_n=100)
                    self.last_backup_time = ist_now.replace(tzinfo=None)
                
                # Detect and process trade completions (profit protection)
                completed_trades = self.profit_protection.detect_and_process_trade_completions()
                if completed_trades:
                    logger.info(f"Detected {len(completed_trades)} completed trades")
                    # Resubscribe to positions if WebSocket is active
                    if self.websocket_client and self.websocket_client.is_connected:
                        self.websocket_client.subscribe_to_positions()
                
                # Get protected profit for loss calculation
                protected_profit = self.profit_protection.get_protected_profit()
                
                # Check daily loss limit (applies only to current positions, not protected profit)
                loss_status = self.loss_protection.check_loss_limit(protected_profit)
                
                # Check trailing stop loss (only if loss limit not hit)
                if not loss_status.get("loss_limit_hit", False):
                    trailing_sl_status = self.trailing_sl.check_and_update_trailing_sl()
                    
                    # Update daily stats
                    self._update_daily_stats(protected_profit, loss_status, trailing_sl_status)
                else:
                    # Loss limit hit, update stats accordingly
                    self._update_daily_stats(protected_profit, loss_status, None)
                
                # Hourly P&L update - update every hour on the hour (IST)
                ist_now = get_current_ist_time()
                current_hour_ist = ist_now.replace(minute=0, second=0, microsecond=0)
                if current_hour_ist > last_hourly_update:
                    try:
                        from src.utils.daily_pnl_updater import update_daily_pnl_hourly
                        pnl_result = update_daily_pnl_hourly()
                        logger.info(
                            f"⏰ Hourly P&L Update (IST {ist_now.strftime('%H:%M')}): Total=Rs.{pnl_result['total_pnl']:,.2f} "
                            f"(Protected: Rs.{pnl_result['protected_profit']:,.2f}, "
                            f"Unrealized: Rs.{pnl_result['unrealized_pnl']:,.2f}, "
                            f"Open Positions: {pnl_result['open_positions']})"
                        )
                        last_hourly_update = current_hour_ist
                    except Exception as e:
                        logger.error(f"Error in hourly P&L update: {e}", exc_info=True)
                
                # Pre-market close P&L update (at 15:00, 15:10, 15:15 IST)
                current_time_ist = ist_now.time()
                if current_time_ist.hour == 15 and current_time_ist.minute in [0, 10, 15]:
                    update_key = f"{current_time_ist.hour}:{current_time_ist.minute}"
                    if last_preclose_update != update_key:
                        try:
                            from src.utils.daily_pnl_updater import update_daily_pnl_before_market_close
                            update_daily_pnl_before_market_close()
                            last_preclose_update = update_key
                        except Exception as e:
                            logger.error(f"Error in pre-close P&L update: {e}", exc_info=True)
                
                # Sleep for monitoring interval
                time.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                time.sleep(self.monitoring_interval)
    
    def _update_daily_stats(
        self,
        protected_profit: float,
        loss_status: dict,
        trailing_sl_status: Optional[dict]
    ):
        """Update daily statistics"""
        try:
            # Get P&L breakdown from profit protection
            pnl_breakdown = self.profit_protection.get_total_daily_pnl()
            
            # Get daily loss used (only from current positions, not protected profit)
            daily_loss = loss_status.get("daily_loss", 0.0)
            
            # Update stats
            self.daily_stats_repo.update_daily_stats(
                total_unrealized_pnl=pnl_breakdown["current_pnl"],
                protected_profit=pnl_breakdown["protected_profit"],
                daily_loss_used=daily_loss,
                loss_limit_hit=loss_status.get("loss_limit_hit", False),
                trading_blocked=loss_status.get("trading_blocked", False)
            )
            
            # Update trailing SL stats if available
            if trailing_sl_status:
                self.daily_stats_repo.update_daily_stats(
                    trailing_sl_active=trailing_sl_status.get("trailing_sl_active", False),
                    trailing_sl_level=trailing_sl_status.get("trailing_sl_level")
                )
        except Exception as e:
            logger.error(f"Error updating daily stats: {e}")
    
    def get_current_status(self) -> dict:
        """Get current risk monitoring status"""
        protected_profit = self.profit_protection.get_protected_profit()
        loss_status = self.loss_protection.check_loss_limit(protected_profit)
        trailing_sl_status = self.trailing_sl.get_status()
        profit_protection_status = self.profit_protection.get_status()
        
        return {
            "monitoring_active": self.monitoring_active,
            "loss_protection": loss_status,
            "trailing_sl": trailing_sl_status,
            "profit_protection": profit_protection_status,
            "trading_blocked": self.trading_block_manager.is_blocked(),
            "protected_profit": protected_profit,
            "current_pnl": profit_protection_status["current_positions_pnl"],
            "total_daily_pnl": profit_protection_status["total_daily_pnl"],
            "net_position_pnl": self.quantity_manager.get_net_position_pnl(),
            "booked_profit": self.quantity_manager.get_booked_profit()
        }

