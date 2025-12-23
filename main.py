"""
Main Entry Point for Risk Management System
"""

import sys
import os
import time
from pathlib import Path
from src.config.config_manager import ConfigManager
from src.utils.logger import initialize_logger, get_logger
from src.database.models import DatabaseManager
from src.database.repository import (
    PositionRepository, DailyStatsRepository, TradeRepository
)
from src.api.kite_client import KiteClient
from src.risk_management.loss_protection import DailyLossProtection
from src.risk_management.trailing_stop_loss import TrailingStopLoss
from src.risk_management.profit_protection import ProfitProtection
from src.risk_management.trading_block_manager import TradingBlockManager
from src.risk_management.risk_monitor import RiskMonitor
from src.ui.dashboard import Dashboard
from src.utils.notifications import NotificationService
from src.security.access_control import AccessControl
from src.security.parameter_locker import ParameterLocker
from src.security.version_control import VersionControl
from src.api.websocket_client import WebSocketClient
from src.api.position_sync import PositionSync

def main():
    """Main application entry point"""
    try:
        # Initialize configuration
        config_manager = ConfigManager()
        
        # Create example configs if they don't exist
        if not (config_manager.user_config_path.exists() or 
                config_manager.admin_config_path.exists()):
            print("Configuration files not found. Creating examples...")
            config_manager.create_example_configs()
            print("\nPlease configure the files and run again.")
            return
        
        # Load configurations
        user_config, admin_config = config_manager.load_configs()
        
        # Initialize logging
        initialize_logger(log_level=user_config.log_level)
        logger = get_logger("app")
        logger.info("=" * 60)
        logger.info("Risk Management System Starting...")
        logger.info("=" * 60)
        
        # Initialize database
        db_manager = DatabaseManager()
        logger.info("Database initialized")
        
        # Initialize repositories
        position_repo = PositionRepository(db_manager)
        daily_stats_repo = DailyStatsRepository(db_manager)
        trade_repo = TradeRepository(db_manager)
        
        # Purge Day-1 trades on first startup of the day
        try:
            if not trade_repo.is_purge_done_for_today():
                deleted_count = trade_repo.purge_day_minus_one_trades()
                if deleted_count > 0:
                    logger.info(f"Daily purge completed: {deleted_count} Day-1 trades removed")
                else:
                    logger.info("Daily purge completed: No Day-1 trades found")
            else:
                logger.info("Daily purge already completed for today")
        except Exception as purge_error:
            logger.error(f"Error during daily purge: {purge_error}", exc_info=True)
            # Continue startup even if purge fails
        
        # Initialize Kite client
        kite_client = KiteClient(config_manager)
        logger.info("Kite client initialized")
        
        # Initialize risk management components
        trading_block_manager = TradingBlockManager(daily_stats_repo)
        loss_protection = DailyLossProtection(
            config_manager,
            kite_client,
            position_repo,
            daily_stats_repo,
            trade_repo
        )
        trailing_sl = TrailingStopLoss(
            config_manager,
            kite_client,
            position_repo,
            daily_stats_repo,
            trade_repo
        )
        
        # Initialize profit protection
        profit_protection = ProfitProtection(
            position_repo,
            trade_repo,
            daily_stats_repo,
            kite_client
        )
        
        # Initialize notification service
        notification_service = NotificationService(config_manager)
        
        # Initialize WebSocket client and position sync
        websocket_client = WebSocketClient(kite_client)
        position_sync = PositionSync(kite_client, position_repo)
        
        # Initialize risk monitor
        risk_monitor = RiskMonitor(
            loss_protection,
            trailing_sl,
            profit_protection,
            trading_block_manager,
            position_repo,
            daily_stats_repo,
            websocket_client=websocket_client,
            position_sync=position_sync
        )
        
        # Pass notification service to components
        loss_protection.set_notification_service(notification_service)
        trailing_sl.set_notification_service(notification_service)
        profit_protection.set_notification_service(notification_service)
        
        # Initialize security components
        access_control = AccessControl(db_manager)
        version_control = VersionControl(db_manager)
        parameter_locker = ParameterLocker(config_manager, access_control, version_control)
        
        # Get host and port from environment variables (for Azure/local flexibility)
        # Azure App Service sets PORT environment variable
        # Local development can use HOST and PORT env vars or defaults
        host = os.getenv("HOST", "127.0.0.1" if user_config.environment == "dev" else "0.0.0.0")
        port = int(os.getenv("PORT", "5000"))
        debug_mode = os.getenv("DEBUG", "false").lower() == "true" or (user_config.environment == "dev")
        
        # Initialize dashboard
        dashboard = Dashboard(
            risk_monitor,
            position_repo,
            trade_repo,
            access_control,
            parameter_locker,
            version_control,
            kite_client=kite_client,
            host=host,
            port=port,
            debug=debug_mode
        )
        
        logger.info("Risk management system initialized")
        logger.info(f"Daily loss limit: ₹{admin_config.daily_loss_limit:.2f}")
        logger.info(f"Trailing SL activation: ₹{admin_config.trailing_sl_activation:.2f}")
        logger.info(f"Trailing SL increment: ₹{admin_config.trailing_sl_increment:.2f}")
        logger.info(f"Environment: {user_config.environment}")
        
        # Check trading block status
        trading_block_manager.check_and_reset_block()
        if trading_block_manager.is_blocked():
            logger.warning("Trading is currently blocked")
        else:
            logger.info("Trading is active")
        
        # Start risk monitoring
        risk_monitor.start_monitoring()
        logger.info("Risk monitoring started")
        
        # Start dashboard in separate thread
        import threading
        dashboard_thread = threading.Thread(
            target=dashboard.run,
            daemon=True,
            name="Dashboard"
        )
        dashboard_thread.start()
        logger.info(f"Dashboard started at http://{host}:{port}")
        
        # TODO: Start WebSocket connection for real-time prices
        
        logger.info("System ready and monitoring...")
        logger.info(f"Dashboard: http://{host}:{port}")
        logger.info("Press Ctrl+C to stop")
        
        # Keep running
        try:
            while True:
                time.sleep(1)
                # Monitor status periodically
                status = risk_monitor.get_current_status()
                if status["monitoring_active"]:
                    # Log status every 60 seconds
                    import time as time_module
                    if int(time_module.time()) % 60 == 0:
                        logger.debug(f"Monitoring status: {status}")
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            risk_monitor.stop_monitoring()
            
    except KeyboardInterrupt:
        logger = get_logger("app")
        logger.info("Shutting down...")
        sys.exit(0)
    except Exception as e:
        logger = get_logger("app")
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

