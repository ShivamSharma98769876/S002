"""
Performance Tests for Risk Management System
"""

import unittest
import time
from unittest.mock import Mock, patch
from src.risk_management.loss_protection import DailyLossProtection
from src.risk_management.trailing_stop_loss import TrailingStopLoss
from src.database.repository import PositionRepository, TradeRepository, DailyStatsRepository
from src.api.kite_client import KiteClient


class TestPerformance(unittest.TestCase):
    """Performance tests for risk management system"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_db_manager = Mock()
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
    
    def test_loss_calculation_performance(self):
        """Test loss calculation performance with many positions"""
        # Create 100 mock positions
        positions = [Mock(unrealized_pnl=-50.0) for _ in range(100)]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        start_time = time.time()
        loss = self.loss_protection.calculate_daily_loss()
        elapsed_time = time.time() - start_time
        
        # Should complete in less than 0.1 seconds
        self.assertLess(elapsed_time, 0.1)
        self.assertEqual(loss, 5000.0)  # 100 * 50
    
    def test_trailing_sl_check_performance(self):
        """Test trailing SL check performance"""
        positions = [Mock(unrealized_pnl=6000.0) for _ in range(50)]
        self.mock_position_repo.get_active_positions.return_value = positions
        
        trailing_sl = TrailingStopLoss(
            activation_threshold=5000.0,
            increment_amount=10000.0,
            kite_client=self.mock_kite_client,
            position_repo=self.mock_position_repo,
            trade_repo=self.mock_trade_repo,
            daily_stats_repo=self.mock_daily_stats_repo
        )
        
        start_time = time.time()
        status = trailing_sl.check_and_update_trailing_sl()
        elapsed_time = time.time() - start_time
        
        # Should complete in less than 0.1 seconds
        self.assertLess(elapsed_time, 0.1)
    
    def test_auto_exit_performance(self):
        """Test auto-exit performance (should be fast)"""
        positions = [Mock(unrealized_pnl=-100.0) for _ in range(20)]
        self.mock_position_repo.get_active_positions.return_value = positions
        self.mock_kite_client.square_off_all_positions.return_value = ["order"] * 20
        
        # Simulate loss limit breach
        start_time = time.time()
        status = self.loss_protection.check_loss_limit(protected_profit=0.0)
        elapsed_time = time.time() - start_time
        
        # Critical operation should complete quickly
        # Note: Actual API calls would add latency, but logic should be fast
        self.assertLess(elapsed_time, 0.5)  # Allow some margin for mocks


if __name__ == '__main__':
    unittest.main()

