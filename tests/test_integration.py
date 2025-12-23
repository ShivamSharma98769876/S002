"""
Integration Tests for Risk Management System
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date
from src.risk_management.risk_monitor import RiskMonitor
from src.risk_management.loss_protection import DailyLossProtection
from src.risk_management.trailing_stop_loss import TrailingStopLoss
from src.risk_management.profit_protection import ProfitProtection
from src.risk_management.trading_block_manager import TradingBlockManager
from src.database.repository import PositionRepository, DailyStatsRepository, TradeRepository
from src.database.models import Position, DatabaseManager


class TestIntegration(unittest.TestCase):
    """Integration tests for the complete risk management system"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_db_manager = Mock(spec=DatabaseManager)
        self.mock_position_repo = Mock(spec=PositionRepository)
        self.mock_trade_repo = Mock(spec=TradeRepository)
        self.mock_daily_stats_repo = Mock(spec=DailyStatsRepository)
        self.mock_kite_client = Mock()
        
        # Initialize components
        self.loss_protection = DailyLossProtection(
            daily_loss_limit=5000.0,
            kite_client=self.mock_kite_client,
            position_repo=self.mock_position_repo,
            trade_repo=self.mock_trade_repo,
            daily_stats_repo=self.mock_daily_stats_repo
        )
        
        self.trailing_sl = TrailingStopLoss(
            activation_threshold=5000.0,
            increment_amount=10000.0,
            kite_client=self.mock_kite_client,
            position_repo=self.mock_position_repo,
            trade_repo=self.mock_trade_repo,
            daily_stats_repo=self.mock_daily_stats_repo
        )
        
        self.profit_protection = ProfitProtection(
            position_repo=self.mock_position_repo,
            trade_repo=self.mock_trade_repo,
            kite_client=self.mock_kite_client
        )
        
        self.trading_block_manager = TradingBlockManager(self.mock_daily_stats_repo)
        
        self.risk_monitor = RiskMonitor(
            loss_protection=self.loss_protection,
            trailing_sl=self.trailing_sl,
            profit_protection=self.profit_protection,
            trading_block_manager=self.trading_block_manager,
            position_repo=self.mock_position_repo,
            daily_stats_repo=self.mock_daily_stats_repo
        )
    
    def test_loss_limit_auto_exit_integration(self):
        """Test complete flow: loss limit hit -> auto exit"""
        # Setup: positions with total loss exceeding limit
        positions = [
            Mock(unrealized_pnl=-3000.0, id=1, trading_symbol="NIFTY25JAN24000CE"),
            Mock(unrealized_pnl=-2500.0, id=2, trading_symbol="NIFTY25JAN24001CE")
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        self.mock_kite_client.square_off_all_positions.return_value = ["order1", "order2"]
        
        # Check loss limit
        status = self.loss_protection.check_loss_limit(protected_profit=0.0)
        
        # Verify
        self.assertTrue(status["loss_limit_hit"])
        self.assertTrue(status["trading_blocked"])
        self.mock_kite_client.square_off_all_positions.assert_called_once()
    
    def test_trailing_sl_activation_integration(self):
        """Test complete flow: profit reaches threshold -> trailing SL activated"""
        # Setup: positions with profit exceeding activation threshold
        positions = [
            Mock(unrealized_pnl=6000.0, id=1)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        # Check trailing SL
        status = self.trailing_sl.check_and_update_trailing_sl()
        
        # Verify
        self.assertTrue(status["trailing_sl_active"])
        self.assertEqual(status["trailing_sl_level"], 5000.0)
    
    def test_protected_profit_separation(self):
        """Test that protected profit is separate from current P&L"""
        # Setup: protected profit exists, but current positions are losing
        self.mock_trade_repo.get_protected_profit.return_value = 3000.0
        
        positions = [
            Mock(unrealized_pnl=-2000.0)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        # Calculate daily loss (should only count live positions)
        loss = self.loss_protection.calculate_daily_loss(protected_profit=3000.0)
        
        # Verify: loss should only be from live positions, not protected profit
        self.assertEqual(loss, 2000.0)
        # Protected profit should not affect loss calculation
    
    def test_multi_position_scenario(self):
        """Test handling multiple positions correctly"""
        positions = [
            Mock(unrealized_pnl=1000.0, id=1),
            Mock(unrealized_pnl=-500.0, id=2),
            Mock(unrealized_pnl=-2000.0, id=3),
            Mock(unrealized_pnl=750.0, id=4),
            Mock(unrealized_pnl=-1000.0, id=5)
        ]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        # Total loss: -500 - 2000 - 1000 = -3500 (within limit)
        loss = self.loss_protection.calculate_daily_loss()
        
        self.assertEqual(loss, 3500.0)
        
        # If loss exceeds limit, all positions should exit
        positions[4].unrealized_pnl = -3000.0  # Total loss now: -5500
        self.mock_kite_client.square_off_all_positions.return_value = ["order1", "order2", "order3", "order4", "order5"]
        
        status = self.loss_protection.check_loss_limit(protected_profit=0.0)
        
        self.assertTrue(status["loss_limit_hit"])
        self.assertEqual(self.mock_kite_client.square_off_all_positions.call_count, 1)


if __name__ == '__main__':
    unittest.main()

