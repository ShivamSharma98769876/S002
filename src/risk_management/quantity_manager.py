"""
Quantity Management
Handles dynamic position quantity changes and risk recalculation
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from src.utils.logger import get_logger
from src.database.repository import PositionRepository, TradeRepository
from src.database.models import Position

logger = get_logger("risk")


class QuantityManager:
    """Manages position quantity changes and risk recalculation"""
    
    def __init__(
        self,
        position_repo: PositionRepository,
        trade_repo: TradeRepository
    ):
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.quantity_history: Dict[int, List[Dict[str, Any]]] = {}  # position_id -> history
    
    def detect_quantity_changes(self) -> List[Dict[str, Any]]:
        """
        Detect quantity changes in positions
        
        Returns:
            List of positions with quantity changes
        """
        try:
            active_positions = self.position_repo.get_active_positions()
            changes = []
            
            for position in active_positions:
                # Initialize history if first time seeing this position
                if position.id not in self.quantity_history:
                    self.quantity_history[position.id] = [{
                        "timestamp": datetime.utcnow(),
                        "quantity": position.quantity
                    }]
                else:
                    # Check if quantity changed
                    last_quantity = self.quantity_history[position.id][-1]["quantity"]
                    if position.quantity != last_quantity:
                        change = {
                            "position_id": position.id,
                            "trading_symbol": position.trading_symbol,
                            "exchange": position.exchange,
                            "old_quantity": last_quantity,
                            "new_quantity": position.quantity,
                            "change": position.quantity - last_quantity,
                            "change_type": "increase" if position.quantity > last_quantity else "decrease",
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        changes.append(change)
                        
                        # Update history
                        self.quantity_history[position.id].append({
                            "timestamp": datetime.utcnow(),
                            "quantity": position.quantity
                        })
                        
                        logger.info(
                            f"Quantity change detected: {position.trading_symbol} "
                            f"{last_quantity} -> {position.quantity} "
                            f"({change['change_type']})"
                        )
            
            return changes
            
        except Exception as e:
            logger.error(f"Error detecting quantity changes: {e}")
            return []
    
    def recalculate_risk_metrics(self, position: Position) -> Dict[str, float]:
        """
        Recalculate risk metrics when quantity changes
        
        Args:
            position: Position with changed quantity
        
        Returns:
            Updated risk metrics
        """
        try:
            # Recalculate P&L with new quantity
            if position.current_price:
                self.position_repo.update_position_pnl(position.id, position.current_price)
            
            # Get updated position
            updated_position = self.position_repo.get_position_by_id(position.id)
            
            if not updated_position:
                return {}
            
            # Calculate updated metrics
            metrics = {
                "unrealized_pnl": updated_position.unrealized_pnl,
                "quantity": updated_position.quantity,
                "current_price": updated_position.current_price,
                "entry_price": updated_position.entry_price,
                "total_value": updated_position.current_price * updated_position.quantity * updated_position.lot_size,
                "net_position_pnl": self.get_net_position_pnl()
            }
            
            logger.info(
                f"Risk metrics recalculated for {updated_position.trading_symbol}: "
                f"P&L={metrics['unrealized_pnl']:.2f}, Qty={metrics['quantity']}"
            )
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error recalculating risk metrics: {e}")
            return {}
    
    def get_quantity_history(self, position_id: int) -> List[Dict[str, Any]]:
        """Get quantity change history for a position"""
        return self.quantity_history.get(position_id, [])
    
    def get_net_position_pnl(self) -> float:
        """Calculate net P&L for all live positions combined"""
        try:
            active_positions = self.position_repo.get_active_positions()
            total_pnl = sum(pos.unrealized_pnl for pos in active_positions)
            return total_pnl
        except Exception as e:
            logger.error(f"Error calculating net position P&L: {e}")
            return 0.0
    
    def get_booked_profit(self, trade_date: Optional[datetime.date] = None) -> float:
        """
        Get booked profit from past trades
        
        Args:
            trade_date: Optional date filter (defaults to today)
        
        Returns:
            Total booked profit
        """
        try:
            if trade_date is None:
                trade_date = datetime.now().date()
            
            # Get all profitable trades for the date
            trades = self.trade_repo.get_trades_by_date(trade_date)
            booked_profit = sum(
                trade.realized_pnl for trade in trades
                if trade.is_profit and trade.realized_pnl > 0
            )
            
            return booked_profit
            
        except Exception as e:
            logger.error(f"Error getting booked profit: {e}")
            return 0.0

