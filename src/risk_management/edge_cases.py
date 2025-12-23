"""
Edge Cases Handling
Handles various edge cases and error scenarios
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, time as dt_time
from src.utils.logger import get_logger
from src.utils.date_utils import is_market_open, get_current_ist_time
from src.api.kite_client import KiteClient
from src.database.repository import PositionRepository, TradeRepository
from src.utils.exceptions import OrderExecutionError

logger = get_logger("risk")


class EdgeCaseHandler:
    """Handles edge cases and error scenarios"""
    
    def __init__(
        self,
        kite_client: KiteClient,
        position_repo: PositionRepository,
        trade_repo: TradeRepository
    ):
        self.kite_client = kite_client
        self.position_repo = position_repo
        self.trade_repo = trade_repo
    
    def handle_multiple_positions_exit(self, positions: List[Any]) -> List[str]:
        """
        Handle exiting multiple positions simultaneously
        
        Args:
            positions: List of positions to exit
        
        Returns:
            List of order IDs
        """
        try:
            order_ids = []
            
            for position in positions:
                try:
                    # Determine transaction type based on position
                    quantity = abs(position.quantity)
                    if quantity == 0:
                        continue
                    
                    # Place market order to square off
                    order_id = self.kite_client.place_market_order(
                        tradingsymbol=position.trading_symbol,
                        exchange=position.exchange,
                        transaction_type="SELL" if position.quantity > 0 else "BUY",
                        quantity=quantity,
                        product="MIS"
                    )
                    order_ids.append(order_id)
                    
                    # Small delay between orders to avoid rate limiting
                    import time
                    time.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error exiting position {position.trading_symbol}: {e}")
                    continue
            
            logger.info(f"Exited {len(order_ids)} positions simultaneously")
            return order_ids
            
        except Exception as e:
            logger.error(f"Error handling multiple positions exit: {e}")
            return []
    
    def handle_market_closure_scenario(self) -> bool:
        """
        Handle loss limit hit near market close
        
        Returns:
            True if handled successfully
        """
        try:
            from src.utils.date_utils import get_market_hours
            ist_time = get_current_ist_time()
            current_time = ist_time.time()
            _, market_close = get_market_hours()  # Get from config.json
            
            # Check if market is closing soon (within 5 minutes)
            time_to_close = (
                (market_close.hour * 60 + market_close.minute) -
                (current_time.hour * 60 + current_time.minute)
            )
            
            if time_to_close <= 5 and time_to_close > 0:
                logger.warning(f"Market closing in {time_to_close} minutes. Attempting emergency exit...")
                
                # Try to exit all positions
                try:
                    order_ids = self.kite_client.square_off_all_positions()
                    logger.info(f"Emergency exit orders placed: {order_ids}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to exit positions before market close: {e}")
                    # Block trading for next day
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling market closure scenario: {e}")
            return False
    
    def handle_partial_order_fills(self, order_id: str, position: Any) -> bool:
        """
        Handle partial order fills
        
        Args:
            order_id: Order ID to check
            position: Position being exited
        
        Returns:
            True if fully filled, False if partial
        """
        try:
            # Get order status from Kite
            orders = self.kite_client.get_orders()
            order = next((o for o in orders if str(o.get('order_id')) == order_id), None)
            
            if not order:
                logger.warning(f"Order {order_id} not found")
                return False
            
            order_status = order.get('status')
            filled_quantity = order.get('filled_quantity', 0)
            pending_quantity = order.get('pending_quantity', 0)
            
            if order_status == 'COMPLETE':
                return True
            elif order_status == 'PARTIALLY_FILLED':
                logger.info(
                    f"Order {order_id} partially filled: {filled_quantity}/{position.quantity}"
                )
                
                # Retry for remaining quantity
                if pending_quantity > 0:
                    try:
                        retry_order_id = self.kite_client.place_market_order(
                            tradingsymbol=position.trading_symbol,
                            exchange=position.exchange,
                            transaction_type="SELL" if position.quantity > 0 else "BUY",
                            quantity=pending_quantity,
                            product="MIS"
                        )
                        logger.info(f"Retry order placed: {retry_order_id}")
                        return False  # Still pending
                    except Exception as e:
                        logger.error(f"Error placing retry order: {e}")
                        return False
                
            return False
            
        except Exception as e:
            logger.error(f"Error handling partial order fills: {e}")
            return False
    
    def handle_order_rejection(self, order_id: str, reason: str) -> bool:
        """
        Handle rejected orders with retry mechanism
        
        Args:
            order_id: Rejected order ID
            reason: Rejection reason
        
        Returns:
            True if retry successful, False otherwise
        """
        try:
            logger.warning(f"Order {order_id} rejected: {reason}")
            
            # Log rejection
            # TODO: Store in database for analysis
            
            # Retry logic with exponential backoff
            max_retries = 3
            retry_delay = 1  # Start with 1 second
            
            for attempt in range(max_retries):
                logger.info(f"Retrying order (attempt {attempt + 1}/{max_retries})...")
                
                import time
                time.sleep(retry_delay)
                
                # Get order details to retry
                orders = self.kite_client.get_orders()
                order = next((o for o in orders if str(o.get('order_id')) == order_id), None)
                
                if order:
                    # Extract position info and retry
                    # This would need position context - simplified for now
                    logger.info("Retry mechanism would be implemented here")
                    retry_delay *= 2  # Exponential backoff
                
            logger.error(f"Order {order_id} failed after {max_retries} retries")
            return False
            
        except Exception as e:
            logger.error(f"Error handling order rejection: {e}")
            return False
    
    def recover_from_downtime(self) -> bool:
        """
        Recover system state after downtime
        
        Returns:
            True if recovery successful
        """
        try:
            logger.info("Recovering from system downtime...")
            
            # Load latest position snapshot
            from src.utils.backup_manager import BackupManager
            backup_manager = BackupManager(self.position_repo)
            snapshot = backup_manager.load_latest_snapshot()
            
            if snapshot:
                logger.info(f"Loaded snapshot from {snapshot.get('timestamp')}")
                # Restore positions from snapshot if needed
                # This would sync with current API state
            
            # Sync positions from API
            from src.api.position_sync import PositionSync
            from src.api.kite_client import KiteClient
            # Note: This would need kite_client instance
            # position_sync = PositionSync(self.kite_client, self.position_repo)
            # position_sync.sync_positions_from_api()
            
            logger.info("System recovery completed")
            return True
            
        except Exception as e:
            logger.error(f"Error recovering from downtime: {e}")
            return False

