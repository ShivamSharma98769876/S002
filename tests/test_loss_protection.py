"""
Unit Tests for Daily Loss Protection
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date
from src.risk_management.loss_protection import DailyLossProtection
from src.database.repository import PositionRepository, TradeRepository, DailyStatsRepository
from src.api.kite_client import KiteClient
from src.database.models import Position, DatabaseManager


class TestDailyLossProtection(unittest.TestCase):
    """Test cases for Daily Loss Protection"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_db_manager = Mock(spec=DatabaseManager)
        self.mock_position_repo = Mock(spec=PositionRepository)
        self.mock_trade_repo = Mock(spec=TradeRepository)
        self.mock_daily_stats_repo = Mock(spec=DailyStatsRepository)
        self.mock_kite_client = Mock(spec=KiteClient)
        
        self.loss_protection = DailyLossProtection(
            daily_loss_limit=5000.0,
            kite_client=self.mock_kite_client,
            position_repo=self.mock_position_repo,
            trade_repo=self.mock_trade_repo,
            daily_stats_repo=self.mock_daily_stats_repo
        )
    
    def test_calculate_daily_loss_no_positions(self):
        """Test daily loss calculation with no positions"""
        self.mock_position_repo.get_active_positions.return_value = []
        
        loss = self.loss_protection.calculate_daily_loss()
        
        self.assertEqual(loss, 0.0)
    
    def test_calculate_daily_loss_profitable_positions(self):
        """Test daily loss calculation with profitable positions"""
        positions = [
            Mock(unrealized_pnl=1000.0),
            Mock(unrealized_pnl=500.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        loss = self.loss_protection.calculate_daily_loss()
        
        self.assertEqual(loss, 0.0)  # No loss, only profit
    
    def test_calculate_daily_loss_losing_positions(self):
        """Test daily loss calculation with losing positions"""
        positions = [
            Mock(unrealized_pnl=-2000.0),
            Mock(unrealized_pnl=-1500.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        loss = self.loss_protection.calculate_daily_loss()
        
        self.assertEqual(loss, 3500.0)  # Total loss
    
    def test_calculate_daily_loss_mixed_positions(self):
        """Test daily loss calculation with mixed positions"""
        positions = [
            Mock(unrealized_pnl=-2000.0),
            Mock(unrealized_pnl=1000.0),
            Mock(unrealized_pnl=-1500.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        loss = self.loss_protection.calculate_daily_loss()
        
        self.assertEqual(loss, 2500.0)  # Only losses count
    
    def test_check_loss_limit_not_breached(self):
        """Test loss limit check when not breached"""
        positions = [
            Mock(unrealized_pnl=-2000.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        status = self.loss_protection.check_loss_limit(protected_profit=0.0)
        
        self.assertFalse(status["loss_limit_hit"])
        self.assertFalse(status["trading_blocked"])
        self.assertEqual(status["daily_loss"], 2000.0)
    
    def test_check_loss_limit_breached(self):
        """Test loss limit check when breached"""
        positions = [
            Mock(unrealized_pnl=-3000.0),
            Mock(unrealized_pnl=-2500.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        self.mock_kite_client.square_off_all_positions.return_value = ["order1", "order2"]
        
        status = self.loss_protection.check_loss_limit(protected_profit=0.0)
        
        self.assertTrue(status["loss_limit_hit"])
        self.assertTrue(status["trading_blocked"])
        self.assertEqual(status["daily_loss"], 5500.0)
        self.mock_kite_client.square_off_all_positions.assert_called_once()
    
    def test_protected_profit_not_included_in_loss(self):
        """Test that protected profit is not included in loss calculation"""
        positions = [
            Mock(unrealized_pnl=-2000.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        # Even with protected profit, loss should only count live positions
        loss = self.loss_protection.calculate_daily_loss(protected_profit=10000.0)
        
        self.assertEqual(loss, 2000.0)  # Only live position loss
    
    def test_loss_warning_threshold(self):
        """Test loss warning when approaching limit"""
        positions = [
            Mock(unrealized_pnl=-4000.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        # Set warning threshold to 80%
        self.loss_protection.loss_warning_threshold = 0.8
        
        status = self.loss_protection.check_loss_limit(protected_profit=0.0)
        
        # Should trigger warning (4000 / 5000 = 80%)
        self.assertFalse(status["loss_limit_hit"])  # Not yet breached
        self.assertEqual(status["daily_loss"], 4000.0)


if __name__ == '__main__':
    unittest.main()

