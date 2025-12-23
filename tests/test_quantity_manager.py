"""
Unit Tests for Quantity Management
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime
from src.risk_management.quantity_manager import QuantityManager
from src.database.repository import PositionRepository, TradeRepository
from src.database.models import Position


class TestQuantityManager(unittest.TestCase):
    """Test cases for Quantity Manager"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_position_repo = Mock(spec=PositionRepository)
        self.mock_trade_repo = Mock(spec=TradeRepository)
        
        self.quantity_manager = QuantityManager(
            position_repo=self.mock_position_repo,
            trade_repo=self.mock_trade_repo
        )
    
    def test_detect_quantity_changes_no_changes(self):
        """Test quantity change detection with no changes"""
        positions = [
            Mock(id=1, quantity=10, trading_symbol="NIFTY25JAN24000CE")
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        # First call initializes history
        changes1 = self.quantity_manager.detect_quantity_changes()
        self.assertEqual(len(changes1), 0)
        
        # Second call with same quantity should detect no change
        changes2 = self.quantity_manager.detect_quantity_changes()
        self.assertEqual(len(changes2), 0)
    
    def test_detect_quantity_increase(self):
        """Test quantity increase detection"""
        position = Mock(id=1, quantity=15, trading_symbol="NIFTY25JAN24000CE", exchange="NFO")
        self.mock_position_repo.get_active_positions.return_value = [position]
        
        # Initialize history
        self.quantity_manager.quantity_history[1] = [{
            "timestamp": datetime.utcnow(),
            "quantity": 10
        }]
        
        changes = self.quantity_manager.detect_quantity_changes()
        
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["old_quantity"], 10)
        self.assertEqual(changes[0]["new_quantity"], 15)
        self.assertEqual(changes[0]["change"], 5)
        self.assertEqual(changes[0]["change_type"], "increase")
    
    def test_detect_quantity_decrease(self):
        """Test quantity decrease detection"""
        position = Mock(id=1, quantity=5, trading_symbol="NIFTY25JAN24000CE", exchange="NFO")
        self.mock_position_repo.get_active_positions.return_value = [position]
        
        # Initialize history
        self.quantity_manager.quantity_history[1] = [{
            "timestamp": datetime.utcnow(),
            "quantity": 10
        }]
        
        changes = self.quantity_manager.detect_quantity_changes()
        
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["old_quantity"], 10)
        self.assertEqual(changes[0]["new_quantity"], 5)
        self.assertEqual(changes[0]["change"], -5)
        self.assertEqual(changes[0]["change_type"], "decrease")
    
    def test_recalculate_risk_metrics(self):
        """Test risk metrics recalculation"""
        position = Mock(
            id=1,
            quantity=10,
            current_price=150.0,
            entry_price=100.0,
            lot_size=1
        )
        
        updated_position = Mock(
            id=1,
            quantity=10,
            current_price=150.0,
            entry_price=100.0,
            lot_size=1,
            unrealized_pnl=500.0
        )
        
        self.mock_position_repo.update_position_pnl.return_value = updated_position
        self.mock_position_repo.get_position_by_id.return_value = updated_position
        
        metrics = self.quantity_manager.recalculate_risk_metrics(position)
        
        self.assertEqual(metrics["unrealized_pnl"], 500.0)
        self.assertEqual(metrics["quantity"], 10)
        self.assertEqual(metrics["current_price"], 150.0)
        self.assertEqual(metrics["entry_price"], 100.0)
        self.mock_position_repo.update_position_pnl.assert_called_once_with(1, 150.0)
    
    def test_get_net_position_pnl(self):
        """Test net position P&L calculation"""
        positions = [
            Mock(unrealized_pnl=1000.0),
            Mock(unrealized_pnl=-500.0),
            Mock(unrealized_pnl=750.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        net_pnl = self.quantity_manager.get_net_position_pnl()
        
        self.assertEqual(net_pnl, 1250.0)  # 1000 - 500 + 750
    
    def test_get_booked_profit(self):
        """Test booked profit calculation"""
        from datetime import date
        from src.database.models import Trade
        
        trades = [
            Mock(realized_pnl=1000.0, is_profit=True),
            Mock(realized_pnl=-500.0, is_profit=False),
            Mock(realized_pnl=750.0, is_profit=True)
        ]
        self.mock_trade_repo.get_trades_by_date.return_value = trades
        
        booked_profit = self.quantity_manager.get_booked_profit()
        
        self.assertEqual(booked_profit, 1750.0)  # Only profitable trades
    
    def test_get_quantity_history(self):
        """Test quantity history retrieval"""
        position_id = 1
        history = [
            {"timestamp": datetime.utcnow(), "quantity": 10},
            {"timestamp": datetime.utcnow(), "quantity": 15}
        ]
        self.quantity_manager.quantity_history[position_id] = history
        
        retrieved_history = self.quantity_manager.get_quantity_history(position_id)
        
        self.assertEqual(len(retrieved_history), 2)
        self.assertEqual(retrieved_history[0]["quantity"], 10)
        self.assertEqual(retrieved_history[1]["quantity"], 15)


if __name__ == '__main__':
    unittest.main()

